from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _within_range() -> list[AbilitySpec]:
    """When this enchantment enters, create two 1/1 red Warrior creature tokens.
    Whenever you attack, each opponent loses life equal to the number of creatures attacking them.

    — Within Range. `PLAYER_ATTACKED` fires once per defending player with ``count`` = the creatures of the
    attacker attacking *that player* (not a planeswalker), so one trigger per attacked opponent makes exactly
    that opponent lose ``count`` life; an opponent no creature attacks loses 0 either way. The only visible
    difference from the printed single trigger is one stack object per attacked opponent.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 1, "colors": ["R"], "subtypes": ["Warrior"],
                "token_name": "Warrior",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "amount": {"kind": "trigger_event", "field": "count"},
                "player": {"of": "attacked_player"},
            })],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {"subject": "you"}},
        ),
    ]


register("Within Range", _within_range)
