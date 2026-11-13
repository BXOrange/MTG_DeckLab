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
    KEYWORD_WORDS,
    parse_characteristic_phrase,
    parse_qualifier,
)
from .trigger_context import PHASE_TAILS, consume

_SPELL_PHRASE = re.compile(
    r"^(?:an?|another)\s+(?P<head>.*?)\s*\bspell\b\s*(?P<tail>.*)$", re.IGNORECASE | re.S
)
#: RULE 601.2: "other than your first spell" is the second or any later spell the player casts this turn.
SECOND_SPELL = 2
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
_ORDINAL_SPELL = re.compile(
    rf"^(?:your|their) (?P<n>{'|'.join(_ORDINALS)}) spell (?P<tail>.+)$"
)
#: PAR-207: "your first **instant or sorcery** spell each turn" -- the ordinal counts only the spells that match the
#: rest of the phrase (RULE 601: each spell cast is a separate event), so the same filter that scopes the trigger also
#: scopes the count (`is_nth_matching_spell_cast_this_turn`, read over the turn's `SPELL_CAST` events).
#: PAR-236: "your first instant or sorcery spell **from your graveyard** each turn" -- the origin is part of what is
#: counted (only casts from that zone are "such spells"), so it rides through to the trigger's ``spell_cast_from``.
_ORDINAL_TYPED_SPELL = re.compile(
    rf"^(?:your|their) (?P<n>{'|'.join(_ORDINALS)}) (?P<head>(?:[a-z'-]+ )+?)spell "
    r"(?P<origin>from your graveyard )?(?:each turn|in a turn)$"
)
#: PAR-236 / RULE 601.2: "a spell **other than your first spell** each turn" -- every cast after the first by that player
#: this turn. The typed form ("an instant spell other than the first instant spell that player casts each turn")
#: counts only the spells of that type, so the same ``spell_filter`` scopes the count.
_OTHER_THAN_FIRST = re.compile(
    r"^(?P<article>an?) (?P<head>(?:[a-z'-]+ )*?)spell other than (?:your|the|their) first "
    r"(?P<again>(?:[a-z'-]+ )*?)spell(?: (?:that player|they|you) casts?)? (?:each turn|in a turn)$"
)
_FIRST_X_SPELL = re.compile(
    r"^(?:your|their) first spell with \{x\} in its mana cost each turn$"
)

#: Everything a card can target that is a permanent (RULE 110.1).
_PERMANENT_TYPES = sorted(CARD_TYPES - {"instant", "sorcery"})

_QUALIFIER = re.compile(
    r"^with (?P<q>mana value \d+ or (?:greater|less)|(?:power|toughness) \d+ or (?:greater|less)|"
    r"\d+ or more card types|[a-z ]+?)(?=$| from | that | you )"
)
#: RULE 702: "another spell **that has flash**" -- a keyword the spell object itself has (`combat.has` reads the cast
#: object's keywords), the relative-clause spelling of the "with <keyword>" qualifier.
_THAT_HAS_KEYWORD = re.compile(rf"^that has (?P<kw>{'|'.join(re.escape(k) for k in KEYWORD_WORDS)})(?=$| from | you )")
#: PAR-236: the wider "that targets ..." clause -- "only", players, "~", "an opponent controls", "A or B" alternatives.
_TARGETS_CLAUSE = re.compile(r"^that targets (?P<only>only )?(?P<body>.+)$")
_TARGET_CONTROL = re.compile(r"^(?P<noun>.+?)(?: (?P<ctrl>you control|an opponent controls|you don't control))?$")
_TARGET_ARTICLE = re.compile(r"^(?:a single |an |a |another |1 or more |one or more )")
_TARGET_CONTROLLERS = {"you control": "you", "an opponent controls": "opponent", "you don't control": "not_you"}
#: The trigger key the binder reads (`game/binding/spell_target_predicates.py`); value `{alternatives, only}`.
SPELL_TARGET_CLAUSE_KEY = "spell_target_clause"

#: Cast-*context* tails (no captures): text → the trigger keys it sets. Zones are
#: `Zone` values — the `from_zone` `SPELL_CAST` stamps (RULE 601.2a).
_CONTEXT_TAILS: list[tuple[str, dict[str, Any]]] = [
    ("from your graveyard", {"spell_cast_from": ["graveyard"]}),
    ("from a graveyard", {"spell_cast_from": ["graveyard"]}),
    ("from exile", {"spell_cast_from": ["exile"]}),
    ("from your hand", {"spell_cast_from": ["hand"]}),
    ("from anywhere other than your hand", {"spell_not_cast_from_hand": True}),
    ("from anywhere other than their hand", {"spell_not_cast_from_hand": True}),
    ("you don't own", {"spell_not_owned": True}),
    *PHASE_TAILS,
]

#: Object-property tails with no captures → the filter keys they add. "Of the
#: chosen …" reads the *ability source's* ETB choice (RULE 601.2b), resolved by
#: `matches_object_filter`'s ``*_from_source`` keys.
_FILTER_TAILS: list[tuple[str, dict[str, Any]]] = [
    ("of the chosen color", {"color_from_source": True}),
    ("of the chosen type", {"subtype_from_source": True}),
    ("that has an adventure", {"has_adventure": True}),
]


def _target_alternative(part: str) -> Optional[dict[str, Any]]:
    """One "A" of "that targets A or B": a player, the ability's own object, or a permanent noun with its controller."""
    part = part.strip()
    if part == "~":
        return {"kind": "source"}
    if part == "you":
        return {"kind": "player", "relation": "you"}
    if part == "an opponent":
        return {"kind": "player", "relation": "opponent"}
    m = _TARGET_CONTROL.match(_TARGET_ARTICLE.sub("", part, count=1))
    if m is None or not _TARGET_ARTICLE.match(part):
        return None
    noun = m.group("noun").strip()
    if part.startswith(("1 or more ", "one or more ")) and noun.endswith("s"):
        noun = noun[:-1]  # "one or more creatures"
    if noun == "permanent":
        filt: dict[str, Any] = {"card_type_any": list(_PERMANENT_TYPES)}
    else:
        parsed = parse_characteristic_phrase(noun)
        if not parsed:
            return None
        filt = parsed
    return {"kind": "object", "filter": filt, "controller": _TARGET_CONTROLLERS.get(m.group("ctrl") or "")}


def _parse_targets_clause(tail: str) -> Optional[dict[str, Any]]:
    """``that targets ...`` → the trigger keys it sets (RULE 601.2c), or ``None``. The classic single "creature you
    control" shape keeps its long-standing keys; players, "opponent controls", "only" and "or" use the clause key."""
    m = _TARGETS_CLAUSE.match(tail)
    if m is None:
        return None
    only = bool(m.group("only"))
    body = m.group("body").strip()
    alternatives: list[dict[str, Any]] = []
    whole = _target_alternative(body)
    if whole is not None:
        alternatives = [whole]
    else:
        parts = re.split(r" or (?=an? |you\b|~)", body)
        if len(parts) < 2:
            return None
        for part in parts:
            alt = _target_alternative(part)
            if alt is None:
                return None
            alternatives.append(alt)
    if len(alternatives) == 1 and not only:
        alt = alternatives[0]
        if alt["kind"] == "source":
            return {"requires_spell_targets_source": True}
        if alt["kind"] == "object" and alt["controller"] in (None, "you"):
            return {"spell_targets": {**alt["filter"], **({"you_control": True} if alt["controller"] else {})}}
    return {SPELL_TARGET_CLAUSE_KEY: {"alternatives": alternatives, "only": only}}


def parse_spell_phrase(phrase: str) -> Optional[dict[str, Any]]:
    """``phrase`` (the words between "cast" and the comma) → trigger keys, or ``None``."""
    phrase = phrase.strip().lower()
    if _FIRST_X_SPELL.fullmatch(phrase):
        return {"first_x_spell": True, "spell_has_x": True}
    typed = _ORDINAL_TYPED_SPELL.fullmatch(phrase)
    ordinal = _ORDINAL_SPELL.fullmatch(phrase)
    other_than_first = _OTHER_THAN_FIRST.fullmatch(phrase)
    ordinal_keys: dict[str, Any] = {}
    if other_than_first:
        head_words = other_than_first.group("head")
        if head_words != other_than_first.group("again"):
            return None  # "an instant spell other than the first creature spell" counts something else
        if head_words:
            ordinal_keys["matching_spells_cast_this_turn_at_least"] = SECOND_SPELL
        else:
            ordinal_keys["spells_cast_this_turn_at_least"] = SECOND_SPELL
        phrase = f"{other_than_first.group('article')} {head_words}spell"
    elif typed:
        ordinal_keys["is_nth_matching_spell_cast_this_turn"] = _ORDINALS[typed.group("n")]
        phrase = f"a {typed.group('head')}spell"
        if typed.group("origin"):
            phrase += " from your graveyard"
    elif ordinal:
        tail = ordinal.group("tail")
        if tail in ("each turn", "in a turn"):
            tail = ""
        elif not any(tail == text for text, _ in PHASE_TAILS):
            return None
        ordinal_keys["is_nth_spell_cast_this_turn"] = _ORDINALS[ordinal.group("n")]
        phrase = "a spell " + tail
    m = _SPELL_PHRASE.match(phrase)
    if m is None:
        return None
    head = m.group("head").strip()
    # "a white **permanent** spell" (the Defilers): a permanent spell is a spell of any permanent type (RULE 110.1),
    # so — unlike the empty noun "permanent" on the battlefield — it excludes instants and sorceries.
    permanent_spell = head == "permanent" or head.endswith(" permanent")
    if permanent_spell:
        head = head[: -len("permanent")].strip()
    obj_filter = parse_characteristic_phrase(head)
    if obj_filter is None:
        return None
    if permanent_spell:
        if any(k in obj_filter for k in ("card_type", "card_type_all", "card_type_any", "any_of")):
            return None
        obj_filter["card_type_any"] = list(_PERMANENT_TYPES)
    keys: dict[str, Any] = dict(ordinal_keys)
    tail = m.group("tail").strip()
    while tail:
        if tail.startswith("with {x} in its mana cost"):
            if "spell_has_x" in keys:
                return None
            keys["spell_has_x"] = True
            tail = tail[len("with {x} in its mana cost"):].strip()
            continue
        q = _QUALIFIER.match(tail)
        if q is not None:
            extra = parse_qualifier(q.group("q"))
            if extra is None or any(k in obj_filter for k in extra):
                return None
            obj_filter.update(extra)
            tail = tail[q.end():].strip()
            continue
        has_kw = _THAT_HAS_KEYWORD.match(tail)
        if has_kw is not None:
            if "keyword" in obj_filter:
                return None
            obj_filter["keyword"] = KEYWORD_WORDS[has_kw.group("kw")]
            tail = tail[has_kw.end():].strip()
            continue
        if tail.startswith("that targets "):
            target_keys = _parse_targets_clause(tail)
            if target_keys is None or any(k in keys for k in target_keys):
                return None
            keys.update(target_keys)
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
