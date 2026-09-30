"""PAR-123 — a condition whose subject is a bare pronoun: "if **it** has flying", "if **that
creature's** power is 3 or greater", "if **it** was attacking".

Under a RULE 603.1 group trigger the pronoun is the object that fired the trigger. This grammar reads
the predicate and leaves the *subject* unstated — the caller (`segmenter._peel_condition` /
`_if_else_specs`) scopes the result to that object (`of: "trigger_subject"`), the one place that
knows a group trigger is in play. The result is a condition in the shared vocabulary
(`game/static_conditions.py`); a predicate outside it returns ``None`` so the whole clause stays
unclaimed rather than losing its gate.

No `game/` imports (docs/09): the keyword and subtype vocabularies come from this package.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .keywords import KEYWORDS, KeywordShape, keyword_slug
from .subtype_vocabulary import SUBTYPES

#: What "that `<noun>`" may name under a group trigger: the object types, or any creature subtype
#: ("whenever another Hero you control enters, put a counter on that hero").
PRONOUN_NOUN_ALT = "(?:creature|permanent|artifact|land|token|" + "|".join(
    re.escape(word) for word in sorted(SUBTYPES, key=len, reverse=True)
) + ")"

_SUBJECT = rf"(?:it|that {PRONOUN_NOUN_ALT})"
_POSSESSIVE = rf"(?:its|that {PRONOUN_NOUN_ALT}'s)"
_CARD_TYPES = ("artifact", "creature", "enchantment", "land", "planeswalker", "instant", "sorcery", "battle")
_CHARACTERISTICS = {"power": "power", "toughness": "toughness", "mana value": "mana_value"}
_CHARACTERISTIC_WORDS = "|".join(sorted(_CHARACTERISTICS, key=len, reverse=True))

#: "3 or greater"/"3 or more" is a lower bound (``min``), "3 or less"/"3 or fewer" an upper one.
_LOWER_WORDS = ("greater", "more")


def _negative(word: Optional[str]) -> bool:
    """Whether a captured verb is the negative spelling ("isn't", "wasn't", "was not", "doesn't have")."""
    return bool(word) and ("n't" in word or " not" in word)


def _negated(condition: dict[str, Any], word: Optional[str]) -> dict[str, Any]:
    return {"kind": "not", "condition": condition} if _negative(word) else condition


def _flag_keyword(word: str) -> Optional[str]:
    slug = keyword_slug(word.strip())
    definition = KEYWORDS.get(slug)
    if definition is not None and definition.shape is KeywordShape.FLAG:
        return definition.slug
    return None


_TYPE_RE = re.compile(
    rf"{_SUBJECT} (?P<neg>isn'?t|wasn'?t|is not|was not|is|was) an? (?P<word>[a-z]+)"
    r"(?: or (?P<word2>[a-z]+))?(?: card)?"
)
_KEYWORD_RE = re.compile(rf"{_SUBJECT} (?P<neg>doesn'?t have|didn'?t have|has|had) (?P<kw>[a-z ]+)")
_COUNTER_RE = re.compile(
    rf"{_SUBJECT} (?P<neg>doesn'?t have|didn'?t have|has|had) "
    r"(?:an? (?:(?P<kind>[+\-]\d+/[+\-]\d+|[a-z]+) )?counter|counters) on it"
)
_ATTACKING_RE = re.compile(rf"{_SUBJECT} (?P<neg>isn'?t|wasn'?t|is not|was not|is|was) attacking")
_ENTERED_RE = re.compile(
    rf"{_SUBJECT} (?P<neg>didn'?t enter|did not enter|entered|enters) (?:the battlefield )?this turn"
)
_CAST_RE = re.compile(
    rf"(?:{_SUBJECT} (?P<neg>wasn'?t|was not|was)|you (?P<cast>cast)) (?:cast|it)"
)
_THRESHOLD_RE = re.compile(
    rf"{_POSSESSIVE} (?P<what>{_CHARACTERISTIC_WORDS}) (?:is|was) (?P<n>\d+) or (?P<dir>greater|more|less|fewer)"
)
_SIZE_RE = re.compile(rf"{_SUBJECT} (?:is|was) (?P<p>\d+)/(?P<t>\d+)")
_COMPARE_RE = re.compile(
    rf"{_POSSESSIVE} (?P<what>power|toughness) (?:is|was) (?P<dir>greater|less) than "
    r"(?:~'s|~) ?(?P<other>power|toughness)?"
)
_EITHER_COMPARE_RE = re.compile(
    rf"{_SUBJECT} (?:has|had) (?P<dir>greater|less) power or toughness than ~"
)
_EITHER_COMPARE_OWN_RE = re.compile(
    rf"{_POSSESSIVE} power is greater than ~'s power or {_POSSESSIVE} toughness is greater than ~'s toughness"
)


def _characteristic(name: str, of: str) -> dict[str, Any]:
    return {"kind": "characteristic", "characteristic": name, "of": of}


def _compared(what: str, direction: str, other: str) -> dict[str, Any]:
    """The subject's ``what`` against the ability source's ``other`` (`amount_compare`)."""
    return {
        "kind": "amount_compare",
        "left": _characteristic(what, "trigger_subject"),
        "right": _characteristic(other, "source"),
        "op": "gt" if direction == "greater" else "lt",
    }


def parse_referent_condition(text: str) -> Optional[dict[str, Any]]:
    """``"it has flying"`` → a condition about that object, ``None`` outside the vocabulary.

    Comparisons against the ability's own source name their subject explicitly
    (``of: "trigger_subject"``), since only they mention two objects; every other result leaves
    ``of`` off for the caller to scope."""
    phrase = " ".join(text.strip().rstrip(".").lower().split())
    phrase = re.sub(r"^it's\b", "it is", phrase)

    m = _EITHER_COMPARE_OWN_RE.fullmatch(phrase)
    if m is not None:
        return {"kind": "any", "conditions": [
            _compared("power", "greater", "power"), _compared("toughness", "greater", "toughness"),
        ]}
    m = _EITHER_COMPARE_RE.fullmatch(phrase)
    if m is not None:
        return {"kind": "any", "conditions": [
            _compared("power", m.group("dir"), "power"), _compared("toughness", m.group("dir"), "toughness"),
        ]}
    m = _COMPARE_RE.fullmatch(phrase)
    if m is not None:
        return _compared(m.group("what"), m.group("dir"), m.group("other") or m.group("what"))

    m = _THRESHOLD_RE.fullmatch(phrase)
    if m is not None:
        bound = "min" if m.group("dir") in _LOWER_WORDS else "max"
        return {"kind": _CHARACTERISTICS[m.group("what")], bound: int(m.group("n"))}
    m = _SIZE_RE.fullmatch(phrase)
    if m is not None:
        power, toughness = int(m.group("p")), int(m.group("t"))
        return {"kind": "all", "conditions": [
            {"kind": "power", "min": power, "max": power},
            {"kind": "toughness", "min": toughness, "max": toughness},
        ]}

    m = _ATTACKING_RE.fullmatch(phrase)
    if m is not None:
        return _negated({"kind": "source_attacking"}, m.group("neg"))
    m = _ENTERED_RE.fullmatch(phrase)
    if m is not None:
        return _negated({"kind": "entered_this_turn"}, m.group("neg"))
    m = _CAST_RE.fullmatch(phrase)
    if m is not None:
        return _negated({"kind": "flag", "flag": "was_cast"}, m.group("neg"))

    m = _COUNTER_RE.fullmatch(phrase)
    if m is not None:
        kind = (m.group("kind") or "").strip()
        condition: dict[str, Any] = {"kind": "source_counters", "min": 1}
        if kind:
            condition["counter"] = kind
        return _negated(condition, m.group("neg"))

    m = _TYPE_RE.fullmatch(phrase)
    if m is not None:
        word = m.group("word")
        if m.group("word2") is not None:
            # "an instant or sorcery card": either type.
            if word not in _CARD_TYPES or m.group("word2") not in _CARD_TYPES:
                return None
            either = {"kind": "any", "conditions": [
                {"kind": "is_card_type", "card_type": word},
                {"kind": "is_card_type", "card_type": m.group("word2")},
            ]}
            return _negated(either, m.group("neg"))
        if word in _CARD_TYPES:
            return _negated({"kind": "is_card_type", "card_type": word}, m.group("neg"))
        if word in SUBTYPES:
            return _negated({"kind": "is_subtype", "subtype": word}, m.group("neg"))
        return None

    m = _KEYWORD_RE.fullmatch(phrase)
    if m is not None:
        slug = _flag_keyword(m.group("kw"))
        if slug is None:
            return None
        return _negated({"kind": "has_keyword", "keyword": slug}, m.group("neg"))
    return None
