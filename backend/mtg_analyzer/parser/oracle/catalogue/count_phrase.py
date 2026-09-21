"""Count phrases → structured selectors and count conditions (PAR-120).

"How many X" was spelled out in eleven phrase → selector tables (`_FOR_EACH_*`,
`_PT_CDA_*`, `_CONTROL_COUNT_*`, …) and one named branch per phrase in
`continuous.count_selector`. Here it is one grammar: the noun phrase
(`characteristic_phrase`, plural allowed) plus where the objects are —
"creatures you control", "lands your opponents control", "creature cards in your
graveyard", "cards in your hand" — becomes a structured selector::

    {"zone": "battlefield" | "graveyard" | "hand" | "exile" | "library",
     "of": "you" | "opponents" | "any",
     "filter": {<combat.matches_object_filter keys>},
     "distinct": "power" | "toughness" | "mana_value" | "name"}     # optional

which `continuous.count_selector` evaluates through the same filter every trigger
head and target phrase uses. On top of it, `parse_count_condition` reads the
comparator half of a leading "if": "you control three or more gates", "there are
seven or more creature cards in your graveyard", "an opponent controls more lands
than you". Anything unrecognised returns ``None``. Pure — no `game/` imports.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .characteristic_phrase import parse_object_phrase

#: A count phrase's location suffix → the selector keys it sets. "Your opponents'"
#: and "all" scopes are sums over those players' zones.
_ZONE_SUFFIXES: list[tuple[str, dict[str, str]]] = [
    (" in your graveyard", {"zone": "graveyard", "of": "you"}),
    (" in all graveyards", {"zone": "graveyard", "of": "any"}),
    (" in each graveyard", {"zone": "graveyard", "of": "any"}),
    (" in your opponents' graveyards", {"zone": "graveyard", "of": "opponents"}),
    (" in opponents' graveyards", {"zone": "graveyard", "of": "opponents"}),
    (" in each opponent's graveyard", {"zone": "graveyard", "of": "opponents"}),
    (" in your hand", {"zone": "hand", "of": "you"}),
    (" in your library", {"zone": "library", "of": "you"}),
    (" in exile", {"zone": "exile", "of": "any"}),
]

_OF_FOR_CONTROLLER = {"you": "you", "not_you": "opponents"}
_DIFFERENT = re.compile(r"\s+with different (?P<what>powers|toughnesses|names|mana values)")
_DISTINCT_KEYS = {
    "powers": "power", "toughnesses": "toughness", "names": "name", "mana values": "mana_value",
}
_ON_BATTLEFIELD = re.compile(r"\s+on the battlefield$")

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10,
}
_NUMBER = r"(?:\d+|" + "|".join(_NUMBER_WORDS) + r")"


def _number(text: str) -> int:
    return int(text) if text.isdigit() else _NUMBER_WORDS[text]


def parse_count_phrase(text: str) -> Optional[dict[str, Any]]:
    """The words after "for each" / "the number of" → a structured selector, or ``None``."""
    text = text.strip().lower()
    if not text:
        return None  # an empty phrase would count every permanent
    selector: dict[str, Any] = {}
    different = _DIFFERENT.search(text)
    if different is not None:
        selector["distinct"] = _DISTINCT_KEYS[different.group("what")]
        text = (text[: different.start()] + text[different.end():]).strip()
    for suffix, keys in _ZONE_SUFFIXES:
        if text.endswith(suffix):
            parsed = parse_object_phrase(text[: -len(suffix)], plural=True)
            if parsed is None or parsed[1] is not None:
                return None  # a controller tail contradicts the zone's owner
            selector.update(keys)
            if parsed[0]:
                selector["filter"] = parsed[0]
            return selector
    text = _ON_BATTLEFIELD.sub("", text)
    parsed = parse_object_phrase(text, plural=True)
    if parsed is None:
        return None
    filt, controller = parsed
    selector.update({"zone": "battlefield", "of": _OF_FOR_CONTROLLER.get(controller or "", "any")})
    if filt:
        selector["filter"] = filt
    return selector


#: The quantity words before the counted noun → the comparison bounds they mean.
#: Each returns ``(min, max, other)`` where ``other`` ("another") excludes the
#: ability's own source from the count.
def _quantity(text: str) -> Optional[tuple[Optional[int], Optional[int], bool, str]]:
    """Leading quantity words → ``(min, max, another, rest)``, or ``None``."""
    patterns: list[tuple[str, Any]] = [
        (rf"^(?P<n>{_NUMBER}) or more ", lambda n: (n, None)),
        (rf"^at least (?P<n>{_NUMBER}) ", lambda n: (n, None)),
        (rf"^(?P<n>{_NUMBER}) or (?:fewer|less) ", lambda n: (None, n)),
        (rf"^at most (?P<n>{_NUMBER}) ", lambda n: (None, n)),
        (rf"^exactly (?P<n>{_NUMBER}) ", lambda n: (n, n)),
        (rf"^more than (?P<n>{_NUMBER}) ", lambda n: (n + 1, None)),
        (rf"^fewer than (?P<n>{_NUMBER}) ", lambda n: (None, n - 1)),
    ]
    for pattern, bounds in patterns:
        m = re.match(pattern, text)
        if m is not None:
            low, high = bounds(_number(m.group("n")))
            return low, high, False, text[m.end():]
    m = re.match(r"^(?:a|an) ", text)
    if m is not None:
        return 1, None, False, text[m.end():]
    if text.startswith("another "):
        return 1, None, True, text[len("another "):]
    if text.startswith("no "):
        return None, 0, False, text[len("no "):]
    return None


_CONTROL = re.compile(r"^you control (?P<rest>.+)$")
_THERE_ARE = re.compile(r"^there (?:are|is) (?P<rest>.+)$")
_OPPONENT_MORE = re.compile(r"^an opponent controls more (?P<phrase>.+?) than you$")


def parse_count_condition(text: str) -> Optional[dict[str, Any]]:
    """A condition phrase about how many objects exist → a `control_count` /
    `opponent_has_more` condition dict, or ``None``.

    "you control `<quantity>` `<phrase>`" counts objects *you* control ("you
    control" is the scope, so the phrase names none); "there are `<quantity>`
    `<phrase>`" counts the phrase's own location ("… in your graveyard").
    """
    text = text.strip().lower().rstrip(".")
    m = _OPPONENT_MORE.match(text)
    if m is not None:
        selector = parse_count_phrase(m.group("phrase"))
        if selector is None or selector.get("of") != "any" or selector.get("zone") != "battlefield":
            return None
        return {"kind": "opponent_has_more", "selector": {**selector, "of": "you"}}
    control = _CONTROL.match(text)
    there = _THERE_ARE.match(text)
    if control is None and there is None:
        return None
    rest = (control or there).group("rest")
    quantity = _quantity(rest)
    if quantity is None:
        return None
    low, high, another, phrase = quantity
    selector = parse_count_phrase(phrase)
    if selector is None:
        return None
    if control is not None:
        if selector.get("zone") != "battlefield" or selector.get("of") != "any":
            return None  # "you control" already fixed the scope
        selector["of"] = "you"
    elif selector.get("zone") == "battlefield":
        pass  # "there are 4 or more creatures on the battlefield": any player's
    if another:
        selector["filter"] = {**selector.get("filter", {}), "not_reference": True}
    condition: dict[str, Any] = {"kind": "control_count", "selector": selector}
    if low is not None:
        condition["min"] = low
    if high is not None:
        condition["max"] = high
    return condition
