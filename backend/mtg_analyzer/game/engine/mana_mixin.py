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
from ..effects.core import ActivatedAbility
from ..mana_abilities import (
    hand_mana_abilities_for,
    is_snow_source_for,
    mana_abilities_for,
    mana_source_kind_for,
    option_label,
    restriction_predicate_for_activation,
    restriction_predicate_for_cast,
    validate_color_split,
)
from .. import mana_potential
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


class ManaMixin:
    """Tapping for mana, incl. RULE 605.1a hand-zone mana abilities."""

    def tap_for_mana(
        self,
        player: Player,
        source: GameObject,
        option_index: int = 0,
        ability_index: int = 0,
        tap_choices: Optional[list[Any]] = None,
        color_split: Optional[dict[str, int]] = None,
        sacrifice_choice: Optional[int] = None,
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
        parameter existed. ``sacrifice_choice`` is the same cost choice
        `activate_ability` takes, for a "Sacrifice a creature: Add …"-shaped
        mana ability (Ashnod's Altar); ``None`` falls back to an auto-pick.
        Returns the mana added.
        """
        if source not in self.state.battlefield or source.controller_id != player.id:
            raise ValueError("can only tap your own permanents in play")
        if continuous.activation_prohibited(self.state, source, is_mana_ability=True):
            # RULE 602/605.1a: a mana ability *is* an activated ability, so a
            # blanket "activated abilities of artifacts can't be activated"
            # (Null Rod) silences it too — unlike a prohibition printed with
            # the "unless they're mana abilities" rider, which
            # `activation_prohibited` skips for this call.
            raise ValueError(f"{source.name}'s abilities can't be activated")
        abilities = mana_abilities_for(source, state=self.state)
        if not 0 <= ability_index < len(abilities):
            raise ValueError(f"{source.name} has no mana ability #{ability_index}")
        ability = abilities[ability_index]
        cost = ability.cost
        # RULE 602.5d, printed on a mana ability itself (Vivi Ornitier's
        # "Activate only during your turn and only once each turn.") — the
        # stack-based `can_activate`'s own checks
        # (`_only_during_your_turn_ok`/`once_per_turn`) don't run for this
        # no-stack path, so they're re-checked here instead.
        if cost.only_during_your_turn and not self._only_during_your_turn_ok(player):
            raise ValueError(f"{source.name}'s mana ability can only be activated during your turn")
        if cost.once_per_turn and ability_index in source.mana_abilities_activated_this_turn:
            raise ValueError(f"{source.name}'s mana ability has already been activated this turn")
        if not self._can_pay_activation_cost(
            player, source, cost, x=0, tap_choices=tap_choices, sacrifice_choice=sacrifice_choice,
            is_mana_ability=True,
        ):
            raise ValueError(f"cannot pay {source.name}'s mana ability cost")
        if not ability.options:
            raise ValueError(f"{source.name}'s mana ability produces nothing")
        if ability.any_combination and color_split is not None:
            total = sum(ability.options[0].values())
            # `ability.options` already carries only the printed colour
            # subset (one option per allowed colour — Vivi Ornitier's own
            # {U}/{R}, not full WUBRG), so the same list both offers the
            # single-colour buttons above and bounds the split here.
            allowed_colors = {next(iter(opt)) for opt in ability.options}
            produced = validate_color_split(color_split, total, allowed_colors)
        else:
            if not 0 <= option_index < len(ability.options):
                raise ValueError(f"invalid mana option {option_index} for {source.name}")
            produced = dict(ability.options[option_index])
        self._pay_activation_cost(
            player, source, cost, x=0, tap_choices=tap_choices, sacrifice_choice=sacrifice_choice,
            is_mana_ability=True,
        )
        if cost.once_per_turn:
            source.mana_abilities_activated_this_turn.add(ability_index)
        if cost.exile_creature:
            # Food Chain (MEC-40): the amount depends on *which* creature
            # just paid this cost — unresolvable at `mana_abilities_for`'s
            # offer-time (nothing chosen yet, and `mana_abilities_for`
            # always resolves/clears `amount_selector` into a fixed
            # ``options`` amount before `tap_for_mana` ever sees it, so
            # that field can't carry the "still unresolved" marker through
            # — `cost.exile_creature` itself is checked directly instead).
            # Recomputed here, now that `_pay_activation_cost` has stamped
            # `GameObject.last_cost_exiled_object_mv`, overriding whatever
            # placeholder `produced` held before payment.
            mv = getattr(source, "last_cost_exiled_object_mv", None) or 0
            color = next(iter(produced), "C")
            produced = {color: mv + 1}
        restriction = ability.restriction
        if restriction is not None and restriction.get("kind") == "chosen_type_spell":
            # Cavern of Souls/Unclaimed Territory-shaped: "of the chosen
            # type" names no fixed type at parse time — resolve it here,
            # per-instance, off this land's own RULE 601.2b ETB choice
            # (`GameObject.chosen_type`) into the ordinary ``type_spell``
            # shape `_restriction_allows_cast` already knows how to check.
            restriction = {
                "kind": "type_spell",
                "types": [source.chosen_type] if source.chosen_type else [],
                "allow_ability": restriction.get("allow_ability", False),
            }
        elif restriction is not None and restriction.get("kind") == "chosen_color_monocolored_spell":
            # Throne of Eldraine-shaped: "monocolored spells of that color"
            # names no fixed colour at parse time — resolve it here off this
            # artifact's own RULE 601.2b ETB choice (`GameObject.chosen_
            # color`) into the concrete ``monocolored_spell`` restriction
            # `_restriction_allows_cast` checks.
            restriction = {"kind": "monocolored_spell", "color": source.chosen_color}
        multiplier = continuous.mana_production_multiplier_for(self.state, player)
        if multiplier > 1:
            # RULE 605.1: "If you tap a permanent for mana, it produces N
            # times as much of that mana instead." (Nyxbloom Ancient) — a
            # genuine tapped-for-mana-only scaling, not a plain "add more
            # mana" rider, so it belongs here rather than folded into
            # `ability.options` (which a `color_split`-driven "any
            # combination" ability already resolved to a fixed total above).
            produced = {color: amount * multiplier for color, amount in produced.items()}
        override = continuous.mana_type_override_for(self.state, source, sum(produced.values()))
        if override is not None:
            # RULE 605.1: "If a land is tapped for 2 or more mana, it
            # produces {C} instead of any other type and amount." (MEC-36,
            # Damping Sphere) — checked against the true post-multiplier
            # total, right before it lands in the pool.
            produced = {override: sum(produced.values())}
        player.mana_pool.add_many(
            produced, restriction=restriction, source_kind=mana_source_kind_for(source),
            is_snow=is_snow_source_for(source),
        )
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
        mana_potential.record_mana_produced(self, player, produced)
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
                # Also under `player_id` — `DealDamageEffect`'s
                # ``selector="event_player"`` (Manabarbs/Burning Earth-shaped
                # "deals damage to that player" payoffs) always reads that
                # key specifically (`_event_player`'s default), same as
                # every other cast/draw/activate "that player" trigger.
                player_id=player.id,
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
            # `ability.options` already carries only the printed colour
            # subset (one option per allowed colour — Vivi Ornitier's own
            # {U}/{R}, not full WUBRG), so the same list both offers the
            # single-colour buttons above and bounds the split here.
            allowed_colors = {next(iter(opt)) for opt in ability.options}
            produced = validate_color_split(color_split, total, allowed_colors)
        else:
            if not 0 <= option_index < len(ability.options):
                raise ValueError(f"invalid mana option {option_index} for {source.name}")
            produced = dict(ability.options[option_index])
        self.rules.exile(source)
        player.mana_pool.add_many(
            produced, restriction=ability.restriction, source_kind=mana_source_kind_for(source),
            is_snow=is_snow_source_for(source),
        )
        if ability.self_damage:
            self.rules.deal_damage(player, ability.self_damage, source=source)
        if ability.self_rad_counters:
            self.rules.add_player_counters(player, ability.self_rad_counters, "rad", source=source)
        self.state.record_stat(player.id, "mana", amount=sum(produced.values()))
        mana_potential.record_mana_produced(self, player, produced)
        return produced
    def auto_tap_for(
        self,
        player: Player,
        source: Optional[GameObject] = None,
        cost: Optional[ManaCost] = None,
        x: int = 0,
        kicked: int = 0,
        kicker_x: int = 0,
    ) -> list[dict[str, int]]:
        """Find a tap plan (`game/mana_potential.py`'s `find_tap_plan`) for
        ``cost`` — or, if omitted, ``source``'s own effective cast cost — and
        actually execute it: the one real mutator this feature adds, built
        entirely out of the existing `tap_for_mana`/`activate_hand_mana_
        ability` calls above (RULE 605) rather than duplicating their
        mutation logic. Raises ``ValueError`` (surfaced like any other
        illegal action) when no plan is found.

        MEC-13: ``x``/``kicked``/``kicker_x`` (all ignored when an explicit
        ``cost`` is given, or when ``source`` is omitted) let a caller who
        *has* already chosen an X/Kicker value — a manual "top up mana for
        this announced X" click, mirroring what `_auto_tap_for_cast_if_
        needed` already does automatically once `cast_spell` itself is
        called with those values — get the true effective cost auto-tapped
        for, rather than always only the base X=0/unkicked one.
        """
        if cost is None:
            if source is None:
                raise ValueError("auto_tap_for needs a source or an explicit cost")
            cost = self.effective_cast_cost(player, source, x, kicked=kicked, kicker_x=kicker_x)
        plan = mana_potential.find_tap_plan(self, player, cost)
        if plan is None:
            raise ValueError("no untapped mana sources can pay this cost")
        produced: list[dict[str, int]] = []
        for step in plan.steps:
            if step.kind == "battlefield":
                obj = next(
                    o for o in self.state.permanents_controlled_by(player.id)
                    if o.instance_id == step.instance_id
                )
                produced.append(self.tap_for_mana(
                    player, obj,
                    option_index=step.option_index,
                    ability_index=step.ability_index,
                    color_split=step.color_split,
                ))
            else:
                obj = next(o for o in player.hand if o.instance_id == step.instance_id)
                produced.append(self.activate_hand_mana_ability(
                    player, obj,
                    option_index=step.option_index,
                    ability_index=step.ability_index,
                    color_split=step.color_split,
                ))
        return produced
