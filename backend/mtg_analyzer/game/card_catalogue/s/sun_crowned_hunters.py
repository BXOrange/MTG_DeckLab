from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sun_crowned_hunters() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, it deals 3 damage
    to target opponent or planeswalker.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 3, "target_kind": "opponent_or_planeswalker"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
        ),
    ]


register("Sun-Crowned Hunters", _sun_crowned_hunters)
