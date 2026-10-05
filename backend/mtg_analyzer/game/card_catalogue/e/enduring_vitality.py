from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _enduring_vitality() -> list[AbilitySpec]:
    """Vigilance
    Creatures you control have "{T}: Add one mana of any color."
    When Enduring Vitality dies, if it was a creature, return it to the
    battlefield under its owner's control. It's an enchantment. (It's not
    a creature.)

    — MEC-12 (cEDH Kinnan). Vigilance and the granted mana ability are
    both already parser-claimed for free (`reuse` confirms it — restated
    here since registering the name turns that fallback off for every
    ability, not just the unclaimed one). The dies-trigger is the new
    `dies_return_as_enchantment`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keyword": "vigilance", "affects": "self"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "creatures_you_control", "mana": [{"C": 1}],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("dies_return_as_enchantment", {})],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
        ),
    ]


register("Enduring Vitality", _enduring_vitality)
