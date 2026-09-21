"""The spell phrase of a cast trigger → `SPELL_CAST` trigger keys (PAR-119).

``whenever you cast <phrase>, …`` where the phrase composes a characteristic
head (`characteristic_phrase`), ``spell``, and any number of context tails::

    "a multicolored spell"
    "an instant or sorcery spell that targets a creature you control"
    "a creature spell with mana value 4 or greater"
    "a spell from anywhere other than your hand"
    "a legendary spell you don't own"

The head and its ``with`` qualifiers describe the *object* and become one
``spell_filter`` (a `combat.matches_object_filter` dict, read off the cast
object); where it was cast from, whose card it is and what it targets are cast
*context*, not object properties, so each is its own trigger key. Unknown words
anywhere fail the whole phrase closed. Pure — no `game/` imports.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .characteristic_phrase import (
    CARD_TYPES,
    parse_characteristic_phrase,
    parse_qualifier,
)
from .trigger_context import PHASE_TAILS, consume

_SPELL_PHRASE = re.compile(
    r"^(?:an?|another)\s+(?P<head>.*?)\s*\bspell\b\s*(?P<tail>.*)$", re.IGNORECASE | re.S
)

#: Everything a card can target that is a permanent (RULE 110.1).
_PERMANENT_TYPES = sorted(CARD_TYPES - {"instant", "sorcery"})

_QUALIFIER = re.compile(
    r"^with (?P<q>mana value \d+ or (?:greater|less)|(?:power|toughness) \d+ or (?:greater|less)|"
    r"[a-z ]+?)(?=$| from | that | you )"
)
_TARGETS = re.compile(
    r"^that targets (?:(?:an?|another|one or more)\s+)(?P<what>[a-z ]+?)(?P<yours>\s+you control)?$"
)

#: Cast-*context* tails (no captures): text → the trigger keys it sets. Zones are
#: `Zone` values — the `from_zone` `SPELL_CAST` stamps (RULE 601.2a).
_CONTEXT_TAILS: list[tuple[str, dict[str, Any]]] = [
    ("from your graveyard", {"spell_cast_from": ["graveyard"]}),
    ("from a graveyard", {"spell_cast_from": ["graveyard"]}),
    ("from exile", {"spell_cast_from": ["exile"]}),
    ("from your hand", {"spell_cast_from": ["hand"]}),
    ("from anywhere other than your hand", {"spell_not_cast_from_hand": True}),
    ("you don't own", {"spell_not_owned": True}),
    *PHASE_TAILS,
]

#: Object-property tails with no captures → the filter keys they add. "Of the
#: chosen …" reads the *ability source's* ETB choice (RULE 601.2b), resolved by
#: `matches_object_filter`'s ``*_from_source`` keys.
_FILTER_TAILS: list[tuple[str, dict[str, Any]]] = [
    ("of the chosen color", {"color_from_source": True}),
    ("of the chosen type", {"subtype_from_source": True}),
]


def _targets_filter(what: str, yours: bool) -> Optional[dict[str, Any]]:
    what = what.strip()
    if what.endswith("s"):  # "one or more creatures"
        what = what[:-1]
    if what == "permanent":
        filt: dict[str, Any] = {"card_type_any": list(_PERMANENT_TYPES)}
    else:
        parsed = parse_characteristic_phrase(what)
        if not parsed:
            return None
        filt = parsed
    if yours:
        filt = {**filt, "you_control": True}
    return filt


def parse_spell_phrase(phrase: str) -> Optional[dict[str, Any]]:
    """``phrase`` (the words between "cast" and the comma) → trigger keys, or ``None``."""
    m = _SPELL_PHRASE.match(phrase.strip().lower())
    if m is None:
        return None
    obj_filter = parse_characteristic_phrase(m.group("head"))
    if obj_filter is None:
        return None
    keys: dict[str, Any] = {}
    tail = m.group("tail").strip()
    while tail:
        q = _QUALIFIER.match(tail)
        if q is not None:
            extra = parse_qualifier(q.group("q"))
            if extra is None or any(k in obj_filter for k in extra):
                return None
            obj_filter.update(extra)
            tail = tail[q.end():].strip()
            continue
        t = _TARGETS.match(tail)
        if t is not None:
            if "spell_targets" in keys:
                return None
            tf = _targets_filter(t.group("what"), bool(t.group("yours")))
            if tf is None:
                return None
            keys["spell_targets"] = tf
            tail = ""
            continue
        frag, rest = consume(tail, _FILTER_TAILS)
        if frag is not None:
            if any(k in obj_filter for k in frag):
                return None
            obj_filter.update(frag)
            tail = rest
            continue
        ctx, rest = consume(tail, _CONTEXT_TAILS)
        if ctx is None or any(k in keys for k in ctx):
            return None
        keys.update(ctx)
        tail = rest
    if obj_filter:
        keys["spell_filter"] = obj_filter
    return keys
