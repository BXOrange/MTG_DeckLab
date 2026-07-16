"""Replacement-clause recognition (RULE 614/616) — a permanent's standing

"if X would Y, Z instead" sentence, docs/09's Phase 1 "static-shaped"
family. The binder side (`game/effects.py`'s `ReplacementRegistry`) has
long supported `prevent_damage`/`double_damage`/`additional_damage`/
`double_counters`/`double_tokens`; this module supplies the missing
*recognition* half for three of those five — the ones with a single, fixed
real-card phrasing (Doubling Season/Anointed Procession's token- and
counter-doubling lines, Torbran/Mechanized Warfare's "plus N damage"
line). `prevent_damage`'s real cards (Riot Control/Thought Lash) are a
different, *one-shot spell effect* shape ("Prevent all/the next N damage
that would be dealt to you this turn" grants a temporary shield, it isn't
itself a standing permanent ability) and aren't covered here.

RULE 616.1's full "if X would Y, Z instead" grammar has many more real
formulations (target/duration variants) than these three fixed sentences —
deliberately not attempted here; see `backend/ToDo_Backend.md` "Rules
Engine" for the open scope.

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import re
from typing import Optional

from ..spec import EffectSpec

#: Colour words → their WUBRG symbol (`additional_damage`'s single-colour filter).
_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

#: Doubling Season's/Anointed Procession's token-doubling line — identical
#: phrasing on every real card that prints it.
_DOUBLE_TOKENS_RE = re.compile(
    r"if an effect would create 1 or more tokens under your control, "
    r"it creates twice that many of those tokens instead",
    re.IGNORECASE,
)
#: Doubling Season's counter-doubling line (deliberately *not* scoped to
#: "a permanent you control" — matches `_double_counters_replacement`'s own
#: engine-side note that the real card doubles even an opponent's counters
#: … except this specific sentence *is* "on a permanent you control"; a
#: differently-scoped variant like Innkeeper's Talent's "on a permanent or
#: player" stays unclaimed, fail-closed).
_DOUBLE_COUNTERS_RE = re.compile(
    r"if an effect would put 1 or more counters on a permanent you control, "
    r"it puts twice that many of those counters on that permanent instead",
    re.IGNORECASE,
)
#: Torbran, Thane of Red Fell's "plus N damage" line — a single printed
#: colour only ("a red source you control …"); Mechanized Warfare's "a red
#: or artifact source" compound filter isn't this shape and stays unclaimed.
_ADDITIONAL_DAMAGE_RE = re.compile(
    r"if a (?P<color>white|blue|black|red|green) source you control would deal damage to "
    r"an opponent or a permanent an opponent controls, it deals that much damage plus "
    r"(?P<n>\d+) instead",
    re.IGNORECASE,
)


def replacement_clause_specs(clause: str) -> Optional[list[EffectSpec]]:
    """`EffectSpec`s for a standing replacement-effect ``clause``, or ``None``.

    Full-matches the clause, mirroring `static_handlers.static_effect_specs`
    (its sibling in `segmenter.segment_line`'s permanent-only fallback) —
    a partial/differently-worded match stays unclaimed rather than guessed.
    """
    text = clause.strip().rstrip(".").strip()

    if _DOUBLE_TOKENS_RE.fullmatch(text):
        return [EffectSpec("double_tokens", {})]

    if _DOUBLE_COUNTERS_RE.fullmatch(text):
        return [EffectSpec("double_counters", {})]

    m = _ADDITIONAL_DAMAGE_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("additional_damage", {
            "amount": int(m.group("n")),
            "your_sources_only": True,
            "to_opponent_only": True,
            "color": _COLOR_WORDS[m.group("color").lower()],
        })]

    return None
