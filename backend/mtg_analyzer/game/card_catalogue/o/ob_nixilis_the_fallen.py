from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ob_nixilis_the_fallen() -> list[AbilitySpec]:
    """Landfall — Whenever a land you control enters, you may have target player lose 3 life. If you do, put three
    +1/+1 counters on Ob Nixilis, the Fallen.

    — PLAY-ALL Step 2 (Sultai Arisen). The parser's "target player loses 3 life" shape (`lose_life` with its own
    player target, RULE 601.2c) plus the self counters, on a triggered spec with ``optional=True`` ("you may"): "if
    you do" is the body only running once the controller accepts, so declining skips both the loss and the counters.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 3, "target_kind": "player"}),
                EffectSpec("add_counters", {"count": 3, "kind": "+1/+1"}),
            ],
            optional=True,
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
            },
        ),
    ]


register("Ob Nixilis, the Fallen", _ob_nixilis_the_fallen)
