from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ninja_pizza() -> list[AbilitySpec]:
    """Foods gain a sacrifice mana ability; create a Food each second main phase."""
    return [
        AbilitySpec("static", [EffectSpec("grant_mana_ability", {
            "affects": "permanents_you_control", "object_filter": {"subtype": "food"},
            "granted_mana_cost": "{T}, sacrifice ~",
            "mana": [{color: 1} for color in "WUBRG"],
        })]),
        AbilitySpec("triggered", [EffectSpec("create_token", {"token_name": "Food", "count": 1})],
                    trigger={"event": "STEP_BEGIN", "filter": {"step": "main2"}, "phase_relation": "you"}),
    ]


register('Ninja Pizza', _ninja_pizza)
