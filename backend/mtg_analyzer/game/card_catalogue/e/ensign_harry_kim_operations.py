from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ensign_harry_kim_operations() -> list[AbilitySpec]:
    """Whenever another creature you control enters, if it has greater power than Ensign Kim, put a +1/+1 counter on Ensign Kim.
    {2}, Remove two +1/+1 counters from among creatures you control: Draw a card.

    RULE 603.4: the intervening "if" is evaluated when the entering event is
    matched (``power_vs_reference`` anchored on this source, the same
    relative comparison Mentor uses); unlike Evolve it ignores toughness.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "creature", "controller": "you", "other": True,
                    "filter": {"power_vs_reference": "greater"},
                },
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{2}, remove 2 +1/+1 counters from among creatures you control"},
        ),
    ]


register("Ensign Harry Kim, Operations", _ensign_harry_kim_operations)
