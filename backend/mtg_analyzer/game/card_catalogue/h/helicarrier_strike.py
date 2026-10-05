from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _helicarrier_strike() -> list[AbilitySpec]:
    """Teamwork 2 (As an additional cost to cast this spell, you may tap
    any number of creatures you control with total power 2 or more.)
    Helicarrier Strike deals 2 damage to target attacking or blocking
    creature. If this spell was cast using teamwork, it deals 4 damage to
    that creature instead.

    — PAR-68. A magnitude-only override (same target either way) — the
    RULE 702.194b sibling of `DealDamageEffect.amount_if_kicked`/
    `amount_if_bargained`'s existing "instead" overrides, new
    `amount_if_teamwork` param. Unlike Cruel Alliance/Too Evil to Stay
    Dead/Earth's Mightiest Heroes (still open, MEC-85), this card's
    "instead" clause never changes *which* targets are legal or *how many*
    get chosen, so no new targeting primitive was needed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": 2, "amount_if_teamwork": 4,
                "target_kind": "attacking_or_blocking_creature",
            })],
        ),
    ]


register("Helicarrier Strike", _helicarrier_strike)
