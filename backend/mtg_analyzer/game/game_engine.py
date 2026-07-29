"""The game engine: turn/phase/step loop, actions, goldfish (docs/02 R4.*).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R4.1-R4.3 (Game Loop, Priority,
Action Validation), UC3 (Goldfisch), docs/07 PART 1/8.

`RulesEngine` is the toolbox of rules primitives; `GameEngine` is the
loop that drives it: it walks a `TurnSequence`, opens priority windows in
which the stack resolves (RULE 117/608), runs step bodies (untap, draw,
combat damage, cleanup), and exposes validated player actions (play a
land, cast a spell, attack) plus a `legal_actions` query the UI/bot can
ask instead of guessing (docs/02 R4.3 — the frontend has no such check
today). `run_goldfish_turn` wires those together into a solo auto-turn
(UC3).

`GameEngine` itself (ENG-20) is a composition of eight per-responsibility
mixins under `game/engine/` — turn loop (incl. `new_game`), combat,
casting, lands, activation, mana, legal-actions, misc — rather than one
class carrying all ~130 methods. This is a pure file-organization split:
every mixin operates on the same shared `self.state`/`self.rules`/etc.
instance state, method names/signatures are unchanged, and nothing outside
`game/` needs to know the class is assembled this way.
"""

from __future__ import annotations

from .rules_engine import RulesEngine
from .engine.activation_mixin import ActivationMixin
from .engine.casting_mixin import CastingMixin
from .engine.combat_mixin import CombatMixin
from .engine.lands_mixin import LandsMixin
from .engine.legal_actions_mixin import LegalActionsMixin
from .engine.mana_mixin import ManaMixin
from .engine.misc_mixin import MiscMixin
from .engine.turn_loop_mixin import MAX_HAND_SIZE, TurnLoopMixin

__all__ = ["GameEngine", "MAX_HAND_SIZE"]


class GameEngine(
    TurnLoopMixin,
    CombatMixin,
    CastingMixin,
    LandsMixin,
    ActivationMixin,
    ManaMixin,
    LegalActionsMixin,
    MiscMixin,
):
    """Drives a `GameState` through turns using a `RulesEngine`.

    Construction and `new_game` (the class's public entry point for
    building a fresh game) live in `TurnLoopMixin` alongside the rest of
    turn/game setup — see that module for both.
    """

    def __init__(self, state: "GameState") -> None:
        self.state = state
        self.rules = RulesEngine(state)
        #: Cursor for interactive step-by-step play (see ``start`` /
        #: ``advance_step``): the current turn's ``(phase, step)`` list and
        #: how far through it we are. ``run_turn``/``run_goldfish_turn`` do
        #: not use these — they run a whole turn at once.
        self._turn_steps: list = []
        self._cursor = 0
        #: RULE 117: whether every priority window is *played out* by real
        #: players (multiplayer) instead of auto-drained. Off by default, so
        #: every solo path — goldfish, replay, every existing test — keeps
        #: resolving the stack the moment a step opens, exactly as before.
        #: On, `_run_step` only puts triggers on the stack and then leaves
        #: it alone: the active player holds priority and the session drives
        #: `pass_priority(player)` around the table (`services/
        #: game_session.py`). See `GameSession._pass_priority`.
        self.interactive_priority = False
