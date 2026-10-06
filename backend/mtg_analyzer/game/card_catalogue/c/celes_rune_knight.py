from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _celes_rune_knight() -> list[AbilitySpec]:
    """When this creature enters, discard any number of cards, then draw that many cards plus one.
    Whenever one or more other creatures you control enter, if one or more of them entered from a graveyard or was cast from a graveyard, put a +1/+1 counter on each creature you control.

    — PLAY-ALL (Revival Trance). The enters trigger uses `discard` with a bounded up-to-any hand choice and its actual-discard draw rider,
    followed by the extra draw (so it also happens when nothing is discarded). The second ability is
    Kotis's batch trigger (``from_zone_or_cast_from: graveyard``) over a group `add_counters`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("discard", {"count_max": 10000, "then_draw_discarded": True}),
             EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "selector": "each_creature_you_control"})],
            trigger={
                "event": "EVENT_BATCH",
                "condition": {
                    "subject": "group", "controller": "you", "other": True, "filter": {"card_type": "creature"},
                },
                "batch": {"of": EventType.ENTERS_BATTLEFIELD, "min": 1},
                "from_zone_or_cast_from": "graveyard",
            },
        ),
    ]


register("Celes, Rune Knight", _celes_rune_knight)
