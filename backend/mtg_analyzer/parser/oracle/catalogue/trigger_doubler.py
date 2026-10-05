"""Trigger doublers (RULE 603.2d) → a `trigger_doubler` spec (PAR-122).

Two printed shapes, both ending "…, that ability triggers an additional time"::

    if a triggered ability of <subject> triggers, …      # whose ability doubles
    if <cause> causes a triggered ability of a permanent you control to trigger, …

A third shape adds a cost ("…, tap any number of Fish you control. That ability triggers
an additional time for each Fish tapped this way", The Fish Brewer) as ``tap_cost``.

The *subject* is a `characteristic_phrase` noun phrase (with "another" and "but
don't own"), read as a filter on the doubled permanent. The *cause* is a trigger
head in its gerund spelling — "a creature you control attacking" is the head
"a creature you control attacks" — so it is turned back into the finite head and
parsed by the same grammar every triggered ability uses; the engine then evaluates
that trigger-shaped dict with the binder's own predicate. Anything unrecognised
returns ``None``. Pure — no `game/` imports.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from ..spec import EffectSpec
from .characteristic_phrase import parse_object_phrase
from .count_phrase import parse_count_condition

_DOUBLER = re.compile(
    r"^if (?P<clause>.+?),\s+(?:that ability|it) triggers an additional time$"
)
#: "…, tap any number of `<permanents>` you control. That ability triggers an additional time
#: for each `<noun>` tapped this way." — the doubling is paid for, one extra copy per tapped
#: permanent, chosen when the trigger is put on the stack (`RulesEngine._place_triggers`).
_TAP_DOUBLER = re.compile(
    r"^if (?P<clause>.+?),\s+tap any number of (?P<tap>.+?) you control\.\s+"
    r"that ability triggers an additional time for each (?P<noun>.+?) tapped this way$"
)
_SUBJECT_CLAUSE = re.compile(
    r"^(?:a triggered ability|an ability) of (?P<subject>.+?) triggers(?: while (?P<gate>.+))?$"
)
_CAUSE_CLAUSE = re.compile(
    r"^(?P<cause>.+?) causes? a triggered ability of (?P<subject>.+?) to trigger$"
)
#: The unrestricted subject a cause-only doubler names.
_ANY_OWN_PERMANENT = "a permanent you control"
_SUBJECT_ARTICLE = re.compile(r"^(?P<article>another|an|a)\s+(?P<phrase>.+)$")

#: Gerund → the finite verb of the same trigger head; "you" takes the base form
#: ("you gaining life" → "you gain life"), everything else the third person.
_GERUNDS: list[tuple[str, str, str]] = [
    ("entering or leaving the battlefield", "enters or leaves the battlefield", "enter or leave the battlefield"),
    ("entering the battlefield", "enters the battlefield", "enter the battlefield"),
    ("leaving the battlefield", "leaves the battlefield", "leave the battlefield"),
    ("dealing combat damage to a player", "deals combat damage to a player", "deal combat damage to a player"),
    ("dealing damage", "deals damage", "deal damage"),
    # PAR-122: the passive gerunds — "a creature you control becoming the target of
    # a spell or ability" / "being dealt damage" (Valiant Emberkin, Wayta).
    ("becoming the target of a spell or ability", "becomes the target of a spell or ability",
     "become the target of a spell or ability"),
    ("being dealt damage", "is dealt damage", "are dealt damage"),
    ("gaining life", "gains life", "gain life"),
    # PAR-122: a player-event cause — "a player drawing a card" (Krang, the All-Powerful).
    ("drawing a card", "draws a card", "draw a card"),
    ("entering", "enters", "enter"),
    ("dying", "dies", "die"),
    ("attacking", "attacks", "attack"),
    ("blocking", "blocks", "block"),
]

#: Phrases that name the permanent an Aura/Equipment is attached to.
_ATTACHED = frozenset({"equipped creature", "enchanted creature", "equipped permanent", "enchanted permanent"})


#: "~ or an Equipment attached to it" (Cloud) — the doubler itself, or a permanent attached to it.
_ATTACHED_TO_IT = re.compile(r"^(?:an?|another) (?P<phrase>.+?) attached to it$")
#: "an emblem you own" (The Masamune) — an emblem's triggers are doubled like a permanent's.
_EMBLEM_YOU_OWN = re.compile(r"^an? emblem you own$")
#: "a colorless spell you control" (Echoes of Eternity) — a spell's own triggers (cascade,
#: storm), which exist while it is on the stack rather than on the battlefield.
_SPELL_YOU_CONTROL = re.compile(r"^(?P<article>an?|another) (?:(?P<phrase>.+?) )?spell you control$")


def _alternative(text: str) -> Optional[dict[str, Any]]:
    """One side of a compound subject: the doubler itself ("~"), "a `<noun>` attached to it",
    "an emblem you own", "a `<noun>` spell you control", or an ordinary permanent phrase."""
    if text == "~":
        return {"self": True}
    if _EMBLEM_YOU_OWN.match(text):
        return {"emblem": True}
    m = _ATTACHED_TO_IT.match(text)
    if m is not None:
        parsed = parse_object_phrase(m.group("phrase"))
        if parsed is None or not parsed[0]:
            return None
        return {"filter": dict(parsed[0]), "attached_to_doubler": True}
    m = _SPELL_YOU_CONTROL.match(text)
    if m is not None:
        phrase = m.group("phrase")
        filt: dict[str, Any] = {}
        if phrase:
            # the spell's characteristics read like a permanent's ("colorless", "creature")
            parsed = parse_object_phrase(f"{phrase} permanent you control")
            if parsed is None or parsed[1] != "you" or not parsed[0]:
                return None
            filt = dict(parsed[0])
        side: dict[str, Any] = {"spell": True}
        if filt:
            side["filter"] = filt
        if m.group("article") == "another":
            side["other"] = True
        return side
    simple = _simple_subject(text)
    if simple is None or simple.get("attached") or "any_of" in simple:
        return None
    return simple


def _subject(text: str) -> Optional[dict[str, Any]]:
    """Whose triggered ability doubles → ``{"filter", "other", "attached"}`` keys, or
    ``{"any_of": [...]}`` for a compound "`<A>` or `<B>`" subject."""
    whole = _simple_subject(text)
    if whole is not None:
        return whole
    left, sep, right = text.partition(" or ")
    if not sep:
        return None
    first, second = _alternative(left.strip()), _alternative(right.strip())
    if first is None or second is None:
        return None
    return {"any_of": [first, second]}


def _simple_subject(text: str) -> Optional[dict[str, Any]]:
    if text in _ATTACHED:
        return {"attached": True}
    not_owned = text.endswith(" but don't own")
    if not_owned:
        text = text[: -len(" but don't own")].strip()
    m = _SUBJECT_ARTICLE.match(text)
    if m is None:
        return None
    parsed = parse_object_phrase(m.group("phrase"))
    if parsed is None or parsed[1] != "you":
        return None  # a doubler only ever names permanents its own controller controls
    filt = dict(parsed[0])
    if not_owned:
        filt["not_owned_by_you"] = True
    subject: dict[str, Any] = {}
    if filt:
        subject["filter"] = filt
    if m.group("article") == "another":
        subject["other"] = True
    return subject


#: "turning a `<noun phrase>` face up" (Panoptic Projektor) — the actor is the turner, not
#: the subject, so it is the passive finite head "a `<noun phrase>` is turned face up".
_TURNING_FACE_UP = re.compile(r"^turning (?P<what>.+) face up$")


def _cause(text: str, condition_dict: Callable[[str], Optional[dict[str, Any]]]) -> Optional[dict[str, Any]]:
    turning = _TURNING_FACE_UP.match(text)
    if turning is not None:
        return condition_dict(f"{turning.group('what')} is turned face up")
    for gerund, third_person, base in _GERUNDS:
        if text.endswith(" " + gerund):
            actor = text[: -len(gerund)].strip()
            verb = base if actor == "you" else third_person
            return condition_dict(f"{actor} {verb}")
    return None


def _doubler_clause(
    clause: str, condition_dict: Callable[[str], Optional[dict[str, Any]]]
) -> Optional[dict[str, Any]]:
    """The subject-or-cause half of a doubler → its params, or ``None``."""
    params: dict[str, Any] = {}
    sm = _SUBJECT_CLAUSE.match(clause)
    if sm is not None:
        subject = _subject(sm.group("subject").strip())
        if subject is None:
            return None
        params["subject"] = subject
        if sm.group("gate"):
            # "… triggers while you control six or more Shrines" (Sanctum of All): a gate on
            # the whole doubler, the same `active_if` an "as long as …" wrapper sets.
            gate = parse_count_condition(sm.group("gate"))
            if gate is None:
                return None
            params["active_if"] = gate
        return params
    cm = _CAUSE_CLAUSE.match(clause)
    if cm is None:
        return None
    cause = _cause(cm.group("cause").strip(), condition_dict)
    if cause is None:
        return None
    params["cause"] = cause
    subject_text = cm.group("subject").strip()
    if subject_text != _ANY_OWN_PERMANENT:
        # "a creature dying causes a triggered ability of ~ or an emblem you own to trigger"
        # (The Masamune): the cause and the doubled subject are both scoped.
        subject = _subject(subject_text)
        if subject is None:
            return None
        params["subject"] = subject
    return params


def parse_trigger_doubler(
    text: str, condition_dict: Callable[[str], Optional[dict[str, Any]]]
) -> Optional[EffectSpec]:
    """``text`` — one normalised static line — → a `trigger_doubler` spec, or ``None``.

    ``condition_dict`` turns a finite trigger condition phrase into an
    `AbilitySpec.trigger`-shaped dict (the segmenter's own trigger grammar).
    """
    line = text.strip().lower().rstrip(".")
    tap_filter: Optional[dict[str, Any]] = None
    m = _DOUBLER.match(line)
    if m is None:
        m = _TAP_DOUBLER.match(line)
        if m is None:
            return None
        parsed = parse_object_phrase(f"{m.group('tap').strip()} you control")
        if parsed is None or parsed[1] != "you" or not parsed[0]:
            return None
        tap_filter = dict(parsed[0])
    params = _doubler_clause(m.group("clause").strip(), condition_dict)
    if params is None:
        return None
    if tap_filter is not None:
        params["tap_cost"] = {"filter": tap_filter}
    return EffectSpec("trigger_doubler", params)
