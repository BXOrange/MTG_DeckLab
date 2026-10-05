from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _case_of_the_ransacked_lab() -> list[AbilitySpec]:
    """Instant and sorcery spells you cast cost {1} less to cast.
    To solve — You've cast four or more instant and sorcery spells this turn.
    (If unsolved, solve at the beginning of your end step.)
    Solved — Whenever you cast an instant or sorcery spell, draw a card.

    — PLAY-ALL Step 2 (yshtola). The discount and the solved draw trigger
    are the parser's own claims, reproduced verbatim; the card was held back
    only by the solve condition, which the segmenter's `_TO_SOLVE_RE` shape
    (`become_solved` on your end step, RULE 719.3a/702.169) takes as an
    ``active_if``. That condition is a ``control_count`` over the new
    ``instant_and_sorcery_spells_cast_this_turn`` selector
    (`continuous.count_selector`), read off the per-turn event history.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "increase": False, "spell_type": ["instant", "sorcery"]})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("become_solved", {})],
            trigger={
                "event": "STEP_BEGIN", "filter": {"step": "end"}, "phase_relation": "you",
                "active_if": {
                    "kind": "control_count",
                    "selector": "instant_and_sorcery_spells_cast_this_turn", "min": 4,
                },
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_filter": {"card_type_any": ["instant", "sorcery"]},
                "active_if": {"kind": "source_solved"},
            },
        ),
    ]


register("Case of the Ransacked Lab", _case_of_the_ransacked_lab)
