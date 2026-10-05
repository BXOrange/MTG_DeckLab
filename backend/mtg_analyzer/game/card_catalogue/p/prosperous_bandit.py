from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _prosperous_bandit() -> list[AbilitySpec]:
    """Offspring {1} (You may pay an additional {1} as you cast this spell. If you do, when this
    creature enters, create a 1/1 token copy of it.)
    First strike
    Whenever this creature deals combat damage to a player, create that many tapped Treasure tokens.

    — Animated Army deck batch. Offspring is the engine's RULE 702.175 keyword (`_kw_offspring`) and
    first strike a plain keyword. The damage trigger is `create_token` whose count reads the
    firing DAMAGE event's own ``amount`` (the `trigger_event` operand), entering tapped.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Treasure", "tapped": True,
                "count": {"kind": "trigger_event", "field": "amount"},
            })],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Prosperous Bandit", _prosperous_bandit)
