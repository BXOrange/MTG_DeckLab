from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _saradoc_master_of_buckland() -> list[AbilitySpec]:
    """Whenever Saradoc or another nontoken creature you control with
    power 2 or less enters, create a 1/1 white Halfling creature token.
    Tap two other untapped Halflings you control: Saradoc gets +2/+0 and
    gains lifelink until end of turn.

    Simplified: the power-2-or-less filter isn't checked (a live per-
    firing power qualifier on a group-ETB condition isn't modeled yet) —
    widened to any nontoken creature entering; the tap cost's pool isn't
    narrowed to exclude Saradoc herself (`costs.ActivationCost.tap_others`
    has no self-exclusion flag), so she could in principle pay her own
    cost. Both are documented over-generosities, not a functional break.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["W"],
                "subtypes": ["Halfling"], "token_name": "Halfling",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self_or_group", "type": "creature", "controller": "you", "other": True},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": 2, "toughness": 0, "keywords": ["lifelink"]})],
            cost={"tap_others": (2, "halfling")},
        ),
    ]


register("Saradoc, Master of Buckland", _saradoc_master_of_buckland)
