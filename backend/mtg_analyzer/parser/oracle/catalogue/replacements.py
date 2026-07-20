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
#: Doubling Season's counter-doubling line ("a permanent you control" —
#: the real card's own wording; engine-side unscoped by ``kind``, but this
#: specific sentence is target-controller-scoped in its own text).
_DOUBLE_COUNTERS_RE = re.compile(
    r"if an effect would put 1 or more counters on a permanent you control, "
    r"it puts twice that many of those counters on that permanent instead",
    re.IGNORECASE,
)
#: Innkeeper's Talent's differently-scoped counter-doubling line: "if
#: **you** would put counters on a permanent or player" — a *causer*-scoped
#: sentence (whoever's effect places the counters), not Doubling Season's
#: *recipient*-scoped "on a permanent you control" — see
#: `_double_counters_replacement`'s ``your_effects_only`` docstring for the
#: distinction. Its "or player" half needs no special-casing here: the
#: engine's `EventType.COUNTER` handling is already recipient-agnostic
#: (`RulesEngine.add_player_counters` fires the same event shape for a
#: player recipient as `add_counters` does for a permanent).
_DOUBLE_COUNTERS_YOUR_EFFECTS_RE = re.compile(
    r"if you would put 1 or more counters on a permanent or player, "
    r"put twice that many of each of those kinds of counters on that "
    r"permanent or player instead",
    re.IGNORECASE,
)
#: Torbran, Thane of Red Fell's "plus N damage" line — one or two source
#: qualifiers joined by "or", each either a WUBRG colour word or a type word
#: (currently only "artifact" — Mechanized Warfare's "a red or artifact
#: source"; extend the word list as a real card needs another, mirroring
#: `_additional_damage_replacement`'s own "extend as needed" note).
_SOURCE_QUALIFIER_WORD = r"white|blue|black|red|green|artifact"
_ADDITIONAL_DAMAGE_RE = re.compile(
    rf"if a (?P<q1>{_SOURCE_QUALIFIER_WORD})(?: or (?P<q2>{_SOURCE_QUALIFIER_WORD}))? "
    r"source you control would deal damage to "
    r"an opponent or a permanent an opponent controls, it deals that much damage plus "
    r"(?P<n>\d+) instead",
    re.IGNORECASE,
)


#: The alternative-win-condition family (Jace, Wielder of Mysteries/
#: Laboratory Maniac-shaped, RULE 104.3a/120-adjacent) — "If you would draw
#: a card while your library has no cards in it, you win the game instead."
#: A recurring exact phrasing across several real cards (Elixir of
#: Immortality-adjacent effects use a different shape, not this one).
_WIN_INSTEAD_OF_EMPTY_DRAW_RE = re.compile(
    r"if you would draw a card while your library has no cards? in it, "
    r"you win the game instead",
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

    if _DOUBLE_COUNTERS_YOUR_EFFECTS_RE.fullmatch(text):
        return [EffectSpec("double_counters", {"your_effects_only": True})]

    m = _ADDITIONAL_DAMAGE_RE.fullmatch(text)
    if m is not None:
        quals = [m.group("q1")] + ([m.group("q2")] if m.group("q2") else [])
        colors = sorted({_COLOR_WORDS[q.lower()] for q in quals if q.lower() in _COLOR_WORDS})
        types = sorted({q.lower() for q in quals if q.lower() not in _COLOR_WORDS})
        params: dict = {
            "amount": int(m.group("n")), "your_sources_only": True, "to_opponent_only": True,
        }
        if len(colors) == 1 and not types:
            # The single-colour shape (Torbran) — kept as the pre-existing
            # ``color`` singular param for backward compatibility.
            params["color"] = colors[0]
        else:
            if colors:
                params["colors"] = colors
            if types:
                params["types"] = types
        return [EffectSpec("additional_damage", params)]

    if _WIN_INSTEAD_OF_EMPTY_DRAW_RE.fullmatch(text):
        return [EffectSpec("win_instead_of_empty_draw", {})]

    return None
