from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _evendo_brushrazer() -> list[AbilitySpec]:
    """Link exiled cards to this source; play them on your turn after a
    nontoken sacrifice. The mana grammar handles the land sacrifice.
    """
    sacrifice = {"event": EventType.SACRIFICE, "condition": {"subject": "group", "controller": "you", "nontoken": True}}
    return [AbilitySpec("triggered", [
        EffectSpec("exile_top_of_library", {"track_exiled_with": True}),
        EffectSpec("grant_conditional_cast_from_exile", {
            "all_cards": True, "linked_source": True,
            "condition": {"kind": "all", "conditions": [
                {"kind": "your_turn"},
                {"kind": "event_this_turn", "trigger": sacrifice, "min": 1},
            ]},
        }),
    ], trigger=sacrifice)]


register("Evendo Brushrazer", _evendo_brushrazer)
