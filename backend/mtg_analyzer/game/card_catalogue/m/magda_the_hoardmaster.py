from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _magda_the_hoardmaster() -> list[AbilitySpec]:
    """Whenever you commit a crime, create a tapped Treasure token. This
    ability triggers only once each turn. (Targeting opponents, anything
    they control, and/or cards in their graveyards is a crime.)
    Sacrifice three Treasures: Create a 4/4 red Scorpion Dragon creature
    token with flying and haste. Activate only as a sorcery.

    The RULE 700.13 crime event fires when targets are announced. The
    once-per-turn limit applies to the trigger, not its resolution.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1, "tapped": True})],
            trigger={"event": EventType.CRIME_COMMITTED, "condition": {"subject": "you"}, "limit": True},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 4, "toughness": 4, "colors": ["R"],
                "subtypes": ["Scorpion", "Dragon"], "keywords": ["flying", "haste"],
                "token_name": "Scorpion Dragon",
            }), EffectSpec("sorcery_speed_marker", {})],
            cost={"text": "Sacrifice three Treasures"},
        ),
    ]


register("Magda, the Hoardmaster", _magda_the_hoardmaster)
