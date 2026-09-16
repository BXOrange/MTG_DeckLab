from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _acererak_the_archlich() -> list[AbilitySpec]:
    """When Acererak enters, if you haven't completed Tomb of Annihilation,
    return Acererak to its owner's hand and venture into the dungeon.
    Whenever Acererak attacks, for each opponent, you create a 2/2 black
    Zombie creature token unless that player sacrifices a creature of
    their choice.

    — MEC-43. The ETB combines the new ``not_completed_dungeon`` RULE
    603.4 intervening-if (reading `Player.completed_dungeons`, RULE 309.7)
    with the already-shipped self-bounce + `venture` effects. The attack
    trigger is `EachPlayerPayOrEffect`'s new ``scope="each_opponent"``/
    ``effect_targets="controller"`` combination — every opponent
    independently chooses whether to sacrifice, and only a decliner's
    absence of payment lets Acererak's own controller make the token,
    never the decliner themselves.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_to_hand", {"target_kind": None}),
                EffectSpec("venture", {}),
            ],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
                "not_completed_dungeon": "Tomb of Annihilation",
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("each_player_pay_or", {
                "cost": "Sacrifice a creature",
                "scope": "each_opponent",
                "effect_targets": "controller",
                "effects": [{
                    "type": "create_token",
                    "params": {
                        "count": 1, "power": 2, "toughness": 2, "colors": ["B"],
                        "subtypes": ["Zombie"], "token_name": "Zombie",
                    },
                }],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Acererak the Archlich", _acererak_the_archlich)
