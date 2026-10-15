"""RULE 614/704.7: replace losing with an ordered, resumable recovery."""
from .core import GameEffect, ReplacementEffect, _apply_effects_partitioned
from .life_sacrifice import SetLifeEffect
from .exile_control import ShuffleGraveyardIntoLibraryEffect
from ...models.game.events import EventType


class FinishLossRecoveryEffect(GameEffect):
    """Finish the payload before another simultaneous loss/priority window."""
    def apply(self, context, targets=None):
        player = context.state.player_by_id(self.source.controller_id)
        if player is not None:
            # RULE 122: remove poison only; unrelated counters are unchanged.
            context.add_player_counters(player, -player.poison, "poison")
            emblem = next((e for e in player.emblems if e.instance_id == self.source.instance_id), None)
            if emblem is not None:
                player.emblems.remove(emblem)
        context.engine._finish_loss_replacement_payload()


class RecoverInsteadOfLosingEffect(ReplacementEffect):
    """Puresteel's payload; the source is the consumed command-zone emblem."""
    def __init__(self, source=None, life_total=20):
        self.life_total = max(0, int(life_total))
        super().__init__(EventType.PLAYER_WOULD_LOSE, self._replace,
                         condition=self._matches, source=source,
                         description="Leben zurücksetzen, Friedhof mischen, Gift und dieses Emblem verlieren")

    def _matches(self, event, context):
        if self.source is None or event.get("player_id") != self.source.controller_id:
            return False
        player = context.state.player_by_id(self.source.controller_id)
        return player is not None and any(e is self.source for e in player.emblems)

    def _replace(self, event, context):
        batch = context.state.player_loss_batch
        if batch is not None:
            batch["payload_pending"] = True
            batch["recovery_source_id"] = self.source.instance_id
        # RULE 119.5: becoming 20 is real life gain/loss, with its own
        # replacements. Nested choices suspend every later instruction.
        _apply_effects_partitioned([
            SetLifeEffect(self.life_total, target_kind=None, source=self.source),
            ShuffleGraveyardIntoLibraryEffect(source=self.source),
            FinishLossRecoveryEffect(source=self.source),
        ], context, None, None, source=self.source)
        return None
