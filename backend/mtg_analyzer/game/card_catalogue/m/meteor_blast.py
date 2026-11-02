
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _meteor_blast() -> list[AbilitySpec]:
    """Meteor Blast deals 4 damage to each of X targets.

    RULE 601.2c: the spell has exactly X targets (any target), where X is the
    announced value. The clause is a `damage` whose `TargetSpec.count_selector`
    is ``source_x_paid`` (the same announce-time read Icy Blast's "tap X target
    creatures" uses, `GameObject.x_paid`), and every chosen target takes the full
    4 (RULE 120.3 — no division, unlike Fireball-style divided damage).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": 4, "target_kind": "any", "count": 10, "count_selector": "source_x_paid",
            })],
        ),
    ]


register("Meteor Blast", _meteor_blast)
