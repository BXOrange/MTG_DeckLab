from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: Spacecraft creatures get this many +N/+N from Captain Kirk.
KIRK_SPACECRAFT_BONUS = 3


def _captain_kirk_boldly_going() -> list[AbilitySpec]:
    """Vigilance
    Spacecraft creatures you control get +3/+3.
    Whenever Captain Kirk enters or attacks, search your library and/or graveyard for a basic land card or a card named Starship Enterprise, reveal it, and put it into your hand. If you search your library this way, shuffle.

    RULE 701.23: one search over both zones; the card filter is a union
    (``or``) of "basic land" and "named Starship Enterprise". Vigilance
    folds in from the keyword catalogue.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "power": KIRK_SPACECRAFT_BONUS, "toughness": KIRK_SPACECRAFT_BONUS,
                "affects": "creatures_you_control", "subtype": "Spacecraft",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"or": [{"basic": True}, {"name": "Starship Enterprise"}]},
                "destination": "hand", "zones": ["library", "graveyard"],
            })],
            trigger={"event": [EventType.ENTERS_BATTLEFIELD, EventType.ATTACKS], "condition": {"subject": "self"}},
        ),
    ]


register("Captain Kirk, Boldly Going", _captain_kirk_boldly_going)
