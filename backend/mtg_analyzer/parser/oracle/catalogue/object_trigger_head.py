"""The condition of an object-event trigger → event(s) + subject scope (PAR-119).

``whenever <subject> <verb> [or <verb>] [tails], …`` for the object events —
enters, dies, attacks, blocks, leaves the battlefield, deals [combat] damage [to
<recipient>] — and ``whenever <player> <verb> <object>`` for the events a player
does *to* an object (sacrifice, discard)::

    "another nontoken creature you control dies"
    "a creature you control with power 4 or greater enters"
    "your commander enters or attacks"
    "~ or another legendary creature you control enters"
    "a land enters during your turn"
    "whenever you sacrifice another permanent"
    "whenever an opponent discards a creature card"
    "whenever a creature you control with a counter on it deals combat damage to a player"

The subject is one `characteristic_phrase` noun phrase, so a new adjective, type
or qualifier needs no row here; the verbs and tails are the only tables. The
result is the same ``{"subject": "group", …}`` condition the older per-adjective
regexes in `segmenter` emit, plus a ``filter`` (a `combat.matches_object_filter`
dict) that the binder reads off the acting object. Anything unrecognised returns
``None`` and the trigger stays unclaimed — including a "… this turn" tail: on an
instant or sorcery that is a trigger created at resolution (RULE 603.7a), which
`segmenter._turn_trigger_segment` strips and wraps *before* this grammar sees the
head; a permanent's ability can never carry it. Pure — no `game/` imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .characteristic_phrase import parse_object_phrase
from .player_event_head import parse_player_event_head
from .trigger_context import PHASE_TAILS, consume

#: Verb phrase → `EventType` name (RULE 603.1). "Enters" carries an optional
#: trailing "the battlefield" in its older printing.
_VERBS: dict[str, str] = {
    "enters": "ENTERS_BATTLEFIELD",
    "dies": "DIES",
    "attacks": "ATTACKS",
    "blocks": "BLOCKS",
    "leaves the battlefield": "LEAVES_BATTLEFIELD",
}
_VERB_ALT = r"(?:enters(?: the battlefield)?|dies|attacks|blocks|leaves the battlefield)"
_HEAD = re.compile(
    rf"^(?P<subject>.+?)\s+(?P<v1>{_VERB_ALT})(?:\s+or\s+(?P<v2>{_VERB_ALT}))?(?P<tail>\s.*)?$"
)
#: "<player> <verb> <object>" — the actor is a player, the acted-on object is the
#: subject of the filter. Verb → `EventType`; both events fire once per object,
#: name the object as ``instance_id`` and the acting player under
#: `binding.core._GROUP_CONTROLLER_EVENT_KEYS`.
_ACTOR_VERBS: dict[str, str] = {
    "sacrifice": "SACRIFICE", "sacrifices": "SACRIFICE",
    "discard": "DISCARD_CARD", "discards": "DISCARD_CARD",
}
_ACTOR_SCOPE: dict[str, str] = {
    "you": "you", "an opponent": "not_you", "each opponent": "not_you", "a player": "any",
    "each player": "any",
}
#: "<subject> deals [combat|noncombat] damage [to <recipient>]" — RULE 120.3. The
#: DAMAGE event names its *source* (``source_id``/``source_controller_id``), so
#: the subject phrase filters the damage source; the recipient is player-or-object.
_DAMAGE_HEAD = re.compile(
    r"^(?P<subject>.+?)\s+deals\s+(?P<kind>combat |noncombat )?damage"
    r"(?:\s+to\s+(?P<recipient>.+?))?(?P<tail>\s+during .+)?$"
)
_ATTACHED_SUBJECT = re.compile(r"^(?:enchanted|equipped)\s+(?:creature|permanent|land|artifact)$")
_ACTOR_HEAD = re.compile(
    r"^(?P<actor>you|an opponent|each opponent|a player|each player)\s+"
    r"(?P<verb>sacrifices?|discards?)\s+(?P<object>.+)$"
)
_SUBJECT_ARTICLE = re.compile(r"^(?P<article>another|an|a)\s+(?P<phrase>.+)$")
_SELF_OR_ANOTHER = re.compile(r"^~ or another\s+(?P<phrase>.+)$")

#: Attack-only tails: RULE 506.4's defending-player scope, as condition keys
#: `effect_binder._build_group_ok` reads off the ATTACKS event. Longest first.
_ATTACK_TAILS: list[tuple[str, dict[str, Any]]] = [
    ("you or a planeswalker you control", {"attacks_you_or_planeswalker": True}),
    ("you", {"attacks_you": True}),
    ("enchanted player", {"attacks_enchanted_player": True}),
]


@dataclass(frozen=True)
class ObjectHead:
    event: "str | list[str]"
    condition: dict[str, Any]
    trigger: dict[str, Any] = field(default_factory=dict)


def _event_name(verb: str) -> str:
    return _VERBS[verb.removesuffix(" the battlefield") if verb.startswith("enters") else verb]


def _subject(text: str) -> Optional[dict[str, Any]]:
    """The subject words → the group condition's scope keys, or ``None``."""
    if text == "your commander":
        # RULE 903.3: a commander is designated, so it is a filter, not a type.
        return {"subject": "group", "controller": "you", "other": False,
                "filter": {"is_commander": True}}
    subject, other = "group", False
    m = _SELF_OR_ANOTHER.match(text)
    if m is not None:
        subject, other, phrase = "self_or_group", True, m.group("phrase")
    else:
        m = _SUBJECT_ARTICLE.match(text)
        if m is None:
            return None
        other, phrase = m.group("article") == "another", m.group("phrase")
    parsed = parse_object_phrase(phrase)
    if parsed is None:
        return None
    filt, controller = parsed
    condition: dict[str, Any] = {
        "subject": subject, "controller": controller or "any", "other": other,
    }
    if filt:
        condition["filter"] = filt
    return condition


def _damage_recipient(text: str) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    """The words after "damage to" → ``(event filter keys, condition keys)``."""
    if text in ("a player", "each player"):
        return {"is_player": True}, {}
    if text in ("an opponent", "one of your opponents", "1 of your opponents"):
        return {"is_player": True}, {"recipient_is_opponent": True}
    if text == "you":
        return {"is_player": True}, {"recipient_is_you": True}
    if text in ("a player or planeswalker", "a player or a planeswalker"):
        return {"player_or_planeswalker": True}, {}
    article = _SUBJECT_ARTICLE.match(text)
    if article is None:
        return None
    parsed = parse_object_phrase(article.group("phrase"))
    if parsed is None or parsed[1] is not None or not parsed[0]:
        return None  # whose it is would need a recipient-controller scope no card prints
    return {"is_player": False}, {"recipient_filter": parsed[0]}


def _parse_damage_head(cond: str) -> Optional[ObjectHead]:
    m = _DAMAGE_HEAD.match(cond)
    if m is None:
        return None
    subject = m.group("subject").strip()
    if subject == "~":
        condition: Optional[dict[str, Any]] = {"subject": "self"}
    elif _ATTACHED_SUBJECT.match(subject):
        condition = {"subject": "attached_permanent"}
    else:
        condition = _subject(subject)
    if condition is None or condition["subject"] == "self_or_group":
        return None
    event_filter: dict[str, Any] = {}
    kind = (m.group("kind") or "").strip()
    if kind:
        event_filter["combat"] = kind == "combat"
    if m.group("recipient"):
        recipient = _damage_recipient(m.group("recipient").strip())
        if recipient is None:
            return None
        if recipient[1] and condition["subject"] != "group":
            # Only the group subject's predicate reads the recipient scope keys;
            # emitting them on a self/attached subject would silently over-fire.
            return None
        event_filter.update(recipient[0])
        condition.update(recipient[1])
    trigger: dict[str, Any] = {"filter": event_filter}
    tail = (m.group("tail") or "").strip()
    if tail:
        phase, rest = consume(tail, PHASE_TAILS)
        if phase is None or rest:
            return None
        trigger.update(phase)
    return ObjectHead("DAMAGE", condition, trigger)


def _parse_actor_head(cond: str) -> Optional[ObjectHead]:
    m = _ACTOR_HEAD.match(cond)
    if m is None:
        return None
    event = _ACTOR_VERBS[m.group("verb")]
    text = m.group("object").strip()
    trigger: dict[str, Any] = {}
    for phase_text, keys in PHASE_TAILS:
        if text.endswith(" " + phase_text):
            trigger.update(keys)
            text = text[: -len(phase_text)].strip()
            break
    condition: Optional[dict[str, Any]]
    if text == "~":
        condition = {"subject": "self"}
    else:
        condition = _subject(text)
    if condition is None:
        return None
    if condition["subject"] != "group" and event != "SACRIFICE":
        # A discarded card is already in the graveyard, where a plain triggered
        # ability of that card cannot fire.
        return None
    if condition["subject"] != "self":
        if condition["controller"] != "any":
            return None  # "sacrifice a creature you control": the actor already says whose
        condition["controller"] = _ACTOR_SCOPE[m.group("actor")]
    elif m.group("actor") != "you":
        return None  # only its controller can sacrifice a permanent as this ability's subject
    return ObjectHead(event, condition, trigger)


#: "you attack with `<quantity>` `<creatures>`" / "~ and at least N other creatures
#: attack" — a count over the whole declaration (`ATTACKERS_DECLARED`), not one
#: attacker. Quantity words are digits by the time the normaliser is done.
_ATTACK_WITH = re.compile(
    r"^you attack with (?:(?P<min>\d+) or more|at least (?P<atleast>\d+)|exactly (?P<exact>\d+)) "
    r"(?P<phrase>.+)$"
)
_SELF_AND_OTHERS_ATTACK = re.compile(r"^~ and at least (?P<n>\d+) other (?P<phrase>.+) attack$")


def _attackers_spec(
    phrase: str, low: Optional[int], high: Optional[int], *, other: bool, includes_source: bool
) -> Optional[ObjectHead]:
    other = other or phrase.startswith("other ")
    phrase = phrase.removeprefix("other ")
    parsed = parse_object_phrase(phrase, plural=True)
    if parsed is None:
        return None
    filt, controller = parsed
    if controller not in (None, "you"):
        return None  # only your own creatures can attack for you
    spec: dict[str, Any] = {"filter": filt}
    if low is not None:
        spec["min"] = low
    if high is not None:
        spec["max"] = high
    if other:
        spec["other"] = True
    if includes_source:
        spec["includes_source"] = True
    return ObjectHead("ATTACKERS_DECLARED", {"subject": "you"}, {"attackers_declared": spec})


def _parse_attack_batch_head(cond: str) -> Optional[ObjectHead]:
    m = _ATTACK_WITH.match(cond)
    if m is not None:
        exact = m.group("exact")
        low = int(m.group("min") or m.group("atleast") or exact)
        return _attackers_spec(
            m.group("phrase"), low, low if exact else None, other=False, includes_source=False
        )
    m = _SELF_AND_OTHERS_ATTACK.match(cond)
    if m is not None:
        return _attackers_spec(m.group("phrase"), int(m.group("n")), None, other=True, includes_source=True)
    return None


#: "<subject> blocks <a creature …>" / "becomes blocked by <a creature …>" / "blocks or
#: becomes blocked by <a creature …>" — the block relation, whose other side is an object
#: filter over the event's ``related_ids``.
_BLOCK_RELATION = re.compile(
    r"^(?P<subject>.+?)\s+(?:(?P<both>blocks or becomes blocked by)|(?P<blocks>blocks)|"
    r"(?P<blocked>becomes blocked by))\s+(?P<other>(?:a|an) .+)$"
)


def _parse_block_relation_head(cond: str) -> Optional[ObjectHead]:
    m = _BLOCK_RELATION.match(cond)
    if m is None:
        return None
    subject = m.group("subject").strip()
    condition = {"subject": "self"} if subject == "~" else _subject(subject)
    if condition is None or condition["subject"] == "self_or_group":
        return None
    other = _SUBJECT_ARTICLE.match(m.group("other"))
    parsed = parse_object_phrase(other.group("phrase")) if other else None
    if parsed is None or not parsed[0]:
        return None
    if parsed[1] is not None:  # whose creature it is is not modelled
        return None
    if m.group("both"):
        events: "str | list[str]" = ["BLOCKS", "BECOMES_BLOCKED"]
    else:
        events = "BLOCKS" if m.group("blocks") else "BECOMES_BLOCKED"
    # Any creature is every attacker/blocker there is, so it adds nothing to the plain head.
    related = {} if parsed[0] == {"card_type": "creature"} else {"related_filter": parsed[0]}
    return ObjectHead(events, condition, related)


def parse_object_trigger_head(cond: str) -> Optional[ObjectHead]:
    """``cond`` — the trigger condition with its "when"/"whenever" stripped."""
    cond = cond.strip().lower()
    player = parse_player_event_head(cond)
    if player is not None:
        return ObjectHead(*player)
    actor = (
        _parse_actor_head(cond) or _parse_damage_head(cond) or _parse_attack_batch_head(cond)
        or _parse_block_relation_head(cond)
    )
    if actor is not None:
        return actor
    m = _HEAD.match(cond)
    if m is None:
        return None
    subject_text = m.group("subject").strip()
    if subject_text == "~" and (m.group("tail") or "").strip() == "and isn't blocked":
        condition: Optional[dict[str, Any]] = {"subject": "self"}  # the source itself
    else:
        condition = _subject(subject_text)
    if condition is None:
        return None
    events = [_event_name(m.group("v1"))]
    if m.group("v2"):
        events.append(_event_name(m.group("v2")))
    trigger: dict[str, Any] = {}
    tail = (m.group("tail") or "").strip()
    while tail:
        if tail.startswith("alone") and events == ["ATTACKS"]:
            events, tail = ["ATTACKS_ALONE"], tail[len("alone"):].strip()
            continue
        if tail.startswith("under your control"):
            if condition.get("controller", "any") != "any":
                return None
            condition["controller"], tail = "you", tail[len("under your control"):].strip()
            continue
        phase, rest = consume(tail, PHASE_TAILS)
        if phase is not None:
            if any(k in trigger for k in phase):
                return None
            trigger.update(phase)
            tail = rest
            continue
        if events == ["ATTACKS"] and tail == "and isn't blocked":
            events, tail = ["ATTACKER_UNBLOCKED"], ""
            continue
        if "ATTACKS" in events:
            attack, rest = consume(tail, _ATTACK_TAILS)
            if attack is not None and not any(k in condition for k in attack):
                condition.update(attack)
                tail = rest
                continue
        return None
    return ObjectHead(events[0] if len(events) == 1 else events, condition, trigger)
