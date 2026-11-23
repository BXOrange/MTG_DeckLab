"""PAR-292 M14, RULE 701.20 / 400.3: "reveal cards from the top of their library until ..." where the digger is a player
other than the ability's controller ("its controller", "that player", "target player", "target opponent").

The dig itself is `RulesEngine.dig_until` run on the digger's own library: the hit and the rest are put by that player,
so a creature enters under the digger's control (RULE 110.2) and the rest goes to that library / graveyard (RULE 401.3),
never the ability controller's. The only new part is who digs: `DigUntilEffect.digger` reads the previous clause's
target controller, the loop item's controller (`for_each` over what was exiled / destroyed this way) or a target player.
"""

from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from ..clause_reading import ClauseReading
from ..clause_hooks import match_clause
from ..dig import parse_criteria
from .shared import compile_clause, EffectHandler

#: The digger wordings whose referent is the permanent an earlier clause of this ability took away (its last-known
#: controller, RULE 608.2h). "that player" after such a clause is the same person (Blessed Reincarnation).
_CONTROLLER_WHO = r"its controller|that (?:creature|permanent|artifact|land)'?s controller|that player"
_TARGET_WHO = r"target player|target opponent"
_DIGGER_TARGETS = {"target player": "player", "target opponent": "opponent"}

#: "<who> reveals cards from the top of their library until <they reveal a creature card | a creature card is revealed>".
_HEAD = (
    r"(?P<who>{who}) reveals cards from the top of their library until "
    r"(?:they reveal (?P<p1>an? [a-z ,'-]+?) card|(?P<p2>an? [a-z ,'-]+?) card is revealed)"
)
#: Where the rest of the revealed cards go. "in any order" is deliberately absent (BUG-80: the engine bottoms in a
#: random order, the player cannot choose the sequence); only "in a random order" is the printed random bottom.
_REST = (
    r"(?:, then shuffles (?:the rest|all other cards revealed this way) into their library(?P<shuffle>)"
    r"|(?:,? then | and )(?:puts )?the rest on the bottom of their library in a random order(?P<bottom>))"
)
_PUT = r"(?:\.\s+|,\s+)(?:(?:that player|the player|they) )?puts that card (?P<hit>onto the battlefield|into their hand)"
_SUFFIX = r"(?:" + _REST + r")"

_PUT_RE = {
    who: compile_clause(_HEAD.format(who=who) + _PUT + _SUFFIX)
    for who in (_CONTROLLER_WHO, _TARGET_WHO)
}
#: "... until they reveal a land card, then puts those cards into their graveyard": the hit goes with the rest.
_GRAVEYARD_RE = {
    who: compile_clause(_HEAD.format(who=who) + r", then puts those cards into their graveyard(?P<grave>)")
    for who in (_CONTROLLER_WHO, _TARGET_WHO)
}
_DIG_CARD_TYPES = frozenset({"creature", "land", "artifact", "enchantment", "planeswalker"})
_HIT_DESTINATIONS = {"onto the battlefield": "battlefield", "into their hand": "hand"}


def _dig_specs(m: re.Match[str]) -> Optional[dict]:
    """The ``dig_until`` params of one matched wording, or ``None`` when the quality is not a plain card predicate."""
    quality = (m.group("p1") or m.group("p2")).split(" ", 1)[1]  # drop the article
    criteria = parse_criteria(f"{quality} card")
    if not criteria or criteria.get("type") not in _DIG_CARD_TYPES:
        return None  # only one plain card type: "a permanent card that shares ..." etc. stay unclaimed
    groups = m.groupdict()
    params: dict = {"criteria": dict(criteria)}
    if groups.get("grave") is not None:
        params.update(hit_destination="graveyard", rest_destination="graveyard")
    else:
        params["hit_destination"] = _HIT_DESTINATIONS[m.group("hit")]
        params["rest_destination"] = "library_shuffled" if groups.get("shuffle") is not None else "library_bottom_random"
    return params


def parse_reveal_until_other(text: str, *, iterating: bool = False) -> Optional[list[EffectSpec]]:
    """One sentence group in a controller wording as a ``dig_until`` run by that controller, or by the loop item's
    controller when ``iterating`` (the body of a "for each ... exiled this way" loop). ``None`` if it is anything else."""
    for table in (_PUT_RE, _GRAVEYARD_RE):
        m = table[_CONTROLLER_WHO].fullmatch(text.strip())
        if m is not None:
            params = _dig_specs(m)
            if params is None:
                return None
            params["digger"] = "iteration_item_controller" if iterating else "previous_target_controller"
            return [EffectSpec("dig_until", params)]
    return None


def _controller_dig(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    params = _dig_specs(m)
    if params is None:
        return None
    params["digger"] = "previous_target_controller"
    return [EffectSpec("dig_until", params)]


def _target_dig(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _dig_specs(m)
    if params is None:
        return None
    # RULE 115.1: the dug player is a target of this ability; `digger="facing"` reads it.
    params.update(digger="facing", target_kind=_DIGGER_TARGETS[m.group("who")])
    return [EffectSpec("dig_until", params)]


#: "Exile N target creatures. For each of those creatures, its controller reveals ... " (Divergent Transformations): the
#: loop runs over what the exile took (RULE 608.2c), so the pronoun phrase is only read behind this exact exile head.
_EXILE_THEN_EACH_RE = compile_clause(
    r"(?P<head>exile \d+ target creatures)\. for each of those creatures, (?P<body>its controller reveals [^.]+)"
)


def _exile_then_each_dig(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    head = match_clause(m.group("head"))
    dig = parse_reveal_until_other(m.group("body"), iterating=True)
    if not head or len(head) != 1 or head[0].type != "exile" or dig is None:
        return None
    over = {"this_way": "exiled", "this_way_type": ["Creature"]}
    return [head[0], EffectSpec("for_each", {"over": over, "effects": [e.to_dict() for e in dig]})]


#: "Reveal cards from the top of your library until you reveal a nonland card, then put all cards revealed this way into
#: your hand." (Treasure Hunt): the own-library dig whose hit and rest share one destination.
_REVEAL_ALL_TO_HAND_RE = compile_clause(
    r"reveal cards from the top of your library until you reveal (?P<pred>an? [a-z ,'-]+?) card, "
    r"then put all cards revealed this way into your hand"
)


def _reveal_all_to_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    criteria = parse_criteria(f'{m.group("pred").split(" ", 1)[1]} card')
    if not criteria:
        return None
    if "type" in criteria and criteria["type"] not in _DIG_CARD_TYPES:
        return None
    return [EffectSpec("dig_until", {"criteria": dict(criteria), "hit_destination": "hand", "rest_destination": "hand"})]


ROWS: list[EffectHandler] = [
    EffectHandler("reveal_until_all_to_hand", _REVEAL_ALL_TO_HAND_RE, _reveal_all_to_hand),
    EffectHandler("exile_then_each_dig", _EXILE_THEN_EACH_RE, _exile_then_each_dig),
    EffectHandler(
        "reveal_until_controller_put", _PUT_RE[_CONTROLLER_WHO], _controller_dig,
        reading_aware=True, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "reveal_until_controller_graveyard", _GRAVEYARD_RE[_CONTROLLER_WHO], _controller_dig,
        reading_aware=True, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler("reveal_until_target_put", _PUT_RE[_TARGET_WHO], _target_dig),
    EffectHandler("reveal_until_target_graveyard", _GRAVEYARD_RE[_TARGET_WHO], _target_dig),
]
