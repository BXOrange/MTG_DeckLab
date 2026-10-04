"""ManaMaximizerBot policy; shared registry/driver is services.bots."""
from __future__ import annotations

from typing import Any, Optional

from .base import Bot


class ManaMaximizerBot(Bot):
    """Plays a land every turn and taps every remaining untapped land/
    artifact mana source for mana — never casts a spell, never attacks or
    blocks. Not a real opponent: a diagnostic bot for ANA-4's dynamic
    analysis (`services/dynamic_analysis.py`).

    `GoldfishBot` never taps for mana at all (it only plays lands), and
    `GreedyBot` only taps for whatever it's about to cast — so neither
    bot's "mana produced" reading says anything about how much mana the
    board *could* have made that turn if fully tapped out. That gap is
    exactly what showed up as "mana production/potential trailing the
    lands drawn": the board's real ceiling was never actually reached by
    either bot, so there was nothing wrong to fix there — but there was
    also no way to *see* the ceiling to compare against. This bot exists
    to produce that comparison point: with everything tapped every turn,
    "mana produced" reads as the board's true per-turn capacity, directly
    comparable to `mana_potential`'s battlefield-only figure.

    Deliberately mirrors `GreedyBot._tap_for_mana`'s own "tap whichever
    colour the pool has least of" rule rather than sharing it — the two
    bots are meant to stay independently simple (see this module's
    docstring), and the method is a few lines either way.
    """

    kind = "mana_maximizer"
    label = "Mana-Bot"
    description = "Spielt Länder und tappt jede Manaquelle voll aus, castet aber nichts und greift nie an."

    def play(
        self, view: dict[str, Any], actions: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        if not self.is_active(view) or view["state"].get("current_step") not in ("main1", "main2"):
            return None
        land = next((a for a in actions if a["type"] == "play_land"), None)
        if land is not None:
            return land
        mana = next((a for a in actions if a["type"] == "tap_for_mana"), None)
        if mana is not None:
            return self._tap_for_mana(view, mana)
        return None

    def _tap_for_mana(self, view: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        """Tap one source, picking the colour the pool has least of — same
        rationale as `GreedyBot._tap_for_mana`: not aimed at any cost in
        particular, just spread across colours instead of draining one dual
        land's colour choice the same way every time."""
        pool = self.my_pool(view)
        options = action.get("options") or []

        def held(option: dict[str, Any]) -> int:
            produced = option.get("mana") or {}
            return sum(pool.get(colour, 0) for colour in produced)

        best = min(options, key=held)["index"] if options else 0
        return {
            "type": "tap_for_mana",
            "instance_id": action["instance_id"],
            "ability_index": action.get("ability_index", 0),
            "option_index": best,
        }

