"""Card criteria: a pure predicate over a `Card` (RULE 700.4 "a card that…").

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md (pure, JSON-serializable data at
the security boundary — nothing derived from card text becomes code).

A library search (RULE 701.19) picks *some kind* of card: "a basic land",
"a creature card with mana value 3 or less", "a Plains or Island card", or
just "a card". This module turns that English into a small, whitelisted,
JSON-serializable **criteria dict** and matches it against a `Card`. It is
deliberately dependency-light (only `Card`) so the future oracle-text
parser can emit these criteria as plain data and the game engine can match
them without either side importing the other.

A criteria value is one of:

* ``""`` / ``None`` / ``{}``      — matches *any* card ("search for a card").
* a plain string ``"Creature"``   — shorthand for ``{"type": "Creature"}``
  (a case-insensitive substring of the type line), kept for backward
  compatibility with the original `type_restriction` API.
* a dict with any of the keys below, **all** of which must hold (AND):

  ``type``            str | list[str] — case-insensitive substring(s) of the
                      type line; a list is an OR ("Plains or Island"), so it
                      spans supertypes ("Basic Land"), card types ("Creature"),
                      and subtypes ("Forest").
  ``basic``           bool — the card is a basic land (the "Basic" supertype).
  ``max_mana_value``  int  — mana value ≤ this (e.g. Green Sun's Zenith's X).
  ``min_mana_value``  int  — mana value ≥ this.
  ``name``            str  — exact card name, case-insensitive ("a card named…").
  ``color``           str | list[str] — a colour ("W"/"U"/"B"/"R"/"G") that
                      must be in the card's colour identity; a list is an OR.
"""

from __future__ import annotations

from typing import Any, Union

from .card import Card

#: What a search can be parameterized by — a string shorthand or a dict.
Criteria = Union[str, dict[str, Any], None]

#: Recognized dict keys, so an unknown key fails closed instead of being
#: silently ignored (which would over-match and search wrongly).
_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"type", "basic", "max_mana_value", "min_mana_value", "name", "not_name", "color"}
)


def normalize(criteria: Criteria) -> dict[str, Any]:
    """Coerce any accepted criteria form into a plain dict.

    A bare string becomes ``{"type": string}``; ``None`` becomes ``{}``
    (match anything). Raises ``ValueError`` on an unknown dict key so a
    typo can't silently widen a search.
    """
    if criteria is None or criteria == "":
        return {}
    if isinstance(criteria, str):
        return {"type": criteria}
    if isinstance(criteria, dict):
        unknown = set(criteria) - _ALLOWED_KEYS
        if unknown:
            raise ValueError(f"unknown card-criteria key(s): {sorted(unknown)}")
        return criteria
    raise ValueError(f"criteria must be a str, dict, or None (got {type(criteria).__name__})")


def matches(card: Card, criteria: Criteria) -> bool:
    """Whether ``card`` satisfies ``criteria`` (all conditions AND-combined)."""
    crit = normalize(criteria)
    type_line = (card.type_line or "").lower()

    if not _type_matches(type_line, crit.get("type")):
        return False
    if crit.get("basic") and "basic" not in type_line:
        return False
    if "max_mana_value" in crit and card.converted_mana_cost > crit["max_mana_value"]:
        return False
    if "min_mana_value" in crit and card.converted_mana_cost < crit["min_mana_value"]:
        return False
    if "name" in crit and card.name.lower() != str(crit["name"]).lower():
        return False
    # The negated form ("a nonland card with a **different name** than that
    # spell" — Tibalt's Trickery). Kept as its own key rather than allowing a
    # magic value in ``name``, so a criteria dict stays literal data.
    if "not_name" in crit and card.name.lower() == str(crit["not_name"]).lower():
        return False
    if not _color_matches(card, crit.get("color")):
        return False
    return True


def describe(criteria: Criteria) -> str:
    """A short human label for the choice UI, e.g. "a basic land card"."""
    crit = normalize(criteria)
    if not crit:
        return "a card"
    parts: list[str] = []
    if crit.get("basic"):
        parts.append("basic")
    type_val = crit.get("type")
    if isinstance(type_val, str) and type_val:
        parts.append(type_val)
    elif isinstance(type_val, list) and type_val:
        parts.append(" or ".join(str(t) for t in type_val))
    label = " ".join(parts) if parts else "card"
    if "name" in crit:
        label = f'named "{crit["name"]}"'
    if "not_name" in crit:
        label = f'not named "{crit["not_name"]}"'
    bounds = []
    if "max_mana_value" in crit:
        bounds.append(f"mana value ≤ {crit['max_mana_value']}")
    if "min_mana_value" in crit:
        bounds.append(f"mana value ≥ {crit['min_mana_value']}")
    suffix = f" with {' and '.join(bounds)}" if bounds else ""
    article = "an" if label[:1].lower() in "aeiou" else "a"
    return f"{article} {label} card{suffix}"


def _type_matches(type_line: str, type_val: Any) -> bool:
    if not type_val:
        return True
    if isinstance(type_val, str):
        return type_val.lower() in type_line
    if isinstance(type_val, list):
        return any(str(t).lower() in type_line for t in type_val)
    raise ValueError(f"'type' must be a str or list (got {type(type_val).__name__})")


def _color_matches(card: Card, color_val: Any) -> bool:
    if not color_val:
        return True
    wanted = [color_val] if isinstance(color_val, str) else list(color_val)
    identity = card.color_identity
    return any(str(c).upper() in identity for c in wanted)
