"""Resolution windows, player restrictions, and linked permanent sequences."""
from __future__ import annotations

from ..targeting import TargetSpec
from .core import EffectRegistry, GameEffect, _apply_effects_partitioned
from .counters_tokens import GrantUntilEffect


class RestrictTargetPlayerThisTurnEffect(GameEffect):
    """RULE 611.2: fix the player when the targeted spell resolves."""

    def __init__(self, spell_types=None, activations=False, source=None):
        super().__init__(source)
        self.spell_types = spell_types
        self.activations = activations
        self.target_spec = TargetSpec(kind='player')

    def apply(self, context, targets=None):
        if not targets:
            return
        params = {'scope': 'all', 'player_id': targets[0].id}
        if self.spell_types:
            params['spell_types'] = list(self.spell_types)
        payloads = [{'type': 'cast_prohibition', 'params': params}]
        if self.activations:
            payloads.append({'type': 'activation_prohibition', 'params': {
                'player_id': targets[0].id, 'except_mana_abilities': True}})
        GrantUntilEffect(static=payloads[0], extra_statics=payloads[1:],
                         duration='end_of_turn', target_kind=None, source=self.source).apply(context)


class SacrificeSourceThenEffect(GameEffect):
    """RULE 118.12: the rider requires a successful sacrifice of this source."""

    def __init__(self, then_specs=None, source=None):
        super().__init__(source)
        self.then_specs = list(then_specs or [])

    def apply(self, context, targets=None):
        from .core import _controller_of
        player = _controller_of(self.source, context)
        if (self.source not in context.state.permanents() or player is None
                or self.source.controller_id != player.id
                or self.source.cant_be_sacrificed_this_turn):
            return
        _apply_effects_partitioned([
            _SacrificeSourceEffect(self.source),
            _AfterSourceSacrificeEffect(self.then_specs, len(context.state.event_log), self.source),
        ], context, targets, None, source=self.source)


class _SacrificeSourceEffect(GameEffect):
    def apply(self, context, targets=None):
        context.put_into_graveyard(self.source)


class _AfterSourceSacrificeEffect(GameEffect):
    def __init__(self, then_specs, history_start, source):
        super().__init__(source)
        self.then_specs, self.history_start = then_specs, history_start

    def apply(self, context, targets=None):
        from ..binding.core import build_effects
        from ...models.game.events import EventType
        from ...models.game.game_object import Zone
        from ...parser.oracle.spec import EffectSpec
        # The legacy zone mover emits SACRIFICE only on its graveyard route.
        # A valid sacrifice redirected to exile/library still fulfills the cost.
        sacrificed = self.source.zone != Zone.BATTLEFIELD or any(
            e.type == EventType.SACRIFICE and e.get('instance_id') == self.source.instance_id
            for e in context.state.event_log[self.history_start:])
        if sacrificed:
            effects = build_effects([EffectSpec.from_dict(s) for s in self.then_specs], source=self.source)
            _apply_effects_partitioned(effects, context, targets, None, source=self.source)


EffectRegistry.register('restrict_target_player_this_turn', lambda p: RestrictTargetPlayerThisTurnEffect(
    p.get('spell_types'), bool(p.get('activations', False))))
EffectRegistry.register('sacrifice_source_then', lambda p: SacrificeSourceThenEffect(p.get('then_specs')))


class RememberCardNameEffect(GameEffect):
    def __init__(self, name='', card_type=None, source=None):
        super().__init__(source)
        self.name, self.card_type = name, card_type

    def apply(self, context, targets=None):
        # Naming is a data choice, never executable text. Validate Hamlet's land restriction.
        if self.card_type:
            from ...services.card_database import CardDatabase
            from ...config import DB_PATH
            card = CardDatabase(DB_PATH).get_card(self.name)
            if card is None or not getattr(card, f'is_{self.card_type}', False):
                raise ValueError('Choose a land card name')
        self.source.chosen_card_name = card.name if self.card_type else self.name


class PumpAttackerPerOtherAttackerEffect(GameEffect):
    def __init__(self, keywords=None, source=None):
        super().__init__(source)
        self.keywords = list(keywords or [])
        self.target_spec = TargetSpec(kind='creature_you_control', creature_filter={'attacking': True})

    def apply(self, context, targets=None):
        from .counters_tokens import PumpEffect
        n = sum(o.attacking and o.controller_id == self.source.controller_id
                for o in context.state.battlefield) - 1
        PumpEffect(power=max(0, n), toughness=max(0, n), keywords=self.keywords,
                   target_kind='creature', source=self.source).apply(context, targets)


class PreventSourceDamageUntilNextTurnEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='permanent')

    def apply(self, context, targets=None):
        if not targets:
            return
        target = targets[0]
        player = context.state.player_by_id(target.controller_id)
        context.engine.prevent_damage_from_source(target, 'all')
        player.player_effects[-1].until_next_turn_of = self.source.controller_id


class EndCombatPhaseEffect(GameEffect):
    """RULE 724.2: clear the stack and jump past this combat, without cleanup."""
    def apply(self, context, targets=None):
        from .. import durations
        from ...models.game.game_object import Zone
        state = context.state
        context.engine.pending_triggers.clear()
        while state.stack:
            item = state.stack[-1]
            context.engine._capture_stack_copy_departure(item)
            state.stack.pop()
            if item.obj is not None:
                context.exile(item.obj)
        if self.source is not None and self.source.zone == Zone.STACK:
            context.exile(self.source)
        for obj in state.battlefield:
            obj.attacking = False
            obj.blocking = None
            obj.additional_blocking.clear()
            obj.blocked_by.clear()
            obj.combat_defender = None
        durations.sweep(state, 'end_of_combat')
        state.end_combat_requested = True


class ReturnExiledBatchToHandEffect(GameEffect):
    def __init__(self, ids=None, source=None):
        super().__init__(source)
        self.ids = list(ids or [])

    def apply(self, context, targets=None):
        from ...models.game.game_object import Zone
        for iid in self.ids:
            obj = context.state.find_object(iid)
            if obj is not None and obj.zone == Zone.EXILE:
                context.return_to_hand(obj)


class ExileHandMayPlayOwnerDrawsEffect(GameEffect):
    """Apple's hand exile; only cards played through this grant reward their owner."""
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='opponent')

    def apply(self, context, targets=None):
        from .choices_actions import CreateDelayedTriggerEffect
        from .core import TriggeredAbility
        from .damage_draw import DrawCardEffect
        from ...models.game.events import EventType
        from ...models.game.game_state import TurnScopedTrigger
        if not targets:
            return
        holder = context.state.player_by_id(self.source.controller_id)
        cards = list(targets[0].hand)
        for obj in cards:
            context.exile(obj)
            obj.face_down_in_exile = True
            obj.face_down_exile_viewers.add(holder.id)
            context.engine._grant_temp_play_permission(obj, holder, self.source.name, True, 'type')
        ids = frozenset(o.instance_id for o in cards)
        for event_type in (EventType.SPELL_CAST, EventType.LAND_PLAYED):
            ability = TriggeredAbility(
                trigger_event=event_type,
                effects=[DrawCardEffect(count=1, player={'of': 'trigger_subject', 'as': 'owner'}, source=self.source)],
                condition=lambda e, c, ids=ids, pid=holder.id: (
                    e.get('instance_id') in ids and e.get('player_id') == pid and e.get('from_exile')),
                source=self.source, controller_id=holder.id, description='Apple of Eden: Besitzer zieht eine Karte',
            )
            context.state.turn_scoped_triggers.append(
                TurnScopedTrigger(ability, context.state.internal_turn.number))
        CreateDelayedTriggerEffect(step='end', scope='any', effects=[{
            'type': 'return_exiled_batch_to_hand', 'params': {'ids': [o.instance_id for o in cards]}}],
            description='Apple of Eden: Karten zurück auf die Hand', source=self.source).apply(context)


class RevealCreaturesGiveOpponentsEffect(GameEffect):
    """Reveal and enter first, then choose a distinct recipient per creature (RULE 608.2)."""
    def apply(self, context, targets=None):
        from ...models.game.events import EventType, GameEvent
        player = context.state.player_by_id(self.source.controller_id)
        opponents = [p.id for p in context.state.living_players() if p.id != player.id]
        if not opponents:
            return
        hits = []
        for obj in reversed(list(player.library)):
            context.state.fire_event(GameEvent(EventType.REVEAL, player_id=player.id, object=obj.name))
            if obj.card.is_creature:
                hits.append(obj)
                if len(hits) == len(opponents):
                    break
        effects = []
        for obj in hits:
            effects.extend([
                _EnterRevealedCreatureEffect(obj.instance_id, self.source),
                _GoadRevealedCreatureEffect(obj.instance_id, player.id, self.source),
            ])
        effects.append(_GiveRevealedCreaturesEffect(
            player.id, [o.instance_id for o in hits], opponents, self.source))
        _apply_effects_partitioned(effects, context, None, None, source=self.source)


class _EnterRevealedCreatureEffect(GameEffect):
    def __init__(self, instance_id, source):
        super().__init__(source)
        self.instance_id = instance_id

    def apply(self, context, targets=None):
        obj = context.state.find_object(self.instance_id)
        if obj is not None:
            # Reuse the casting entry choosers after the zone-change reset, so
            # a revealed Revoker/Image chooses before entering, without its
            # answer being discarded by a second reset.
            owner = context.state.player_by_id(obj.owner_id)
            context.engine._remove_from_current_zone(owner, obj)
            obj.reset_as_new_object()
            obj.controller_id = owner.id
            def finish():
                context.engine._put_searched_card(owner, obj, 'battlefield')
            if obj.enter_as_copy_effects:
                context.engine._offer_enter_as_copy(
                    obj, lambda: context.engine._offer_enter_choices(obj, finish))
            else:
                context.engine._offer_enter_choices(obj, finish)


class _GoadRevealedCreatureEffect(GameEffect):
    def __init__(self, instance_id, player_id, source):
        super().__init__(source)
        self.instance_id, self.player_id = instance_id, player_id

    def apply(self, context, targets=None):
        obj = context.state.find_object(self.instance_id)
        if obj is not None and obj in context.state.permanents():
            context.engine.goad(obj, self.player_id, permanent=True)


class _GiveRevealedCreaturesEffect(GameEffect):
    def __init__(self, player_id, ids, opponents, source):
        super().__init__(source)
        self.player_id, self.ids, self.opponents = player_id, ids, opponents

    def apply(self, context, targets=None):
        context.shuffle_library(context.state.player_by_id(self.player_id))
        _offer_creature_recipient(context.engine, self.player_id, self.ids, self.opponents)


def _offer_creature_recipient(rules, player_id, ids, opponents):
    if ids and opponents:
        rules.open_choice({'kind': 'creature_recipient', 'player_id': player_id,
                           'prompt': 'Gegner für die aufgedeckte Kreatur wählen',
                           'ids': ids, 'opponents': opponents,
                           'options': [{'id': p, 'label': rules.state.player_by_id(p).name} for p in opponents]})


from ..continuations import choice


@choice('creature_recipient', rule='608.2d')
def _resume_creature_recipient(rules, pending, answer):
    if answer not in pending['opponents']:
        raise ValueError('Choose an offered opponent')
    from .exile_control import GainControlUntilEndOfTurnEffect
    from .core import GameContext
    obj = rules.state.find_object(pending['ids'][0])
    if obj is not None and obj in rules.state.permanents():
        effect = GainControlUntilEndOfTurnEffect(duration='permanent', haste=False, untap=False, source=obj)
        # This effect's explicit player operand avoids changing its source controller.
        effect._take(GameContext(rules.state, rules), obj, rules.state.player_by_id(answer))
        GameContext(rules.state, rules).recompute()
    _offer_creature_recipient(rules, pending['player_id'], pending['ids'][1:],
                             [p for p in pending['opponents'] if p != answer])


EffectRegistry.register('remember_card_name', lambda p: RememberCardNameEffect(p.get('name', ''), p.get('card_type')))
EffectRegistry.register('pump_attacker_per_other_attacker', lambda p: PumpAttackerPerOtherAttackerEffect(p.get('keywords')))
EffectRegistry.register('prevent_source_damage_until_next_turn', lambda p: PreventSourceDamageUntilNextTurnEffect())
EffectRegistry.register('end_combat_phase', lambda p: EndCombatPhaseEffect())
EffectRegistry.register('return_exiled_batch_to_hand', lambda p: ReturnExiledBatchToHandEffect(p.get('ids')))
EffectRegistry.register('exile_hand_may_play_owner_draws', lambda p: ExileHandMayPlayOwnerDrawsEffect())
EffectRegistry.register('reveal_creatures_give_opponents', lambda p: RevealCreaturesGiveOpponentsEffect())
