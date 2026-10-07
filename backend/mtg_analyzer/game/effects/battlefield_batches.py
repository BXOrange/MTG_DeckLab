"""Prepare entry choices, then put a group of permanents onto the field together."""
from __future__ import annotations

from ...models.game.events import EventType, GameEvent
from .core import GameEffect, _controller_of, ChooseColorReplacement


def start_battlefield_batch(rules, objects, controller_id, *, tapped=False):
    frame = {'cards': [{'id': o.instance_id, 'from_zone': o.zone.value,
                        'controller_id': controller_id or o.owner_id,
                        'tapped': tapped} for o in objects],
             'cursor': 0, 'stage': 'reset'}
    advance_battlefield_batch(rules, frame)


def _current(rules, frame):
    record = frame['cards'][frame['cursor']]
    return rules.state.find_object(record['id']), record


def restore_batch_runtime(rules, choice):
    """Rebuild the current entry chooser from identities after a state restore.

    Ordinary entry handlers still apply their existing semantics. The batch
    never depends on a Python closure surviving a session rewind.
    """
    frame = choice['battlefield_batch']
    obj, record = _current(rules, frame)
    kind = choice['kind']
    if kind == 'enter_as_copy':
        rules._pending_enter_as_copy_obj = obj
        rules._pending_enter_as_copy_effect = obj.enter_as_copy_effects[0]
        rules._pending_enter_as_copy_continuation = lambda: None
        frame['stage'] = 'protector'
    elif frame['stage'] == 'choose':
        effect = obj.enter_choice_effects[0]
        remaining = obj.enter_choice_effects[1:]
        if isinstance(effect, ChooseColorReplacement) and effect.count > 1:
            remaining = [ChooseColorReplacement(count=effect.count - 1), *remaining]
        rules._pending_enter_choice_obj = obj
        rules._pending_enter_choice_effect = effect
        rules._pending_enter_choice_continuation = lambda: setattr(obj, 'enter_choice_effects', remaining)
    elif kind == 'choose_protector':
        rules._pending_protector_obj = obj
        rules._pending_protector_continuation = lambda: None
        frame['stage'] = 'choose'
    elif kind == 'read_ahead':
        rules._pending_read_ahead_obj = obj
        rules._pending_read_ahead_continuation = lambda: None
        frame['stage'] = 'read_answered'


def resume_battlefield_batch(rules, choice):
    frame = choice['battlefield_batch']
    if rules.state.pending_choice:
        rules.state.pending_choice.setdefault('battlefield_batch', frame)
        return
    if frame['stage'] == 'read_answered':
        frame['cards'][frame['cursor']]['lore'] = rules._pending_read_ahead_count
        rules._pending_read_ahead_count = None
        frame['stage'] = 'tap'
    if frame['stage'] == 'tap_wait':
        frame['stage'] = 'ready'
    advance_battlefield_batch(rules, frame)


def advance_battlefield_batch(rules, frame):
    while frame['cursor'] < len(frame['cards']):
        obj, record = _current(rules, frame)
        if obj is None:
            frame['cursor'] += 1
            frame['stage'] = 'reset'
            continue
        stage = frame['stage']
        if stage == 'reset':
            obj.reset_as_new_object()
            obj.controller_id = record['controller_id']
            frame['stage'] = 'copy'
        elif stage == 'copy':
            if obj.enter_as_copy_effects:
                rules._offer_enter_as_copy(obj, lambda: None)
            if not rules.state.pending_choice:
                frame['stage'] = 'protector'
        elif stage == 'protector':
            rules._offer_protector_choice(obj, lambda: None)
            if not rules.state.pending_choice:
                frame['stage'] = 'choose'
        elif stage == 'choose':
            rules._offer_enter_choices(obj, lambda: None)
            if not rules.state.pending_choice:
                frame['stage'] = 'read'
        elif stage == 'read':
            rules._offer_read_ahead(obj, lambda: None)
            if not rules.state.pending_choice:
                frame['stage'] = 'tap'
        elif stage == 'tap':
            if record.get('tapped'):
                obj.tapped = True
            else:
                rules.enter_land_tapped(obj)
            frame['stage'] = 'tap_wait' if rules.state.pending_choice else 'ready'
        elif stage == 'ready':
            frame['cursor'] += 1
            frame['stage'] = 'reset'
        if rules.state.pending_choice:
            rules.state.pending_choice['battlefield_batch'] = frame
            return
    _commit_battlefield_batch(rules, frame)


def _commit_battlefield_batch(rules, frame):
    from .. import continuous
    state = rules.state
    entrants = [(state.find_object(r['id']), r) for r in frame['cards']]
    entrants = [(obj, r) for obj, r in entrants if obj is not None]
    # RULE 614.12: prepare all entry replacements before any entrant is a
    # battlefield source for the other entrants' replacement effects.
    for obj, record in entrants:
        rules._apply_entry_counters(obj)
        rules._apply_granted_entry_counters(obj)
        obj.summoning_sick = True
    buffered = []
    state._deferred_entry_events = buffered
    try:
        with state.simultaneous():
            for obj, record in entrants:
                rules._remove_from_current_zone(state.player_by_id(obj.owner_id), obj)
                state.add_to_battlefield(obj, saga_lore_override=record.get('lore'))
                state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,
                    from_zone=record['from_zone'], controller_id=obj.controller_id,
                    object=obj.name, instance_id=obj.instance_id, object_types=sorted(obj.type_words)))
            continuous.recompute(state)
            state._deferred_entry_events = None
            for event in buffered:
                if event.type == EventType.ENTERS_BATTLEFIELD:
                    obj = state.find_object(event.get('instance_id'))
                    event.data['object_types'] = sorted(obj.type_words)
                state.fire_event(event)
    finally:
        state._deferred_entry_events = None


class BattlefieldBatchEffect(GameEffect):
    """Internal runtime step: immutable identities of revealed/selected cards."""
    def __init__(self, ids, controller_id, source=None):
        super().__init__(source)
        self.ids, self.controller_id = list(ids), controller_id

    def apply(self, context, targets=None):
        objects = [o for iid in self.ids if (o := context.state.find_object(iid)) is not None]
        start_battlefield_batch(context.engine, objects, self.controller_id)
