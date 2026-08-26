"""RULE 614.1-style "enters with N counters" replacement-clause recognition
(docs/09).

Mirrors `catalogue/lands.py`'s tapped-entry machinery: an entry-counters
clause isn't resolved through the generic effect-handler table
(`catalogue/handlers.py`, step 3) because on an ``X`` amount it needs the
object's *actual* paid X (RULE 107.3c: 0 if it didn't enter by being cast
for X) at the moment it enters the battlefield — not a value the binder can
precompute onto a reusable spec. The engine resolves it directly through
`game/ability_catalogue.entry_counters`, the same split `lands.py` uses for
tapped-entry.

This module is the **single source of truth** for recognising these clauses;
both the coverage gate (`gate.py`, claims the line without emitting a spec)
and the engine-facing card-level API (`game/ability_catalogue.entry_counters`)
call into it, so the shapes the gate claims and the shapes the engine
resolves can never drift apart.

Pure — **no `game/` imports** (front-end security boundary, docs/09).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..normalize import normalize

#: A tapped-entry-style subject: the card's own name (already folded to "~"
#: by `normalize`) or one of the literal subjects real cards print.
_SUBJECT = r"(?:this creature|this artifact|this enchantment|this permanent|~)"
_ENTERS = r"enters(?: the battlefield)?"
#: "a"/"an" (=1), a bare number (number words are already folded to digits
#: by `normalize`), or the variable "x".
_AMOUNT = r"(a|an|x|\d+)"
#: The counter's kind: "+1/+1"/"-1/-1" (number words are already folded to
#: digits by `normalize`), or a bare word like "ice"/"charge".
_COUNTER_TYPE = r"(\+\d+/\+\d+|-\d+/-\d+|[a-z]+)"

#: "~ enters with X +1/+1 counters on it." / "this creature enters with
#: three ice counters on it." / "this artifact enters with a charge counter
#: on it." — 20+ cards across Hydras, counters-matter artifacts/enchantments.
_ENTRY_COUNTERS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with {_AMOUNT} {_COUNTER_TYPE} counters? on it\.?$",
    re.IGNORECASE,
)

#: A fixed amount only — used by the Multikicker-scaled shape below, which
#: is always a fixed *per-kick* amount (no cache card scales that amount
#: itself by an independently-announced Kicker {X}).
_FIXED_AMOUNT = r"(a|an|\d+)"

#: The kicked-gate shape's own amount: a fixed number, or "x" — Emblazoned
#: Golem's Kicker {X} (PAR-7), resolved against `GameObject.kicker_x_paid`
#: (a *different* value than a plain cast-for-X's `x_paid` the unconditional
#: `_ENTRY_COUNTERS_RE` shape above resolves against; kept distinct rather
#: than conflated, per the comment this replaced).
_KICKED_GATE_AMOUNT = r"(a|an|x|\d+)"

#: A small closed keyword vocabulary a "...and with <keyword>" compound
#: kicked-counters clause plausibly names (RULE 702.33b's "...and with
#: `<keyword>`." tail) — mirrors `catalogue.handlers.
#: _CREATURE_FILTER_KEYWORD_WORDS`'s "closed list, extend as needed" style;
#: kept local rather than imported from there since this module is
#: deliberately import-independent of the general effect-handler table.
_GRANT_KEYWORD_WORDS: dict[str, str] = {
    "flying": "flying", "vigilance": "vigilance", "trample": "trample",
    "haste": "haste", "deathtouch": "deathtouch", "lifelink": "lifelink",
    "menace": "menace", "first strike": "first_strike",
    "double strike": "double_strike", "reach": "reach",
    "indestructible": "indestructible", "hexproof": "hexproof",
}
#: The optional trailing "...and with <keyword>." clause shared by both
#: kicked-counters regexes below.
_GRANT_KEYWORD_SUFFIX = rf"(?: and with (?P<kw>{'|'.join(_GRANT_KEYWORD_WORDS)}))?"

#: RULE 702.33b: "If ~ was kicked, it enters with N counters on it." — the
#: same RULE 614.1 entry-counters replacement, gated on whether Kicker
#: (RULE 702.33) was paid at all (`GameObject.kicker_count`, stamped at cast
#: time by `GameEngine._cast_current_face`) — Academy Drake/Baloth Gorger/
#: Cragplate Baloth/Grunn-shaped. Kept as its own regex (not folded into
#: `_ENTRY_COUNTERS_RE`) since resolution needs a different rule (0 unless
#: kicked) instead of the plain unconditional count. The optional trailing
#: "...and with <keyword>." (`_GRANT_KEYWORD_SUFFIX`) is the same kicked
#: gate applied to a granted keyword instead of/alongside the counters.
_KICKED_ENTRY_COUNTERS_RE = re.compile(
    rf"^if {_SUBJECT} was kicked, it {_ENTERS} with {_KICKED_GATE_AMOUNT} {_COUNTER_TYPE} counters? on it"
    rf"{_GRANT_KEYWORD_SUFFIX}\.?$",
    re.IGNORECASE,
)

#: "~ enters with N counters on it for each time it was kicked." — the
#: Multikicker-scaled sibling (RULE 702.34a): the total isn't fixed, it's
#: ``N`` (the per-kick amount printed) times however many times Kicker was
#: actually paid — Apex Hawks-shaped.
_KICKED_SCALED_ENTRY_COUNTERS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with {_FIXED_AMOUNT} {_COUNTER_TYPE} counters? on it for each time it was kicked"
    rf"{_GRANT_KEYWORD_SUFFIX}\.?$",
    re.IGNORECASE,
)


def _fixed_count(amount_raw: str) -> int:
    return 1 if amount_raw.lower() in ("a", "an") else int(amount_raw)


def entry_counters_condition(line: str) -> Optional[dict[str, Any]]:
    """Classify one **already-normalized** oracle line as a RULE 614.1-style
    "enters with N counters" replacement clause, or ``None`` if it isn't one.

    Full-matches the line — never claims a line with extra, unrecognized
    text tacked onto a recognized shape (keeps the coverage gate fail-closed,
    docs/09). Returns one of:

    - ``{"is_x": True, "counter_type": "+1/+1"}`` — the amount is the
      object's actual paid X (RULE 107.3c; 0 outside a cast-for-X).
    - ``{"is_x": False, "count": N, "counter_type": "ice"}`` — a fixed
      amount ("a"/"an" folds to 1).
    - ``{"is_x": False, "count": N, "counter_type": T, "kicked_gate": True}``
      — apply only if Kicker was paid at all (any number of times); ``N`` is
      the fixed total, not a per-kick amount.
    - ``{"is_x": False, "count": N, "counter_type": T, "kicked_scale": True}``
      — ``N`` is a *per-kick* amount; the real total is ``N`` times
      however many times Kicker was actually paid (0 if never kicked).
    - ``{"is_x": False, "counter_type": T, "kicked_gate": True,
      "kicked_x_scale": True}`` — Kicker's own ``{X}`` (PAR-7, Emblazoned
      Golem's own ``GameObject.kicker_x_paid``, not the count-of-times-paid
      the other two kicked shapes use, and not the *spell's* own X the
      unconditional ``is_x`` shape above uses); 0 unless Kicker was paid.

    Either kicked shape may also carry ``"grant_keyword": "vigilance"`` (RULE
    702.33b's "...and with `<keyword>`." tail) — a keyword granted under the
    exact same kicked gate as the counters (present at all once kicked, for
    either shape; the per-kick scaling only ever applies to the counter
    count, never to "how many times" a keyword is granted).
    """
    match = _KICKED_ENTRY_COUNTERS_RE.match(line)
    if match is not None:
        amount_raw = match.group(1).lower()
        counter_type = match.group(2).lower()
        result: dict[str, Any] = {
            "is_x": False, "counter_type": counter_type, "kicked_gate": True,
        }
        if amount_raw == "x":
            result["kicked_x_scale"] = True
        else:
            result["count"] = _fixed_count(amount_raw)
        if match.group("kw"):
            result["grant_keyword"] = _GRANT_KEYWORD_WORDS[match.group("kw")]
        return result
    match = _KICKED_SCALED_ENTRY_COUNTERS_RE.match(line)
    if match is not None:
        count = _fixed_count(match.group(1))
        counter_type = match.group(2).lower()
        result = {
            "is_x": False, "count": count, "counter_type": counter_type, "kicked_scale": True,
        }
        if match.group("kw"):
            result["grant_keyword"] = _GRANT_KEYWORD_WORDS[match.group("kw")]
        return result
    match = _ENTRY_COUNTERS_RE.match(line)
    if not match:
        return None
    amount_raw = match.group(1).lower()
    counter_type = match.group(2).lower()
    if amount_raw == "x":
        return {"is_x": True, "counter_type": counter_type}
    count = 1 if amount_raw in ("a", "an") else int(amount_raw)
    return {"is_x": False, "count": count, "counter_type": counter_type}


def entry_counters(card: Any) -> Optional[dict[str, Any]]:
    """How ``card``'s RULE 614.1-style "enters with N counters" clause
    resolves, read off its text — ``None`` if it has no such clause.

    Normalizes the card's oracle text the same way the front-end pipeline
    does (self-name folded to "~", reminder text stripped, number words
    folded to digits — docs/09 step 1) and classifies each line with
    `entry_counters_condition`, so the shapes recognised here can never
    drift from the shapes the coverage gate (`gate.py`) claims.
    """
    text = getattr(card, "oracle_text", "") or ""
    normalized = normalize(text, getattr(card, "name", None))
    for line in normalized.split("\n"):
        line = line.strip()
        if not line:
            continue
        condition = entry_counters_condition(line)
        if condition is not None:
            return condition
    return None
