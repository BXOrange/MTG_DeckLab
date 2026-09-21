"""Trigger doublers (RULE 603.2d) → a `trigger_doubler` spec (PAR-122).

Two printed shapes, both ending "…, that ability triggers an additional time"::

    if a triggered ability of <subject> triggers, …      # whose ability doubles
    if <cause> causes a triggered ability of a permanent you control to trigger, …

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

_DOUBLER = re.compile(
    r"^if (?P<clause>.+?),\s+(?:that ability|it) triggers an additional time$"
)
_SUBJECT_CLAUSE = re.compile(
    r"^(?:a triggered ability|an ability) of (?P<subject>.+?) triggers$"
)
_CAUSE_CLAUSE = re.compile(
    r"^(?P<cause>.+?) causes? a triggered ability of a permanent you control to trigger$"
)
_SUBJECT_ARTICLE = re.compile(r"^(?P<article>another|an|a)\s+(?P<phrase>.+)$")

#: Gerund → the finite verb of the same trigger head; "you" takes the base form
#: ("you gaining life" → "you gain life"), everything else the third person.
_GERUNDS: list[tuple[str, str, str]] = [
    ("entering or leaving the battlefield", "enters or leaves the battlefield", "enter or leave the battlefield"),
    ("entering the battlefield", "enters the battlefield", "enter the battlefield"),
    ("leaving the battlefield", "leaves the battlefield", "leave the battlefield"),
    ("dealing combat damage to a player", "deals combat damage to a player", "deal combat damage to a player"),
    ("dealing damage", "deals damage", "deal damage"),
    ("gaining life", "gains life", "gain life"),
    ("entering", "enters", "enter"),
    ("dying", "dies", "die"),
    ("attacking", "attacks", "attack"),
    ("blocking", "blocks", "block"),
]

#: Phrases that name the permanent an Aura/Equipment is attached to.
_ATTACHED = frozenset({"equipped creature", "enchanted creature", "equipped permanent", "enchanted permanent"})


def _subject(text: str) -> Optional[dict[str, Any]]:
    """Whose triggered ability doubles → ``{"filter", "other", "attached"}`` keys."""
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


def _cause(text: str, condition_dict: Callable[[str], Optional[dict[str, Any]]]) -> Optional[dict[str, Any]]:
    for gerund, third_person, base in _GERUNDS:
        if text.endswith(" " + gerund):
            actor = text[: -len(gerund)].strip()
            verb = base if actor == "you" else third_person
            return condition_dict(f"{actor} {verb}")
    return None


def parse_trigger_doubler(
    text: str, condition_dict: Callable[[str], Optional[dict[str, Any]]]
) -> Optional[EffectSpec]:
    """``text`` — one normalised static line — → a `trigger_doubler` spec, or ``None``.

    ``condition_dict`` turns a finite trigger condition phrase into an
    `AbilitySpec.trigger`-shaped dict (the segmenter's own trigger grammar).
    """
    m = _DOUBLER.match(text.strip().lower().rstrip("."))
    if m is None:
        return None
    clause = m.group("clause").strip()
    params: dict[str, Any] = {}
    sm = _SUBJECT_CLAUSE.match(clause)
    if sm is not None:
        subject = _subject(sm.group("subject").strip())
        if subject is None:
            return None
        params["subject"] = subject
    else:
        cm = _CAUSE_CLAUSE.match(clause)
        if cm is None:
            return None
        cause = _cause(cm.group("cause").strip(), condition_dict)
        if cause is None:
            return None
        params["cause"] = cause
    return EffectSpec("trigger_doubler", params)
