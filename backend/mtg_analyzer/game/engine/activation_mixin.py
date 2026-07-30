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
from ...models.emblem import Emblem
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
from ..effects import ActivatedAbility
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


class ActivationMixin:
    """Activated abilities: legality, cost payment, the cost-choice families."""

    def can_activate(
        self,
        player: Player,
        source: GameObject,
        ability: ActivatedAbility,
        x: int = 0,
        tap_choices: Optional[list[Any]] = None,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
    ) -> bool:
        """Whether ``player`` may activate ``ability`` of ``source`` right now.

        Requires ``source`` to be a permanent ``player`` controls carrying the
        ability, and every part of its cost to be payable (RULE 602.2a):
        mana, tapping/untapping the source, a life/discard/counter payment,
        and a legal thing to sacrifice. ``discard_choices`` is the same RULE
        602.1 cost-choice shape as ``sacrifice_choice``, for a plain
        "discard N cards" cost component (`_resolve_discard_cost`); ``None``
        falls back to an auto-pick.

        A ``discard_self`` cost (Channel/Cycling, RULE 702.29/28.2h) is the
        one shape activated from *hand* instead of the battlefield — the
        ability still uses the stack like any other (unlike the mana-ability
        shortcut `activate_hand_mana_ability` uses), so it goes through this
        same path with a hand-zone legality check instead.
        """
        if ability.cost.discard_self:
            if source not in player.hand or source.owner_id != player.id:
                return False
        elif isinstance(source, Emblem):
            # RULE 114.4 — an emblem's own activated ability (MEC-8) "functions
            # in the command zone": no permanent, no tap/summoning-sickness
            # state, just membership + controller like every other emblem
            # ability family (`continuous.py`'s static scan, `_collect_triggers`).
            if source not in player.emblems or source.controller_id != player.id:
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
        return self._can_pay_activation_cost(
            player, source, ability.cost, x, tap_choices=tap_choices,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
        )
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
        the same shape `_cast_action` uses for spells (RULE 602.2b / 115).

        Reads `GameEffect.target_specs` (not ``target_spec``) so a single
        effect announcing two requirements — "target creature you control
        fights another target creature", Ulvenwald Tracker — offers both,
        and carries the same ``count``/cross-target keys
        `targeting.requirements_with_targets` gives the cast path, so the
        board's targeting rounds behave identically for an ability."""
        out: list[dict[str, Any]] = []
        for spec in ability_target_specs(ability):
            out.append(
                {
                    "kind": spec.kind,
                    "optional": spec.optional,
                    # RULE 601.2c — see `targeting.resolved_count`.
                    "count": resolved_count(spec, self.state, player.id, source),
                    "label": spec.label(),
                    "options": legal_targets(self.state, player.id, spec, source=source),
                    "distinct_controllers": spec.distinct_controllers,
                    "distinct_from_others": spec.distinct_from_others,
                }
            )
        return out
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
    def _chosen_color_locked_cost(
        self, source: GameObject, mana: "ManaCost"
    ) -> Optional["ManaCost"]:
        """Throne of Eldraine's colour-lock: ``mana`` re-expressed as its full
        mana value in pips of ``source``'s `chosen_color`, so the ordinary
        any-colour generic solve is forced onto that one colour (RULE
        601.2b). ``None`` while no colour has been chosen (nothing legal to
        pay with) — every real card printing this rider also has the "as ~
        enters, choose a color" ETB that sets it. Only the generic total is
        re-coloured; any card that ever paired a differently-coloured pip
        with this rider (none does today) would be mis-modeled, so it's kept
        deliberately simple rather than guessing a multi-colour split."""
        chosen = getattr(source, "chosen_color", None)
        if not chosen:
            return None
        return ManaCost.parse(("{" + chosen + "}") * mana.converted_mana_cost)
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
        "costs {1} less for each rad counter you have"; Eiganjo, Seat of the
        Empire's "costs {1} less to activate for each legendary creature you
        control") is a *second*, independent reduction source — the ability's
        own cost, not a separate permanent's static — added on top before the
        floor is applied, since both would stack on a real card that had both.
        Its magnitude comes from either a player-counter ``kind`` or a
        board-reading ``count_selector`` (`continuous.count_selector`),
        whichever the cost names.
        """
        reduction, floor = continuous.activation_cost_reduction_for(self.state, source)
        if cost is not None and cost.dynamic_reduction:
            per = int(cost.dynamic_reduction.get("generic_per", 1))
            selector = cost.dynamic_reduction.get("count_selector")
            if selector:
                reduction += per * continuous.count_selector(
                    self.state, source.controller_id, str(selector), source=source
                )
            else:
                kind = cost.dynamic_reduction.get("kind", "rad")
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
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
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
        if cost.spend_only_chosen_color:
            # Throne of Eldraine-shaped colour-lock: the whole mana cost must
            # be paid with mana of the source's chosen colour (RULE 601.2b) —
            # modeled by requiring that many pips of `chosen_color` instead
            # of the ordinary any-colour generic solve.
            locked = self._chosen_color_locked_cost(source, mana)
            if locked is None or not player.mana_pool.can_pay(locked, life_available=player.life):
                return False
        elif mana.symbols:
            allows_restriction = restriction_predicate_for_activation(source, has_x=cost.mana.has_variable)
            if not player.mana_pool.can_pay(
                mana, life_available=player.life, allows_restriction=allows_restriction
            ):
                return False
        if cost.pay_life and player.life < cost.pay_life:
            return False
        if cost.pay_energy and player.counters.get("energy", 0) < cost.pay_energy:
            return False
        if cost.discard and cost.discard != DISCARD_HAND:
            if self._resolve_discard_cost(player, cost.discard, discard_choices) is None:
                return False
        if cost.discard_self and source not in player.hand:
            return False
        if cost.sacrifice and self._sacrifice_candidate(
            player, source, cost.sacrifice, chosen_id=sacrifice_choice
        ) is None:
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
        if cost.exile_top_of_library and not player.library:
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
        loyalty_change = -x if cost.loyalty_is_x else cost.loyalty
        if loyalty_change is not None and loyalty_change < 0 and source.loyalty < -loyalty_change:
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
        non-interactive callers (tests, the goldfish auto-player). See
        `_resolve_pool_cost` for the shared "choose N from a pool" logic.
        """
        pool = self._tap_others_pool(player, source, subtype)
        return self._resolve_pool_cost(pool, count, chosen_ids)
    @staticmethod
    def _resolve_pool_cost(
        pool: list[GameObject], count: int, chosen_ids: Optional[list[Any]]
    ) -> Optional[list[GameObject]]:
        """RULE 602.1's "choose N from a pool" resolution, shared by every
        cost component that picks N objects from a candidate list
        (`_resolve_tap_others`'s tap-others, `_resolve_discard_cost`'s plain
        discard-N): ``chosen_ids`` is the player's own pick (instance ids),
        validated against ``pool``; ``None`` falls back to an auto-pick of
        the first ``count`` eligible objects, for non-interactive callers
        (tests, the goldfish auto-player). Returns ``None`` (not payable /
        not a valid choice) if fewer than ``count`` are eligible, or
        ``chosen_ids`` doesn't name exactly ``count`` distinct eligible
        objects.
        """
        if chosen_ids is None:
            return pool[:count] if len(pool) >= count else None
        if len(chosen_ids) != count or len(set(chosen_ids)) != count:
            return None
        by_id = {o.instance_id: o for o in pool}
        chosen = [by_id[i] for i in chosen_ids if i in by_id]
        return chosen if len(chosen) == count else None
    def _sacrifice_candidate(
        self,
        player: Player,
        source: GameObject,
        what: str,
        chosen_id: Optional[int] = None,
    ) -> Optional[GameObject]:
        """A permanent ``player`` can sacrifice to pay ``what`` (RULE 701.17).

        ``"self"`` is the ability's own source — never a choice. Otherwise
        this is a genuine cost *choice* (RULE 602.1), the same shape
        `_resolve_tap_others` already uses for "tap N untapped <type>s":
        ``chosen_id`` is the player's own pick, validated against every
        legal candidate; ``None`` falls back to the first matching
        permanent, for non-interactive callers (tests, the goldfish
        auto-player) and existence-only legality checks (`legal_actions`
        offering the ability before a choice has been made yet).
        """
        if what == "self":
            return source if source in self.state.permanents() else None
        candidates = [
            obj
            for obj in self.state.permanents_controlled_by(player.id)
            if self._matches_sacrifice_type(obj, what)
        ]
        if chosen_id is not None:
            return next((o for o in candidates if o.instance_id == chosen_id), None)
        return candidates[0] if candidates else None
    def _sacrifice_cost_choice(
        self, player: Player, cost: "ActivationCost"
    ) -> dict[str, Any]:
        """The offer-time UI shape for a ``sacrifice`` cost: every legal
        candidate, so the player can pick which permanent pays it instead of
        the engine auto-choosing (RULE 602.1) — the `_sacrifice_candidate`
        counterpart to `_tap_cost_choice`. Never called for ``"self"``,
        which isn't a choice."""
        candidates = [
            obj
            for obj in self.state.permanents_controlled_by(player.id)
            if self._matches_sacrifice_type(obj, cost.sacrifice)
        ]
        return {
            "options": [{"instance_id": o.instance_id, "name": o.name} for o in candidates]
        }
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
    def _discard_cost_pool(
        self, player: Player, exclude: Optional[GameObject] = None
    ) -> list[GameObject]:
        """Every card in ``player``'s hand eligible to pay a plain "discard
        N cards" cost component. ``exclude`` keeps a spell's own hand copy
        of itself out of its own additional-cost pool (RULE 601.2b — it
        isn't a legal discard candidate for its own cost); unused for an
        activated ability's cost, whose source is a battlefield permanent,
        not a card in hand."""
        return [c for c in player.hand if c is not exclude]
    def _resolve_discard_cost(
        self,
        player: Player,
        count: int,
        chosen_ids: Optional[list[int]],
        exclude: Optional[GameObject] = None,
    ) -> Optional[list[GameObject]]:
        """The cards to actually discard for a plain "discard N cards" cost
        component — the `_resolve_tap_others` counterpart for discard (ENG-3:
        this used to be an unconditional back-of-hand auto-pick, ``RulesEngine.
        discard``, even though a cost is a genuine RULE 602.1 choice).

        ``chosen_ids`` is the player's own pick (instance ids); ``None``
        falls back to an auto-pick of the first ``count`` eligible cards,
        for non-interactive callers (tests, the goldfish auto-player) and
        existence-only legality checks (`legal_actions` offering the cast/
        activation before a choice has been made yet). See
        `_resolve_pool_cost` for the shared "choose N from a pool" logic
        (the same "not payable / not a valid choice" signal
        `_resolve_tap_others` uses).
        """
        pool = self._discard_cost_pool(player, exclude)
        return self._resolve_pool_cost(pool, count, chosen_ids)
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
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
    ) -> None:
        """Charge every component of ``cost`` (RULE 601.2h analogue for
        abilities) — tap/untap the source, tap other permanents, pay mana,
        pay life, sacrifice, discard, add/remove counters, loyalty. Shared by
        `activate_ability` and `tap_for_mana` (a mana ability's cost is
        charged exactly the same way, just without going on the stack).
        Assumes `_can_pay_activation_cost` already passed (with the same
        ``tap_choices``/``sacrifice_choice``/``discard_choices``, if any).
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
        if cost.spend_only_chosen_color:
            # See `_can_pay_activation_cost` — pay the whole cost as
            # `chosen_color` pips (Throne of Eldraine).
            locked = self._chosen_color_locked_cost(source, mana)
            if locked is not None and locked.symbols:
                player.mana_pool.pay(locked, life_available=player.life)
        elif mana.symbols:
            allows_restriction = restriction_predicate_for_activation(source, has_x=cost.mana.has_variable)
            life_spent = player.mana_pool.pay(
                mana, life_available=player.life, allows_restriction=allows_restriction
            )
            self.rules.lose_life(player, life_spent, cause="cost")
        if cost.pay_life:
            self.rules.lose_life(player, cost.pay_life, cause="cost")
        if cost.pay_energy:
            # RULE 122: spend energy counters — a player-level resource
            # (`Player.counters["energy"]`), same generic dict "rad"/
            # "poison" already use.
            self.rules.add_player_counters(player, -cost.pay_energy, "energy")
        if cost.sacrifice:
            victim = self._sacrifice_candidate(
                player, source, cost.sacrifice, chosen_id=sacrifice_choice
            )
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
        if cost.exile_top_of_library and player.library:
            self.rules.exile(player.library[-1])
        if cost.discard:
            if cost.discard == DISCARD_HAND:
                self.rules.discard(player, len(player.hand))
            else:
                chosen = self._resolve_discard_cost(player, cost.discard, discard_choices)
                for card in chosen or []:
                    self.rules.discard_specific(card)
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
            # per turn per planeswalker (RULE 606.3). A ``[-X]`` cost
            # (Jeska, Thrice Reborn) removes the *announced* X rather than a
            # printed constant — see `ActivationCost.loyalty_is_x`.
            source.add_counters("loyalty", -x if cost.loyalty_is_x else cost.loyalty)
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
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
    ) -> None:
        """Pay an activated ability's cost and put it on the stack (RULE 602.2).

        Costs are paid in one go (RULE 601.2h analogue for abilities): tap /
        untap the source, pay mana, pay life, sacrifice, discard, remove
        counters — then the ability goes on the stack to resolve later like any
        other object. ``tap_choices`` is the player's pick for a "tap N
        untapped <type>s you control" cost, if any (see `tap_for_mana`).
        ``sacrifice_choice`` is the player's pick of *which* permanent pays a
        "Sacrifice a <type>" cost (RULE 602.1 — a genuine cost choice, not an
        engine auto-pick; see `_sacrifice_candidate`); ``discard_choices`` is
        the same shape for a plain "discard N cards" cost component
        (`_resolve_discard_cost`). Both ``None`` fall back to an auto-pick,
        for non-interactive callers. Raises ValueError if the ability can't
        be paid for.

        ``target_groups``, when given, partitions ``targets`` per targeting
        effect (`StackItem.target_groups`) — needed only when the ability
        carries 2+ *different* targeting effects; omitted (``None``), every
        effect reads ``targets`` directly, unchanged from before this existed.
        """
        abilities = source.activated_abilities + source.granted_activated_abilities
        if not 0 <= ability_index < len(abilities):
            raise ValueError(f"{source.name} has no activated ability #{ability_index}")
        ability = abilities[ability_index]
        if target_groups is None:
            # RULE 115.1, same derivation the cast path makes: an ability
            # announcing 2+ requirements needs its flat picks split per
            # targeting effect (Ulvenwald Tracker's "target creature you
            # control fights another target creature").
            target_groups = partition_targets(ability_target_specs(ability), targets)
        if target_groups is not None and targets is None:
            # Same derivation `RulesEngine.cast_spell` does: every flat-
            # ``targets`` consumer (ward, the stack display) still needs to
            # see every chosen target, even when the groups are what the
            # effects actually resolve against.
            targets = [t for group in target_groups for t in group]
        if not self.can_activate(
            player, source, ability, x, tap_choices=tap_choices,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
        ):
            raise ValueError(f"cannot activate {source.name}'s ability")

        self._pay_activation_cost(
            player, source, ability.cost, x, tap_choices=tap_choices,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
        )
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
