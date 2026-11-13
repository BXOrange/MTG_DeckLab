"""Archnemesis attaches its original Aura to the attacking player."""
from .core import GameEffect
from ...models.game.game_object import Zone
from ...models.game.player import Player


class ArchnemesisAttachEffect(GameEffect):
    def apply(self, context, targets=None):
        source = self.source
        visit = context.resolving_source_incarnation
        # RULE 400.7 / 701.3: the instruction cannot move a new Aura visit.
        if (source is None or source.zone != Zone.BATTLEFIELD or source.phased_out
                or (visit is not None and source.zone_incarnation != visit)):
            return
        player = next((p for p in (targets or []) if isinstance(p, Player)), None)
        if player is not None:
            context.engine.attach_to_target(source, player, check_control=False)
