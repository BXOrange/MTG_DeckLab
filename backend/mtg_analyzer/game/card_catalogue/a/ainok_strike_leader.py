from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ainok_strike_leader() -> list[AbilitySpec]:
    """Whenever you attack with this creature and/or your commander, for each opponent, create a 1/1 red Goblin creature token that's tapped and attacking that player.
    Sacrifice this creature: Creature tokens you control gain indestructible until end of turn.

    — Ainok Strike Leader. The head is `ATTACKERS_DECLARED` with an `any_of` attacker filter: at least one
    declared attacker is this creature (`is_reference`) or a commander (`is_commander`). The body is Adeline's
    per-opponent tapped-and-attacking token. The ability is a keyword-granting group `pump` over a structured
    "creature tokens you control" selector.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["R"], "subtypes": ["Goblin"],
                "token_name": "Goblin", "per_opponent": True, "tapped": True, "attacking": True,
            })],
            trigger={
                "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                "attackers_declared": {
                    "filter": {"any_of": [{"is_reference": True}, {"is_commander": True}]}, "min": 1,
                },
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "keywords": ["indestructible"],
                "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "token": True}},
            })],
            cost={"text": "Sacrifice ~"},
        ),
    ]


register("Ainok Strike Leader", _ainok_strike_leader)
