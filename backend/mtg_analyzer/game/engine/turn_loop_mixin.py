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
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from typing import Any, Optional

from ...models.card import Card
from ...models.events import EventType, GameEvent
from ...models.game_object import GameObject, Zone
from ...models.game_state import GameState, StackItem
from ...models.mana_cost import ManaCost
from ...models.player import Player
from .. import combat, condition_query, continuous, durations, face_down, variants
from ...models import game_format
from ...models.game_format import GameFormat, get_format
from ..costs import (
    DISCARD_HAND,
    PAY_LIFE_X,
    REMOVE_COUNTERS_ANY,
    REMOVE_COUNTERS_X,
    ActivationCost,
    parse_activation_cost,
)
from ..effects import ActivatedAbility, GrantSkipExtraTurnsEffect
from ..mana_abilities import (
    hand_mana_abilities_for,
    mana_abilities_for,
    option_label,
    restriction_predicate_for_activation,
    restriction_predicate_for_cast,
    validate_color_split,
)
from ..phases import GamePhase, GameStep, default_turn_sequence
from ..rules_engine import RulesEngine
from ..targeting import (
    TargetSpec,
    ability_target_specs,
    all_requirements_satisfiable,
    legal_targets,
    partition_targets,
    requirements_with_targets,
    resolved_count,
    spell_target_specs,
)
from ..graveyard_cast import graveyard_cast_grant_for
from ..top_library import (
    may_cast_flash_from_top_of_library,
    may_cast_spell_from_top_of_library,
    may_play_land_from_top_of_library,
    top_library_life_payment_required,
)

#: Maximum hand size enforced at cleanup (RULE 402.2 / 514.1).
MAX_HAND_SIZE = 7

#: Safety cap so a misbehaving trigger/replacement can't hang the loop.
_MAX_RESOLUTIONS = 1000




class TurnLoopMixin:
    """The turn/phase/step loop and its priority-window plumbing (RULE 500/117)."""

    @classmethod
    def new_game(
        cls,
        player_libraries: list[tuple[str, str, list[Card]]],
        starting_life: int = 40,
        starting_hand: int = 7,
        game_format: Optional[str] = None,
        archenemy_id: Optional[str] = None,
    ) -> "GameEngine":
        """Build a game from ``(player_id, name, library_cards)`` tuples.

        Each player's library is built from the given cards (top of the
        library is the end of the list), and an opening hand is drawn. No
        shuffle is applied — callers wanting randomness shuffle first — so
        games are reproducible for tests and the bot.

        ``game_format`` names a `models/game_format.py` record (RULE 8/9).
        Given one, its own starting life/hand size replace the arguments
        above — a caller picks *a format*, not a combination of numbers — and
        its RULE 9 variants are set up: Planechase's shared planar deck (RULE
        901.15), the archenemy's scheme deck and 40 life (RULE 904.4/904.5),
        a Vanguard avatar per player with its hand/life modifiers (RULE
        902.3/902.4). Without one, nothing changes: the explicit numbers win
        and no variant state exists, which is every existing caller.
        """
        fmt = get_format(game_format) if game_format else None
        if fmt is not None:
            starting_life, starting_hand = fmt.starting_life, fmt.starting_hand
        players: list[Player] = []
        for player_id, name, cards in player_libraries:
            player = Player(id=player_id, name=name, life=starting_life)
            for card in cards:
                obj = GameObject(card=card, owner_id=player_id, zone=Zone.LIBRARY)
                player.library.append(obj)
            players.append(player)

        state = GameState(players=players)
        engine = cls(state)
        if fmt is not None:
            state.format_name = fmt.name
            engine._setup_variants(fmt, archenemy_id)
        for player in players:
            # RULE 902.3: a Vanguard avatar's hand modifier changes how many
            # cards its controller starts with, so it has to be settled
            # before the opening hand is drawn.
            player.draw(max(0, starting_hand + player.hand_size_modifier))
        return engine
    def _setup_variants(self, fmt: "GameFormat", archenemy_id: Optional[str]) -> None:
        """Put the RULE 9 variants' command-zone cards in place for a new game."""
        state = self.state
        if fmt.has(game_format.PLANECHASE):
            # RULE 901.5/901.15: one shared planar deck; RULE 901.9: the game
            # starts with its top card face up as the first plane, which
            # `planeswalk`-free setup does by simply leaving it on top.
            state.planar_deck = variants.build_planar_deck(state.players[0].id)
        if fmt.has(game_format.ARCHENEMY) and state.players:
            archenemy = next(
                (p for p in state.players if p.id == archenemy_id), state.players[0]
            )
            state.archenemy_id = archenemy.id
            archenemy.scheme_deck = variants.build_scheme_deck(archenemy.id)
            archenemy.life = fmt.archenemy_life  # RULE 904.4
        if fmt.has(game_format.VANGUARD):
            for player in state.players:
                avatar = variants.build_vanguard(player.id)
                if avatar is None:
                    continue
                player.vanguard = avatar
                hand_mod, life_mod = variants.vanguard_modifiers(avatar.name)
                player.hand_size_modifier = hand_mod
                player.life += life_mod  # RULE 902.4
    def _advance_round_number(self) -> None:
        """Bump the display-only round counter when the table wraps around.

        RULE 500.1 counts every player's turn separately, which is what
        `turn_number` is; `round_number` counts how often the turn has come
        back around to whoever started, which is what players mean by
        "we're on turn 4". A player leaving the game (RULE 800.4a) would
        strand a counter keyed on them alone, so the reference point moves
        to whoever the turn lands on next in that case.
        """
        state = self.state
        if state.starting_player_id is None:
            state.starting_player_id = state.active_player.id
        elif not any(p.id == state.starting_player_id for p in state.players):
            state.starting_player_id = state.active_player.id
            state.round_number += 1
            return
        if state.active_player.id == state.starting_player_id:
            state.round_number += 1
    def begin_turn(self) -> None:
        """Advance to the next player's turn and reset per-turn state."""
        if self.state.turn_number == 0:
            self.state.turn_number = 1
            self.state.active_player_index = 0
            # The reference point for the display-only round counter: round 1
            # begins with whoever takes turn 1 (`GameState.round_number`).
            self.state.round_number = 1
            self.state.starting_player_id = self.state.active_player.id
        else:
            # Capture the outgoing player's final spell count before rotating
            # — RULE 731.2's day/night check reads *last* turn's active
            # player, from the untap step of the turn about to begin.
            outgoing = self.state.active_player
            self.state._last_turn_player_id = outgoing.id
            self.state._last_turn_spell_count = self.state.spells_cast_this_turn.get(outgoing.id, 0)
            self.state.turn_number += 1
            # RULE 500.7: a queued extra turn is taken right after this one,
            # before the normal next player — pop the front of the queue and
            # hand that player the turn instead of rotating the round-robin.
            # RULE 500.7/700.4: "If an opponent would begin an extra turn,
            # that player skips that turn instead." (Stranglehold-shaped)
            # — pop past every queued taker a live grant skips, so the
            # turn falls through to the next queued extra turn (or,
            # failing that, normal rotation) rather than handing the
            # skipped player anything.
            while self.state.extra_turns and any(
                isinstance(e, GrantSkipExtraTurnsEffect) and permanent.controller_id != self.state.extra_turns[0]
                for permanent in self.state.battlefield
                for e in getattr(permanent, "static_effects", None) or []
            ):
                self.state.extra_turns.pop(0)
            if self.state.extra_turns:
                taker_id = self.state.extra_turns.pop(0)
                self.state.active_player_index = next(
                    (i for i, p in enumerate(self.state.players) if p.id == taker_id),
                    self.state.next_active_index(),
                )
            else:
                # Rotate to the next player, skipping the passive goldfish dummy
                # (UC3) so a solo game keeps handing turns back to the human.
                self.state.active_player_index = self.state.next_active_index()
            self._advance_round_number()
        # RULE 800.4a, deferred: a player who conceded during someone else's
        # turn keeps their board standing until the next turn begins, so the
        # position the other players were reading doesn't vanish mid-turn
        # (see `RulesEngine.concede`). Swept here, before the new active
        # player is settled on, so their permanents are already gone for
        # every turn-based action of the turn about to start.
        for player_id in self.state.pending_leave_ids:
            try:
                self.rules.remove_player_from_game(self.state.player_by_id(player_id))
            except KeyError:
                pass
        self.state.pending_leave_ids.clear()
        active = self.state.active_player
        active.lands_played_this_turn = 0
        active.extra_land_plays_this_turn = 0
        # RULE 901.6b: the planar die costs {X} where X is how many times its
        # roller has already rolled it *this turn*, so the tally resets with
        # every other per-turn counter here.
        self.state.planar_die_rolls_this_turn.clear()
        # MEC-36: widened from `active.id`-only to every player (Damping
        # Sphere needs a non-active player's own running total to stay
        # accurate too — see the field's own docstring), the same
        # game-wide reset scope `noncreature_spells_cast_this_turn` below
        # already uses.
        for player in self.state.players:
            self.state.spells_cast_this_turn[player.id] = 0
        self.state.combats_this_turn = 0
        self.state.cards_drawn_this_turn[active.id] = 0
        self.state.cards_drawn_this_turn_ids[active.id] = []
        self.state.life_gained_this_turn[active.id] = 0
        # RULE 120.3 history ("dealt combat damage by ~ *this turn*", Hope of
        # Ghirapur) — game-wide, not per active player: last turn's combat
        # damage is stale for everyone once a new turn starts.
        self.state.combat_damage_to_players_this_turn.clear()
        # RULE 700.4 history ("unless a creature died under your control this
        # turn", Bontu the Glorified) — game-wide for the same reason.
        self.state.creatures_died_this_turn.clear()
        # Mana-potential tracking (`game/mana_potential.py`) — game-wide,
        # not `active.id`-only like `spells_cast_this_turn` above: a
        # non-active player can still tap mana at instant speed under
        # `interactive_priority` (Multiplayer), and "open + used = total
        # capacity accessed this turn" must hold for the turn now beginning
        # regardless of whose turn it is.
        for player in self.state.players:
            self.state.mana_produced_this_turn[player.id] = {}
        # PAR-10 (`static_conditions.py`'s `cast_instant_or_sorcery_this_
        # turn`) — game-wide for the same reason as `mana_produced_this_
        # turn` above: a non-active player's static condition must read
        # correctly too, not just the active player's own activation check.
        for player in self.state.players:
            self.state.cast_instant_or_sorcery_this_turn[player.id] = False
        # Same game-wide reset scope as the row above — Magebane Lizard's
        # own running per-player noncreature-spell count.
        for player in self.state.players:
            self.state.noncreature_spells_cast_this_turn[player.id] = 0
        # Veil of Summer-shaped "if an opponent has cast a blue or black
        # spell this turn" — same game-wide reset scope as the row above.
        for player in self.state.players:
            self.state.spell_colors_cast_this_turn[player.id] = set()
        # "Until your next turn, …" (RULE 611.2b) — a player-scoped effect
        # granted on someone's turn lapses the moment *that* player's next
        # turn begins, which is exactly now for `active`. Swept across every
        # player's `player_effects`, since the restricted player (Hope of
        # Ghirapur's target) generally isn't the one the duration is keyed to.
        for player in self.state.players:
            player.player_effects = [
                e for e in player.player_effects
                if getattr(e, "until_next_turn_of", None) != active.id
            ]
        # …and the same duration on a *permanent*-scoped replacement effect
        # (Jeska, Thrice Reborn's damage multiplier, which lives on the
        # targeted creature's own `replacement_effects` rather than on a
        # player).
        for obj in self.state.battlefield:
            if any(
                getattr(e, "until_next_turn_of", None) == active.id
                for e in obj.replacement_effects
            ):
                obj.replacement_effects = [
                    e for e in obj.replacement_effects
                    if getattr(e, "until_next_turn_of", None) != active.id
                ]
        # RULE 701.15a: goad lasts "until the next turn of the controller of
        # that spell or ability" — so the moment a player's turn begins, every
        # goad *they* applied ends. The same "until your next turn" duration
        # as the two sweeps above, keyed per-goader on the creature rather
        # than by an effect object, since goaded is a designation and not an
        # effect (701.15b). The static half (`_goaded_by_static`) is not swept
        # here: it is re-derived every recompute and lasts as long as its
        # source does.
        for obj in self.state.battlefield:
            obj.goaded_by.discard(active.id)
        # RULE 611.2b: "until your next turn" ends as that player's turn
        # begins — the one duration a `temp_*` field can't express, since
        # those are all cleared at the cleanup step of the turn they were
        # created in (`game/durations.py`).
        if durations.sweep(self.state, "turn_begin"):
            self.recompute_continuous_effects()
        self._clear_combat()
        # RULE 117.3a: the active player receives priority at the start of
        # their turn (harmless bookkeeping for solo play; the primitive an
        # interactive multiplayer loop drives via `pass_priority(player)`).
        self.give_priority(active)
        self.state.fire_event(
            GameEvent(EventType.TURN_BEGIN, player_id=active.id, turn=self.state.turn_number)
        )
    def run_turn(self) -> None:
        """Run one full turn: walk every step, giving priority where due."""
        self.begin_turn()
        for phase, step in default_turn_sequence().iter_steps():
            if self.state.game_over:
                return
            self._run_step(phase, step)
        self.state.fire_event(
            GameEvent(EventType.TURN_END, player_id=self.state.active_player.id)
        )
    def start(self) -> None:
        """Begin the game at turn 1, positioned before the first step.

        The next ``advance_step`` runs the untap step. Between advances a
        player can take actions (play a land, cast, attack); each action
        auto-resolves the stack (a session with no opponent has no one to
        hold priority), so a goldfish plays out one deliberate step at a
        time with full undo between them.
        """
        self._begin_turn_steps()
    def _begin_turn_steps(self) -> None:
        self.begin_turn()
        self._turn_steps = list(default_turn_sequence().iter_steps())
        self._cursor = 0
    @property
    def step_cursor(self) -> int:
        """How far through the current turn's steps we are (for snapshots)."""
        return self._cursor
    def resume_at(self, cursor: int) -> None:
        """Restore the stepping position after a state was swapped in (undo).

        The turn's step list is deterministic, so only the cursor needs to
        travel with a snapshot; this rebuilds the list and seeks to it.
        """
        self._turn_steps = list(default_turn_sequence().iter_steps())
        self._cursor = cursor
    def auto_play_step(self) -> None:
        """Auto-play the greedy goldfish line for the *current* step.

        Used by an interactive session's "auto-turn" so it can reuse the
        same develop-board / attack logic as ``run_goldfish_turn`` while
        still driving the step cursor (``advance_step``) rather than
        running a whole turn behind its back.
        """
        step = self.state.current_step
        if step == "main1":
            self._goldfish_develop_board()
            self.resolve_until_stable()
        elif step == "declare_attackers":
            self._goldfish_attack()
    def advance_step(self) -> Optional[tuple[str, str]]:
        """Run the next step, rolling over to the next turn when exhausted.

        Returns the ``(phase, step)`` just run, or ``None`` if the game is
        over. Turn-based actions (untap, draw, combat damage, cleanup) run
        as part of the step; the caller injects any player actions before
        the next advance.
        """
        if self.state.game_over:
            return None
        # RULE 500.4-adjacent: drain any "additional combat phase" request an
        # effect queued since the last advance (`ExtraCombatPhaseEffect`) —
        # done here, not where it's queued, since only `GameEngine` (not the
        # effect that requested it) can see `_turn_steps`/`_cursor`.
        while self.state.pending_extra_combats:
            self.insert_additional_combat_phase(self.state.pending_extra_combats.pop(0))
        if self.state.end_turn_requested:
            # RULE 500-adjacent "end the turn" (Day's Undoing) — the
            # reminder text's own "discard down to your maximum hand size.
            # Damage wears off, and 'this turn'/'until end of turn' effects
            # end" is exactly RULE 514.1/514.2, so it's the real cleanup
            # step's own body, not a re-derived copy of it (`RulesEngine.
            # end_the_turn` can't call this directly — no GameEngine
            # back-reference, the same reason `pending_extra_combats` is
            # queued rather than actioned from an effect). Then fast-
            # forward past every remaining step of the current turn, so
            # this same call rolls straight into `_begin_turn_steps` below
            # instead of running combat/postcombat/end for a turn the
            # effect already said is over.
            self.state.end_turn_requested = False
            self._step_cleanup()
            self._cursor = len(self._turn_steps)
        if self.state.current_step == "declare_attackers":
            self._enforce_attacks_if_able()
            self._enforce_goad_requirements()
            self._enforce_attack_alone_restrictions()
            self._fire_player_attacked_events()
            self._fire_attacks_alone_event()
        if self.state.current_step == "declare_blockers":
            self._enforce_block_requirements()
        if not self._turn_steps or self._cursor >= len(self._turn_steps):
            self.state.fire_event(
                GameEvent(EventType.TURN_END, player_id=self.state.active_player.id)
            )
            self._begin_turn_steps()
        phase, step = self._turn_steps[self._cursor]
        self._cursor += 1
        self._run_step(phase, step)
        return (phase.name, step.name)
    def _run_step(self, phase: GamePhase, step: GameStep) -> None:
        self.state.current_phase = phase.name
        self.state.current_step = step.name

        # Rule-override skips (docs/07 PART 8): "skip your untap step", etc.
        if self.rules.should_skip_step(self.state.active_player, step.name):
            return

        if step.name == "begin_combat":
            # RULE 603.4: "if it's the first combat phase of the turn" —
            # game-wide (not per-player), so an extra combat phase granted
            # mid-turn is correctly the *second* one regardless of who
            # controls the effect that grants it.
            self.state.combats_this_turn += 1
        if step.name == "draw":
            # MEC-32: reset right as this player's own draw step begins, so
            # `RulesEngine._single_draw` can tell "the step's own first
            # draw" apart from a later one within the same step (Notion
            # Thief/Chains of Mephistopheles's shared exemption clause).
            self.state.first_draw_done_this_step[self.state.active_player.id] = False
        self.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step.name, phase=phase.name))
        self._fire_delayed_triggers(step.name)
        # RULE 611: "until the beginning of the next end step" — swept as
        # that step opens, alongside the delayed triggers due there, since
        # both are "the next time we reach this step" durations.
        if step.name == "end" and durations.sweep(self.state, "end_step"):
            self.recompute_continuous_effects()
        self._execute_step_body(step)

        if not step.gives_priority:
            # RULE 117.3a: nobody receives priority during untap or cleanup.
            # Cleared rather than left pointing at whoever held it last, so
            # "is anybody able to act right now?" is answerable from the
            # state alone (`GameSession._advance_to_priority_window` runs
            # through exactly these steps on that basis).
            self.state.priority_player_index = None
            self.state.priority_passed.clear()
        else:
            # RULE 117.3a: (re-)grant priority to the active player as this
            # step's window opens.
            self.give_priority(self.state.active_player)
            # Turn-based actions can create triggers; resolve everything and
            # let priority pass around until the stack is empty (RULE 117).
            # Solo/goldfish auto-drains here. With `interactive_priority` the
            # triggers still go on the stack (so everyone can *see* what's
            # waiting and respond to it) but nothing resolves on its own —
            # each object comes off only when all players have passed in
            # succession, which is the session's job to drive.
            if self.interactive_priority:
                self.rules.put_triggers_on_stack()
            else:
                self.resolve_until_stable()

        # RULE 500.4: unused mana empties as the step ends.
        for player in self.state.players:
            player.mana_pool.empty()
        self.state.fire_event(GameEvent(EventType.STEP_END, step=step.name, phase=phase.name))
    def insert_additional_combat_phase(self, main_phase_too: bool = False) -> None:
        """RULE 500.4-adjacent "after this combat phase, there is an
        additional combat phase[, followed by an additional main phase]"
        (Combat Celebrant/Godo/Aurelia/Xenagos-shaped triggered abilities;
        ``main_phase_too`` covers World at War/Aggravated Assault's own
        activated-ability wording instead). No CR number of its own — this
        is the turn genuinely growing an extra phase, not a skip/replace —
        so it splices a fresh `GamePhase("combat", …)` (and, if asked, a
        fresh `postcombat_main`) straight into `_turn_steps`, the same
        mutable per-turn step list `advance_step`'s cursor already walks;
        `phases.default_turn_sequence`'s own docstring flagged this exact
        insertion as the reason that function returns a fresh instance
        every call.

        Inserted right after the *next* upcoming ``end_combat`` in the
        list (found from the current cursor onward — the combat phase
        that's still in progress when this fires, since the trigger
        resolves mid-combat), not at the raw cursor position itself,
        which would otherwise splice the new phase's steps *before* the
        current combat's own remaining declare-blockers/damage/end-combat
        steps and reorder them.

        A no-op outside the interactive step-cursor model (`start`/
        `advance_step` never called — `_turn_steps` still empty, `run_turn`'s
        own one-shot loop): no shipped card reaches extra-combat that way in
        this codebase, so nothing currently needs it, and inventing a second
        insertion path for an unreachable case isn't worth the surface.
        """
        steps = self._turn_steps
        if not steps:
            return
        insert_at = len(steps)
        for i in range(max(0, self._cursor - 1), len(steps)):
            if steps[i][1].name == "end_combat":
                insert_at = i + 1
                break
        new_combat = GamePhase(
            "combat",
            [
                GameStep("begin_combat", rule="507"),
                GameStep("declare_attackers", rule="508"),
                GameStep("declare_blockers", rule="509"),
                GameStep("combat_damage", rule="510"),
                GameStep("end_combat", rule="511"),
            ],
        )
        new_steps = [(new_combat, s) for s in new_combat.steps]
        if main_phase_too:
            new_main = GamePhase("postcombat_main", [GameStep("main2", rule="505")])
            new_steps.append((new_main, new_main.steps[0]))
        steps[insert_at:insert_at] = new_steps
    def _execute_step_body(self, step: GameStep) -> None:
        handler = getattr(self, f"_step_{step.name}", None)
        if handler is not None:
            handler()
    def _fire_delayed_triggers(self, step_name: str) -> None:
        """Place any delayed triggered abilities (RULE 603.7) due this step on
        the stack, and drop them (they fire exactly once).

        A `DelayedTrigger` is due when its ``step`` matches this step and its
        ``scope`` is satisfied: ``"controller"`` needs the active player to be
        the trigger's controller ("your next upkeep"), ``"any"`` fires at the
        very next such step regardless of whose turn it is ("the next end
        step"). Placed as ordinary ``ability`` stack items — resolved by the
        normal stack/priority drain that follows the step's `give_priority`.
        """
        if not self.state.delayed_triggers:
            return
        active_id = self.state.active_player.id

        def _step_matches(dt_step: str) -> bool:
            # "your next main phase" (Mana Drain) fires at whichever main step
            # comes first — precombat (main1) or postcombat (main2).
            if dt_step == "main":
                return step_name in ("main1", "main2")
            return dt_step == step_name

        due, remaining = [], []
        for dt in self.state.delayed_triggers:
            if (
                _step_matches(dt.step)
                and self.state.turn_number >= getattr(dt, "min_turn", 0)
                and (dt.scope != "controller" or dt.controller_id == active_id)
            ):
                due.append(dt)
            else:
                remaining.append(dt)
        self.state.delayed_triggers = remaining
        for dt in due:
            self.state.stack.append(
                StackItem(
                    kind="ability",
                    controller_id=dt.controller_id,
                    effects=dt.effects,
                    targets=dt.targets,
                    description=dt.description,
                    category="triggered_ability",
                )
            )
    def _step_untap(self) -> None:
        active = self.state.active_player
        # RULE 702.26a: "at the beginning of the untap step, before
        # performing any other turn-based actions", every phased-out
        # permanent this player controls phases back in. (No card in this
        # engine yet auto-phases an already-phased-in permanent *out* at
        # this point, so that half of 702.26a is deliberately not modeled —
        # every phase-out here comes from an explicit activated ability,
        # e.g. Robe of Stars' Astral Projection.) Reads `state.battlefield`
        # directly, not `permanents_controlled_by`, since that filters
        # phased-out objects out — exactly the ones this loop needs to find.
        for obj in self.state.battlefield:
            if obj.controller_id == active.id and obj.phased_out:
                obj.phased_out = False
        # RULE 502.3-adjacent (Winter Orb/Static Orb/Winter Moon): "players
        # can't untap more than N `<type>` during their untap steps" — a
        # flat, unscoped cap that applies to every player's untap step
        # identically, including each static's own controller. An empty
        # list means unrestricted (the overwhelmingly common case), so this
        # never changes anything for a board without one; an auto-pick
        # (first N matching permanents found) untaps up to each cap, the
        # same non-interactive MVP simplification `_sacrifice_candidate`'s
        # callers already make elsewhere. 2+ active caps are enforced
        # independently (each keeps its own running count), not merged.
        untap_caps = continuous.active_untap_caps(self.state)
        cap_counts = [0] * len(untap_caps)
        # RULE 502.3-adjacent (Stasis): "players skip their untap steps" is
        # unconditional and total — unlike `active_untap_caps`'s count limit,
        # nothing about the step happens at all (no bookkeeping either, the
        # same "whole step skipped" treatment `should_skip_step` gets, not
        # `has_no_untap_static`'s "just don't untap this one").
        skip_whole_step = continuous.all_untap_steps_skipped(self.state)
        for obj in self.state.permanents_controlled_by(active.id):
            if skip_whole_step or self.rules.should_skip_step(
                active, "untap_permanents"
            ) or continuous.has_no_untap_static(
                self.state, obj
            ):
                continue
            # RULE 702.19b: exert's one-time consequence — consumed and
            # cleared here, not a standing static like `has_no_untap_static`
            # above, so it only ever blocks the *next* untap step.
            capped_out = obj.skip_next_untap
            obj.skip_next_untap = False
            for i, cap in enumerate(untap_caps):
                if capped_out:
                    break
                if continuous.matches_untap_cap_filter(obj, cap) and cap_counts[i] >= cap["count"]:
                    capped_out = True
            if not capped_out:
                # RULE 502.3-adjacent: "This artifact doesn't untap during
                # your untap step." (Basalt Monolith/Grim Monolith/Mana
                # Vault) — a separate "{N}: Untap this artifact." activated
                # ability (or Mana Vault's upkeep trigger) is unaffected,
                # it's a different code path (an ordinary `untap` effect).
                obj.untap()
                for i, cap in enumerate(untap_caps):
                    if continuous.matches_untap_cap_filter(obj, cap):
                        cap_counts[i] += 1
            # Controlled since the turn began → no longer summoning sick.
            obj.summoning_sick = False
            # RULE 606.3: a new loyalty ability may be activated this turn.
            obj.activated_loyalty_this_turn = False
            # RULE 500.4-adjacent: a `GraveyardCastPermissionEffect`'s "once
            # during each of your turns" restriction (Lurrus-shaped) resets
            # the same way.
            obj.graveyard_casts_this_turn = 0
            # ENG-27: "if you haven't added mana with this ability this
            # turn" (Carpet of Flowers) resets the same way too.
            obj.added_mana_with_ability_this_turn = False
            # RULE 702.19a: a new turn means "hasn't been exerted this
            # turn" is true again.
            obj.exerted_this_turn = False
            # MEC-29/RULE 702.122c: "crewed by ~ this turn" resets the same
            # way — a new turn means no creature has crewed this permanent
            # yet.
            obj.crewed_by_ids = []
        self.state.fire_event(GameEvent(EventType.UNTAP, player_id=active.id))
        # RULE 731.2: "as the second part of the untap step", check whether
        # day/night should flip based on last turn's spell count.
        self.rules.apply_day_night_turn_check()
    def _step_draw(self) -> None:
        # RULE 103.8a: in a **two-player** game the player who plays first
        # skips the draw step of their first turn. RULE 103.8c: "in all
        # other multiplayer games, no player skips the draw step of their
        # first turn" — so at a pod of three or four *nobody* skips it,
        # including the starting player. Gated on exactly two seats for
        # that reason; it used to read `> 1`, which wrongly carried the
        # two-player rule into every pod.
        #
        # The goldfish dummy counts as the second seat here: a solo game is
        # modeling a two-player game against a passive opponent, and its
        # setup screen is what clears `skip_first_draw` to put the human on
        # the draw instead.
        skip_draw = (
            self.state.turn_number == 1
            and len(self.state.players) == 2
            and self.state.skip_first_draw
        )
        if not skip_draw:
            self.rules.draw(self.state.active_player, 1)
    def _step_main1(self) -> None:
        # RULE 714.3c: as a player's precombat main phase begins, they put a
        # lore counter on each Saga they control with one or more chapter
        # abilities — a turn-based action, not a trigger off the draw step
        # (which is where this lived before it was fixed to match the CR).
        self.rules.advance_sagas(self.state.active_player)
        # RULE 904.7: "at the beginning of the archenemy's precombat main
        # phase, before the active player gets priority, that player sets the
        # top card of their scheme deck in motion" — a turn-based action like
        # the Saga counter above, not a triggered ability, so it belongs here
        # rather than in the trigger machinery. Silent in every non-Archenemy
        # game: nobody has a scheme deck.
        active = self.state.active_player
        if self.state.archenemy_id == active.id and active.scheme_deck:
            self.rules.set_scheme_in_motion(active)
    def _step_combat_damage(self) -> None:
        """Assign and deal combat damage (RULE 510), honouring combat keywords.

        First/double strike split this into two damage steps (RULE 702.7e /
        702.4b): when any combatant has either, first-strike damage is dealt
        and state-based actions checked — so a first-striker can kill a blocker
        before it strikes back — then the regular step runs, where double
        strikers deal a second time and ordinary creatures deal their only
        damage. Within a step: protection prevents damage from a source of the
        named quality (RULE 702.16c), deathtouch makes any damage lethal
        (702.2b), trample spills the excess over lethal onto the defender
        (702.19), and lifelink gains its controller that much life (702.15b).
        Damage in a step is gathered first, then applied together so it is
        simultaneous (marked, then one SBA pass — RULE 704.5g).
        """
        if self._combat_has_first_strikers():
            self._deal_combat_damage_step(first_strike_step=True)
            self.rules.check_state_based_actions()
        self._deal_combat_damage_step(first_strike_step=False)
        self.rules.check_state_based_actions()
    def _step_end_combat(self) -> None:
        # RULE 511.3: creatures are removed from combat as it ends.
        self._clear_combat()
        # …and RULE 611's combat-scoped continuous effects end with it
        # ("target creature gains flying until end of combat"), which is
        # strictly earlier than the cleanup step every ``temp_*`` grant waits
        # for (`game/durations.py`).
        if durations.sweep(self.state, "end_of_combat"):
            self.recompute_continuous_effects()
    def _step_cleanup(self) -> None:
        active = self.state.active_player
        # RULE 514.1: discard down to maximum hand size — unless a standing
        # "no maximum hand size" static (RULE 402.2, `continuous.
        # has_no_maximum_hand_size`) exempts this player.
        if not continuous.has_no_maximum_hand_size(self.state, active):
            excess = len(active.hand) - MAX_HAND_SIZE
            if excess > 0:
                self.rules.discard(active, excess)
        # RULE 514.2: remove marked damage and end "until end of turn" effects
        # (pump P/T bonuses, temporary keyword grants, and a "becomes a copy
        # of target creature until end of turn" activation — Cursed Mirror).
        from .. import copy_mechanics

        ended_effects = False
        for obj in self.state.permanents():
            obj.damage_marked = 0
            if obj.temp_power or obj.temp_toughness or obj.temp_keywords:
                obj.temp_power = 0
                obj.temp_toughness = 0
                obj.temp_keywords.clear()
                obj.temp_effects.clear()
                ended_effects = True
            if obj.temp_unblockable:
                obj.temp_unblockable = False
                ended_effects = True
            if obj.temp_cant_block:
                obj.temp_cant_block = False
                ended_effects = True
            if obj.temp_combat_restrictions:
                obj.temp_combat_restrictions.clear()
                ended_effects = True
            if obj.temp_protections:
                obj.temp_protections.clear()
                ended_effects = True
            if obj.temp_granted_activated_abilities:
                obj.temp_granted_activated_abilities.clear()
                ended_effects = True
            if obj._copy_until_eot_base is not None:
                copy_mechanics.restore_face(obj, obj._copy_until_eot_base)
                obj._copy_until_eot_base = None
                ended_effects = True
            # RULE 108.4-adjacent "gain control ... until end of turn"
            # (Zealous Conscripts/Coercive Recruiter, `GainControlUntilEnd
            # OfTurnEffect`) — hand control back to the original controller
            # at the next cleanup, regardless of whose turn it is (matching
            # "until end of turn", not "until your next turn").
            if obj.control_change_until_eot is not None:
                obj.controller_id = obj.control_change_until_eot
                obj.control_change_until_eot = None
                ended_effects = True
            # RULE 701.16a: an unused regeneration shield lasts only "that
            # turn" — sweep it here rather than only on consumption
            # (`RulesEngine.regenerate`'s own removal handles the used case).
            if any(getattr(e, "regeneration_shield", False) for e in obj.replacement_effects):
                obj.replacement_effects = [
                    e for e in obj.replacement_effects if not getattr(e, "regeneration_shield", False)
                ]
            # RULE 514.2 analogue for a permanent-targeted damage-prevention
            # shield (`RulesEngine.prevent_damage_to_target`, PAR-15) — the
            # object-scoped sibling of the `player.player_effects` sweep
            # below, since "prevent the next N damage ... to any number of
            # targets" can allot a share to a creature, not just a player.
            if any(getattr(e, "damage_prevention_shield", False) for e in obj.replacement_effects):
                obj.replacement_effects = [
                    e for e in obj.replacement_effects if not getattr(e, "damage_prevention_shield", False)
                ]
        # RULE 514.2 again, for the RULE 611 floating statics: "until end of
        # turn" ends here too, in the same window as every ``temp_*`` field
        # above — the difference is only *where* the effect was stored, not
        # when it lapses (`game/durations.py`).
        if durations.sweep(self.state, "cleanup"):
            ended_effects = True
        if ended_effects:
            self.recompute_continuous_effects()  # re-derive P/T sans the pumps
        # RULE 514.2 analogue: an unused (or partially-spent) turn-scoped
        # damage-prevention shield (RULE 615, Riot Control/Thought Lash —
        # `RulesEngine.prevent_damage_to_player`) also lasts only "this
        # turn" — sweep it here rather than only on full consumption,
        # mirroring the regeneration-shield sweep above but on
        # `Player.player_effects` instead of a permanent's own.
        for player in self.state.players:
            if any(getattr(e, "damage_prevention_shield", False) for e in player.player_effects):
                player.player_effects = [
                    e for e in player.player_effects
                    if not getattr(e, "damage_prevention_shield", False)
                ]
            # Same "this turn" expiry (RULE 119.3/611.2a), for
            # `RulesEngine.prevent_life_gain_this_turn`'s (Roiling Vortex)
            # own player-effect shield.
            if any(getattr(e, "life_gain_prevention_shield", False) for e in player.player_effects):
                player.player_effects = [
                    e for e in player.player_effects
                    if not getattr(e, "life_gain_prevention_shield", False)
                ]
            # Same "this turn" expiry again (RULE 616, MEC-30), for
            # `RulesEngine.grant_damage_multiplier_this_turn`'s (Insult //
            # Injury/Isengard Unleashed) own player-effect grant — a
            # dedicated flag rather than `damage_prevention_shield`, since
            # this isn't a prevention effect and must stay untouched by
            # `damage_prevention_disabled`'s filter below.
            if any(getattr(e, "damage_multiplier_grant", False) for e in player.player_effects):
                player.player_effects = [
                    e for e in player.player_effects
                    if not getattr(e, "damage_multiplier_grant", False)
                ]
        # RULE 615 (MEC-30): "Damage can't be prevented this turn." also
        # lapses here, the same window every other "this turn" flag clears.
        self.state.damage_prevention_disabled = False
        self._clear_combat()
        # RULE 601.3b analogue: a temporary "play until end of your next
        # turn" permission (Light Up the Stage-shaped impulsive draw) lapses
        # at *its own holder's* next-turn cleanup — not simply the very next
        # cleanup in turn order, which (RULE 500.1: every player's turn
        # increments turn_number) is usually an opponent's turn, cutting the
        # window a full turn short and to the wrong player's clock in
        # anything but a 1-player game. A same-turn-only entry (Ragavan,
        # Nimble Pilferer/Mnemonic Betrayal's own shorter printed window,
        # `temp_play_permission_same_turn_only`) has no such holder-turn
        # wait: it never survives past the very first cleanup after it was
        # granted, whoever's turn that is.
        active_id = self.state.active_player.id
        same_turn_only = self.state.temp_play_permission_same_turn_only

        def _permission_still_active(instance_id: int, granted_turn: int) -> bool:
            if instance_id in same_turn_only:
                return False
            holder_id = self.state.temp_play_permission_player.get(instance_id)
            return not (
                holder_id is not None
                and active_id == holder_id
                and self.state.turn_number > granted_turn
            )

        self.state.temp_play_permissions = {
            iid: turn for iid, turn in self.state.temp_play_permissions.items()
            if _permission_still_active(iid, turn)
        }
        self.state.temp_play_permission_same_turn_only &= set(self.state.temp_play_permissions)
        self.state.temp_play_permission_source = {
            iid: name for iid, name in self.state.temp_play_permission_source.items()
            if iid in self.state.temp_play_permissions
        }
        self.state.temp_play_permission_player = {
            iid: pid for iid, pid in self.state.temp_play_permission_player.items()
            if iid in self.state.temp_play_permissions
        }
        self.state.mana_wildcard_permission = {
            iid: kind for iid, kind in self.state.mana_wildcard_permission.items()
            if iid in self.state.temp_play_permissions
        }
        self.state.free_cast_instance_ids = {
            iid for iid in self.state.free_cast_instance_ids
            if iid in self.state.temp_play_permissions
        }
        # RULE 514.2: MEC-24's targeted "gains flashback until end of turn"
        # grant is a flat per-turn expiry (unlike `temp_play_permissions`'
        # own "until your next turn" survival above) — cleared unconditionally.
        if self.state.temp_flashback_grants:
            self.state.temp_flashback_grants = {}
    def resolve_until_stable(self) -> None:
        """Resolve triggers + the stack until empty, stable, or blocked.

        Models an all-players-pass priority window with no responses: put
        fired triggers on the stack, resolve the top, repeat; check SBAs
        throughout (RULE 704.3). Stops early if a resolving effect needs a
        player choice (`state.pending_choice`, e.g. a library search) — the
        session surfaces it and resumes via `resolve_pending_choice`. When
        that choice is answered, any effects the same resolution still owed
        (`state.deferred_effects`) finish before the stack moves on — see
        `RulesEngine.resume_deferred_effects`.
        """
        for _ in range(_MAX_RESOLUTIONS):
            self.rules.check_state_based_actions()
            if self.state.game_over:
                return
            if self.state.pending_choice:
                return  # await a player decision before resolving further
            if self.rules.resume_deferred_effects():
                # RULE 608.2: a resolution that stopped mid-list on an
                # interactive choice finishes here, *before* anything else
                # on the stack — its remaining effects are still part of
                # that same, still-resolving object.
                continue
            self.rules.put_triggers_on_stack()
            if self.state.pending_choice:
                # `put_triggers_on_stack` itself just opened one (RULE
                # 603.3c's own target/mode/"you may" choice for a trigger
                # it's still placing) — stop *now*, before falling into the
                # stack-resolution branch below. Otherwise a still-unresolved
                # spell already sitting on the stack (Nether Void-shaped:
                # "whenever a player casts a spell, counter it unless…",
                # where the counter trigger's own target is that same spell)
                # would resolve for real while the player is still supposed
                # to be choosing the trigger's target — the triggered
                # ability that's *supposed* to counter it hasn't even been
                # placed above it yet.
                return
            if self.state.stack:
                self.rules.resolve_top_of_stack()
                continue
            if not self.rules.pending_triggers:
                return
        raise RuntimeError("stack failed to stabilize (possible effect loop)")
    def pass_priority(self, player: Optional[Player] = None) -> bool:
        """Pass priority once: resolve the top of the stack (RULE 117/608).

        Called with no ``player`` (solo/goldfish): "everyone passes"
        collapses to resolving the top object immediately, as before —
        every existing caller keeps working unchanged.

        Called *with* a ``player`` (interactive multiplayer, RULE 117.3-4):
        only resolves once every living player has passed in succession.
        Raises `ValueError` if ``player`` doesn't currently hold priority;
        otherwise records the pass and, if players remain who haven't passed
        yet, hands priority to the next one (APNAP) and returns ``False``
        without resolving anything — the real mechanic that lets a
        non-active player respond (cast an instant, activate an ability)
        before the stack moves. Returns whether anything resolved.
        """
        self.rules.check_state_based_actions()
        if self.state.game_over or self.state.pending_choice:
            return False

        if player is not None:
            holder = self.state.priority_player
            if holder is not None and player is not holder:
                raise ValueError(f"{player.id} does not have priority")
            self.state.priority_passed.add(player.id)
            living_ids = {p.id for p in self.state.living_players()}
            if not living_ids <= self.state.priority_passed:
                self._advance_priority()
                return False

        self.rules.put_triggers_on_stack()
        if self.state.stack:
            self.rules.resolve_top_of_stack()
            self.rules.check_state_based_actions()
            # RULE 117.5: before any player can receive priority again,
            # state-based actions are performed and triggered abilities are
            # put on the stack. Without this second call, a trigger fired by
            # what just resolved (e.g. Sigarda's Aid's "whenever an
            # Equipment you control enters…") sits in `rules.pending_triggers`
            # with an empty `state.stack` and no `pending_choice` — nothing
            # in the view hints that anything is owed, so it's only placed
            # (and its own target choice opened) on some later, unrelated
            # `pass_priority` call, if ever. `resolve_until_stable` already
            # loops for exactly this reason; a single `pass_priority` call
            # must still finish this part of the cycle before returning.
            self.rules.put_triggers_on_stack()
            # RULE 117.3b: after anything resolves, priority resets to the
            # active player and everyone gets a fresh chance to act.
            self.give_priority(self.state.active_player)
            return True
        self.state.priority_passed.clear()
        return False
    def give_priority(self, player: Player) -> None:
        """Grant ``player`` priority and clear who has passed (RULE 117.3b).

        Called at the start of each priority window (a new step, or after
        something resolves) and whenever a player takes a real action —
        acting implicitly reclaims priority and invalidates any prior passes
        since the game state just changed (RULE 117.3c).
        """
        self.state.priority_player_index = self.state.players.index(player)
        self.state.priority_passed.clear()
    def _advance_priority(self) -> None:
        """Move priority to the next living player in turn order (APNAP)."""
        start = self.state.priority_player_index
        if start is None:
            start = self.state.active_player_index
        count = len(self.state.players)
        for step in range(1, count + 1):
            index = (start + step) % count
            if not self.state.players[index].has_lost:
                self.state.priority_player_index = index
                return
    def resolve_pending_choice(self, answer: Any) -> None:
        """Answer whatever choice is pending, then keep resolving the stack.

        ``answer`` is the chosen option's ``id`` (a string like ``"cast"`` /
        ``"hand"`` / ``"decline"`` or a card's instance id as a string), or —
        for backward compatibility — a bare ``int`` instance id / ``None`` to
        decline. Dispatches on the choice ``kind`` so search, cascade and
        discover share one choose/decline path from the session and UI.
        """
        choice = self.state.pending_choice
        kind = choice.get("kind") if choice else None
        declined = answer is None or answer == "decline"

        if kind == "cascade":
            self.rules.resolve_cascade_choice(cast=(answer == "cast"))
        elif kind == "discover":
            # Two positive options: cast (default) or take to hand.
            self.rules.resolve_discover_choice(to_hand=(answer == "hand"))
        elif kind == "order_triggers":
            # RULE 603.3b: the option id is the index of the trigger to place next.
            index = None if declined else int(answer)
            self.rules.resolve_trigger_order_choice(index)
        elif kind == "trigger_target":
            # RULE 115/603.3c: the option id is a permanent's instance id or a
            # player's id (not always int-castable, unlike the other kinds).
            self.rules.resolve_trigger_target_choice(None if declined else str(answer))
        elif kind == "trigger_target_multi":
            # RULE 115.1/603.3c generalized: a trigger with 2+ *different*
            # targeting effects — one of these fires per effect, in turn
            # (`_continue_trigger_multi_target`), same option shape as
            # "trigger_target" above.
            self.rules.resolve_trigger_target_multi_choice(None if declined else str(answer))
        elif kind == "trigger_mode":
            # RULE 700.2: the option id is a mode's index, or "both" (700.2e)
            # — a mandatory choice, so a decline still resolves the first mode
            # rather than dropping it (`resolve_trigger_mode_choice` defaults
            # an unrecognized/missing answer the same way).
            self.rules.resolve_trigger_mode_choice(None if declined else str(answer))
        elif kind == "opening_hand_battlefield":
            # RULE 103.6a: "you may begin the game with it on the
            # battlefield" (the Leyline cycle) — "battlefield" moves the
            # card there straight from the opening hand, anything else
            # leaves it in hand.
            self.rules.resolve_opening_hand_battlefield_choice(
                None if declined else str(answer)
            )
        elif kind == "land_tapped":
            # RULE 614.1: a shock land's "pay life to stay untapped" choice.
            self.rules.resolve_land_tapped_choice(None if declined else str(answer))
        elif kind == "land_tapped_bonus":
            # RULE 614.1's "you may have this land enter tapped. If you do,
            # <bonus>." (Mariposa Military Base) — the mirror-image choice:
            # untapped by default, tap it for the bonus instead.
            self.rules.resolve_land_tapped_bonus_choice(None if declined else str(answer))
        elif kind == "land_tapped_reveal":
            # RULE 614.1's "reveal land" cycle: reveal a matching card from
            # hand to stay untapped, only offered when one is actually held.
            self.rules.resolve_land_tapped_reveal_choice(None if declined else str(answer))
        elif kind == "choose_objects":
            # The general "which one?" chooser (`request_choose_objects`) —
            # Cloudstone Curio's bounce, Tangle Wire's tap, Tevesh Szat's
            # and Professor Onyx's sacrifices, Deadeye Navigator's Soulbond
            # partner, a library reorder. Declining is only legal when the
            # effect said "you may"/"up to", which the choice records.
            self.rules.resolve_choose_objects_choice(None if declined else int(answer))
        elif kind == "choose_type_for_source":
            # `RulesEngine.request_choose_creature_type_grant` — a
            # triggered ability's own resolve-time "choose a creature
            # type" (Selfless Safewright-shaped), distinct from RULE
            # 601.2b's as-it-enters `choose_creature_type` above. Mandatory
            # (no decline offered), same "default to the first option"
            # treatment `resolve_enter_choice` gives a missing answer.
            self.rules.resolve_choose_type_for_source_choice(None if declined else str(answer))
        elif kind == "choose_player_for_source":
            # `RulesEngine.request_choose_player` (Stuffy Doll-shaped "as
            # ~ enters, choose a player") — mandatory, same "default to
            # the first option" treatment as the type-choice sibling above.
            self.rules.resolve_choose_player_choice(None if declined else str(answer))
        elif kind == "ring_bearer":
            # RULE 701.52a: "you choose a creature you control as your
            # Ring-bearer" — mandatory (the choice only opens with 2+
            # candidates), so a decline isn't offered or accepted.
            self.rules.resolve_ring_bearer_choice(int(answer))
        elif kind == "name_card":
            # RULE 701's naming action (Demonic Consultation) — the one
            # choice whose answer space isn't enumerable, so the raw string
            # is passed straight through rather than matched against the
            # offered options (which are only suggestions).
            self.rules.resolve_name_card_choice(None if declined else str(answer))
        elif kind == "look_top_pay_life":
            # Lim-Dûl's Vault's open-ended "as many times as you choose"
            # loop — "again" pays the life and re-opens; anything else stops.
            self.rules.resolve_look_top_pay_life_loop_choice(
                None if declined else str(answer)
            )
        elif kind == "reveal_top_hand_lose_life_loop":
            # Ad Nauseam's own open-ended "you may repeat this process any
            # number of times" — "again" reveals/hands/loses-life and
            # re-opens; anything else stops.
            self.rules.resolve_reveal_top_hand_lose_life_loop_choice(
                None if declined else str(answer)
            )
        elif kind == "pay_cost_then":
            # RULE 118.3: "you may pay <cost>. If you do, <effect>." (Mana
            # Vault, Wandering Archaic) — "pay" charges the cost and runs
            # the follow-up; anything else runs the "if you don't" branch.
            self.rules.resolve_pay_cost_then_choice(None if declined else str(answer))
        elif kind == "pay_life_or_return_to_library":
            # Sylvan Library (MEC-40): "…pay 4 life or put the card on top
            # of your library." — a mandatory per-card either/or, not a
            # "may" (declining maps to "return", the same treatment a
            # missing/invalid answer gets).
            self.rules.resolve_pay_life_or_return_choice(str(answer) if not declined else "return")
        elif kind == "all_decline_or":
            # RULE 118.3-adjacent multi-player tax: "Any player may pay
            # <cost>. If no one does, <effect>." (Rhystic Circle, MEC-30) —
            # "pay" cancels the whole sweep; anything else moves on to the
            # next player.
            self.rules.resolve_all_decline_or_choice(None if declined else str(answer))
        elif kind == "pay_energy_then":
            # RULE 122: "you may pay {E}{E}. If you do, <effect>." (Aether
            # Chaser) — "pay" spends the energy and resolves the follow-up,
            # anything else declines.
            self.rules.resolve_pay_energy_then_choice(None if declined else str(answer))
        elif kind == "add_mana_any_color":
            # RULE 106.4: which color to add — a mandatory choice, so a
            # decline still resolves to a color rather than adding nothing
            # (`resolve_add_mana_any_color_choice` defaults an
            # unrecognized/missing answer the same way trigger_mode does).
            self.rules.resolve_add_mana_any_color_choice(None if declined else str(answer))
        elif kind == "grant_protection_color":
            # RULE 702.16: which colour (or colorless) to gain protection from
            # — a mandatory choice, defaulted like add_mana_any_color.
            self.rules.resolve_grant_protection_choice(None if declined else str(answer))
        elif kind == "replacement_order":
            # RULE 616.1: the option id is the index of the replacement
            # effect to apply next.
            index = None if declined else int(answer)
            self.rules.resolve_replacement_order_choice(index)
        elif kind == "enter_as_copy":
            # RULE 614.1c/614.12: the option id is a permanent's instance id,
            # or decline to enter as itself.
            self.rules.resolve_enter_as_copy_choice(None if declined else str(answer))
        elif kind == "enter_or_graveyard":
            # RULE 614.12: the option id is a land card's instance id, or
            # decline to send the permanent straight to the graveyard
            # instead of letting it enter (Mox Diamond).
            self.rules.resolve_enter_or_graveyard_choice(None if declined else str(answer))
        elif kind == "tainted_pact":
            # Tainted Pact: "take" the just-exiled card, or "continue"
            # digging further at the risk of a duplicate name. A decline/
            # missing answer defaults to "take" (the safe option).
            self.rules.resolve_tainted_pact_choice("take" if declined else str(answer))
        elif kind == "transmute_sacrifice":
            # Transmute Artifact stage 1: which of the player's own
            # artifacts to sacrifice — the option id is its instance id.
            self.rules.resolve_transmute_sacrifice_choice(None if declined else str(answer))
        elif kind == "transmute_search":
            # Transmute Artifact stage 2: which artifact card was found (or
            # decline) — the option id is a library card's instance id.
            self.rules.resolve_transmute_search_choice(None if declined else str(answer))
        elif kind == "transmute_pay_x":
            # Transmute Artifact stage 3: pay the mana-value difference, or
            # let the found card go to its owner's graveyard instead.
            self.rules.resolve_transmute_pay_x_choice(None if declined else str(answer))
        elif kind in (
            "choose_creature_type", "choose_color", "choose_named_mode", "choose_basic_land_type",
            "choose_card_name",
        ):
            # RULE 601.2b(-adjacent): a mandatory pick (no "decline" option
            # is ever offered) — the option id is a creature-type name, a
            # WUBRG colour letter, (``choose_named_mode``) a lowercase mode
            # slug (Struggle for Project Purity's "choose Brotherhood or
            # Enclave"), (``choose_basic_land_type``, PAR-4) a basic land
            # type name, or (``choose_card_name``, MEC-12) an arbitrary card
            # name — `resolve_enter_choice` defaults an unrecognized/missing
            # answer to the first offered option for every kind except the
            # last, whose free-text answer is passed straight through.
            self.rules.resolve_enter_choice(None if declined else str(answer))
        elif kind == "choose_protector":
            # RULE 310.8a/310.11a: which player protects an entering battle —
            # a mandatory pick (no "decline" is offered), the option id being
            # a player id; `resolve_protector_choice` defaults an
            # unrecognized/missing answer to the first eligible player, same
            # treatment as choose_creature_type above.
            self.rules.resolve_protector_choice(None if declined else str(answer))
        elif kind == "read_ahead":
            # RULE 702.155/714.3b: a mandatory pick (no "decline" option is
            # ever offered) — the option id is the chosen lore-counter count
            # as a string; `resolve_read_ahead_choice` defaults an
            # unrecognized/missing answer to 1 (no read-ahead), same
            # treatment as choose_creature_type.
            self.rules.resolve_read_ahead_choice(None if declined else str(answer))
        elif kind == "counter_unless_pays":
            # RULE 601: "pay" saves the target spell, anything else counters it.
            self.rules.resolve_counter_unless_pays_choice(None if declined else str(answer))
        elif kind == "change_target":
            # RULE 115.4/601.2c: Misdirection/Deflecting Swat's own
            # retarget — the option id is the new target's instance id or
            # player id, or a decline (only offered when optional) leaving
            # the spell's existing target untouched.
            self.rules.resolve_change_target_choice(None if declined else str(answer))
        elif kind == "ward":
            # RULE 702.21: "pay" saves the caster's spell/ability, anything
            # else counters it — the caster decides, not the target's
            # controller (unlike counter_unless_pays).
            self.rules.resolve_ward_choice(None if declined else str(answer))
        elif kind == "sacrifice_unless_pay":
            # RULE 701.17: "sacrifice ~ unless you pay <cost>" (Arcades
            # Sabboth/Breeding Pit) — "pay" keeps the permanent, anything
            # else sacrifices it. Same pay-or-lose-it shape as ward.
            self.rules.resolve_sacrifice_unless_pay_choice(
                None if declined else str(answer)
            )
        elif kind == "commander_zone":
            # RULE 903.9a/9b: "command" moves the commander to the command
            # zone instead of wherever it landed/was headed; anything else
            # leaves it there.
            self.rules.resolve_commander_zone_choice(None if declined else str(answer))
        elif kind == "choose_dungeon":
            # RULE 309.2a: which dungeon card to bring in from outside the
            # game — mandatory (venturing always enters one), so a decline
            # still picks rather than aborting the venture.
            self.rules.resolve_choose_dungeon_choice(None if declined else str(answer))
        elif kind == "venture_room":
            # RULE 701.49b: which arrow to follow out of the current room —
            # mandatory for the same reason; the option id is the room name.
            self.rules.resolve_venture_room_choice(None if declined else str(answer))
        elif kind == "scry":
            # RULE 701.18: the option id is one of the looked-at cards
            # (bottom it, or — in the ordering phase — place it next from
            # the top). Declining means "leave what's left as it is" in
            # both phases; see `RulesEngine._LOOK_TOP_KINDS`.
            self.rules.resolve_scry_choice(None if declined else int(answer))
        elif kind == "surveil":
            # RULE 701.31: the same decision as scry with the graveyard
            # where scry has the bottom of the library.
            self.rules.resolve_surveil_choice(None if declined else int(answer))
        elif kind == "intuition_search":
            # Intuition's own first phase: the searching player picks each
            # card one at a time — mandatory unless ``search_optional``
            # (MEC-41, Gifts Ungiven's "up to four") offers a real decline.
            self.rules.resolve_intuition_search_choice(None if declined else int(answer))
        elif kind == "intuition_choose":
            # Intuition's own second phase: the *targeted opponent* (not
            # the searcher) picks which revealed card goes to the
            # searcher's hand — also mandatory ("chooses one").
            self.rules.resolve_intuition_choose_choice(int(answer))
        elif kind == "look_top_select":
            # RULE 701.19-adjacent "look at top N, put M into hand, rest
            # <destination>" (Anticipate-shaped) — the option id is one of
            # the looked-at cards (select it for hand, or — in the
            # ordering phase — place it next); decline only appears in the
            # ordering phase, see `RulesEngine._look_top_select_choice`.
            self.rules.resolve_look_top_select_choice(None if declined else int(answer))
        elif kind == "manifest_dread":
            # RULE 701.40a: which of the two looked-at cards is manifested
            # face down (the other is milled) — mandatory, so a decline
            # still manifests the top card rather than neither.
            self.rules.resolve_manifest_dread_choice(None if declined else int(answer))
        elif kind == "impulsive_look":
            # Grisly Salvage/Commune with the Gods-shaped: the option id is
            # one of the *peeled* cards' instance ids, or decline.
            instance_id = None if declined else int(answer)
            self.rules.resolve_impulsive_look_choice(instance_id)
        elif kind == "remove_counters_amount":
            # RULE 122: "remove up to N counters from target permanent" —
            # the option id is the chosen amount (a string digit); a
            # decline/missing answer defaults to 0 (remove nothing), unlike
            # a mandatory pick, since 0 is itself always a legal answer here.
            self.rules.resolve_remove_counters_amount_choice(None if declined else str(answer))
        elif kind == "remove_counters_kind":
            # The follow-up "which counter kind" choice, only opened when
            # the target carries 2+ kinds — a mandatory pick (no "decline"
            # option is ever offered), defaulted like choose_creature_type.
            self.rules.resolve_remove_counters_kind_choice(None if declined else str(answer))
        else:  # search: a card's instance id, or decline
            instance_id = None if declined else int(answer)
            self.rules.resolve_search_choice(instance_id)
        self.resolve_until_stable()
    def set_skip_untap(self, player: Player, obj: GameObject, value: bool) -> None:
        """Toggle RULE 502.1's "you may choose not to untap ~ during your
        untap step" permission on ``obj`` (Rubinia Soulsinger/Hivis of the
        Scale/The Pandorica-shaped).

        The engine has no mid-untap-step pause to ask fresh every turn (the
        rest of `_step_untap` runs straight through), so this is a standing
        toggle the controller flips any time rather than a per-turn prompt —
        it stays sticky (`GameObject.skip_untap`) until changed again, and
        `continuous.has_no_untap_static` only honours it while ``obj``
        actually carries the underlying `"no_untap_optional"` grant.
        """
        if obj.controller_id != player.id:
            raise ValueError(f"{player.id} doesn't control {obj.name}")
        if not continuous.has_optional_no_untap_permission(self.state, obj):
            raise ValueError(f"{obj.name} has no 'you may choose not to untap' permission")
        obj.skip_untap = value
