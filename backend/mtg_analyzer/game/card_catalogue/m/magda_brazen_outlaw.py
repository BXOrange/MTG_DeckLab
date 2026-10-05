from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _magda_brazen_outlaw() -> list[AbilitySpec]:
    """Other Dwarves you control get +1/+0.
    Whenever a Dwarf you control becomes tapped, create a Treasure
    token.
    Sacrifice five Treasures: Search your library for an artifact or
    Dragon card, put that card onto the battlefield, then shuffle.

    — MEC-43. The anthem and the tap-trigger are already fully `MODELED`
    by the oracle-text parser; reused as-is. The activated ability is
    `costs.ActivationCost.sacrifice_count`'s already-shipped ``(count,
    subtype)`` shape (Trail of Crumbs/Cauldron Familiar-family, ``(3,
    "food")``) at Magda's own ``(5, "Treasure")``, plus the already-
    general `SearchLibraryEffect` with an "artifact or Dragon" criteria
    union.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "power": 1, "toughness": 0, "affects": "other_creatures_you_control", "subtype": "Dwarf",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.TAPPED,
                "condition": {
                    "subject": "group", "subtypes": ["dwarf"], "nontoken": False,
                    "controller": "you", "other": False,
                },
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": ["Artifact", "Dragon"]}, "destination": "battlefield",
            })],
            cost={"sacrifice_count": (5, "treasure")},
        ),
    ]


register("Magda, Brazen Outlaw", _magda_brazen_outlaw)
