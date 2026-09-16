from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Intermediate Chirography (hand-authored Class) — PAR-60
# ===========================================================================
# The parser already claims 4 of 5 clauses; only the level-3 "modified
# creature died" end-step trigger was a gap. Hand-authored as a full Class
# instead (the parser's own Class shapes: a ``class_level`` level-up
# activated ability per level + ``min_level``/``level_counter="class_level"``
# gates on each body ability). The level-3 body self-gates on the new
# `GameState.modified_creatures_died_this_turn` tracker.


_INKLING = {
    "count": 1, "token_name": "Inkling", "power": 2, "toughness": 1,
    "colors": ["W", "B"], "subtypes": ["Inkling"], "keywords": ["flying"],
}


def _intermediate_chirography() -> list[AbilitySpec]:
    """(Gain the next level as a sorcery to add its ability.)
    When this Class enters, create a 2/1 white and black Inkling creature
    token with flying.
    {1}{B}: Level 2
    Whenever you lose life for the first time each turn, put a +1/+1 counter
    on target creature you control.
    {2}{B}: Level 3
    At the beginning of each end step, if a modified creature died under your
    control this turn, create a 2/1 white and black Inkling creature token
    with flying."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", dict(_INKLING))],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": 2})],
            cost={"text": "{1}{B}", "sorcery_speed_only": True, "class_level": 2},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1",
                                         "target_kind": "creature_you_control"})],
            trigger={
                "event": "LIFE_LOST", "condition": {"subject": "you"}, "limit": True,
                "min_level": 2, "level_counter": "class_level",
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": 3})],
            cost={"text": "{2}{B}", "sorcery_speed_only": True, "class_level": 3},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("intermediate_chirography_l3", {})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "min_level": 3, "level_counter": "class_level",
            },
        ),
    ]


register("Intermediate Chirography", _intermediate_chirography)
