from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _assault_formation() -> list[AbilitySpec]:
    """Each creature you control assigns combat damage equal to its toughness rather than its power.
    {G}: Target creature with defender can attack this turn as though it didn't have defender.
    {2}{G}: Creatures you control get +0/+1 until end of turn.

    — PLAY-ALL (Abzan Armor). The toughness damage static and the group pump are the parser's. The defender permission is
    `combat_restriction_this_turn` with ``attacks_as_though_no_defender`` (RULE 508.1a — the same restriction kind the
    standing "can attack as though it didn't have defender" statics use) on a target creature that has defender.
    """
    return [
        AbilitySpec("static", [EffectSpec("combat_restriction", {
            "kind": "damage_uses_toughness", "affects": "creatures_you_control",
        })]),
        AbilitySpec(
            "activated",
            [EffectSpec("combat_restriction_this_turn", {
                "restriction": {"kind": "attacks_as_though_no_defender"},
                "target_kind": "creature", "creature_filter": {"keyword": "defender"},
            })],
            cost={"text": "{G}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 1,
                "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
            })],
            cost={"text": "{2}{G}"},
        ),
    ]


register("Assault Formation", _assault_formation)
