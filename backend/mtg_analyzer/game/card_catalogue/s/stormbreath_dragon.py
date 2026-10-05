from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stormbreath_dragon() -> list[AbilitySpec]:
    """Flying, haste, protection from white
    {5}{R}{R}: Monstrosity 3. (If this creature isn't monstrous, put three +1/+1 counters on it and it becomes monstrous.)
    When this creature becomes monstrous, it deals damage to each opponent equal to the number of cards in that player's hand.

    — PLAY-ALL Step 2 (Temur Roar). Flying/haste/protection are keywords and
    Monstrosity is the parser's own claim. The trigger is a `for_each` over
    each opponent whose body `bind`s that player's own hand size (the
    iteration item is the body's target) into a player-targeted damage, so
    each opponent takes damage equal to *their* hand rather than one shared
    number.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("monstrosity", {"amount": 3})],
            cost={"text": "{5}{r}{r}"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("for_each", {
                "over": {"players": "each_opponent"},
                "effects": [{"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "resource", "resource": "hand_size", "of": "target"},
                    "effects": [{"type": "damage", "params": {"amount": "$n", "target_kind": "player"}}],
                }}],
            })],
            trigger={"event": EventType.BECAME_MONSTROUS, "condition": {"subject": "self"}},
        ),
    ]


register("Stormbreath Dragon", _stormbreath_dragon)
