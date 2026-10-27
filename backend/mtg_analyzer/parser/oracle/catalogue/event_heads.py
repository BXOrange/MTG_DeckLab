"""Trigger heads that name no object verb: activations, counter thresholds, board states (PAR-207).

``whenever <a player> activates <an ability>``, ``when the fourth <kind> counter is put on ~`` and the
RULE 603.8 *state* trigger ``when <a board state>`` each reduce to the same three-part shape the
object/player heads use -- an event name, a subject scope, and extra trigger keys -- so they are small
tables over vocabularies that already exist (the characteristic phrase for "an artifact or creature", the
`static_condition` predicate vocabulary for "there are no creatures on the battlefield"), not a regex per
card::

    "you activate an exhaust ability"
    "you activate a loyalty ability of a chandra planeswalker"
    "you activate an ability of an artifact or creature that isn't a mana ability"
    "the fourth plan counter is put on ~"
    "there are no creatures on the battlefield"
    "~ has flying"

Pure -- no `game/` imports (parser security boundary). The caller (`object_trigger_head.
parse_object_trigger_head`) tries these after every object/player head has declined.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .characteristic_phrase import parse_object_phrase
from .clause_hooks import static_condition
from .keywords import KEYWORDS, KeywordShape, keyword_slug
from .player_event_head import parse_player_event_head

#: Ordinal words a counter threshold may print ("the fourth plan counter"). RULE 122: counters are counted, so
#: the Nth counter is reached when the permanent holds N of that kind.
ORDINALS: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
}

_COUNTER_KIND = r"(?:[+\-]\d+/[+\-]\d+|[a-z]+)"
_COUNTER_THRESHOLD = re.compile(
    rf"^the (?P<ordinal>{'|'.join(ORDINALS)}) (?P<kind>{_COUNTER_KIND}) counter is put on (?P<subject>~)$"
)

#: "you activate `<what>`" -- RULE 602.2. Mana abilities never fire `ACTIVATED_ABILITY` (RULE 605.1a), so
#: "that isn't a mana ability" restates what the event already guarantees.
_ACTIVATE = re.compile(r"^you activate (?P<what>.+)$")
_NOT_MANA = " that isn't a mana ability"
_KINDED_ABILITY = re.compile(
    r"^an? (?P<kind>exhaust|loyalty) ability(?: of (?P<object>(?:a|an) .+))?$"
)
_ABILITY_OF = re.compile(r"^an ability of (?P<object>(?:a|an) .+)$")
#: The event fields `GameEngine.activate_ability` stamps on `ACTIVATED_ABILITY` for each kind.
_ABILITY_KIND_FIELDS = {"exhaust": "is_exhaust_ability", "loyalty": "is_loyalty_ability"}

#: A board state a head may name: only these openings, so a phrase that merely happens to parse as a condition
#: ("you control a creature") cannot turn into a trigger by accident.
_STATE_OPENING = re.compile(r"^(?:there (?:are|is) |you (?:control|have|don'?t control) |~ (?:has|is) )")
_SELF_HAS_KEYWORD = re.compile(r"^~ has (?P<keyword>[a-z ]+)$")

#: Player-event verbs this module adds to `player_event_head`'s table by rewriting to a phrase it knows.
_ENCHANTED_PLAYER_ATTACKED = "enchanted player is attacked"


def _activation_object(text: str) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    """The permanent whose ability was activated -> ``(condition keys, trigger keys)``, or ``None``."""
    article, _, phrase = text.partition(" ")
    parsed = parse_object_phrase(phrase)
    if article not in ("a", "an") or parsed is None:
        return None
    filt, controller = parsed
    if controller is not None:
        return None  # "you activate" already says whose; a second scope is not modelled
    condition: dict[str, Any] = {"subject": "group", "controller": "you", "other": False}
    if filt:
        condition["filter"] = filt
    return condition, {}


def _activation_head(cond: str) -> Optional[tuple[str, dict[str, Any], dict[str, Any]]]:
    m = _ACTIVATE.match(cond)
    if m is None:
        return None
    what = m.group("what").strip().removesuffix(_NOT_MANA)
    kinded = _KINDED_ABILITY.match(what)
    if kinded is not None:
        trigger: dict[str, Any] = {"filter": {_ABILITY_KIND_FIELDS[kinded.group("kind")]: True}}
        if kinded.group("object") is None:
            return "ACTIVATED_ABILITY", {"subject": "group", "controller": "you", "other": False}, trigger
        scoped = _activation_object(kinded.group("object"))
        if scoped is None:
            return None
        return "ACTIVATED_ABILITY", scoped[0], trigger
    ability_of = _ABILITY_OF.match(what)
    if ability_of is not None and what != m.group("what").strip():
        # Only with the explicit "isn't a mana ability": a bare "an ability of a creature" would read as
        # including mana abilities, which this event never reports.
        scoped = _activation_object(ability_of.group("object"))
        if scoped is None:
            return None
        return "ACTIVATED_ABILITY", scoped[0], {}
    return None


def _counter_threshold_head(cond: str) -> Optional[tuple[str, dict[str, Any], dict[str, Any]]]:
    m = _COUNTER_THRESHOLD.match(cond)
    if m is None:
        return None
    kind = m.group("kind")
    return "COUNTER", {"subject": "self"}, {
        "filter": {"kind": kind},
        "source_counter_reaches": {"count": ORDINALS[m.group("ordinal")], "kind": kind},
    }


#: RULE 107.14 / 122.1: "you get N or more {E}" -- energy counters placed on the player. `add_player_counters`
#: fires one `COUNTER` event per placement (``is_player``, ``kind``, ``amount``), whose recipient is the player.
_ENERGY_GAINED = re.compile(r"^you get (?P<n>\d+) or more \{e\}$")


def _energy_gained_head(cond: str) -> Optional[tuple[str, dict[str, Any], dict[str, Any]]]:
    m = _ENERGY_GAINED.match(cond)
    if m is None:
        return None
    event_filter: dict[str, Any] = {"kind": "energy", "is_player": True}
    if int(m.group("n")) > 1:
        event_filter["event_minimums"] = {"amount": int(m.group("n"))}
    return "COUNTER", {"subject": "you"}, {"filter": event_filter}


def _enchanted_player_attacked(cond: str) -> Optional[tuple[str, dict[str, Any], dict[str, Any]]]:
    if cond != _ENCHANTED_PLAYER_ATTACKED:
        return None
    # RULE 508.1 / 303.4: the same PLAYER_ATTACKED event as "a player attacks enchanted player".
    return parse_player_event_head("a player attacks enchanted player")


def _state_head(cond: str) -> Optional[tuple[str, dict[str, Any], dict[str, Any]]]:
    """RULE 603.8: "when `<board state>`" -- true now, not an event -- as a ``STATE_CHECK`` trigger, read through
    the shared state-predicate vocabulary (`static_handlers.static_condition`, late-bound via `clause_hooks`)."""
    if _STATE_OPENING.match(cond) is None:
        return None
    keyword = _SELF_HAS_KEYWORD.match(cond)
    if keyword is not None:
        slug = keyword_slug(keyword.group("keyword").strip())
        definition = KEYWORDS.get(slug)
        if definition is None or definition.shape is not KeywordShape.FLAG:
            return None
        state: Optional[dict[str, Any]] = {"kind": "has_keyword", "keyword": definition.slug}
    else:
        state = static_condition(cond)
    if state is None:
        return None
    return "STATE_CHECK", {}, {"state_condition": state}


def parse_event_head(cond: str) -> Optional[tuple[str, dict[str, Any], dict[str, Any]]]:
    """``(event, condition, trigger keys)`` for an activation / threshold / state head, or ``None``."""
    cond = cond.strip().lower()
    return (
        _activation_head(cond) or _counter_threshold_head(cond) or _energy_gained_head(cond)
        or _enchanted_player_attacked(cond)
        or _state_head(cond)
    )
