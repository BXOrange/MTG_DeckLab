"""Guile replaces a controlled counter instruction with exile and an immediate play."""
from .core import GameEffect, ReplacementEffect
from ...models.game.game_object import Zone
from ...models.game.events import EventType


class GuileCounterReplacement(ReplacementEffect):
    def __init__(self):
        super().__init__(EventType.WOULD_COUNTER_SPELL, self._replace, condition=self._applies,
            description="Guile — stattdessen ins Exil schicken und kostenlos spielen")

    def _applies(self, event, context):
        return (not event.get("guile_exile") and self.source is not None
                and event.get("countered_by") == self.source.controller_id)

    def _replace(self, event, context):
        # RULE 614.6: the replaced counter never happens. The immediate
        # play is part of the replacement, not a later triggered ability.
        return event.copy_with(guile_exile=True, guile_controller_id=self.source.controller_id)


class GuileShuffleEffect(GameEffect):
    def apply(self, context, targets=None):
        obj = self.source
        event = context.trigger_event or {}
        visit = event.get("zone_incarnation", context.resolving_source_incarnation)
        # RULE 400.7: Guile's graveyard trigger refers to that exact visit,
        # not a later hand, exile, or graveyard object of the same card.
        if (obj is not None and obj.zone == Zone.GRAVEYARD and obj.zone_incarnation == visit
                and obj in context.state.player_by_id(obj.owner_id).graveyard):
            context.shuffle_into_library(obj)
