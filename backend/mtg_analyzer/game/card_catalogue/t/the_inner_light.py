from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_inner_light() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
    I — Return target green or white creature card from your graveyard to the battlefield.
    II — Choose target creature. Whenever it deals combat damage to a player this turn, you draw that many cards.
    III — You gain life equal to the greatest power among creatures you control. Create a Treasure token.

    RULE 603.7: chapter II creates a delayed trigger on the chosen creature
    for this turn only; "that many" is the damage event's ``amount``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "battlefield", "colors": ["G", "W"],
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_turn_trigger", {
                "trigger": {"event": "DAMAGE", "condition": {"subject": "self"},
                            "filter": {"combat": True, "is_player": True}},
                "effects": [{"type": "draw", "params": {"count_from_trigger_event": "amount"}}],
                "optional": False, "target_kind": "creature",
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("bind", {
                    "name": "n",
                    "amount": {"kind": "count_selector", "selector": {
                        "zone": "battlefield", "of": "you", "filter": {"card_type": "creature"},
                        "aggregate": "max", "value": "power"}},
                    "effects": [{"type": "gain_life", "params": {"amount": "$n"}}],
                }),
                EffectSpec("create_token", {"count": 1, "token_name": "Treasure"}),
            ],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [3]},
        ),
    ]


register("The Inner Light", _the_inner_light)
