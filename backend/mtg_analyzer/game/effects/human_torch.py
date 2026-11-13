"""Human Torch's paid, repeating combat-damage trigger."""
from .core import GameEffect, TriggeredAbility, _controller_of
from ...models.game.events import EventType
from ...models.game.game_state import TurnScopedTrigger


class HumanTorchDamageEffect(GameEffect):
    def __init__(self, source=None, source_incarnation=None):
        super().__init__(source)
        self.source_incarnation = source_incarnation

    def apply(self, context, targets=None):
        event = context.trigger_event or {}
        amount = int(event.get("amount") or 0)
        controller = _controller_of(self.source, context)
        if amount <= 0 or controller is None:
            return
        dealer = self.source
        if dealer.zone_incarnation != self.source_incarnation:
            dealer = context.state.zone_visit_sources.get(
                (dealer.instance_id, self.source_incarnation), dealer)
        # RULE 608.2h: the original source deals the damage even after leaving.
        with context.engine.damage_batch():
            for player in context.state.living_players():
                if player.id not in (controller.id, event.get("target_id")):
                    context.engine.deal_damage(player, amount, source=dealer)


class HumanTorchCreateTriggerEffect(GameEffect):
    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        source_id = self.source.instance_id
        visit = context.resolving_source_incarnation
        if visit is None:
            visit = self.source.zone_incarnation
        controller_id = controller.id

        def matches(event, ctx):
            return (event.get("source_id") == source_id
                and event.get("source_zone_incarnation") == visit
                and event.get("combat") and event.get("is_player")
                and event.get("target_id") != controller_id)

        ability = TriggeredAbility(trigger_event=EventType.DAMAGE, condition=matches,
            effects=[HumanTorchDamageEffect(self.source, visit)],
            source=self.source, controller_id=controller_id,
            description="Human Torch deals that much damage to each other opponent.")
        # RULE 603.7b: an explicit turn duration permits repeated triggers.
        context.state.turn_scoped_triggers.append(
            TurnScopedTrigger(ability, context.state.internal_turn.number))
