from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "three or more lands with the same name".
_SAME_NAME_LANDS = 3


def _endless_atlas() -> list[AbilitySpec]:
    """{2}, {T}: Draw a card. Activate only if you control three or more lands with the same name.

    — PLAY-ALL (Calling All Angels). A plain draw activation gated by ``activation_condition`` on the new
    `control_same_name_at_least` (the largest group of same-named lands you control reaches three).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{2}, {T}", "activation_condition": {
                "kind": "control_same_name_at_least", "card_type": "land", "min": _SAME_NAME_LANDS,
            }},
        ),
    ]


register("Endless Atlas", _endless_atlas)
