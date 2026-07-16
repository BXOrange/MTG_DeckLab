"""RULE 614.1 "enters tapped" land-clause recognition (docs/09).

A tapped-entry clause isn't resolved through the generic effect-handler
table (step 3, `catalogue/handlers.py`) — the engine has its own dedicated
machinery for it (`game/ability_catalogue.land_tap_condition`, consumed by
`RulesEngine.enter_land_tapped`), the same way a mana ability's "add {g}" is
covered without an effect spec (`segmenter.py`'s `_MANA_EFFECT_RE`). This
module is the **single source of truth** for recognising those clauses in
oracle text; both the coverage gate (`gate.py`, claims the line without
emitting a spec) and the engine-facing card-level API
(`game/ability_catalogue.land_tap_condition`, which the engine actually
resolves off of) call into it, so the shapes the gate claims and the shapes
the engine resolves can never drift apart.

Pure — **no `game/` imports** (front-end security boundary, docs/09).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..normalize import normalize

#: A tapped-entry clause's subject: either the card's own name (already
#: folded to "~" by `normalize`) or one of the post-2022-templating literal
#: subjects real cards now print ("This land enters tapped unless …").
_SUBJECT = r"(?:this land|this artifact|this creature|this permanent|~)"
#: "enters" or "enters the battlefield" — both appear on real cards.
_ENTERS = r"enters(?: the battlefield)?"

#: Plain tap-land: "~ enters tapped." / "this land enters the battlefield
#: tapped." (35+ cards — the single biggest unclaimed cluster).
_ALWAYS_RE = re.compile(rf"^{_SUBJECT} {_ENTERS} tapped\.?$", re.IGNORECASE)
#: Shock lands: "As ~ enters the battlefield, you may pay N life. If you
#: don't, it enters tapped." — a genuine choice, RULE 614.1 optional cost.
_PAY_LIFE_RE = re.compile(
    rf"^as {_SUBJECT} {_ENTERS}, you may pay (\d+) life\. "
    r"if you don'?t, it enters tapped\.?$",
    re.IGNORECASE,
)
#: Commander "Battlebond" lands: "~ enters tapped unless you have N or more
#: opponents." — deterministic on the game's player count, not the board.
_UNLESS_OPPONENTS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} tapped unless you have (\d+) or more opponents\.?$",
    re.IGNORECASE,
)
#: Fast/slow lands: "unless you control N or fewer/more other lands" —
#: deterministic on the board the controller already has (excluding this
#: land itself, since the clause is read before it's added).
_UNLESS_COUNT_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} tapped unless you control (\d+) or (more|fewer) other lands\.?$",
    re.IGNORECASE,
)
#: A variant counting only *basic* lands rather than any other land.
_UNLESS_BASIC_COUNT_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} tapped unless you control (\d+) or (more|fewer) basic lands\.?$",
    re.IGNORECASE,
)
#: Check lands: "unless you control a/an <Type> [or a/an <Type> …]" —
#: deterministic on the land *types* the controller already has.
_UNLESS_TYPES_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} tapped unless you control an? (.+?)\.?$",
    re.IGNORECASE,
)
#: A fourth "unless" variant counting the *opponents'* lands rather than the
#: controller's own (distinct from `_UNLESS_COUNT_RE`, "you control", and
#: `_UNLESS_OPPONENTS_RE`, which counts opponent *players*, not lands) — the
#: "Turbulent" land cycle: "~ enters tapped unless your opponents control N
#: or more lands."
_UNLESS_OPPONENTS_COUNT_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} tapped unless your opponents control (\d+) or (more|fewer) lands\.?$",
    re.IGNORECASE,
)


def _split_types_clause(clause: str) -> list[str]:
    """"a mountain or a forest" → ``["mountain", "forest"]`` (each subsequent
    item repeats its own "a"/"an" per official templating)."""
    types: list[str] = []
    for part in re.split(r"\s+or\s+", clause):
        part = re.sub(r"^an?\s+", "", part.strip(), flags=re.IGNORECASE).strip()
        if part:
            types.append(part.lower())
    return types


def tap_clause_condition(line: str) -> Optional[dict[str, Any]]:
    """Classify one **already-normalized** oracle line as a RULE 614.1
    tapped-entry clause, or ``None`` if it isn't one.

    Every pattern here **full-matches** the line — never claims a line that
    has extra, unrecognized text tacked onto a recognized shape, which is
    what keeps the coverage gate fail-closed (docs/09). Returns one of:

    - ``{"kind": "always"}`` — a plain tap-land, unconditionally tapped.
    - ``{"kind": "pay_life", "amount": N}`` — a shock land: the controller
      may pay ``N`` life to keep it untapped, a genuine interactive choice.
    - ``{"kind": "unless_types", "types": [...]}`` — a check land: untapped
      iff the controller already controls a land of one of these types.
    - ``{"kind": "unless_count", "cmp": "le" | "ge", "count": N}`` — a fast
      land (``"le"``) or slow land (``"ge"``): untapped iff the count of
      *other* lands the controller controls compares as stated. The
      basic-land-counting variant additionally sets ``"basic": True``.
    - ``{"kind": "unless_opponents", "count": N}`` — a Commander
      "Battlebond" land: untapped iff the game has at least ``N`` opponents
      of the controller.
    - ``{"kind": "unless_opponents_count", "cmp": "le" | "ge", "count": N}``
      — the "Turbulent" land cycle: untapped iff the *total* count of lands
      across all opponents compares as stated (unlike ``unless_count``,
      which counts the controller's own other lands).
    """
    match = _PAY_LIFE_RE.match(line)
    if match:
        return {"kind": "pay_life", "amount": int(match.group(1))}
    match = _UNLESS_OPPONENTS_COUNT_RE.match(line)
    if match:
        cmp_op = "le" if match.group(2).lower() == "fewer" else "ge"
        return {"kind": "unless_opponents_count", "cmp": cmp_op, "count": int(match.group(1))}
    match = _UNLESS_OPPONENTS_RE.match(line)
    if match:
        return {"kind": "unless_opponents", "count": int(match.group(1))}
    match = _UNLESS_BASIC_COUNT_RE.match(line)
    if match:
        cmp_op = "le" if match.group(2).lower() == "fewer" else "ge"
        return {
            "kind": "unless_count",
            "cmp": cmp_op,
            "count": int(match.group(1)),
            "basic": True,
        }
    match = _UNLESS_COUNT_RE.match(line)
    if match:
        cmp_op = "le" if match.group(2).lower() == "fewer" else "ge"
        return {"kind": "unless_count", "cmp": cmp_op, "count": int(match.group(1))}
    match = _UNLESS_TYPES_RE.match(line)
    if match:
        types = _split_types_clause(match.group(1))
        if types:
            return {"kind": "unless_types", "types": types}
    if _ALWAYS_RE.match(line):
        return {"kind": "always"}
    return None


def land_tap_condition(card: Any) -> dict[str, Any]:
    """How ``card``'s RULE 614.1 tapped-entry resolves, read off its text.

    Normalizes the card's oracle text the same way the front-end pipeline
    does (self-name folded to "~", reminder text stripped, number words
    folded to digits — docs/09 step 1) and classifies each line with
    `tap_clause_condition`, so the shapes recognised here can never drift
    from the shapes the coverage gate (`gate.py`) claims.

    Returns ``{"kind": "never"}`` when no line matches a recognized
    tapped-entry clause — a normal land, or a conditional shape not (yet)
    recognized (fails safe: untapped rather than wrongly forcing it down).
    """
    text = getattr(card, "oracle_text", "") or ""
    normalized = normalize(text, getattr(card, "name", None))
    for line in normalized.split("\n"):
        line = line.strip()
        if not line:
            continue
        condition = tap_clause_condition(line)
        if condition is not None:
            return condition
    return {"kind": "never"}
