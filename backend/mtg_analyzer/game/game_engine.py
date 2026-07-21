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

from ..models.card import Card
from ..models.events import EventType, GameEvent
from ..models.game_object import GameObject, Zone
from ..models.game_state import GameState, StackItem
from ..models.mana_cost import ManaCost
from ..models.player import Player
from . import combat, condition_query, continuous
from .costs import (
    DISCARD_HAND,
    PAY_LIFE_X,
    REMOVE_COUNTERS_ANY,
    REMOVE_COUNTERS_X,
    ActivationCost,
    parse_activation_cost,
)
from .effects import ActivatedAbility
from .mana_abilities import (
    hand_mana_abilities_for,
    mana_abilities_for,
    option_label,
    restriction_predicate_for_activation,
    restriction_predicate_for_cast,
    validate_color_split,
)
from .phases import GamePhase, GameStep, default_turn_sequence
from .rules_engine import RulesEngine
from .targeting import (
    all_requirements_satisfiable,
    legal_targets,
    requirements_with_targets,
    spell_target_specs,
)
from .graveyard_cast import graveyard_cast_grant_for
from .top_library import (
    may_cast_spell_from_top_of_library,
    may_play_land_from_top_of_library,
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
            # RULE 500.7: a queued extra turn is taken right after this one,
            # before the normal next player — pop the front of the queue and
            # hand that player the turn instead of rotating the round-robin.
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
        active = self.state.active_player
        active.lands_played_this_turn = 0
        active.extra_land_plays_this_turn = 0
        self.state.spells_cast_this_turn[active.id] = 0
        self.state.cards_drawn_this_turn[active.id] = 0
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
        if self.state.current_step == "declare_attackers":
            self._enforce_attacks_if_able()
            self._fire_player_attacked_events()
        if not self._turn_steps or self._cursor >= len(self._turn_steps):
            self.state.fire_event(
                GameEvent(EventType.TURN_END, player_id=self.state.active_player.id)
            )
            self._begin_turn_steps()
        phase, step = self._turn_steps[self._cursor]
        self._cursor += 1
        self._run_step(phase, step)
        return (phase.name, step.name)

    def _enforce_attacks_if_able(self) -> None:
        """RULE 508.1a: a creature under an "attacks each combat if able"
        static must be declared as an attacker if it's able to.

        `declare_attackers` is additive (the UI declares one creature at a
        time) and has no "I'm done" signal of its own, so the natural gate is
        here — the moment the caller tries to leave the declare-attackers
        step. Checked against `_can_attack` before anything about this combat
        (blocks, damage) has changed the board, so a creature this flag
        applies to is still evaluated on the same terms `declare_attackers`
        itself would have accepted.
        """
        active = self.state.active_player
        for obj in self.state.permanents_controlled_by(active.id):
            if (
                combat.has(obj, "attacks_if_able")
                and not obj.attacking
                and self._can_attack(active, obj)
            ):
                raise ValueError(f"{obj.name} attacks each combat if able")

    def _fire_player_attacked_events(self) -> None:
        """RULE 506.4's "a player attacks you with one or more creatures" —
        see `EventType.PLAYER_ATTACKED`'s docstring for why this needs its
        own aggregate event rather than reusing `ATTACKS`. Groups every
        currently-attacking creature by (its controller, the player it's
        attacking) and fires one event per group.
        """
        counts: dict[tuple[str, str], int] = {}
        for obj in self.state.battlefield:
            if not obj.attacking:
                continue
            spec = obj.combat_defender
            if not spec or spec.get("kind") != "player":
                continue
            key = (obj.controller_id, spec["id"])
            counts[key] = counts.get(key, 0) + 1
        for (attacker_id, defender_id), count in counts.items():
            self.state.fire_event(
                GameEvent(
                    EventType.PLAYER_ATTACKED,
                    attacking_player_id=attacker_id,
                    defending_player_id=defender_id,
                    count=count,
                )
            )

    def _run_step(self, phase: GamePhase, step: GameStep) -> None:
        self.state.current_phase = phase.name
        self.state.current_step = step.name

        # Rule-override skips (docs/07 PART 8): "skip your untap step", etc.
        if self.rules.should_skip_step(self.state.active_player, step.name):
            return

        self.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step.name, phase=phase.name))
        self._fire_delayed_triggers(step.name)
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

    # -- Individual step bodies -----------------------------------------

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
        # RULE 502.3-adjacent (Winter Orb): "players can't untap more than
        # N lands during their untap steps" — a flat, unscoped cap that
        # applies to every player's untap step identically, including the
        # static's own controller. ``None`` means unrestricted (the
        # overwhelmingly common case), so this never changes anything for
        # a board without one; an auto-pick (first N lands found) untaps up
        # to the cap, the same non-interactive MVP simplification
        # `_sacrifice_candidate`'s callers already make elsewhere.
        land_cap = continuous.untap_cap_for_lands(self.state)
        lands_untapped = 0
        for obj in self.state.permanents_controlled_by(active.id):
            if (
                not self.rules.should_skip_step(active, "untap_permanents")
                and not continuous.has_no_untap_static(self.state, obj)
                and not (obj.is_land and land_cap is not None and lands_untapped >= land_cap)
            ):
                # RULE 502.3-adjacent: "This artifact doesn't untap during
                # your untap step." (Basalt Monolith/Grim Monolith/Mana
                # Vault) — a separate "{N}: Untap this artifact." activated
                # ability (or Mana Vault's upkeep trigger) is unaffected,
                # it's a different code path (an ordinary `untap` effect).
                obj.untap()
                if obj.is_land:
                    lands_untapped += 1
            # Controlled since the turn began → no longer summoning sick.
            obj.summoning_sick = False
            # RULE 606.3: a new loyalty ability may be activated this turn.
            obj.activated_loyalty_this_turn = False
            # RULE 500.4-adjacent: a `GraveyardCastPermissionEffect`'s "once
            # during each of your turns" restriction (Lurrus-shaped) resets
            # the same way.
            obj.graveyard_casts_this_turn = 0
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
        from . import copy_mechanics

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
            if obj.temp_protections:
                obj.temp_protections.clear()
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
        if ended_effects:
            self.recompute_continuous_effects()  # re-derive P/T sans the pumps
        self._clear_combat()
        # RULE 601.3b analogue: a temporary "play until end of your next
        # turn" permission (Light Up the Stage-shaped impulsive draw) lapses
        # exactly at this cleanup once its granting turn is no longer
        # "this turn or your next" — i.e. once a turn has already passed
        # since it was granted.
        self.state.temp_play_permissions = {
            iid: turn for iid, turn in self.state.temp_play_permissions.items()
            if turn >= self.state.turn_number
        }
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
        elif kind == "land_tapped":
            # RULE 614.1: a shock land's "pay life to stay untapped" choice.
            self.rules.resolve_land_tapped_choice(None if declined else str(answer))
        elif kind == "land_tapped_bonus":
            # RULE 614.1's "you may have this land enter tapped. If you do,
            # <bonus>." (Mariposa Military Base) — the mirror-image choice:
            # untapped by default, tap it for the bonus instead.
            self.rules.resolve_land_tapped_bonus_choice(None if declined else str(answer))
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
        elif kind in ("choose_creature_type", "choose_color", "choose_named_mode"):
            # RULE 601.2b(-adjacent): a mandatory pick (no "decline" option
            # is ever offered) — the option id is a creature-type name, a
            # WUBRG colour letter, or (``choose_named_mode``) a lowercase
            # mode slug (Struggle for Project Purity's "choose Brotherhood
            # or Enclave"); `resolve_enter_choice` defaults an
            # unrecognized/missing answer to the first offered option.
            self.rules.resolve_enter_choice(None if declined else str(answer))
        elif kind == "counter_unless_pays":
            # RULE 601: "pay" saves the target spell, anything else counters it.
            self.rules.resolve_counter_unless_pays_choice(None if declined else str(answer))
        elif kind == "ward":
            # RULE 702.21: "pay" saves the caster's spell/ability, anything
            # else counters it — the caster decides, not the target's
            # controller (unlike counter_unless_pays).
            self.rules.resolve_ward_choice(None if declined else str(answer))
        elif kind == "commander_zone":
            # RULE 903.9a/9b: "command" moves the commander to the command
            # zone instead of wherever it landed/was headed; anything else
            # leaves it there.
            self.rules.resolve_commander_zone_choice(None if declined else str(answer))
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
        # RULE 505.5b: from hand, always — or from the top of the library
        # (Oracle of Mul Daya-shaped) when some permanent grants that.
        in_playable_zone = (
            obj in player.hand
            or (
                bool(player.library)
                and obj is player.library[-1]
                and may_play_land_from_top_of_library(player, self.state)
            )
            or (obj.zone == Zone.EXILE and self._has_temp_play_permission(obj, player))
        )
        return (
            card is not None
            and player is self.state.active_player
            and self._in_main_phase()
            and not self.state.stack
            and player.lands_played_this_turn < (
                player.max_lands_per_turn
                + continuous.extra_land_plays_for(self.state, player)
                + player.extra_land_plays_this_turn
            )
            and in_playable_zone
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
        # Zone-agnostic (not just hand) so a land can be played from the top
        # of the library (Oracle of Mul Daya-shaped, `can_play_land` above) —
        # ``obj.zone`` is always accurate (set on creation/every zone move),
        # the same "read the object's own zone" idiom
        # `RulesEngine._remove_from_current_zone` uses for casting.
        player.remove_from_zone(obj, obj.zone)
        obj.summoning_sick = True
        # RULE 614.1: a tap-land enters the battlefield tapped — including a
        # shock/check/fast/slow land's conditional shape (payment choice or
        # board-state check), resolved by `enter_land_tapped`.
        self.rules.enter_land_tapped(obj)
        self.state.add_to_battlefield(obj)
        player.lands_played_this_turn += 1
        self.state.record_stat(player.id, "land", name=obj.name)
        self.state.fire_event(
            GameEvent(
                EventType.LAND_PLAYED,
                player_id=player.id,
                card_id=obj.card.id,
                land=obj.name,
                # A "whenever you play another land" trigger (City of
                # Traitors) needs to exclude its own play event via
                # `effect_binder`'s "group"/"other" subject condition.
                instance_id=obj.instance_id,
            )
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

    def _has_temp_play_permission(self, obj: GameObject, player: Player) -> bool:
        """RULE 601.3b analogue: a temporary "you may play this card"
        permission (Light Up the Stage-shaped impulsive draw,
        `RulesEngine.exile_with_play_permission`,
        `GameState.temp_play_permissions`) — swept once its "until the end
        of your next turn" (or, Ragavan/Mnemonic Betrayal-shaped, "until
        end of turn") window lapses (`_step_cleanup`), so mere presence
        here means "still valid" without re-checking the turn number.

        Also checks `GameState.temp_play_permission_player`: the permission
        belongs to a *specific* player, not to whoever's zone the card
        happens to sit in (Ragavan exiles from the player it damaged, but
        only its own controller may cast the result) — an absent entry
        (an older snapshot predating that dict, or a caller that never set
        it) defaults to "anyone may", matching every pre-existing single-
        player grant's behaviour.
        """
        if obj.instance_id not in self.state.temp_play_permissions:
            return False
        holder_id = self.state.temp_play_permission_player.get(obj.instance_id)
        return holder_id is None or holder_id == player.id

    @staticmethod
    def _graveyard_cast_keyword(obj: GameObject) -> Optional[str]:
        """Which alt-cost-from-graveyard keyword ``obj`` carries — ``"flashback"``
        (RULE 702.34) or ``"escape"`` (RULE 702.138) — or ``None``. The two
        share the same "cast from the graveyard for an alternative cost"
        zone gate; only what that cost is (and whether the card is exiled
        after resolving, Flashback only) differs.
        """
        params = getattr(obj, "parametric_keywords", None) or {}
        if "flashback" in params:
            return "flashback"
        if "escape" in params:
            return "escape"
        return None

    @classmethod
    def _castable_from_graveyard(cls, obj: GameObject) -> bool:
        """Whether an object sitting in a graveyard is castable from there
        (RULE 702.34/702.138) — unlike `_castable_from_exile`, this needs no
        extra per-object flag: the keyword's mere presence is enough, since
        Flashback/Escape are always-available alternative costs, not a
        one-shot grant from some other effect.
        """
        return cls._graveyard_cast_keyword(obj) is not None

    def _graveyard_cast_permission(self, player: Player, obj: GameObject) -> bool:
        """Whether ``obj`` — sitting in ``player``'s own graveyard — is
        castable from there via a standing permission some other permanent
        grants (Lurrus of the Dream-Den-shaped, `game/graveyard_cast.py`) —
        the open-ended sibling of `_castable_from_graveyard`'s closed
        Flashback/Escape keyword vocabulary. Cast this way, ``obj`` pays its
        own normal mana cost (`effective_cast_cost` only substitutes an
        alternative cost for a recognised graveyard keyword, so this falls
        through to the printed cost unchanged).
        """
        return graveyard_cast_grant_for(player, self.state, obj.card) is not None

    def _castable_from_library(self, player: Player, obj: GameObject) -> bool:
        """Whether the top-of-library card ``obj`` is castable from there
        right now (Oracle of Mul Daya/Glarb, Calamity's Augur-shaped — see
        `game/top_library.py`). Only ever called for ``player.library[-1]``
        (the top); a card any deeper in the library is never castable."""
        return may_cast_spell_from_top_of_library(player, self.state, obj.card)

    @staticmethod
    def _flashback_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.34b: ``obj``'s Flashback cost as a `ManaCost`, or
        ``None`` if it carries no Flashback keyword (or one with no parsed
        cost)."""
        param = (getattr(obj, "parametric_keywords", None) or {}).get("flashback")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))

    @staticmethod
    def _escape_cost(obj: GameObject) -> Optional["ActivationCost"]:
        """RULE 702.138b: ``obj``'s Escape cost — mana plus "exile N other
        cards from your graveyard" — as a parsed `ActivationCost`, or
        ``None`` if it carries no Escape keyword (or one with no parsed
        cost). Uses the full activated-ability cost grammar (`game/costs.
        parse_activation_cost`), not just `ManaCost`, since Escape's cost
        has a non-mana component the mana model alone can't hold.
        """
        param = (getattr(obj, "parametric_keywords", None) or {}).get("escape")
        if not param or not param.get("cost"):
            return None
        return parse_activation_cost(str(param["cost"]))

    def can_cast(
        self,
        player: Player,
        obj: GameObject,
        x: int = 0,
        face: str = "front",
        kicked: int = 0,
        buyback: bool = False,
        free: bool = False,
    ) -> bool:
        """RULE 601/602.5: is this spell castable by ``player`` right now?

        ``x`` is the value that would be announced for a cost containing
        ``{X}`` (ignored otherwise) — pass 0 (the default) to check bare
        castability, or a specific value to check whether *that* X is
        affordable. ``face="back"``/``"fuse"`` check a second castable face
        (see `_face_card`) instead, without mutating ``obj`` — a preview,
        used by `legal_actions` to decide whether to offer casting it.
        ``kicked`` is how many times Kicker (RULE 702.33) would be paid — 0
        (the default), or a value validated against the object's own
        ``kicker`` parametric keyword (see `_kicker_cost`): any nonzero value
        without one is illegal, and only Multikicker permits more than 1.
        ``buyback`` is whether Buyback's own additional cost (RULE 702.27)
        would also be paid — illegal (``False``) for an object with no
        ``buyback`` parametric keyword. ``free=True`` checks the RULE
        601.2f-adjacent condition-gated free-cast alternative cost instead
        of paying the mana cost at all ("If you control a commander, you may
        cast this spell without paying its mana cost." — Deadly Rollick/
        Deflecting Swat/Fierce Guardianship-shaped): legal only when ``obj``
        carries a `free_cast_condition` (`game/effect_binder.py`) whose
        condition currently holds (`condition_query.
        free_cast_condition_holds`); illegal for an object with no such
        condition at all.
        """
        # A commander may be cast from the command zone as well as the
        # hand (RULE 903.6, 903.8) — commander tax (RULE 903.8, +{2} per
        # previous cast from there) isn't modeled yet. An Adventure creature
        # or a prepared copy sitting in exile may also be castable — see
        # `_castable_from_exile`. A graveyard card with Flashback/Escape may
        # be castable from there too — see `_castable_from_graveyard` — as
        # may one some other permanent grants standing permission for
        # (Lurrus of the Dream-Den-shaped) — see `_graveyard_cast_permission`.
        # The top of the library may be castable too (Oracle of Mul Daya/
        # Glarb, Calamity's Augur-shaped) — see `_castable_from_library`;
        # only the top card itself ever qualifies, never anything deeper.
        in_castable_zone = (
            obj in player.hand
            or obj in player.command
            or (obj in player.exile and self._castable_from_exile(obj))
            or (obj.zone == Zone.EXILE and self._has_temp_play_permission(obj, player))
            or (obj in player.graveyard and self._castable_from_graveyard(obj))
            or (obj in player.graveyard and self._graveyard_cast_permission(player, obj))
            or (
                bool(player.library)
                and obj is player.library[-1]
                and self._castable_from_library(player, obj)
            )
        )
        if not in_castable_zone:
            return False
        card = self._face_card(obj, face)
        if card is None or card.is_land:
            return False
        # RULE 601-area: "Each player can't cast more than N spells each
        # turn." (Eidolon of Rhetoric/Rule of Law/Archon of Emeria) — a flat
        # cap tracked per player, reset each turn (`state.spells_cast_this_
        # turn`, already maintained by `RulesEngine._track_spell_cast`).
        max_spells = continuous.max_spells_per_turn(self.state)
        if max_spells is not None and self.state.spells_cast_this_turn.get(player.id, 0) >= max_spells:
            return False
        # Timing (RULE 601.3a): sorcery-speed spells need an empty stack,
        # the player's own main phase, and their priority. RULE 702.8b:
        # Flash lets an otherwise-sorcery-speed card (Embercleave, The
        # Wandering Emperor) be cast any time its controller could cast an
        # instant instead — checked off the *object* (`combat.has`, the same
        # printed+intrinsic+granted keyword union combat reads elsewhere),
        # not just the card, so a temporary flash grant works too. A
        # `conditional_flash` (RULE 702.8b's "as though it had flash if
        # <condition>") grants the same permission only while its condition
        # holds, checked live (`condition_query`).
        conditional_flash = getattr(obj, "conditional_flash", None)
        has_conditional_flash = (
            conditional_flash is not None
            and condition_query.conditional_flash_holds(conditional_flash, obj, self.state)
        )
        # "You may cast spells this turn as though they had flash." (Borne
        # Upon a Wind-shaped) — a temporary, player-scoped blanket flash
        # grant (`GameState.temp_flash_until_turn`, `GrantFlashUntilEndOf
        # TurnEffect`), independent of any keyword/condition on the object
        # itself.
        has_temp_flash = self.state.temp_flash_until_turn.get(player.id) == self.state.turn_number
        sorcery_speed = not (
            card.is_instant or combat.has(obj, "flash") or has_conditional_flash or has_temp_flash
        )
        if sorcery_speed:
            if player is not self.state.active_player:
                return False
            if not self._in_main_phase() or self.state.stack:
                return False
        if kicked:
            kicker_cost = self._kicker_cost(obj)
            if kicker_cost is None:
                return False
            kicker_param = (getattr(obj, "parametric_keywords", None) or {}).get("kicker") or {}
            if kicked > 1 and not kicker_param.get("multi"):
                return False
        if buyback and self._buyback_cost(obj) is None:
            return False
        if obj in player.graveyard and self._graveyard_cast_keyword(obj) == "escape":
            # RULE 702.138b: "exile N *other* cards from your graveyard" —
            # ``obj`` itself doesn't count toward that N.
            escape_cost = self._escape_cost(obj)
            if escape_cost is None:
                return False
            if len(player.graveyard) - 1 < escape_cost.exile_from_graveyard:
                return False
        if free:
            free_cast_condition = getattr(obj, "free_cast_condition", None)
            if free_cast_condition is None:
                return False
            if not condition_query.free_cast_condition_holds(free_cast_condition, obj, self.state):
                return False
        elif obj.instance_id in self.state.free_cast_instance_ids:
            # RULE 702.88b Rebound's own free-cast window
            # (`RulesEngine.grant_rebound_free_cast_window`) — already
            # armed for this specific instance, no mana check needed.
            pass
        else:
            cost = self.effective_cast_cost(player, obj, x, face=face, kicked=kicked, buyback=buyback)
            allows_restriction = restriction_predicate_for_cast(obj, has_x=cost.has_variable)
            wildcard = self.state.mana_wildcard_permission.get(obj.instance_id)
            if not player.mana_pool.can_pay(
                cost, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard
            ):
                return False
        # RULE 601.2b: an "as an additional cost to cast this spell, …"
        # clause is a separate legality gate from the mana cost above — a
        # sacrifice/discard/life payment that isn't payable makes the spell
        # uncastable even with the mana in hand.
        return self._can_pay_additional_cast_cost(
            player, obj, getattr(obj, "additional_cast_cost", None), x
        )

    @staticmethod
    def _buyback_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.27: ``obj``'s Buyback cost as a `ManaCost`, or ``None``
        if it carries no Buyback keyword (or one with no parsed cost)."""
        param = (getattr(obj, "parametric_keywords", None) or {}).get("buyback")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))

    @staticmethod
    def _kicker_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.33: ``obj``'s Kicker cost as a `ManaCost`, or ``None`` if
        it carries no Kicker/Multikicker keyword (or one with no parsed
        cost). Multikicker shares this same ``kicker`` param shape — see
        `effect_binder.attach_keyword` — distinguished only by its ``multi``
        flag, which callers check separately.
        """
        param = (getattr(obj, "parametric_keywords", None) or {}).get("kicker")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))

    def max_affordable_kicker(self, player: Player, obj: GameObject) -> int:
        """The highest number of times ``player`` could pay Kicker and still
        cast ``obj`` (RULE 702.33) — 0 or 1 for a plain Kicker, 0..N for
        Multikicker. Mirrors `max_affordable_x`'s "scan down from an upper
        bound" shape; the interaction with an independently announced ``{X}``
        isn't modeled (an MVP simplification — no card needs both solved
        jointly today).
        """
        kicker_cost = self._kicker_cost(obj)
        if kicker_cost is None:
            return 0
        kicker_param = (getattr(obj, "parametric_keywords", None) or {}).get("kicker") or {}
        upper = player.mana_pool.total() if kicker_param.get("multi") else 1
        for kicked in range(upper, -1, -1):
            if self.can_cast(player, obj, kicked=kicked):
                return kicked
        return 0

    def effective_cast_cost(
        self,
        player: Player,
        obj: GameObject,
        x: int = 0,
        face: str = "front",
        kicked: int = 0,
        buyback: bool = False,
    ) -> "ManaCost":
        """``obj``'s mana cost after static cost adjustments (RULE 601.2f/903.8).

        Starts from the printed cost (with ``{X}`` resolved), applies the net
        generic reduction from "spells you cast cost {N} less/more" statics in
        play, then adds commander tax ({2} per previous cast of this commander
        from the command zone, RULE 903.8) when it's being cast from there.
        Generic-only and floored at zero — the common, safe case. ``face``
        previews a second castable face's own printed cost (see
        `_face_card`) without mutating ``obj``. ``kicked`` adds Kicker's own
        cost (RULE 702.33b) once per time paid, and ``buyback`` adds
        Buyback's own cost once (RULE 702.27), both via `ManaCost.add` — not
        subject to the generic-only reduction above, since each is a
        distinct additional cost, not part of the printed one.

        RULE 601.2b/702.34b: a card actually sitting in ``player``'s
        graveyard (only reachable at all via `_castable_from_graveyard`) is
        cast for its alternative Flashback/Escape cost *instead of* the
        printed one — a substitution, not an addition, applied before the
        reduction/tax below so those still apply on top of it as usual.
        """
        card = self._face_card(obj, face) or obj.card
        if obj in player.graveyard:
            keyword = self._graveyard_cast_keyword(obj)
            if keyword == "flashback":
                alt_cost = self._flashback_cost(obj)
            elif keyword == "escape":
                escape_cost = self._escape_cost(obj)
                alt_cost = escape_cost.mana if escape_cost is not None else None
            else:
                alt_cost = None
            cost = alt_cost if alt_cost is not None else self.rules.mana_cost_of(card)
        else:
            cost = self.rules.mana_cost_of(card)
        if cost.has_variable:
            cost = cost.with_x(x)
        cost = self._adjust_cost(cost, player, obj)
        tax = self.commander_tax(player, obj)
        if tax:
            cost = cost.increase_generic(tax)
        if kicked:
            kicker_cost = self._kicker_cost(obj)
            if kicker_cost is not None:
                for _ in range(kicked):
                    cost = cost.add(kicker_cost)
        if buyback:
            buyback_cost = self._buyback_cost(obj)
            if buyback_cost is not None:
                cost = cost.add(buyback_cost)
        return cost

    @staticmethod
    def commander_tax(player: Player, obj: GameObject) -> int:
        """Generic surcharge to cast ``obj`` from the command zone (RULE 903.8).

        {2} for each previous time this commander was cast from the command
        zone; 0 for a normal spell or a commander being cast from hand."""
        if obj.is_commander and obj in player.command:
            return 2 * player.commander_casts.get(obj.instance_id, 0)
        return 0

    def _adjust_cost(self, cost: "ManaCost", player: Player, obj: Optional[GameObject] = None) -> "ManaCost":
        """Apply the net static generic adjustment (reduce or increase).

        ``obj``, when given, also folds in a Delve/Affinity-shaped reduction
        printed on the card itself (`continuous.self_cost_reduction_for`) —
        distinct from a battlefield permanent's "your spells cost less".
        """
        reduction, _ = continuous.cost_reduction_for(self.state, player, obj)
        if obj is not None:
            self_reduction, _ = continuous.self_cost_reduction_for(obj, self.state)
            reduction += self_reduction
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
        kicked: int = 0,
        buyback: bool = False,
        target_groups: Optional[list[list[Any]]] = None,
        free: bool = False,
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

        ``kicked`` is how many times to pay Kicker (RULE 702.33b) — see
        `can_cast`/`effective_cast_cost`; recorded on ``obj.kicker_count``
        once the cast succeeds. ``buyback`` is whether to pay Buyback's
        additional cost (RULE 702.27) — recorded on ``obj.buyback_paid``,
        consulted by `RulesEngine.resolve_top_of_stack` to route the spell
        back to hand instead of the graveyard.

        ``target_groups``, when given, partitions ``targets`` per targeting
        effect (`StackItem.target_groups`) — needed only when ``obj`` carries
        2+ *different* targeting effects; omitted (``None``), every effect
        reads ``targets`` directly, unchanged from before this existed.
        """
        if face in ("back", "fuse"):
            if not self.can_cast(player, obj, x, face=face, kicked=kicked, buyback=buyback, free=free):
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
                result = self._cast_current_face(
                    player, obj, targets, x, mode=mode, kicked=kicked, buyback=buyback,
                    target_groups=target_groups, free=free,
                )
            except Exception:
                self.rules.restore_face(obj, snapshot)
                raise
            if is_adventure_cast:
                obj.adventure_snapshot = snapshot
            return result
        return self._cast_current_face(
            player, obj, targets, x, mode=mode, kicked=kicked, buyback=buyback,
            target_groups=target_groups, free=free,
        )

    def _effects_for_mode(self, obj: GameObject, mode: Any) -> list[Any]:
        """The `GameEffect`s a modal spell's chosen ``mode`` resolves with.

        ``mode`` is an index into ``obj.spell_modes`` (only when
        ``obj.spell_modes_choose == 1``), the literal ``"both"`` (RULE
        700.2e — both modes' effects, in printed order), or a list/tuple of
        distinct indices: exactly ``obj.spell_modes_choose`` of them (RULE
        700.2 "choose *N*", ``N>=2``), or at least that many when
        ``obj.spell_modes_at_least`` (RULE 700.2 "choose *N* or more —",
        ``N>=1``) — `_modal_cast_actions` offers one action per legal
        combination either way. Combined effects always run in *printed*
        order, not the order given in ``mode``. Raises for an out-of-range/
        wrong-length/duplicate index, or a "both" not actually offered
        (`obj` has no ``spell_modes`` at all, or isn't
        ``spell_modes_or_both``, or doesn't have exactly the two modes RULE
        700.2e's "or both" implies).
        """
        modes = list(getattr(obj, "spell_modes", None) or [])
        choose = getattr(obj, "spell_modes_choose", 1)
        at_least = getattr(obj, "spell_modes_at_least", False)
        if mode == "both":
            if not getattr(obj, "spell_modes_or_both", False) or len(modes) != 2:
                raise ValueError(f"{obj.name} has no 'choose both' mode")
            effects: list[Any] = []
            for entry in modes:
                effects.extend(entry["effects"])
            return effects
        if isinstance(mode, (list, tuple)):
            indices = list(mode)
            count_ok = len(indices) >= choose if at_least else len(indices) == choose
            valid = (
                count_ok
                and len(set(indices)) == len(indices)
                and all(isinstance(i, int) and 0 <= i < len(modes) for i in indices)
            )
            if not valid:
                raise ValueError(f"{obj.name}: invalid mode combination {mode!r}")
            effects = []
            for i in sorted(indices):
                effects.extend(modes[i]["effects"])
            return effects
        if choose != 1 or not isinstance(mode, int) or not (0 <= mode < len(modes)):
            raise ValueError(f"{obj.name}: invalid mode {mode!r}")
        return list(modes[mode]["effects"])

    def _mode_description(self, obj: GameObject, mode: Any) -> str:
        """A modal spell's chosen ``mode`` as UI label text."""
        modes = list(getattr(obj, "spell_modes", None) or [])
        if mode == "both":
            return " + ".join(entry.get("description", "") for entry in modes)
        if isinstance(mode, (list, tuple)):
            return " + ".join(
                modes[i].get("description", "") for i in sorted(mode) if 0 <= i < len(modes)
            )
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
        kicked: int = 0,
        buyback: bool = False,
        target_groups: Optional[list[list[Any]]] = None,
        free: bool = False,
    ):
        """The common cast body, reading whatever `obj.card` currently is.

        ``free=True`` (RULE 601.2f-adjacent condition-gated free-cast
        alternative cost — see `can_cast`) skips mana payment entirely via
        `RulesEngine.cast_without_paying`, instead of the ordinary
        `RulesEngine.cast_spell` mana-cost path.
        """
        with self._mode_effects_applied(obj, mode):
            if not self.can_cast(player, obj, x, kicked=kicked, buyback=buyback, free=free):
                raise ValueError(f"{player.id} cannot cast {obj.name} now")
            # RULE 601.2c: a spell that requires a target can't be cast unless
            # a legal target is available — the same check that locks the offer.
            if not self.has_legal_targets(player, obj):
                raise ValueError(f"{obj.name} has no legal target")
            # RULE 903.8: record this command-zone cast so the next one is
            # taxed {2} more. Read *before* the cast moves the card off the
            # command zone.
            from_command = obj.is_commander and obj in player.command
            # RULE 702.34a: likewise read *before* the cast moves the card
            # off the graveyard — only a Flashback cast is exiled instead of
            # going to the graveyard on resolution (Escape has no such
            # after-resolving clause).
            graveyard_keyword = (
                self._graveyard_cast_keyword(obj) if obj in player.graveyard else None
            )
            # Lurrus-shaped standing permission, read *before* the cast for
            # the same "off the object's current zone" reason as above — only
            # relevant when no closed-vocabulary keyword already covers it.
            graveyard_grant = (
                graveyard_cast_grant_for(player, self.state, obj.card)
                if obj in player.graveyard and graveyard_keyword is None
                else None
            )
            if free:
                result = self.rules.cast_without_paying(player, obj, targets)
            else:
                cost = self.effective_cast_cost(player, obj, x, kicked=kicked, buyback=buyback)
                result = self.rules.cast_spell(player, obj, targets, x, cost=cost, target_groups=target_groups)
            # RULE 601.2b/601.2h: an additional cost is paid as part of
            # casting, not resolving — so it stays paid even if the spell is
            # later countered. Paid *after* the mana cost (just above) so a
            # Phyrexian-mana payment reads the player's life before any
            # "pay N life" additional cost reduces it.
            self._pay_additional_cast_cost(
                player, obj, getattr(obj, "additional_cast_cost", None), x
            )
            # RULE 702.33b: record how many times Kicker was paid, so a
            # resolve-time effect that reads "if this spell was kicked" (a
            # follow-up, not yet parsed) has something to consult.
            obj.kicker_count = kicked
            # RULE 702.27a: record whether Buyback was paid — consulted by
            # `RulesEngine.resolve_top_of_stack` to route the spell back to
            # hand instead of the graveyard.
            obj.buyback_paid = buyback
            # RULE 702.34a: record a Flashback cast — consulted by
            # `RulesEngine.resolve_top_of_stack` to exile the spell instead
            # of returning it to the graveyard on resolution.
            obj.cast_via_flashback = graveyard_keyword == "flashback"
            # RULE 702.138b: Escape's own "exile N other cards from your
            # graveyard" cost, paid as part of casting (like any other
            # additional cost) now that ``obj`` itself has left the
            # graveyard (so it can't accidentally exile itself).
            if graveyard_keyword == "escape":
                escape_cost = self._escape_cost(obj)
                if escape_cost is not None and escape_cost.exile_from_graveyard:
                    self._pay_escape_graveyard_cost(player, escape_cost.exile_from_graveyard)
            # RULE 500.4-adjacent: record this use of a Lurrus-shaped
            # "once during each of your turns" standing permission against
            # its *granting* permanent, not the cast card — untapped again
            # by `_step_untap` alongside `activated_loyalty_this_turn`.
            if graveyard_grant is not None and graveyard_grant.source is not None:
                graveyard_grant.source.graveyard_casts_this_turn += 1
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
            # RULE 702.107: Dethrone's own per-firing dynamic check — see
            # `RulesEngine.check_dethrone` for why this can't go through the
            # ordinary annihilator/afflict/bushido `TriggeredAbility` path.
            self.rules.check_dethrone(obj)

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
            and obj in self.state.permanents()  # RULE 702.26c: excludes a phased-out creature
            and not obj.tapped
            # Haste (RULE 702.10b) lets a creature attack the turn it arrives.
            and (not obj.summoning_sick or combat.has_haste(obj))
            # Defender (RULE 702.3b) can never attack.
            and not combat.has_defender(obj)
            # "~ can't attack." / "enchanted creature can't attack [or
            # block]." — a synthetic layer-6 flag, not a real keyword; see
            # `parser/oracle/catalogue/static_handlers.py`'s combat-
            # restriction family.
            and not combat.has(obj, "cant_attack")
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

        # RULE 702.130/702.45/702.23 (afflict/bushido/rampage): capture, before
        # any mutation, which attackers are transitioning from unblocked to
        # blocked this call — BECOMES_BLOCKED fires once per such attacker,
        # never once per blocker, only on that transition (RULE 509.5).
        newly_blocked = [
            attacker
            for attacker in {attacker.instance_id: attacker for _, attacker in resolved}.values()
            if not attacker.blocked_by
        ]

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

        for attacker in newly_blocked:
            blocker_count = len(attacker.blocked_by)
            self.state.fire_event(
                GameEvent(
                    EventType.BECOMES_BLOCKED,
                    attacker=attacker.name,
                    player_id=attacker.controller_id,  # the attacker's own controller
                    instance_id=attacker.instance_id,
                    object_types=sorted(attacker.type_words),
                    blocker_count=blocker_count,
                )
            )
            # RULE 702.23: Rampage's own per-firing dynamic pump — see
            # `RulesEngine.check_rampage` for why this can't go through the
            # ordinary annihilator/afflict/bushido `TriggeredAbility` path.
            self.rules.check_rampage(attacker, blocker_count)

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
        if getattr(attacker, "temp_unblockable", False):
            # "Target creature can't be blocked this turn" (Rogue's Passage) —
            # a resolve-time grant, unlike landwalk's static evasion above;
            # cleared at cleanup (RULE 514.2) like every other temp_* flag.
            return False
        if combat.has(attacker, "cant_be_blocked"):
            # "~ can't be blocked." / "equipped creature can't be blocked."
            # — the printed-static sibling of `temp_unblockable` above; see
            # `parser/oracle/catalogue/static_handlers.py`'s combat-
            # restriction family.
            return False
        return (
            blocker.controller_id == player.id
            and blocker.is_creature
            and blocker in self.state.permanents()  # RULE 702.26c: excludes a phased-out creature
            and not blocker.tapped
            and blocker.blocking is None
            # "~ can't block." / "enchanted creature can't block [or
            # attack]." — a synthetic layer-6 flag, same family as above.
            and not combat.has(blocker, "cant_block")
            and attacker.attacking
            and self._attacker_attacks_player(attacker, player)
            and combat.can_block(attacker, blocker)
        )

    def _lands_controlled_by(self, player_id: str) -> list[GameObject]:
        return [
            o for o in self.state.permanents()
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
        self,
        player: Player,
        source: GameObject,
        option_index: int = 0,
        ability_index: int = 0,
        tap_choices: Optional[list[Any]] = None,
        color_split: Optional[dict[str, int]] = None,
    ) -> dict[str, int]:
        """Activate one of a permanent's mana abilities (RULE 605) — the
        fast, no-stack path.

        ``ability_index`` picks *which* mana ability (most permanents print
        just one; Devoted Druid's second line isn't a mana ability at all,
        so it never counts here); ``option_index`` then picks one of *that*
        ability's mutually-exclusive production options (the dual-land fix:
        a "{T}: Add {W} or {U}." land makes *one* colour, not both). Charges
        the ability's **full** cost (RULE 602.1) — not just {T} — so e.g.
        Selvala's {G} or Gnarlroot Trapper's 1 life are actually paid.
        ``tap_choices`` is the player's own pick of *which* permanents pay a
        "tap N untapped Elves you control" cost (Birchlore Rangers, Heritage
        Druid — a real cost choice, not an auto-pick, and the source itself
        is eligible since the printed text doesn't say "other"); ``None``
        falls back to an auto-pick (non-interactive callers). ``color_split``
        is only consulted for an "any combination of colours" ability
        (`ManaAbility.any_combination` — Flamebraider/Gwenna/Smokebraider/
        Selvala): a ``{colour: count}`` distribution across WUBRG summing to
        the ability's resolved total, validated by `validate_color_split`;
        ``None`` (or a non-combination ability) falls back to
        ``option_index``'s single-colour choice, same as before this
        parameter existed. Returns the mana added.
        """
        if source not in self.state.battlefield or source.controller_id != player.id:
            raise ValueError("can only tap your own permanents in play")
        abilities = mana_abilities_for(source, state=self.state)
        if not 0 <= ability_index < len(abilities):
            raise ValueError(f"{source.name} has no mana ability #{ability_index}")
        ability = abilities[ability_index]
        cost = ability.cost
        if not self._can_pay_activation_cost(player, source, cost, x=0, tap_choices=tap_choices):
            raise ValueError(f"cannot pay {source.name}'s mana ability cost")
        if not ability.options:
            raise ValueError(f"{source.name}'s mana ability produces nothing")
        if ability.any_combination and color_split is not None:
            total = sum(ability.options[0].values())
            produced = validate_color_split(color_split, total)
        else:
            if not 0 <= option_index < len(ability.options):
                raise ValueError(f"invalid mana option {option_index} for {source.name}")
            produced = dict(ability.options[option_index])
        self._pay_activation_cost(player, source, cost, x=0, tap_choices=tap_choices)
        player.mana_pool.add_many(produced, restriction=ability.restriction)
        if ability.self_damage:
            # RULE 605.1a: a mana ability may have effects besides producing
            # mana (the painland/Elves-of-Deep-Shadow "deals N damage to
            # you" rider) — applied right alongside it, no stack involved.
            self.rules.deal_damage(player, ability.self_damage, source=source)
        if ability.self_rad_counters:
            # RULE 728's own rider (Harold and Bob's granted ability) —
            # same "applied right alongside, no stack" treatment.
            self.rules.add_player_counters(player, ability.self_rad_counters, "rad", source=source)
        self.state.record_stat(player.id, "mana", amount=sum(produced.values()))
        # RULE 605.1: a "whenever ~ is tapped for mana" trigger (Price of
        # Glory, Wild Growth, Mana Web) fires here — after the mana is in the
        # pool — off the genuine mana-ability tap, never a plain tap-cost or
        # an attack. Collected like any other event; the caller places pending
        # triggers on the stack as usual.
        self.state.fire_event(
            GameEvent(
                EventType.TAPPED_FOR_MANA,
                object=source.name,
                controller_id=player.id,
                instance_id=source.instance_id,
                object_types=sorted(source.type_words),
                produced=dict(produced),
            )
        )
        return produced

    def activate_hand_mana_ability(
        self,
        player: Player,
        source: GameObject,
        option_index: int = 0,
        ability_index: int = 0,
        color_split: Optional[dict[str, int]] = None,
    ) -> dict[str, int]:
        """RULE 605.1a "Exile this card from your hand: Add …" (Elvish
        Spirit Guide, Simian Spirit Guide) — `tap_for_mana`'s hand-zone
        counterpart: no battlefield permanent, no {T}/summoning-sickness
        check; the cost is exiling the card itself straight out of hand
        (`RulesEngine.exile` already handles the hand→exile zone move and
        its event). Every real printed card's only cost component is the
        exile itself; a future card pairing it with e.g. a life payment
        would need this extended, same as `tap_for_mana`'s cost handling.
        ``option_index``/``ability_index``/``color_split`` mirror
        `tap_for_mana`'s parameters exactly (a hand-exile ability could in
        principle be a dual-colour choice or an "any combination of
        colours" one, same as a battlefield one). Returns the mana added.
        """
        if source not in player.hand:
            raise ValueError("can only activate a hand mana ability from your own hand")
        abilities = hand_mana_abilities_for(source, state=self.state)
        if not 0 <= ability_index < len(abilities):
            raise ValueError(f"{source.name} has no hand mana ability #{ability_index}")
        ability = abilities[ability_index]
        if not ability.options:
            raise ValueError(f"{source.name}'s mana ability produces nothing")
        if ability.any_combination and color_split is not None:
            total = sum(ability.options[0].values())
            produced = validate_color_split(color_split, total)
        else:
            if not 0 <= option_index < len(ability.options):
                raise ValueError(f"invalid mana option {option_index} for {source.name}")
            produced = dict(ability.options[option_index])
        self.rules.exile(source)
        player.mana_pool.add_many(produced, restriction=ability.restriction)
        if ability.self_damage:
            self.rules.deal_damage(player, ability.self_damage, source=source)
        if ability.self_rad_counters:
            self.rules.add_player_counters(player, ability.self_rad_counters, "rad", source=source)
        self.state.record_stat(player.id, "mana", amount=sum(produced.values()))
        return produced

    # ------------------------------------------------------------------
    # Activated abilities (RULE 602)
    # ------------------------------------------------------------------

    def can_activate(
        self,
        player: Player,
        source: GameObject,
        ability: ActivatedAbility,
        x: int = 0,
        tap_choices: Optional[list[Any]] = None,
    ) -> bool:
        """Whether ``player`` may activate ``ability`` of ``source`` right now.

        Requires ``source`` to be a permanent ``player`` controls carrying the
        ability, and every part of its cost to be payable (RULE 602.2a):
        mana, tapping/untapping the source, a life/discard/counter payment,
        and a legal thing to sacrifice.

        A ``discard_self`` cost (Channel/Cycling, RULE 702.29/28.2h) is the
        one shape activated from *hand* instead of the battlefield — the
        ability still uses the stack like any other (unlike the mana-ability
        shortcut `activate_hand_mana_ability` uses), so it goes through this
        same path with a hand-zone legality check instead.
        """
        if ability.cost.discard_self:
            if source not in player.hand or source.owner_id != player.id:
                return False
        elif source not in self.state.permanents() or source.controller_id != player.id:
            return False  # RULE 702.26c: a phased-out permanent's abilities can't be activated
        if ability not in source.activated_abilities and ability not in source.granted_activated_abilities:
            return False
        if getattr(source, "loses_all_abilities", False):
            return False  # RULE 613.7f: Humility/Dress Down stripped its abilities
        if continuous.activation_prohibited(self.state, source):
            # RULE 602: "Activated abilities of artifacts can't be
            # activated." (Collector Ouphe/Stony Silence/Null Rod) — the
            # single choke point both this validation and `legal_actions`'s
            # offer list already go through.
            return False
        if ability.once_per_turn and ability._last_activated_turn == self.state.turn_number:
            return False
        if ability.cost.is_loyalty and not self._can_activate_loyalty(player, source):
            return False
        if ability.cost.sorcery_speed_only and not self._sorcery_speed_ok(player):
            return False
        if ability.cost.class_level is not None and not self._can_activate_class_level(
            source, ability.cost.class_level
        ):
            return False
        return self._can_pay_activation_cost(player, source, ability.cost, x, tap_choices=tap_choices)

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

        Ordinarily only at sorcery speed; a `conditional_flash` (The
        Wandering Emperor's "you may activate loyalty abilities any time
        you could cast an instant" while it entered this turn) grants
        instant-speed activation instead, while its condition holds. Only
        once per turn per planeswalker either way.
        """
        conditional_flash = getattr(source, "conditional_flash", None)
        has_conditional_flash = (
            conditional_flash is not None
            and condition_query.conditional_flash_holds(conditional_flash, source, self.state)
        )
        return (
            source.is_planeswalker
            and (self._sorcery_speed_ok(player) or has_conditional_flash)
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
        remove_counters_x = ability.cost.remove_counters is not None and ability.cost.remove_counters[1] in (
            REMOVE_COUNTERS_X, REMOVE_COUNTERS_ANY,
        )
        if mana.has_variable or remove_counters_x:
            action["has_x"] = True
            action["max_x"] = self._max_x_for_activation_cost(player, source, ability.cost)
        requirements = self._ability_target_requirements(player, ability, source)
        if requirements:
            action["requires_target"] = True
            action["targets"] = requirements
            if not all_requirements_satisfiable(requirements):
                action["locked"] = True
                action["lock_reason"] = "Kein gültiges Ziel im Spiel"
        if ability.cost.tap_others:
            action["tap_cost"] = self._tap_cost_choice(player, source, ability.cost)
        return action

    def _max_x_for_activation_cost(
        self, player: Player, source: GameObject, cost: "ActivationCost"
    ) -> int:
        """The highest legal ``x`` for an ability whose cost announces X via
        mana (``{X}``), a "Remove X counters"/"Remove any number of
        counters" clause, or both at once (Chamber Sentry/Marath-shaped,
        where the *same* announced X pays both) — the merged bound is the
        stricter of whichever components are actually variable.
        """
        bound: Optional[int] = None
        if cost.mana.has_variable:
            bound = self._max_x_for_mana(player, source, cost.mana)
        if cost.remove_counters is not None and cost.remove_counters[1] in (
            REMOVE_COUNTERS_X, REMOVE_COUNTERS_ANY,
        ):
            kind = cost.remove_counters[0]
            counters_bound = source.counters.get(kind, 0)
            bound = counters_bound if bound is None else min(bound, counters_bound)
        return bound if bound is not None else 0

    def _max_x_for_mana(self, player: Player, source: GameObject, mana: "ManaCost") -> int:
        bound = player.mana_pool.total()
        allows_restriction = restriction_predicate_for_activation(source, has_x=True)
        for x in range(bound, -1, -1):
            if player.mana_pool.can_pay(
                mana.with_x(x), life_available=player.life, allows_restriction=allows_restriction
            ):
                return x
        return 0

    def _reduced_activation_mana(
        self, source: GameObject, mana: "ManaCost", cost: Optional["ActivationCost"] = None
    ) -> "ManaCost":
        """Apply any "activated abilities cost {N} less to activate" static
        scoped to ``source`` (Power Artifact-shaped, RULE 601.2f-adjacent) —
        nothing in the ordinary activation-cost path consulted a reduction
        before this (unlike a spell's cast cost, `continuous.
        cost_reduction_for`). See `continuous.activation_cost_reduction_for`
        for the static's own "can't reduce below N mana" floor, honoured
        here by capping the reduction rather than trusting `reduce_generic`'s
        own floor-at-zero.

        ``cost.dynamic_reduction`` (Mariposa Military Base's own printed
        "costs {1} less for each rad counter you have") is a *second*,
        independent reduction source — the ability's own cost, not a
        separate permanent's static — added on top before the floor is
        applied, since both would stack on a real card that had both.
        """
        reduction, floor = continuous.activation_cost_reduction_for(self.state, source)
        if cost is not None and cost.dynamic_reduction:
            kind = cost.dynamic_reduction.get("kind", "rad")
            per = int(cost.dynamic_reduction.get("generic_per", 1))
            try:
                player = self.state.player_by_id(source.controller_id)
            except (KeyError, ValueError):
                player = None
            if player is not None:
                reduction += per * player.counters.get(kind, 0)
        if reduction <= 0:
            return mana
        if floor and mana.converted_mana_cost - reduction < floor:
            reduction = max(0, mana.converted_mana_cost - floor)
        return mana.reduce_generic(reduction)

    def _can_pay_activation_cost(
        self,
        player: Player,
        source: GameObject,
        cost: "ActivationCost",
        x: int,
        tap_choices: Optional[list[Any]] = None,
    ) -> bool:
        # {T} needs an untapped source; {Q} a tapped one. Either symbol also
        # needs a non-summoning-sick source unless it has haste (RULE 302.6,
        # 602.5e, 702.10b) — the same rule the mana-tap path enforces.
        if cost.taps_self and (source.tapped or self._summoning_sick_for_tap(source)):
            return False
        if cost.untaps_self and (not source.tapped or self._summoning_sick_for_tap(source)):
            return False
        mana = cost.mana.with_x(x) if cost.mana.has_variable else cost.mana
        mana = self._reduced_activation_mana(source, mana, cost)
        if mana.symbols:
            allows_restriction = restriction_predicate_for_activation(source, has_x=cost.mana.has_variable)
            if not player.mana_pool.can_pay(
                mana, life_available=player.life, allows_restriction=allows_restriction
            ):
                return False
        if cost.pay_life and player.life < cost.pay_life:
            return False
        if cost.discard and cost.discard != DISCARD_HAND and len(player.hand) < cost.discard:
            return False
        if cost.discard_self and source not in player.hand:
            return False
        if cost.sacrifice and self._sacrifice_candidate(player, source, cost.sacrifice) is None:
            return False
        if cost.return_to_hand and self._return_to_hand_candidate(player, cost.return_to_hand) is None:
            return False
        if cost.unattach_self and source.attached_to is None:
            return False
        if cost.remove_counters:
            kind, count = cost.remove_counters
            if count in (REMOVE_COUNTERS_X, REMOVE_COUNTERS_ANY):
                # RULE 601.2b analogue: the amount is announced via ``x`` at
                # activation time, not printed — payable as long as that
                # many of the counter actually sit on the source.
                if x < 0 or source.counters.get(kind, 0) < x:
                    return False
            elif source.counters.get(kind, 0) < count:
                return False
        if cost.tap_others:
            count, subtype = cost.tap_others
            if self._resolve_tap_others(player, source, count, subtype, tap_choices) is None:
                return False
        if cost.exile_self_from_hand:
            # This path is for a battlefield permanent's own ability cost
            # (`can_activate`/`tap_for_mana`'s non-hand-exile branch) — an
            # "Exile this card from your hand" cost is never payable here,
            # whatever `source` is; see `activate_hand_mana_ability` for
            # the actual hand-zone counterpart (Elvish/Simian Spirit Guide).
            return False
        # A minus loyalty ability can't be activated for more loyalty than the
        # planeswalker has (RULE 606.5c / 118.5).
        if cost.loyalty is not None and cost.loyalty < 0 and source.loyalty < -cost.loyalty:
            return False
        return True

    def _tap_others_pool(self, player: Player, source: GameObject, subtype: str) -> list[GameObject]:
        """Every untapped permanent of type ``subtype`` ``player`` controls,
        eligible to pay a "Tap N untapped <type>s you control" cost
        (Birchlore Rangers, Heritage Druid) — **including the ability's own
        source**, since the printed text doesn't say "other" (RULE 602.1;
        the real card lets Birchlore Rangers tap itself as one of the two).
        Not gated by summoning sickness: RULE 302.6 only restricts a
        permanent's own {T}-cost ability, not being tapped to pay a
        *different* ability's cost. This is the full candidate pool the
        player picks from — see `_resolve_tap_others` for the actual choice.
        """
        return [
            o for o in self.state.permanents_controlled_by(player.id)
            if not o.tapped and continuous.has_subtype(o, subtype)
        ]

    def _tap_cost_choice(
        self, player: Player, source: GameObject, cost: "ActivationCost"
    ) -> dict[str, Any]:
        """The offer-time UI shape for a `tap_others` cost: how many to pick
        (``count``) and the full eligible pool (``options``) — the player
        picks exactly ``count`` of them (RULE 602.1's cost *choice*, not an
        engine auto-pick; see `_resolve_tap_others`)."""
        count, subtype = cost.tap_others
        pool = self._tap_others_pool(player, source, subtype)
        return {
            "count": count,
            "options": [{"instance_id": o.instance_id, "name": o.name} for o in pool],
        }

    def _resolve_tap_others(
        self,
        player: Player,
        source: GameObject,
        count: int,
        subtype: str,
        chosen_ids: Optional[list[Any]],
    ) -> Optional[list[GameObject]]:
        """The permanents to actually tap for a `tap_others` cost.

        ``chosen_ids`` is the player's own pick (instance ids) — this is a
        real cost *choice*, not something the engine should auto-decide, so
        an interactive caller always supplies it. ``None`` falls back to an
        auto-pick of the first ``count`` eligible permanents, for
        non-interactive callers (tests, the goldfish auto-player). Returns
        ``None`` (not payable / not a valid choice) if fewer than ``count``
        are eligible, or ``chosen_ids`` doesn't name exactly ``count``
        distinct eligible permanents.
        """
        pool = self._tap_others_pool(player, source, subtype)
        if chosen_ids is None:
            return pool[:count] if len(pool) >= count else None
        if len(chosen_ids) != count or len(set(chosen_ids)) != count:
            return None
        by_id = {o.instance_id: o for o in pool}
        chosen = [by_id[i] for i in chosen_ids if i in by_id]
        return chosen if len(chosen) == count else None

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
                # RULE 701.16c: sacrifice isn't destruction — regeneration
                # can't save it — so this bypasses `destroy` and its
                # regeneration-shield check.
                self.rules.put_into_graveyard(victim)
        if cost.discard:
            self.rules.discard(
                player, len(player.hand) if cost.discard == DISCARD_HAND else cost.discard
            )
        if cost.pay_life:
            amount = x if cost.pay_life == PAY_LIFE_X else cost.pay_life
            self.rules.lose_life(player, amount, cause="cost")

    def _pay_escape_graveyard_cost(self, player: Player, count: int) -> None:
        """RULE 702.138b: exile ``count`` other cards from ``player``'s
        graveyard as part of casting via Escape — an auto-choice (the first
        ``count`` remaining cards), the same non-interactive MVP
        simplification `_sacrifice_candidate`'s callers already make for
        other costs. Called after the escaping card itself has already left
        the graveyard, so it can never be exiled as its own cost.
        """
        for victim in list(player.graveyard)[:count]:
            self.rules.exile(victim)

    def _sacrifice_candidate(
        self, player: Player, source: GameObject, what: str
    ) -> Optional[GameObject]:
        """A permanent ``player`` can sacrifice to pay ``what`` (RULE 701.17).

        ``"self"`` is the ability's own source; a type word matches the first
        permanent the player controls of that type — an auto-choice, matching
        the MVP's non-interactive discard/search picks.
        """
        if what == "self":
            return source if source in self.state.permanents() else None
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

    def _return_to_hand_candidate(
        self, player: Player, subtype: str
    ) -> Optional[GameObject]:
        """A permanent of ``subtype`` ``player`` controls, to pay a "Return a
        <Type> you control to its owner's hand" cost (Quirion Ranger/Scryb
        Ranger, RULE 602.1) — an auto-choice, the same non-interactive
        first-match convention `_sacrifice_candidate` uses.
        """
        for obj in self.state.permanents_controlled_by(player.id):
            if continuous.has_subtype(obj, subtype):
                return obj
        return None

    def _pay_activation_cost(
        self,
        player: Player,
        source: GameObject,
        cost: "ActivationCost",
        x: int,
        tap_choices: Optional[list[Any]] = None,
    ) -> None:
        """Charge every component of ``cost`` (RULE 601.2h analogue for
        abilities) — tap/untap the source, tap other permanents, pay mana,
        pay life, sacrifice, discard, add/remove counters, loyalty. Shared by
        `activate_ability` and `tap_for_mana` (a mana ability's cost is
        charged exactly the same way, just without going on the stack).
        Assumes `_can_pay_activation_cost` already passed (with the same
        ``tap_choices``, if any).
        """
        if cost.taps_self:
            self.rules.set_tapped(source, True)
        if cost.untaps_self:
            source.untap()
        if cost.tap_others:
            count, subtype = cost.tap_others
            for obj in self._resolve_tap_others(player, source, count, subtype, tap_choices) or []:
                self.rules.set_tapped(obj, True)
        mana = cost.mana.with_x(x) if cost.mana.has_variable else cost.mana
        mana = self._reduced_activation_mana(source, mana, cost)
        if mana.symbols:
            allows_restriction = restriction_predicate_for_activation(source, has_x=cost.mana.has_variable)
            life_spent = player.mana_pool.pay(
                mana, life_available=player.life, allows_restriction=allows_restriction
            )
            self.rules.lose_life(player, life_spent, cause="cost")
        if cost.pay_life:
            self.rules.lose_life(player, cost.pay_life, cause="cost")
        if cost.sacrifice:
            victim = self._sacrifice_candidate(player, source, cost.sacrifice)
            if victim is not None:
                # RULE 701.16c: sacrifice isn't destruction — see the
                # matching comment in `_pay_additional_cast_cost`.
                self.rules.put_into_graveyard(victim)
        if cost.return_to_hand:
            bounced = self._return_to_hand_candidate(player, cost.return_to_hand)
            if bounced is not None:
                self.rules.return_to_hand(bounced)
        if cost.unattach_self:
            source.last_unattached_from_id = source.attached_to
            source.attached_to = None
        if cost.discard:
            self.rules.discard(player, len(player.hand) if cost.discard == DISCARD_HAND else cost.discard)
        if cost.discard_self:
            self.rules.discard_specific(source)
        if cost.remove_counters:
            kind, count = cost.remove_counters
            amount = x if count in (REMOVE_COUNTERS_X, REMOVE_COUNTERS_ANY) else count
            source.add_counters(kind, -amount)
        if cost.add_counters_cost:
            kind, count = cost.add_counters_cost
            source.add_counters(kind, count)
        if cost.loyalty is not None:
            # RULE 606.5c: pay by changing loyalty; a loyalty ability is once
            # per turn per planeswalker (RULE 606.3).
            source.add_counters("loyalty", cost.loyalty)
            source.activated_loyalty_this_turn = True

    def activate_ability(
        self,
        player: Player,
        source: GameObject,
        ability_index: int = 0,
        targets: Optional[list[Any]] = None,
        x: int = 0,
        tap_choices: Optional[list[Any]] = None,
        target_groups: Optional[list[list[Any]]] = None,
    ) -> None:
        """Pay an activated ability's cost and put it on the stack (RULE 602.2).

        Costs are paid in one go (RULE 601.2h analogue for abilities): tap /
        untap the source, pay mana, pay life, sacrifice, discard, remove
        counters — then the ability goes on the stack to resolve later like any
        other object. ``tap_choices`` is the player's pick for a "tap N
        untapped <type>s you control" cost, if any (see `tap_for_mana`).
        Raises ValueError if the ability can't be paid for.

        ``target_groups``, when given, partitions ``targets`` per targeting
        effect (`StackItem.target_groups`) — needed only when the ability
        carries 2+ *different* targeting effects; omitted (``None``), every
        effect reads ``targets`` directly, unchanged from before this existed.
        """
        abilities = source.activated_abilities + source.granted_activated_abilities
        if not 0 <= ability_index < len(abilities):
            raise ValueError(f"{source.name} has no activated ability #{ability_index}")
        ability = abilities[ability_index]
        if not self.can_activate(player, source, ability, x, tap_choices=tap_choices):
            raise ValueError(f"cannot activate {source.name}'s ability")

        self._pay_activation_cost(player, source, ability.cost, x, tap_choices=tap_choices)
        if ability.once_per_turn:
            ability._last_activated_turn = self.state.turn_number

        item = StackItem(
            kind="ability",
            controller_id=player.id,
            effects=[ability],
            description=ability.description or f"{source.name} ability",
            targets=targets,
            target_groups=target_groups,
            x=x,
            source=source,
        )
        self.state.stack.append(item)
        self.rules.check_ward(item, player)
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

        # RULE 702.33: surface Kicker/Multikicker so the UI can prompt for
        # how many times to pay it, the same "has_x/max_x" shape as {X}.
        kicker_cost = self._kicker_cost(obj)
        if kicker_cost is not None:
            kicker_param = (getattr(obj, "parametric_keywords", None) or {}).get("kicker") or {}
            action["has_kicker"] = True
            action["kicker_cost"] = kicker_cost.raw
            action["kicker_multi"] = bool(kicker_param.get("multi"))
            action["max_kicker"] = self.max_affordable_kicker(player, obj)

        # RULE 702.27: surface Buyback so the UI can offer a "pay to buy
        # back" toggle, locked when its own cost isn't affordable.
        buyback_cost = self._buyback_cost(obj)
        if buyback_cost is not None:
            action["has_buyback"] = True
            action["buyback_cost"] = buyback_cost.raw
            action["buyback_affordable"] = self.can_cast(player, obj, buyback=True)

        # RULE 702.34/702.138: a graveyard cast is by definition via
        # Flashback/Escape's own alternative cost, not the printed one — tag
        # it so the UI can label the offer distinctly from a normal cast.
        graveyard_keyword = self._graveyard_cast_keyword(obj) if obj in player.graveyard else None
        if graveyard_keyword is not None:
            action["cast_from_graveyard"] = graveyard_keyword
            if graveyard_keyword == "escape":
                escape_cost = self._escape_cost(obj)
                if escape_cost is not None and escape_cost.exile_from_graveyard:
                    action["escape_exile_count"] = escape_cost.exile_from_graveyard

        # Static cost adjustment (RULE 601.2f): surface base vs. reduced so the
        # UI can show "was {3}, now {1}" and the static-effects panel can
        # attribute it. Only attached when something actually changes the cost.
        reduction, contributors = continuous.cost_reduction_for(self.state, player, obj)
        self_reduction, self_contributors = continuous.self_cost_reduction_for(obj, self.state)
        reduction += self_reduction
        contributors = contributors + self_contributors
        tax = self.commander_tax(player, obj)
        if (reduction or tax or graveyard_keyword) and cost.raw:
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
        """One ``cast_spell`` action per mode of a modal spell (RULE 700.2).

        For the ordinary "choose one" case (``spell_modes_choose == 1``):
        one action per single mode, plus a combined "both" action when
        ``obj.spell_modes_or_both`` (RULE 700.2e) — the same "an offer per
        option" treatment `legal_actions` already gives an MDFC's two faces.
        For "choose *N*" (``N>=2`` — Kolaghan's Command/Austere Command
        -shaped): one action per legal *combination* of ``N`` modes
        (``itertools.combinations``), each tagged with a list of indices
        instead of a bare int (see `_effects_for_mode`). For "choose *N* or
        more" (``obj.spell_modes_at_least`` — Farewell-shaped): one action
        per combination of *every* size from ``N`` to all modes.
        """
        modes = list(getattr(obj, "spell_modes", None) or [])
        choose = getattr(obj, "spell_modes_choose", 1)
        at_least = getattr(obj, "spell_modes_at_least", False)
        if choose <= 1 and not at_least:
            actions = [self._cast_action(player, obj, mode=i) for i in range(len(modes))]
            if getattr(obj, "spell_modes_or_both", False) and len(modes) == 2:
                actions.append(self._cast_action(player, obj, mode="both"))
            return actions
        sizes = range(choose, len(modes) + 1) if at_least else [choose]
        return [
            self._cast_action(player, obj, mode=list(combo))
            for size in sizes
            for combo in itertools.combinations(range(len(modes)), size)
        ]

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
            # spell half, or a prepared copy, may be cast from exile — or
            # RULE 601.3b analogue's temporary "you may play/cast this"
            # permission (Light Up the Stage/Ragavan/Mnemonic Betrayal/
            # Ephemerate's Rebound-shaped, `_has_temp_play_permission`).
            # Previously missing here entirely — `can_cast`/`cast_spell`
            # already supported this zone/permission combination, but
            # nothing ever surfaced it as an actual offered action, so no
            # caller (UI or otherwise) could ever actually cast one of
            # these; found end-to-end testing Ephemerate's Rebound.
            castable = self._castable_from_exile(obj) or self._has_temp_play_permission(obj, player)
            if castable and self.can_cast(player, obj):
                if getattr(obj, "spell_modes", None):
                    actions.extend(self._modal_cast_actions(player, obj))
                else:
                    actions.append(self._cast_action(player, obj))
            if self._has_temp_play_permission(obj, player) and self.can_play_land(player, obj):
                actions.append(
                    {"type": "play_land", "instance_id": obj.instance_id, "name": obj.name}
                )

        for obj in list(player.graveyard):
            # RULE 702.34 / 702.138: Flashback/Escape let a card be cast
            # from the graveyard for an alternative cost — or some other
            # permanent may grant a standing permission instead (Lurrus of
            # the Dream-Den-shaped, `_graveyard_cast_permission`).
            castable = (
                self._castable_from_graveyard(obj)
                or self._graveyard_cast_permission(player, obj)
            )
            if castable and self.can_cast(player, obj):
                if getattr(obj, "spell_modes", None):
                    actions.extend(self._modal_cast_actions(player, obj))
                else:
                    actions.append(self._cast_action(player, obj))

        if player.library:
            # Oracle of Mul Daya/Glarb, Calamity's Augur-shaped: a permanent
            # may grant playing lands and/or casting spells straight off the
            # top of the library — see `game/top_library.py`. Only the top
            # card itself is ever offered.
            top = player.library[-1]
            if self.can_play_land(player, top):
                actions.append(
                    {"type": "play_land", "instance_id": top.instance_id, "name": top.name}
                )
            if self.can_cast(player, top):
                if getattr(top, "spell_modes", None):
                    actions.extend(self._modal_cast_actions(player, top))
                else:
                    actions.append(self._cast_action(player, top))

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
            # One offer per mana ability the source has (almost always just
            # one) — `_can_pay_activation_cost` covers tap/summoning-sickness
            # *and* any extra cost component (Selvala's {G}, Gnarlroot
            # Trapper's life payment, Birchlore Rangers' "tap two other
            # Elves" — RULE 602.1), so a source that can't tap itself can
            # still offer an ability that doesn't need to.
            for ability_index, ability in enumerate(mana_abilities_for(source, state=self.state)):
                if not ability.options:
                    continue
                # Existence-only check here (no chosen tap_others yet — the
                # player picks those in the UI *after* choosing to activate,
                # same as a target); `tap_for_mana` re-validates the actual
                # choice at payment time.
                if not self._can_pay_activation_cost(player, source, ability.cost, x=0):
                    continue
                action = {
                    "type": "tap_for_mana",
                    "instance_id": source.instance_id,
                    "name": source.name,
                    "ability_index": ability_index,
                    "cost_label": ability.cost.label(),
                    # Each option is a distinct choice (dual-land "W or U");
                    # the UI shows one button per option so the player picks
                    # the colour.
                    "options": [
                        {"index": i, "mana": opt, "label": option_label(opt)}
                        for i, opt in enumerate(ability.options)
                    ],
                }
                if ability.any_combination:
                    # RULE 605.1a "any combination of colours" (Flamebraider/
                    # Gwenna/Smokebraider/Selvala) — the player may split
                    # this total across colours (`color_split`) instead of
                    # picking one of the single-colour ``options`` above;
                    # `gameBoardView.js`'s `colorSplitHtml` offers both: the
                    # single-colour buttons as a still-legal fallback, plus
                    # this split builder.
                    action["any_combination"] = True
                    action["combination_total"] = sum(ability.options[0].values())
                if ability.cost.tap_others:
                    action["tap_cost"] = self._tap_cost_choice(player, source, ability.cost)
                actions.append(action)

        for source in list(player.hand):
            # RULE 605.1a "Exile this card from your hand: Add …" (Elvish/
            # Simian Spirit Guide) — the hand-zone counterpart of the
            # battlefield loop above; every real card's cost is just the
            # exile itself, so (unlike `tap_for_mana`'s offer) there's no
            # extra payability check here.
            for ability_index, ability in enumerate(hand_mana_abilities_for(source, state=self.state)):
                if not ability.options:
                    continue
                action = {
                    "type": "activate_hand_mana",
                    "instance_id": source.instance_id,
                    "name": source.name,
                    "ability_index": ability_index,
                    "cost_label": ability.cost.label(),
                    "options": [
                        {"index": i, "mana": opt, "label": option_label(opt)}
                        for i, opt in enumerate(ability.options)
                    ],
                }
                if ability.any_combination:
                    action["any_combination"] = True
                    action["combination_total"] = sum(ability.options[0].values())
                actions.append(action)

        for obj in self.state.permanents_controlled_by(player.id):
            # RULE 502.1 "you may choose not to untap ~ during your untap
            # step" (Rubinia Soulsinger/Hivis of the Scale/The Pandorica-
            # shaped) — a sticky preference toggle (see `GameObject.
            # skip_untap`'s docstring for why: the untap step has no mid-step
            # pause to ask fresh every turn), so it's offered any time this
            # player controls the permanent, not just during untap.
            if continuous.has_optional_no_untap_permission(self.state, obj):
                actions.append(
                    {
                        "type": "set_skip_untap",
                        "instance_id": obj.instance_id,
                        "name": obj.name,
                        "skip_untap": obj.skip_untap,
                    }
                )

        # Activated abilities (RULE 602) bound onto permanents this player
        # controls — one offer per payable ability (a fetch land's
        # "{T}, Sacrifice: …", a mana rock, a pinger, …). Includes any
        # layer-6-granted ones (Umbral Mantle/Squirrel Nest-shaped) so the
        # index offered here lines up with `activate_ability`'s own combined
        # list — both must enumerate the identical concatenation.
        for source in self.state.permanents_controlled_by(player.id):
            for index, ability in enumerate(source.activated_abilities + source.granted_activated_abilities):
                if self.can_activate(player, source, ability):
                    actions.append(self._activate_action(player, source, index, ability))

        # Channel (RULE 702.29)/Cycling (RULE 702.28): a hand-zone card's own
        # "Discard this card: <effect>" activated ability — unlike the
        # battlefield loop above, discovered off `player.hand`, since the
        # card itself (not a permanent) is the ability's source.
        for source in list(player.hand):
            for index, ability in enumerate(source.activated_abilities):
                if ability.cost.discard_self and self.can_activate(player, source, ability):
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
            for ability_index, ability in enumerate(mana_abilities_for(source, state=self.state)):
                cost = ability.cost
                # Keep the greedy auto-player conservative: only a plain
                # {T}-only mana ability taps itself automatically — one that
                # also costs mana/life/other-Elves (Selvala, Gnarlroot
                # Trapper, Birchlore Rangers) needs a real choice the bot
                # doesn't make.
                simple = (
                    cost.taps_self
                    and not cost.mana.symbols
                    and not cost.pay_life
                    and not cost.tap_others
                    and not cost.sacrifice
                    and not cost.discard
                    and not cost.add_counters_cost
                )
                if not simple or not ability.options:
                    continue
                if not self._can_pay_activation_cost(active, source, cost, x=0):
                    continue
                self.tap_for_mana(active, source, ability_index=ability_index)  # option 0 (greedy)
                break
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
