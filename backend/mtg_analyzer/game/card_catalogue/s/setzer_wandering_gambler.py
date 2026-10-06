from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "create 2 tapped Treasure tokens".
_TREASURES = 2


def _setzer_wandering_gambler() -> list[AbilitySpec]:
    """When this creature enters, create the Blackjack, a legendary 3/3 colorless Vehicle artifact token with flying and crew 2.
    Whenever a Vehicle you control deals combat damage to a player, flip a coin.
    Whenever you win a coin flip, create two tapped Treasure tokens.

    — PLAY-ALL (Revival Trance). The Blackjack is a legendary Vehicle token (Pia Nalaar's ``vehicle`` shape, with Crew from its
    text). **Simplification:** the two coin clauses are one trigger — a Vehicle's combat damage flips a coin whose winning branch
    creates the Treasures (`coin_flip`); a coin won through some other effect does not trigger Setzer.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 3, "toughness": 3, "colors": [], "subtypes": ["Vehicle"], "legendary": True,
                "keywords": ["flying", "Crew"], "is_artifact": True, "vehicle": True,
                "token_name": "The Blackjack", "oracle_text": "Flying\nCrew 2",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("coin_flip", {"win_effects": [
                {"type": "create_token", "params": {"token_name": "Treasure", "count": _TREASURES, "tapped": True}},
            ]})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "controller": "you", "other": False, "filter": {"subtype": "vehicle"}},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Setzer, Wandering Gambler", _setzer_wandering_gambler)
