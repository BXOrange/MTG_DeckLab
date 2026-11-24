"""PAR-292 M21, RULE 700.3 / 101.4 / 701.20: "reveal the top N cards of your library. An opponent separates those cards into
two piles. Put one pile into your hand and the other into your graveyard." (Fact or Fiction, Sphinx of Uthuun) and its
siblings, all one `reveal_split_piles` (`game/effects/piles.py`):

* who divides: "an opponent separates those cards into 2 piles" (``divider`` opponent) against "<you> ... separate them
  into 2 piles. An opponent chooses 1 of those piles" (Steam Augury, Epiphany at the Drownyard; ``divider`` you);
* reveal against look: "look at the top N ... and separate them into a face-down pile and a face-up pile. An opponent
  chooses 1 of those piles" (Curator of Destinies, Riddles in the Dark) and "target opponent / [choose an opponent.] they
  look at the top N cards of your library and separate(s) them into a face-down pile and a face-up pile. Put 1 pile into
  your hand ..." (Atris, Fortune's Favor, Sauron's Ransom), whose chooser is the controller and whose opponent is a RULE
  115 target for the "target opponent" wording;
* how many: a literal N, "x plus 1" (the announced X of the spell), or "x, where x is the number of basic land types
  among lands you control" (Sphinx of Clear Skies).

Pure data in, `EffectSpec`s out. The destinations are fixed by the one wording the piles are printed with (hand and
graveyard); any other destination leaves the clause unclaimed.
"""

from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from .shared import compile_clause, EffectHandler

_COUNT = r"(?P<count>\d+|x(?: plus 1)?)"
_CARDS = rf"the top {_COUNT} cards? of your library"
#: "x, where x is <how many>": the one measured count the pile cards print.
_WHERE_X = r"(?:, where x is (?P<where>the number of basic land types among lands you control))?"
_TWO_PILES = r"(?:2|two) piles"
_FACE_PILES = r"a face-down pile and a face-up pile"
_PUT = r"put (?:1|one) pile into your hand and the other into your graveyard"
_PUT_THAT = r"put that pile into your hand and the other into your graveyard"
#: PAR-292 M23 (Truth or Tale): one card of the chosen pile to the hand, every other revealed card to the library bottom.
_PICK_ONE_REST_BOTTOM = (
    r"put a card from the chosen pile into your hand, then put all other cards revealed this way on the bottom of your "
    r"library in any order"
)

#: Count words the grammar measures at resolution -> the `continuous.count_selector` argument.
_WHERE_SELECTORS = {"the number of basic land types among lands you control": "basic_land_types_among_lands_you_control"}
#: "x plus 1" -> `{"terms": ["source_x_paid"], "plus": 1}` (RULE 107.3: the announced X of the resolving spell).
_X_PLUS_ONE = {"terms": ["source_x_paid"], "plus": 1}

_OPPONENT_SEPARATES_RE = compile_clause(
    rf"reveal {_CARDS}{_WHERE_X}\.\s*an opponent separates those cards into {_TWO_PILES}\.\s*{_PUT}"
)
_YOU_SEPARATE_REVEALED_RE = compile_clause(
    rf"reveal {_CARDS}{_WHERE_X} and separate them into {_TWO_PILES}\.\s*an opponent chooses (?:1|one) of those piles\.\s*"
    rf"{_PUT_THAT}"
)
_YOU_SEPARATE_PICK_RE = compile_clause(
    rf"reveal {_CARDS}{_WHERE_X} and separate them into {_TWO_PILES}\.\s*an opponent chooses (?:1|one) of those piles\.\s*"
    rf"{_PICK_ONE_REST_BOTTOM}"
)
_YOU_SEPARATE_LOOKED_RE = compile_clause(
    rf"look at {_CARDS} and separate them into {_FACE_PILES}\.\s*an opponent chooses (?:1|one) of (?:those|the) piles\.\s*"
    rf"{_PUT_THAT}"
)
_OPPONENT_LOOKS_RE = compile_clause(
    rf"(?P<who>target opponent|choose an opponent\.\s*they) looks? at {_CARDS} and separates? them into {_FACE_PILES}\.\s*"
    rf"{_PUT}"
)


def _piles(m: re.Match[str], *, reveal: bool, divider: str, face_down: bool, opponent: Optional[str] = None) -> Optional[list[EffectSpec]]:
    raw = m.group("count")
    params: dict = {"reveal": reveal, "divider": divider, "face_down": face_down}
    where = m.groupdict().get("where")
    if where:
        if raw != "x":
            return None
        params["count_selector"] = _WHERE_SELECTORS[where]
    elif raw == "x":
        return None  # a bare X is the announced X of a spell; a trigger or ability would measure another number
    elif raw == "x plus 1":
        params["count_selector"] = dict(_X_PLUS_ONE)
    else:
        params["count"] = int(raw)
    if opponent:
        params["opponent"] = opponent
    return [EffectSpec("reveal_split_piles", params)]


def _opponent_separates(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _piles(m, reveal=True, divider="opponent", face_down=False)


def _you_separate_revealed(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _piles(m, reveal=True, divider="you", face_down=False)


def _you_separate_looked(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _piles(m, reveal=False, divider="you", face_down=True)


def _you_separate_pick(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    specs = _piles(m, reveal=True, divider="you", face_down=False)
    if specs is not None:
        specs[0].params["fate"] = "pick_one_rest_bottom"
    return specs


def _opponent_looks(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _piles(m, reveal=False, divider="opponent", face_down=True,
                  opponent="target" if m.group("who") == "target opponent" else None)


ROWS: list[EffectHandler] = [
    EffectHandler("piles_opponent_separates_revealed", _OPPONENT_SEPARATES_RE, _opponent_separates),
    EffectHandler("piles_you_separate_revealed", _YOU_SEPARATE_REVEALED_RE, _you_separate_revealed),
    EffectHandler("piles_you_separate_revealed_pick_one", _YOU_SEPARATE_PICK_RE, _you_separate_pick),
    EffectHandler("piles_you_separate_looked", _YOU_SEPARATE_LOOKED_RE, _you_separate_looked),
    EffectHandler("piles_opponent_looks_separates", _OPPONENT_LOOKS_RE, _opponent_looks),
]
