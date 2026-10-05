"""Resolution sequences involving permanent names and death information."""
from __future__ import annotations

from ...models.game.events import EventType
from ...models.game.game_object import Zone
from ..targeting import TargetSpec
from .core import GameEffect, EffectRegistry, _apply_effects_partitioned
from .core import DestroyEffect


class DestroySameNameEffect(GameEffect):
    """RULE 608.2: fix the name before destroying the entire matching group."""

    def __init__(self, target_kind='nonland_permanent', source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context, targets=None):
        if not targets:
            return
        name = targets[0].name
        victims = [obj for obj in context.state.permanents() if obj.name == name]
        _apply_effects_partitioned(
            [DestroyEffect(target=obj, source=self.source) for obj in victims],
            context, None, None, source=self.source,
        )


class _CopyIfDiedEffect(GameEffect):
    def __init__(self, original, power, toughness, controller_id, history_start, source=None):
        super().__init__(source)
        self.original = original.card
        self.instance_id = original.instance_id
        self.power, self.toughness = power, toughness
        self.controller_id = controller_id
        self.history_start = history_start

    def apply(self, context, targets=None):
        died = any(
            event.type == EventType.DIES and event.get('instance_id') == self.instance_id
            for event in context.state.event_log[self.history_start:]
        )
        if died:
            # RULE 707.9: these exceptions are copiable values of the new tokens.
            card = self.original.as_copy(set_power=self.power, set_toughness=self.toughness)
            context.created_objects.extend(context.create_token(self.controller_id, card, 2) or [])


class DestroyAndHalfCopiesEffect(GameEffect):
    """Destroy a creature, then copy it only if that destruction made it die.

    Captures controller, copiable characteristics and live P/T before the zone
    change (RULE 608.2h). The sequence resumes after replacement choices.
    """

    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='creature')

    def apply(self, context, targets=None):
        if not targets:
            return
        obj = targets[0]
        follow = _CopyIfDiedEffect(
            obj, ((obj.power or 0) + 1) // 2, ((obj.toughness or 0) + 1) // 2,
            obj.controller_id, len(context.state.event_log), self.source,
        )
        _apply_effects_partitioned(
            [DestroyEffect(target=obj, source=self.source), follow], context, None, None,
            source=self.source,
        )


EffectRegistry.register('destroy_same_name', lambda p: DestroySameNameEffect(p.get('target_kind', 'nonland_permanent')))
EffectRegistry.register('destroy_and_half_copies', lambda p: DestroyAndHalfCopiesEffect())


class SacrificePermanentOrDiscardEffect(GameEffect):
    """The iteration's player chooses a creature/planeswalker, else a hand card."""

    def apply(self, context, targets=None):
        if not targets:
            return
        player = targets[0]
        candidates = [
            obj for obj in context.state.permanents_controlled_by(player.id)
            if obj.is_creature or obj.is_planeswalker
        ]
        if candidates:
            context.choose_objects(player, candidates, 'sacrifice', source=self.source)
        else:
            context.discard_choice(player, 1)


EffectRegistry.register('sacrifice_permanent_or_discard', lambda p: SacrificePermanentOrDiscardEffect())


class _RecoverMilledPermanentEffect(GameEffect):
    def __init__(self, history_start, source=None):
        super().__init__(source)
        self.history_start = history_start

    def _milled(self, context):
        from .core import _controller_of
        player = _controller_of(self.source, context)
        return [
            context.state.find_object(card['instance_id'])
            for event in context.state.event_log[self.history_start:]
            if event.type == EventType.CARDS_MILLED and event.get('player_id') == player.id
            for card in event.get('cards', [])
        ]

    def apply(self, context, targets=None):
        from .core import _controller_of
        permanent_types = {'artifact', 'battle', 'creature', 'enchantment', 'land', 'planeswalker'}
        candidates = [obj for obj in self._milled(context)
                      if obj is not None and obj.zone == Zone.GRAVEYARD
                      and set(obj.type_words) & permanent_types]
        context.choose_objects(
            _controller_of(self.source, context), candidates,
            'return_from_graveyard_to_hand', optional=True, source=self.source,
        )


class _MilledSubtypeBonusEffect(_RecoverMilledPermanentEffect):
    def apply(self, context, targets=None):
        from ..continuous import has_subtype
        from .core import _controller_of, CreateTokenEffect
        player = _controller_of(self.source, context)
        has_squirrel = any(has_subtype(obj, 'Squirrel') for obj in context.state.permanents_controlled_by(player.id))
        returned_squirrel = any(obj is not None and obj in player.hand and has_subtype(obj, 'Squirrel')
                                for obj in self._milled(context))
        if has_squirrel or returned_squirrel:
            CreateTokenEffect(token_name='Food', source=self.source).apply(context)


class MillRecoverPermanentAndSubtypeBonusEffect(GameEffect):
    """Mill four, optionally recover one permanent, then check the tribal bonus."""

    def apply(self, context, targets=None):
        from .core import MillEffect
        start = len(context.state.event_log)
        _apply_effects_partitioned([
            MillEffect(count=4, source=self.source),
            _RecoverMilledPermanentEffect(start, self.source),
            _MilledSubtypeBonusEffect(start, self.source),
        ], context, None, None, source=self.source)


class RepeatPaidProcessEffect(GameEffect):
    """A finite graveyard-consuming process with a new payment choice each time.

    Reusing the payment continuation avoids a synchronous loop overwriting
    unanswered choices. Every repetition consumes three cards (RULE 118.3).
    """

    def apply(self, context, targets=None):
        from .core import CreateTokenEffect
        _apply_effects_partitioned([
            CreateTokenEffect(token_name='Food', source=self.source),
            _OfferExileRepeatEffect(source=self.source),
        ], context, None, None, source=self.source)


class _OfferExileRepeatEffect(GameEffect):
    def apply(self, context, targets=None):
        from .core import _controller_of
        from .composition import OptionalEffect
        player = _controller_of(self.source, context)
        if len(player.graveyard) >= 3:
            OptionalEffect(
                effects=[{'type': 'exile_graveyard_then_repeat_food', 'params': {}}],
                prompt='Drei Karten aus deinem Friedhof ins Exil schicken?',
                source=self.source,
            ).apply(context)


class _ExileGraveyardAndRepeatEffect(GameEffect):
    def apply(self, context, targets=None):
        from .core import _controller_of
        player = _controller_of(self.source, context)
        if len(player.graveyard) < 3:
            return
        # Once accepted, all three picks are mandatory: no partial payment.
        context.choose_objects(
            player, list(player.graveyard), 'exile', count=3, source=self.source,
            then_specs=[{'type': 'repeat_food_exile_process', 'params': {}}],
        )


EffectRegistry.register('mill_recover_permanent_subtype_bonus', lambda p: MillRecoverPermanentAndSubtypeBonusEffect())
EffectRegistry.register('repeat_food_exile_process', lambda p: RepeatPaidProcessEffect())

EffectRegistry.register('exile_graveyard_then_repeat_food', lambda p: _ExileGraveyardAndRepeatEffect())
