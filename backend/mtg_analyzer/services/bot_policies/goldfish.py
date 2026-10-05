"""GoldfishBot policy; shared registry/driver is services.bots."""
from __future__ import annotations

from typing import Any, Optional

from .base import Bot


class GoldfishBot(Bot):
    """Plays lands, passes on everything else (the classic goldfish).

    A real seat rather than `GameSession`'s passive dummy: it has a deck
    that mills, a life total that can be attacked, a hand that can be
    discarded from — it simply never uses any of it. It does play its land
    for the turn, because a goldfish that can't be Stone-Rained isn't
    testing much, and because an empty board is a less honest clock than a
    board that at least grows lands.
    """

    kind = "goldfish"
    label = "Goldfisch-Bot"
    description = "Spielt nur Länder und passt sonst immer."

    def can_pass_turn(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> bool:
        # Never responds to anything, and only ever acts on its own turn.
        return True

    def play(
        self, view: dict[str, Any], actions: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        if not self.is_active(view) or view["state"].get("current_step") not in ("main1", "main2"):
            return None
        return next((a for a in actions if a["type"] == "play_land"), None)

