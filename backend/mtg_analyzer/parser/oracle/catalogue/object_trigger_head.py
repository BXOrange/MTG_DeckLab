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
    # RULE 708.8 / 509.5 / 701.21b / 701.22 / 702.140c / 701.37a — the object events
    # the legacy `segmenter._TRIGGER_VERBS` rows named (PAR-119 migration).
    "is turned face up": "TURNED_FACE_UP",
    "becomes blocked": "BECOMES_BLOCKED",
    "becomes tapped": "TAPPED",
    "becomes untapped": "UNTAPPED",
    "mutates": "MUTATES",
    "becomes monstrous": "BECAME_MONSTROUS",
    "specializes": "SPECIALIZED",
    # RULE 700.4's long spelling of "dies"; "your" scopes the owner (`_OWN_GRAVEYARD`).
    "is put into your graveyard from the battlefield": "DIES",
    # RULE 406.3 / 603.6c: a permanent exiled from the battlefield leaves it —
    # LEAVES_BATTLEFIELD with ``to_zone: exile`` (Psychomancer, Slagstone Refinery).
    "is put into exile from the battlefield": "LEAVES_BATTLEFIELD",
}
_OWN_GRAVEYARD = "is put into your graveyard from the battlefield"
_TO_EXILE = "is put into exile from the battlefield"
_VERB_ALT = (
    r"(?:enters(?: the battlefield)?|dies|attacks|blocks|leaves the battlefield|is turned face up|"
    r"becomes (?:blocked|tapped|untapped|monstrous)|mutates|specializes|"
    r"is put into your graveyard from the battlefield|is put into exile from the battlefield)"
)
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
    "each player": "any", "1 or more players": "any",
}
#: "<subject> deals [combat|noncombat] damage [to <recipient>]" — RULE 120.3. The
#: DAMAGE event names its *source* (``source_id``/``source_controller_id``), so
#: the subject phrase filters the damage source; the recipient is player-or-object.
_DAMAGE_HEAD = re.compile(
    r"^(?P<subject>.+?)\s+deals\s+(?P<kind>combat |noncombat )?damage"
    r"(?:\s+to\s+(?P<recipient>.+?))?(?P<tail>\s+during .+)?$"
)
_DAMAGE_RECIPIENT_HEAD = re.compile(
    r"^(?P<subject>.+?)\s+is dealt\s+(?P<kind>combat |noncombat )?damage$"
)
_BECOMES_TARGET_HEAD = re.compile(
    r"^(?P<subject>.+?)\s+becomes the target of an? "
    r"(?P<item_kind>spell or ability|spell|ability)"
    r"(?P<caster> an opponent controls| you control)?$"
)
_GROUP_ATTACK_HEAD = re.compile(
    r"^(?:1|one) or more (?P<phrase>.+?) attack(?: a player)?$"
)
_ATTACHED_SUBJECT = re.compile(r"^(?:enchanted|equipped)\s+(?:creature|permanent|land|artifact)$")
_ACTOR_HEAD = re.compile(
    r"^(?P<actor>you|an opponent|each opponent|a player|each player|1 or more players)\s+"
    r"(?P<verb>sacrifices?|discards?)\s+(?P<object>.+)$"
)
#: "<n> or more <plural object phrase>" after an actor verb (a batch, RULE 603.2c).
_ACTOR_QUANTITY = re.compile(r"^(?P<n>\d+) or more (?P<phrase>.+)$")
_SUBJECT_ARTICLE = re.compile(r"^(?P<article>another|an|a)\s+(?P<phrase>.+)$")
_SELF_OR_ANOTHER = re.compile(r"^~ or another\s+(?P<phrase>.+)$")

#: Attack-only tails: RULE 506.4's defending-player scope, as condition keys
#: `effect_binder._build_group_ok` reads off the ATTACKS event. Longest first.
_ATTACK_TAILS: list[tuple[str, dict[str, Any]]] = [
    ("you or a planeswalker you control", {"attacks_you_or_planeswalker": True}),
    ("you", {"attacks_you": True}),
    ("enchanted player", {"attacks_enchanted_player": True}),
    ("1 of your opponents", {"attacks_opponent": True}),
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


#: MEC-104: `_damage_recipient`'s marker for "…to one or more of your opponents".
_OPPONENTS_BATCH = "opponents_batch"


def _damage_recipient(text: str) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    """The words after "damage to" → ``(event filter keys, condition keys)``."""
    if text in ("a player", "each player", "a player or battle"):
        # DAMAGE does not yet distinguish battles from other non-player
        # permanents here; retain the legacy family's documented player-side
        # simplification for the printed "player or battle" union.
        return {"is_player": True}, {}
    if text in ("an opponent", "one of your opponents", "1 of your opponents"):
        return {"is_player": True}, {"recipient_is_opponent": True}
    if text in ("1 or more of your opponents", "1 or more opponents"):
        # MEC-104: one trigger for the whole simultaneous batch of hits on opponents — the
        # marker moves out of the condition into the trigger (`_OPPONENTS_BATCH`).
        return {"is_player": True}, {"recipient_is_opponent": True, _OPPONENTS_BATCH: True}
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
    if condition is None:
        return None
    event_filter: dict[str, Any] = {}
    kind = (m.group("kind") or "").strip()
    if kind:
        event_filter["combat"] = kind == "combat"
    if m.group("recipient"):
        recipient = _damage_recipient(m.group("recipient").strip())
        if recipient is None:
            return None
        event_filter.update(recipient[0])
    trigger: dict[str, Any] = {"filter": event_filter}
    if m.group("recipient") and recipient[1]:
        if condition["subject"] == "self_or_group":
            return None  # only the group half would read the recipient scope
        if condition["subject"] == "group":
            # The group predicate reads the recipient keys itself.
            condition.update(recipient[1])
            if condition.pop(_OPPONENTS_BATCH, False):
                trigger[_OPPONENTS_BATCH] = True
        else:
            # A self/attached subject has no group predicate: the recipient
            # scope becomes a trigger-level gate the binder applies to every
            # subject ("whenever enchanted creature deals damage to an
            # opponent" — Curiosity; "…to you").
            if recipient[1].get("recipient_is_opponent"):
                trigger["recipient_relation"] = "opponent"
            if recipient[1].get("recipient_is_you"):
                trigger["recipient_relation"] = "you"
            if recipient[1].get("recipient_filter"):
                trigger["recipient_filter"] = dict(recipient[1]["recipient_filter"])
    tail = (m.group("tail") or "").strip()
    if tail:
        phase, rest = consume(tail, PHASE_TAILS)
        if phase is None or rest:
            return None
        trigger.update(phase)
    return ObjectHead("DAMAGE", condition, trigger)


def _parse_damage_recipient_head(cond: str) -> Optional[ObjectHead]:
    """Recipient-side DAMAGE head (Enrage / Rite of Passage family)."""
    m = _DAMAGE_RECIPIENT_HEAD.match(cond)
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
    condition["recipient"] = True
    event_filter: dict[str, Any] = {}
    kind = (m.group("kind") or "").strip()
    if kind:
        event_filter["combat"] = kind == "combat"
    return ObjectHead("DAMAGE", condition, {"filter": event_filter})


def _parse_becomes_target_head(cond: str) -> Optional[ObjectHead]:
    """RULE 115 object target-event head (Ward-style ordinary triggers)."""
    m = _BECOMES_TARGET_HEAD.match(cond)
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
    trigger: dict[str, Any] = {}
    item_kind = m.group("item_kind")
    if item_kind != "spell or ability":
        trigger["filter"] = {"item_kind": item_kind}
    caster = (m.group("caster") or "").strip()
    if caster == "an opponent controls":
        trigger["caster_relation"] = "opponent"
    elif caster == "you control":
        trigger["caster_relation"] = "you"
    return ObjectHead("BECOMES_TARGET", condition, trigger)


def _parse_group_attack_head(cond: str) -> Optional[ObjectHead]:
    """RULE 508.3a's once-per-combat "one or more creatures attack" head."""
    m = _GROUP_ATTACK_HEAD.match(cond)
    if m is None:
        return None
    parsed = parse_object_phrase(m.group("phrase"), plural=True)
    if parsed is None or parsed[1] != "you":
        return None
    filt = dict(parsed[0])
    group_filter: dict[str, Any] = {}
    card_type = filt.pop("card_type", None)
    card_types = filt.pop("card_type_all", None)
    # PAR-148: "one or more **Goblins** you control attack" — a creature subtype (or several, "Goblins and/or
    # Orcs") names the creatures without saying "creatures"; any one attacker of those subtypes qualifies.
    subtype = filt.pop("subtype", None)
    subtype_any = filt.pop("subtype_any", None)
    subtypes = list(subtype_any) if subtype_any else ([subtype] if subtype else [])
    if subtypes:
        group_filter["subtypes_any"] = subtypes
    if card_type != "creature" and not (subtypes and card_type is None and not card_types):
        if not card_types or "creature" not in card_types or len(card_types) != 2:
            return None
        group_filter["type"] = next(kind for kind in card_types if kind != "creature")
    excluded = filt.pop("without_subtype", None)
    if excluded:
        group_filter["excluded_subtypes"] = (
            list(excluded) if isinstance(excluded, list) else [excluded]
        )
    if filt.pop("is_suspected", False):
        group_filter["is_suspected"] = True
    if filt:
        return None
    condition: dict[str, Any] = {"subject": "you"}
    if group_filter:
        condition["group_filter"] = group_filter
    return ObjectHead("PLAYER_ATTACKED", condition)


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
    quantity = _ACTOR_QUANTITY.match(text)
    if quantity is not None:
        # "you discard / sacrifice 1 or more [other] [artifact] cards" (RULE 603.2c) — a
        # batch of the same per-object event, counted by `EVENT_BATCH`
        # (`_parse_batch_quantity_head`). A cost's sacrifices are one batch too
        # (`GameEngine` scopes the whole payment).
        phrase = quantity.group("phrase")
        other = phrase.startswith("other ")
        parsed = parse_object_phrase(phrase.removeprefix("other "), plural=True)
        if parsed is None or parsed[1] is not None:
            return None
        condition = {"subject": "group", "controller": _ACTOR_SCOPE[m.group("actor")],
                     "other": other, **({"filter": parsed[0]} if parsed[0] else {})}
        trigger["batch"] = {"of": event, "min": int(quantity.group("n"))}
        return ObjectHead("EVENT_BATCH", condition, trigger)
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
_SELF_AND_ANOTHER_ATTACK = re.compile(
    r"^(?:~ and another (?P<subject>.+) attack|you attack with ~ and another (?P<with>.+))$"
)
_TOTAL_POWER = re.compile(r"^(?P<phrase>.+) with total power (?P<n>\d+) or greater$")
#: "from your hand/graveyard" (PAR-148, Thousand-Faced Shadow, Phyrexian Dragon Engine) names the owner too; only
#: the head's own "~" can read it, because the entry filter carries no zone owner for a group subject.
_ENTRY_ORIGIN = re.compile(r"^from (?:(?P<poss>a|your) )?(?P<zone>graveyard|exile|hand|library)(?:\s+|$)")


def _attackers_spec(
    phrase: str, low: Optional[int], high: Optional[int], *, other: bool, includes_source: bool
) -> Optional[ObjectHead]:
    other = other or phrase.startswith("other ")
    phrase = phrase.removeprefix("other ")
    total = _TOTAL_POWER.fullmatch(phrase)
    if total:
        phrase = total.group("phrase")
    parsed = parse_object_phrase(phrase, plural=True)
    if parsed is None:
        return None
    filt, controller = parsed
    if controller not in (None, "you"):
        return None  # only your own creatures can attack for you
    spec: dict[str, Any] = {"filter": filt}
    if total:
        spec["min_total_power"] = int(total.group("n"))
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
    m = _SELF_AND_ANOTHER_ATTACK.fullmatch(cond)
    if m is not None:
        return _attackers_spec(m.group("subject") or m.group("with"), 1, None,
                               other=True, includes_source=True)
    if cond == "you attack with your commander":
        return _attackers_spec("commander", 1, None, other=False, includes_source=False)
    if cond.startswith("you attack with "):
        phrase = cond.removeprefix("you attack with ")
        if _TOTAL_POWER.fullmatch(phrase):
            return _attackers_spec(phrase, 1, None, other=False, includes_source=False)
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


#: "<subject> exploits a creature" (RULE 702.110b) — the exploit relation: the subject is the exploiting
#: creature, the other side the sacrificed creature (the `EXPLOITS` event's ``related_ids``).
_EXPLOIT_HEAD = re.compile(r"^(?P<subject>.+?)\s+exploits\s+(?P<other>(?:a|an) .+)$")


def _parse_exploit_head(cond: str) -> Optional[ObjectHead]:
    m = _EXPLOIT_HEAD.match(cond)
    if m is None:
        return None
    subject = m.group("subject").strip()
    condition = {"subject": "self"} if subject == "~" else _subject(subject)
    if condition is None or condition["subject"] == "self_or_group":
        return None
    other = _SUBJECT_ARTICLE.match(m.group("other"))
    parsed = parse_object_phrase(other.group("phrase")) if other else None
    if parsed is None or parsed[1] is not None:  # whose creature it was is not modelled
        return None
    # Any creature is every creature a player can sacrifice to exploit, so it adds nothing to the head.
    related = {} if parsed[0] == {"card_type": "creature"} else {"related_filter": parsed[0]}
    return ObjectHead("EXPLOITS", condition, related)


def parse_object_trigger_head(cond: str) -> Optional[ObjectHead]:
    """``cond`` — the trigger condition with its "when"/"whenever" stripped."""
    cond = cond.strip().lower()
    player = parse_player_event_head(cond)
    if player is not None:
        return ObjectHead(*player)
    actor = (
        _parse_actor_head(cond) or _parse_damage_head(cond) or _parse_damage_recipient_head(cond)
        or _parse_becomes_target_head(cond) or _parse_group_attack_head(cond)
        or _parse_attack_batch_head(cond)
        or _parse_block_relation_head(cond) or _parse_exploit_head(cond) or _parse_batch_quantity_head(cond)
        or _parse_combat_damage_batch_head(cond) or _parse_graveyard_arrival_head(cond)
        or _parse_counters_put_head(cond)
    )
    if actor is not None:
        return actor
    m = _HEAD.match(cond)
    if m is None:
        return None
    subject_text = m.group("subject").strip()
    if subject_text == "~":
        condition: Optional[dict[str, Any]] = {"subject": "self"}  # the source itself
    else:
        condition = _subject(subject_text)
    if condition is None:
        return None
    events = [_event_name(m.group("v1"))]
    if m.group("v2"):
        events.append(_event_name(m.group("v2")))
    if _OWN_GRAVEYARD in (m.group("v1"), m.group("v2")):
        if m.group("v2") or condition["subject"] == "self":
            return None  # the self form is the legacy self row's; no compound needs it
        condition["owner"] = "you"
    trigger: dict[str, Any] = {}
    if _TO_EXILE in (m.group("v1"), m.group("v2")):
        if m.group("v2"):
            # "dies or is put into exile …": the zone key belongs to one event only,
            # so the segmenter splits the compound into one head per verb.
            return None
        trigger["to_zone"] = "exile"
    events = _consume_tails((m.group("tail") or "").strip(), events, condition, trigger)
    if events is None:
        return None
    return ObjectHead(events[0] if len(events) == 1 else events, condition, trigger)


def _consume_tails(
    tail: str, events: list[str], condition: dict[str, Any], trigger: dict[str, Any]
) -> Optional[list[str]]:
    """Read a head's trailing words into ``condition``/``trigger`` (in place).

    Returns the — possibly narrowed ("attacks alone", "attacks and isn't blocked") —
    event list, or ``None`` if any tail is unknown or repeated.
    """
    while tail:
        origin = _ENTRY_ORIGIN.match(tail) if events == ["ENTERS_BATTLEFIELD"] else None
        if origin is not None:
            if "from_zone" in trigger.get("filter", {}):
                return None
            if origin.group("poss") == "your" and condition.get("subject") != "self":
                return None
            trigger.setdefault("filter", {})["from_zone"] = origin.group("zone")
            tail = tail[origin.end():].strip()
            continue
        if tail.startswith("alone") and events == ["ATTACKS"]:
            events, tail = ["ATTACKS_ALONE"], tail[len("alone"):].strip()
            continue
        if tail.startswith("under your control"):
            if condition.get("controller", "any") != "any":
                return None
            condition["controller"], tail = "you", tail[len("under your control"):].strip()
            continue
        if tail.startswith("under an opponent's control") and events == ["ENTERS_BATTLEFIELD"]:
            if condition.get("controller", "any") != "any":
                return None
            condition["controller"] = "not_you"
            tail = tail[len("under an opponent's control"):].strip()
            continue
        if tail.startswith("without dying") and events == ["LEAVES_BATTLEFIELD"]:
            if "to_zone_not" in trigger:
                return None
            trigger["to_zone_not"], tail = "graveyard", tail[len("without dying"):].strip()
            continue
        if tail.startswith("without being played") and events == ["ENTERS_BATTLEFIELD"]:
            if "not_played" in trigger:
                return None
            trigger["not_played"], tail = True, tail[len("without being played"):].strip()
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
    return events


#: RULE 603.2c batch quantity: "whenever `<n>` or more [other] `<objects>` enter / die /
#: leave the battlefield" — one trigger per simultaneous batch (`EventType.EVENT_BATCH`,
#: fired by `GameState.simultaneous`) when at least ``n`` of its members match the
#: ordinary per-object condition. Number words are digits after `normalize`.
_BATCH_QUANTITY = re.compile(
    r"^(?P<n>\d+) or more (?P<other>other )?(?P<phrase>.+?)\s+"
    r"(?P<verb>enter(?: the battlefield)?|die|leave the battlefield)(?P<tail>\s.*)?$"
)
_PLURAL_VERBS: dict[str, str] = {
    "enter": "ENTERS_BATTLEFIELD", "enter the battlefield": "ENTERS_BATTLEFIELD",
    "die": "DIES", "leave the battlefield": "LEAVES_BATTLEFIELD",
}


def _parse_batch_quantity_head(cond: str) -> Optional[ObjectHead]:
    m = _BATCH_QUANTITY.match(cond)
    if m is None:
        return None
    parsed = parse_object_phrase(m.group("phrase"), plural=True)
    if parsed is None:
        return None
    filt, controller = parsed
    condition: dict[str, Any] = {
        "subject": "group", "controller": controller or "any", "other": bool(m.group("other")),
    }
    if filt:
        condition["filter"] = filt
    of = _PLURAL_VERBS[m.group("verb")]
    trigger: dict[str, Any] = {}
    events = _consume_tails((m.group("tail") or "").strip(), [of], condition, trigger)
    if events != [of]:
        return None
    trigger["batch"] = {"of": of, "min": int(m.group("n"))}
    return ObjectHead("EVENT_BATCH", condition, trigger)


#: RULE 510.2 / 603.2c: "whenever `<n>` or more `<creatures>` deal combat damage to
#: `<a player>`" — combat damage is dealt simultaneously, so the step's hits on one
#: player are one batch: `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`, fired
#: once per (contributors' controller, damaged player) by `_apply_combat_damage`.
#: The subject is the ordinary per-creature DAMAGE condition, checked against each
#: contributor (`binding.core._contributor_condition`) — a quantity, not a new
#: vocabulary. Only player recipients: the aggregate never names a permanent.
_COMBAT_DAMAGE_BATCH = re.compile(
    r"^(?P<n>\d+) or more (?P<phrase>.+?) deal combat damage to (?P<recipient>.+)$"
)
_PLURAL_PLAYER_RECIPIENTS = {"1 or more players": "a player"}


def _parse_combat_damage_batch_head(cond: str) -> Optional[ObjectHead]:
    m = _COMBAT_DAMAGE_BATCH.match(cond)
    if m is None:
        return None
    parsed = parse_object_phrase(m.group("phrase"), plural=True)
    if parsed is None:
        return None
    filt, controller = parsed
    recipient_text = m.group("recipient").strip()
    if "battle" in recipient_text:
        return None  # the batch event counts only damage dealt to players
    recipient = _damage_recipient(_PLURAL_PLAYER_RECIPIENTS.get(recipient_text, recipient_text))
    if recipient is None or recipient[0] != {"is_player": True}:
        return None
    condition: dict[str, Any] = {"subject": "group", "controller": controller or "any", "other": False}
    if filt:
        condition["filter"] = filt
    condition.update(recipient[1])
    trigger: dict[str, Any] = {"contributors": {"min": int(m.group("n"))}}
    if condition.pop(_OPPONENTS_BATCH, False):
        trigger[_OPPONENTS_BATCH] = True
    return ObjectHead("CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER", condition, trigger)


#: RULE 603.6c: "`<subject>` is put into `<whose>` graveyard [from `<origin>`]" and its
#: batch form "`<n>` or more `<cards>` are put into …" — `EventType.PUT_INTO_GRAVEYARD`,
#: fired per arrival from any zone. "From the battlefield" stays with the dies/leaves
#: rows: a leaves-the-battlefield ability looks back in time (RULE 603.10a), this doesn't.
_GRAVEYARD_ARRIVAL = re.compile(
    r"^(?:(?P<n>\d+) or more (?P<plural>.+?) are|(?P<single>.+?) is) put into "
    r"(?P<whose>a|your|an opponent's) graveyard"
    r"(?: from (?P<origin>anywhere other than the battlefield|anywhere|a library|your library|"
    r"your hand))?(?P<tail>\s.*)?$"
)
_GRAVEYARD_OWNER = {"a": "any", "your": "you", "an opponent's": "not_you"}


def _parse_graveyard_arrival_head(cond: str) -> Optional[ObjectHead]:
    m = _GRAVEYARD_ARRIVAL.match(cond)
    if m is None:
        return None
    event = "PUT_INTO_GRAVEYARD"
    owner = _GRAVEYARD_OWNER[m.group("whose")]
    condition: Optional[dict[str, Any]]
    if m.group("plural") is not None:
        parsed = parse_object_phrase(m.group("plural"), plural=True)
        if parsed is None or parsed[1] is not None:
            return None
        condition = {"subject": "group", "controller": owner, "other": False,
                     **({"filter": parsed[0]} if parsed[0] else {})}
    elif m.group("single") in ("~", "this card"):
        if owner == "not_you":
            return None  # a card only ever goes to its owner's graveyard
        condition = {"subject": "self"}
    else:
        condition = _subject(m.group("single"))
        if condition is None or condition["subject"] != "group" or condition["controller"] != "any":
            return None  # the graveyard names whose it is; a second scope is not modelled
        condition["controller"] = owner
    subject_text = m.group("plural") or m.group("single") or ""
    names_card = bool(re.search(r"\bcards?\b", subject_text)) or condition["subject"] == "self"
    if names_card and condition["subject"] != "self":
        condition["nontoken"] = True  # a token is never a card (RULE 111.1)
    trigger: dict[str, Any] = {}
    # "a permanent / a creature is put into a graveyard" names an object that only exists
    # on the battlefield (RULE 110.1), so the unstated origin is the battlefield.
    origin = m.group("origin") or ("anywhere" if names_card else "the battlefield")
    if origin == "anywhere other than the battlefield":
        trigger["from_zone_not"] = "battlefield"
    elif origin != "anywhere":
        trigger["filter"] = {"from_zone": origin.split()[-1]}
    events = _consume_tails((m.group("tail") or "").strip(), [event], condition, trigger)
    if events != [event]:
        return None
    if m.group("n") is not None:
        trigger["batch"] = {"of": event, "min": int(m.group("n"))}
        return ObjectHead("EVENT_BATCH", condition, trigger)
    return ObjectHead(event, condition, trigger)


#: PAR-138, RULE 122.5 / 603.2: "`<n>` or more `<kind>` counters are put on `<subject>`" and its single form
#: "a `<kind>` counter is put on `<subject>`" — `EventType.COUNTER`, which `RulesEngine.add_counters` fires
#: *after* the counters landed (the same event a replacement reads before). One placement is one event, so
#: "1 or more" needs no batching of its own. The subject is the object counters went on (the event's
#: ``target_id``): ``~``, or one `characteristic_phrase` noun phrase with its controller scope. "For the first
#: time each turn" is a once-per-turn limit (counters landing on the same subject twice in a turn trigger once).
_COUNTER_KIND = r"(?:[+\-]\d+/[+\-]\d+|[a-z]+)"
_COUNTERS_PUT = re.compile(
    rf"^(?:(?P<n>1|one) or more (?P<kinds>{_COUNTER_KIND}|) ?counters are|"
    rf"an? (?P<kind>{_COUNTER_KIND}) counter is) put on (?P<subject>.+?)"
    r"(?P<first> for the first time each turn)?$"
)


def _parse_counters_put_head(cond: str) -> Optional[ObjectHead]:
    m = _COUNTERS_PUT.match(cond)
    if m is None:
        return None
    kind = (m.group("kinds") or m.group("kind") or "").strip()
    subject = m.group("subject").strip()
    if subject == "~":
        condition: Optional[dict[str, Any]] = {"subject": "self"}
    else:
        plural = _ACTOR_QUANTITY_PLURAL.match(subject)
        if plural is not None:
            parsed = parse_object_phrase(plural.group("phrase"), plural=True)
            if parsed is None:
                return None
            condition = {"subject": "group", "controller": parsed[1] or "any", "other": False,
                         **({"filter": parsed[0]} if parsed[0] else {})}
        else:
            condition = _subject(subject)
    if condition is None or condition["subject"] == "self_or_group":
        return None
    filt: dict[str, Any] = {"kind": kind} if kind else {}
    trigger: dict[str, Any] = {**({"filter": filt} if filt else {})}
    if m.group("first"):
        trigger["limit"] = True
    return ObjectHead("COUNTER", condition, trigger)


#: "1 or more `<plural object phrase>`" as a counters' recipient ("1 or more humans you control").
_ACTOR_QUANTITY_PLURAL = re.compile(r"^(?:1|one) or more (?P<phrase>.+)$")


#: Condition keys other than the subject scope that pass through `legacy_condition`
#: unchanged — the RULE 506.4 defender scopes the attack tails add.
_LEGACY_PASSTHROUGH = frozenset({
    "attacks_you", "attacks_you_or_planeswalker", "attacks_enchanted_player", "attacks_opponent",
    "owner",
})


def legacy_condition(condition: dict[str, Any], phrase: str = "") -> Optional[dict[str, Any]]:
    """A composed group condition in the flat keys the binder has always read, or ``None``.

    PAR-119's migration keeps every `AbilitySpec` the retired per-adjective rows emitted
    byte-identical: those keys (``type`` / ``subtypes`` / ``color`` / …) read the event's
    last-known snapshot where the ``filter`` form reads the live object, so rewriting
    them would change behaviour, not only spelling. Only a shape those rows could print
    translates; anything richer keeps its ``filter`` (``None`` here). ``phrase`` is the
    subject noun phrase — "permanent" has no filter key of its own.
    """
    if condition.get("subject") not in ("group", "self_or_group"):
        return None
    base = {k: condition[k] for k in ("subject", "controller", "other") if k in condition}
    extra = set(condition) - {"subject", "controller", "other", "filter"}
    if extra - _LEGACY_PASSTHROUGH:
        return None
    base.update({k: condition[k] for k in extra})
    f = dict(condition.get("filter") or {})
    nontoken = bool(f.pop("nontoken", False))
    if "subtype" in f or "subtype_any" in f:
        subtypes = [f.pop("subtype")] if "subtype" in f else list(f.pop("subtype_any"))
        if f or extra - {"owner"}:
            return None
        return {**base, "subtypes": subtypes, "nontoken": nontoken}
    if nontoken:
        return None
    if "card_type" in f:
        base["type"] = f.pop("card_type")
    elif "card_type_any" in f:
        base["type"] = list(f.pop("card_type_any"))
    elif re.search(r"\bpermanents?\b", phrase):
        base["type"] = "permanent"
    else:
        return None
    if f.pop("without_card_type", None) == "land":
        base["nonland"] = True
    if "without_subtype" in f:
        base["excluded_subtypes"] = [f.pop("without_subtype")]
    if f.pop("goaded", False):
        base.update({"goaded": True, "in_combat": False})
    for key in ("color", "min_power", "max_power", "has_counter", "has_counter_kind"):
        if key in f:
            base[key] = f.pop(key)
    return None if f else base


def legacy_group_condition(cond: str) -> Optional[tuple[str, dict[str, Any]]]:
    """``(event, condition)`` for a plain one-verb group head in the flat legacy keys.

    What the retired `segmenter` rows `_GROUP_SUBJECT_RE` / `_GROUP_SUBTYPE_SUBJECT_RE` /
    `_SELF_OR_GROUP_SUBJECT_RE` / `_SELF_OR_GROUP_SUBTYPE_RE` returned, now derived from
    the composed head (`legacy_condition`). A head with a tail, a batch or two verbs is
    not one of theirs and stays with the composed path.
    """
    cond = cond.strip().lower()
    head = parse_object_trigger_head(cond)
    if head is None or head.trigger or not isinstance(head.event, str):
        return None
    m = _HEAD.match(cond)
    if m is None:
        return None
    translated = legacy_condition(head.condition, m.group("subject"))
    return None if translated is None else (head.event, translated)
