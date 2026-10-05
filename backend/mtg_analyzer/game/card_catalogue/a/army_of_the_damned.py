from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _army_of_the_damned() -> list[AbilitySpec]:
    """Create thirteen tapped 2/2 black Zombie creature tokens.
    Flashback {7}{B}{B}{B}

    — PLAY-ALL Step 2 (Wretched Ranks). Flashback is a printed keyword; the body is a plain tapped `create_token`.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("create_token", {
        "count": 13, "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Zombie"],
        "token_name": "Zombie", "tapped": True,
    })])]


register("Army of the Damned", _army_of_the_damned)
