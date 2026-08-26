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
  ``max_power``       int  — printed power ≤ this (Imperial Recruiter's "with
                      power 2 or less") — a non-creature card (``power`` is
                      ``None``) never matches a ``max_power``/``min_power``
                      bound, the same fail-closed treatment ``max_mana_value``
                      gets from an unset ``converted_mana_cost``.
  ``min_power``       int  — printed power ≥ this.
  ``max_toughness``   int  — printed toughness ≤ this (Recruiter of the
                      Guard's "with toughness 2 or less").
  ``min_toughness``   int  — printed toughness ≥ this.
  ``name``            str  — exact card name, case-insensitive ("a card named…").
  ``color``           str | list[str] — a colour ("W"/"U"/"B"/"R"/"G") that
                      must be in the card's colour identity; a list is an OR.
                      ``"colorless"`` is a special entry meaning an *empty*
                      colour identity instead (Eye of Ugin's "a colorless
                      creature card") — the opposite check, since nothing is
                      ever "colorless" *in* an identity set.
  ``has_mana_ability`` bool — the card's own printed oracle text reads like a
                      mana ability ("an artifact card **with a mana
                      ability**" — Moonsilver Key). A plain oracle-text
                      heuristic (an "Add" mana symbol/wording present) rather
                      than a real `game/mana_abilities.py` parse — this
                      module deliberately imports nothing from `game/` (see
                      the module docstring), and the heuristic already
                      matches every real printed mana ability template.
  ``or``              list[dict] — this whole criteria dict matches if *any*
                      alternative in the list does ("an artifact card with a
                      mana ability **or** a basic land card" — each
                      alternative is itself a complete criteria dict, not
                      merged with the outer one).
"""

from __future__ import annotations

from typing import Any, Union

from .card import Card

#: What a search can be parameterized by — a string shorthand or a dict.
Criteria = Union[str, dict[str, Any], None]

#: Recognized dict keys, so an unknown key fails closed instead of being
#: silently ignored (which would over-match and search wrongly).
_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "type", "basic", "max_mana_value", "min_mana_value",
        "max_power", "min_power", "max_toughness", "min_toughness",
        "name", "not_name", "color", "without_type", "has_mana_ability", "or",
        "nonlegendary",
    }
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
    # "a **noncreature, nonland** card" (Narset, Parter of Veils) — the
    # negated sibling of ``type`` above, one or more words that must all be
    # *absent* from the type line (AND-combined with each other, same as
    # every other key in this dict combining with the rest).
    without_type = crit.get("without_type")
    if without_type is not None and _type_matches(type_line, without_type):
        return False
    if crit.get("basic") and "basic" not in type_line:
        return False
    # "a nonlegendary card" (Unmarked Grave, MEC-43) — the negation of the
    # already-recognized "legendary" type-line word, its own key rather
    # than a magic string in ``without_type`` so a criteria dict stays
    # literal data (mirrors ``not_name``'s own treatment of ``name``).
    if crit.get("nonlegendary") and "legendary" in type_line:
        return False
    if "max_mana_value" in crit and card.converted_mana_cost > crit["max_mana_value"]:
        return False
    if "min_mana_value" in crit and card.converted_mana_cost < crit["min_mana_value"]:
        return False
    if "max_power" in crit and (card.power is None or card.power > crit["max_power"]):
        return False
    if "min_power" in crit and (card.power is None or card.power < crit["min_power"]):
        return False
    if "max_toughness" in crit and (card.toughness is None or card.toughness > crit["max_toughness"]):
        return False
    if "min_toughness" in crit and (card.toughness is None or card.toughness < crit["min_toughness"]):
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
    if crit.get("has_mana_ability") and not _has_mana_ability(card):
        return False
    alternatives = crit.get("or")
    if alternatives is not None and not any(matches(card, alt) for alt in alternatives):
        return False
    return True


def _has_mana_ability(card: Card) -> bool:
    """A plain oracle-text heuristic for "has a mana ability" — see
    ``has_mana_ability``'s own docstring above."""
    text = (card.oracle_text or "").lower()
    return "add {" in text or "add one mana" in text or "add an amount of" in text


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
    if "max_power" in crit:
        bounds.append(f"power ≤ {crit['max_power']}")
    if "min_power" in crit:
        bounds.append(f"power ≥ {crit['min_power']}")
    if "max_toughness" in crit:
        bounds.append(f"toughness ≤ {crit['max_toughness']}")
    if "min_toughness" in crit:
        bounds.append(f"toughness ≥ {crit['min_toughness']}")
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
    # "colorless" is a real (if unusual) search word ("a colorless creature
    # card" — Eye of Ugin) meaning an *empty* colour identity, not a WUBRG
    # letter to look for among the card's colours — the opposite check from
    # every other entry in ``wanted``, so it can't share the membership test
    # below (nothing is ever "colorless" *in* an identity set).
    return any(
        not identity if str(c).lower() == "colorless" else str(c).upper() in identity
        for c in wanted
    )
