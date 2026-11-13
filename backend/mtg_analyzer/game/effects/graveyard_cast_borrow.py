"""Cast a particular graveyard visit, then borrow that spell's activated abilities."""
from .core import GameEffect, EffectRegistry, TriggeredAbility, StaticAbility, _controller_of
from copy import deepcopy
from .game_status import GrantFlashbackToTargetEffect
from ...models.game.events import EventType
from ...models.game.game_object import Zone
from ...models.game.game_state import TurnScopedTrigger


class _BorrowCastAbilities(GameEffect):
    def __init__(self, source, incarnation):
        super().__init__(source)
        self.incarnation = incarnation
        self.snapshot = []
        self.mana_snapshot = []

    def capture(self, spell):
        # RULE 603.7c/611.2d: capture the spell's abilities at the cast event,
        # before it can be countered or change zones while this trigger waits.
        self.snapshot = deepcopy(list(spell.activated_abilities), {id(spell): self.source})
        # Usage limits belong to this newly gained ability instance.
        for ability in self.snapshot:
            ability._last_activated_turn = None
            ability._activations_this_turn = 0
        from ..mana_abilities import parse_mana_abilities
        self.mana_snapshot = deepcopy(parse_mana_abilities(spell.card))

    def apply(self, context, targets=None):
        if (self.source is not None and self.source in context.state.permanents()
                and self.source.zone_incarnation == self.incarnation):
            self.source.temp_granted_activated_abilities.extend(self.snapshot)
            if self.mana_snapshot:
                from ..durations import stamp
                ability = StaticAbility("ability", affects="objects", params={
                    "borrowed_mana_snapshots": self.mana_snapshot,
                    "object_incarnations": {self.source.instance_id: self.incarnation},
                })
                stamp(ability, context, self.source, "end_of_turn")
                ability.object_ids = [self.source.instance_id]
                ability.timestamp = context.state.next_timestamp()
                context.state.floating_statics.append(ability)


class _CastExactVisit:
    def __init__(self, target_id, visit, player_id, payoff):
        self.target_id, self.visit, self.player_id = target_id, visit, player_id
        self.payoff = payoff

    def __call__(self, event, context):
        matches = (event.get("instance_id") == self.target_id
                   and event.get("from_zone") == "graveyard"
                   and event.get("from_zone_incarnation") == self.visit
                   and event.get("player_id") == self.player_id)
        if matches:
            obj = context.state.find_object(self.target_id)
            if obj is not None:
                self.payoff.capture(obj)
        return matches


class GraveyardCastBorrowEffect(GrantFlashbackToTargetEffect):
    def __init__(self):
        super().__init__(target_kind="any_graveyard_creature", as_permission=True)

    def apply(self, context, targets=None):
        target = targets[0] if targets else None
        if target is None or target.zone != Zone.GRAVEYARD or self.source is None:
            return
        super().apply(context, targets)
        controller = _controller_of(self.source, context)
        incarnation = context.resolving_source_incarnation
        if incarnation is None:
            incarnation = self.source.zone_incarnation
        payoff = _BorrowCastAbilities(self.source, incarnation)
        ability = TriggeredAbility(
            trigger_event=EventType.SPELL_CAST, effects=[payoff], source=self.source,
            controller_id=controller.id, description="Havengul Lich: aktivierte Fähigkeiten erhalten",
            condition=_CastExactVisit(target.instance_id, target.zone_incarnation, controller.id, payoff),
        )
        context.state.turn_scoped_triggers.append(TurnScopedTrigger(
            ability, context.state.internal_turn.number, once=True,
        ))


EffectRegistry.register("graveyard_cast_borrow_activated", lambda p: GraveyardCastBorrowEffect())
