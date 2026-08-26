"""RULE 702.33b Kicker's own ``{X}`` payment restriction (docs/09, PAR-7).

Mirrors `catalogue/counters.py`'s split: "Spend only colored mana on X. No
more than one mana of each color may be spent this way." (Emblazoned Golem)
isn't resolved through the generic effect-handler table because it doesn't
describe a `GameEffect` at all — it constrains *how Kicker's own {X} may be
paid*, a fact the engine needs at cast time (`GameEngine.can_cast`/
`cast_spell`, via `models.mana_pool.ManaPool.can_pay_distinct_colors`/
`pay_distinct_colors`), not something the binder attaches to the object.
The engine resolves it directly through
`game/ability_catalogue.kicker_x_mana_restriction`, the same
recognize-directly-off-card-text shape `counters.py`/`lands.py` use.

This module is the **single source of truth** for recognising the clause;
both the coverage gate (`gate.py`, claims the line without emitting a spec)
and the engine-facing card-level API
(`game/ability_catalogue.kicker_x_mana_restriction`) call into it, so the
shape the gate claims and the shape the engine resolves can never drift
apart.

Pure — **no `game/` imports** (front-end security boundary, docs/09).
"""

from __future__ import annotations

import re
from typing import Optional

from ..normalize import normalize

#: "Spend only colored mana on X. No more than one mana of each color may be
#: spent this way." — a single normalized *line* (both sentences, joined by
#: a period, `gate.py` splits on NEWLINE only): the only real-cache phrasing
#: of this restriction (confirmed via a full-cache scan for the shape
#: alongside "kicker {x}"), so a narrow, exact pattern is correct rather
#: than a generalized one nothing else would ever match.
_KICKER_X_DISTINCT_COLOR_RE = re.compile(
    r"^spend only colored mana on x\. "
    r"no more than 1 mana of each color may be spent this way\.?$",
    re.IGNORECASE,
)

#: The restriction-kind vocabulary this module recognizes — currently one
#: entry; `ManaPool.can_pay_distinct_colors`/`pay_distinct_colors` is its
#: only consumer.
KICKER_X_DISTINCT_COLORS = "distinct_colors"


def kicker_x_mana_restriction_condition(line: str) -> Optional[str]:
    """Classify one **already-normalized** oracle line as Kicker's own
    ``{X}`` payment restriction, or ``None`` if it isn't one.

    Full-matches the line (keeps the coverage gate fail-closed, docs/09).
    Returns `KICKER_X_DISTINCT_COLORS` for the one recognized shape.
    """
    if _KICKER_X_DISTINCT_COLOR_RE.match(line):
        return KICKER_X_DISTINCT_COLORS
    return None


def kicker_x_mana_restriction(card: object) -> Optional[str]:
    """``card``'s Kicker ``{X}`` payment restriction, read off its printed
    text — ``None`` for an ordinary/no-``{X}`` Kicker cost.

    Normalizes the same way the front-end pipeline does (docs/09 step 1)
    and classifies each line with `kicker_x_mana_restriction_condition`, so
    the shape recognised here can never drift from what the coverage gate
    (`gate.py`) claims.
    """
    text = getattr(card, "oracle_text", "") or ""
    normalized = normalize(text, getattr(card, "name", None))
    for line in normalized.split("\n"):
        line = line.strip()
        if not line:
            continue
        restriction = kicker_x_mana_restriction_condition(line)
        if restriction is not None:
            return restriction
    return None
