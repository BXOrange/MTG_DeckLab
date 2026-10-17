"""Riders read the departing object or the successfully returned incarnation."""
from .core import GameEffect, _controller_of, _apply_effects_partitioned
from .battlefield_batches import start_exile_return_batch
from .flicker_composites import _exile_batch
from .damage_draw import DrawCardEffect
from .counters_tokens import GrantUntilEffect
from ..targeting import TargetSpec
from ...models.game.game_object import Zone
from ...models.game.game_state import DelayedTrigger


class _ReturnedRiderEffect(GameEffect):
    def __init__(self, rider, player_id, source=None):
        super().__init__(source)
        self.rider, self.player_id = rider, player_id

    def apply(self, context, targets=None):
        if not targets:
            return  # "If you do" requires an actual return of the captured card.
        if self.rider == 'discard_toughness':
            # RULE 608.2h: use the new permanent, after its entry choices
            # and continuous effects, rather than the exiled creature's LKI.
            context.recompute()
            count = max(0, int(targets[0].toughness or 0))
            context.engine.discard_choice(context.state.player_by_id(self.player_id), count, source=self.source)
        elif self.rider == 'haste':
            # RULE 611.2c: no stated duration; the grant follows only this
            # battlefield incarnation and is not copied into its card text.
            GrantUntilEffect(static={'type': 'grant_keyword', 'params': {'keywords': ['haste']}},
                duration='rest_of_game', previous_subject=True, source=self.source).apply(context)


class _ReturnWithRiderEffect(GameEffect):
    def __init__(self, visits, player_id, rider, source=None):
        super().__init__(source)
        self.visits, self.player_id, self.rider = list(visits), player_id, rider

    def apply(self, context, targets=None):
        start_exile_return_batch(context.engine, self.visits,
            after_effects=[_ReturnedRiderEffect(self.rider, self.player_id, self.source)], source=self.source)


class _ScheduleUpkeepReturnEffect(GameEffect):
    def __init__(self, visits, player_id, rider, source=None):
        super().__init__(source)
        self.visits, self.player_id, self.rider = list(visits), player_id, rider

    def apply(self, context, targets=None):
        context.state.delayed_triggers.append(DelayedTrigger(
            self.player_id, 'upkeep', [_ReturnWithRiderEffect(
                self.visits, self.player_id, self.rider, self.source)], scope='controller'))


class VanishIntoMemoryEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='creature')

    def apply(self, context, targets=None):
        if not targets:
            return
        context.recompute()
        # RULE 608.2h: the creature's last battlefield power includes pumps
        # and counters; a return later measures its NEW toughness instead.
        power = max(0, int(targets[0].power or 0))
        player = _controller_of(self.source, context)
        visits = _exile_batch(context, targets[:1])
        _apply_effects_partitioned([
            DrawCardEffect(count=power, source=self.source),
            _ScheduleUpkeepReturnEffect(visits, player.id, 'discard_toughness', self.source),
        ], context, [], None, source=self.source)


class SelfExileUpkeepRiderEffect(GameEffect):
    def apply(self, context, targets=None):
        obj = self.source
        expected = context.resolving_source_incarnation
        if (obj is None or obj.zone != Zone.BATTLEFIELD or
                (expected is not None and obj.zone_incarnation != expected)):
            return  # RULE 400.7: a departed source's new visit is not "it".
        player = _controller_of(obj, context)
        visits = _exile_batch(context, [obj])
        if visits:
            _ScheduleUpkeepReturnEffect(visits, player.id, 'haste', obj).apply(context)


EFFECT_FACTORIES = {
    'vanish_into_memory': lambda p: VanishIntoMemoryEffect(),
    'self_exile_upkeep_haste': lambda p: SelfExileUpkeepRiderEffect(),
}
