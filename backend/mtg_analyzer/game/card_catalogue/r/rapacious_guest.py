from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rapacious_guest() -> list[AbilitySpec]:
    """Menace
    Whenever one or more creatures you control deal combat damage to a
    player, create a Food token.
    Whenever you sacrifice a Food, put a +1/+1 counter on this creature.
    When this creature leaves the battlefield, target opponent loses life
    equal to its power.

    Simplified: the first trigger is capped at once per turn
    (`trigger["limit"]`) — see Meriadoc Brandybuck's own note on RULE
    603.3b's "any number of X" aggregate-once shape.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {
                    "subject": "group", "type": "creature",
                    "controller": "you", "other": False,
                },
                "filter": {"combat": True, "is_player": True},
                "limit": True,
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {})],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "food",
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"target_kind": "player", "amount_from_trigger_event": "power"})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Rapacious Guest", _rapacious_guest)
