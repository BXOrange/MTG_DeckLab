from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "a creature card with mana value 1 or less".
_CHEAP_CREATURE_MAX_MANA_VALUE = 1


def _starfield_shepherd() -> list[AbilitySpec]:
    """Flying
    When this creature enters, search your library for a basic Plains card or a creature card with mana value 1 or less, reveal it, put it into your hand, then shuffle.
    Warp {1}{W}

    — PLAY-ALL (Hope to the last). Flying and Warp are the keyword catalogue's. The tutor is a `search` over an ``or``
    criteria (basic Plains | creature with mana value ≤ 1) to hand.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"or": [
                    {"all_types": ["basic", "plains"]},
                    {"type": "Creature", "max_mana_value": _CHEAP_CREATURE_MAX_MANA_VALUE},
                ]},
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Starfield Shepherd", _starfield_shepherd)
