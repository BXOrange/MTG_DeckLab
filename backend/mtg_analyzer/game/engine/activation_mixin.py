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
from .. import combat, condition_query, continuous, durations, face_down, static_conditions, variants
from ...models import game_format
from ...models.game_format import GameFormat, get_format
from ..costs import (
    DISCARD_HAND,
    PAY_LIFE_X,
    REMOVE_COUNTERS_ANY,
    REMOVE_COUNTERS_X,
    SACRIFICE_COUNT_X,
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
    effects_target_specs,
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

#: "Sacrifice a green creature." (Natural Order, MEC-43) — the
#: ``"<color>_creature"`` additional-cost sentinel's own color-name to
#: WUBRG-letter mapping, matched against `GameObject.colors`.
_SACRIFICE_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

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
        hand_card_choices: Optional[list[int]] = None,
        assume_mana_available: bool = False,
    ) -> bool:
        """Whether ``player`` may activate ``ability`` of ``source`` right now.

        Requires ``source`` to be a permanent ``player`` controls carrying the
        ability, and every part of its cost to be payable (RULE 602.2a):
        mana, tapping/untapping the source, a life/discard/counter payment,
        and a legal thing to sacrifice. ``discard_choices`` is the same RULE
        602.1 cost-choice shape as ``sacrifice_choice``, for a plain
        "discard N cards" cost component (`_resolve_discard_cost`);
        ``hand_card_choices`` is its sibling for a "put a card from your hand
        on top of your library" cost component (Penance, MEC-30 —
        `_resolve_put_hand_card_cost`). Both ``None`` fall back to an
        auto-pick.

        A ``discard_self`` cost (Channel/Cycling, RULE 702.29/28.2h) is the
        one shape activated from *hand* instead of the battlefield — the
        ability still uses the stack like any other (unlike the mana-ability
        shortcut `activate_hand_mana_ability` uses), so it goes through this
        same path with a hand-zone legality check instead.

        ``assume_mana_available`` (default ``False``) — see `can_cast`'s
        identical parameter: skips only the mana-pool payability check,
        everything else about the cost (sacrifice, tap-others, life, …)
        still enforced normally. A read-only probe, never used by
        `activate_ability`'s own real legality gate.
        """
        # RULE 702.61b (Legolas's Quick Reflexes, MEC-43): a split second
        # spell on the stack blocks activating anything but a mana ability —
        # which never reaches `can_activate` at all (see `continuous.
        # split_second_active`'s own docstring), so no exemption is needed.
        if continuous.split_second_active(self.state):
            return False
        if ability.cost.discard_self:
            if source not in player.hand or source.owner_id != player.id:
                return False
        elif ability.cost.hand_zone:
            # Talon Gates of Madara-shaped "{N}: Put this card from your
            # hand onto the battlefield." — activated from hand like
            # `discard_self`, but the source ends up on the battlefield
            # rather than being discarded as the cost.
            if source not in player.hand or source.owner_id != player.id:
                return False
        elif ability.cost.graveyard_zone:
            # PAR-10: "Return this card from your graveyard to the
            # battlefield[, tapped]." — activated *from* the graveyard,
            # the same "not a battlefield permanent" carve-out `discard_self`
            # gets for the hand.
            if source not in player.graveyard or source.owner_id != player.id:
                return False
        elif isinstance(source, Emblem):
            # RULE 114.4 — an emblem's own activated ability (MEC-8) "functions
            # in the command zone": no permanent, no tap/summoning-sickness
            # state, just membership + controller like every other emblem
            # ability family (`continuous.py`'s static scan, `_collect_triggers`).
            if source not in player.emblems or source.controller_id != player.id:
                return False
        elif source not in self.state.permanents():
            return False  # RULE 702.26c: a phased-out permanent's abilities can't be activated
        elif source.controller_id != player.id and not ability.cost.any_player_may_activate:
            # "Any player may activate this ability." (Mercenaries, MEC-30)
            # is a standing exception to the ordinary "controller only"
            # eligibility gate — the ability's *effect* still protects
            # whoever actually activates it (RULE 602.2b), not this
            # permanent's own controller; see `GameContext.
            # resolving_controller_id`.
            return False
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
        if combat.is_detained(source):
            # RULE 701.35b: a detained permanent's activated abilities can't
            # be activated. (Mana abilities go through `tap_for_mana`, not
            # here — a detained permanent's mana ability staying usable is a
            # known minor deviation, no detain target in the cache has one.)
            return False
        if ability.once_per_turn and ability._last_activated_turn == self.state.turn_number:
            return False
        if getattr(ability, "once_per_game", False) and (
            ability.description in getattr(source, "used_once_per_game_abilities", set())
        ):
            # PAR-28 / RULE 702.177a: Exhaust & Power-up — "Activate only
            # once." A per-ability, per-game cap keyed on the ability's own
            # printed text (a card with two exhaust abilities tracks them
            # separately); recorded in `activate_ability`, never reset.
            return False
        if ability.cost.is_loyalty and not self._can_activate_loyalty(player, source):
            return False
        if ability.cost.sorcery_speed_only and not self._sorcery_speed_ok(player):
            return False
        if ability.cost.only_during_your_turn and not self._only_during_your_turn_ok(player):
            return False
        if ability.cost.activation_condition and not static_conditions.condition_holds(
            ability.cost.activation_condition, self.state, source=source, controller_id=player.id
        ):
            # PAR-10: "…and only if `<condition>`." — the same RULE 613.6
            # whitelist a permanent's own "as long as" static is checked
            # against, evaluated live rather than cached (Hall of Oracles'
            # own instant/sorcery-this-turn flag can flip mid-turn).
            return False
        if ability.cost.class_level is not None and not self._can_activate_class_level(
            source, ability.cost.class_level
        ):
            return False
        return self._can_pay_activation_cost(
            player, source, ability.cost, x, tap_choices=tap_choices,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            hand_card_choices=hand_card_choices,
            assume_mana_available=assume_mana_available,
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
    def _only_during_your_turn_ok(self, player: Player) -> bool:
        """RULE 602.5d's "Activate only during your turn." — wider than
        `_sorcery_speed_ok`: still legal at instant speed with a non-empty
        stack or outside the controller's own main phase, only ruled out on
        someone else's turn (Wishclaw Talisman-shaped)."""
        return player is self.state.active_player
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
        self, player: Player, ability: ActivatedAbility, source: GameObject,
        mode: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Target requirements of an activated ability, with legal options —
        the same shape `_cast_action` uses for spells (RULE 602.2b / 115).

        Reads `GameEffect.target_specs` (not ``target_spec``) so a single
        effect announcing two requirements — "target creature you control
        fights another target creature", Ulvenwald Tracker — offers both,
        and carries the same ``count``/cross-target keys
        `targeting.requirements_with_targets` gives the cast path, so the
        board's targeting rounds behave identically for an ability.

        ``mode`` (RULE 700.2, MEC-43): for a modal ability, ``ability.
        effects`` is empty — the real requirements live on the chosen
        mode's own effects instead (`_modal_activate_actions` always
        passes this; a non-modal ability ignores it)."""
        specs = (
            effects_target_specs(ability.modes[mode]["effects"])
            if ability.modes and mode is not None
            else ability_target_specs(ability)
        )
        out: list[dict[str, Any]] = []
        for spec in specs:
            entry = {
                "kind": spec.kind,
                "optional": spec.optional,
                # RULE 601.2c — see `targeting.resolved_count`.
                "count": resolved_count(spec, self.state, player.id, source),
                "label": spec.label(),
                "options": legal_targets(self.state, player.id, spec, source=source),
                "distinct_controllers": spec.distinct_controllers,
                "distinct_from_others": spec.distinct_from_others,
                "polarity": spec.polarity,
            }
            # ENG-30: "N or M target X" range — see `TargetSpec.count_max`.
            if spec.count_max is not None:
                entry["count_max"] = spec.count_max
            out.append(entry)
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
        wildcard = continuous.any_color_for_activation(self.state, player, source)
        # MEC-43: K'rrik, Son of Yawgmoth's standing "pay 2 life instead of
        # a {B} pip" permission (`continuous.life_for_mana_pip_color`).
        extra_life_color = continuous.life_for_mana_pip_color(self.state, player)
        for x in range(bound, -1, -1):
            if player.mana_pool.can_pay(
                mana.with_x(x), life_available=player.life, allows_restriction=allows_restriction,
                wildcard=wildcard, extra_life_color=extra_life_color,
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
        self,
        source: GameObject,
        mana: "ManaCost",
        cost: Optional["ActivationCost"] = None,
        is_mana_ability: bool = False,
    ) -> "ManaCost":
        """Apply any "activated abilities cost {N} less/more to activate"
        static scoped to ``source`` (Power Artifact-shaped reduction, RULE
        601.2f-adjacent; Suppression Field/Tithe Taker-shaped *tax*, MEC-12)
        — nothing in the ordinary activation-cost path consulted either
        before this (unlike a spell's cast cost, `continuous.
        cost_reduction_for`). See `continuous.activation_cost_reduction_for`
        for the static's own "can't reduce below N mana" floor, honoured
        here by capping the reduction rather than trusting `reduce_generic`'s
        own floor-at-zero — meaningless for a tax, which only ever grows the
        cost via `increase_generic`, the same "positive reduces, negative
        increases" convention `CastingMixin._adjust_cost` already uses for a
        spell's own net.

        ``is_mana_ability`` is passed straight through to `continuous.
        activation_cost_reduction_for` so a static's "…unless they're mana
        abilities" carve-out actually exempts one; ``tap_for_mana`` is the
        only caller that ever activates one.

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
        reduction, floor = continuous.activation_cost_reduction_for(
            self.state, source, is_mana_ability=is_mana_ability
        )
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
        if (
            cost is not None
            and getattr(cost, "powerup_cost_reduction", False)
            and source.turn_entered == self.state.turn_number
        ):
            # PAR-28 / Power-up: "Reduce the cost by its mana cost if it
            # entered this turn." — a generic reduction equal to the
            # source's own printed mana value (RULE 202.3).
            reduction += int(getattr(source.card, "converted_mana_cost", 0) or 0)
        if reduction < 0:
            return mana.increase_generic(-reduction)
        if reduction == 0:
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
        hand_card_choices: Optional[list[int]] = None,
        assume_mana_available: bool = False,
        is_mana_ability: bool = False,
    ) -> bool:
        # {T} needs an untapped source; {Q} a tapped one. Either symbol also
        # needs a non-summoning-sick source unless it has haste (RULE 302.6,
        # 602.5e, 702.10b) — the same rule the mana-tap path enforces.
        if cost.taps_self and (source.tapped or self._summoning_sick_for_tap(source)):
            return False
        if cost.untaps_self and (not source.tapped or self._summoning_sick_for_tap(source)):
            return False
        mana = cost.mana.with_x(x) if cost.mana.has_variable else cost.mana
        mana = self._reduced_activation_mana(source, mana, cost, is_mana_ability=is_mana_ability)
        if cost.spend_only_chosen_color:
            # Throne of Eldraine-shaped colour-lock: the whole mana cost must
            # be paid with mana of the source's chosen colour (RULE 601.2b) —
            # modeled by requiring that many pips of `chosen_color` instead
            # of the ordinary any-colour generic solve.
            locked = self._chosen_color_locked_cost(source, mana)
            if locked is None:
                return False  # no chosen colour at all — not a mana-availability question
            if not assume_mana_available and not player.mana_pool.can_pay(
                locked, life_available=player.life
            ):
                return False
        elif mana.symbols and not assume_mana_available:
            allows_restriction = restriction_predicate_for_activation(source, has_x=cost.mana.has_variable)
            wildcard = continuous.any_color_for_activation(self.state, player, source)
            # MEC-43: K'rrik, Son of Yawgmoth's standing "pay 2 life instead
            # of a {B} pip" permission (`continuous.life_for_mana_pip_color`).
            extra_life_color = continuous.life_for_mana_pip_color(self.state, player)
            if not player.mana_pool.can_pay(
                mana, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard,
                extra_life_color=extra_life_color,
            ):
                return False
        # Yasharn, Implacable Earth (MEC-40): "Players can't pay life or
        # sacrifice nonland permanents to cast spells or activate
        # abilities." — same choke point as `_can_pay_additional_cast_cost`'s
        # own check, checked before the ordinary payability gates below.
        if cost.pay_life and continuous.cost_restricted(self.state, "pay_life"):
            return False
        if cost.sacrifice and cost.sacrifice != "land" and continuous.cost_restricted(
            self.state, "sacrifice_nonland_permanent"
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
        if cost.put_hand_card_on_library:
            if self._resolve_put_hand_card_cost(player, hand_card_choices) is None:
                return False
        if cost.sacrifice and self._sacrifice_candidate(
            player, source, cost.sacrifice, chosen_id=sacrifice_choice
        ) is None:
            return False
        if cost.exile_creature and self._exile_creature_candidate(
            player, chosen_id=sacrifice_choice
        ) is None:
            return False
        if cost.collect_evidence and not self.rules.collect_evidence_possible(
            player, cost.collect_evidence
        ):
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
        if cost.crew_power:
            if self._resolve_crew_cost(player, source, cost.crew_power, tap_choices) is None:
                return False
        if cost.saddle_power:
            # RULE 702.171a (Guardian Sunmare, MEC-40) — identical pool
            # shape to `crew_power` just above, reusing the same resolver.
            if self._resolve_crew_cost(player, source, cost.saddle_power, tap_choices) is None:
                return False
        if cost.station:
            # RULE 702.184a: "Tap another untapped creature you control" —
            # an exact-count-one choice from `_crew_pool`'s own "other
            # untapped creatures you control" pool (see `_resolve_station_
            # cost`), unlike `crew_power`/`saddle_power`'s threshold-sized
            # subset just above.
            if self._resolve_station_cost(player, source, tap_choices) is None:
                return False
        if cost.sacrifice_count:
            # Reuses the `tap_others` cost's own `tap_choices` slot for its
            # chosen instance ids — no printed card needs both a
            # `tap_others` and a `sacrifice_count` cost component at once,
            # so one "which N did the player pick" parameter suffices
            # rather than growing this already-long signature further.
            count, subtype = cost.sacrifice_count
            if count == SACRIFICE_COUNT_X:
                # RULE 601.2b analogue (Grim Hireling, MEC-43): the amount
                # is the ability's own announced ``x``, mirroring
                # `remove_counters`'s `REMOVE_COUNTERS_X` just above — a
                # negative announced X is never legal to pay.
                if x < 0:
                    return False
                count = x
            if self._resolve_sacrifice_count(player, count, subtype, tap_choices) is None:
                return False
        if cost.exile_top_of_library and len(player.library) < cost.exile_top_of_library:
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

        ``subtype`` is usually a real creature subtype ("Elves"), but a
        RULE 118.9 alt-cast cost can also print the bare main type ("tap an
        untapped creature you control", Dark Triumph's own "cycle"
        siblings) — `continuous.has_subtype` alone would never match that
        (a main type isn't a subtype), so `has_card_type` is tried too.
        """
        return [
            o for o in self.state.permanents_controlled_by(player.id)
            if not o.tapped and (
                continuous.has_subtype(o, subtype) or continuous.has_card_type(o, subtype)
            )
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
    def _crew_pool(self, player: Player, source: GameObject) -> list[GameObject]:
        """Every untapped creature ``player`` controls other than ``source``
        itself — RULE 702.122a's "any number of **other** untapped creatures
        you control" — eligible to crew a Vehicle. Not gated by summoning
        sickness (RULE 302.6, same reasoning as `_tap_others_pool`: crewing
        taps a creature to pay a *different* permanent's cost, not activate
        its own {T} ability).
        """
        return [
            o for o in self.state.permanents_controlled_by(player.id)
            if o is not source and o.is_creature and not o.tapped
        ]
    def _crew_cost_choice(
        self, player: Player, source: GameObject, cost: "ActivationCost"
    ) -> dict[str, Any]:
        """The offer-time UI shape for a `crew_power` cost: the required
        power threshold and the full eligible pool, each with its own live
        power — the player picks *any subset* summing to at least
        ``power_required``, unlike `_tap_cost_choice`'s exact ``count``."""
        pool = self._crew_pool(player, source)
        return {
            "power_required": cost.crew_power,
            "options": [
                {"instance_id": o.instance_id, "name": o.name, "power": o.power or 0}
                for o in pool
            ],
        }
    def _resolve_crew_cost(
        self,
        player: Player,
        source: GameObject,
        power_required: int,
        chosen_ids: Optional[list[Any]],
    ) -> Optional[list[GameObject]]:
        """The creatures to actually tap for a `crew_power` cost (RULE
        702.122a's "total power N or greater") — an "any number from a
        pool" choice sized by a power *threshold*, unlike
        `_resolve_pool_cost`'s exact ``count``.

        ``chosen_ids`` is the player's own pick — validated against the
        pool and required to meet the threshold, never trimmed or padded
        (RULE 602.1: any *legal* subset is the player's own choice, not the
        engine's to second-guess). ``None`` falls back to an auto-pick for
        non-interactive callers (tests, the goldfish auto-player): the
        fewest creatures, highest power first, that reach the threshold —
        so an automated caller doesn't tap more of the board than it has to.
        """
        pool = self._crew_pool(player, source)
        by_id = {o.instance_id: o for o in pool}
        if chosen_ids is not None:
            chosen: list[GameObject] = []
            seen: set[Any] = set()
            for iid in chosen_ids:
                if iid in seen or iid not in by_id:
                    return None
                seen.add(iid)
                chosen.append(by_id[iid])
            if sum(o.power or 0 for o in chosen) < power_required:
                return None
            return chosen
        ranked = sorted(pool, key=lambda o: o.power or 0, reverse=True)
        auto_chosen: list[GameObject] = []
        total = 0
        for o in ranked:
            if total >= power_required:
                break
            auto_chosen.append(o)
            total += o.power or 0
        return auto_chosen if total >= power_required else None
    def _station_cost_choice(self, player: Player, source: GameObject, cost: "ActivationCost") -> dict[str, Any]:
        """The offer-time UI shape for a `station` cost (RULE 702.184a): an
        exact count of one, from `_crew_pool`'s own "other untapped
        creatures you control" pool (reused unchanged — RULE 702.184a's own
        pool is worded identically to Crew's) — the same ``count``/
        ``options`` shape `_tap_cost_choice` uses, just sourced from the
        pool that excludes the source itself."""
        pool = self._crew_pool(player, source)
        return {
            "count": 1,
            "options": [
                {"instance_id": o.instance_id, "name": o.name, "power": o.power or 0}
                for o in pool
            ],
        }
    def _resolve_station_cost(
        self, player: Player, source: GameObject, chosen_ids: Optional[list[Any]]
    ) -> Optional[list[GameObject]]:
        """The single creature to tap for a `station` cost (RULE 702.184a)
        — `_crew_pool`'s own "other untapped creatures you control" pool
        (excludes ``source`` itself, unlike `_tap_others_pool`'s "including
        the ability's own source" convention — RULE 702.184a's "**another**
        untapped creature" is explicit), resolved with `_resolve_pool_cost`'s
        exact-count-one choice rather than `_resolve_crew_cost`'s
        any-subset-meeting-a-threshold one."""
        pool = self._crew_pool(player, source)
        return self._resolve_pool_cost(pool, 1, chosen_ids)
    def _sacrifice_count_pool(self, player: Player, subtype: str) -> list[GameObject]:
        """Every permanent of type ``subtype`` ``player`` controls, eligible
        to pay a "Sacrifice N `<type>`s" cost (Samwise Gamgee's "Sacrifice
        three Foods:") — the `sacrifice_count` sibling of `_tap_others_pool`,
        subtype-matched the same way (`continuous.has_subtype`) rather than
        `_matches_sacrifice_type`'s broad main-type words, since a printed
        count always names a specific subtype (Food/Clue/Treasure/a
        creature type), never a main type."""
        return [
            o for o in self.state.permanents_controlled_by(player.id)
            if continuous.has_subtype(o, subtype)
        ]
    def _resolve_sacrifice_count(
        self, player: Player, count: int, subtype: str, chosen_ids: Optional[list[Any]]
    ) -> Optional[list[GameObject]]:
        """The permanents to actually sacrifice for a `sacrifice_count`
        cost — the `_resolve_tap_others` counterpart for sacrifice."""
        pool = self._sacrifice_count_pool(player, subtype)
        return self._resolve_pool_cost(pool, count, chosen_ids)
    def _sacrifice_count_cost_choice(
        self, player: Player, cost: "ActivationCost"
    ) -> dict[str, Any]:
        """The offer-time UI shape for a `sacrifice_count` cost — the
        `_tap_cost_choice` counterpart for sacrifice."""
        count, subtype = cost.sacrifice_count
        pool = self._sacrifice_count_pool(player, subtype)
        return {
            "count": count,
            "options": [{"instance_id": o.instance_id, "name": o.name} for o in pool],
        }
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
    def _exile_creature_candidate(
        self, player: Player, chosen_id: Optional[int] = None,
    ) -> Optional[GameObject]:
        """A creature ``player`` controls, eligible to pay an
        ``exile_creature`` cost (Food Chain, MEC-40 — "Exile a creature you
        control: …") — the exile-cost sibling of `_sacrifice_candidate`,
        reusing the same "chosen id, or first candidate" shape and the same
        ``sacrifice_choice`` UI slot (no printed card needs both an
        ordinary ``sacrifice`` *and* an ``exile_creature`` cost at once).
        """
        candidates = [
            obj for obj in self.state.permanents_controlled_by(player.id) if obj.is_creature
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
        if what == "creature_or_planeswalker":
            # RULE 306/302: Tevesh Szat's "another creature or planeswalker".
            # Mirrors `rules.misc_mixin._matches_permanent_type` (the
            # effect-driven sacrifice path) — this is the cost-*payment*
            # counterpart, previously missing every compound word that
            # function already handled, so a cost using one silently fell
            # through to the "any permanent" catch-all below instead of the
            # narrower RAW-correct set.
            return obj.is_creature or obj.card.is_planeswalker
        if what == "creature_artifact_or_land":
            # PAR-13: "sacrifice a creature, artifact, or land" (Sandfall
            # Cell) — see `_matches_permanent_type`'s matching branch.
            return obj.is_creature or obj.card.is_artifact or obj.is_land
        if what == "artifact_or_creature":
            # Deadly Dispute/Costly Plunder-shaped additional cost.
            return obj.is_creature or obj.card.is_artifact
        color_letter = _SACRIFICE_COLOR_WORDS.get(what[: -len("_creature")]) if what.endswith("_creature") else None
        if color_letter is not None:
            # "Sacrifice a green creature." (Natural Order, MEC-43) — a
            # color+type compound sacrifice cost, a `<color>_creature`
            # sentinel this catalogue chooses itself (not derived from
            # printed text by a parser handler), matched against the
            # object's own layer-5 derived colours.
            return obj.is_creature and color_letter in obj.colors
        # A genuine subtype word (RULE 205.3 — "Sacrifice a Mountain"/
        # "Sacrifice a Human", `costs._SACRIFICE_RE`'s generic single-word
        # capture from oracle text) — matched narrowly rather than falling
        # through to "any permanent", which had been silently accepting
        # *every* sacrifice choice for a cost like this (a latent bug: no
        # shipped card had exercised a non-generic word here before MEC-12's
        # alt-cost pitch family surfaced it).
        return continuous.has_subtype(obj, what)
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
    def _resolve_put_hand_card_cost(
        self, player: Player, chosen_ids: Optional[list[int]]
    ) -> Optional[list[GameObject]]:
        """The card to actually put on top of the library for a "put a card
        from your hand on top of your library" cost component (Penance,
        MEC-30) — the `_resolve_discard_cost` counterpart for this cost
        shape, sharing its hand pool (any card in hand is eligible; unlike
        `_discard_cost_pool`'s ``exclude``, no activated ability's own source
        is ever a hand card) and `_resolve_pool_cost`'s "chosen_ids, or
        auto-pick" resolution."""
        return self._resolve_pool_cost(list(player.hand), 1, chosen_ids)
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
        hand_card_choices: Optional[list[int]] = None,
        is_mana_ability: bool = False,
    ) -> None:
        """Charge every component of ``cost`` (RULE 601.2h analogue for
        abilities) — tap/untap the source, tap other permanents, pay mana,
        pay life, sacrifice, discard, add/remove counters, loyalty. Shared by
        `activate_ability` and `tap_for_mana` (a mana ability's cost is
        charged exactly the same way, just without going on the stack).
        Assumes `_can_pay_activation_cost` already passed (with the same
        ``tap_choices``/``sacrifice_choice``/``discard_choices``/
        ``hand_card_choices``, if any).
        """
        # MEC-43: cleared unconditionally, same as `_pay_additional_cast_
        # cost`'s own reset — a stale value from a *previous* activation of
        # this same permanent's sacrifice cost must not leak into a later
        # one that didn't sacrifice anything (or sacrificed nothing found).
        source.sacrificed_cost_mana_value = None
        source.sacrificed_cost_power = None
        source.station_tapped_power = None
        if cost.taps_self:
            self.rules.set_tapped(source, True)
        if cost.untaps_self:
            # `self.rules.set_tapped` (MEC-43 round 4E, Mesmeric Orb), not
            # the plain model-level `source.untap()` — a paid ``{Q}``
            # untap is still a genuine RULE 603.2 "becomes untapped"
            # transition, same as any other untap route.
            self.rules.set_tapped(source, False)
        if cost.tap_others:
            count, subtype = cost.tap_others
            for obj in self._resolve_tap_others(player, source, count, subtype, tap_choices) or []:
                self.rules.set_tapped(obj, True)
        if cost.crew_power:
            # RULE 702.122b: a creature "crews" a Vehicle exactly when
            # tapped to pay this cost — recorded on `source` (RULE
            # 702.122c's "crewed by") regardless of whether the ability
            # later resolves, since the tap already happened.
            for obj in self._resolve_crew_cost(player, source, cost.crew_power, tap_choices) or []:
                self.rules.set_tapped(obj, True)
                if obj.instance_id not in source.crewed_by_ids:
                    source.crewed_by_ids.append(obj.instance_id)
        if cost.saddle_power:
            # RULE 702.171a (Guardian Sunmare, MEC-40) — same pool/tap
            # mechanics as ``crew_power`` just above; no "saddled_by"
            # bookkeeping equivalent to `crewed_by_ids` since no printed
            # card asks "who saddled it".
            for obj in self._resolve_crew_cost(player, source, cost.saddle_power, tap_choices) or []:
                self.rules.set_tapped(obj, True)
        if cost.station:
            # RULE 702.184a: tap the chosen creature, then remember its
            # power (`GameObject.station_tapped_power`) for the resolving
            # `add_counters` effect to read — the cost-payment side of the
            # `sacrificed_cost_power` idiom.
            tapped = self._resolve_station_cost(player, source, tap_choices) or []
            for obj in tapped:
                self.rules.set_tapped(obj, True)
            if tapped:
                source.station_tapped_power = tapped[0].power or 0
        if cost.sacrifice_count:
            count, subtype = cost.sacrifice_count
            if count == SACRIFICE_COUNT_X:
                count = x  # see `_can_pay_activation_cost`'s matching branch
            for obj in self._resolve_sacrifice_count(player, count, subtype, tap_choices) or []:
                self.rules.put_into_graveyard(obj)
        mana = cost.mana.with_x(x) if cost.mana.has_variable else cost.mana
        mana = self._reduced_activation_mana(source, mana, cost, is_mana_ability=is_mana_ability)
        if cost.spend_only_chosen_color:
            # See `_can_pay_activation_cost` — pay the whole cost as
            # `chosen_color` pips (Throne of Eldraine).
            locked = self._chosen_color_locked_cost(source, mana)
            if locked is not None and locked.symbols:
                player.mana_pool.pay(locked, life_available=player.life)
        elif mana.symbols:
            allows_restriction = restriction_predicate_for_activation(source, has_x=cost.mana.has_variable)
            wildcard = continuous.any_color_for_activation(self.state, player, source)
            # MEC-43: K'rrik, Son of Yawgmoth's standing "pay 2 life instead
            # of a {B} pip" permission (`continuous.life_for_mana_pip_color`).
            extra_life_color = continuous.life_for_mana_pip_color(self.state, player)
            life_spent = player.mana_pool.pay(
                mana, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard,
                extra_life_color=extra_life_color,
            )
            self.rules.lose_life(player, life_spent, cause="cost")
            if cost.note_spent_color:
                # "Note the type of mana spent to pay this activation
                # cost." (Jeweled Amulet, MEC-43) — `ManaPool.pay` just
                # stamped which type(s) actually left the pool; a single
                # generic pip (this card's own cost) always resolves to
                # exactly one type, but fall back to the first key
                # deterministically if a future caller's cost ever mixes
                # colored and generic pips.
                spent = player.mana_pool.last_payment_types
                if spent:
                    source.noted_mana_color = next(iter(spent))
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
                # MEC-43 (Birthing Pod/Oswald Fiddlebender): mirrors
                # `_pay_additional_cast_cost`'s own `sacrificed_cost_mana_
                # value` stamp, which only ever covered a *spell's* RULE
                # 601.2b additional cost — an activated ability's own
                # sacrifice cost had never stamped anything at all, the
                # same "stamp on `source` for cost-payment-driven
                # magnitude" idiom `cost.exile_creature`'s own
                # `last_cost_exiled_object_mv` just below already uses.
                source.sacrificed_cost_mana_value = victim.card.converted_mana_cost
                # MEC-43 (Altar of Dementia): the *power* sibling of the
                # stamp just above — read `victim.power` (derived, RULE
                # 613) rather than the card's printed value, since a
                # sacrificed creature's power may have been modified by the
                # layer engine before it left the battlefield.
                source.sacrificed_cost_power = victim.power
        if cost.exile_creature:
            exiled = self._exile_creature_candidate(player, chosen_id=sacrifice_choice)
            if exiled is not None:
                mv = exiled.card.converted_mana_cost or 0
                self.rules.exile(exiled)
                # "…where X is 1 plus the exiled creature's mana value."
                # (Food Chain, MEC-40) — the mana ability's own amount
                # depends on *which* creature just paid this cost, only
                # known now; `mana_options_for`'s own pre-resolved
                # ``options`` can't reach it (nothing chosen yet at offer
                # time), so `GameEngine.tap_for_mana` re-reads this stamp
                # and overrides the produced amount right after payment.
                source.last_cost_exiled_object_mv = mv
        if cost.return_to_hand:
            bounced = self._return_to_hand_candidate(player, cost.return_to_hand)
            if bounced is not None:
                self.rules.return_to_hand(bounced)
        if cost.unattach_self:
            source.last_unattached_from_id = source.attached_to
            source.attached_to = None
        if cost.exile_top_of_library:
            for _ in range(cost.exile_top_of_library):
                if not player.library:
                    break
                self.rules.exile(player.library[-1])
        if cost.collect_evidence:
            # RULE 701.59a — exile graveyard cards totalling `collect_evidence`
            # mana value or more; `RulesEngine.collect_evidence` auto-picks
            # and fires `EventType.COLLECTED_EVIDENCE`.
            self.rules.collect_evidence(player, cost.collect_evidence)
        if cost.put_hand_card_on_library:
            chosen = self._resolve_put_hand_card_cost(player, hand_card_choices)
            if chosen:
                self.rules.put_hand_card_on_top_of_library(chosen[0])
        if cost.discard:
            if cost.discard == DISCARD_HAND:
                self.rules.discard(player, len(player.hand))
            else:
                chosen = self._resolve_discard_cost(player, cost.discard, discard_choices)
                for card in chosen or []:
                    self.rules.discard_specific(card)
        if cost.discard_self:
            instance_id, controller_id, name = source.instance_id, player.id, source.name
            self.rules.discard_specific(source)
            if cost.is_cycling:
                # RULE 702.28c: "when you cycle this card" — fired *after*
                # the discard (the card is genuinely in the graveyard by
                # the time the trigger checks), so a "return this from your
                # graveyard" bonus effect on the same cycle sees it there;
                # `_collect_cycled_triggers` is the graveyard-scoped scan
                # that finds the now-discarded source's own trigger.
                source.cycling_x_paid = x
                self.state.fire_event(
                    GameEvent(
                        EventType.CYCLED, instance_id=instance_id,
                        controller_id=controller_id, object=name,
                    )
                )
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
    def _auto_tap_for_activation_if_needed(
        self,
        player: Player,
        source: GameObject,
        ability: ActivatedAbility,
        x: int,
        tap_choices: Optional[list[Any]] = None,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
        hand_card_choices: Optional[list[int]] = None,
    ) -> None:
        """"Automatisches Tappen" for an ordinary activated ability's own
        mana cost — the `activate_ability` counterpart of `CastingMixin.
        _auto_tap_for_cast_if_needed`; see that docstring for the shared
        reasoning (only fires when nothing but mana blocks the activation,
        via the same ``assume_mana_available`` probe, and never spends a
        sacrifice- or hand-exile-cost source — `game/mana_potential.py`).
        """
        if self.can_activate(
            player, source, ability, x, tap_choices=tap_choices,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            hand_card_choices=hand_card_choices,
        ):
            return
        if not self.can_activate(
            player, source, ability, x, tap_choices=tap_choices,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            hand_card_choices=hand_card_choices,
            assume_mana_available=True,
        ):
            return  # illegal for a reason other than mana — never auto-tap
        cost = ability.cost
        mana = cost.mana.with_x(x) if cost.mana.has_variable else cost.mana
        mana = self._reduced_activation_mana(source, mana, cost)
        if cost.spend_only_chosen_color:
            locked = self._chosen_color_locked_cost(source, mana)
            if locked is None:
                return
            mana = locked
        try:
            self.auto_tap_for(player, cost=mana)
        except ValueError:
            pass
    def _resolve_activation_mode(
        self, ability: ActivatedAbility, mode: Optional[int]
    ) -> list[Any]:
        """The effects this activation actually resolves with (RULE 700.2,
        `ActivatedAbility.modes` — MEC-43, Umezawa's Jitte's "Remove a
        charge counter: Choose one — …") — ``ability.effects`` unchanged for
        an ordinary (non-modal) ability, or the chosen mode's own effects
        for a modal one. Deliberately scoped to plain "choose one"
        (``ability.modes`` only ever holds that shape — see
        `effect_binder.bind_ability`'s own guard): no activated ability in
        this cache needs "choose N"/"or both" yet.
        """
        if not ability.modes:
            return ability.effects
        if mode is None or not 0 <= mode < len(ability.modes):
            raise ValueError(
                f"{ability.description or 'ability'}: must choose a mode in "
                f"0..{len(ability.modes) - 1}"
            )
        return list(ability.modes[mode]["effects"])
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
        hand_card_choices: Optional[list[int]] = None,
        mode: Optional[int] = None,
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
        (`_resolve_discard_cost`); ``hand_card_choices`` is its sibling for a
        "put a card from your hand on top of your library" cost component
        (Penance, MEC-30 — `_resolve_put_hand_card_cost`). All ``None`` fall
        back to an auto-pick, for non-interactive callers. Raises ValueError
        if the ability can't be paid for.

        ``target_groups``, when given, partitions ``targets`` per targeting
        effect (`StackItem.target_groups`) — needed only when the ability
        carries 2+ *different* targeting effects; omitted (``None``), every
        effect reads ``targets`` directly, unchanged from before this existed.

        ``mode`` (RULE 700.2, MEC-43) picks which of a *modal* ability's
        printed modes resolves — required whenever ``ability.modes`` is set
        (`_resolve_activation_mode`), ignored otherwise. The mode is chosen
        before targets are gathered, same ordering RULE 601.2b gives a modal
        spell's own mode-then-target choice: the chosen mode's own effects,
        not ``ability.effects`` (empty for a modal ability), decide what
        target requirements this activation actually has.
        """
        abilities = source.activated_abilities + source.granted_activated_abilities
        if not 0 <= ability_index < len(abilities):
            raise ValueError(f"{source.name} has no activated ability #{ability_index}")
        ability = abilities[ability_index]
        resolved_effects = self._resolve_activation_mode(ability, mode)
        if target_groups is None:
            # RULE 115.1, same derivation the cast path makes: an ability
            # announcing 2+ requirements needs its flat picks split per
            # targeting effect (Ulvenwald Tracker's "target creature you
            # control fights another target creature").
            target_groups = partition_targets(effects_target_specs(resolved_effects), targets)
        if target_groups is not None and targets is None:
            # Same derivation `RulesEngine.cast_spell` does: every flat-
            # ``targets`` consumer (ward, the stack display) still needs to
            # see every chosen target, even when the groups are what the
            # effects actually resolve against.
            targets = [t for group in target_groups for t in group]
        self._auto_tap_for_activation_if_needed(
            player, source, ability, x, tap_choices=tap_choices,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            hand_card_choices=hand_card_choices,
        )
        if not self.can_activate(
            player, source, ability, x, tap_choices=tap_choices,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            hand_card_choices=hand_card_choices,
        ):
            raise ValueError(f"cannot activate {source.name}'s ability")

        self._pay_activation_cost(
            player, source, ability.cost, x, tap_choices=tap_choices,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            hand_card_choices=hand_card_choices,
        )
        # RULE 107.3c/601.2b: remember the announced X on the ability's own
        # source, mirroring `RulesEngine.cast_spell`'s `obj.x_paid` stamp —
        # every existing X-reading effect (`AddCountersEffect.x_multiplier`,
        # etc.) already reads `getattr(self.source, "x_paid", 0)`, so this
        # is what makes an activated ability's own ``{X}`` cost reach them
        # too (Lazotep Quarry, MEC-41). A second ability activated off the
        # same source before this one resolves would overwrite it — rare
        # enough (no shipped card depends on two X-cost activations of the
        # same permanent racing on the stack) to accept as-is.
        source.x_paid = x
        if ability.once_per_turn:
            ability._last_activated_turn = self.state.turn_number
        if getattr(ability, "once_per_game", False) and ability.description:
            # PAR-28 / RULE 702.177a: mark this Exhaust/Power-up ability used
            # for the rest of the game (keyed on its printed text so a card
            # with two of them tracks each separately).
            source.used_once_per_game_abilities.add(ability.description)

        # RULE 700.2: a modal ability's `StackItem` carries the chosen
        # mode's own flat effects list directly, not the `ActivatedAbility`
        # wrapper — its own `effects` field is empty, so `apply()` would
        # have nothing to resolve (`_place_trigger`'s `effects_override`
        # is the exact triggered-ability precedent for this).
        item_description = ability.description or f"{source.name} ability"
        if ability.modes:
            item_description = ability.modes[mode].get("description") or item_description
        item = StackItem(
            kind="ability",
            controller_id=player.id,
            effects=resolved_effects if ability.modes else [ability],
            description=item_description,
            targets=targets,
            target_groups=target_groups,
            x=x,
            source=source,
        )
        self.state.stack.append(item)
        self.state.fire_event(
            GameEvent(
                EventType.ACTIVATED_ABILITY,
                player_id=player.id, controller_id=player.id,
                instance_id=source.instance_id,
                # `source` can be an `Emblem` (RULE 114.4's rare own
                # activated ability) — no card frame, so no type words.
                object_types=sorted(getattr(source, "type_words", None) or []),
                # RULE 706.10 (Rings of Brighthearth): the ability's own
                # stack identity, so a "copy that ability" trigger can find
                # the exact `StackItem` just pushed above — an ability item
                # has no `GameObject` of its own to name by `instance_id`
                # (ENG-26, `StackItem.stack_id`).
                stack_id=item.stack_id,
            )
        )
        self.rules.check_ward(item, player)
        # RULE 117.3c: taking an action reclaims priority for its taker.
        self.give_priority(player)
