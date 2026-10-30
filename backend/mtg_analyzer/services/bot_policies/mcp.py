"""Seat played by an external MCP client; the server never chooses for it."""
from __future__ import annotations

from typing import Any, Optional

from mtg_analyzer.services.lobby import MCP_BOT_KIND

from .base import Bot


class McpBot(Bot):
    """Placeholder policy for a seat an MCP client plays over the token API.

    The client submits its own actions (`api/mcp_seat.py`), so `decide` never
    proposes one. ``waiting`` makes `run_bots` leave priority with the seat
    instead of passing for it, exactly like a pending AI request. A client that
    went silent is replaced by Smart Bot in `bots_for_game`, so this policy
    only exists while the client is connected.
    """

    kind = MCP_BOT_KIND
    label = "MCP-Client"
    description = "Wird von einem externen MCP-Client (z. B. Claude) gespielt."
    waiting = True

    def decide(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        return None
