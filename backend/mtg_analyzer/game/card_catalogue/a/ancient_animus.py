from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ancient_animus() -> list[AbilitySpec]:
    """Put a +1/+1 counter on target creature you control if it's legendary.
    Then it fights target creature an opponent controls. (Each deals damage
    equal to its power to the other.)

    — PLAY-ALL Step 2 (Kodama). Two clauses on one first target: the
    counter is `add_counters` on a ``creature_you_control`` target gated by an
    effect-level ``is_legendary`` condition read off that target
    (`static_conditions`' RULE 205.4a predicate, ``of: target``), and "it
    fights" is `fight` with ``fighter_kind="previous_target"`` — the
    "pronoun pointing back at the previous clause's target" the fight effect
    already supports — so the spell announces only the two real targets.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec(
                    "add_counters", {"count": 1, "kind": "+1/+1", "target_kind": "creature_you_control"},
                    condition={"kind": "is_legendary", "of": "target"},
                ),
                EffectSpec("fight", {"fighter_kind": "previous_target", "other_kind": "creature_you_dont_control"}),
            ],
        )
    ]


register("Ancient Animus", _ancient_animus)
