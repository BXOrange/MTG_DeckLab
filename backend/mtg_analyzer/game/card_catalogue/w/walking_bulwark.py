from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _walking_bulwark() -> list[AbilitySpec]:
    """Defender
    {2}: Until end of turn, target creature with defender gains haste, can attack as though it didn't have defender, and assigns combat damage equal to its toughness rather than its power. Activate only as a sorcery.

    — PLAY-ALL (Abzan Armor). Defender is a keyword. One targeted `pump` (haste) on a creature with defender, then two
    `combat_restriction_this_turn` clauses over the same creature (``previous_subject``): the defender permission and
    the toughness-damage rule.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("pump", {
                    "power": 0, "toughness": 0, "keywords": ["haste"],
                    "target_kind": "creature", "creature_filter": {"keyword": "defender"},
                }),
                EffectSpec("combat_restriction_this_turn", {
                    "restriction": {"kind": "attacks_as_though_no_defender"}, "previous_subject": True,
                }),
                EffectSpec("combat_restriction_this_turn", {
                    "restriction": {"kind": "damage_uses_toughness"}, "previous_subject": True,
                }),
            ],
            cost={"text": "{2}", "sorcery_speed_only": True},
        ),
    ]


register("Walking Bulwark", _walking_bulwark)
