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

from ...models.cards.card import Card
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject, Zone
from ...models.game.game_state import GameState, StackItem
from ...models.mana.mana_cost import ManaCost
from ...models.mana.mana_pool import kept_mana_expiring_at
from ...models.game.player import Player
from .. import combat, condition_query, continuous, durations, face_down, variants
from ...models.decks import formats as game_format
from ...models.decks.formats import GameFormat, get_format
from ..mana_abilities import restriction_predicate_for_turn_face_up
from ..costs import (
    DISCARD_HAND,
    PAY_LIFE_X,
    REMOVE_COUNTERS_ANY,
    REMOVE_COUNTERS_X,
    ActivationCost,
    parse_activation_cost,
)
from ..effects.core import ActivatedAbility
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


class MiscMixin:
    """Planar die, face-down/morph turn-up, and the goldfish solo-AI helpers."""

    def recompute_continuous_effects(self) -> None:
        """Re-derive all layer-based characteristics now (RULE 613).

        SBAs already do this whenever the board settles; call this to refresh
        derived P/T, types and granted keywords for a read outside that loop
        (e.g. building the view for the UI)."""
        continuous.recompute(self.state)
    def planar_die_cost(self, player: Player) -> "ManaCost":
        """RULE 901.6b: rolling the planar die costs {X}, where X is the
        number of times ``player`` has already rolled it this turn — so the
        first roll of a turn is free and each further one costs one more."""
        rolled = self.state.planar_die_rolls_this_turn.get(player.id, 0)
        return ManaCost.parse(f"{{{rolled}}}") if rolled else ManaCost.parse("")
    def can_roll_planar_die(self, player: Player) -> bool:
        """RULE 901.6a: a special action, so it needs only a face-up plane,
        the player's own turn, their priority — and the {X} in the pool."""
        if not self.state.planar_deck or player is not self.state.active_player:
            return False
        cost = self.planar_die_cost(player)
        return not cost.symbols or player.mana_pool.can_pay(cost, life_available=player.life)
    def roll_planar_die(self, player: Player) -> str:
        """Take the RULE 901.6 special action: pay {X}, roll, apply the face.

        Returns the face rolled (``"chaos"``/``"planeswalk"``/``"blank"``).
        Like every special action this doesn't use the stack — but unlike
        turning a permanent face up, the *consequences* do: a chaos ability
        is a triggered ability and goes on the stack normally (RULE 901.13a).
        """
        if not self.can_roll_planar_die(player):
            raise ValueError("cannot roll the planar die now")
        cost = self.planar_die_cost(player)
        if cost.symbols:
            life_spent = player.mana_pool.pay(cost, life_available=player.life)
            self.rules.lose_life(player, life_spent, cause="cost")
        face = self.rules.roll_planar_die(player)
        self.give_priority(player)  # RULE 117.3c, as for any other action
        return face
    def turn_face_up_actions(self, player: Player, obj: GameObject) -> list[dict[str, Any]]:
        """The offered `legal_actions` entries for turning ``obj`` face up
        (RULE 702.37e/702.168d/701.40b/701.58b) — one per payable route.

        A special action, so it is offered "any time you have priority" with
        no timing restriction of its own (RULE 116.2b): no main-phase gate,
        no empty-stack gate — turning a morph up in response to a removal
        spell is exactly the point of the mechanic. Payability is checked
        against the mana pool here (the same way an activated ability's offer
        is), so an unaffordable route simply isn't offered.
        """
        if not obj.face_down or obj.controller_id != player.id:
            return []
        actions: list[dict[str, Any]] = []
        for index, option in enumerate(face_down.turn_face_up_options(obj)):
            if not player.mana_pool.can_pay(
                option["cost"], life_available=player.life, allows_restriction=restriction_predicate_for_turn_face_up(),
            ):
                continue
            actions.append(
                {
                    "type": "turn_face_up",
                    "instance_id": obj.instance_id,
                    "name": obj.name,
                    "option_index": index,
                    "kind": option["kind"],
                    "cost_label": option["label"],
                }
            )
        return actions
    def turn_face_up(self, player: Player, obj: GameObject, option_index: int = 0) -> bool:
        """Take the RULE 116.2b special action of turning ``obj`` face up.

        Pays the chosen route's cost (morph/disguise's printed cost, or a
        manifested/cloaked creature card's own mana cost) and turns the
        permanent face up. Doesn't use the stack (RULE 702.37e) — the
        permanent has its normal characteristics back the instant this
        returns, with no window for anyone to respond in between, which is
        what makes a face-down blocker's reveal work the way players expect.
        """
        options = face_down.turn_face_up_options(obj)
        if not obj.face_down or obj.controller_id != player.id or not options:
            raise ValueError(f"{obj.name} can't be turned face up")
        if option_index < 0 or option_index >= len(options):
            raise ValueError("no such turn-face-up option")
        option = options[option_index]
        allows_restriction = restriction_predicate_for_turn_face_up()  # Creeping Peeper's mana may pay for this
        if not player.mana_pool.can_pay(option["cost"], life_available=player.life, allows_restriction=allows_restriction):
            raise ValueError(f"cannot pay {option['label']} to turn {obj.name} face up")
        life_spent = player.mana_pool.pay(option["cost"], life_available=player.life, allows_restriction=allows_restriction)
        self.rules.lose_life(player, life_spent, cause="cost")
        turned = self.rules.turn_face_up(obj, megamorph=bool(option.get("megamorph")))
        self.recompute_continuous_effects()
        # RULE 117.3c: taking an action reclaims priority for its taker, the
        # same as casting a spell or activating an ability does.
        self.give_priority(player)
        return turned
    def pay_search_exemption_actions(self, player: Player) -> list[dict[str, Any]]:
        """The offered `legal_actions` entry for RULE 116.2a's "Any player
        may pay {2} for that player to ignore this effect until end of
        turn." (MEC-35, Leonin Arbiter) — a special action, so (like `turn_
        face_up_actions`) it carries no timing restriction of its own and
        is only offered when payable. Not offered at all once already
        exempt this turn (nothing left to gain by paying again) or when no
        search prohibition currently applies to ``player``.
        """
        if not self.rules.is_search_prohibited_for(player):
            return []
        cost = ManaCost.parse("{2}")
        if not player.mana_pool.can_pay(cost, life_available=player.life):
            return []
        return [{"type": "pay_search_exemption", "cost_label": "{2}"}]
    def pay_search_exemption(self, player: Player) -> None:
        """Take the RULE 116.2a special action of paying to ignore every
        current search prohibition until end of turn (MEC-35, Leonin
        Arbiter) — doesn't use the stack, same as `turn_face_up`.
        """
        cost = ManaCost.parse("{2}")
        if not player.mana_pool.can_pay(cost, life_available=player.life):
            raise ValueError(f"{player.name} cannot pay {{2}} for the search exemption")
        life_spent = player.mana_pool.pay(cost, life_available=player.life)
        self.rules.lose_life(player, life_spent, cause="cost")
        self.state.search_exempt_until_turn[player.id] = self.state.internal_turn.number
        # RULE 117.3c: taking an action reclaims priority for its taker.
        self.give_priority(player)
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
                continuous.empty_mana_pool(self.state, player, kept_mana_expiring_at(step.name))
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
                if not self._can_pay_activation_cost(active, source, cost, x=0, is_mana_ability=True):
                    continue
                self.tap_for_mana(active, source, ability_index=ability_index)  # option 0 (greedy)
                break
        # Cast affordable non-land spells cheapest first.
        castable = sorted(
            (o for o in active.hand if not o.card.is_land),
            key=lambda o: o.mana_value,
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
