from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _righteous_aura() -> list[AbilitySpec]:
    """{W}, Pay 2 life: The next time a source of your choice would deal
    damage to you this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"text": "{W}, Pay 2 life"},
        ),
    ]


register("Righteous Aura", _righteous_aura)
