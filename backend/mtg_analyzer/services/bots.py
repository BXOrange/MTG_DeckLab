"""Bots that can sit in a multiplayer seat and play the game (UC5).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md UC5,
mtg_analyzer/services/game_session.py, mtg_analyzer/services/lobby.py.

A bot occupies an ordinary seat: the lobby gives it a `LobbyPlayer` and a
`Seat` like anyone else, the engine gives it a `Player` in the `GameState`
like anyone else, and it takes its turn through the same actions a browser
posts. Nothing about the rules engine knows a bot exists.

**A bot plays through exactly the surface a browser has**, and that is the
load-bearing design rule here, not a stylistic one:

* it reads `GameSession.view(perspective=<its own id>)` — the *redacted*
  view, so it cannot see an opponent's hand or anybody's library (RULE
  400.2). A bot that read `engine.state` directly would be cheating, and
  worse, would quietly become the one client whose behaviour doesn't prove
  the redaction works.
* it only ever plays something `legal_actions` offered it, and applies it
  with `apply_action(action, actor_id=...)` — so RULE 117 priority, RULE
  601.3a timing and every other per-player gate are enforced against it by
  the engine, not re-implemented (or accidentally skipped) here.

Five bots are built on that base, each in its own `bot_policies` module:

* `GoldfishBot` — plays a land per turn and otherwise passes. It is the
  moving target `run_goldfish_turn`'s passive dummy never was: a real seat
  with a real deck, a library that mills and a life total that can be
  attacked, that nonetheless never interferes. What you want to time a
  combo against.
* `GreedyBot` — plays everything it can as soon as it can, activates the
  first ability it can pay for, attacks with everything and blocks with
  everything. No lookahead, no evaluation, no holding mana up for a
  response. What you want to check that your deck survives contact with an
  opponent that actually does things.
* `ManaMaximizerBot` — plays a land per turn and taps every remaining mana
  source dry, but never casts or attacks. A diagnostic bot for ANA-4's
  dynamic analysis (`services/dynamic_analysis.py`), not a real opponent:
  it exists to show a deck's true per-turn mana-production ceiling, since
  neither of the other two bots ever taps out for its own sake.

* `SmartBot` — detects deck themes, commander synergies and colours from
  its own deck list; prioritizes visible combo progress, tutors for missing
  pieces, develops mana and evaluates combat and responses. A bounded
  heuristic opponent, not an exhaustive solver of arbitrary combos.

* `AIBot` — asks the configured LLM to choose offered actions using the
  same deck profile. Background requests preserve priority; failures use
  Smart Bot. See docs/Reference/LLM_INTEGRATION.md.

The three diagnostic policies remain simple and predictable. Smart Bot uses
`bot_strategy.py` for unordered deck knowledge and a local Spellbook snapshot
when available; gameplay still reads only its redacted client view.

`run_bots` is the driver: it is called after anything changes a game
(`api/multiplayer.py`) and once a second by the watchdog
(`api/multiplayer_ws.py`, which is what keeps a bot-vs-bot table moving
with no human in it at all).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from mtg_analyzer.services.bot_policies.base import Bot
from mtg_analyzer.services.bot_policies.goldfish import GoldfishBot
from mtg_analyzer.services.bot_policies.greedy import GreedyBot
from mtg_analyzer.services.bot_policies.smart import SmartBot
from mtg_analyzer.services.bot_policies.ai import AIBot
from mtg_analyzer.services.bot_policies.mana_maximizer import ManaMaximizerBot
from mtg_analyzer.services.game_session import GameActionError, GameSession

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mtg_analyzer.services.lobby import LobbyGame

logger = logging.getLogger(__name__)

#: Ceiling on how many actions one `run_bots` call may apply. Generous
#: relative to a real bot turn (a greedy bot developing a full board runs
#: to a few dozen), and the only thing standing between the server and a
#: card that lets a greedy bot activate the same ability forever.
MAX_BOT_ACTIONS = 200

#: Prefix every bot's player id carries, so a bot seat is recognizable in a
#: lobby snapshot / game state without a lookup (`is_bot_id`).
BOT_ID_PREFIX = "bot:"


def is_bot_id(player_id: Optional[str]) -> bool:
    return bool(player_id) and str(player_id).startswith(BOT_ID_PREFIX)


#: Every bot a seat can be filled with, keyed by `Bot.kind`.
BOT_TYPES: dict[str, type[Bot]] = {
    SmartBot.kind: SmartBot,
    GoldfishBot.kind: GoldfishBot,
    GreedyBot.kind: GreedyBot,
    AIBot.kind: AIBot,
    ManaMaximizerBot.kind: ManaMaximizerBot,
}


def bot_catalogue() -> list[dict[str, str]]:
    """The pickable bots, for the lobby UI's "add a bot" menu."""
    return [
        {"kind": cls.kind, "label": cls.label, "description": cls.description}
        for cls in BOT_TYPES.values()
    ]


def create_bot(kind: str, player_id: str, name: str = "") -> Bot:
    """Build a bot of ``kind``. Raises `KeyError` for an unknown kind."""
    return BOT_TYPES[kind](player_id, name)


def bots_for_game(game: "LobbyGame") -> dict[str, Bot]:
    """Every bot seated at ``game``, in seat (turn) order.

    Built fresh each call rather than cached: a bot holds no game state
    (its whole policy is a function of the view it is handed), and the one
    thing it *does* remember — which offers blew up on it — is meant to
    last a single `run_bots` call, not the game.
    """
    bots: dict[str, Bot] = {}
    for seat in game.seats:
        if not seat.bot_kind:
            continue
        try:
            bots[seat.player_id] = create_bot(seat.bot_kind, seat.player_id, seat.name)
        except KeyError:
            logger.warning("seat %s has unknown bot kind %r", seat.player_id, seat.bot_kind)
    return bots


def run_bots(
    session: GameSession, bots: dict[str, Bot], max_actions: int = MAX_BOT_ACTIONS
) -> bool:
    """Let every bot at the table act until none of them can. Returns "moved".

    Called after anything changes the game — a human's action
    (`api/multiplayer.py`), a disconnect, or just the once-a-second
    watchdog tick (`api/multiplayer_ws.py`), which is what drives a table
    with no humans at it at all.

    One action per iteration, re-reading the view each time, so a bot sees
    the consequences of what it just did exactly as a human client would
    (a resolved trigger, a new pending choice, a creature that died).

    `max_actions` is a yield point, not an error budget: at a table with no
    human at all the bots would otherwise play the whole game inside one
    request, so the run stops and hands control back to the caller, which
    (a broadcast, then the next watchdog tick) simply calls again. Hitting
    it is therefore normal — hence `debug`, not `warning`.
    """
    moved = False
    for _ in range(max_actions):
        if session.engine.state.game_over:
            return moved
        if not _one_bot_action(session, bots):
            return moved
        moved = True
    logger.debug("bot run yielded at the %d-action cap in session %s", max_actions, session.id)
    return moved


def _one_bot_action(session: GameSession, bots: dict[str, Bot]) -> bool:
    """Apply at most one bot action. Returns whether anything happened."""
    for bot in bots.values():
        # Cheap gate first: a bot with nothing offered has nothing to do,
        # and this is the common case on a human's turn.
        actions = session.legal_actions(perspective=bot.player_id)
        if not actions:
            continue
        bot.prepare(session)
        view = session.view(perspective=bot.player_id)
        action = bot.decide(view, actions)
        if action is None and bot.waiting:
            continue  # background LLM decision; preserve this priority window
        if action is None:
            # RULE 117.3: holding priority with nothing to do means passing.
            if not bot.has_priority(view) or not view["setup"]["complete"]:
                continue
            action = {"type": "pass_priority"}
        try:
            session.apply_action(action, actor_id=bot.player_id)
        except GameActionError as exc:
            # The bot picked something it couldn't actually complete. Don't
            # let it retry that offer, and don't let one bad choice wedge
            # the table — passing is always legal.
            logger.info("bot %s failed action %s: %s", bot.name, action.get("type"), exc)
            bot.note_failure(action)
            if not bot.has_priority(view):
                continue
            try:
                session.apply_action({"type": "pass_priority"}, actor_id=bot.player_id)
            except GameActionError:
                continue
        return True
    return False
