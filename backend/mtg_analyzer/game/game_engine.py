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

from contextlib import contextmanager
from typing import Any, Optional

from ..models.card import Card
from ..models.events import EventType, GameEvent
from ..models.game_object import GameObject, Zone
from ..models.game_state import GameState, StackItem
from ..models.mana_cost import ManaCost
from ..models.player import Player
from . import combat, continuous
from .costs import DISCARD_HAND, PAY_LIFE_X, ActivationCost
from .effects import ActivatedAbility
from .mana_abilities import mana_options_for, option_label
from .phases import GamePhase, GameStep, default_turn_sequence
from .rules_engine import RulesEngine
from .targeting import (
    all_requirements_satisfiable,
    legal_targets,
    requirements_with_targets,
    spell_target_specs,
)

#: Maximum hand size enforced at cleanup (RULE 402.2 / 514.1).
MAX_HAND_SIZE = 7

#: Safety cap so a misbehaving trigger/replacement can't hang the loop.
_MAX_RESOLUTIONS = 1000


class GameEngine:
    """Drives a `GameState` through turns using a `RulesEngine`."""

    def __init__(self, state: GameState) -> None:
        self.state = state
        self.rules = RulesEngine(state)
        #: Cursor for interactive step-by-step play (see ``start`` /
        #: ``advance_step``): the current turn's ``(phase, step)`` list and
        #: how far through it we are. ``run_turn``/``run_goldfish_turn`` do
        #: not use these — they run a whole turn at once.
        self._turn_steps: list = []
        self._cursor = 0

    @property
    def attackers(self) -> list[GameObject]:
        """Creatures currently declared as attackers (RULE 508).

        Derived from the battlefield rather than stored on the engine, so
        combat survives a rewind: a `GameSession` restores by wrapping a
        *fresh* engine around a cloned `GameState`, which carries each
        object's ``attacking`` flag with it — an engine-side list would be
        lost.
        """
        return [obj for obj in self.state.battlefield if obj.attacking]

    def _clear_combat(self) -> None:
        """End combat: no creature is attacking or blocking (RULE 511.3)."""
        for obj in self.state.battlefield:
            obj.attacking = False
            obj.combat_defender = None
            obj.blocking = None
            obj.blocked_by = []
            obj.dealt_deathtouch_damage = False

    # ------------------------------------------------------------------
    # Game setup
    # ------------------------------------------------------------------

    @classmethod
    def new_game(
        cls,
        player_libraries: list[tuple[str, str, list[Card]]],
        starting_life: int = 40,
        starting_hand: int = 7,
    ) -> "GameEngine":
        """Build a game from ``(player_id, name, library_cards)`` tuples.

        Each player's library is built from the given cards (top of the
        library is the end of the list), and an opening hand is drawn. No
        shuffle is applied — callers wanting randomness shuffle first — so
        games are reproducible for tests and the bot.
        """
        players: list[Player] = []
        for player_id, name, cards in player_libraries:
            player = Player(id=player_id, name=name, life=starting_life)
            for card in cards:
                obj = GameObject(card=card, owner_id=player_id, zone=Zone.LIBRARY)
                player.library.append(obj)
            players.append(player)

        state = GameState(players=players)
        engine = cls(state)
        for player in players:
            player.draw(starting_hand)
        return engine

    # ------------------------------------------------------------------
    # Turn loop (RULE 500, R4.1)
    # ------------------------------------------------------------------

    def begin_turn(self) -> None:
        """Advance to the next player's turn and reset per-turn state."""
        if self.state.turn_number == 0:
            self.state.turn_number = 1
            self.state.active_player_index = 0
        else:
            # Capture the outgoing player's final spell count before rotating
            # — RULE 731.2's day/night check reads *last* turn's active
            # player, from the untap step of the turn about to begin.
            outgoing = self.state.active_player
            self.state._last_turn_player_id = outgoing.id
            self.state._last_turn_spell_count = self.state.spells_cast_this_turn.get(outgoing.id, 0)
            self.state.turn_number += 1
            # Rotate to the next player, skipping the passive goldfish dummy
            # (UC3) so a solo game keeps handing turns back to the human.
            self.state.active_player_index = self.state.next_active_index()
        active = self.state.active_player
        active.lands_played_this_turn = 0
        self.state.spells_cast_this_turn[active.id] = 0
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

    # -- Interactive stepping (for a controllable goldfish / UI) ---------

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

        self.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step.name, phase=phase.name))
        self._execute_step_body(step)

        if step.gives_priority:
            # RULE 117.3a: (re-)grant priority to the active player as this
            # step's window opens.
            self.give_priority(self.state.active_player)
            # Turn-based actions can create triggers; resolve everything and
            # let priority pass around until the stack is empty (RULE 117).
            # Solo/goldfish auto-drains here; an interactive multiplayer loop
            # would instead drive `pass_priority(player)` itself and skip
            # this auto-resolve — not wired into any session path yet.
            self.resolve_until_stable()

        # RULE 500.4: unused mana empties as the step ends.
        for player in self.state.players:
            player.mana_pool.empty()
        self.state.fire_event(GameEvent(EventType.STEP_END, step=step.name, phase=phase.name))

    def _execute_step_body(self, step: GameStep) -> None:
        handler = getattr(self, f"_step_{step.name}", None)
        if handler is not None:
            handler()

    # -- Individual step bodies -----------------------------------------

    def _step_untap(self) -> None:
        active = self.state.active_player
        for obj in self.state.permanents_controlled_by(active.id):
            if not self.rules.should_skip_step(active, "untap_permanents"):
                obj.untap()
            # Controlled since the turn began → no longer summoning sick.
            obj.summoning_sick = False
            # RULE 606.3: a new loyalty ability may be activated this turn.
            obj.activated_loyalty_this_turn = False
        self.state.fire_event(GameEvent(EventType.UNTAP, player_id=active.id))
        # RULE 731.2: "as the second part of the untap step", check whether
        # day/night should flip based on last turn's spell count.
        self.rules.apply_day_night_turn_check()

    def _step_draw(self) -> None:
        # RULE 103.7a: the starting player skips their first draw in a
        # two-or-more-player game — unless the goldfish setup opted the human
        # onto the draw (`skip_first_draw` cleared).
        skip_draw = (
            self.state.turn_number == 1
            and len(self.state.players) > 1
            and self.state.skip_first_draw
        )
        if not skip_draw:
            self.rules.draw(self.state.active_player, 1)
        # RULE 714.2b: after the draw step, each Saga its controller controls
        # gets another lore counter, advancing it to its next chapter.
        self.rules.advance_sagas(self.state.active_player)

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

    def _combat_has_first_strikers(self) -> bool:
        """Whether any attacker or blocker has first or double strike (→ two
        damage steps, RULE 702.7e)."""
        combatants = list(self.attackers) + [
            b for b in self.state.battlefield if b.blocking is not None
        ]
        return any(
            combat.has_first_strike(c) or combat.has_double_strike(c) for c in combatants
        )

    @staticmethod
    def _deals_in_step(obj: GameObject, first_strike_step: bool) -> bool:
        """Whether ``obj`` deals damage in this combat-damage step.

        First-strike step: first strike *or* double strike. Regular step:
        double strike (again) or a creature with neither — a pure first-striker
        has already dealt and deals nothing more.
        """
        fs = combat.has_first_strike(obj)
        ds = combat.has_double_strike(obj)
        return (fs or ds) if first_strike_step else (ds or not fs)

    def _deal_combat_damage_step(self, first_strike_step: bool) -> None:
        # (target, amount, source) gathered before anything is dealt.
        assignments: list[tuple[Any, int, GameObject]] = []
        for attacker in self.attackers:
            if not self._deals_in_step(attacker, first_strike_step):
                continue
            power = attacker.power or 0
            if power <= 0:
                continue
            if attacker.blocked_by:
                # Blocked (RULE 509.1h: it stays blocked even if every blocker
                # has left) — damage goes to whatever blockers remain, with
                # trample overflow to the defender.
                living = [
                    b
                    for b in (self.state.find_object(i) for i in attacker.blocked_by)
                    if b is not None and b in self.state.battlefield
                ]
                assignments.extend(self._assign_blocked_attacker(attacker, power, living))
            else:
                defender = self._resolve_combat_defender(attacker.combat_defender)
                if defender is not None:  # None → bare swing (solo goldfish)
                    assignments.append((defender, power, attacker))

        # Blockers strike the attacker they're blocking (RULE 510.1c).
        for blocker in self.state.battlefield:
            if blocker.blocking is None or not self._deals_in_step(blocker, first_strike_step):
                continue
            power = blocker.power or 0
            if power <= 0:
                continue
            attacker = self.state.find_object(blocker.blocking)
            if attacker is not None and attacker in self.state.battlefield:
                assignments.append((attacker, power, blocker))

        self._apply_combat_damage(assignments)

    def _assign_blocked_attacker(
        self, attacker: GameObject, power: int, blockers: list[GameObject]
    ) -> list[tuple[Any, int, GameObject]]:
        """Spread a blocked attacker's ``power`` across its blockers (RULE
        510.1c ordering, lethal-first), trampling the excess onto the defender
        if it has trample (RULE 702.19), else soaking the remainder on the last
        blocker. Deathtouch shrinks "lethal" to 1 (RULE 702.2b) so trample
        needs assign only 1 per blocker before spilling over.
        """
        out: list[tuple[Any, int, GameObject]] = []
        trample = combat.has_trample(attacker)
        if not blockers:
            # Every blocker gone: only trample leaks to the defender.
            if trample:
                defender = self._resolve_combat_defender(attacker.combat_defender)
                if defender is not None:
                    out.append((defender, power, attacker))
            return out

        remaining = power
        for index, blocker in enumerate(blockers):
            if remaining <= 0:
                break
            last = index == len(blockers) - 1
            lethal = combat.lethal_damage(blocker, attacker)
            if trample:
                amount = min(remaining, lethal)
            else:
                amount = remaining if last else min(remaining, lethal)
            if amount > 0:
                out.append((blocker, amount, attacker))
                remaining -= amount
        if trample and remaining > 0:
            defender = self._resolve_combat_defender(attacker.combat_defender)
            if defender is not None:
                out.append((defender, remaining, attacker))
        return out

    def _apply_combat_damage(
        self, assignments: list[tuple[Any, int, GameObject]]
    ) -> None:
        """Deal one damage step's gathered assignments, applying protection,
        deathtouch and lifelink to each."""
        for target, amount, source in assignments:
            # Protection prevents the damage from a source of the named quality
            # (RULE 702.16c; `rules.deal_damage` enforces this too, so no
            # damage lands even if a caller skips this check) — checked here
            # as well so deathtouch/lifelink below don't fire off damage that
            # never happened. Players carry no protection in this model.
            if isinstance(target, GameObject) and combat.is_protected_from(target, source):
                continue
            self.rules.deal_damage(target, amount, source=source, combat=True)
            if amount <= 0:
                continue
            # Deathtouch: mark any creature damaged by a deathtouch source for
            # the SBA to destroy (RULE 702.2b).
            if isinstance(target, GameObject) and combat.has_deathtouch(source):
                target.dealt_deathtouch_damage = True
            # Lifelink: the source's controller gains that much life (702.15b).
            if combat.has_lifelink(source):
                self.rules.gain_life(self.state.player_by_id(source.controller_id), amount)

    def _resolve_combat_defender(self, spec: Optional[dict[str, Any]]) -> Optional[Any]:
        """Turn a stored ``combat_defender`` spec back into the live target.

        Returns the defending `Player`, the planeswalker `GameObject`, or
        None (a bare swing / a defender that has since left). Robust to a
        rewind having swapped in a fresh state — everything is re-looked-up
        by id, never held by reference.
        """
        if not spec:
            return None
        if spec.get("kind") == "player":
            try:
                player = self.state.player_by_id(spec["id"])
            except KeyError:
                return None
            return None if player.has_lost else player
        if spec.get("kind") == "planeswalker":
            obj = self.state.find_object(spec["instance_id"])
            if obj is not None and obj in self.state.battlefield:
                return obj
        return None

    def _step_end_combat(self) -> None:
        # RULE 511.3: creatures are removed from combat as it ends.
        self._clear_combat()

    def _step_cleanup(self) -> None:
        active = self.state.active_player
        # RULE 514.1: discard down to maximum hand size.
        excess = len(active.hand) - MAX_HAND_SIZE
        if excess > 0:
            self.rules.discard(active, excess)
        # RULE 514.2: remove marked damage and end "until end of turn" effects
        # (pump P/T bonuses, temporary keyword grants, and a "becomes a copy
        # of target creature until end of turn" activation — Cursed Mirror).
        from . import copy_mechanics

        ended_effects = False
        for obj in self.state.permanents():
            obj.damage_marked = 0
            if obj.temp_power or obj.temp_toughness or obj.temp_keywords:
                obj.temp_power = 0
                obj.temp_toughness = 0
                obj.temp_keywords.clear()
                ended_effects = True
            if obj._copy_until_eot_base is not None:
                copy_mechanics.restore_face(obj, obj._copy_until_eot_base)
                obj._copy_until_eot_base = None
                ended_effects = True
        if ended_effects:
            self.recompute_continuous_effects()  # re-derive P/T sans the pumps
        self._clear_combat()

    # ------------------------------------------------------------------
    # Stack / priority resolution (RULE 117 / 608)
    # ------------------------------------------------------------------

    def resolve_until_stable(self) -> None:
        """Resolve triggers + the stack until empty, stable, or blocked.

        Models an all-players-pass priority window with no responses: put
        fired triggers on the stack, resolve the top, repeat; check SBAs
        throughout (RULE 704.3). Stops early if a resolving effect needs a
        player choice (`state.pending_choice`, e.g. a library search) — the
        session surfaces it and resumes via `resolve_pending_choice`.
        """
        for _ in range(_MAX_RESOLUTIONS):
            self.rules.check_state_based_actions()
            if self.state.game_over:
                return
            if self.state.pending_choice:
                return  # await a player decision before resolving further
            self.rules.put_triggers_on_stack()
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
        elif kind == "land_tapped":
            # RULE 614.1: a shock land's "pay life to stay untapped" choice.
            self.rules.resolve_land_tapped_choice(None if declined else str(answer))
        elif kind == "replacement_order":
            # RULE 616.1: the option id is the index of the replacement
            # effect to apply next.
            index = None if declined else int(answer)
            self.rules.resolve_replacement_order_choice(index)
        elif kind == "enter_as_copy":
            # RULE 614.1c/614.12: the option id is a permanent's instance id,
            # or decline to enter as itself.
            self.rules.resolve_enter_as_copy_choice(None if declined else str(answer))
        elif kind == "counter_unless_pays":
            # RULE 601: "pay" saves the target spell, anything else counters it.
            self.rules.resolve_counter_unless_pays_choice(None if declined else str(answer))
        else:  # search: a card's instance id, or decline
            instance_id = None if declined else int(answer)
            self.rules.resolve_search_choice(instance_id)
        self.resolve_until_stable()

    # ------------------------------------------------------------------
    # Player actions with validation (RULE 601 / 505 / R4.3)
    # ------------------------------------------------------------------

    def _in_main_phase(self) -> bool:
        return self.state.current_step in ("main1", "main2")

    def _face_card(self, obj: GameObject, face: str = "front") -> Optional[Card]:
        """The `Card` ``face`` ("front"/"back"/"fuse") refers to for ``obj``.

        "front" is always ``obj.card`` as it currently stands — which also
        makes this work after a second face has already been switched to,
        since at that point "the current face" *is* the back. "back" is
        whatever `Card.back_face` captured — a modal DFC's back (RULE
        712.10), a split card's other half (RULE 709.3), or an Adventure's
        instant/sorcery half (RULE 715.2b) — or None if nothing was
        captured for this card. "fuse" is a split card's synthetic combined
        cast (RULE 709.4, `Card.fuse_face`), or None without Fuse. Read-only:
        never mutates ``obj``, so callers can use it to preview an un-chosen
        face (e.g. for `legal_actions`) without committing to it.
        """
        if face == "back":
            return obj.card.back_face()
        if face == "fuse":
            return obj.card.fuse_face()
        return obj.card

    def can_play_land(self, player: Player, obj: GameObject, face: str = "front") -> bool:
        card = self._face_card(obj, face)
        return (
            card is not None
            and player is self.state.active_player
            and self._in_main_phase()
            and not self.state.stack
            and player.lands_played_this_turn < player.max_lands_per_turn
            and obj in player.hand
            and card.is_land
        )

    def play_land(self, player: Player, obj: GameObject, face: str = "front") -> GameObject:
        """Play a land from hand (RULE 505.5b — a special action, no stack).

        ``face="back"`` plays a modal DFC's back face instead (RULE 712.10) —
        legal only when that face is itself a land; the front/back choice is
        made once, here, by rebinding ``obj`` onto the back `Card` before the
        rest of this method (which then reads ``obj.card`` exactly as for any
        other land) runs unchanged.
        """
        if not self.can_play_land(player, obj, face=face):
            raise ValueError(f"{player.id} cannot play {obj.name} now")
        if face == "back":
            self.rules.switch_to_face(obj, obj.card.back_face())
        player.remove_from_zone(obj, Zone.HAND)
        obj.summoning_sick = True
        # RULE 614.1: a tap-land enters the battlefield tapped — including a
        # shock/check/fast/slow land's conditional shape (payment choice or
        # board-state check), resolved by `enter_land_tapped`.
        self.rules.enter_land_tapped(obj)
        self.state.add_to_battlefield(obj)
        player.lands_played_this_turn += 1
        self.state.record_stat(player.id, "land", name=obj.name)
        self.state.fire_event(
            GameEvent(EventType.LAND_PLAYED, player_id=player.id, card_id=obj.card.id, land=obj.name)
        )
        self.state.fire_event(
            GameEvent(
                EventType.ENTERS_BATTLEFIELD,
                controller_id=player.id,
                object=obj.name,
                instance_id=obj.instance_id,
                object_types=sorted(obj.type_words),
            )
        )
        # RULE 117.3c: taking an action reclaims priority for its taker.
        self.give_priority(player)
        return obj

    @staticmethod
    def _castable_from_exile(obj: GameObject) -> bool:
        """Whether an object sitting in exile is castable from there.

        Two independent cases: an Adventure creature exiled by its own
        spell half (RULE 715.3d, flagged `adventure_castable`), or a
        prepared copy (RULE 722.3c) — the copy's mere presence in exile
        already proves it's still valid, since `RulesEngine.
        _remove_stranded_tokens` reaps it the instant its source stops
        being prepared/on the battlefield, so no extra freshness check is
        needed here beyond the `prepared_source_id` link existing.
        """
        return obj.adventure_castable or obj.prepared_source_id is not None

    def can_cast(self, player: Player, obj: GameObject, x: int = 0, face: str = "front") -> bool:
        """RULE 601/602.5: is this spell castable by ``player`` right now?

        ``x`` is the value that would be announced for a cost containing
        ``{X}`` (ignored otherwise) — pass 0 (the default) to check bare
        castability, or a specific value to check whether *that* X is
        affordable. ``face="back"``/``"fuse"`` check a second castable face
        (see `_face_card`) instead, without mutating ``obj`` — a preview,
        used by `legal_actions` to decide whether to offer casting it.
        """
        # A commander may be cast from the command zone as well as the
        # hand (RULE 903.6, 903.8) — commander tax (RULE 903.8, +{2} per
        # previous cast from there) isn't modeled yet. An Adventure creature
        # or a prepared copy sitting in exile may also be castable — see
        # `_castable_from_exile`.
        in_castable_zone = (
            obj in player.hand
            or obj in player.command
            or (obj in player.exile and self._castable_from_exile(obj))
        )
        if not in_castable_zone:
            return False
        card = self._face_card(obj, face)
        if card is None or card.is_land:
            return False
        # Timing (RULE 601.3a): sorcery-speed spells need an empty stack,
        # the player's own main phase, and their priority.
        sorcery_speed = not card.is_instant
        if sorcery_speed:
            if player is not self.state.active_player:
                return False
            if not self._in_main_phase() or self.state.stack:
                return False
        cost = self.effective_cast_cost(player, obj, x, face=face)
        if not player.mana_pool.can_pay(cost, life_available=player.life):
            return False
        # RULE 601.2b: an "as an additional cost to cast this spell, …"
        # clause is a separate legality gate from the mana cost above — a
        # sacrifice/discard/life payment that isn't payable makes the spell
        # uncastable even with the mana in hand.
        return self._can_pay_additional_cast_cost(
            player, obj, getattr(obj, "additional_cast_cost", None), x
        )

    def effective_cast_cost(
        self, player: Player, obj: GameObject, x: int = 0, face: str = "front"
    ) -> "ManaCost":
        """``obj``'s mana cost after static cost adjustments (RULE 601.2f/903.8).

        Starts from the printed cost (with ``{X}`` resolved), applies the net
        generic reduction from "spells you cast cost {N} less/more" statics in
        play, then adds commander tax ({2} per previous cast of this commander
        from the command zone, RULE 903.8) when it's being cast from there.
        Generic-only and floored at zero — the common, safe case. ``face``
        previews a second castable face's own printed cost (see
        `_face_card`) without mutating ``obj``.
        """
        card = self._face_card(obj, face) or obj.card
        cost = self.rules.mana_cost_of(card)
        if cost.has_variable:
            cost = cost.with_x(x)
        cost = self._adjust_cost(cost, player)
        tax = self.commander_tax(player, obj)
        if tax:
            cost = cost.increase_generic(tax)
        return cost

    @staticmethod
    def commander_tax(player: Player, obj: GameObject) -> int:
        """Generic surcharge to cast ``obj`` from the command zone (RULE 903.8).

        {2} for each previous time this commander was cast from the command
        zone; 0 for a normal spell or a commander being cast from hand."""
        if obj.is_commander and obj in player.command:
            return 2 * player.commander_casts.get(obj.instance_id, 0)
        return 0

    def _adjust_cost(self, cost: "ManaCost", player: Player) -> "ManaCost":
        """Apply the net static generic adjustment (reduce or increase)."""
        reduction, _ = continuous.cost_reduction_for(self.state, player)
        if reduction > 0:
            return cost.reduce_generic(reduction)
        if reduction < 0:
            return cost.increase_generic(-reduction)
        return cost

    def recompute_continuous_effects(self) -> None:
        """Re-derive all layer-based characteristics now (RULE 613).

        SBAs already do this whenever the board settles; call this to refresh
        derived P/T, types and granted keywords for a read outside that loop
        (e.g. building the view for the UI)."""
        continuous.recompute(self.state)

    def max_affordable_x(self, player: Player, obj: GameObject) -> int:
        """The highest X ``player`` could announce and still pay for ``obj``.

        Only meaningful when the cost has ``{X}``; scans down from the
        pool's total mana (X can never exceed that) to the first payable
        value, 0 if even X=0 doesn't work.
        """
        bound = player.mana_pool.total()
        for x in range(bound, -1, -1):
            if self.can_cast(player, obj, x):
                return x
        return 0

    def cast_spell(
        self,
        player: Player,
        obj: GameObject,
        targets: Optional[list[Any]] = None,
        x: int = 0,
        face: str = "front",
        mode: Optional[Any] = None,
    ):
        """Cast a spell after validating timing, payability and targets (RULE 601).

        ``face="back"``/``"fuse"`` cast a second castable face instead (see
        `_face_card`) — a modal DFC's back (RULE 712.10), a split card's
        other half or fused combination (RULE 709.3/709.4), or an
        Adventure's instant/sorcery half (RULE 715.2b): ``obj`` is rebound
        onto that face (`RulesEngine.switch_to_face`, the same "clear +
        rebind catalogue abilities" treatment `become_copy` uses) before the
        ordinary cast validation/commit runs — so any failure below leaves
        ``obj`` restored to its original face rather than silently stuck on
        the second one.

        ``mode`` chooses which of a modal spell's ("Choose one —", RULE
        700.2) printed options resolves: an index into ``obj.spell_modes``,
        or the literal ``"both"`` (RULE 700.2e, only when
        ``obj.spell_modes_or_both``). Required — raises — for a spell that
        carries ``spell_modes``; ignored otherwise. See `_mode_effects_applied`.
        """
        if face in ("back", "fuse"):
            if not self.can_cast(player, obj, x, face=face):
                raise ValueError(f"{player.id} cannot cast {obj.name} now")
            # RULE 715.2b: an Adventure spell half must be recognized while
            # ``obj.card`` is still the front (creature) face, before the
            # switch below — resolution needs to know to exile-and-restore
            # rather than send it to the graveyard.
            is_adventure_cast = face == "back" and obj.card.is_adventure
            alt = obj.card.back_face() if face == "back" else obj.card.fuse_face()
            snapshot = self.rules.snapshot_face(obj)
            self.rules.switch_to_face(obj, alt)
            try:
                result = self._cast_current_face(player, obj, targets, x, mode=mode)
            except Exception:
                self.rules.restore_face(obj, snapshot)
                raise
            if is_adventure_cast:
                obj.adventure_snapshot = snapshot
            return result
        return self._cast_current_face(player, obj, targets, x, mode=mode)

    def _effects_for_mode(self, obj: GameObject, mode: Any) -> list[Any]:
        """The `GameEffect`s a modal spell's chosen ``mode`` resolves with.

        ``mode`` is an index into ``obj.spell_modes``, or ``"both"`` (RULE
        700.2e) — both modes' effects, in printed order. Raises for an
        out-of-range index or a "both" not actually offered (`obj` has no
        ``spell_modes`` at all, or isn't ``spell_modes_or_both``, or doesn't
        have exactly the two modes RULE 700.2e's "or both" implies).
        """
        modes = list(getattr(obj, "spell_modes", None) or [])
        if mode == "both":
            if not getattr(obj, "spell_modes_or_both", False) or len(modes) != 2:
                raise ValueError(f"{obj.name} has no 'choose both' mode")
            effects: list[Any] = []
            for entry in modes:
                effects.extend(entry["effects"])
            return effects
        if not isinstance(mode, int) or not (0 <= mode < len(modes)):
            raise ValueError(f"{obj.name}: invalid mode {mode!r}")
        return list(modes[mode]["effects"])

    def _mode_description(self, obj: GameObject, mode: Any) -> str:
        """A modal spell's chosen ``mode`` as UI label text."""
        modes = list(getattr(obj, "spell_modes", None) or [])
        if mode == "both":
            return " + ".join(entry.get("description", "") for entry in modes)
        if isinstance(mode, int) and 0 <= mode < len(modes):
            return modes[mode].get("description", "")
        return ""

    @contextmanager
    def _mode_effects_applied(self, obj: GameObject, mode: Optional[Any]):
        """Temporarily point ``obj.spell_effects`` at a modal spell's chosen
        mode(s) (RULE 601.2b: the mode is chosen before targets/costs).

        `has_legal_targets`/`RulesEngine._effects_for_spell` both read
        ``obj.spell_effects`` — swapping it here (and restoring it on exit,
        success or failure) means neither needs to know modes exist at all,
        the same "no top-level change needed" trick `switch_to_face` uses
        for a second castable face. A no-op for a non-modal ``obj``
        (``spell_modes`` unset/empty).
        """
        modes = getattr(obj, "spell_modes", None)
        if not modes:
            yield
            return
        if mode is None:
            raise ValueError(f"{obj.name} requires a mode choice (RULE 601.2b)")
        previous = list(getattr(obj, "spell_effects", None) or [])
        obj.spell_effects = self._effects_for_mode(obj, mode)
        try:
            yield
        finally:
            obj.spell_effects = previous

    def _cast_current_face(
        self,
        player: Player,
        obj: GameObject,
        targets: Optional[list[Any]],
        x: int,
        mode: Optional[Any] = None,
    ):
        """The common cast body, reading whatever `obj.card` currently is."""
        with self._mode_effects_applied(obj, mode):
            if not self.can_cast(player, obj, x):
                raise ValueError(f"{player.id} cannot cast {obj.name} now")
            # RULE 601.2c: a spell that requires a target can't be cast unless
            # a legal target is available — the same check that locks the offer.
            if not self.has_legal_targets(player, obj):
                raise ValueError(f"{obj.name} has no legal target")
            cost = self.effective_cast_cost(player, obj, x)
            # RULE 903.8: record this command-zone cast so the next one is
            # taxed {2} more. Read *before* the cast moves the card off the
            # command zone.
            from_command = obj.is_commander and obj in player.command
            result = self.rules.cast_spell(player, obj, targets, x, cost=cost)
            # RULE 601.2b/601.2h: an additional cost is paid as part of
            # casting, not resolving — so it stays paid even if the spell is
            # later countered. Paid *after* the mana cost (just above) so a
            # Phyrexian-mana payment reads the player's life before any
            # "pay N life" additional cost reduces it.
            self._pay_additional_cast_cost(
                player, obj, getattr(obj, "additional_cast_cost", None), x
            )
        if from_command:
            player.commander_casts[obj.instance_id] = (
                player.commander_casts.get(obj.instance_id, 0) + 1
            )
        # RULE 117.3c: taking an action reclaims priority for its taker.
        self.give_priority(player)
        return result

    def has_legal_targets(self, player: Player, obj: GameObject) -> bool:
        """Whether every target ``obj`` requires can be legally chosen now.

        True for a non-targeting spell (no requirements to satisfy). RULE
        601.2c / 608.2b: a targeting spell needs at least one legal target
        per non-optional requirement, computed from the live board.
        """
        requirements = requirements_with_targets(self.state, player.id, obj)
        return all_requirements_satisfiable(requirements)

    def legal_defenders_for(self, player: Player) -> list[dict[str, Any]]:
        """Who ``player``'s creatures may attack (RULE 508.1a).

        Each attacking creature is declared attacking either a player or a
        planeswalker an opponent controls. Returns those choices as
        serializable specs the UI renders as targets (and `declare_attackers`
        validates against). In a solo goldfish there are no opponents, so
        this is empty — attacks become "bare" swings with no target.
        """
        defenders: list[dict[str, Any]] = []
        for other in self.state.players:
            if other.id == player.id or other.has_lost:
                continue
            defenders.append({"kind": "player", "id": other.id, "label": other.name})
        for obj in self.state.battlefield:
            if obj.controller_id != player.id and obj.is_planeswalker:
                defenders.append(
                    {"kind": "planeswalker", "instance_id": obj.instance_id, "label": obj.name}
                )
        return defenders

    def declare_attackers(
        self, player: Player, declarations: list[Any]
    ) -> None:
        """Declare attackers (RULE 508), each against a chosen defender.

        Each entry is either a bare `GameObject` (the engine picks the
        defender when it is unambiguous) or a ``{"attacker": obj, "defender":
        spec}`` dict, where ``spec`` is one of the entries `legal_defenders_for`
        returns (or None for a bare swing). Declaring is *additive* — the UI
        declares creatures one at a time so each can pick its own target
        below it — so repeated calls accumulate the combat. Taps each
        attacker and fires ATTACKS.
        """
        if player is not self.state.active_player:
            raise ValueError("only the active player declares attackers")
        if self.state.current_step != "declare_attackers":
            raise ValueError("not in the declare-attackers step")

        legal = self.legal_defenders_for(player)
        resolved: list[tuple[GameObject, Optional[dict[str, Any]]]] = []
        for entry in declarations:
            if isinstance(entry, dict):
                obj = entry["attacker"]
                defender = entry.get("defender")
            else:
                obj, defender = entry, None
            if not self._can_attack(player, obj):
                raise ValueError(f"{obj.name} cannot attack")
            resolved.append((obj, self._assign_defender(obj, defender, legal)))

        for obj, defender in resolved:
            # Vigilance (RULE 702.21b): attacking doesn't cause it to tap.
            if not combat.has_vigilance(obj):
                self.rules.set_tapped(obj, True)
            obj.attacking = True
            obj.combat_defender = defender
            self.state.fire_event(
                GameEvent(
                    EventType.ATTACKS,
                    attacker=obj.name,
                    player_id=player.id,  # RULE 508.1a: the attacker's controller
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )

    def _assign_defender(
        self, obj: GameObject, defender: Any, legal: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """Validate/normalize an attacker's declared defender (RULE 508.1a).

        With no defender given: auto-assign when exactly one is legal (the
        common two-player case — no need to make the player pick), a bare
        swing when none is legal (solo goldfish), and an error when the
        choice is ambiguous (2+ legal defenders — the UI must pass one).
        """
        if defender is None:
            if not legal:
                return None
            if len(legal) == 1:
                return dict(legal[0])
            raise ValueError(f"{obj.name} must choose which defender to attack")
        spec = self._defender_spec(defender)
        if not any(self._same_defender(spec, cand) for cand in legal):
            raise ValueError(f"{obj.name} cannot attack that defender")
        return spec

    @staticmethod
    def _defender_spec(defender: Any) -> dict[str, Any]:
        """Coerce a Player / planeswalker `GameObject` / spec dict → a spec."""
        if isinstance(defender, dict):
            return dict(defender)
        if isinstance(defender, Player):
            return {"kind": "player", "id": defender.id, "label": defender.name}
        if isinstance(defender, GameObject):
            return {
                "kind": "planeswalker",
                "instance_id": defender.instance_id,
                "label": defender.name,
            }
        raise ValueError(f"invalid defender: {defender!r}")

    @staticmethod
    def _same_defender(a: dict[str, Any], b: dict[str, Any]) -> bool:
        if a.get("kind") != b.get("kind"):
            return False
        if a.get("kind") == "player":
            return a.get("id") == b.get("id")
        return a.get("instance_id") == b.get("instance_id")

    def _can_attack(self, player: Player, obj: GameObject) -> bool:
        return (
            obj.controller_id == player.id
            and obj.is_creature
            and obj in self.state.battlefield
            and not obj.tapped
            # Haste (RULE 702.10b) lets a creature attack the turn it arrives.
            and (not obj.summoning_sick or combat.has_haste(obj))
            # Defender (RULE 702.3b) can never attack.
            and not combat.has_defender(obj)
        )

    @staticmethod
    def _summoning_sick_for_tap(obj: GameObject) -> bool:
        """Whether summoning sickness stops ``obj`` paying a {T}/{Q} cost.

        RULE 302.6 / 602.5e: a creature can't activate an ability whose cost
        includes the tap or untap symbol unless its controller has controlled
        it continuously since their most recent turn began (i.e. it isn't
        summoning sick) — and this covers a creature's mana ability just as
        much as any other, since a mana ability *is* an activated ability
        (RULE 605.1a). Haste (RULE 702.10b) lifts the restriction, and
        non-creature permanents (lands, mana rocks) are never affected.
        """
        return obj.is_creature and obj.summoning_sick and not combat.has_haste(obj)

    # -- Blocking (RULE 509) --------------------------------------------

    def declare_blockers(self, player: Player, assignments: list[Any]) -> None:
        """Declare ``player``'s creatures as blockers (RULE 509).

        ``player`` is a *defending* player (not the active/attacking one).
        Each entry is a ``{"blocker": obj, "attacker": obj}`` dict or a
        ``(blocker, attacker)`` pair. A blocker may be assigned to an
        attacker only if that attacker is attacking this player (or a
        planeswalker they control). Additive, like `declare_attackers`.

        Goldfish's passive dummy never blocks, so in solo play this stays
        dormant; it's the engine half of interactive/multiplayer combat.
        """
        if self.state.current_step != "declare_blockers":
            raise ValueError("not in the declare-blockers step")
        if player is self.state.active_player:
            raise ValueError("the attacking player does not declare blockers")
        resolved: list[tuple[GameObject, GameObject]] = []
        for entry in assignments:
            if isinstance(entry, dict):
                blocker, attacker = entry["blocker"], entry["attacker"]
            else:
                blocker, attacker = entry
            if not self.can_block(player, blocker, attacker):
                raise ValueError(f"{blocker.name} cannot block {attacker.name}")
            resolved.append((blocker, attacker))

        # Menace (RULE 702.111b): a blocked menacing attacker must be blocked
        # by two or more creatures. Validated over the resulting block —
        # counting blockers already assigned plus this call's — *before* any
        # mutation, so an illegal single-creature block leaves state untouched.
        # (A whole legal block for one attacker is therefore declared in one
        # call, matching how the UI submits blocks.)
        projected: dict[int, set[int]] = {}
        for blocker, attacker in resolved:
            projected.setdefault(attacker.instance_id, set(attacker.blocked_by)).add(
                blocker.instance_id
            )
        for attacker_id, blocker_ids in projected.items():
            attacker = self.state.find_object(attacker_id)
            if attacker is not None and combat.has_menace(attacker) and len(blocker_ids) < 2:
                raise ValueError(
                    f"{attacker.name} has menace and must be blocked by two or more creatures"
                )

        for blocker, attacker in resolved:
            blocker.blocking = attacker.instance_id
            if blocker.instance_id not in attacker.blocked_by:
                attacker.blocked_by.append(blocker.instance_id)
            self.state.fire_event(
                GameEvent(
                    EventType.BLOCKS,
                    blocker=blocker.name,
                    player_id=player.id,  # RULE 509.1b: the blocker's controller
                    instance_id=blocker.instance_id,
                    object_types=sorted(blocker.type_words),
                )
            )

    def can_block(self, player: Player, blocker: GameObject, attacker: GameObject) -> bool:
        """RULE 509.1a: an untapped creature ``player`` controls may block an
        attacker that is attacking ``player`` (or a planeswalker they control).

        Plus the evasion half (RULE 509.1b): flying can only be blocked by
        flying/reach, protection stops a block by the protected-from quality
        (see `combat.can_block`), and landwalk (RULE 702.14b) makes the
        attacker unblockable while this player controls a land of that type.
        Menace — a *group* requirement — is checked over the whole assignment
        in `declare_blockers`, not here.
        """
        if combat.unblockable_by_landwalk(attacker, self._lands_controlled_by(player.id)):
            return False
        return (
            blocker.controller_id == player.id
            and blocker.is_creature
            and blocker in self.state.battlefield
            and not blocker.tapped
            and blocker.blocking is None
            and attacker.attacking
            and self._attacker_attacks_player(attacker, player)
            and combat.can_block(attacker, blocker)
        )

    def _lands_controlled_by(self, player_id: str) -> list[GameObject]:
        return [
            o for o in self.state.battlefield
            if o.is_land and o.controller_id == player_id
        ]

    def _attacker_attacks_player(self, attacker: GameObject, player: Player) -> bool:
        defender = attacker.combat_defender
        if not defender:
            return False
        if defender.get("kind") == "player":
            return defender.get("id") == player.id
        pw = self.state.find_object(defender.get("instance_id"))
        return pw is not None and pw.controller_id == player.id

    def tap_for_mana(
        self, player: Player, source: GameObject, option_index: int = 0
    ) -> dict[str, int]:
        """Tap a permanent for one of its mana options (RULE 605).

        ``option_index`` picks which production to make — this is the
        dual-land fix: a "{T}: Add {W} or {U}." land makes *one* colour,
        the chosen option, not both. Returns the mana added.
        """
        if source not in self.state.battlefield or source.controller_id != player.id:
            raise ValueError("can only tap your own permanents in play")
        if source.tapped:
            raise ValueError(f"{source.name} is already tapped")
        # RULE 302.6: a summoning-sick creature (Llanowar Elves, Birds of
        # Paradise, …) can't tap for mana — its mana ability has the {T} symbol.
        if self._summoning_sick_for_tap(source):
            raise ValueError(f"{source.name} has summoning sickness and can't tap for mana")
        options = mana_options_for(source)
        if not options:
            raise ValueError(f"{source.name} has no mana ability")
        if not 0 <= option_index < len(options):
            raise ValueError(f"invalid mana option {option_index} for {source.name}")
        produced = options[option_index]
        self.rules.set_tapped(source, True)
        player.mana_pool.add_many(produced)
        self.state.record_stat(player.id, "mana", amount=sum(produced.values()))
        return dict(produced)

    # ------------------------------------------------------------------
    # Activated abilities (RULE 602)
    # ------------------------------------------------------------------

    def can_activate(
        self, player: Player, source: GameObject, ability: ActivatedAbility, x: int = 0
    ) -> bool:
        """Whether ``player`` may activate ``ability`` of ``source`` right now.

        Requires ``source`` to be a permanent ``player`` controls carrying the
        ability, and every part of its cost to be payable (RULE 602.2a):
        mana, tapping/untapping the source, a life/discard/counter payment,
        and a legal thing to sacrifice.
        """
        if source not in self.state.battlefield or source.controller_id != player.id:
            return False
        if ability not in source.activated_abilities:
            return False
        if ability.cost.is_loyalty and not self._can_activate_loyalty(player, source):
            return False
        if ability.cost.sorcery_speed_only and not self._sorcery_speed_ok(player):
            return False
        if ability.cost.class_level is not None and not self._can_activate_class_level(
            source, ability.cost.class_level
        ):
            return False
        return self._can_pay_activation_cost(player, source, ability.cost, x)

    def _sorcery_speed_ok(self, player: Player) -> bool:
        """RULE 117.1a-style sorcery-speed timing: the controller's main
        phase, an empty stack, and it being that player's turn — the same
        shape `can_play_land`/`can_cast`'s sorcery branch already check."""
        return (
            player is self.state.active_player
            and self._in_main_phase()
            and not self.state.stack
        )

    def _can_activate_loyalty(self, player: Player, source: GameObject) -> bool:
        """Timing gate for a planeswalker loyalty ability (RULE 606.3).

        Only at sorcery speed and only once per turn per planeswalker."""
        return (
            source.is_planeswalker
            and self._sorcery_speed_ok(player)
            and not source.activated_loyalty_this_turn
        )

    def _can_activate_class_level(self, source: GameObject, target_level: int) -> bool:
        """RULE 716.4c: a Class's level-up ability may only be activated when
        the Class's current level is exactly one less than the ability's
        level — levels can't be skipped or repeated."""
        return source.counters.get("class_level", 0) == target_level - 1

    def _ability_target_requirements(
        self, player: Player, ability: ActivatedAbility, source: GameObject
    ) -> list[dict[str, Any]]:
        """Target requirements of an activated ability, with legal options —
        the same shape `_cast_action` uses for spells (RULE 602.2b / 115)."""
        out: list[dict[str, Any]] = []
        for effect in ability.effects:
            spec = getattr(effect, "target_spec", None)
            if spec is not None:
                out.append(
                    {
                        "kind": spec.kind,
                        "optional": spec.optional,
                        "label": spec.label(),
                        "options": legal_targets(self.state, player.id, spec, source=source),
                    }
                )
        return out

    def _activate_action(
        self, player: Player, source: GameObject, index: int, ability: ActivatedAbility
    ) -> dict[str, Any]:
        """A ``activate_ability`` legal-action entry (RULE 602), mirroring the
        cast entry: cost label, ``{X}`` prompt, and per-requirement targets
        (marked ``locked`` when a required target has no legal option)."""
        action: dict[str, Any] = {
            "type": "activate_ability",
            "instance_id": source.instance_id,
            "ability_index": index,
            "name": source.name,
            "cost_label": ability.cost.label(),
            "description": ability.description or "",
        }
        mana = ability.cost.mana
        if mana.has_variable:
            action["has_x"] = True
            action["max_x"] = self._max_x_for_mana(player, mana)
        requirements = self._ability_target_requirements(player, ability, source)
        if requirements:
            action["requires_target"] = True
            action["targets"] = requirements
            if not all_requirements_satisfiable(requirements):
                action["locked"] = True
                action["lock_reason"] = "Kein gültiges Ziel im Spiel"
        return action

    def _max_x_for_mana(self, player: Player, mana: "ManaCost") -> int:
        bound = player.mana_pool.total()
        for x in range(bound, -1, -1):
            if player.mana_pool.can_pay(mana.with_x(x), life_available=player.life):
                return x
        return 0

    def _can_pay_activation_cost(
        self, player: Player, source: GameObject, cost: "ActivationCost", x: int
    ) -> bool:
        # {T} needs an untapped source; {Q} a tapped one. Either symbol also
        # needs a non-summoning-sick source unless it has haste (RULE 302.6,
        # 602.5e, 702.10b) — the same rule the mana-tap path enforces.
        if cost.taps_self and (source.tapped or self._summoning_sick_for_tap(source)):
            return False
        if cost.untaps_self and (not source.tapped or self._summoning_sick_for_tap(source)):
            return False
        mana = cost.mana.with_x(x) if cost.mana.has_variable else cost.mana
        if mana.symbols and not player.mana_pool.can_pay(mana, life_available=player.life):
            return False
        if cost.pay_life and player.life < cost.pay_life:
            return False
        if cost.discard and cost.discard != DISCARD_HAND and len(player.hand) < cost.discard:
            return False
        if cost.sacrifice and self._sacrifice_candidate(player, source, cost.sacrifice) is None:
            return False
        if cost.remove_counters:
            kind, count = cost.remove_counters
            if source.counters.get(kind, 0) < count:
                return False
        # A minus loyalty ability can't be activated for more loyalty than the
        # planeswalker has (RULE 606.5c / 118.5).
        if cost.loyalty is not None and cost.loyalty < 0 and source.loyalty < -cost.loyalty:
            return False
        return True

    def _can_pay_additional_cast_cost(
        self, player: Player, obj: GameObject, cost: Optional["ActivationCost"], x: int
    ) -> bool:
        """RULE 601.2b: whether ``player`` can pay a spell's "as an
        additional cost to cast this spell, …" clause right now.

        A narrow subset of `_can_pay_activation_cost` — only the three
        shapes the oracle-text parser recognizes for it (sacrifice/discard/
        pay life); there's no mana or {T}/{Q} portion to an additional cost.
        A ``pay_life`` of `costs.PAY_LIFE_X` checks the spell's own
        announced ``x`` rather than a fixed amount (RULE 601.2b: "pay X
        life" is tied to *this* spell's X, chosen in the same announcement).
        ``obj`` — the spell itself, still sitting in hand at legality-check
        time — is excluded from its own "discard a card" count: it isn't a
        legal discard candidate for its own cost.
        """
        if cost is None:
            return True
        if cost.sacrifice and self._sacrifice_candidate(player, obj, cost.sacrifice) is None:
            return False
        if cost.discard and cost.discard != DISCARD_HAND:
            available = len(player.hand) - (1 if obj in player.hand else 0)
            if available < cost.discard:
                return False
        if cost.pay_life:
            amount = x if cost.pay_life == PAY_LIFE_X else cost.pay_life
            if player.life < amount:
                return False
        return True

    def _pay_additional_cast_cost(
        self,
        player: Player,
        obj: GameObject,
        cost: Optional["ActivationCost"],
        x: int,
    ) -> None:
        """Pay a spell's additional cast cost (RULE 601.2b), assumed already
        checked payable by `_can_pay_additional_cast_cost`/`can_cast`.

        Sacrifice/discard use the same non-interactive auto-choice
        `_can_pay_activation_cost`'s callers do for an activated ability's
        cost (an MVP simplification, not this feature's own decision — see
        `_sacrifice_candidate`'s docstring). ``obj`` — the spell itself — is
        never a valid sacrifice candidate at this point (it's a spell on the
        stack, not a permanent), so passing it as the sacrifice ability's
        "self" source is only ever a no-op fallback.
        """
        if cost is None:
            return
        if cost.sacrifice:
            victim = self._sacrifice_candidate(player, obj, cost.sacrifice)
            if victim is not None:
                self.rules.destroy(victim)
        if cost.discard:
            self.rules.discard(
                player, len(player.hand) if cost.discard == DISCARD_HAND else cost.discard
            )
        if cost.pay_life:
            amount = x if cost.pay_life == PAY_LIFE_X else cost.pay_life
            self.rules.lose_life(player, amount, cause="cost")

    def _sacrifice_candidate(
        self, player: Player, source: GameObject, what: str
    ) -> Optional[GameObject]:
        """A permanent ``player`` can sacrifice to pay ``what`` (RULE 701.17).

        ``"self"`` is the ability's own source; a type word matches the first
        permanent the player controls of that type — an auto-choice, matching
        the MVP's non-interactive discard/search picks.
        """
        if what == "self":
            return source if source in self.state.battlefield else None
        for obj in self.state.permanents_controlled_by(player.id):
            if self._matches_sacrifice_type(obj, what):
                return obj
        return None

    @staticmethod
    def _matches_sacrifice_type(obj: GameObject, what: str) -> bool:
        if what in ("permanent", "another"):
            return True
        if what == "creature":
            return obj.is_creature
        if what == "artifact":
            return obj.card.is_artifact
        if what == "enchantment":
            return obj.card.is_enchantment
        if what == "land":
            return obj.is_land
        return True  # unknown type word → any permanent, so the cost is payable

    def activate_ability(
        self,
        player: Player,
        source: GameObject,
        ability_index: int = 0,
        targets: Optional[list[Any]] = None,
        x: int = 0,
    ) -> None:
        """Pay an activated ability's cost and put it on the stack (RULE 602.2).

        Costs are paid in one go (RULE 601.2h analogue for abilities): tap /
        untap the source, pay mana, pay life, sacrifice, discard, remove
        counters — then the ability goes on the stack to resolve later like any
        other object. Raises ValueError if the ability can't be paid for.
        """
        abilities = source.activated_abilities
        if not 0 <= ability_index < len(abilities):
            raise ValueError(f"{source.name} has no activated ability #{ability_index}")
        ability = abilities[ability_index]
        if not self.can_activate(player, source, ability, x):
            raise ValueError(f"cannot activate {source.name}'s ability")

        cost = ability.cost
        if cost.taps_self:
            self.rules.set_tapped(source, True)
        if cost.untaps_self:
            source.untap()
        mana = cost.mana.with_x(x) if cost.mana.has_variable else cost.mana
        if mana.symbols:
            life_spent = player.mana_pool.pay(mana, life_available=player.life)
            self.rules.lose_life(player, life_spent, cause="cost")
        if cost.pay_life:
            self.rules.lose_life(player, cost.pay_life, cause="cost")
        if cost.sacrifice:
            victim = self._sacrifice_candidate(player, source, cost.sacrifice)
            if victim is not None:
                self.rules.destroy(victim)
        if cost.discard:
            self.rules.discard(player, len(player.hand) if cost.discard == DISCARD_HAND else cost.discard)
        if cost.remove_counters:
            kind, count = cost.remove_counters
            source.add_counters(kind, -count)
        if cost.loyalty is not None:
            # RULE 606.5c: pay by changing loyalty; a loyalty ability is once
            # per turn per planeswalker (RULE 606.3).
            source.add_counters("loyalty", cost.loyalty)
            source.activated_loyalty_this_turn = True

        self.state.stack.append(
            StackItem(
                kind="ability",
                controller_id=player.id,
                effects=[ability],
                description=ability.description or f"{source.name} ability",
                targets=targets,
                x=x,
                source=source,
            )
        )
        # RULE 117.3c: taking an action reclaims priority for its taker.
        self.give_priority(player)

    # ------------------------------------------------------------------
    # Action validation query (docs/02 R4.3)
    # ------------------------------------------------------------------

    def _cast_action(
        self, player: Player, obj: GameObject, face: str = "front", mode: Optional[Any] = None
    ) -> dict[str, Any]:
        """A ``cast_spell`` legal-action entry, flagging ``{X}`` and targets.

        ``has_x`` tells the UI to prompt for a value; ``max_x`` is the
        highest it can offer up front (still re-validated server-side by
        `cast_spell`, which re-checks payability for the chosen ``x``).

        For a *targeting* spell (RULE 115) it reports ``requires_target`` and
        the per-requirement ``targets`` (the legal choices on the current
        board). When no legal target exists the entry is marked ``locked``
        with a reason — the UI renders it with a 🔒 and can't cast it, which
        is the offer-time face of RULE 601.2c.

        ``face="back"``/``"fuse"`` build this for a second castable face
        (see `_face_card`): ``obj`` is temporarily rebound onto that face
        (so targeting/cost read its *own* abilities, not the front's) then
        restored before returning — a pure preview, unlike `cast_spell`'s
        real (and rollback-on-failure) switch.

        ``mode`` (an index into ``obj.spell_modes``, or ``"both"``) tags the
        entry with that mode (RULE 700.2 — see `_modal_cast_actions`, which
        calls this once per mode instead of once per ``obj``) and computes
        ``targets``/``locked`` under that mode's own effects only.
        """
        if face in ("back", "fuse"):
            alt = obj.card.back_face() if face == "back" else obj.card.fuse_face()
            snapshot = self.rules.snapshot_face(obj)
            self.rules.switch_to_face(obj, alt)
            try:
                action = self._cast_action(player, obj)
            finally:
                self.rules.restore_face(obj, snapshot)
            action["face"] = face
            return action
        action = {"type": "cast_spell", "instance_id": obj.instance_id, "name": obj.name}
        if mode is not None:
            action["mode"] = mode
            action["mode_description"] = self._mode_description(obj, mode)
        cost = self.rules.mana_cost_of(obj.card)
        if cost.has_variable:
            action["has_x"] = True
            action["max_x"] = self.max_affordable_x(player, obj)

        # Static cost adjustment (RULE 601.2f): surface base vs. reduced so the
        # UI can show "was {3}, now {1}" and the static-effects panel can
        # attribute it. Only attached when something actually changes the cost.
        reduction, contributors = continuous.cost_reduction_for(self.state, player)
        tax = self.commander_tax(player, obj)
        if (reduction or tax) and cost.raw:
            action["base_cost"] = cost.raw
            action["effective_cost"] = self.effective_cast_cost(player, obj).raw
            if reduction:
                action["cost_reduction"] = contributors
            if tax:
                action["commander_tax"] = tax

        # RULE 601.2b: surface the additional cast cost (if any) so the UI
        # can show it alongside the mana cost, and lock the offer when its
        # non-X portion (sacrifice/discard) isn't payable — the same
        # "offer-time face" treatment missing targets get above. A pending
        # "pay X life" isn't locked here since X isn't chosen until cast.
        additional_cost = getattr(obj, "additional_cast_cost", None)
        if additional_cost is not None and not additional_cost.is_free:
            action["additional_cost_label"] = additional_cost.label()
            if not self._can_pay_additional_cast_cost(player, obj, additional_cost, x=0):
                action["locked"] = True
                action["lock_reason"] = "Zusätzliche Kosten nicht bezahlbar"

        with self._mode_effects_applied(obj, mode):
            requirements = requirements_with_targets(self.state, player.id, obj)
        if requirements:
            action["requires_target"] = True
            action["targets"] = requirements
            if not all_requirements_satisfiable(requirements):
                action["locked"] = True
                action["lock_reason"] = "Kein gültiges Ziel im Spiel"
        return action

    def _modal_cast_actions(self, player: Player, obj: GameObject) -> list[dict[str, Any]]:
        """One ``cast_spell`` action per mode of a modal spell (RULE 700.2),
        plus a combined "both" action when ``obj.spell_modes_or_both``
        (RULE 700.2e) — the same "an offer per option" treatment
        `legal_actions` already gives an MDFC's two faces."""
        modes = list(getattr(obj, "spell_modes", None) or [])
        actions = [self._cast_action(player, obj, mode=i) for i in range(len(modes))]
        if getattr(obj, "spell_modes_or_both", False) and len(modes) == 2:
            actions.append(self._cast_action(player, obj, mode="both"))
        return actions

    def legal_actions(self, player: Player) -> list[dict[str, Any]]:
        """Every action ``player`` may legally take in the current state.

        The single source of truth the UI/bot should consult instead of
        letting any card be "played" with no rule checks (docs/02 R4.3).
        """
        actions: list[dict[str, Any]] = [{"type": "pass_priority"}]
        if self.state.game_over or player.has_lost:
            return actions

        for obj in list(player.hand):
            if self.can_play_land(player, obj):
                actions.append(
                    {"type": "play_land", "instance_id": obj.instance_id, "name": obj.name}
                )
            if self.can_cast(player, obj):
                if getattr(obj, "spell_modes", None):
                    actions.extend(self._modal_cast_actions(player, obj))
                else:
                    actions.append(self._cast_action(player, obj))
            # A second castable face offers its own action(s) too — a modal
            # DFC's back (RULE 712.10), a split card's other half (RULE
            # 709.3), or an Adventure's instant/sorcery half (RULE 715.2b) —
            # a second, independently-gated action for the same hand card.
            if obj.card.back_face() is not None:
                if self.can_play_land(player, obj, face="back"):
                    actions.append(
                        {
                            "type": "play_land",
                            "instance_id": obj.instance_id,
                            "name": obj.card.back_face().name,
                            "face": "back",
                        }
                    )
                if self.can_cast(player, obj, face="back"):
                    actions.append(self._cast_action(player, obj, face="back"))
            # A split card with Fuse offers casting both halves as one spell
            # too (RULE 709.4), for their combined cost.
            if obj.card.fuse_face() is not None and self.can_cast(player, obj, face="fuse"):
                actions.append(self._cast_action(player, obj, face="fuse"))

        for obj in list(player.command):
            if self.can_cast(player, obj):
                if getattr(obj, "spell_modes", None):
                    actions.extend(self._modal_cast_actions(player, obj))
                else:
                    actions.append(self._cast_action(player, obj))

        for obj in list(player.exile):
            # RULE 715.3d / 722.3c: an Adventure creature exiled by its own
            # spell half, or a prepared copy, may be cast from exile.
            if self._castable_from_exile(obj) and self.can_cast(player, obj):
                if getattr(obj, "spell_modes", None):
                    actions.extend(self._modal_cast_actions(player, obj))
                else:
                    actions.append(self._cast_action(player, obj))

        if (
            player is self.state.active_player
            and self.state.current_step == "declare_attackers"
        ):
            # The defenders are the same for every attacker this combat, so
            # compute them once and attach to each attack offer. The UI reads
            # the count to decide a one-step declaration (0/1 defender) vs. a
            # two-step "pick a defender" choice (RULE 508.1a).
            defenders = self.legal_defenders_for(player)
            for obj in self.state.permanents_controlled_by(player.id):
                if self._can_attack(player, obj):
                    actions.append(
                        {
                            "type": "attack",
                            "instance_id": obj.instance_id,
                            "name": obj.name,
                            "legal_defenders": defenders,
                        }
                    )

        for source in self.state.permanents_controlled_by(player.id):
            # A tapped source, or a summoning-sick creature (RULE 302.6), can't
            # tap for mana — don't offer it as a legal action.
            if source.tapped or self._summoning_sick_for_tap(source):
                continue
            options = mana_options_for(source)
            if not options:
                continue
            # Each option is a distinct choice (dual-land "W or U"); the UI
            # shows one button per option so the player picks the colour.
            actions.append(
                {
                    "type": "tap_for_mana",
                    "instance_id": source.instance_id,
                    "name": source.name,
                    "options": [
                        {"index": i, "mana": opt, "label": option_label(opt)}
                        for i, opt in enumerate(options)
                    ],
                }
            )

        # Activated abilities (RULE 602) bound onto permanents this player
        # controls — one offer per payable ability (a fetch land's
        # "{T}, Sacrifice: …", a mana rock, a pinger, …).
        for source in self.state.permanents_controlled_by(player.id):
            for index, ability in enumerate(source.activated_abilities):
                if self.can_activate(player, source, ability):
                    actions.append(self._activate_action(player, source, index, ability))
        return actions

    # ------------------------------------------------------------------
    # Goldfish auto-play (UC3)
    # ------------------------------------------------------------------

    def run_goldfish_turn(self) -> None:
        """Run one solo turn, auto-playing a greedy line (UC3, docs/02 UC5).

        Plays the first land in hand, taps all lands, then casts affordable
        spells cheapest-first, and swings with every able creature. A
        deliberately simple baseline the bot (UC5) can later refine.
        """
        self.begin_turn()
        for phase, step in default_turn_sequence().iter_steps():
            if self.state.game_over:
                return
            self.state.current_phase = phase.name
            self.state.current_step = step.name
            if self.rules.should_skip_step(self.state.active_player, step.name):
                continue

            self.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step.name, phase=phase.name))
            self._execute_step_body(step)

            if step.name == "main1":
                self._goldfish_develop_board()
            elif step.name == "declare_attackers":
                self._goldfish_attack()

            if step.gives_priority:
                self.resolve_until_stable()
            for player in self.state.players:
                player.mana_pool.empty()
            self.state.fire_event(GameEvent(EventType.STEP_END, step=step.name, phase=phase.name))

        self.state.fire_event(
            GameEvent(EventType.TURN_END, player_id=self.state.active_player.id)
        )

    def _goldfish_develop_board(self) -> None:
        active = self.state.active_player
        land = next((o for o in active.hand if self.can_play_land(active, o)), None)
        if land is not None:
            self.play_land(active, land)
        for source in self.state.permanents_controlled_by(active.id):
            if (
                not source.tapped
                and mana_options_for(source)
                and not self._summoning_sick_for_tap(source)  # RULE 302.6
            ):
                self.tap_for_mana(active, source)  # option 0 (greedy)
        # Cast affordable non-land spells cheapest first.
        castable = sorted(
            (o for o in active.hand if not o.card.is_land),
            key=lambda o: o.card.converted_mana_cost,
        )
        for obj in castable:
            if getattr(obj, "spell_modes", None):
                # RULE 700.2: a modal spell needs a mode choice (`mode=`)
                # before `has_legal_targets` even means anything — the
                # greedy auto-play heuristic doesn't pick modes, so it skips
                # these rather than raise mid-autoplay.
                continue
            # Skip a targeting spell with nothing legal to point at (RULE
            # 601.2c) rather than have `cast_spell` raise mid-autoplay.
            if self.can_cast(active, obj) and self.has_legal_targets(active, obj):
                self.cast_spell(active, obj)
                self.resolve_until_stable()

    def _goldfish_attack(self) -> None:
        active = self.state.active_player
        if not self.state.non_active_players():
            return
        attackers = [
            o
            for o in self.state.permanents_controlled_by(active.id)
            if self._can_attack(active, o)
        ]
        if attackers:
            self.declare_attackers(active, attackers)
