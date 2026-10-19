from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _liliana_dreadhorde_general() -> list[AbilitySpec]:
    """Whenever a creature you control dies, draw a card.
    +1: Create a 2/2 black Zombie creature token.
    −4: Each player sacrifices two creatures of their choice.
    −9: Each opponent chooses a permanent they control of each permanent
    type and sacrifices the rest.

    The final ability shares per-type keeper selections with the generic
    choose-player-objects effect. All selections finish before sacrifice;
    a multitype permanent may fill several slots and remains in the union
    of kept visits (RULE 608.2e).
    """
    types = ["battle", "planeswalker", "creature", "land", "artifact", "enchantment"]
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "type": "creature", "controller": "you", "other": False},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["B"],
                "subtypes": ["Zombie"], "keywords": [], "token_name": "Zombie",
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("sacrifice", {"selector": "each_player", "what": "creature", "count": 2})],
            cost={"loyalty": -4},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("choose_player_objects", {
                "action": "sacrifice_rest", "player_scope": "each_opponent", "keep_types": types,
            })],
            cost={"loyalty": -9},
        ),
    ]


register("Liliana, Dreadhorde General", _liliana_dreadhorde_general)
