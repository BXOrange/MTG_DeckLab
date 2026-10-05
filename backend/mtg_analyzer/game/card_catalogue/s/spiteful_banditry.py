from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spiteful_banditry() -> list[AbilitySpec]:
    """When this enchantment enters, it deals X damage to each creature.
    Whenever one or more creatures your opponents control die, you create
    a Treasure token. This ability triggers only once each turn.

    — Spiteful Banditry. New `DealDamageEffect.x_multiplier` (the
    `AddCountersEffect` primitive's own sibling) for the ETB's announced
    {X}. The "one or more … die" aggregate quantifier is approximated by
    an ordinary per-creature DIES group trigger plus the printed "only
    once each turn" cap (``trigger["limit"]``) — both shapes create at
    most one Treasure per turn regardless of how many opponent creatures
    die simultaneously, so the board outcome is identical either way.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"x_multiplier": 1, "selector": "each_creature"})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature", "controller": "not_you"},
                "limit": True,
            },
        ),
    ]


register("Spiteful Banditry", _spiteful_banditry)
