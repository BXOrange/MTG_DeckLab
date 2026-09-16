from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _martial_impetus() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +1/+1 and is goaded.
    Whenever enchanted creature attacks, each other creature that's attacking
    one of your opponents gets +1/+1 until end of turn.

    — Martial Impetus. Documented simplification: the parser/engine has no
    "attacking one of *your* opponents" attacker selector, so the temp pump
    is modeled with the existing ``other_attacking_creatures`` group
    selector (every other attacker). Differs only in a multi-opponent game
    where an attacker is swinging at *you* — rare, and the goad on the
    enchanted creature already pushes it away from you anyway."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1}),
                EffectSpec("goaded", {"affects": "attached_permanent"}),
            ],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"power": 1, "toughness": 1, "selector": "other_attacking_creatures"})],
            trigger={"event": "ATTACKS", "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Martial Impetus", _martial_impetus)
