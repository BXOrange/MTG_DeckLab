"""External MCP seat: leave decisions to the client, pass empty windows locally."""
from __future__ import annotations

from typing import Any, Optional

from mtg_analyzer.services.lobby import MCP_BOT_KIND

from .base import Bot


class McpBot(Bot):
    """Policy for a seat an MCP client plays over the token API.

    The client submits its own plays (`api/mcp_seat.py`). ``waiting`` keeps
    priority whenever a play or choice is available; mana-only/pass windows
    are handled locally with the same yield gates as other bots. A client that
    went silent is replaced by Smart Bot in `bots_for_game`, so this policy
    only exists while the client is connected.
    """

    kind = MCP_BOT_KIND
    label = "MCP-Client"
    description = "Wird von einem externen MCP-Client (z. B. Claude) gespielt."
    waiting = True
    skips_to_end_step = True

    def can_pass_turn(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> bool:
        # Mana alone is not a play. Keep every other decision, including
        # setup, choices, optional abilities and combat, with the client.
        return all(a["type"] in {"pass_priority", "tap_for_mana", "activate_hand_mana"} for a in actions)

    def decide(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if (not view["setup"]["complete"] or view.get("pending_choice")
                or not self.has_priority(view) or not self.can_pass_turn(view, actions)
                or not any(a["type"] == "pass_priority" for a in actions)):
            return None
        if self.wants_turn_yield(view, actions):
            return {"type": "set_yield", "mode": "turn"}
        if self.wants_end_step_yield(view, actions):
            return {"type": "set_yield", "mode": "end_step"}
        return {"type": "pass_priority"}
