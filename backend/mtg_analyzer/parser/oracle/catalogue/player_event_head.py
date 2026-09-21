"""Player-event trigger heads → one composed grammar (PAR-119).

"Whenever `<a player | an opponent | you>` `<verb phrase>` `<tail>`": who acts is a scope,
what they do is a row of one verb table, and the tails ("during your turn", "for the first
time each turn", "in a turn") are the shared `trigger_context` ones. A new event or phrase is
a table entry, not a regex per actor × verb. Only what the older per-verb rows decline reaches
here. Pure — no `game/` imports.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .trigger_context import PHASE_TAILS, consume

#: Actor words → the condition that scopes the acting player. "You" keeps the long-standing
#: ``{"subject": "you"}``; the others are ``{"subject": "player", "scope": …}``
#: (`effect_binder._subject_condition`).
_ACTORS: dict[str, dict[str, Any]] = {
    "you": {"subject": "you"},
    "an opponent": {"subject": "player", "scope": "not_you"},
    "each opponent": {"subject": "player", "scope": "not_you"},
    "a player": {"subject": "player", "scope": "any"},
}

#: Verb phrase (after the actor, either conjugation) → `EventType`.
_VERBS: dict[str, str] = {
    "gain life": "LIFE_GAINED", "gains life": "LIFE_GAINED",
    "lose life": "LIFE_LOST", "loses life": "LIFE_LOST",
    "cycle a card": "CYCLED", "cycles a card": "CYCLED",
    "play a land": "LAND_PLAYED", "plays a land": "LAND_PLAYED",
    "draw a card": "DRAW", "draws a card": "DRAW",
}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
_NTH_DRAW = re.compile(
    rf"^(?:draw|draws) (?:your|their) (?P<n>{'|'.join(_ORDINALS)}) card (?:each turn|in a turn)$"
)
_ONCE = "for the first time each turn"

_HEAD = re.compile(r"^(?P<actor>you|an opponent|each opponent|a player)\s+(?P<rest>.+)$")


def parse_player_event_head(cond: str) -> Optional[tuple[str, dict[str, Any], dict[str, Any]]]:
    """``(event, condition, trigger keys)`` for a player-event head, or ``None``."""
    m = _HEAD.match(cond.strip().lower())
    if m is None:
        return None
    condition = dict(_ACTORS[m.group("actor")])
    rest = m.group("rest").strip()
    trigger: dict[str, Any] = {}
    if rest.endswith(" " + _ONCE):
        trigger["limit"] = True
        rest = rest[: -len(_ONCE) - 1].strip()
    nth = _NTH_DRAW.match(rest)
    if nth is not None:
        trigger["is_nth_draw_this_turn"] = _ORDINALS[nth.group("n")]
        return "DRAW", condition, trigger
    for phrase, event in _VERBS.items():
        if rest == phrase or rest.startswith(phrase + " "):
            tail = rest[len(phrase):].strip()
            if tail:
                phase, left = consume(tail, PHASE_TAILS)
                if phase is None or left:
                    return None
                trigger.update(phase)
            return event, condition, trigger
    return None
