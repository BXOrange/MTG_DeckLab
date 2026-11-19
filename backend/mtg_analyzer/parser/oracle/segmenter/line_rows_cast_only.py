"""Segmenter: "Cast this spell only ..." restrictions (PAR-290).

RULE 601.3 / 101.2: a printed "cast this spell only <during a window | if a condition>" removes legal casts for exactly
this spell; it never grants one. The two shapes ride the spec fields the engine already enforces in `GameEngine.can_cast`:

* a window -> ``cast_timing_restriction`` (whose turn, and optionally which step), read by `cast_timing`;
* a condition -> ``cast_condition``, a shared-vocabulary condition (``static_condition``) judged live against the board at
  the cast attempt (`condition_query.free_cast_condition_holds`).

A window or condition the closed vocabulary cannot read leaves the whole line unclaimed (fail closed).
"""

from __future__ import annotations

import re
from typing import Optional

from ..catalogue.static_handlers import static_condition
from ..spec import AbilitySpec
from .line_types import LineContext
from .segment_types import Segment

#: Printed window -> ``cast_timing_restriction``. A step name is a `game/phases.py` step; a bare turn key restricts whose
#: turn (RULE 500.1) without naming a step.
CAST_ONLY_WINDOWS: dict[str, dict] = {
    "during your turn": {"your_turn": True},
    "during an opponent's turn": {"opponents_turn": True},
    "during your end step": {"step": "end", "your_turn": True},
    "during an opponent's upkeep": {"step": "upkeep", "opponents_turn": True},
    "during the declare attackers step": {"step": "declare_attackers"},
    "during your declare attackers step": {"step": "declare_attackers", "your_turn": True},
}
_CAST_ONLY_WINDOW_RE = re.compile(
    r"^cast this spell only (?P<window>" + "|".join(map(re.escape, CAST_ONLY_WINDOWS)) + r")\.?$", re.IGNORECASE,
)
_CAST_ONLY_IF_RE = re.compile(r"^cast this spell only if (?P<condition>.+?)\.?$", re.IGNORECASE)


def line_cast_only_window_or_condition(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    window = _CAST_ONLY_WINDOW_RE.fullmatch(raw)
    if window is not None:
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[], cast_timing_restriction=dict(CAST_ONLY_WINDOWS[window.group("window").lower()]),
            raw_text=raw, parser=ctx.provenance,
        ), claimed=True)
    cond = _CAST_ONLY_IF_RE.fullmatch(raw)
    if cond is not None:
        condition = static_condition(cond.group("condition"))
        if condition is not None:
            return Segment(raw=raw, spec=AbilitySpec(
                "spell_effect", effects=[], cast_condition=condition, raw_text=raw, parser=ctx.provenance,
            ), claimed=True)
    return None
