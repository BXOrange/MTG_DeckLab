from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spoils_of_blood() -> list[AbilitySpec]:
    """Spoils of Blood (Instant, {B})

    "Create an X/X black Horror creature token, where X is the number of
    creatures that died this turn."

    a `bind` over `continuous.count_selector`'s ``"creatures_died_this_turn"`` entry
    (MEC-43 round 4C) — the X/X token sized off a live board count.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("bind", {
                "name": "x",
                "amount": {"kind": "count_selector", "selector": "creatures_died_this_turn"},
                "effects": [{"type": "create_token", "params": {
                    "count": 1, "colors": ["B"], "subtypes": ["Horror"],
                    "power": "$x", "toughness": "$x",
                }}],
            })],
        )
    ]


register("Spoils of Blood", _spoils_of_blood)
