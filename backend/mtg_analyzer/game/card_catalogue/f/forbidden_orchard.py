from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _forbidden_orchard() -> list[AbilitySpec]:
    """{T}: Add one mana of any color.
    Whenever you tap this land for mana, target opponent creates a 1/1
    colorless Spirit creature token.

    **Documented simplification**: "target opponent" becomes every
    opponent (`CreateTokenEffect`'s ``each_opponent`` creator) — no single-
    opponent target choice for a land-tap trigger yet; correct in 1v1,
    an overstatement in multiplayer.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "creators": "each_opponent", "power": 1, "toughness": 1,
                "colors": [], "subtypes": ["Spirit"], "token_name": "Spirit",
            })],
            trigger={"event": EventType.TAPPED_FOR_MANA, "condition": {"subject": "self"}},
        )
    ]


register("Forbidden Orchard", _forbidden_orchard)
