from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wrecking_ball_arm() -> list[AbilitySpec]:
    """Equipped creature has base power and toughness 7/7 and can't be blocked by creatures with power 2 or less.
    Equip legendary creature {3}
    Equip {7}

    — PLAY-ALL (Limit Break). `pt_set` 7/7 and Kithkin Armor's ``cant_be_blocked_by`` restriction (``max_power`` 2) on the attached permanent. The ordinary
    ``Equip {7}`` is the keyword's; "Equip legendary creature {3}" is a second, coexisting equip ability restricted by ``creature_filter`` (Commander's
    Plate's shape, `legendary` key).
    """
    return [
        AbilitySpec("static", [EffectSpec("pt_set", {"affects": "attached_permanent", "power": 7, "toughness": 7})]),
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "kind": "cant_be_blocked_by", "filter": {"max_power": 2}, "affects": "attached_permanent",
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("attach", {"target_kind": "creature", "creature_filter": {"legendary": True}})],
            cost={"text": "{3}", "sorcery_speed_only": True},
        ),
    ]


register("Wrecking Ball Arm", _wrecking_ball_arm)
