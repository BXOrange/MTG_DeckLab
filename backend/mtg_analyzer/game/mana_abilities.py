"""Parse a permanent's mana abilities (RULE 605), incl. dual-land choice.

Reference: docs/02_MVP_USECASES_REVISED.md R2.6 (Mana System).

A basic Forest taps for exactly `{G}`. A dual land ("{T}: Add {W} or
{U}.") taps for `{W}` *or* `{U}` — the player chooses one, they do NOT
get both (the bug this fixes: the old `_land_mana` added every colour a
land could make). So a card's tap-for-mana ability is modeled as a list
of mutually-exclusive *production options*, each a `{colour: count}`
dict; tapping picks one (index 0 when there's only one, so basics need no
prompt).

Parsing is intentionally simple — it covers basics, guildgates/duals,
tri-lands, "add one mana of any colour", and multi-pip lands (`{C}{C}`)
— and approximates the long tail (filter lands, "any one colour" with an
amount) rather than modeling every printed ability.
"""

from __future__ import annotations

import re
from typing import Any

#: Colours the five basic lands produce, by their basic land *type*.
BASIC_LAND_MANA = {
    "Plains": "W",
    "Island": "U",
    "Swamp": "B",
    "Mountain": "R",
    "Forest": "G",
}

#: The text inside an "Add …." clause (up to the sentence's period).
_ADD_CLAUSE_RE = re.compile(r"Add ([^.]*)\.")
_PIP_RE = re.compile(r"\{([WUBRGC])\}")
_ALTERNATIVE_SPLIT_RE = re.compile(r",| or ")
_ALL_COLORS = ("W", "U", "B", "R", "G")


def mana_options(card: Any) -> list[dict[str, int]]:
    """Mutually-exclusive ways a card taps for mana (empty if it can't).

    Returns e.g. ``[{"G": 1}]`` for a Forest, ``[{"W": 1}, {"U": 1}]`` for
    a WU dual, ``[{"C": 2}]`` for an Eldrazi land, or one option per colour
    for "add one mana of any colour". The first option is the default the
    goldfish auto-player / a single-option tap uses.
    """
    basic = _basic_options(card)
    if basic:
        return basic

    options: list[dict[str, int]] = []
    for clause in _ADD_CLAUSE_RE.findall(getattr(card, "oracle_text", "") or ""):
        options.extend(_parse_clause(clause))
    return _dedupe(options)


def mana_options_for(obj: Any) -> list[dict[str, int]]:
    """``mana_options`` for a `GameObject`, folding in layer-6 grants too.

    A permanent's own printed options, plus any a static ability granted it
    (RULE 613.7f — "Elves you control have '{T}: Add {B}.'", Tyvar Kell;
    `game/continuous.py` stamps these onto ``obj.granted_mana_options`` every
    recompute). Duck-typed: any object with ``.card`` and
    ``.granted_mana_options`` works, so tests can pass a bare stub.
    """
    return _dedupe(mana_options(obj.card) + list(getattr(obj, "granted_mana_options", [])))


def _basic_options(card: Any) -> list[dict[str, int]]:
    type_line = getattr(card, "type_line", "") or ""
    name = getattr(card, "name", "") or ""
    produced: list[dict[str, int]] = []
    for basic_name, color in BASIC_LAND_MANA.items():
        # A basic land *type* (or the exact basic name) grants that colour.
        if basic_name in type_line or name == basic_name:
            produced.append({color: 1})
    return produced


def _parse_clause(clause: str) -> list[dict[str, int]]:
    lowered = clause.lower()
    if "any color" in lowered or "any colour" in lowered:
        # "one mana of any colour" — one single-colour option each.
        return [{color: 1} for color in _ALL_COLORS]

    options: list[dict[str, int]] = []
    for alternative in _ALTERNATIVE_SPLIT_RE.split(clause):
        pips = _PIP_RE.findall(alternative)
        if not pips:
            continue
        counts: dict[str, int] = {}
        for pip in pips:
            counts[pip] = counts.get(pip, 0) + 1
        options.append(counts)
    return options


def _dedupe(options: list[dict[str, int]]) -> list[dict[str, int]]:
    seen: set[tuple] = set()
    unique: list[dict[str, int]] = []
    for option in options:
        key = tuple(sorted(option.items()))
        if key not in seen:
            seen.add(key)
            unique.append(option)
    return unique


def option_label(option: dict[str, int]) -> str:
    """A short glyph label for a production option, e.g. "🟢" or "⟡⟡"."""
    glyph = {"W": "⚪", "U": "🔵", "B": "⚫", "R": "🔴", "G": "🟢", "C": "⟡"}
    parts: list[str] = []
    for color in ("C", "W", "U", "B", "R", "G"):
        parts.append(glyph[color] * option.get(color, 0))
    return "".join(parts) or "—"
