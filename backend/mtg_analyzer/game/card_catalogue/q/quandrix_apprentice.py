from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# magecraft + ``impulsive_look`` (PAR-60)
# ===========================================================================
# `ImpulsiveLookEffect` ("look at the top N, take one matching a filter,
# rest to Y") already does exactly Quandrix Apprentice's dig.


def _quandrix_apprentice() -> list[AbilitySpec]:
    """Magecraft — Whenever you cast or copy an instant or sorcery spell,
    look at the top three cards of your library. You may reveal a land card
    from among them and put that card into your hand. Put the rest on the
    bottom of your library in any order."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("impulsive_look", {
                "count": 3, "criteria": {"type": "land"},
                "hit_destination": "hand",
                "miss_destination": "library_bottom_random",
                "optional": True,
            })],
            trigger={"event": [EventType.SPELL_CAST, EventType.SPELL_COPIED],
                     "condition": {"subject": "group", "controller": "you"},
                     "spell_card_types": ["instant", "sorcery"]},
        ),
    ]


register("Quandrix Apprentice", _quandrix_apprentice)
