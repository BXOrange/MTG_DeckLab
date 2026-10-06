from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _red_xiii_proud_warrior() -> list[AbilitySpec]:
    """Vigilance, trample
    Other modified creatures you control have vigilance and trample. (Equipment, Auras you control, and counters are modifications.)
    Cosmo Memory — When Red XIII enters, return target Aura or Equipment card from your graveyard to your hand.

    — PLAY-ALL (Limit Break). Vigilance and trample are keywords; the grant is the parser's claim (the ``modified`` object filter). The enters trigger is
    `return_from_graveyard` over the new ``graveyard_aura_or_equipment`` kind.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "object_filter": {"modified": True}, "keywords": ["vigilance", "trample"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_aura_or_equipment", "destination": "hand"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Red XIII, Proud Warrior", _red_xiii_proud_warrior)
