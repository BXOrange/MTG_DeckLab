"""RULE 614.1-style "enters with N counters" replacement-clause recognition
(docs/09).

Mirrors `catalogue/lands.py`'s tapped-entry machinery: an entry-counters
clause isn't resolved through the generic effect-handler table
(`catalogue/handlers.py`, step 3) because on an ``X`` amount it needs the
object's *actual* paid X (RULE 107.3c: 0 if it didn't enter by being cast
for X) at the moment it enters the battlefield — not a value the binder can
precompute onto a reusable spec. The engine resolves it directly through
`game/card_registry.entry_counters`, the same split `lands.py` uses for
tapped-entry.

This module is the **single source of truth** for recognising these clauses;
both the coverage gate (`gate.py`, claims the line without emitting a spec)
and the engine-facing card-level API (`game/card_registry.entry_counters`)
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
_COUNTER_TYPE = r"(\+\d+/\+\d+|-\d+/-\d+|first strike|double strike|[a-z]+)"

#: RULE 122.1b keyword counters, spelled as the oracle text prints the kind
#: (the layer engine's matching reader is `game/continuous.py`'s
#: `KEYWORD_COUNTER_SLUGS`; a test pins the two lists together, since this
#: module may not import `game/`). `decayed`/`exalted` are deliberately absent
#: — see that constant's comment.
KEYWORD_COUNTER_KINDS: tuple[str, ...] = (
    "flying", "first strike", "double strike", "deathtouch", "haste", "hexproof",
    "indestructible", "lifelink", "menace", "reach", "shadow", "trample", "vigilance",
)

#: One option of a "your choice of …" counter list: an optional amount ("a"/"an"
#: = 1, a digit), the kind, and an optional trailing "counter(s)" word — the
#: shared-noun list "a +1/+1, first strike, or trample counter" carries the
#: word only on its last option.
def counter_choice_item(kinds: str) -> str:
    return rf"(?:(?:a|an|\d+) )?(?:\+1/\+1|{kinds})(?: counters?)?"


def counter_choice_list(kinds: str) -> str:
    """Regex fragment for ``<item>, <item>, or <item>`` / ``<item> or <item>``
    (two or more options), as the named group ``items``."""
    item = counter_choice_item(kinds)
    return rf"(?P<items>{item}(?:, {item})*,? or {item})"


_CHOICE_OPTION_RE = re.compile(r"(?:(?P<n>a|an|\d+) )?(?P<kind>\+1/\+1|[a-z]+(?: strike)?)(?: counters?)?$")


def parse_counter_choice_items(items: str) -> Optional[list[dict[str, Any]]]:
    """Split a `counter_choice_list` match into ``[{"kind", "count"}, …]``
    (an amount-less option in a shared-noun list counts as 1), or ``None``
    when any option doesn't read back cleanly."""
    options: list[dict[str, Any]] = []
    for part in re.split(r",? or |, ", items):
        match = _CHOICE_OPTION_RE.match(part.strip())
        if match is None:
            return None
        amount = match.group("n")
        options.append({
            "kind": match.group("kind"),
            "count": int(amount) if amount and amount.isdigit() else 1,
        })
    return options if len(options) >= 2 else None


#: "~ enters with your choice of a flying counter or a first strike counter on
#: it." / "…with your choice of a +1/+1, first strike, or vigilance counter on
#: it." (RULE 614.1 + 122.1b — the controller picks as it enters).
ENTER_COUNTER_CHOICE_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with your choice of "
    + counter_choice_list("|".join(KEYWORD_COUNTER_KINDS)) + r" on it\.?$",
    re.IGNORECASE,
)

#: "~ enters with a +1/+1 counter and a flying counter on it." — a fixed
#: compound of two (or three) counters; `_ENTRY_COUNTERS_RE` only ever names
#: one. Kinds are the +1/+1/-1/-1 shapes, a keyword counter, or a bare word.
_ENTRY_COMPOUND_ITEM = rf"(?:a|an|\d+) (?:\+\d+/\+\d+|-\d+/-\d+|first strike|double strike|[a-z]+) counters?"
_ENTRY_COUNTERS_COMPOUND_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with (?P<items>{_ENTRY_COMPOUND_ITEM}(?:, {_ENTRY_COMPOUND_ITEM})*,? and {_ENTRY_COMPOUND_ITEM}) on it\.?$",
    re.IGNORECASE,
)
_ENTRY_COMPOUND_PART_RE = re.compile(
    r"(?P<n>a|an|\d+) (?P<kind>\+\d+/\+\d+|-\d+/-\d+|first strike|double strike|[a-z]+) counters?"
)

#: "~ enters with X +1/+1 counters on it." / "this creature enters with
#: three ice counters on it." / "this artifact enters with a charge counter
#: on it." — 20+ cards across Hydras, counters-matter artifacts/enchantments.
_ENTRY_COUNTERS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with {_AMOUNT} {_COUNTER_TYPE} counters? on it\.?$",
    re.IGNORECASE,
)
_CAST_FROM_HAND_ENTRY_COUNTERS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with (a|an|\d+) {_COUNTER_TYPE} counters? on it if you cast it from your hand\.?$",
    re.IGNORECASE,
)
_TAPPED_ENTRY_COUNTERS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} tapped with {_AMOUNT} {_COUNTER_TYPE} counters? on it\.?$",
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

#: MEC-84 (Revolt): "~ enters with N `<T>` counters on it **if a permanent
#: left the battlefield under your control this turn**." (Narnam Renegade /
#: Greenwheel Liberator / Lifecraft Cavalry / Night Market Aeronaut / Putrid
#: Pals). The suffix sibling of `_KICKED_ENTRY_COUNTERS_RE`, gated on
#: `GameState.permanents_left_battlefield_this_turn` at resolution (0 unless
#: something left) instead of `kicker_count`.
_REVOLT_ENTRY_COUNTERS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with {_FIXED_AMOUNT} {_COUNTER_TYPE} counters? on it "
    rf"if an? permanent left the battlefield under your control this turn\.?$",
    re.IGNORECASE,
)

#: PAR-64 / Raid: "~ enters with N counters on it if you attacked this
#: turn."  This is the player-scoped RULE 508.1a declaration history (not
#: Boast's source-only ``attacked_this_turn`` flag), read when the permanent
#: enters just like the Revolt sibling above.
_RAID_ENTRY_COUNTERS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with {_FIXED_AMOUNT} {_COUNTER_TYPE} counters? on it "
    r"if you attacked this turn\.?$",
    re.IGNORECASE,
)

#: PAR-95 / Adamant: this is an entry replacement, not a delayed spell
#: effect, so the counter exists before the permanent enters.  ``colorless``
#: is included because the same spent-mana family has a real colorless rider.
_ADAMANT_ENTRY_COUNTERS_RE = re.compile(
    rf"^if at least (?P<n>\d+) (?P<color>white|blue|black|red|green|colorless) mana was spent to cast "
    rf"this spell, {_SUBJECT} {_ENTERS} with {_FIXED_AMOUNT} {_COUNTER_TYPE} counters? on it\.?$",
    re.IGNORECASE,
)
_ADAMANT_MANA_KEYS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G", "colorless": "C",
}

# MEC-97: Hotheaded Giant's "unless you've cast another red spell this
# turn" is still an entry replacement (RULE 614.12), so the test belongs at
# the same pre-entry point as revolt/raid rather than becoming a late ETB
# trigger.  The spell being cast is not counted here: its own cast was
# recorded before it resolved, hence "another" requires at least two.
_ANOTHER_COLOR_SPELL_ENTRY_COUNTERS_UNLESS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with {_FIXED_AMOUNT} {_COUNTER_TYPE} counters? on it "
    r"unless you'?ve cast another (?P<color>white|blue|black|red|green) spell this turn\.?$",
    re.IGNORECASE,
)

#: PAR-45: Canker Abomination's compound entry instruction, after the
#: preceding "as ~ enters, choose an opponent" replacement has stamped
#: ``chosen_player_id``.  The counter count is fixed at the same pre-entry
#: moment, hence it belongs beside the other entry-counter conditions.
_CHOSEN_OPPONENT_CREATURES_ENTRY_COUNTERS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with {_FIXED_AMOUNT} {_COUNTER_TYPE} counters? on it "
    r"for each creature that player controls\.?$",
    re.IGNORECASE,
)

#: RULE 702.43a **Sunburst**: "~ enters with a +1/+1 counter on it for each
#: **color of mana spent to cast it**." (Chamber Sentry / Crystalline
#: Crawler / Rancorous Archaic / Skyrider Elf / Etched Oracle). Scaled by
#: `GameObject.colors_spent_to_cast` (a frozenset the mana-payment solver
#: already records — the same field `SearchLibraryEffect.mana_value_from`'s
#: ``"colors_spent_to_cast"`` sentinel reads). Always a per-colour amount
#: of 1 on a real card, but ``_FIXED_AMOUNT`` is kept for symmetry.
_SUNBURST_ENTRY_COUNTERS_RE = re.compile(
    rf"^{_SUBJECT} {_ENTERS} with {_FIXED_AMOUNT} {_COUNTER_TYPE} counters? on it "
    rf"for each color of mana spent to cast it\.?$",
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

    - ``{"is_x": False, "count": N, "counter_type": T, "extra_counters":
      [{"counter_type": T2, "count": N2}, …]}`` — a compound ("~ enters with
      a +1/+1 counter and a flying counter on it"): the first counter plus
      the rest, all placed unconditionally.

    Either kicked shape may also carry ``"grant_keyword": "vigilance"`` (RULE
    702.33b's "...and with `<keyword>`." tail) — a keyword granted under the
    exact same kicked gate as the counters (present at all once kicked, for
    either shape; the per-kick scaling only ever applies to the counter
    count, never to "how many times" a keyword is granted).
    """
    match = _TAPPED_ENTRY_COUNTERS_RE.match(line)
    if match is not None:
        return {"is_x": False, "count": _fixed_count(match.group(1)),
                "counter_type": match.group(2).lower()}
    match = _CAST_FROM_HAND_ENTRY_COUNTERS_RE.match(line)
    if match is not None:
        return {"is_x": False, "count": _fixed_count(match.group(1)),
                "counter_type": match.group(2).lower(), "cast_from_hand_gate": True}
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
    match = _SUNBURST_ENTRY_COUNTERS_RE.match(line)
    if match is not None:
        return {
            "is_x": False, "count": _fixed_count(match.group(1)),
            "counter_type": match.group(2).lower(), "colors_spent_scale": True,
        }
    match = _REVOLT_ENTRY_COUNTERS_RE.match(line)  # MEC-84
    if match is not None:
        return {
            "is_x": False, "count": _fixed_count(match.group(1)),
            "counter_type": match.group(2).lower(), "revolt_gate": True,
        }
    match = _RAID_ENTRY_COUNTERS_RE.match(line)  # PAR-64 / Raid
    if match is not None:
        return {
            "is_x": False, "count": _fixed_count(match.group(1)),
            "counter_type": match.group(2).lower(), "raid_gate": True,
        }
    match = _ADAMANT_ENTRY_COUNTERS_RE.match(line)  # PAR-95 / Adamant
    if match is not None:
        return {
            "is_x": False, "count": _fixed_count(match.group(3)),
            "counter_type": match.group(4).lower(),
            "mana_color_spent_gate": {
                "color": _ADAMANT_MANA_KEYS[match.group("color").lower()],
                "amount": int(match.group("n")),
            },
        }
    match = _ANOTHER_COLOR_SPELL_ENTRY_COUNTERS_UNLESS_RE.match(line)  # MEC-97
    if match is not None:
        return {
            "is_x": False, "count": _fixed_count(match.group(1)),
            "counter_type": match.group(2).lower(),
            "another_color_spell_unless": {
                "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
            }[match.group("color").lower()],
        }
    match = _CHOSEN_OPPONENT_CREATURES_ENTRY_COUNTERS_RE.match(line)  # PAR-45
    if match is not None:
        return {
            "is_x": False, "count": _fixed_count(match.group(1)),
            "counter_type": match.group(2).lower(), "chosen_opponent_creatures_scale": True,
        }
    match = _ENTRY_COUNTERS_COMPOUND_RE.match(line)
    if match is not None:
        parts = [
            {"counter_type": p.group("kind").lower(), "count": _fixed_count(p.group("n"))}
            for p in _ENTRY_COMPOUND_PART_RE.finditer(match.group("items"))
        ]
        first, rest = parts[0], parts[1:]
        return {"is_x": False, "count": first["count"], "counter_type": first["counter_type"],
                "extra_counters": rest}
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
    # Pass ``keywords`` so an unregistered ability-word label ("Revolt —",
    # "Disappear —") is stripped exactly as the front-end pipeline strips it
    # (MEC-84 — the first entry-counter shape gated behind an ability word).
    normalized = normalize(
        text, getattr(card, "name", None), getattr(card, "keywords", None)
    )
    for line in normalized.split("\n"):
        line = line.strip()
        if not line:
            continue
        # PAR-45: the opponent pick and this entry-counter replacement share
        # one printed line (Canker Abomination).  The gate performs the same
        # narrow split before binding the choice; expose the counter tail to
        # this engine-facing recognizer too so the two paths cannot drift.
        compound = re.fullmatch(r"as ~ enters, choose an opponent\.\s*(?P<tail>.+)", line, re.I)
        if compound is not None:
            line = compound.group("tail")
        condition = entry_counters_condition(line)
        if condition is not None:
            return condition
    return None
