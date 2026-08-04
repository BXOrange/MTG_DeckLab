"""RULE 103.6 pregame setup permission recognition (docs/09).

A card printing "If this card is in your opening hand, you may begin the
game with it on the battlefield." (RULE 103.6a — the Leyline cycle, plus a
scatter of other cards using the identical shape) grants a *pregame setup*
permission — not a static ability, not a resolve-time effect, so it doesn't
fit the `EffectRegistry`/binder pipeline at all (there's no permanent yet to
bind an ability onto; the card is still sitting in a player's hand). Same
split as `catalogue/lands.py`'s tapped-entry/`catalogue/counters.py`'s
entry-counters: this module is the single source of truth for recognising
the clause, claimed-without-a-spec by the coverage gate (`gate.py`) and read
directly off the card by the engine's own setup step (`game/ability_
catalogue.opening_hand_battlefield_permission`, `services/game_session.py`'s
opening-hand handling in `_keep_hand`).

Two genuinely different shapes (PLR-11's own follow-up, deliberately left
unclaimed at the time) round the family out, both still RULE 103.6 pregame
setup rather than in-game behaviour: Gemstone Caverns' **conditional,
costed, counter-bearing** battlefield permission ("...and you're not the
starting player...with a luck counter on it. If you do, exile a card from
your hand.") and Buried Ogre's **graveyard-destination** permission
("...in your graveyard. If you do, you lose N life." — RULE 103.6 has no
sub-letter of its own for a non-battlefield destination; RULE 103.6a is
specifically the battlefield case). `pregame_setup_permission(card)` is the
single card-level entry point covering all three shapes; the original
`opening_hand_battlefield_permission_line`/`_permission` pair stays narrowly
scoped to the plain unconditional shape (still what the coverage gate uses
to claim *that* line specifically, and what makes the two "shaped extra
clause" cases below correctly read as un-claimed by it).

Pure — **no `game/` imports** (front-end security boundary, docs/09).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from ..normalize import normalize

#: "if this card is in your opening hand, you may begin the game with it
#: on the battlefield." / "...with him/her/them on the battlefield." (a
#: card whose own printed name is folded to ``~`` and referred back to by a
#: personal pronoun instead of "it" — Quicksilver, Brash Blur). Deliberately
#: a full-line match: a trailing clause (Gemstone Caverns' "...and you're
#: not the starting player"/"...with a luck counter on it. If you do, exile
#: a card from your hand.") is a genuinely different, conditional/costed
#: shape this regex correctly leaves unmatched — see
#: `_BATTLEFIELD_CONDITIONAL_RE` below for that one instead.
_OPENING_HAND_BATTLEFIELD_RE = re.compile(
    r"^if (?:this card|~) is in your opening hand, "
    r"you may begin the game with (?:it|him|her|them) on the battlefield\.?$",
    re.IGNORECASE,
)

#: Gemstone Caverns' shape: RULE 103.6a's battlefield permission, gated on
#: "you're not the starting player" (103.6's own turn-order clause — the
#: starting player takes their pregame actions first, so a card worded this
#: way is only ever offered to someone else), entering with a named counter,
#: and trailing a mandatory "if you do, exile a card from your hand." — not
#: a payable cost gating the choice itself (unlike an activation cost), just
#: an unavoidable consequence of having made it, same as the plain shape's
#: "If you do" tails elsewhere in this engine (RULE 601.2c). Amount is "a"/
#: "an" (=1) or a bare digit (number words already folded by `normalize`),
#: matching `catalogue/counters.py`'s own `_AMOUNT`/`_COUNTER_TYPE` shapes.
#: Unlike the Leyline cycle (which refers back to "this card" with a
#: pronoun), Gemstone Caverns and Buried Ogre both name themselves directly
#: — folded to ``~`` by `normalize`, not "it"/"him"/"her"/"them" — so both
#: regexes below accept either form.
_BATTLEFIELD_CONDITIONAL_RE = re.compile(
    r"^if (?:this card|~) is in your opening hand and you're not the starting player, "
    r"you may begin the game with (?:it|him|her|them|~) on the battlefield with "
    r"(a|an|\d+) ([a-z]+) counter on it\. if you do, exile a card from your hand\.?$",
    re.IGNORECASE,
)

#: Buried Ogre's shape: a *graveyard*-destination pregame permission (RULE
#: 103.6 — there's no RULE 103.6a-style sub-letter for a non-battlefield
#: destination, it's just the general "some cards allow a player to take
#: actions with them from their opening hand" umbrella) with its own
#: mandatory "if you do, you lose N life." tail.
_GRAVEYARD_RE = re.compile(
    r"^you may begin the game with (?:it|him|her|them|~) in your graveyard\. "
    r"if you do, you lose (\d+) life\.?$",
    re.IGNORECASE,
)


def opening_hand_battlefield_permission_line(line: str) -> bool:
    """Whether ``line`` is the RULE 103.6a "begin the game with it on the
    battlefield" clause — see `_OPENING_HAND_BATTLEFIELD_RE`. Claimed at the
    `gate._process_line` level, not through an `EffectSpec`: it carries no
    in-game behaviour to bind, only a pregame setup choice."""
    return bool(_OPENING_HAND_BATTLEFIELD_RE.match(line.strip()))


def opening_hand_battlefield_conditional_permission_line(line: str) -> bool:
    """Whether ``line`` is Gemstone Caverns' conditional/costed/counter-
    bearing battlefield permission — see `_BATTLEFIELD_CONDITIONAL_RE`."""
    return bool(_BATTLEFIELD_CONDITIONAL_RE.match(line.strip()))


def opening_hand_graveyard_permission_line(line: str) -> bool:
    """Whether ``line`` is Buried Ogre's graveyard-destination pregame
    permission — see `_GRAVEYARD_RE`."""
    return bool(_GRAVEYARD_RE.match(line.strip()))


def opening_hand_battlefield_permission(card: Any) -> bool:
    """Whether ``card`` may begin the game on the battlefield straight from
    a kept opening hand (RULE 103.6a), read off its printed text.

    Normalizes the same way the front-end pipeline does (self-name folded
    to ``~``, reminder text stripped — docs/09 step 1) and checks each
    line, so the cards this recognises can never drift from what the
    coverage gate claims. Narrowly the *plain, unconditional* shape — see
    `pregame_setup_permission` for the conditional/graveyard shapes too.
    """
    text = getattr(card, "oracle_text", "") or ""
    normalized = normalize(text, getattr(card, "name", None))
    return any(
        opening_hand_battlefield_permission_line(line)
        for line in normalized.split("\n")
        if line.strip()
    )


@dataclass(frozen=True)
class PregameSetupPermission:
    """One card's RULE 103.6 pregame setup permission, read off its printed
    text by `pregame_setup_permission` below.

    ``destination`` is ``"battlefield"`` or ``"graveyard"``. ``condition``
    is ``None`` (unconditional — the plain Leyline shape) or
    ``"not_starting_player"`` (Gemstone Caverns — `services/game_session.py`
    checks this against `GameState.starting_player_id` before ever queuing
    the choice, since an unmet condition means the permission was never
    offered at all, not offered-and-auto-declined). ``counter_type``/
    ``counter_count`` are the RULE 614.1-style counters the card enters
    with, applied unconditionally the moment the destination is chosen
    (before the ``cost_kind`` tail, which is a *separate*, always-mandatory
    "if you do" consequence — never a payable cost that could make the
    player reconsider): ``None``/``"lose_life"`` (an amount off `RulesEngine
    .lose_life`) or ``"exile_hand_card"`` (a card the player chooses,
    `RulesEngine.request_choose_objects`'s ``"exile"`` action — nothing
    happens if the hand is empty, same as any "if you do" with nothing left
    to do).
    """

    destination: str
    condition: Optional[str] = None
    counter_type: Optional[str] = None
    counter_count: int = 0
    cost_kind: Optional[str] = None
    cost_amount: int = 0


def pregame_setup_permission(card: Any) -> Optional[PregameSetupPermission]:
    """``card``'s RULE 103.6 pregame setup permission, covering all three
    recognised shapes (plain/conditional-battlefield/graveyard) — or
    ``None`` if it has none. Single source of truth for `game/
    ability_catalogue.pregame_setup_permission`, the same split every
    other clause-shape module in this package uses.
    """
    text = getattr(card, "oracle_text", "") or ""
    normalized = normalize(text, getattr(card, "name", None))
    for line in normalized.split("\n"):
        line = line.strip()
        if not line:
            continue
        if opening_hand_battlefield_permission_line(line):
            return PregameSetupPermission(destination="battlefield")
        match = _BATTLEFIELD_CONDITIONAL_RE.match(line)
        if match:
            amount_token, counter_type = match.groups()
            count = 1 if amount_token in ("a", "an") else int(amount_token)
            return PregameSetupPermission(
                destination="battlefield",
                condition="not_starting_player",
                counter_type=counter_type,
                counter_count=count,
                cost_kind="exile_hand_card",
            )
        match = _GRAVEYARD_RE.match(line)
        if match:
            return PregameSetupPermission(
                destination="graveyard",
                cost_kind="lose_life",
                cost_amount=int(match.group(1)),
            )
    return None
