"""RULE 103.6a "begin the game with it on the battlefield" opening-hand
permission recognition (docs/09).

A card printing "If this card is in your opening hand, you may begin the
game with it on the battlefield." (the Leyline cycle, plus a scatter of
other cards using the identical shape) grants a *pregame setup* permission
(RULE 103.6a) — not a static ability, not a resolve-time effect, so it
doesn't fit the `EffectRegistry`/binder pipeline at all (there's no
permanent yet to bind an ability onto; the card is still sitting in a
player's hand). Same split as `catalogue/lands.py`'s tapped-entry/
`catalogue/counters.py`'s entry-counters: this module is the single source
of truth for recognising the clause, claimed-without-a-spec by the
coverage gate (`gate.py`) and read directly off the card by the engine's
own setup step (`game/ability_catalogue.opening_hand_battlefield_permission`,
`services/game_session.py`'s opening-hand handling in `_keep_hand`).

Pure — **no `game/` imports** (front-end security boundary, docs/09).
"""

from __future__ import annotations

import re
from typing import Any

from ..normalize import normalize

#: "if this card is in your opening hand, you may begin the game with it
#: on the battlefield." / "...with him/her/them on the battlefield." (a
#: card whose own printed name is folded to ``~`` and referred back to by a
#: personal pronoun instead of "it" — Quicksilver, Brash Blur). Deliberately
#: a full-line match: a trailing clause (Gemstone Caverns' "...and you're
#: not the starting player"/"...with a luck counter on it. If you do, exile
#: a card from your hand.") is a genuinely different, conditional/costed
#: shape and stays unclaimed rather than silently dropping the condition.
_OPENING_HAND_BATTLEFIELD_RE = re.compile(
    r"^if (?:this card|~) is in your opening hand, "
    r"you may begin the game with (?:it|him|her|them) on the battlefield\.?$",
    re.IGNORECASE,
)


def opening_hand_battlefield_permission_line(line: str) -> bool:
    """Whether ``line`` is the RULE 103.6a "begin the game with it on the
    battlefield" clause — see `_OPENING_HAND_BATTLEFIELD_RE`. Claimed at the
    `gate._process_line` level, not through an `EffectSpec`: it carries no
    in-game behaviour to bind, only a pregame setup choice."""
    return bool(_OPENING_HAND_BATTLEFIELD_RE.match(line.strip()))


def opening_hand_battlefield_permission(card: Any) -> bool:
    """Whether ``card`` may begin the game on the battlefield straight from
    a kept opening hand (RULE 103.6a), read off its printed text.

    Normalizes the same way the front-end pipeline does (self-name folded
    to ``~``, reminder text stripped — docs/09 step 1) and checks each
    line, so the cards this recognises can never drift from what the
    coverage gate claims.
    """
    text = getattr(card, "oracle_text", "") or ""
    normalized = normalize(text, getattr(card, "name", None))
    return any(
        opening_hand_battlefield_permission_line(line)
        for line in normalized.split("\n")
        if line.strip()
    )
