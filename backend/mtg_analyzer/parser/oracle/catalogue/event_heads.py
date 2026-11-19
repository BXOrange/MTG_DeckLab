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
_ACTIVATE = re.compile(r"^(?P<actor>you|a player|an opponent) activates? (?P<what>.+)$")
_NOT_MANA = " that isn't a mana ability"
_KINDED_ABILITY = re.compile(
    r"^an? (?P<kind>exhaust|loyalty) ability(?: of (?P<object>(?:a|an) .+|enchanted planeswalker))?$"
)
#: "an ability that isn't a mana ability" with no object: any non-mana activation (Burning-Tree Shaman).
_ANY_NON_MANA_ABILITY = "an ability"
#: Keyword abilities `GameEngine.activate_ability` labels with ``ActivationCost.ability_keyword`` (Boast's label rides on
#: its once-per-turn marker, PAR-256; Embalm/Eternalize carry theirs from `_graveyard_keyword_activated_ability`).
#: "outlast" is deliberately absent: the engine binds no activated ability for it, so a head naming it could never fire.
_LABELLED_KEYWORDS = ("boast", "eternalize", "embalm")
_KEYWORD_ABILITY = re.compile(
    rf"^an? (?P<kw>{'|'.join(_LABELLED_KEYWORDS)})(?: or (?P<kw2>{'|'.join(_LABELLED_KEYWORDS)}))? ability$"
)
#: RULE 603.1 / 106.1a: "whenever you activate an ability of a creature" includes mana abilities (RULE 605.1a only
#: removes them from *stack-using* abilities), which fire their own event; both are watched.
_ANY_ABILITY_EVENTS = ["ACTIVATED_ABILITY", "MANA_ABILITY_ACTIVATED"]
#: Who "activates": the player-subject scopes `binding.core._subject_condition` compares with the event's acting
#: player (``controller_id``) -- the same shape `player_event_head._ACTORS` gives every other player-event head.
_ACTIVATOR_SCOPES: dict[str, dict[str, Any]] = {
    "a player": {"subject": "player", "scope": "any"},
    "an opponent": {"subject": "player", "scope": "not_you"},
}
_ABILITY_OF = re.compile(r"^an ability of (?P<object>(?:a|an) .+)$")
#: The event fields `GameEngine.activate_ability` stamps on `ACTIVATED_ABILITY` for each kind.
_ABILITY_KIND_FIELDS = {"exhaust": "is_exhaust_ability", "loyalty": "is_loyalty_ability"}

#: A board state a head may name: only these openings, so a phrase that merely happens to parse as a condition
#: ("you control a creature") cannot turn into a trigger by accident.
#: PAR-286: "an opponent controls / has ..." and "a player has ..." name a state any one of those players satisfies.
_STATE_OPENING = re.compile(
    r"^(?:there (?:are|is) |you (?:control|have|don'?t control) |~ (?:has|is) |an opponent (?:controls|has) |a player has )"
)
_SELF_HAS_KEYWORD = re.compile(r"^~ has (?P<keyword>[a-z ]+)$")

#: Player-event verbs this module adds to `player_event_head`'s table by rewriting to a phrase it knows.
_ENCHANTED_PLAYER_ATTACKED = "enchanted player is attacked"


#: RULE 303.4m: the Aura's host as the permanent whose ability was activated ("whenever you activate a loyalty
#: ability of enchanted planeswalker" -- the Talent cycle). The host is read live, per firing, by the binder's
#: ``attached_permanent`` subject; ``activator_is_you`` keeps "you activate" meaning the Aura's controller (the
#: host may be an opponent's planeswalker, whose abilities its controller activates).
_ENCHANTED_PLANESWALKER = "enchanted planeswalker"


def _activation_object(text: str) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    """The permanent whose ability was activated -> ``(condition keys, trigger keys)``, or ``None``."""
    if text == _ENCHANTED_PLANESWALKER:
        return {"subject": "attached_permanent"}, {"activator_is_you": True}
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
    raw_what = m.group("what").strip()
    what = raw_what.removesuffix(_NOT_MANA)
    if m.group("actor") != "you":
        # "whenever a player/an opponent activates ...": the acting player is the subject, whatever the source's
        # controller. Only the two unscoped kinds exist on real cards (Burning-Tree Shaman, Gideon the Oathless).
        scope = dict(_ACTIVATOR_SCOPES[m.group("actor")])
        if what == _ANY_NON_MANA_ABILITY and raw_what != what:
            return "ACTIVATED_ABILITY", scope, {}
        kinded = _KINDED_ABILITY.match(what)
        if kinded is not None and kinded.group("kind") == "loyalty" and kinded.group("object") is None:
            return "ACTIVATED_ABILITY", scope, {"filter": {_ABILITY_KIND_FIELDS["loyalty"]: True}}
        return None
    keyworded = _KEYWORD_ABILITY.match(what)
    if keyworded is not None:
        names = sorted({keyworded.group("kw"), keyworded.group("kw2") or keyworded.group("kw")})
        # RULE 702.142 / 702.128 / 702.129: the activation's ``ability_keyword`` label (a list when two kinds are named).
        trigger_filter = {"ability_keyword": names[0]} if len(names) == 1 else {"ability_keyword_in": names}
        return "ACTIVATED_ABILITY", {"subject": "you"}, {"filter": trigger_filter}
    kinded = _KINDED_ABILITY.match(what)
    if kinded is not None:
        trigger: dict[str, Any] = {"filter": {_ABILITY_KIND_FIELDS[kinded.group("kind")]: True}}
        if kinded.group("object") is None:
            return "ACTIVATED_ABILITY", {"subject": "group", "controller": "you", "other": False}, trigger
        scoped = _activation_object(kinded.group("object"))
        if scoped is None:
            return None
        return "ACTIVATED_ABILITY", scoped[0], {**trigger, **scoped[1]}
    ability_of = _ABILITY_OF.match(what)
    if ability_of is not None:
        scoped = _activation_object(ability_of.group("object"))
        if scoped is None:
            return None
        if what != raw_what:
            # With the explicit "isn't a mana ability": the stack-using event alone.
            return "ACTIVATED_ABILITY", scoped[0], {}
        return _ANY_ABILITY_EVENTS, scoped[0], {}
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


#: RULE 706 (PAR-286): "a 6 is rolled on a 6-sided die" (Chicken a la King) -- any player's kept die whose natural face is
#: that number on a die with that many sides (one `DIE_RESULT` per kept die).
_DIE_ROLLED_ON = re.compile(r"^an? (?P<n>\d+) is rolled on an? (?P<sides>\d+)-sided die$")


def _die_rolled_on_head(cond: str) -> Optional[tuple[str, dict[str, Any], dict[str, Any]]]:
    m = _DIE_ROLLED_ON.match(cond)
    if m is None or m.group("n") != m.group("sides"):
        return None  # only the die's highest face is printed this way
    return "DIE_RESULT", {"subject": "player", "scope": "any"}, {
        "filter": {"natural_result": int(m.group("n")), "sides": int(m.group("sides"))},
    }


def parse_event_head(cond: str) -> Optional[tuple[str, dict[str, Any], dict[str, Any]]]:
    """``(event, condition, trigger keys)`` for an activation / threshold / state head, or ``None``."""
    cond = cond.strip().lower()
    return (
        _activation_head(cond) or _counter_threshold_head(cond) or _energy_gained_head(cond)
        or _enchanted_player_attacked(cond) or _die_rolled_on_head(cond)
        or _state_head(cond)
    )
