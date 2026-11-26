"""PAR-291 M5, RULE 701.13 / 406: "each opponent exiles cards from the top of their library until <they exile a nonland
card | they have exiled cards with total mana value N or greater [this way]>", optionally followed by the controller's
cast rider.

Each opponent digs their own library in turn order (RULE 101.4) and keeps ownership of what they exile (RULE 108.3);
the controller, not the owner, casts a hit (RULE 601.2, 601.3e). One `dig_until` spec with ``digger="each_opponent"``
(`RulesEngine._dig_each_opponent`) covers all of it; the stop condition is either the shared dig predicate table of
`casting_window` or the new running ``total_mana_value`` (a land adds 0, RULE 202.3). The rider is one of

* none (Krang & Shredder, Tasha's Hideous Laughter): the cards just stay exiled, linked to the source;
* "you may cast any number of spells from among those nonland cards without paying their mana costs" (Fevered
  Suspicion): one cast choice during this resolution (RULE 608.2g) over the hits;
* "until end of turn, you may cast cards exiled this way without paying their mana costs" (Dream Harvest): the same-turn
  free-cast window over every card exiled.
"""

from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from ..casting_window import DIG_PREDICATES
from .shared import compile_clause, EffectHandler

#: The whole spec keeps the digger's stop condition in one of two exclusive groups.
_STOP = (
    r"(?:they exile (?P<pred>" + "|".join(map(re.escape, DIG_PREDICATES)) + r") card"
    r"|(?:they have|that player has) exiled cards with total mana value (?P<total>\d+) or greater(?: this way)?)"
)
_RIDER = (
    r"(?:\s+(?:(?P<pool>you may cast any number of spells from among those nonland cards without paying their mana costs)"
    r"|(?P<window>until end of turn, you may cast cards exiled this way without paying their mana costs))\.?)?"
)
_DIG_EACH_OPPONENT_RE = compile_clause(
    r"each opponent exiles cards from the top of their library until " + _STOP + r"\.?" + _RIDER
)

#: The two cast riders only make sense after the stop they were printed with: "those nonland cards" follows the
#: nonland hit, "cards exiled this way" the total-mana-value pile (a window over a pile of hits is a different card).
_POOL_RESOLUTION = "cast_pool_resolution"
_POOL_WINDOW = "cast_pool_window"


def _dig_each_opponent(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    total = m.group("total")
    pred = m.group("pred")
    params: dict = {"digger": "each_opponent", "rest_destination": "exile", "track_exiled_with": True}
    if total is not None:
        if m.group("pool"):
            return None
        params["total_mana_value"] = int(total)
    else:
        if m.group("window") or (m.group("pool") and pred.lower() != "a nonland"):
            return None
        params["criteria"] = dict(DIG_PREDICATES[pred.lower()])
    params["hit_destination"] = (
        _POOL_RESOLUTION if m.group("pool") else _POOL_WINDOW if m.group("window") else "exile"
    )
    return [EffectSpec("dig_until", params)]


ROWS: list[EffectHandler] = [
    EffectHandler("dig_each_opponent", _DIG_EACH_OPPONENT_RE, _dig_each_opponent),
]
