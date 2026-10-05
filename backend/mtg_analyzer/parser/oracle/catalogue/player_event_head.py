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

from .characteristic_phrase import parse_object_phrase
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
    "scry": "SCRY", "surveil": "SURVEIL",
    "gain life": "LIFE_GAINED", "gains life": "LIFE_GAINED",
    "lose life": "LIFE_LOST", "loses life": "LIFE_LOST",
    "cycle a card": "CYCLED", "cycles a card": "CYCLED",
    "cycle another card": "CYCLED", "cycles another card": "CYCLED",
    "play a land": "LAND_PLAYED", "plays a land": "LAND_PLAYED",
    "draw a card": "DRAW", "draws a card": "DRAW",
    "proliferate": "PROLIFERATED", "proliferates": "PROLIFERATED",
    "attack": "PLAYER_ATTACKED", "attack a player": "PLAYER_ATTACKED",
    "clash": "CLASHED", "win a clash": "WON_CLASH", "clash and win": "WON_CLASH",
    "collect evidence": "COLLECTED_EVIDENCE", "forage": "FORAGED",
    "roll a die": "DICE_ROLLED", "roll 1 or more dice": "DICE_ROLLED",
    "discard a card": "DISCARD_CARD", "discard another card": "DISCARD_CARD",
    # RULE 702.174c (MEC-106): "whenever you give a gift" — `GIFT_GIVEN`, fired when a promised gift is given.
    "give a gift": "GIFT_GIVEN", "gives a gift": "GIFT_GIVEN",
}
_COMPOUND_VERBS: dict[str, list[str]] = {
    "scry or surveil": ["SCRY", "SURVEIL"],
    "surveil or scry": ["SURVEIL", "SCRY"],
    "cycle or discard a card": ["CYCLED", "DISCARD_CARD"],
    "cycle or discard another card": ["CYCLED", "DISCARD_CARD"],
    "discard or cycle a card": ["DISCARD_CARD", "CYCLED"],
    "discard or cycle another card": ["DISCARD_CARD", "CYCLED"],
}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
_NTH_DRAW = re.compile(
    rf"^(?:draw|draws) (?:your|their) (?P<n>{'|'.join(_ORDINALS)}) card (?:each turn|in a turn)$"
)
_ONCE = "for the first time each turn"
_DRAW_EXCEPT = re.compile(
    r"^(?:draw|draws) a card except the first (?P<n>\d+|one) "
    r"(?:they|you) draw in each of (?:their|your) draw steps$"
)
_DAMAGE_DEALT_TO_YOU = re.compile(r"^(?P<kind>combat |noncombat )?damage is dealt to you$")
_DAMAGE = re.compile(r"^(?:are|is) dealt (?P<kind>combat |noncombat )?damage$")
#: RULE 700.14 (MEC-107): "you expend 4" — the running spend crossed N. The engine fires one
#: `EXPEND` per N crossed, so the threshold is an exact-match ``filter`` on ``amount``.
_EXPEND = re.compile(r"^expends? (?P<n>\d+)$")
_MANA_TAP = re.compile(r"^taps? (?:an?|another) (?P<object>.+) for mana$")

_PLAYER_ATTACKS = re.compile(r"^attacks?(?: with (?P<n>\d+) or more creatures)?$")
#: "attacks you", "attacks enchanted player [with N or more creatures]", "attacks 1 of your opponents",
#: "attacks 1 or more of your opponents" — a player attack with the *defender* named (RULE 508.1).
_PLAYER_ATTACKS_DEFENDER = re.compile(
    r"^attacks? (?:(?P<you>you)|(?P<enchanted>enchanted player)|(?P<opponents>(?P<one>1|1 or more) of your opponents))"
    r"(?: with (?P<n>\d+) or more creatures)?$"
)
#: The trigger keys `binding/core.py` reads off a `PLAYER_ATTACKED` / `ATTACKERS_DECLARED` event for each defender.
_DEFENDER_KEYS = {
    "you": {"defender_is_you": True},
    "enchanted": {"defender_is_enchanted_player": True},
    "opponents": {"defender_is_opponent": True},
}

_HEAD = re.compile(r"^(?P<actor>you|an opponent|each opponent|a player)\s+(?P<rest>.+)$")


def parse_player_event_head(cond: str) -> Optional[tuple[str, dict[str, Any], dict[str, Any]]]:
    """``(event, condition, trigger keys)`` for a player-event head, or ``None``."""
    cond = cond.strip().lower()
    if cond == "the ring tempts you":
        return "RING_TEMPTED", {"subject": "you"}, {}
    if cond.startswith("you're "):
        cond = "you are " + cond[len("you're "):]
    # "whenever combat damage is dealt to you" (Risona) — the passive spelling of "you're dealt combat damage".
    passive = _DAMAGE_DEALT_TO_YOU.fullmatch(cond)
    if passive is not None:
        cond = f"you are dealt {passive.group('kind') or ''}damage"
    m = _HEAD.match(cond)
    if m is None:
        return None
    condition = dict(_ACTORS[m.group("actor")])
    rest = m.group("rest").strip()
    trigger: dict[str, Any] = {}
    if rest.endswith(" " + _ONCE):
        trigger["limit"] = True
        rest = rest[: -len(_ONCE) - 1].strip()
    if m.group("actor") == "you" and rest in _COMPOUND_VERBS:
        return _COMPOUND_VERBS[rest], condition, trigger
    if m.group("actor") == "you" and re.fullmatch(r"behold(?: an?\s+\w+)?", rest):
        return "BEHELD", condition, trigger
    for phrase, keys in PHASE_TAILS:
        if rest.endswith(" " + phrase):
            trigger.update(keys)
            rest = rest[: -len(phrase) - 1].strip()
            break
    excluded = _DRAW_EXCEPT.fullmatch(rest)
    if excluded:
        n = excluded.group("n")
        trigger["skip_first_draws_in_draw_step"] = 1 if n == "one" else int(n)
        return "DRAW", condition, trigger
    damage = _DAMAGE.fullmatch(rest)
    if damage:
        condition["recipient"] = True
        trigger["filter"] = {"is_player": True}
        if damage.group("kind"):
            trigger["filter"]["combat"] = damage.group("kind").strip() == "combat"
        return "DAMAGE", condition, trigger
    attacks = _PLAYER_ATTACKS.fullmatch(rest)
    if attacks and m.group("actor") != "you":
        # "whenever a player attacks [with N or more creatures]" (Avatar Roku, Aurelia): once per declaration by that
        # player (RULE 508.1), not once per defender as `PLAYER_ATTACKED` would fire.
        spec: dict[str, Any] = {"filter": {"card_type": "creature"}, "min": int(attacks.group("n") or 1)}
        return "ATTACKERS_DECLARED", condition, {"attackers_declared": spec}
    defended = _PLAYER_ATTACKS_DEFENDER.fullmatch(rest)
    if defended and m.group("actor") != "you":
        kind = next(k for k in _DEFENDER_KEYS if defended.group(k))
        keys = dict(_DEFENDER_KEYS[kind])
        n = int(defended.group("n") or 1)
        if defended.group("one") == "1 or more":
            # Once per declaration, however many of the opponents it names: `ATTACKERS_DECLARED`
            # (its event lists every attacked player) rather than `PLAYER_ATTACKED`'s once-per-defender.
            return "ATTACKERS_DECLARED", condition, {
                **keys, "attackers_declared": {"filter": {"card_type": "creature"}, "min": n},
            }
        if n > 1:
            keys["attackers_at_least"] = n
        return "PLAYER_ATTACKED", condition, {**trigger, **keys}
    expend = _EXPEND.fullmatch(rest)
    if expend:
        trigger["filter"] = {"amount": int(expend.group("n"))}
        return "EXPEND", condition, trigger
    mana = _MANA_TAP.fullmatch(rest)
    if mana:
        parsed = parse_object_phrase(mana.group("object"))
        if parsed is None or parsed[1] is not None:
            return None
        controller = "you" if condition["subject"] == "you" else condition["scope"]
        return "TAPPED_FOR_MANA", {
            "subject": "group", "controller": controller, "filter": parsed[0],
            "other": rest.startswith("tap another ") or rest.startswith("taps another "),
        }, trigger
    nth = _NTH_DRAW.match(rest)
    if nth is not None:
        trigger["is_nth_draw_this_turn"] = _ORDINALS[nth.group("n")]
        return "DRAW", condition, trigger
    for phrase, event in _VERBS.items():
        if rest == phrase:
            return event, condition, trigger
    for phrase, event in _VERBS.items():
        if rest.startswith(phrase + " "):
            tail = rest[len(phrase):].strip()
            if tail:
                phase, left = consume(tail, PHASE_TAILS)
                if phase is None or left:
                    return None
                trigger.update(phase)
            return event, condition, trigger
    return None
