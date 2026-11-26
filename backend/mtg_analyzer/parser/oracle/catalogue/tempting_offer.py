"""The tempting offer: "<X>. Each opponent may <X'>. For each opponent who does, <X''>." (the Tempt cycle, Tempting Contract).

One shape, read from three sentences. The controller's own instruction (absent for Tempting Contract), the
opponents' optional copy of it with the pronouns turned third-person, and the payoff repeated once for each opponent
who took the offer (RULE 608.2c: "does" is deciding to). Every opponent decides before the payoff runs
(RULE 101.4, turn order), so the payoff count is the number who said yes.

Built from existing nodes only: a `for_each` over the opponents asking each one an `optional` that runs as the asked
player (``acting: "chooser"``), whose first step records the yes (`accept_offer`); the payoff is the
`player_action_outcome_specs` shape, a `for_each` over the opponents filtered by ``action_result`` on that event,
inside a `bind` that opens the event window. The opponent's body is never parsed in third person: it must read
exactly like the controller's last sentence once "you control / your" is "they control / their", and then it *is*
that sentence's specs, run as the opponent.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from ..spec import EffectSpec

#: Event the accepted body fires; counted by the payoff loop (`composition.ForEachEffect`'s ``action_result``).
OFFER_EVENT = "OFFER_ACCEPTED"
#: The question asks for one yes: a player either took the offer or did not.
OFFER_MIN_COUNT = 1

_OFFER_RE = re.compile(
    r"(?:(?P<own>.+?)\. )?each opponent may (?P<opp>.+?)\. "
    r"for each opponent who does, (?:you )?(?P<pay>.+?)\.?"
)
_THIRD_PERSON = (
    (re.compile(r"\byou control\b"), "they control"),
    (re.compile(r"\byour\b"), "their"),
)
_THIRD_PERSON_WORD_RE = re.compile(r"\b(?:they|their|them)\b")


def _third_person(text: str) -> str:
    for pattern, replacement in _THIRD_PERSON:
        text = pattern.sub(replacement, text)
    return text


def tempting_offer_specs(body: str, parse: Callable[[str], Optional[list[EffectSpec]]]) -> Optional[list[EffectSpec]]:
    """The offer's specs, or ``None`` unless the three sentences agree exactly (fail closed)."""
    m = _OFFER_RE.fullmatch(body.strip())
    if m is None:
        return None
    own, opp, pay = m["own"], m["opp"], m["pay"]
    if own is not None:
        sentences = own.split(". ")
        last = sentences[-1]
        if _third_person(last) != opp or last != pay:
            return None
        head_text = ". ".join(sentences[:-1])
        head = parse(head_text) if head_text else []
        full = parse(own)
        if head is None or full is None or full[: len(head)] != head or len(full) == len(head):
            return None
        own_specs, offer = full, full[len(head):]
    else:
        if _THIRD_PERSON_WORD_RE.search(opp) or pay != opp:
            return None
        offer = parse(opp)
        own_specs = []
        if offer is None:
            return None
    # A body that announces a target of its own would be asked at resolution, not announced (RULE 601.2c).
    if any("target" in str(spec.params.get(key, "")) for spec in offer for key in ("target_kind", "kinds")):
        return None
    offer_dicts = [spec.to_dict() for spec in offer]
    ask = EffectSpec("for_each", {"over": {"players": "each_opponent", "carry_previous": True}, "effects": [
        {"type": "optional", "params": {"player": "target", "acting": "chooser", "effects": [
            {"type": "accept_offer", "params": {}}, *offer_dicts,
        ]}},
    ]})
    result = {"event": OFFER_EVENT, "start": "$action_start", "count": OFFER_MIN_COUNT, "negated": False}
    payoff = EffectSpec("for_each", {
        "over": {"players": "each_opponent", "action_result": result, "carry_previous": True},
        "effects": offer_dicts,
    })
    window = EffectSpec("bind", {"name": "action_start", "amount": {"kind": "event_cursor"},
                                 "effects": [ask.to_dict(), payoff.to_dict()]})
    return [*own_specs, window]
