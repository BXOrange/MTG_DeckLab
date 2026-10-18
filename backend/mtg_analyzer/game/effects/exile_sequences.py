"""Exile → intervening instructions → exact return → successful-return riders.

Timing, recipients, entry options and instruction bodies are independent axes.
Captured values live in ordinary effect objects, so the existing resolution
and entry continuations own suspension, cloning and undo.
"""
from .core import GameEffect, _controller_of, _apply_effects_partitioned
from .composition import _build
from ..targeting import TargetSpec
from ...models.game.game_object import GameObject, Zone
from ...models.game.game_state import DelayedTrigger


class _SuccessfulReturnEffect(GameEffect):
    def __init__(self, effects, source=None):
        super().__init__(source)
        self.effects = effects

    def apply(self, context, targets=None):
        if targets:
            # RULE 608.2h: measurements in this body see the new permanent,
            # after entry choices and continuous effects, rather than its LKI.
            context.recompute()
            _apply_effects_partitioned(self.effects, context, targets, None,
                                      source=self.source, previous_targets=targets)


class _ReturnPhaseEffect(GameEffect):
    def __init__(self, effect, player_id, step, scope, source=None):
        super().__init__(source)
        self.effect, self.player_id = effect, player_id
        self.step, self.scope = step, scope

    def apply(self, context, targets=None):
        if self.step:
            context.state.delayed_triggers.append(DelayedTrigger(
                self.player_id, self.step, [self.effect], scope=self.scope))
        else:
            outer = context.resolving_controller_id
            context.resolving_controller_id = self.player_id
            try:
                self.effect.apply(context)
            finally:
                context.resolving_controller_id = outer


def _copy_departing(context, source, captured_card, owner_id, player_id, params, visits):
    from ..copy_mechanics import become_copy
    from ..combat import matches_object_filter

    if params.get('requires_exile') and not visits:
        return
    recipients = params.get('recipients', 'self')
    if recipients == 'self':
        expected = context.resolving_source_incarnation
        objects = [source] if (source is not None and source.zone == Zone.BATTLEFIELD
            and (expected is None or source.zone_incarnation == expected)) else []
    elif recipients == 'you_control':
        context.recompute()
        objects = [obj for obj in context.state.permanents_controlled_by(player_id)
                   if matches_object_filter(obj, params.get('filter') or {},
                                            reference=source, state=context.state)]
    else:
        raise ValueError('Unknown departing-copy recipients')
    # RULE 707.2 / 611.2c: one frozen copiable face and one fixed recipient
    # set; later objects never join it, and a controller change doesn't end it.
    proxy = GameObject(captured_card, owner_id=owner_id, zone=Zone.BATTLEFIELD)
    for obj in objects:
        become_copy(obj, proxy, duration=params.get('duration'))


class BlinkEffect(GameEffect):
    """Compose one exile/return instruction from independent data axes.

    Numeric LKI belongs in an outer ``bind``; ``departing_copy`` freezes
    copiable values. Intervening effects finish before the return is armed.
    Entry options and successful-return bodies reuse the shared entry batch.
    """
    def __init__(self, target=None, source=None, target_kind='creature_you_control',
                 under_your_control=False, creature_filter=None, optional=False,
                 count=1, count_max=None, trigger_event_key=None, tapped=False,
                 attacking=False, entry_counters=None, typed_entry_counters=None,
                 transformed=False, face_down_kind=None, return_step=None,
                 return_scope='any', return_effects=None, tapped_if_types=None,
                 subject='targets', exile_effects=None, departing_copy=None,
                 return_if_successful=False, return_to_battlefield=True):
        super().__init__(source)
        if subject not in {'targets', 'source', 'previous_targets', 'event_visits'}:
            raise ValueError('Unknown blink subject')
        self.target, self.subject = target, subject
        self.creature_filter = creature_filter
        self._trigger_subject_mode = target_kind == 'trigger_subject'
        self.trigger_event_key = trigger_event_key or 'instance_id'
        self.target_spec = TargetSpec(kind=target_kind, creature_filter=creature_filter,
            optional=optional, count=count, count_max=count_max) if (
                subject == 'targets' and not self._trigger_subject_mode) else None
        self.under_your_control = under_your_control
        options = dict(tapped=tapped, attacking=attacking,
            entry_counters=entry_counters, typed_entry_counters=typed_entry_counters,
            transformed=transformed, face_down_kind=face_down_kind,
            tapped_if_types=tapped_if_types or [])
        for name, value in options.items():
            setattr(self, name, value)
        self.return_step, self.return_scope = return_step, return_scope
        self.return_effects = list(return_effects or [])
        self.exile_effects = list(exile_effects or [])
        self.departing_copy = dict(departing_copy or {})
        self.return_if_successful = return_if_successful
        self.return_to_battlefield = return_to_battlefield
        self.returned_objects = []

    @property
    def entry_options(self):
        return {name: getattr(self, name) for name in (
            'tapped', 'attacking', 'entry_counters', 'typed_entry_counters',
            'transformed', 'face_down_kind', 'tapped_if_types')}

    def apply(self, context, targets=None):
        from .choices_actions import ReturnSpecificToBattlefieldEffect
        from .flicker_composites import _exile_batch

        player = _controller_of(self.source, context)
        if self.subject == 'source':
            expected = context.resolving_source_incarnation
            chosen = [self.source] if (self.source is not None
                and (expected is None or self.source.zone_incarnation == expected)) else []
        elif self.subject == 'previous_targets':
            chosen = list(context.previous_targets)
        elif self.subject == 'event_visits':
            from ..combat import matches_object_filter
            context.recompute()
            chosen = []
            for instance_id, incarnation in (context.trigger_event or {}).get(self.trigger_event_key, []):
                obj = context.state.find_object(instance_id)
                if (obj is not None and obj.zone_incarnation == incarnation
                        and matches_object_filter(obj, self.creature_filter,
                            reference=self.source, state=context.state)):
                    chosen.append(obj)
        elif self._trigger_subject_mode:
            obj = context.state.find_object((context.trigger_event or {}).get(self.trigger_event_key))
            chosen = [obj] if obj is not None else []
        else:
            chosen = list(targets or ([self.target] if self.target is not None else []))
        chosen = [obj for obj in chosen if obj.zone == Zone.BATTLEFIELD]
        if not chosen:
            return
        # Capture before exile restores a copied/transformed physical card.
        captured = chosen[0].card.as_copy() if self.departing_copy else None
        owner_id = chosen[0].owner_id
        intervening = _build(self.exile_effects, self.source)
        effects = _build(self.return_effects, self.source)
        for obj in chosen:
            context.engine._detach_attachments_from(obj)
        visits = _exile_batch(context, chosen)
        if self.departing_copy:
            _copy_departing(context, self.source, captured, owner_id, player.id, self.departing_copy, visits)
        objects = [obj for iid, incarnation in visits
                   if (obj := context.state.find_object(iid)) is not None
                   and obj.zone == Zone.EXILE and obj.zone_incarnation == incarnation]
        if not self.return_to_battlefield:
            # RULE 400.7h: an exile-phase grant applies only to the cards
            # actually moved by this instruction. Future return choices
            # belong to that grant, not an unconditional blink return.
            if objects:
                _apply_effects_partitioned(intervening, context, objects, None,
                                          source=self.source, previous_targets=objects)
            return
        returned = ReturnSpecificToBattlefieldEffect(objects, source=self.source,
            under_your_control=self.under_your_control, **self.entry_options)
        if self.return_if_successful:
            effects = [_SuccessfulReturnEffect(effects, self.source)]
        # Entry batches own the successful-return continuation. Keeping the
        # already-built body also preserves measurements across delayed firing.
        returned.after_effects = effects
        phase = _ReturnPhaseEffect(returned, player.id, self.return_step, self.return_scope, self.source)
        _apply_effects_partitioned([*intervening, phase],
                                  context, [], None, source=self.source)
        self.returned_objects = returned.returned_objects
