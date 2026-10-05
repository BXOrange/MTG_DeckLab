from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tangleweave_armor() -> list[AbilitySpec]:
    """Living weapon (When this Equipment enters, create a 0/0 black Phyrexian Germ creature token,
    then attach this to it.)
    Equipped creature gets +X/+X, where X is the greatest mana value among your commanders.
    Equip {4}

    — Tramplesaurus Rex deck batch. Living weapon and Equip are keywords. The bonus is a per-count
    `anthem` over the attached permanent: the ``greatest_commander_mana_value`` selector (Tevesh
    Szat's reader) scales both stats.
    """
    return [
        AbilitySpec("static", [EffectSpec("anthem", {
            "affects": "attached_permanent", "power": 1, "toughness": 1,
            "power_count": "greatest_commander_mana_value", "toughness_count": "greatest_commander_mana_value",
        })]),
    ]


register("Tangleweave Armor", _tangleweave_armor)
