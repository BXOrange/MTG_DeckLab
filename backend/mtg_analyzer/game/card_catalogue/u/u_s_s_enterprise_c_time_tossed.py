from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _u_s_s_enterprise_c_time_tossed() -> list[AbilitySpec]:
    """When U.S.S. Enterprise-C enters or dies, you may discard your hand. If you do, draw a card for each card discarded this way.
    Station (Tap another creature you control: Put charge counters equal to its power on this Spacecraft. Station only as a sorcery. It's an artifact creature at 3+.)
    3+ | Flying

    RULE 701.9a: "a card for each card discarded this way" is the
    ``discarded_this_way`` tally of this resolution's discard, inside an
    ``optional`` wrapper for the "you may". Station and the 3+ rows (RULE 721) are the
    parser-claimed statics.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("optional", {"effects": [
                {"type": "mark_event_log", "params": {}},  # opens the "this way" window (RULE 608.2c)
                {"type": "discard", "params": {"whole_hand": True}},
                {"type": "draw", "params": {"count": {"kind": "discarded_this_way"}}},
            ]})],
            trigger={"event": [EventType.ENTERS_BATTLEFIELD, EventType.DIES], "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "keywords": ["flying"], "affects": "self", "min_level": 3, "level_counter": "charge",
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "add_types": ["creature"], "affects": "self", "min_level": 3,
                "level_counter": "charge", "power": 6, "toughness": 6,
            })],
        ),
    ]


register("U.S.S. Enterprise-C, Time-Tossed", _u_s_s_enterprise_c_time_tossed)
