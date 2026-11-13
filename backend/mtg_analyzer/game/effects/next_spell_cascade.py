"""A resolve-time cascade grant for a player's next spell this turn."""
from __future__ import annotations

from .core import GameEffect


class GrantNextSpellCascadeEffect(GameEffect):
    def apply(self, context, targets=None):
        player = self._operand_player(context, targets, {"of": "previous_player"})
        if player is None:
            return
        # RULE 702.85a: the chosen player's next cast receives its own cascade trigger.
        context.state.next_spell_cascade_grants.append({
            "player_id": player.id, "turn": context.state.internal_turn.number,
        })
