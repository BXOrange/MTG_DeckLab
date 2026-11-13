from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _glory_to_the_empire() -> list[AbilitySpec]:
    """When this enchantment enters, create a number of 2/1 red Klingon Warrior creature tokens with haste equal to the number of opponents you have.
    Creatures you control have melee. (Whenever a creature with melee attacks, it gets +1/+1 until end of turn for each opponent you attacked this combat.)

    RULE 111: ``per_opponent`` creates one token per living opponent, all
    under the controller. Melee (RULE 702.121) is granted by the layer-6
    ``grant_keyword`` the parser emits for the second line.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "per_opponent": True, "power": 2, "toughness": 1, "colors": ["R"],
                "subtypes": ["Klingon", "Warrior"], "keywords": ["haste"], "token_name": "Klingon Warrior",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "creatures_you_control", "keywords": ["melee"]})],
        ),
    ]


register("Glory to the Empire!", _glory_to_the_empire)
