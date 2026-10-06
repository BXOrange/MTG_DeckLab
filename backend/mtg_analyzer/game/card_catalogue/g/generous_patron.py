from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _generous_patron() -> list[AbilitySpec]:
    """When this creature enters, support 2. (Put a +1/+1 counter on each of up to two other target creatures.)
    Whenever you put one or more counters on a creature you don't control, draw a card.

    — PLAY-ALL (Counter Blitz). Support is the parser's own claim (reproduced). The draw is the Hapatra `COUNTER` shape (``by_you``) with
    the new ``recipient_not_you`` filter key (the counters' recipient is controlled by someone else).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "+1/+1", "target_kind": "creature", "target_count": 2, "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.COUNTER,
                "filter": {"recipient_is_creature": True, "by_you": True, "recipient_not_you": True},
            },
        ),
    ]


register("Generous Patron", _generous_patron)
