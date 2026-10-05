from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _anduril_flame_of_the_west() -> list[AbilitySpec]:
    """Equipped creature gets +3/+1.
    Whenever equipped creature attacks, create two tapped 1/1 white Spirit
    creature tokens with flying. If that creature is legendary, instead
    create two of those tokens that are tapped and attacking.

    Simplified: the "instead tapped and attacking" branch for a legendary
    equipped creature isn't modeled — the tokens always enter merely
    tapped, never already attacking (no primitive yet for a token entering
    mid-combat as an attacker).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 3, "toughness": 1})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 1, "colors": ["W"],
                "subtypes": ["Spirit"], "keywords": ["flying"], "token_name": "Spirit", "tapped": True,
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Andúril, Flame of the West", _anduril_flame_of_the_west)
