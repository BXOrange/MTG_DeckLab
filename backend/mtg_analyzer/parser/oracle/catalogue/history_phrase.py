"""Turn-history conditions → `event_this_turn` (ENG-47 / PAR-120).

"If a creature you controlled died this turn", "if you gained life this turn",
"if two or more nonland permanents entered the battlefield under your control this
turn", "if you haven't cast a spell from your hand this turn". Each is *the head of a
trigger, in the past tense, asked over the turn's event log*: the subject is the same
noun phrase (`characteristic_phrase`) and the event the same one the triggered
ability of that shape watches, so the condition is a trigger-shaped dict that the
engine evaluates with the binder's own predicate against the turn-stamped
`GameState.event_log` (`static_conditions` kind ``event_this_turn``) — no hand-kept
`*_this_turn` tracker per phrase. Anything unrecognised returns ``None``. Pure — no
`game/` imports.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .characteristic_phrase import parse_object_phrase
from .count_phrase import _NUMBER, _number
from .object_trigger_head import parse_object_trigger_head
from .spell_phrase import parse_spell_phrase

_THIS_TURN = re.compile(r"\s+this turn$")

#: Past-tense object verb → the event it names.
_OBJECT_VERBS: list[tuple[str, str]] = [
    ("entered the battlefield", "ENTERS_BATTLEFIELD"),
    ("left the battlefield", "LEAVES_BATTLEFIELD"),
    ("entered", "ENTERS_BATTLEFIELD"),
    ("attacked", "ATTACKS"),
    ("blocked", "BLOCKS"),
    ("died", "DIES"),
    ("fought", "FIGHTS"),
]
_CONTROL_TAILS = [
    (" under your control", "you"),
    (" under an opponent's control", "not_you"),
]
#: "you <verb>" with no object: the player events that carry only the player.
_PLAYER_VERBS: dict[str, "str | list[str]"] = {
    "gained life": "LIFE_GAINED", "gain life": "LIFE_GAINED",
    "lost life": "LIFE_LOST", "lose life": "LIFE_LOST",
    "gained or lost life": ["LIFE_GAINED", "LIFE_LOST"],
    "attacked": "PLAYER_ATTACKED", "attack": "PLAYER_ATTACKED",
    "played a land": "LAND_PLAYED", "play a land": "LAND_PLAYED",
    "committed a crime": "CRIME_COMMITTED", "commit a crime": "CRIME_COMMITTED",
}
_YOU_CONTROL_THAT = re.compile(r"^you control (?P<object>(?:an?|\d+ or more) .+?) that (?P<verb>[a-z ]+)$")
_NEGATION = re.compile(r"^you (?:haven't|didn't|have not|did not) ")
_YOU = re.compile(r"^you(?:'ve| have)? ")


def _quantity(text: str) -> Optional[tuple[Optional[int], Optional[int], str]]:
    """Leading quantity words → ``(min, max, rest)``; ``None`` when there are none."""
    m = re.match(rf"^(?P<n>{_NUMBER}) or more ", text)
    if m:
        return _number(m.group("n")), None, text[m.end():]
    m = re.match(r"^(?:a|an|one or more) ", text)
    if m:
        return 1, None, text[m.end():]
    m = re.match(r"^no ", text)
    if m:
        return None, 0, text[m.end():]
    return None


def _condition(trigger: dict[str, Any], low: Optional[int], high: Optional[int]) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": "event_this_turn", "trigger": trigger}
    if low is not None:
        out["min"] = low
    if high is not None:
        out["max"] = high
    return out


def _object_event(text: str) -> Optional[dict[str, Any]]:
    """``[<quantity>] <object phrase> <past verb> [under whose control]`` → a condition."""
    quantity = _quantity(text)
    if quantity is None:
        return None
    low, high, rest = quantity
    rest = rest.replace(" you controlled", " you control")
    for verb, event in _OBJECT_VERBS:
        marker = f" {verb}"
        cut = rest.find(marker)
        if cut < 0:
            continue
        subject, tail = rest[:cut], rest[cut + len(marker):]
        if tail == "":
            control = None
        else:
            control = next((scope for text_, scope in _CONTROL_TAILS if tail == text_), False)
            if control is False:
                return None
        parsed = parse_object_phrase(subject, plural=True)
        if parsed is None:
            return None
        filt, controller = parsed
        if control is not None:
            if controller is not None:
                return None
            controller = control
        group: dict[str, Any] = {
            "subject": "group", "controller": controller or "any", "other": False,
        }
        if filt:
            group["filter"] = filt
        return _condition({"event": event, "condition": group}, low, high)
    return None


def _singular_object(rest: str) -> Optional[str]:
    """A plural object phrase ("clues", "creatures") back to its singular words — only
    for a phrase the noun grammar reads, else ``None``."""
    if parse_object_phrase(rest, plural=True) is None:
        return None
    singular = rest[:-1] if rest.endswith("s") else rest
    return singular if parse_object_phrase(singular) is not None else rest


def _player_event(text: str, negated: bool) -> Optional[dict[str, Any]]:
    """``you <verb> …`` (already stripped of "you" and any negation) → a condition."""
    if text in ("created a token", "create a token"):
        # A token is created under its creator's control, so "you created a token" is "a token
        # entered the battlefield under your control" (a token put onto the battlefield for
        # someone else's benefit is the one place these differ — none in the pool).
        condition = _object_event("a token entered the battlefield under your control")
        if condition is not None and negated:
            condition.pop("min", None)
            condition["max"] = 0
        return condition
    if text in _PLAYER_VERBS:
        trigger = {"event": _PLAYER_VERBS[text], "condition": {"subject": "you"}}
        return _condition(trigger, None if negated else 1, 0 if negated else None)
    m = re.match(r"^cast (?P<rest>.+)$", text)
    if m is not None:
        quantity = _quantity(m.group("rest"))
        if quantity is None:
            return None
        low, high, rest = quantity
        singular = re.sub(r"\bspells\b", "spell", rest)
        keys = parse_spell_phrase(f"a {singular}") if re.search(r"\bspell\b", singular) else None
        if keys is None:
            return None
        trigger = {"event": "SPELL_CAST", "condition": {"subject": "you"}, **keys}
        return _condition(trigger, None if negated else low, 0 if negated else high)
    m = re.match(r"^(?P<verb>discarded|sacrificed) (?P<rest>.+)$", text)
    if m is not None:
        quantity = _quantity(m.group("rest"))
        if quantity is None:
            return None
        low, high, rest = quantity
        present = "discard" if m.group("verb") == "discarded" else "sacrifice"
        singular = _singular_object(rest)
        head = parse_object_trigger_head(f"you {present} a {singular}") if singular else None
        if head is None:
            return None
        trigger = {"event": head.event, "condition": head.condition, **head.trigger}
        return _condition(trigger, None if negated else low, 0 if negated else high)
    m = re.match(r"^attack with (?P<rest>.+)$", text)
    if m is not None and negated:
        quantity = _quantity(m.group("rest"))
        if quantity is None:
            return None
        singular = _singular_object(quantity[2])
        head = parse_object_trigger_head(f"a {singular} you control attacks") if singular else None
        if head is None:
            return None
        return _condition({"event": head.event, "condition": head.condition}, None, 0)
    return None


def parse_history_condition(text: str) -> Optional[dict[str, Any]]:
    """A "… this turn" condition phrase → an ``event_this_turn`` condition, or ``None``."""
    text = text.strip().lower().rstrip(".")
    stripped = _THIS_TURN.sub("", text)
    if stripped == text:
        return None
    controlled = _YOU_CONTROL_THAT.match(stripped)
    if controlled is not None:
        # "you control a creature that fought" is "a creature you control fought".
        stripped = f"{controlled.group('object')} you control {controlled.group('verb')}"
    negation = _NEGATION.match(stripped)
    if negation is not None:
        return _player_event(stripped[negation.end():], negated=True)
    if _YOU.match(stripped):
        return _player_event(_YOU.sub("", stripped, count=1), negated=False)
    return _object_event(stripped)
