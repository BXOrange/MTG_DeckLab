from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _frilled_deathspitter() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, it deals 2 damage
    to target opponent or planeswalker.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "target_kind": "opponent_or_planeswalker"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
        ),
    ]


register("Frilled Deathspitter", _frilled_deathspitter)
