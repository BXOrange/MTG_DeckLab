from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _void_winnower() -> list[AbilitySpec]:
    """Your opponents can't cast spells with even mana values. (Zero is
    even.)
    Your opponents can't block with creatures with even mana values.

    — MEC-12 (cEDH Kinnan). Two new filter keys, both keyed off "Zero is
    even": `cast_prohibition`'s new ``even_mana_value`` param
    (`continuous.cast_prohibited`) for the cast-side clause, and
    `combat.matches_object_filter`'s new ``even_mana_value`` key (checked
    against the *blocker itself* via the new `cant_block_self_filtered`
    combat-restriction kind — every existing blocker-side kind filters the
    *attacker*, which isn't what this card's blocker-own-characteristics
    restriction needs) for the block-side one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents", "even_mana_value": True,
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "kind": "cant_block_self_filtered",
                "filter": {"even_mana_value": True},
                "affects": "creatures_opponents_control",
            })],
        ),
    ]


register("Void Winnower", _void_winnower)
