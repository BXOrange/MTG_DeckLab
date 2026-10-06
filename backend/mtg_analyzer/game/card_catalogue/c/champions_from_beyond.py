from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _champions_from_beyond() -> list[AbilitySpec]:
    """When this enchantment enters, create X 1/1 colorless Hero creature tokens.
    Light Party — Whenever you attack with four or more creatures, scry 2, then draw a card.
    Full Party — Whenever you attack with eight or more creatures, those creatures get +4/+4 until end of turn.

    — PLAY-ALL (Scions & Spellcraft). The ETB and Light Party are the parser's. Full Party is Light Party's
    ``attackers_declared`` head with ``min`` 8 over a `pump` of the ``attacking_creatures_you_control`` group.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": "x", "power": 1, "toughness": 1, "colors": [], "subtypes": ["Hero"], "keywords": [],
                "token_name": "Hero",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("scry", {"count": 2}), EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                "attackers_declared": {"filter": {"card_type": "creature"}, "min": 4},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"power": 4, "toughness": 4, "selector": "attacking_creatures_you_control"})],
            trigger={
                "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                "attackers_declared": {"filter": {"card_type": "creature"}, "min": 8},
            },
        ),
    ]


register("Champions from Beyond", _champions_from_beyond)
