from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bident_of_thassa() -> list[AbilitySpec]:
    """Whenever a creature you control deals combat damage to a player, you may draw a card.
    {1}{U}, {T}: Creatures your opponents control attack this turn if able.

    — Family Matters deck batch. The draw is the parser's own claim. The activation is a resolve-time
    `grant_until` of the synthetic ``attacks_if_able`` flag over the creatures your opponents control at that
    moment (``lock_group``, RULE 611.2c), until end of turn.
    """
    return [
        AbilitySpec(
            "triggered", [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.DAMAGE,
                     "condition": {"subject": "group", "controller": "you", "other": False,
                                   "filter": {"card_type": "creature"}},
                     "filter": {"combat": True, "is_player": True}},
            optional=True,
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "grant_keyword", "params": {
                    "affects": "creatures_opponents_control", "keywords": ["attacks_if_able"]}},
                "duration": "end_of_turn", "target_kind": None, "lock_group": True,
            })],
            cost={"text": "{1}{U}, {T}"},
        ),
    ]


register("Bident of Thassa", _bident_of_thassa)
