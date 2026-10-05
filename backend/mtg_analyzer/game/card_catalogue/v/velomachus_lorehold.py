from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _velomachus_lorehold() -> list[AbilitySpec]:
    """Flying, vigilance, haste
    Whenever Velomachus Lorehold attacks, look at the top seven cards of your library. You may
    cast an instant or sorcery spell with mana value less than or equal to Velomachus Lorehold's
    power from among them without paying its mana cost. Put the rest on the bottom of your
    library in a random order.

    — Jeskai Striker deck batch. Flying/vigilance/haste are keywords. The attack trigger is
    `look_top_cast_free` (`LookTopCastFreeEffect`) — see its docstring for the exile-then-
    resolution-play route and its one simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("look_top_cast_free", {
                "count": 7, "criteria": {"type": ["Instant", "Sorcery"]},
                "max_mana_value_from": "source_power",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Velomachus Lorehold", _velomachus_lorehold)
