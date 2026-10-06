from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lulu_stern_guardian() -> list[AbilitySpec]:
    """Whenever an opponent attacks you, choose target creature attacking you. Put a stun counter on that creature.
    {3}{U}: Proliferate. (Choose any number of permanents and/or players, then give each another counter of each kind already there.)

    — PLAY-ALL (Counter Blitz). The attack trigger is Tomik's `PLAYER_ATTACKED` head (``defender_is_you``, an opponent attacking) over a stun
    `add_counters` on an attacking creature an opponent controls. **Simplification:** at a table with several opponents the target may
    be a creature attacking someone else (no "attacking you" target filter exists). The proliferate is the parser's own claim.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "stun", "target_kind": "creature_you_dont_control",
                "creature_filter": {"attacking": True},
            })],
            trigger={
                "event": EventType.PLAYER_ATTACKED,
                "condition": {"subject": "group", "controller": "not_you"},
                "defender_is_you": True,
            },
        ),
        AbilitySpec("activated", [EffectSpec("proliferate", {})], cost={"text": "{3}{u}"}),
    ]


register("Lulu, Stern Guardian", _lulu_stern_guardian)
