"""Effect type hierarchy + registry (RULE 611/603/614/602, docs/07 PART 2/4/6).

docs/07 is emphatic: "Cards don't just do things. Cards CHANGE THE
RULES." So effects are first-class objects the engine consults, not
hardcoded branches. There are four kinds (docs/07 PART 2):

* ``StaticEffect``      — continuous modifiers (RULE 611), incl. rule
                          overrides like "skip your untap step".
* ``TriggeredAbility``  — fire on an event, go on the stack (RULE 603).
* ``ReplacementEffect`` — rewrite an event before it happens (RULE 614).
* ``ActivatedAbility``  — a cost the controller may pay for an effect
                          (RULE 602).

``WinConditionEffect`` is the special "you can't lose"-style override
(docs/07 PART 9). Concrete one-shot effects (deal damage, draw, …) plus
an `EffectRegistry` implement the hybrid class+registry design docs/07
PART 4 recommends: predefined classes for type-safety, a registry so new
effects need no engine change.

Effects act on the game through a `GameContext` facade rather than
touching `GameState` directly, so the primitive operations (draw, deal
damage, destroy) stay defined in one place (the rules engine) and pick up
their own replacement/trigger consequences.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from ..models import card_query
from ..models.events import EventType, GameEvent
from ..models.game_object import Zone
from ..models.mana_cost import ManaCost
from .targeting import TargetSpec, all_requirements_satisfiable, requirements_with_targets

if TYPE_CHECKING:  # avoid an import cycle with rules_engine at runtime
    from ..models.game_object import GameObject
    from ..models.game_state import GameState, StackItem
    from ..models.player import Player
    from .costs import ActivationCost
    from .rules_engine import RulesEngine


class GameContext:
    """Facade an effect uses to reach the game and the engine's primitives.

    Effects call these instead of mutating `GameState` directly so that
    e.g. a draw caused by an effect runs through the same replacement /
    trigger machinery as a draw-step draw.
    """

    def __init__(self, state: "GameState", engine: "RulesEngine") -> None:
        self.state = state
        self.engine = engine
        #: RULE 603.1: the `GameEvent` that fired the triggered ability
        #: currently resolving (`StackItem.trigger_event`), or ``None``
        #: outside that window. Set by `RulesEngine.resolve_top_of_stack`
        #: around the resolution and cleared afterward, so an effect whose
        #: behaviour genuinely depends on *this* firing — the mana a
        #: permanent just produced (Kinnan, Wild Growth, Mana Web), which
        #: player cast the spell (Possibility Storm), what type it was
        #: (Cloudstone Curio) — can read it without every effect's `apply`
        #: signature growing an event parameter. The `TriggeredAbility`
        #: docstring's "bake per-firing data into freshly-built effects"
        #: pattern stays the answer whenever the *shape* of the ability
        #: varies per firing; this covers the far commoner case where only a
        #: value does.
        self.trigger_event: Optional[GameEvent] = None
        #: RULE 602.2b: the player who actually activated/cast the ability
        #: or spell currently resolving (`StackItem.controller_id`), or
        #: ``None`` outside a stack-item resolution (a direct `effect.
        #: apply()` call — tests, a fixture — where no such distinction
        #: exists). Set/restored by `RulesEngine.resolve_top_of_stack`
        #: exactly like `trigger_event` above. Ordinarily identical to the
        #: source's own printed controller (`_controller_of`), so almost
        #: every effect can ignore this entirely; it only actually diverges
        #: for a standing "any player may activate this ability" exception
        #: (Mercenaries, MEC-30 — `ActivationCost.any_player_may_activate`),
        #: where "you" in the printed text means whoever activated it, not
        #: the permanent's own controller — read by `PreventDamageEffect`'s
        #: opt-in ``recipient_is_activator``.
        self.resolving_controller_id: Optional[str] = None
        #: The targets the last *targeting* effect of this same resolution
        #: used (RULE 608.2 applies an effect list in printed order), so a
        #: clause whose subject is a pronoun pointing back at an earlier one
        #: — "target creature you control gets +1/+2 until end of turn. **It**
        #: fights target creature you don't control." (Epic Confrontation),
        #: "Choose target creature you control and target creature you don't
        #: control. … Then **those creatures** fight each other." — can
        #: resolve that referent without the two clauses being fused into one
        #: bespoke effect class per verb pair. Maintained by
        #: `_apply_effects_partitioned`, which is the single choke point every
        #: resolution (spell, wrapper ability, resumed remainder) goes
        #: through. A *non*-targeting clause in between doesn't clear it: the
        #: referent is the last thing actually chosen, not the last thing that
        #: happened.
        self.previous_targets: list[Any] = []
        #: MEC-28: the `continuous.group_selector_objects` name the last
        #: mass-*selector* effect of this same resolution acted on (RULE
        #: 601.2c, untargeted — "untap all attacking creatures. **They**
        #: gain first strike until end of turn.", Karlach, Fury of
        #: Avernus-shaped). `previous_targets`' sibling for the other kind of
        #: referent: a selector clause never populates that list (nothing
        #: was *targeted*), so a following "they" needs its own tracking.
        #: Maintained by `_apply_effects_partitioned` off a narrow
        #: whitelist of effect types (`_PREVIOUS_SELECTOR_EFFECT_TYPES`),
        #: same save/reset/restore idiom as `previous_targets`.
        self.previous_selector: Optional[str] = None
        #: The permanents an earlier clause of this same resolution **just
        #: created**, for a follow-up clause whose subject is "the tokens" /
        #: "that token" — "…each player creates a tapped 2/2 Bird. **The
        #: tokens** are goaded for the rest of the game." (Rendmaw).
        #:
        #: `previous_targets`' sibling and the reason it isn't enough: those
        #: objects were never *targeted*, and never existed at all when the
        #: ability was put on the stack, so no `TargetSpec` can name them.
        #: `LivingWeaponEffect`'s docstring records the same gap from the
        #: other side ("there's no vocabulary for whatever the previous
        #: effect just made") — an atomic effect class per verb pair was the
        #: only alternative. Maintained by `_apply_effects_partitioned`
        #: alongside `previous_targets`, and appended to (not replaced) by a
        #: creating effect, since "each player creates …" makes several.
        self.created_objects: list[Any] = []
        #: "Each opponent loses X life. You gain life equal to the life lost
        #: this way." (Gray Merchant of Asphodel-shaped RULE 119 "drain" —
        #: 16+ cache cards share the exact trailing sentence) — the running
        #: total of *actual* life lost (post-replacement; see `lose_life`
        #: below) across this same resolution, read by a following
        #: `GainLifeEffect(count_selector="life_lost_this_way")`.
        #: `_apply_effects_partitioned`'s own save/reset/restore idiom, same
        #: as `previous_targets`/`created_objects` above.
        self.life_lost_this_way: int = 0
        #: "Destroy each nonland permanent with mana value 2 or less. Add
        #: {B} or {G} for each permanent destroyed this way." (Culling
        #: Ritual, MEC-40) — `life_lost_this_way`'s sibling for a *count* of
        #: permanents rather than a life total, incremented by `destroy`
        #: below for every object that actually left the battlefield (a
        #: regeneration shield/indestructible no-op doesn't count), read by
        #: `AddManaEffect`'s ``any_amount_from_context`` param.
        #: `_apply_effects_partitioned`'s own save/reset/restore idiom.
        self.permanents_destroyed_this_way: int = 0

    @property
    def players(self) -> list["Player"]:
        return self.state.players

    @property
    def active_player(self) -> "Player":
        return self.state.active_player

    def fire_event(self, event: GameEvent) -> GameEvent:
        return self.state.fire_event(event)

    def deal_damage(
        self, target: Any, amount: int, source: Optional["GameObject"] = None,
        single_target_hint: bool = False,
    ) -> None:
        self.engine.deal_damage(target, amount, source, single_target_hint=single_target_hint)

    def draw(self, player: "Player", count: int = 1) -> None:
        self.engine.draw(player, count)

    def discard(self, player: "Player", count: int = 1) -> None:
        self.engine.discard(player, count)

    def discard_choice(self, player: "Player", count: int = 1) -> None:
        self.engine.discard_choice(player, count)

    def put_hand_cards_on_top(self, player: "Player", count: int = 1) -> None:
        self.engine.put_hand_cards_on_top(player, count)

    def put_hand_card_on_bottom_then_draw(self, player: "Player") -> None:
        self.engine.put_hand_card_on_bottom_then_draw(player)

    def destroy(self, target: "GameObject", can_be_regenerated: bool = True) -> None:
        was_on_battlefield = target in self.state.battlefield
        self.engine.destroy(target, can_be_regenerated=can_be_regenerated)
        # `self.permanents_destroyed_this_way`'s own bookkeeping — only an
        # *actual* destruction (not a regeneration shield/indestructible
        # no-op) counts, mirroring `lose_life`'s before/after check above.
        if was_on_battlefield and target not in self.state.battlefield:
            self.permanents_destroyed_this_way += 1

    def regenerate(self, target: "GameObject") -> None:
        self.engine.regenerate(target)

    def exile(self, target: "GameObject") -> None:
        self.engine.exile(target)

    def exile_until_duplicate_name(self, player: "Player") -> None:
        self.engine.exile_until_duplicate_name(player)

    def transmute_artifact(self, player: "Player") -> None:
        self.engine.transmute_artifact(player)

    def mill(self, player: "Player", count: int = 1) -> None:
        self.engine.mill(player, count)

    def lose_game(self, player: "Player", reason: str = "effect") -> None:
        self.engine._player_loses(player, reason)

    def monstrosity(self, target: "GameObject", amount: int = 1) -> bool:
        # RULE 701.37a.
        return self.engine.monstrosity(target, amount)

    def adapt(self, target: "GameObject", amount: int = 1) -> bool:
        # RULE 701.46a.
        return self.engine.adapt(target, amount)

    def goad(self, target: "GameObject", goader_id: str, permanent: bool = False) -> None:
        # RULE 701.15a; ``permanent`` is the "for the rest of the game" form.
        self.engine.goad(target, goader_id, permanent=permanent)

    def become_monarch(self, player: "Player") -> None:
        self.engine.become_monarch(player)

    def take_initiative(self, player: "Player") -> None:
        self.engine.take_initiative(player)

    def get_city_blessing(self, player: "Player") -> None:
        # RULE 702.131a-c.
        self.engine.get_city_blessing(player)

    def create_emblem(self, player: "Player", ability: dict) -> None:
        self.engine.create_emblem(player, ability)

    def venture_into_the_dungeon(self, player: "Player", dungeon: Optional[str] = None) -> None:
        # RULE 701.49; ``dungeon`` is 701.49d's "venture into [quality]".
        self.engine.venture_into_the_dungeon(player, dungeon)

    def complete_dungeon(self, player: "Player") -> None:
        # RULE 309.6/309.7.
        self.engine.complete_dungeon(player)

    def manifest(self, player: "Player", count: int = 1, kind: str = "manifest") -> None:
        # RULE 701.40a manifest / RULE 701.58a cloak.
        self.engine.manifest(player, count, kind=kind)

    def request_manifest_dread(self, player: "Player") -> None:
        # RULE 701.40a's look-at-two variant.
        self.engine.request_manifest_dread(player)

    def take_extra_turn(self, player: "Player") -> None:
        # RULE 500.7: queue an extra turn for ``player``, taken after the
        # current one (`GameEngine.begin_turn` consumes `state.extra_turns`).
        self.state.extra_turns.append(player.id)

    def set_tapped(self, target: "GameObject", tapped: bool = True) -> None:
        self.engine.set_tapped(target, tapped)

    def attach_to_target(self, source: "GameObject", target: "GameObject") -> None:
        self.engine.attach_to_target(source, target)

    def add_counters(
        self, target: "GameObject", amount: int, kind: str = "+1/+1", source: Optional["GameObject"] = None
    ) -> None:
        self.engine.add_counters(target, amount, kind, source=source)

    def add_player_counters(
        self, player: "Player", amount: int, kind: str = "poison", source: Optional["GameObject"] = None
    ) -> None:
        self.engine.add_player_counters(player, amount, kind, source=source)

    def scry(self, player: "Player", count: int = 1, source: Optional["GameObject"] = None) -> None:
        self.engine.scry(player, count, source=source)

    def surveil(self, player: "Player", count: int = 1, source: Optional["GameObject"] = None) -> None:
        self.engine.surveil(player, count, source=source)

    def look_top_select(
        self,
        player: "Player",
        count: int,
        select_count: int,
        rest_destination: str,
        rest_order: Optional[str] = None,
    ) -> None:
        self.engine.look_top_select(player, count, select_count, rest_destination, rest_order)

    def recompute(self) -> None:
        """Re-derive continuous characteristics now (RULE 613) — used by an
        effect that changes derived P/T mid-resolution (a pump)."""
        from . import continuous  # function-scoped: avoid an import cycle

        continuous.recompute(self.state)

    def create_token(self, controller_id: str, token_card: Any, count: int = 1) -> list[Any]:
        # Returns what it made (RULE 111.5) so a caller can keep the referent
        # for a following "the tokens …" clause — see `created_objects`.
        return self.engine.create_token(controller_id, token_card, count)

    def copy_permanent(
        self,
        controller_id: str,
        source: "GameObject",
        count: int = 1,
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        not_legendary: bool = False,
        set_power: Optional[int] = None,
        set_toughness: Optional[int] = None,
    ) -> list[Any]:
        # Returns what it made, same as `create_token` — see `created_objects`.
        return self.engine.copy_permanent(
            controller_id, source, count,
            add_types=add_types, add_subtypes=add_subtypes, not_legendary=not_legendary,
            set_power=set_power, set_toughness=set_toughness,
        )

    def copy_spell(
        self,
        target: Any,
        controller_id: str,
        count: int = 1,
        new_targets: Optional[list] = None,
    ) -> None:
        self.engine.copy_spell(target, controller_id, count, new_targets)

    def copy_self_spell(self, obj: "GameObject", controller_id: str, targets: Optional[list] = None) -> None:
        self.engine.copy_self_spell(obj, controller_id, targets=targets)

    def make_prepared(self, obj: "GameObject") -> None:
        self.engine.make_prepared(obj)

    def put_into_graveyard(self, obj: "GameObject") -> None:
        """RULE 701.16c: sacrifice isn't destruction — a permanent goes
        straight to the graveyard, never through a regeneration shield."""
        self.engine.put_into_graveyard(obj)

    def become_copy(
        self,
        obj: "GameObject",
        target: "GameObject",
        add_types: Optional[list] = None,
        add_subtypes: Optional[list] = None,
    ) -> None:
        self.engine.become_copy(obj, target, add_types, add_subtypes)

    def become_copy_until_end_of_turn(
        self,
        obj: "GameObject",
        target: "GameObject",
        add_types: Optional[list] = None,
        add_subtypes: Optional[list] = None,
    ) -> None:
        self.engine.become_copy_until_end_of_turn(obj, target, add_types, add_subtypes)

    def set_copy_target(self, obj: "GameObject", target: "GameObject") -> None:
        self.engine.set_copy_target(obj, target)

    def gain_life(self, player: "Player", amount: int) -> None:
        self.engine.gain_life(player, amount)

    def prevent_damage_to_player(
        self, player: "Player", amount: Union[int, str] = "all",
        watched_source_id: Optional[int] = None,
    ) -> None:
        self.engine.prevent_damage_to_player(player, amount, watched_source_id=watched_source_id)

    def prevent_life_gain_this_turn(self, players: list["Player"]) -> None:
        self.engine.prevent_life_gain_this_turn(players)

    def prevent_damage_to_target(self, target: Any, amount: Union[int, str] = "all") -> None:
        self.engine.prevent_damage_to_target(target, amount)

    def prevent_all_combat_damage_this_turn(
        self, controller: "Player", exclude_subtype: Optional[str] = None,
    ) -> None:
        self.engine.prevent_all_combat_damage_this_turn(controller, exclude_subtype=exclude_subtype)

    def disable_damage_prevention_this_turn(self) -> None:
        self.engine.disable_damage_prevention_this_turn()

    def grant_damage_multiplier_this_turn(
        self, controller: "Player", source: "GameObject", multiplier: int = 2,
        to_opponent_only: bool = False,
    ) -> None:
        self.engine.grant_damage_multiplier_this_turn(
            controller, source, multiplier=multiplier, to_opponent_only=to_opponent_only,
        )

    def lose_life(self, player: "Player", amount: int, cause: str = "effect") -> None:
        before = getattr(player, "life", None)
        self.engine.lose_life(player, amount, cause=cause)
        # `self.life_lost_this_way`'s own bookkeeping — the *actual* drop
        # (so a life-locked/replaced loss doesn't overcount "the life lost
        # this way"), not the nominal ``amount`` requested.
        if before is not None:
            actual = before - getattr(player, "life", before)
            if actual > 0:
                self.life_lost_this_way += actual

    def sacrifice(self, player: "Player", what: str = "permanent", count: int = 1) -> None:
        self.engine.sacrifice(player, what, count)

    def request_search(
        self,
        player: "Player",
        criteria: Any = "",
        destination: str = "hand",
        count: int = 1,
        optional: bool = True,
        zones: Optional[list[str]] = None,
        destinations: Optional[list[str]] = None,
        exile_rest: bool = False,
        extra_counters: Optional[dict[str, Any]] = None,
        destination_if: Optional[list[dict[str, Any]]] = None,
        attach_to_creature_you_control: bool = False,
        remember_source_id: Optional[int] = None,
        total_mana_value_budget: Optional[int] = None,
        chooser: Optional["Player"] = None,
        share_land_type: bool = False,
    ) -> None:
        self.engine.request_search(
            player, criteria, destination, count, optional,
            zones=zones, destinations=destinations, exile_rest=exile_rest,
            extra_counters=extra_counters, destination_if=destination_if,
            attach_to_creature_you_control=attach_to_creature_you_control,
            remember_source_id=remember_source_id,
            total_mana_value_budget=total_mana_value_budget,
            chooser=chooser,
            share_land_type=share_land_type,
        )

    def request_intuition(
        self, searcher: "Player", chooser_id: str, count: int, source: Optional["GameObject"] = None,
        search_optional: bool = False, distinct_names: bool = False,
        chosen_count: int = 1, chosen_destination: str = "hand",
        rest_destination: str = "graveyard",
    ) -> None:
        self.engine.request_intuition(
            searcher, chooser_id, count, source,
            search_optional=search_optional, distinct_names=distinct_names,
            chosen_count=chosen_count, chosen_destination=chosen_destination,
            rest_destination=rest_destination,
        )

    def choose_objects(
        self,
        player: "Player",
        candidates: list["GameObject"],
        action: str,
        count: int = 1,
        optional: bool = False,
        prompt: str = "",
        source: Optional["GameObject"] = None,
        then_specs: Optional[list[dict[str, Any]]] = None,
        then_specs_if_commander: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Open the general "which of these objects?" choice — see
        `RulesEngine.request_choose_objects`."""
        self.engine.request_choose_objects(
            player, candidates, action, count=count, optional=optional,
            prompt=prompt, source=source, then_specs=then_specs,
            then_specs_if_commander=then_specs_if_commander,
        )

    def impulsive_look(
        self,
        player: "Player",
        count: int,
        criteria: Any = "",
        hit_destination: str = "hand",
        miss_destination: str = "graveyard",
        optional: bool = True,
    ) -> None:
        self.engine.request_impulsive_look(
            player, count, criteria, hit_destination, miss_destination, optional
        )

    def exile_with_play_permission(
        self,
        player: "Player",
        count: int,
        source_name: Optional[str] = None,
        permission_player: Optional["Player"] = None,
        same_turn_only: bool = False,
    ) -> None:
        self.engine.exile_with_play_permission(
            player, count, source_name=source_name,
            permission_player=permission_player, same_turn_only=same_turn_only,
        )

    def shuffle_library(self, player: "Player") -> None:
        self.engine.shuffle_library(player)

    def shuffle_hand_and_graveyard_into_library(self, player: "Player") -> None:
        self.engine.shuffle_hand_and_graveyard_into_library(player)

    def cascade(self, player: "Player", max_mana_value: int) -> None:
        self.engine.request_cascade(player, max_mana_value)

    def discover(self, player: "Player", max_mana_value: int) -> None:
        self.engine.request_discover(player, max_mana_value)

    def counter(
        self,
        target: Any,
        unless_pays: Optional[str] = None,
        source: Optional["GameObject"] = None,
        suspend_instead: Optional[int] = None,
    ) -> None:
        self.engine.counter_unless_pays(
            target, unless_pays, source, suspend_time_counters=suspend_instead
        )

    def counter_ability(self, target: Any) -> None:
        self.engine.counter_ability(target)

    def change_target(
        self,
        target: Any,
        optional: bool = False,
        source: Optional["GameObject"] = None,
        redirect_to_source: bool = False,
    ) -> None:
        self.engine.change_target(
            target, optional=optional, source=source, redirect_to_source=redirect_to_source
        )

    def return_to_hand(self, target: "GameObject") -> None:
        self.engine.return_to_hand(target)

    def bounce_spell_or_permanent(self, target: "GameObject") -> None:
        self.engine.bounce_spell_or_permanent(target)

    def gain_control_of_spell(self, target: "GameObject", new_controller_id: str) -> None:
        self.engine.gain_control_of_spell(target, new_controller_id)

    def end_the_turn(self) -> None:
        self.engine.end_the_turn()

    def return_to_library(self, target: "GameObject", position: str = "top") -> None:
        self.engine.return_to_library(target, position)

    def shuffle_into_library(self, target: "GameObject") -> None:
        self.engine.shuffle_into_library(target)

    def return_from_graveyard(
        self,
        target: "GameObject",
        destination: str = "battlefield",
        controller_id: Optional[str] = None,
        transformed: bool = False,
    ) -> None:
        self.engine.return_from_graveyard(
            target, destination, controller_id=controller_id, transformed=transformed
        )

    def blink(self, target: "GameObject", controller: Optional["Player"] = None) -> None:
        self.engine.blink(target, controller=controller)

    def exile_return_transformed(self, target: "GameObject") -> None:
        self.engine.exile_return_transformed(target)

    def return_dies_as_new_permanent(
        self,
        target: "GameObject",
        new_type_line: str,
        new_oracle_text: str,
        attach_to: Optional["GameObject"] = None,
    ) -> None:
        self.engine.return_dies_as_new_permanent(
            target, new_type_line, new_oracle_text, attach_to=attach_to
        )

    def add_mana(self, player: "Player", color: str, amount: int = 1) -> None:
        self.engine.add_mana(player, color, amount)

    def add_mana_any_color(
        self, player: "Player", colors: Optional[list[str]] = None, amount: int = 1
    ) -> None:
        self.engine.add_mana_any_color(player, colors, amount=amount)


def _event_player(context: GameContext, key: str = "controller_id") -> Optional["Player"]:
    """The `Player` named by the currently-resolving trigger's own event
    (`GameContext.trigger_event`), or ``None`` outside a trigger resolution
    / when the event carries no such id.

    ``key`` names *which* player the event means — ``"controller_id"`` (who
    tapped the permanent, `TAPPED_FOR_MANA`) or ``"player_id"`` (who cast
    the spell / whose library it was, `SPELL_CAST`/`MILL_CARD`).
    """
    event = context.trigger_event
    if event is None:
        return None
    player_id = event.get(key)
    if player_id is None:
        return None
    try:
        return context.state.player_by_id(player_id)
    except (KeyError, ValueError):
        return None


def _controller_of(source: Optional["GameObject"], context: GameContext) -> Optional["Player"]:
    """The `Player` controlling ``source`` (RULE 109.4), else the active player.

    An untargeted effect ("scry 2", "you draw a card") affects its own
    controller; if the effect has no source yet (a fixture/direct call), fall
    back to the active player.
    """
    controller_id = getattr(source, "controller_id", None)
    if controller_id is not None:
        try:
            return context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            pass
    return context.active_player


def _defending_player_of(source: Optional["GameObject"], context: GameContext) -> Optional["Player"]:
    """The player ``source`` (an attacking creature) is attacking (RULE 506.4),
    for a combat-math keyword's "defending player" clause (annihilator 702.86,
    afflict 702.130). Reads the ``combat_defender`` spec `declare_attackers`
    stamped onto the attacker — a player id directly, or a planeswalker's
    controller when the attack target was a planeswalker (RULE 506.4d).

    ENG-14: ``source`` itself might not be the one attacking. Reconfigure
    (RULE 702.151) lets an Equipment's own trigger fire off a
    ``self_or_attached_permanent`` subject (Simian Sling's "whenever this
    creature **or equipped creature** becomes blocked, it deals 1 damage to
    defending player") — correct when the Equipment is itself a creature
    currently attacking, but when it's attached to (and reconfigured off) a
    *different* attacking creature instead, only that host carries the
    `combat_defender` stamp. Falls back to the object ``source`` is
    currently attached to before giving up — the same self-or-host pair the
    trigger condition already scoped by — so every existing caller (always
    the attacking creature itself, never an attached permanent) sees no
    change: ``attached_to`` is unset for them.

    ``None`` if neither ``source`` nor its host (if any) is a live,
    currently-attacking object (e.g. a hand-built test event with no real
    attack declared).
    """
    spec = getattr(source, "combat_defender", None)
    if not spec:
        host_id = getattr(source, "attached_to", None)
        if host_id is not None:
            host = context.state.find_object(host_id)
            spec = getattr(host, "combat_defender", None) if host is not None else None
    if not spec:
        return None
    if spec.get("kind") == "player":
        try:
            return context.state.player_by_id(spec["id"])
        except (KeyError, ValueError):
            return None
    if spec.get("kind") == "planeswalker":
        pw = context.state.find_object(spec["instance_id"])
        if pw is None:
            return None
        try:
            return context.state.player_by_id(pw.controller_id)
        except (KeyError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class GameEffect(ABC):
    """Base class for all effects (docs/07 PART 2).

    ``target_spec`` is ``None`` for a global / fixed-set effect (draw, gain
    life, board wipe) and a `TargetSpec` for a *targeting* effect (RULE 115),
    so the engine can tell before casting whether a legal target is required
    and available (RULE 601.2c). Subclasses that target set it in ``__init__``.
    """

    target_spec: Optional[TargetSpec] = None
    #: A *second* (and further) requirement for effects that genuinely need
    #: two independently-chosen targets of different kinds in one clause —
    #: "attach target Equipment you control to target creature you control"
    #: (Brass Squire, Halvar), "put a +1/+1 counter on target creature you
    #: control. It deals damage equal to its power to target creature you
    #: don't control." (Archdruid's Charm). ``target_spec`` stays the first;
    #: this holds the rest, in printed order. Every gathering path reads
    #: `target_specs` below rather than ``target_spec`` directly, and
    #: `_apply_effects_partitioned` hands such an effect *all* of its groups
    #: flattened, so `apply` sees ``targets[0]``, ``targets[1]``, … in that
    #: same order. Empty for the overwhelming majority of effects.
    extra_target_specs: tuple[TargetSpec, ...] = ()

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        self.source = source

    @property
    def target_specs(self) -> list[TargetSpec]:
        """Every RULE 115.1 requirement this one effect announces, in printed
        order — ``[]`` for a non-targeting effect, one entry for the ordinary
        case, and 2+ only for the multi-target clauses `extra_target_specs`
        documents."""
        if self.target_spec is None:
            return []
        return [self.target_spec, *self.extra_target_specs]

    @abstractmethod
    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        """Apply this effect to the game."""

    def can_apply(self, context: GameContext) -> bool:  # noqa: D401 - simple default
        """Whether the effect can apply right now (default: always)."""
        return True

    def target_polarity(self) -> Optional[str]:
        """Best-effort "is this effect's target on the receiving end of
        something good or bad" — ``"harmful"``, ``"beneficial"``, or
        ``None`` for no opinion (the default, and every effect not
        overriding this below).

        Not rules data: nothing in the engine reads this, and it is never
        consulted while actually resolving anything. It exists purely so
        `targeting.spell_target_specs`/`ability_target_specs` can stamp a
        `TargetSpec.polarity` hint onto the offer a `cast_spell`/
        `activate_ability` action carries, which `services/bots.py`'s
        `GreedyBot` reads to point a removal spell at an opponent's
        permanent and a pump spell at its own, instead of always preferring
        an opponent's stuff regardless of what the spell actually does to
        it. Deliberately conservative: an effect whose sign genuinely
        depends on its own parameters (a "-N/-N" `PumpEffect`, a "-1/-1"
        `AddCountersEffect`) overrides this to inspect them; anything not
        listed below (a bounce, a granted keyword, a counter-removal of
        unknown sign, …) stays ``None`` rather than guessing.
        """
        return None


def _apply_effects_partitioned(
    effects: list["GameEffect"],
    context: GameContext,
    targets: Optional[list[Any]],
    target_groups: Optional[list[list[Any]]],
    source: Optional["GameObject"] = None,
    group_index: int = 0,
    previous_targets: Optional[list[Any]] = None,
    created_objects: Optional[list[Any]] = None,
    life_lost_this_way: int = 0,
    permanents_destroyed_this_way: int = 0,
    previous_selector: Optional[str] = None,
    stack_item: Optional[Any] = None,
) -> bool:
    """Apply each of ``effects`` against its own share of ``targets``.

    Returns whether the list paused partway through (an effect opened a
    `pending_choice`, deferring the remainder) rather than running to
    completion — see ``stack_item`` below and `RulesEngine._apply_stack_
    item`'s own use of the return value.

    Mirrors `RulesEngine.resolve_top_of_stack`'s per-effect
    `StackItem.target_groups` dispatch, for a *nested* effects list —
    `TriggeredAbility`/`ActivatedAbility` wrap their own sub-effects, so the
    outer stack-resolution loop only ever sees one effect (the wrapper) and
    can't partition *their* targets itself; this is the same logic run one
    level down. ``target_groups=None`` (the overwhelming common case: at
    most one targeting effect) keeps every sub-effect reading ``targets``
    directly, unchanged from before `target_groups` existed.

    RULE 608.2: an effect that opens an interactive `pending_choice`
    **suspends** the rest of the list rather than letting the next effect
    run — the game state holds one pending choice at a time, so a second
    interactive effect resolving now would silently overwrite the first
    player's prompt. The remainder is pushed onto
    `GameState.deferred_effects` and picked back up by
    `RulesEngine.resume_deferred_effects` once the choice is answered. Only
    ever reached by a resolution with 2+ interactive effects — an entwined
    modal spell (RULE 702.42a), or an ability whose clauses each prompt.
    ``group_index`` is where in ``target_groups`` to start, so a resumed
    remainder keeps reading its own slices.

    ``previous_targets`` seeds `GameContext.previous_targets` — the referent
    a later clause's pronoun points at ("… **It** fights target creature you
    don't control."). It is threaded here rather than kept on the context
    alone so a resumed remainder (below) picks the referent back up, and
    restored afterwards so a nested resolution can't leak its own.
    `GameContext.created_objects` ("**The tokens** are goaded…") is scoped
    the same way; ``created_objects`` is only ever passed by a *resumed*
    remainder picking its own referent back up, so a fresh resolution always
    starts empty and can't point at something an unrelated one made.

    ``previous_selector`` seeds `GameContext.previous_selector` (MEC-28) the
    same way — the mass-selector sibling of ``previous_targets``, tracked
    off a narrow whitelist of effect types (`_PREVIOUS_SELECTOR_EFFECT_
    TYPES`) since only `TapEffect`'s own selector is a real card's
    antecedent today (widen the whitelist, not this function, as another
    card needs a different one — same convention `effect_binder.
    _GROUP_SUBJECT_RETARGET_FIELDS` uses).

    ``stack_item`` (MEC-37, Doomsday) is threaded through into the parked
    `deferred_effects` entry unchanged, purely so `RulesEngine.
    resume_deferred_effects` can find its way back to the *spell* this
    effects list belongs to once the remainder finally finishes with
    nothing left to pause on — RULE 608.2m only sends a resolved spell to
    its next zone (ordinarily the graveyard) *after* every one of its
    effects has actually happened, so `RulesEngine._apply_stack_item`
    skips that routing entirely while this function's return value says
    "paused," rather than running it prematurely while the spell's own
    interactive effect (a search, say) is still waiting on an answer — a
    real bug a search naming the caster's own graveyard could otherwise
    see: the still-resolving spell showing up as a candidate in its own
    search a moment before RULE 608.2m actually puts it there.
    """
    state = getattr(context, "state", None)
    already_pending = getattr(state, "pending_choice", None) if state is not None else None
    outer_previous = getattr(context, "previous_targets", [])
    outer_created = getattr(context, "created_objects", [])
    outer_life_lost = getattr(context, "life_lost_this_way", 0)
    outer_permanents_destroyed = getattr(context, "permanents_destroyed_this_way", 0)
    outer_previous_selector = getattr(context, "previous_selector", None)
    context.previous_targets = list(previous_targets or [])
    context.created_objects = list(created_objects or [])
    context.life_lost_this_way = life_lost_this_way
    context.permanents_destroyed_this_way = permanents_destroyed_this_way
    context.previous_selector = previous_selector
    try:
        for position, effect in enumerate(effects):
            if source is not None and effect.source is None:
                effect.source = source
            specs = effect.target_specs
            if target_groups is not None and specs:
                # An effect with 2+ requirements consumes that many groups and
                # sees them flattened, so its `apply` reads targets[0],
                # targets[1], … in printed order (see `extra_target_specs`).
                group: list[Any] = []
                for _ in specs:
                    if group_index < len(target_groups):
                        group.extend(target_groups[group_index])
                    group_index += 1
                effect.apply(context, group)
                used = group
            else:
                effect.apply(context, targets)
                used = list(targets or [])
            if specs and used:
                context.previous_targets = list(used)
            if isinstance(effect, _PREVIOUS_SELECTOR_EFFECT_TYPES) and effect.selector:
                context.previous_selector = effect.selector
            if state is None or position + 1 >= len(effects):
                continue
            opened = getattr(state, "pending_choice", None)
            if opened is not None and opened is not already_pending:
                state.deferred_effects.append(
                    {
                        "effects": list(effects[position + 1:]),
                        "targets": targets,
                        "target_groups": target_groups,
                        "group_index": group_index,
                        "source": source,
                        "previous_targets": list(context.previous_targets),
                        "created_objects": list(context.created_objects),
                        "life_lost_this_way": context.life_lost_this_way,
                        "permanents_destroyed_this_way": context.permanents_destroyed_this_way,
                        "previous_selector": context.previous_selector,
                        "stack_item": stack_item,
                    }
                )
                return True
        return False
    finally:
        context.previous_targets = outer_previous
        context.created_objects = outer_created
        context.life_lost_this_way = outer_life_lost
        context.permanents_destroyed_this_way = outer_permanents_destroyed
        context.previous_selector = outer_previous_selector


# ---------------------------------------------------------------------------
# TYPE 1: Static effects (RULE 611) + rule overrides (skip phase, etc.)
# ---------------------------------------------------------------------------


class StaticEffect(GameEffect):
    """A continuous effect / rule modification (docs/07 PART 1, PART 8).

    ``kind`` names what it overrides (e.g. ``"skip_phase"``). For a
    skip-phase effect, ``params["phase"]`` is the step/phase name to skip.
    ``duration`` controls when the engine discards it (``"permanent"``,
    ``"end_of_turn"``, ``"next_turn"``, ``"once"``).
    """

    def __init__(
        self,
        kind: str,
        params: Optional[dict[str, Any]] = None,
        duration: str = "permanent",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.params = params or {}
        self.duration = duration
        self.active = True

    def skips_step(self, step_name: str) -> bool:
        return (
            self.active
            and self.kind == "skip_phase"
            and self.params.get("phase") == step_name
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        # Static effects are consulted where relevant (e.g. skip checks in
        # the phase loop) rather than "applied" imperatively; nothing to do
        # on a generic apply.
        return None


class StaticAbility(GameEffect):
    """A continuous static ability applied through the layer system (RULE 613).

    Unlike `StaticEffect` (a player-scoped rule override like "skip your draw
    step"), this is a *battlefield* continuous effect that reshapes other
    permanents' characteristics — an anthem's +1/+1, a granted keyword, a
    type change, or a mana-cost reduction. It carries no imperative behaviour;
    `game/continuous.py` reads these off the battlefield and folds them into
    each object's derived characteristics in layer order.

    ``layer`` selects where it applies (RULE 613.7 sublayer names, plus the
    non-layer ``"cost"`` bucket for 601.2f cost adjustments):

    * ``"type"``   → layer 4 (add card types);
    * ``"ability"``→ layer 6 (add keyword abilities);
    * ``"pt_set"`` → layer 7b (set power/toughness);
    * ``"pt_mod"`` → layer 7c (modify power/toughness — anthems, counters);
    * ``"cost"``   → not a layer; a cost adjustment applied when the affected
      spell's total cost is calculated (RULE 601.2f).

    ``affects`` names the set it touches (see `continuous.affected_objects`);
    ``params`` is the modification (e.g. ``{"power": 1, "toughness": 1}``,
    ``{"keywords": ["flying"]}``, ``{"add_types": ["creature"]}``,
    ``{"generic": 1}``).
    """

    LAYER_NUMBERS: dict[str, int] = {
        "copy": 1,         # layer 1 — copy effects (RULE 707)
        "control": 2,      # layer 2 — control-changing effects (RULE 613.2)
        "text": 3,         # layer 3 — text-changing effects (RULE 612)
        "type": 4,         # layer 4 — type-changing effects
        "color": 5,        # layer 5 — colour-changing effects
        "ability": 6,      # layer 6 — ability-adding effects
        "borrowed_activated_ability": 6,  # layer 6 — dynamic ability-adding (MEC-21)
        "pt_cda": 7,       # layer 7a — characteristic-defining P/T
        "pt_set": 7,       # layer 7b — set power/toughness
        "pt_mod": 7,       # layer 7d — modify power/toughness (anthems)
        "pt_switch": 7,    # layer 7e — switch power and toughness
        "cost": 99,        # not a layer — cost adjustment (RULE 601.2f)
    }

    def __init__(
        self,
        layer: str,
        affects: str = "self",
        params: Optional[dict[str, Any]] = None,
        source: Optional["GameObject"] = None,
        description: str = "",
        duration: Optional[str] = None,
        duration_data: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.layer = layer
        self.affects = affects
        self.params = params or {}
        self.description = description
        #: RULE 611: how long this continuous effect lasts, for one created by
        #: a *resolving* spell/ability and parked in `GameState.
        #: floating_statics` ("until your next turn, …"). ``None`` — the
        #: overwhelming majority — is a permanent's own printed static, which
        #: lasts exactly as long as the permanent is on the battlefield and
        #: needs no duration at all. See `game/durations.py`.
        self.duration = duration
        #: Per-duration payload: ``{"player_id": …}`` for ``your_next_turn``
        #: (whose turn ends it), ``{"condition": …}`` for ``for_as_long_as``.
        self.duration_data = duration_data or {}
        #: The objects a floating static applies to when it was created for
        #: specific permanents ("target creature gains flying until …") — an
        #: instance-id list, since the affected object is chosen at
        #: resolution and can't be a selector. Empty = use ``affects``.
        self.object_ids: list[int] = []

    @property
    def layer_number(self) -> int:
        return self.LAYER_NUMBERS.get(self.layer, 99)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # continuous — consulted by continuous.recompute, not applied


# ---------------------------------------------------------------------------
# TYPE 2: Triggered abilities (RULE 603)
# ---------------------------------------------------------------------------


class TriggeredAbility(GameEffect):
    """Fires on an event and goes on the stack (docs/07 PART 2, RULE 603).

    ``effects`` is one fixed list bound once, at bind-on-load, and reused
    for *every* firing — fine for the overwhelming majority of triggered
    abilities, whose effects don't depend on data specific to a given
    firing. A trigger whose magnitude genuinely depends on *that firing*
    (Rampage's per-block blocker count, RULE 702.23; a ward ability's own
    caster/target pair, RULE 702.21) can't be expressed this way. The
    sanctioned answer, rather than new IR here, is to build a fresh
    `TriggeredAbility` (or, when even the controller/shape varies per
    firing, a raw `StackItem`) right at the call site with the per-firing
    data baked directly into its effects, then place it exactly like any
    other trigger — see `RulesEngine.check_rampage` (rebuilds a
    `TriggeredAbility` and calls `_place_trigger`) and `check_ward` (skips
    `TriggeredAbility` entirely and pushes a `StackItem` straight on the
    stack, since ward's controller is the *target's*, not the source's).
    Follow that pattern for a new card needing "that creature"/"the object
    this ability just created" rather than adding a dynamic-reference
    target-spec kind — no card in this catalogue has needed one yet.

    ``trigger_event`` is the `EventType` to watch. ``condition`` is an
    optional extra predicate ``(event, context) -> bool``. ``effects`` are
    the one-shot effects placed on the stack when it triggers — or, for a
    modal ability (RULE 700.2), ignored in favour of ``modes``: a list of
    ``{"effects": [GameEffect, ...], "description": str}`` entries, one per
    printed mode. ``modes`` is chosen from interactively as the ability is
    placed on the stack (`game/rules_engine.py`'s `_place_triggers`/
    `resolve_trigger_mode_choice`, a `trigger_mode` `pending_choice` — the
    same "chosen before target/optional choice" ordering a modal spell's own
    mode gets at cast time); ``modes_or_both`` mirrors RULE 700.2e for a
    triggered ability with exactly two modes. ``modes_choose`` is RULE
    700.2's "choose *N* —" count (``1`` for the ordinary "choose one" case);
    for ``modes_choose > 1`` the choice is made iteratively, one mode per
    round, mirroring how a library search offers "up to N" one card at a
    time (`resolve_trigger_mode_choice`). ``modes_at_least`` is RULE 700.2's
    "choose *N* or more —" (Farewell-shaped): ``modes_choose`` becomes a
    minimum rather than an exact count, and the iterative choice offers a
    "done" option once that minimum is met instead of forcing every mode to
    be picked.
    """

    def __init__(
        self,
        trigger_event: str,
        effects: list[GameEffect],
        condition: Optional[Callable[[GameEvent, GameContext], bool]] = None,
        optional: bool = False,
        once_per_turn: bool = False,
        controller_id: Optional[str] = None,
        source: Optional["GameObject"] = None,
        description: str = "",
        modes: Optional[list[dict[str, Any]]] = None,
        modes_or_both: bool = False,
        modes_choose: int = 1,
        modes_at_least: bool = False,
        modes_optional: bool = False,
        reflexive: bool = False,
        mana_ability: bool = False,
        functions_from_graveyard: bool = False,
    ) -> None:
        super().__init__(source)
        #: RULE 113.6a (PAR-16): whether this ability fires while its own
        #: source sits in the *graveyard* rather than the battlefield — the
        #: Eidolon/Phoenix family ("Whenever `<event>`, [you may] return
        #: this card from your graveyard to your hand"). Inferred by
        #: `effect_binder.bind_ability` whenever the built effects include a
        #: `ReturnSelfFromGraveyardToHandEffect`/
        #: `ReturnSelfFromGraveyardToBattlefieldEffect` — real printings
        #: carry no explicit "(this ability functions from your graveyard.)"
        #: reminder to key off instead, so the effect and the permission
        #: always travel together, the same inference PAR-10's
        #: `ActivationCost.graveyard_zone` already uses for the activated
        #: half of the same family. Consulted by `RulesEngine.
        #: _collect_triggers`'s graveyard scan, which — unlike the ordinary
        #: `state.permanents()` scan — only fires abilities carrying this flag.
        self.functions_from_graveyard = functions_from_graveyard
        #: RULE 605.1b/605.4: this is a **triggered mana ability** — it
        #: triggers off activating a mana ability and itself only produces
        #: mana. Such an ability never uses the stack: it resolves
        #: immediately, so the mana it adds is spendable within the very
        #: payment that triggered it (Wild Growth's extra {G} is available
        #: for the spell you were tapping the land to cast; Kinnan's copy is
        #: the whole reason he is played). `RulesEngine._collect_triggers`
        #: applies these on the spot instead of queueing them into
        #: `pending_triggers`.
        self.mana_ability = mana_ability
        self.trigger_event = trigger_event
        self.effects = effects
        self.condition = condition
        self.optional = optional
        self.controller_id = controller_id
        self.description = description
        self.modes = modes
        self.modes_or_both = modes_or_both
        self.modes_choose = modes_choose
        self.modes_at_least = modes_at_least
        #: RULE 700.2's "choose *up to* one —" (Hullbreaker Horror) — the
        #: 0-or-1 sibling of the plain "choose one" (always exactly 1,
        #: `modes_choose == 1` alone) and "choose one **or both**"
        #: (`modes_or_both`, 1 or 2) shapes; only meaningful with
        #: ``modes_choose == 1`` and neither of those other two set.
        self.modes_optional = modes_optional
        #: RULE 603.3d "that permanent/spell": the ability's single targeting
        #: effect acts on *the exact object that fired the triggering event*
        #: (Lavinia/Boromir "counter that spell", Price of Glory "destroy
        #: that land") — not a freely chosen target. When set, `RulesEngine.
        #: _place_triggers` resolves the target from the event's
        #: ``instance_id`` at placement time and bakes it in, opening no
        #: `trigger_target` choice; if the object is already gone (e.g. the
        #: spell left the stack), the trigger is dropped (RULE 603.3c). This
        #: is the generic form of the per-firing "that object" reference the
        #: bespoke `check_ward`/`check_rampage` paths hand-build.
        self.reflexive = reflexive
        #: "This ability triggers only once each turn" (RULE 603.2, e.g.
        #: Dionus, Elvish Archdruid's granted ability). Stamped by
        #: `check_trigger` the moment it fires — regardless of whether the
        #: ability actually resolves — since this instance is cached/reused
        #: across recomputes for as long as a grant holds (see
        #: `GameState._granted_ability_cache`), so the turn stamp survives
        #: the pass that would otherwise have rebuilt it from scratch.
        self.once_per_turn = once_per_turn
        self._last_triggered_turn: Optional[int] = None

    def check_trigger(self, event: GameEvent, context: GameContext) -> bool:
        """RULE 603.1: does this ability trigger for ``event``?"""
        if event.type != self.trigger_event:
            return False
        if self.condition is not None and not self.condition(event, context):
            return False
        if self.once_per_turn:
            turn = context.state.turn_number
            if self._last_triggered_turn == turn:
                return False
            self._last_triggered_turn = turn
        return True

    def apply(
        self,
        context: GameContext,
        targets: Optional[list[Any]] = None,
        target_groups: Optional[list[list[Any]]] = None,
    ) -> None:
        """Resolve the triggered ability by applying each of its effects.

        ``target_groups``, when given (`StackItem.target_groups`, 2+
        *different* targeting effects), partitions ``targets`` per effect —
        see `_apply_effects_partitioned`.
        """
        _apply_effects_partitioned(self.effects, context, targets, target_groups, source=self.source)


# ---------------------------------------------------------------------------
# TYPE 3: Replacement effects (RULE 614)
# ---------------------------------------------------------------------------


class ReplacementEffect(GameEffect):
    """Rewrites an event before it happens; never uses the stack (RULE 614).

    ``replacement_fn`` maps ``(event, context) -> GameEvent | None`` — a
    new event, or ``None`` to prevent it entirely. ``self_replacement``
    marks effects that may only apply once to a given event (RULE 614.5),
    which the engine tracks to avoid infinite replacement loops.
    """

    def __init__(
        self,
        event_type: str,
        replacement_fn: Callable[[GameEvent, GameContext], Optional[GameEvent]],
        condition: Optional[Callable[[GameEvent, GameContext], bool]] = None,
        source: Optional["GameObject"] = None,
        description: str = "",
    ) -> None:
        super().__init__(source)
        self.event_type = event_type
        self.replacement_fn = replacement_fn
        self.condition = condition
        self.description = description

    def can_replace(self, event: GameEvent, context: GameContext) -> bool:
        if event.type != self.event_type:
            return False
        if self.condition is not None and not self.condition(event, context):
            return False
        return True

    def apply_replacement(self, event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        return self.replacement_fn(event, context)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        # Replacement effects are consulted via apply_replacement, not run
        # imperatively.
        return None


# ---------------------------------------------------------------------------
# TYPE 4: Activated abilities (RULE 602)
# ---------------------------------------------------------------------------


class ActivatedAbility(GameEffect):
    """A cost the controller may pay for an effect (docs/07 PART 2, RULE 602).

    ``cost`` is the full parsed `ActivationCost` (mana + tap/untap + sacrifice
    + life + discard + counter removal, see `game/costs.py`); ``effects`` go on
    the stack when the cost is paid. ``mana_cost``/``taps_source`` remain as
    read-only views over the cost for callers that only care about those two.

    ``once_per_turn=True`` (Quirion Ranger/Scryb Ranger's "Activate only
    once each turn.") mirrors `TriggeredAbility.once_per_turn`'s own
    RULE 603.2-style stamp: `game/game_engine.py`'s `can_activate`/
    `activate_ability` check/stamp `_last_activated_turn` against the
    current turn number, the same "stamped on the *ability instance* itself,
    not a GameObject field reset every turn" shape.
    """

    def __init__(
        self,
        effects: list[GameEffect],
        cost: Optional["ActivationCost"] = None,
        mana_cost: Optional[ManaCost] = None,
        taps_source: bool = False,
        source: Optional["GameObject"] = None,
        description: str = "",
        once_per_turn: bool = False,
        attach_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.effects = effects
        if cost is None:
            # Back-compat: build a cost from the old mana/tap parameters.
            from .costs import ActivationCost

            cost = ActivationCost(mana=mana_cost or ManaCost(), taps_self=taps_source)
        self.cost = cost
        self.description = description
        self.once_per_turn = once_per_turn
        self._last_activated_turn: Optional[int] = None
        #: Which RULE 301/303/704 attachment keyword generated this ability
        #: — ``"equip"``/``"fortify"``/``"reconfigure"`` (`effect_binder.
        #: _keyword_activated_ability`), or ``None`` for an ordinary
        #: activated ability. Surfaced on the `activate_ability` action
        #: (`legal_actions_mixin._activate_action`) purely so
        #: `services/bots.py`'s `GreedyBot` can deprioritize equipping —
        #: better spent mana on casting something else first — without
        #: guessing from the ability's description text.
        self.attach_kind = attach_kind

    @property
    def mana_cost(self) -> ManaCost:
        return self.cost.mana

    @property
    def taps_source(self) -> bool:
        return self.cost.taps_self

    def apply(
        self,
        context: GameContext,
        targets: Optional[list[Any]] = None,
        target_groups: Optional[list[list[Any]]] = None,
    ) -> None:
        """``target_groups``, when given (`StackItem.target_groups`, 2+
        *different* targeting effects), partitions ``targets`` per effect —
        see `_apply_effects_partitioned`."""
        _apply_effects_partitioned(self.effects, context, targets, target_groups, source=self.source)


# ---------------------------------------------------------------------------
# SPECIAL: Win/loss overrides (docs/07 PART 9)
# ---------------------------------------------------------------------------


class WinGameEffect(GameEffect):
    """"You win the game." (RULE 104.2) — Jace, Wielder of Mysteries' "-8:
    Draw seven cards. Then if your library has no cards in it, you win the
    game." tail (``if_empty_library=True`` gates it on the caster's current
    library being empty; unconditional win-the-game clauses would pass
    ``False``, though no card in the pool needs that shape yet). Calls
    `RulesEngine.player_wins` — the ability's own controller wins outright.
    """

    def __init__(self, if_empty_library: bool = False, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.if_empty_library = if_empty_library

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except Exception:
            return
        if self.if_empty_library and player.library:
            return
        context.engine.player_wins(player)


class BecomeMonarchEffect(GameEffect):
    """"[Player] become[s] the monarch." (RULE 725.1) — untargeted ("you
    become the monarch", Palace Jailer-shaped) by default; ``target_kind="player"``
    opts into a real RULE 115 target ("target player becomes the monarch",
    the Throne of the Damned-adjacent phrasing), mirroring `GainLifeEffect`.
    """

    def __init__(
        self,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        if player is not None:
            context.become_monarch(player)


class TakeInitiativeEffect(GameEffect):
    """"[Player] take[s] the initiative." (RULE 726.1) — same untargeted/
    targeted split as `BecomeMonarchEffect`.

    All three of RULE 726.2's inherent abilities are live: the combat-damage
    steal, the upkeep venture, and "whenever a player takes the initiative,
    that player ventures into Undercity" — the last one fired off the
    `EventType.TOOK_INITIATIVE` `RulesEngine.take_initiative` announces, which
    is also why RULE 726.5's "taking the initiative while you already have
    it" still ventures.
    """

    def __init__(
        self,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        if player is not None:
            context.take_initiative(player)


class GetCityBlessingEffect(GameEffect):
    """RULE 702.131a: Ascend's spell-ability form — "If you control ten or
    more permanents and you don't have the city's blessing, you get the
    city's blessing for the rest of the game." (the resolving instant/
    sorcery's own one-shot check).

    Ascend on a *permanent* (702.131b — "any time you control ten or more
    permanents…") is a continuous check instead, since the permanent must
    keep watching the board for as long as it's out there rather than
    checking once at resolution — see `RulesEngine._sba_check_ascend`, swept
    at SBA cadence like the day/night and Ring-bearer checks. This effect is
    only the spell form; both share `RulesEngine.get_city_blessing`'s
    idempotent flag-set (RULE 702.131c/d).
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from . import continuous  # avoid the continuous<->effects import cycle

        player = self.player or _controller_of(self.source, context)
        if player is None or player.has_city_blessing:
            return
        if continuous.count_selector(context.state, player.id, "permanents_you_control") >= 10:
            context.get_city_blessing(player)


class VentureIntoTheDungeonEffect(GameEffect):
    """"Venture into the dungeon." (RULE 701.49) — enter a dungeon, or move
    the venture marker one room down the one you're in.

    ``dungeon`` names RULE 701.49d's "venture into [quality]" variant
    ("venture into Undercity", RULE 726.2's own wording); ``None`` is the
    plain keyword action, which lets the player choose."""

    def __init__(
        self,
        dungeon: Optional[str] = None,
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.dungeon = dungeon
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or _controller_of(self.source, context)
        if player is not None:
            context.venture_into_the_dungeon(player, self.dungeon)


class CompleteDungeonEffect(GameEffect):
    """RULE 309.6/309.7: remove the completed dungeon card from the game.

    Appended by `RulesEngine._collect_dungeon_room_triggers` to a *bottommost*
    room's own ability, so it runs exactly when 309.6's condition first holds
    — "the venture marker is on the bottommost room and that dungeon isn't the
    source of a room ability that has triggered but not yet left the stack".
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.complete_dungeon(player)


class RadiationMillEffect(GameEffect):
    """RULE 728.1's rad-counter inherent ability: "that player mills a
    number of cards equal to the number of rad counters they have. For
    each nonland card milled this way, that player loses 1 life and
    removes one rad counter from themselves." Built fresh by
    `RulesEngine._collect_inherent_triggers` for whichever player's
    precombat main phase is beginning — no permanent hosts this ability,
    same shape as `BecomeMonarchEffect`/`TakeInitiativeEffect`. The count
    is read live at resolution time (not frozen at trigger time), matching
    the rule's present-tense "have".
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None:
            return
        count = player.counters.get("rad", 0)
        if count <= 0:
            return
        before = len(player.graveyard)
        context.mill(player, count)
        milled = player.graveyard[before:]
        nonland = sum(1 for obj in milled if not obj.is_land)
        if nonland:
            # RULE 728.1a: life lost "from radiation" refers to exactly this.
            context.lose_life(player, nonland, cause="radiation")
            context.add_player_counters(player, -nonland, "rad")


class CreateEmblemEffect(GameEffect):
    """"[Player] get[s] an emblem with '[ability]'." (RULE 114.2) — the
    quoted ability was already recursively parsed into a full nested
    `AbilitySpec` at parse time (`parser/oracle/catalogue/handlers.py`'s
    `_emblem_ability_spec`, the same recursive-`segment_line` idiom
    `static_handlers._quoted_ability_grant_effects` uses for an Aura/
    Equipment's quoted grant) and carried here as a plain JSON dict
    (``self.ability``) — still pure IR, nothing derived from card text has
    executed yet.

    Binding it into a live `TriggeredAbility`/`StaticAbility` happens once,
    at resolve time (`RulesEngine.create_emblem`), against a synthetic
    `Emblem` "source" rather than a real permanent (`models/emblem.py`) —
    an emblem has no permanent to attach to, so this can't happen at
    bind-on-load like every other ability.
    """

    def __init__(
        self,
        ability: Optional[dict] = None,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.ability = ability
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        if player is None or not self.ability:
            return
        context.create_emblem(player, self.ability)


class RequestChoosePlayerEffect(GameEffect):
    """"As this creature enters, choose a player." (Stuffy Doll) — opens
    `RulesEngine.request_choose_player`.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        context.engine.request_choose_player(player, self.source)


class DealDamageToChosenPlayerEffect(GameEffect):
    """"…it deals that much damage to the chosen player." (Stuffy Doll) —
    reads the firing `DAMAGE` event's own ``amount`` (the "that much" it
    was just dealt) against `GameObject.chosen_player_id`.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        player_id = getattr(self.source, "chosen_player_id", None)
        event = context.trigger_event
        if player_id is None or not event:
            return
        amount = int(event.get("amount") or 0)
        if amount <= 0:
            return
        try:
            player = context.state.player_by_id(player_id)
        except (KeyError, ValueError):
            return
        context.deal_damage(player, amount, self.source)


class RequestChooseCreatureTypeGrantEffect(GameEffect):
    """"When this creature enters, choose a creature type. <effect naming
    the chosen type>." (Selfless Safewright) — opens `RulesEngine.
    request_choose_creature_type_grant`'s resolve-time type choice; see its
    docstring for why this needs its own primitive rather than RULE
    601.2b's as-it-enters `choose_creature_type_on_enter`.
    """

    def __init__(
        self,
        then_specs: Optional[list[dict]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.then_specs = list(then_specs or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        context.engine.request_choose_creature_type_grant(player, self.source, self.then_specs)


class GrantKeywordsToChosenTypeUntilEotEffect(GameEffect):
    """"Other permanents you control of that type gain hexproof and
    indestructible until end of turn." (Selfless Safewright) — "that type"
    is this effect's own source's `GameObject.chosen_type`, read live
    (set moments earlier in the same resolution by `RequestChooseCreature
    TypeGrantEffect`'s choice) rather than captured at bind time.
    """

    def __init__(
        self,
        keywords: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.keywords = list(keywords or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        wanted = getattr(self.source, "chosen_type", None)
        if not wanted or self.source is None or not self.keywords:
            return
        controller_id = self.source.controller_id
        for obj in context.state.battlefield:
            if obj is self.source or obj.controller_id != controller_id:
                continue
            if wanted.lower() not in (obj.card.type_line or "").lower():
                continue
            for kw in self.keywords:
                obj.temp_keywords.add(kw)
        context.recompute()


class GrantKeywordToTriggerSubjectEffect(GameEffect):
    """"…it gains haste until end of turn…" (Tyvar Kell's emblem, RULE
    603.1 "it" = the spell that triggered this ability) — grants a temporary
    keyword to whatever object `GameContext.trigger_event` named, rather
    than a targeted or self object. The cast spell's own `GameObject`
    persists by identity from the stack onto the battlefield (RULE 400.7's
    "new object" rule doesn't apply mid-cast), so a keyword stamped here
    while it's still a `SPELL_CAST` stack item is still present once it
    resolves.
    """

    def __init__(
        self,
        keyword: str = "haste",
        source: Optional["GameObject"] = None,
        event_key: str = "instance_id",
    ) -> None:
        super().__init__(source)
        self.keyword = keyword
        self.event_key = event_key

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if not event:
            return
        instance_id = event.get(self.event_key)
        if instance_id is None:
            return
        obj = context.state.find_object(instance_id)
        if obj is not None:
            obj.temp_keywords.add(self.keyword)


class WinConditionEffect(GameEffect):
    """Overrides a win/loss check, e.g. "you can't lose the game"."""

    def __init__(
        self,
        condition_type: str = "prevent_loss",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.condition_type = condition_type

    def prevents_loss(self) -> bool:
        return self.condition_type == "prevent_loss"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class TopLibraryPermissionEffect(GameEffect):
    """Standing permission to look at / play lands from / cast spells from
    the top of the controller's library (Oracle of Mul Daya/Glarb, Calamity's
    Augur/Future Sight-shaped) — RULE 701 has no native "play from the top"
    provision, so each real card grants it as its own static ability.

    Bound like any other ``static`` ability (`game/effect_binder.py`'s
    ordinary dispatch), so it lands in ``obj.static_effects`` alongside
    `StaticAbility` — but it carries no layer/characteristic behaviour of its
    own: `continuous.recompute` only ever reads `StaticAbility` instances off
    that list (this isn't one, the same precedent as `CantBeCounteredEffect`
    above), so it's inert there. The only consumer is
    `game/top_library.py`, which scans every battlefield permanent a player
    controls for one of these (honouring ``requires_attached`` — an
    Equipment/Reconfigure-shaped grant that only counts while actually
    attached to something) and merges the results: multiple simultaneous
    grants OR together (a spell is castable if *any* active grant's
    ``min_mana_value`` gate — or lack of one — allows it), never AND.

    ``noncreature_only`` narrows ``cast_spells`` to noncreature spells only
    (Elsha of the Infinite's own restriction — a closed vocabulary of one,
    not a general subtype filter, since no other real card needs a different
    restriction here today). ``grants_flash``/``life_payment`` are each
    card's own conditional tail on top of the base permission: Elsha's "you
    may cast it as though it had flash" (consulted by `game/top_library.py`'s
    `may_cast_flash_from_top_of_library`, `GameEngine.can_cast`'s flash
    union) and Bolas's Citadel's "pay life equal to its mana value rather
    than pay its mana cost" (`top_library.top_library_life_payment_required`,
    `GameEngine._top_library_life_payment`) — both apply automatically
    whenever a spell is actually cast via *this* grant, never as a separate
    opt-in choice, matching the printed wording ("If you cast a spell this
    way, ...").
    """

    def __init__(
        self,
        look: bool = False,
        play_lands: bool = False,
        cast_spells: bool = False,
        min_mana_value: Optional[int] = None,
        requires_attached: bool = False,
        noncreature_only: bool = False,
        grants_flash: bool = False,
        life_payment: bool = False,
        chosen_type_creature_only: bool = False,
        creature_only: bool = False,
        subtypes: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.look = look
        self.play_lands = play_lands
        self.cast_spells = cast_spells
        self.min_mana_value = min_mana_value
        self.requires_attached = requires_attached
        self.noncreature_only = noncreature_only
        self.grants_flash = grants_flash
        self.life_payment = life_payment
        #: "You may cast **creature spells of the chosen type** from the top
        #: of your library." (Realmwalker) — narrows `cast_spells` to
        #: creature spells matching this grant's own source's `GameObject.
        #: chosen_type` (RULE 601.2b), read live off ``self.source`` rather
        #: than captured at bind time so a Replay/Puzzle-mode change to the
        #: choice is honoured immediately, the same live-read idiom
        #: `continuous.recompute`'s `subtype_from_source` selectors use.
        self.chosen_type_creature_only = chosen_type_creature_only
        #: "You may cast **creature** spells from the top of your library."
        #: (Eladamri, Korvecdal, MEC-40) — a plain, printed creature-only
        #: restriction (unlike ``chosen_type_creature_only``'s RULE 601.2b
        #: ETB-choice narrowing), the direct mirror of ``noncreature_only``.
        self.creature_only = creature_only
        #: "You may cast **Angel spells and Human spells** from the top of
        #: your library." (Sigarda, Font of Blessings, MEC-40) — a closed
        #: list of printed subtype words; the card qualifies if its type
        #: line contains *any* of them (union, not intersection — matching
        #: how "Angel spells and Human spells" reads as "either").
        self.subtypes = [str(s).lower() for s in subtypes] if subtypes else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # continuous marker — consulted by top_library.py, not applied


class GraveyardCastPermissionEffect(GameEffect):
    """Standing permission to cast [permanent] spells from the controller's
    own graveyard (Lurrus of the Dream-Den-shaped) — the graveyard sibling of
    `TopLibraryPermissionEffect` above, consulted the same "scan on demand"
    way by `game/graveyard_cast.py` rather than a closed keyword vocabulary
    like Flashback/Escape (`GameEngine._graveyard_cast_keyword`): those are
    an alternative *cost* printed on the card itself, this is a *permission*
    granted by some other permanent, paid at the card's own normal mana cost.

    ``permanent_only`` is Lurrus's own "a permanent spell" restriction
    (creature/artifact/enchantment/land/planeswalker); ``max_mana_value`` is
    its "with mana value 2 or less" gate (``None`` = unrestricted).
    ``once_per_turn`` (RULE 500.4-adjacent "once during each of your turns")
    is tracked per *granting object* (`GameObject.graveyard_casts_this_turn`,
    reset every untap step alongside `activated_loyalty_this_turn` — the same
    per-object, not per-player, precedent: two copies of the granting
    permanent each grant their own use).

    Bound like `TopLibraryPermissionEffect` (an ordinary ``static`` ability,
    inert to `continuous.recompute` — the only consumer is
    `game/graveyard_cast.py`).

    ``exile_if_would_be_put_into_graveyard`` is Lurrus's own trailing "if a
    spell cast this way would be put into a graveyard this turn, exile it
    instead" clause (RULE 616, ``False`` by default — a different card
    reusing this same base permission need not carry it). It isn't checked
    here: `GameEngine.cast_spell`'s dispatch stamps `GameObject.
    cast_via_graveyard_cast_permission_until_turn` with the casting turn
    only when the grant it used has this flag set, and `RulesEngine.
    _move_to_graveyard` (the one choke point every graveyard-bound move —
    destroy, sacrifice, or SBA "dies" — funnels through) redirects to exile
    while that still matches the current turn number. A per-cast turn
    number rather than a per-object bool so a later *normal* recast this
    same turn (no permission involved) correctly clears it, mirroring
    `GameObject.cast_via_flashback`'s own unconditional-reassignment
    pattern.
    """

    def __init__(
        self,
        max_mana_value: Optional[int] = None,
        permanent_only: bool = True,
        once_per_turn: bool = True,
        exile_if_would_be_put_into_graveyard: bool = False,
        source: Optional["GameObject"] = None,
        instant_sorcery_only: bool = False,
        expires_turn: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self.max_mana_value = max_mana_value
        self.permanent_only = permanent_only
        self.once_per_turn = once_per_turn
        self.exile_if_would_be_put_into_graveyard = exile_if_would_be_put_into_graveyard
        #: "Each instant and sorcery card in your graveyard gains flashback
        #: until end of turn." (Backdraft Hellkite) — the mirror image of
        #: ``permanent_only``: only instant/sorcery cards, never a
        #: permanent. Mutually meaningful with ``permanent_only`` off.
        self.instant_sorcery_only = instant_sorcery_only
        #: A one-shot, turn-scoped grant (as opposed to the ordinary
        #: standing-while-attached shape every other consumer uses) —
        #: `RulesEngine.turn_number` this expires after, appended directly
        #: onto a still-on-the-battlefield permanent's own
        #: `GameObject.static_effects` (`GrantGraveyardCastPermissionThis
        #: TurnEffect`) rather than tied to a printed static ability's own
        #: continuous binding. ``None`` (every existing consumer) means
        #: "as long as the granting permanent is on the battlefield", same
        #: as before this field existed.
        self.expires_turn = expires_turn

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # continuous marker — consulted by graveyard_cast.py, not applied


class SelfGraveyardOrExileCastPermissionEffect(GameEffect):
    """"You may cast this card from your graveyard or from exile." (Squee,
    the Immortal-shaped) — the card's own standing self-permission, unlike
    `GraveyardCastPermissionEffect` (granted by some *other* permanent,
    scanned off the battlefield by `game/graveyard_cast.py`). Read
    directly off this object's own ``static_effects`` by `GameEngine.
    can_cast`'s ``in_castable_zone`` check (`_self_graveyard_or_exile_
    cast_permission`) regardless of which of the two zones it's currently
    sitting in — no board scan needed since the source *is* the card being
    cast, and bind-on-load already binds every object at every zone (not
    just the battlefield), so the marker survives the card's own trip
    through hand → battlefield → graveyard/exile.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class GrantGraveyardCastPermissionThisTurnEffect(GameEffect):
    """"Each instant and sorcery card in your graveyard gains flashback
    until end of turn. The flashback cost is equal to its mana cost."
    (Backdraft Hellkite) — "flashback at the printed mana cost" is exactly
    `GraveyardCastPermissionEffect`'s own shape, just turn-scoped and
    instant/sorcery-only rather than a standing permanent-only grant. Appends
    a fresh permission straight onto this effect's own source's
    `GameObject.static_effects` — the source (the attacking creature) is
    already on the battlefield and stays there, so `graveyard_cast.py`'s
    existing per-permanent scan finds it with no new consumer-side code,
    only the expiry check `expires_turn` adds.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        self.source.static_effects.append(
            GraveyardCastPermissionEffect(
                permanent_only=False,
                instant_sorcery_only=True,
                once_per_turn=False,
                expires_turn=context.state.turn_number,
                source=self.source,
            )
        )


class GrantFlashbackToTargetEffect(GameEffect):
    """"Target instant or sorcery card in your graveyard gains flashback
    until end of turn. The flashback cost is equal to its mana cost."
    (MEC-24 — Recoup/Snapcaster Mage/Slickshot Lockpicker/Sphinx of
    Forgotten Lore/Katilda and Lier/The Fugitive Doctor-shaped) — the
    targeted, single-card sibling of `GrantGraveyardCastPermissionThisTurn
    Effect`'s untargeted "each instant and sorcery card in your graveyard"
    grant (Backdraft Hellkite). That one appends a marker onto the
    *granting permanent's own* `GameObject.static_effects`, discoverable by
    `game/graveyard_cast.py`'s battlefield scan; this one instead marks the
    *targeted graveyard card itself* (`GameState.temp_flashback_grants`),
    since the grant must survive independently of whatever granted it (the
    creature that triggered this may attack into removal, or simply leave
    the battlefield, before the graveyard card is ever cast) and must apply
    to exactly the one chosen card, not every instant/sorcery in the
    graveyard.

    ``cost=None`` (every real card but The Fugitive Doctor) means "equal to
    its mana cost" — read off the target's own `Card.mana_cost_string` at
    the moment this effect resolves, matching *that* card's cost rather
    than a fixed one; a literal ``cost`` string (The Fugitive Doctor's flat
    ``"{2}{R}{G}"``) overrides it. Consulted by `game/engine/casting_mixin.
    py`'s `_graveyard_cast_keyword`/`_flashback_cost`, the same choke point
    a printed Flashback keyword goes through — the exile-after-cast (RULE
    702.34a) and cost-computation machinery need no changes at all.
    """

    def __init__(
        self,
        cost: Optional[str] = None,
        target_kind: str = "graveyard_instant_or_sorcery",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost = cost
        self.target_spec = TargetSpec(kind=target_kind, count=1)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None:
            return
        cost = self.cost or getattr(target.card, "mana_cost_string", None) or "{0}"
        context.state.temp_flashback_grants[target.instance_id] = str(cost)


class GrantSelfActivatedAbilityEffect(GameEffect):
    """"This [permanent] gains '`<cost>`: `<effect>`.'" (Urza's Saga's own
    Saga-chapter shape, RULE 714.2c — a chapter's *lasting* self-grant, not
    a turn-scoped one). Appends a real `grant_activated_ability`-shaped
    `StaticAbility` (``affects="self"``) straight onto this effect's own
    source's `GameObject.static_effects`, the same "append a static at
    resolve time" idiom `GrantGraveyardCastPermissionThisTurnEffect` uses —
    permanent (no expiry) rather than turn-scoped, since a Saga chapter's
    grant lasts for as long as the Saga itself does.
    """

    def __init__(
        self,
        cost: Optional[dict[str, Any]] = None,
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.granted_cost = dict(cost or {})
        self.granted_effects = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        from .effect_binder import build_effects  # function-scoped: effects↔binder cycle
        from ..parser.oracle.spec import EffectSpec

        granted = build_effects(
            [EffectSpec("grant_activated_ability", {
                "affects": "self", "cost": self.granted_cost, "grant_effects": self.granted_effects,
            })],
            self.source,
        )
        self.source.static_effects.extend(granted)


class GainActivatedAbilitiesOfTargetEffect(GameEffect):
    """"~ gains all activated abilities of target creature until end of
    turn." (MEC-23, Quicksilver Elemental) — the resolve-time, single-target
    sibling of `grant_borrowed_activated_ability`'s standing layer-6 grant
    (`continuous._apply_borrowed_activated_abilities`, MEC-21, Agatha's Soul
    Cauldron): that one re-derives its granted set live off a permanent's
    own `GameObject.exiled_with_ids` every `continuous.recompute` pass, so a
    later change to an exiled card's own abilities is picked straight back
    up. This effect instead **snapshots** ``target``'s `activated_abilities`
    once, at resolution, onto a turn-scoped field
    (`GameObject.temp_granted_activated_abilities`, cleared at cleanup
    alongside `temp_keywords` — RULE 514.2) — a later change to the
    target's own ability set doesn't retroactively change what was copied,
    matching Quicksilver Elemental's own ruling that this is a one-time
    copy, not a continuous link to the target.

    Reuses `continuous._retarget_effect_source` (RULE 113.7c: "Any ability
    that a permanent gains by another spell/ability applies to that
    permanent, not to the object that granted it") rather than a second
    implementation — the same shallow-copy-per-effect approach the layer-6
    grant already uses.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature", count=1)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or not targets:
            return
        target = targets[0]
        if target is None:
            return
        from . import continuous  # local: avoid the continuous<->effects import cycle

        for base in list(getattr(target, "activated_abilities", None) or []):
            self.source.temp_granted_activated_abilities.append(
                ActivatedAbility(
                    effects=[continuous._retarget_effect_source(e, self.source) for e in base.effects],
                    cost=base.cost,
                    source=self.source,
                    description=base.description,
                    once_per_turn=base.once_per_turn,
                )
            )


# ---------------------------------------------------------------------------
# SPECIAL: Conditional effect wrapper (parser/oracle/spec.py's EffectSpec.condition)
# ---------------------------------------------------------------------------


class ConditionalEffect(GameEffect):
    """Gates ``inner`` so it only applies when ``condition`` holds (RULE
    702.33b's "if this spell was kicked, <effect>." — a *second, additional*
    effect on the same spell/ability, not a replacement of an earlier one;
    see `parser.oracle.spec.EffectSpec.condition`'s docstring for why "if
    kicked, ... instead" — overriding an *existing* effect's own amount —
    is a different, unmodeled shape). ``{"target_is_controller": True}``
    (The Ghoul, Gunslinger: "target player gets two rad counters. If that
    player is you, create a Treasure token.") is the RULE 603.4-style
    sibling gated on the ability's own *resolved target* instead of an
    announced-cost flag — checked against ``targets`` at apply time, which
    only works because this effect carries no `target_spec` of its own: a
    `target_groups=None` ability (the overwhelming common case) passes its
    *whole* targets list to every sub-effect (`_apply_effects_partitioned`),
    so this effect transparently sees the target chosen for whichever
    *other* effect in the same ability actually declared it.

    Built only by `game/effect_binder.py`'s `build_effects`, never directly
    by `EffectRegistry` (``condition`` lives on the `EffectSpec`, not inside
    ``params``, so there's no ``"conditional"`` registry entry to construct
    one from card-text-derived data — keeps the whitelist's shape/behaviour
    split from docs/09 intact).
    """

    def __init__(
        self,
        condition: dict[str, Any],
        inner: GameEffect,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.condition = condition
        self.inner = inner
        self.target_spec = inner.target_spec

    def _condition_holds(
        self, context: GameContext, targets: Optional[list[Any]] = None
    ) -> bool:
        """AND of every key present in ``condition`` — each existing card so
        far has set exactly one, so this was a plain if/elif chain until
        Frodo, Adventurous Hobbit's own second clause ("if ~ is your
        Ring-bearer **and** the Ring has tempted you N or more times this
        game") needed two keys to hold *together*. Backward compatible: a
        one-key dict still checks exactly that one key, same as before.
        """
        kicked = self.condition.get("kicked")
        if kicked is not None:
            count = getattr(self.source, "kicker_count", 0) or 0
            if not ((count > 0) if kicked else (count == 0)):
                return False
        kicked_at_least = self.condition.get("kicked_at_least")
        if kicked_at_least is not None:
            # RULE 702.34a: "if it was kicked twice, <effect>." (PAR-17,
            # Archangel of Wrath) — Multikicker's own count threshold,
            # distinct from the plain "was it kicked at all" gate above.
            count = getattr(self.source, "kicker_count", 0) or 0
            if count < kicked_at_least:
                return False
        bargained = self.condition.get("bargained")
        if bargained is not None:
            # RULE 701.x (Beseech the Mirror's "if this spell was bargained,
            # …") — Kicker's own gate for a different optional additional
            # cost, reading `GameObject.bargained` instead of a counter.
            was = bool(getattr(self.source, "bargained", False))
            if not (was if bargained else not was):
                return False
        target_is_controller = self.condition.get("target_is_controller")
        if target_is_controller is not None:
            target = targets[0] if targets else None
            controller_id = getattr(self.source, "controller_id", None)
            is_controller = (
                controller_id is not None
                and getattr(target, "id", None) == controller_id
            )
            if not (is_controller if target_is_controller else not is_controller):
                return False
        life_gained_at_least = self.condition.get("life_gained_this_turn_at_least")
        if life_gained_at_least is not None:
            # "if you gained N or more life this turn, <effect>." (RULE
            # 119.3 — Frodo, Adventurous Hobbit's own first clause).
            # `self` here means the ability's controller, not a target.
            player = _controller_of(self.source, context)
            gained = context.state.life_gained_this_turn.get(getattr(player, "id", None), 0)
            if gained < life_gained_at_least:
                return False
        is_ring_bearer = self.condition.get("is_ring_bearer")
        if is_ring_bearer is not None:
            # "if ~ is your Ring-bearer, <effect>." (RULE 701.52a) — reads
            # the ability's controller's `ring_bearer_id` against the
            # source's own `instance_id`, "not" for the Aragorn/Faramir-
            # shaped "if you chose a creature **other than** ~" mirror.
            player = _controller_of(self.source, context)
            bearer_id = getattr(player, "ring_bearer_id", None)
            source_id = getattr(self.source, "instance_id", None)
            is_bearer = bearer_id is not None and bearer_id == source_id
            if not (is_bearer if is_ring_bearer else not is_bearer):
                return False
        creatures_died_this_turn_at_least = self.condition.get("creatures_died_this_turn_at_least")
        if creatures_died_this_turn_at_least is not None:
            # "if a creature died under your control this turn, <effect>."
            # (Sméagol, Helpful Guide) — `GameState.creatures_died_this_turn`,
            # tallied by `RulesEngine._move_to_graveyard`'s own DIES handling,
            # the same "this turn" counter idiom as `life_gained_this_turn`.
            player = _controller_of(self.source, context)
            died = context.state.creatures_died_this_turn.get(getattr(player, "id", None), 0)
            if died < creatures_died_this_turn_at_least:
                return False
        source_x_paid_at_least = self.condition.get("source_x_paid_at_least")
        if source_x_paid_at_least is not None:
            # "If X is 5 or more, destroy all other creatures." (Martial
            # Coup) — the announced {X} this spell/ability was itself cast
            # or activated for (RULE 107.3c, `GameObject.x_paid`), unlike
            # `_substitute_x`'s ``"x"`` sentinel (which rewrites a plain
            # magnitude field, not a gate) or `ring_tempted_at_least`-style
            # keys (which read board/player state, not the source itself).
            x_paid = getattr(self.source, "x_paid", 0) or 0
            if x_paid < source_x_paid_at_least:
                return False
        controls_none_of_type = self.condition.get("controls_none_of_type")
        if controls_none_of_type is not None:
            # "if you don't control a Food, <effect>." (Butterbur, Bree
            # Innkeeper) — a live battlefield scan for the controller's own
            # permanents of that printed subtype, same word list
            # `segmenter._SACRIFICE_TYPE_TRIGGER_RE`/`_NAMED_TOKEN_WORDS`
            # already trust.
            controller_id = getattr(_controller_of(self.source, context), "id", None)
            word = str(controls_none_of_type).lower()
            controls_one = any(
                o.controller_id == controller_id
                and word in o.card.type_line.partition("—")[2].strip().lower().split()
                for o in context.state.battlefield
            )
            if controls_one:
                return False
        shares_type_with_linked_exile = self.condition.get("shares_type_with_linked_exile")
        if shares_type_with_linked_exile:
            # "…if it shares a card type with the exiled card, ~ deals 2
            # damage to that player." (Cemetery Gatekeeper) — the played
            # land/cast spell (named by the firing event's own
            # ``instance_id``) against the card this ability's own source
            # remembered exiling (`ExileEffect.remember`, `GameObject.
            # linked_exile_id`).
            event = context.trigger_event or {}
            played_id = event.get("instance_id")
            exiled_id = getattr(self.source, "linked_exile_id", None)
            played = context.state.find_object(played_id) if played_id is not None else None
            exiled = context.state.find_object(exiled_id) if exiled_id is not None else None
            if played is None or exiled is None:
                return False
            # RULE 205.2a's real card types only — `type_words` always
            # includes "permanent" too, which would make every comparison
            # trivially true.
            real_types = {
                "creature", "artifact", "enchantment", "instant", "sorcery",
                "planeswalker", "land", "battle",
            }
            if not (played.type_words & exiled.type_words & real_types):
                return False
        source_entered_untapped = self.condition.get("source_entered_untapped")
        if source_entered_untapped is not None:
            # "When ~ enters **untapped**, `<effect>`." (Mystic Sanctuary-
            # shaped RULE 614.1-adjacent intervening-if) — `GameObject.
            # tapped` is already settled by `RulesEngine.enter_land_tapped`
            # before ENTERS_BATTLEFIELD fires.
            if bool(getattr(self.source, "tapped", False)) == bool(source_entered_untapped):
                return False
        source_was_cast = self.condition.get("source_was_cast")
        if source_was_cast is not None:
            # "When ~ enters, if you cast it, `<effect>`." (Rocco, Cabaretti
            # Caterer-shaped) — RULE 601.2's "actually cast" check
            # (`GameObject.was_cast`), distinguishing a real cast from a
            # searched/reanimated/token entry.
            if bool(getattr(self.source, "was_cast", False)) != bool(source_was_cast):
                return False
        cast_outside_sorcery_speed = self.condition.get("cast_outside_sorcery_speed")
        if cast_outside_sorcery_speed is not None:
            # "If you cast it any time a sorcery couldn't have been cast,
            # `<downside>`." (RULE 601.3a, MEC-44 — Necromancy-shaped) —
            # `GameObject.cast_outside_sorcery_speed`, stamped once at cast
            # time (`GameEngine._cast_current_face`) since the board has
            # moved on by the time this resolves.
            if bool(getattr(self.source, "cast_outside_sorcery_speed", False)) != bool(
                cast_outside_sorcery_speed
            ):
                return False
        cards_in_graveyard_at_least = self.condition.get("cards_in_graveyard_at_least")
        if cards_in_graveyard_at_least is not None:
            # RULE 702.19 Threshold's own gate ("Threshold — Add {B}{B}{B}
            # {B}{B} instead if there are seven or more cards in your
            # graveyard." — Cabal Ritual, MEC-40) — a raw graveyard card
            # *count*, unlike `card_types_in_graveyard_at_least` (a distinct-
            # types count, `static_conditions.py`'s own "as long as" sibling
            # for a permanent's standing `active_if`, not reachable from a
            # resolve-time `EffectSpec.condition`).
            player = _controller_of(self.source, context)
            count = len(getattr(player, "graveyard", []) or [])
            if count < cards_in_graveyard_at_least:
                return False
        entering_object_unique_name = self.condition.get("entering_object_unique_name")
        if entering_object_unique_name:
            # "…if it doesn't have the same name as another creature you
            # control or a creature card in your graveyard, …" (Guardian
            # Project, MEC-40) — the entering creature is the *group*
            # trigger's own subject, not `self.source` (Guardian Project
            # itself), so it's read off the firing event instead, the same
            # "instance_id off `GameContext.trigger_event`" idiom
            # `shares_type_with_linked_exile` uses just below.
            player = _controller_of(self.source, context)
            event = context.trigger_event or {}
            entering_id = event.get("instance_id")
            entering = context.state.find_object(entering_id) if entering_id is not None else None
            # "…a **nontoken** creature you control enters…" — the trigger
            # condition's own ``"nontoken"`` flag only ever combines with a
            # ``subtypes`` filter (`effect_binder._build_group_ok`), not a
            # plain ``type`` one, so it's checked here instead, off the
            # same already-resolved entering object.
            if entering is not None and getattr(entering, "is_token", False):
                return False
            if entering is not None and player is not None:
                name = entering.name
                shares = any(
                    o is not entering and o.controller_id == player.id
                    and o.is_creature and o.name == name
                    for o in context.state.permanents()
                ) or any(
                    o.card.is_creature and o.name == name
                    for o in getattr(player, "graveyard", []) or []
                )
                if shares:
                    return False
        source_is_renowned = self.condition.get("source_is_renowned")
        if source_is_renowned is not None:
            # "…if this creature is renowned, ~ deals 2 damage to that
            # player." (Scab-Clan Berserker) — RULE 603.4's intervening-if,
            # checked here at resolve time (a documented simplification of
            # the real double-check-at-trigger-time-too rule — harmless for
            # a solo damage payoff with nothing else riding on whether the
            # ability "triggered" vs fizzled).
            if bool(getattr(self.source, "renowned", False)) != bool(source_is_renowned):
                return False
        no_creatures_on_battlefield = self.condition.get("no_creatures_on_battlefield")
        if no_creatures_on_battlefield:
            # "At the beginning of the end step, if no creatures are on the
            # battlefield, sacrifice ~." (Pyrohemia) — global, unlike
            # `controls_none_of_type` above (a controller-scoped subtype
            # check); no subtype word either, just "a creature" at all.
            if any(o.is_creature for o in context.state.battlefield):
                return False
        target_is_player = self.condition.get("target_is_player")
        if target_is_player is not None:
            # "If a player is dealt damage this way, scry 1." (Play with
            # Fire) — reads the *other* effect's own shared targets list,
            # the same "no target_spec of its own" idiom `target_is_
            # controller` uses.
            target = targets[0] if targets else None
            is_player = target is not None and not hasattr(target, "instance_id")
            if not (is_player if target_is_player else not is_player):
                return False
        graveyard_has_type = self.condition.get("graveyard_has_type")
        if graveyard_has_type is not None:
            # "Then if there is an Elf card in your graveyard, you gain 2
            # life." (Trystan, Callous Cultivator) — a live scan of the
            # controller's own graveyard for a card whose type line
            # (main type or subtype) carries the named word, the same
            # `controls_none_of_type` word-list convention just above,
            # just over the graveyard zone instead of the battlefield.
            player = _controller_of(self.source, context)
            word = str(graveyard_has_type).lower()
            has_one = player is not None and any(
                word in o.card.type_line.lower() for o in player.graveyard
            )
            if not has_one:
                return False
        ring_tempted_at_least = self.condition.get("ring_tempted_at_least")
        if ring_tempted_at_least is not None:
            # "if the Ring has tempted you N or more times this game,
            # <effect>." (RULE 701.51b — `Player.ring_level`, capped at 4).
            player = _controller_of(self.source, context)
            level = int(getattr(player, "ring_level", 0) or 0)
            if level < ring_tempted_at_least:
                return False
        ring_tempted_at_most = self.condition.get("ring_tempted_at_most")
        if ring_tempted_at_most is not None:
            # The upper-bound mirror of `ring_tempted_at_least` — "…
            # <effect>. Otherwise, the Ring tempts you." (Frodo, Sauron's
            # Bane) is an if/else over the same threshold, expressed as two
            # independent conditionals rather than a dedicated "otherwise"
            # branch, so the complementary bound needs its own key.
            player = _controller_of(self.source, context)
            level = int(getattr(player, "ring_level", 0) or 0)
            if level > ring_tempted_at_most:
                return False
        not_already_exerted = self.condition.get("not_already_exerted")
        if not_already_exerted:
            # RULE 603.4-style intervening if — "if ~ hasn't been exerted
            # this turn, you may exert it… When you do, <effect>." (Combat
            # Celebrant's own self-loop guard: without this, its own granted
            # extra combat phase would let it exert, and grant, forever).
            # Reads the firing `EXERTED` event's own snapshot rather than
            # `GameObject.exerted_this_turn` directly — that flag is already
            # True by the time this trigger resolves (`GameEngine.
            # declare_attackers` sets it before firing), so only the event's
            # own pre-set value still distinguishes a first exert from a
            # repeat one.
            event = context.trigger_event or {}
            if event.get("already_exerted"):
                return False
        is_first_combat_phase = self.condition.get("is_first_combat_phase")
        if is_first_combat_phase is not None:
            # RULE 603.4: "if it's the first combat phase of the turn,
            # <effect>." (Karlach, Fury of Avernus/Finest Hour/Genji
            # Glove-shaped extra-combat guards — without this, a card
            # granting its own extra combat phase could re-trigger itself
            # in that extra phase and grant another, forever). Checked at
            # resolution, the same "intervening if" timing `not_already_
            # exerted` uses, not a separate fire-time gate.
            is_first = context.state.combats_this_turn <= 1
            if is_first != is_first_combat_phase:
                return False
        opponent_cast_color = self.condition.get("opponent_cast_color_this_turn")
        if opponent_cast_color is not None:
            # "if an opponent has cast a blue or black spell this turn."
            # (Veil of Summer) — any opponent's `GameState.spell_colors_
            # cast_this_turn` intersecting the named colours.
            player = _controller_of(self.source, context)
            wanted = {str(c).upper() for c in opponent_cast_color}
            controller_id = getattr(player, "id", None)
            cast_any = any(
                colors & wanted
                for pid, colors in context.state.spell_colors_cast_this_turn.items()
                if pid != controller_id
            )
            if not cast_any:
                return False
        is_your_turn = self.condition.get("is_your_turn")
        if is_your_turn is not None:
            # "If it's your turn, end the turn." (Day's Undoing) — RULE
            # 500.1's active player, compared against this ability's own
            # controller, not any target.
            player = _controller_of(self.source, context)
            active = context.state.active_player
            is_active = player is not None and active is not None and player.id == active.id
            if is_active != is_your_turn:
                return False
        return True

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.inner.source is None:
            self.inner.source = self.source
        if self._condition_holds(context, targets):
            self.inner.apply(context, targets)


# ---------------------------------------------------------------------------
# Concrete one-shot effects (RULE 608 resolution bodies)
# ---------------------------------------------------------------------------


#: `DealDamageEffect`'s closed selector vocabulary for a mass, untargeted hit
#: (RULE 601.2c — not RULE 115 targeting at all, e.g. Pyroclasm's "~ deals 2
#: damage to each creature"). Kept small and explicit rather than reusing
#: `continuous.group_selector_objects`'s full vocabulary, since only these
#: phrasings appear on real damage-dealing cards. ``each_creature_and_player``
#: is the compound "~ deals N damage to each creature and each player"
#: shape (Volcanic Fallout) — a single amount hitting both groups at once,
#: not two separate effects (so a doubling replacement like Furnace of Rath
#: sees — and can double — each hit individually, exactly as printed).
_DAMAGE_SELECTORS: frozenset[str] = frozenset(
    {"each_creature", "each_player", "each_opponent", "each_creature_and_player",
     # "~ deals 1 damage to each creature and each planeswalker." (MEC-11's
     # Stalwart Speartail) — the compound-selector sibling of
     # ``each_creature_and_player``, a creature-or-planeswalker union rather
     # than creature-or-player.
     "each_creature_and_planeswalker",
     # "it deals 1 damage to **you**" (Mana Vault's draw-step ping) — the
     # source's own controller, untargeted (RULE 115: "you" is never a
     # target). The single-player counterpart of "each_player" above.
     "controller",
     # "~ deals 1 damage to itself." (Stuffy Doll) — the source's own
     # permanent, unlike "controller" (that permanent's *player*).
     "self",
     "defending_player",
     # "~ deals N damage to that player." (Spellshock/Eidolon of the Great
     # Revel-shaped cast-trigger punishers) — the player named by the
     # currently-resolving trigger's own event (`_event_player`, the same
     # helper `PayCostThenEffect`'s ``payer="event_player"`` already reads),
     # not a RULE 115 target: the ability names its own firing condition's
     # actor, the caster never chooses who gets hit.
     "event_player",
     # "Whenever a land enters, ~ deals N damage to that land's
     # controller." (Zo-Zu the Punisher) — unlike ``event_player`` (reads
     # the firing event's own ``player_id``, the *acting* player of a
     # cast/draw/tap-for-mana-shaped event), this reads its
     # ``controller_id`` — the *entering permanent's* controller
     # (`AddManaEffect.recipient`'s existing ``"event_controller"`` idiom,
     # `_event_player`'s own default key).
     "event_controller",
     # "Each creature deals 1 damage to its controller." (Rakdos Charm's
     # own third mode) — unlike every other row here, the *recipient*
     # varies per creature (that creature's own controller), so this is N
     # independent single-recipient hits (all sharing the same flat
     # ``amount``) rather than one amount fanned out to a fixed group.
     "each_creature_controller",
     # "…it deals that much damage to each **other** opponent." (Kediss,
     # Emberclaw Familiar) — `each_opponent` minus whichever opponent the
     # *firing* DAMAGE event already hit (`GameContext.trigger_event`'s own
     # ``target_id``), so the original recipient isn't hit a second time.
     "each_other_opponent",
     # "~ deals N damage to each opponent and each creature [and
     # planeswalker] they control." (Tectonic Hazard/End the Festivities/
     # Spiteful Banditry/Delayed Blast Fireball-shaped board wipes) — unlike
     # ``each_creature_and_player`` (every creature globally + every
     # player), this is scoped to *opponents only* and *their own*
     # permanents, so an ally's board is untouched.
     "each_opponent_and_their_creatures",
     "each_opponent_and_their_creatures_and_planeswalkers",
     # "At the beginning of each player's upkeep, ~ deals 1 damage to
     # them." (Roiling Vortex-shaped) — unlike ``event_player`` (a value
     # snapshotted on the firing event), `STEP_BEGIN` carries no player at
     # all, since it fires once per step globally; "them" is whoever's
     # step it is, read live off `GameState.active_player` at resolution
     # time (unchanged since the trigger fired moments earlier).
     "active_player"}
)


class CoinFlipEffect(GameEffect):
    """RULE 705.1 "flip a coin. If you lose the flip, `<effect>`. If you win
    the flip, `<effect>`." (Ral, Monsoon Mage-shaped) — branches into
    ``win_effects``/``lose_effects`` (serialized ``{"type","params"}``
    dicts, the same shape `CreateDelayedTriggerEffect.effects` takes), off
    `RulesEngine.coin_flip`'s existing reproducible RNG. **Documented
    simplification**: a "you may" on the winning branch is modeled as
    unconditional (always taken) — the same accepted simplification every
    other undecided "may" in this codebase uses (Arcane Denial's "may draw
    up to two") when declining a beneficial option is a real but
    vanishingly rare choice.
    """

    def __init__(
        self,
        win_effects: Optional[list[dict[str, Any]]] = None,
        lose_effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.win_specs = list(win_effects or [])
        self.lose_specs = list(lose_effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .effect_binder import build_effects  # function-scoped: effects↔binder cycle
        from ..parser.oracle.spec import EffectSpec

        specs = self.win_specs if context.engine.coin_flip() else self.lose_specs
        if not specs:
            return
        inner = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in specs],
            self.source,
        )
        for effect in inner:
            effect.apply(context, targets)


class DealDamageEffect(GameEffect):
    """Deal ``amount`` damage to a target player or creature — or, with
    ``selector`` set, to *every* object/player a closed vocabulary names
    (RULE 601.2c "each creature"/"each player"/"each opponent" — a mass
    effect, not a RULE 115 target, so it carries no ``target_spec`` at all,
    the same untargeted-group shape `PumpEffect.selector` uses).
    """

    def __init__(
        self,
        amount: int,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "any",
        selector: Optional[str] = None,
        optional: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
        colors: Optional[list[str]] = None,
        divided: bool = False,
        double_at: Optional[int] = None,
        amount_if_kicked: Optional[int] = None,
        amount_if_bargained: Optional[Union[int, str]] = None,
        double_if_bargained: bool = False,
        amount_if_target_color: Optional[tuple[Union[int, str], list[str]]] = None,
        amount_if_cast_from_exile: Optional[int] = None,
        x_multiplier: Optional[int] = None,
        amount_from_noncreature_spells_cast_this_turn: bool = False,
        amount_from_count_selector: Optional[str] = None,
        amount_plus_count_selector: int = 0,
        amount_from_trigger_event: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self._base_amount = amount
        #: "Imodane deals that much damage to each opponent." — the event
        #: field name to read off `GameContext.trigger_event` at
        #: resolution, the same idiom `LoseLifeEffect.amount_from_trigger_
        #: event` already uses. Overrides everything else when set.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "X is 2 plus the number of cards in your graveyard that are
        #: instant cards, sorcery cards, and/or have an Adventure."
        #: (Frantic Firebolt) — a live `continuous.count_selector` read,
        #: scoped to this effect's own controller, resolved once at
        #: `apply()` time (there's no announced ``{X}`` to substitute —
        #: this card's mana cost carries no X at all, so the value is
        #: purely a resolve-time computation, not RULE 107.3c's X).
        #: ``amount_plus_count_selector`` is the flat addend ("2 plus …").
        self.amount_from_count_selector = amount_from_count_selector
        self.amount_plus_count_selector = amount_plus_count_selector
        #: "If this spell was bargained, it deals twice X damage to that
        #: permanent instead." (Stonesplitter Bolt) / "…instead it deals 3
        #: damage…" (Torch the Tower) — RULE 702.157's own `GameObject.
        #: bargained` flag (already stamped at cast time for any spell
        #: printing the Bargain keyword), the same *override*-not-additive
        #: shape `amount_if_kicked` uses. ``double_if_bargained`` is the
        #: "twice X" phrasing specifically (X isn't known until resolution,
        #: so a fixed override number can't express it); a plain
        #: ``amount_if_bargained`` int/``"x"`` covers every other phrasing.
        self.amount_if_bargained = amount_if_bargained
        self.double_if_bargained = double_if_bargained
        #: "It deals 5 damage instead if that target is white and/or
        #: blue." (Lithomantic Barrage) — ``(override_amount, [colors])``;
        #: checked per resolved target against `GameObject.colors`, since
        #: (unlike every other conditional here) this one can vary target
        #: to target rather than being a single flat override.
        self.amount_if_target_color = amount_if_target_color
        # RULE 702.33b's *override* kicked-conditional ("~ deals 2 damage to
        # any target. If this spell was kicked, it deals 4 damage instead." —
        # Burst Lightning-shaped), distinct from the *additive* "if kicked,
        # <effect>" shape `ConditionalEffect`/`EffectSpec.condition` already
        # cover — mirrors `PreventDamageEffect.amount_if_kicked` exactly, a
        # param on the effect rather than a generic wrapper since it's the
        # specific numeric param being overridden that differs per effect
        # type (amount here, a token count for `CreateTokenCopyEffect`, …).
        # A property (below) rather than resolving once in `__init__` since
        # `kicker_count` is only known once ``source`` is fully bound onto
        # the battlefield object, not necessarily yet at construction time.
        self.amount_if_kicked = amount_if_kicked
        #: "If this spell was cast from exile, it deals 5 damage … instead."
        #: (Delayed Blast Fireball) — `GameObject.cast_from_exile`, the
        #: same override-not-additive shape `amount_if_kicked`/
        #: `amount_if_bargained` use.
        self.amount_if_cast_from_exile = amount_if_cast_from_exile
        #: "When ~ enters, it deals X damage to each creature." (Spiteful
        #: Banditry-shaped ETB) — `AddCountersEffect.x_multiplier`'s own
        #: sibling: a self-only ETB trigger reading the source's own
        #: announced {X} (`GameObject.x_paid`), unlike `_substitute_x`'s
        #: ``"x"`` sentinel (spell-resolution-only, no `StackItem.x` exists
        #: for a separately-fired triggered ability to read).
        self.x_multiplier = x_multiplier
        #: "~ deals damage to that player equal to the number of
        #: noncreature spells they've cast this turn." (Magebane Lizard) —
        #: `LoseLifeEffect.amount_from_spells_cast_this_turn`'s own
        #: sibling, reading `GameState.noncreature_spells_cast_this_turn`
        #: for the event's own caster instead of a flat multiplier.
        self.amount_from_noncreature_spells_cast_this_turn = amount_from_noncreature_spells_cast_this_turn
        self.target = target
        self.selector = selector if selector in _DAMAGE_SELECTORS else None
        # RULE 601.2d: a *divided* damage spell splits its total ``amount``
        # (typically {X}) among the chosen targets — "N damage divided as you
        # choose among …" (Fire Covenant, Shatterskull Smashing) — rather than
        # dealing the full amount to each (``count`` > 1's default). The "as
        # you choose" split is UI-less here: the total is distributed as
        # evenly as possible across whatever targets were chosen (an explicit
        # ``division`` list, if a caller sets one, wins) — a documented
        # simplification (the total dealt, and which permanents take damage,
        # are exactly right; only the player's freedom to lump it unevenly is
        # auto-made). ``double_at`` is Shatterskull's "if X is 6 or more,
        # deals twice X … instead" (RULE 107.3) — the pool doubles once the
        # resolved amount reaches that threshold.
        self.divided = divided
        self.double_at = double_at
        self.division: Optional[list[int]] = None
        if self.selector is None:
            # Damage targets "any target" by default (RULE 115.4); a card
            # that only hits creatures can narrow this to "creature".
            # ``optional`` is RULE 115.1a "up to one/N target(s)" — fewer
            # than ``count`` (including zero) is then a legal choice, so
            # casting is never locked on it. ``count`` > 1 is "to each of
            # up to N target X" (Volcanic Salvo-shaped) — the full amount
            # applies to *every* chosen target, not divided among them.
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max,
                colors=tuple(colors) if colors else None,
            )

    @property
    def amount(self) -> Union[int, str]:
        if self.x_multiplier is not None:
            x_paid = getattr(self.source, "x_paid", 0) or 0
            return self.x_multiplier * x_paid
        kicker_count = getattr(self.source, "kicker_count", 0) or 0
        if self.amount_if_kicked is not None and kicker_count > 0:
            return self.amount_if_kicked
        if self.amount_if_cast_from_exile is not None and getattr(self.source, "cast_from_exile", False):
            return self.amount_if_cast_from_exile
        if getattr(self.source, "bargained", False):
            if self.double_if_bargained:
                base = self._base_amount
                return base * 2 if isinstance(base, int) else base
            if self.amount_if_bargained is not None:
                return self.amount_if_bargained
        return self._base_amount

    def _amount_for(self, target: Any, context: Optional["GameContext"] = None) -> Union[int, str]:
        """``self.amount``, further narrowed by ``amount_if_target_color``
        for this specific ``target`` (see its docstring)."""
        amount = self.amount
        if self.amount_from_trigger_event and context is not None:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
        if self.amount_from_count_selector and context is not None:
            from . import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            amount = self.amount_plus_count_selector + continuous.count_selector(
                context.state, controller_id, self.amount_from_count_selector, source=self.source,
            )
        if self.amount_if_target_color is not None:
            override, colors = self.amount_if_target_color
            target_colors = {str(c).upper() for c in (getattr(target, "colors", None) or set())}
            if target_colors & {str(c).upper() for c in colors}:
                return override
        return amount

    @amount.setter
    def amount(self, value: Union[int, str]) -> None:
        # `RulesEngine.resolve_top_of_stack`'s `_substitute_x` rewrites a
        # spell's own "x" sentinel to the announced X in place via plain
        # `setattr` — kept writable (onto `_base_amount`, not a fixed value)
        # so that substitution still composes with `amount_if_kicked`
        # exactly as an X-kicker spell's base amount would.
        self._base_amount = value

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            self._apply_selector(context)
            return
        chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
        if self.divided:
            self._apply_divided(context, chosen)
            return
        # "targets only a single creature" (Imodane, the Pyrohammer) is a
        # property of *this effect's own* target_spec, not of the damage in
        # general — computed here, where that shape is known, and carried
        # onto the DAMAGE event by `RulesEngine.deal_damage`.
        single_target_hint = (
            self.selector is None and self.target_spec is not None
            and self.target_spec.count == 1 and not self.target_spec.optional
        )
        for target in chosen:
            context.deal_damage(
                target, self._amount_for(target, context), self.source,
                single_target_hint=single_target_hint,
            )

    def _apply_divided(self, context: GameContext, targets: list[Any]) -> None:
        """Split the pool across ``targets`` (RULE 601.2d) — see ``divided``."""
        if not targets:
            return
        total = self.amount if isinstance(self.amount, int) else 0
        if self.double_at is not None and total >= self.double_at:
            total *= 2  # RULE 107.3: "deals twice X … instead"
        if self.division is not None and len(self.division) == len(targets):
            amounts = [int(a) for a in self.division]
        else:
            base, extra = divmod(total, len(targets))
            amounts = [base + (1 if i < extra else 0) for i in range(len(targets))]
        for target, amount in zip(targets, amounts):
            if amount > 0:
                context.deal_damage(target, amount, self.source)

    def _apply_selector(self, context: GameContext) -> None:
        # "Imodane deals that much damage to each opponent." — the mass-
        # selector sibling of `_amount_for`'s single-target read: `self.
        # amount` (the property below) takes no `context`, so the
        # trigger-event override is resolved into a local here instead,
        # once, and threaded through every `context.deal_damage` call this
        # method makes below (shadowing `self.amount` reads inline rather
        # than mutating shared state, since this effect instance is reused
        # across every future firing of the same permanent's ability).
        amount = self.amount
        if self.amount_from_trigger_event:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
        if self.amount_from_count_selector:
            # "it deals damage to each opponent equal to your devotion to
            # red." (Fanatic of Mogis) — `_amount_for`'s own read, needed
            # here too since the mass-selector path never calls that method.
            from . import continuous  # avoid the continuous↔effects import cycle

            controller_id_for_amount = getattr(self.source, "controller_id", None)
            amount = self.amount_plus_count_selector + continuous.count_selector(
                context.state, controller_id_for_amount, self.amount_from_count_selector, source=self.source,
            )
        if self.amount_from_noncreature_spells_cast_this_turn:
            caster = _event_player(context, key="player_id")
            amount = context.state.noncreature_spells_cast_this_turn.get(getattr(caster, "id", None), 0)
        if self.selector == "defending_player":
            # Simian Sling's "it deals 1 damage to defending player" — the
            # same per-firing dynamic-defender resolution afflict's
            # `LoseLifeEffect` selector uses (`_defending_player_of`), just
            # dealing damage instead of a direct life loss.
            player = _defending_player_of(self.source, context)
            if player is not None:
                context.deal_damage(player, amount, self.source)
            return
        if self.selector in ("each_creature", "each_creature_and_player", "each_creature_and_planeswalker"):
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            for obj in group_selector_objects(context.state, None, "all_creatures"):
                context.deal_damage(obj, amount, self.source)
            if self.selector == "each_creature_and_planeswalker":
                # A creature that's *also* a planeswalker (rare, but real —
                # RULE 205.2 multi-type permanents) was already hit above;
                # excluding ``is_creature`` here is what keeps it a single
                # hit, not two.
                for obj in context.state.permanents():
                    if obj.is_planeswalker and not obj.is_creature:
                        context.deal_damage(obj, amount, self.source)
                return
            if self.selector == "each_creature":
                return
        controller_id = getattr(self.source, "controller_id", None)
        if self.selector == "controller":
            # "it deals 1 damage to **you**" (Mana Vault) — the source's own
            # controller, and only them.
            player = _controller_of(self.source, context)
            if player is not None:
                context.deal_damage(player, amount, self.source)
            return
        if self.selector == "self":
            # "~ deals 1 damage to itself." (Stuffy Doll)
            if self.source is not None:
                context.deal_damage(self.source, amount, self.source)
            return
        if self.selector == "active_player":
            player = context.state.active_player
            if player is not None:
                context.deal_damage(player, amount, self.source)
            return
        if self.selector == "event_player":
            # "whenever a player casts a spell, ~ deals 2 damage to that
            # player." (Spellshock) — the caster named by the SPELL_CAST
            # event that fired this trigger, read via the same
            # `_event_player` helper `PayCostThenEffect` uses.
            player = _event_player(context, key="player_id")
            if player is not None:
                context.deal_damage(player, amount, self.source)
            return
        if self.selector == "event_controller":
            # "Whenever a land enters, ~ deals N damage to that land's
            # controller." (Zo-Zu the Punisher) — see `_DAMAGE_SELECTORS`'
            # own docstring for why this differs from ``event_player``.
            player = _event_player(context)
            if player is not None:
                context.deal_damage(player, amount, self.source)
            return
        if self.selector == "each_creature_controller":
            # "Each creature deals 1 damage to its controller." (Rakdos
            # Charm) — snapshot the list first: a creature's own damage can
            # kill its controller's other creatures via state-based actions
            # mid-loop, which must not skip or reorder anyone still owed a
            # hit.
            for obj in list(context.state.battlefield):
                if not obj.is_creature:
                    continue
                owner = context.state.player_by_id(obj.controller_id)
                if owner is not None:
                    context.deal_damage(owner, amount, obj)
            return
        if self.selector in (
            "each_opponent_and_their_creatures", "each_opponent_and_their_creatures_and_planeswalkers",
        ):
            # Snapshot first (same reasoning as `each_creature_controller`
            # above): an opponent's own creature dying to this damage must
            # not skip a later opponent's still-owed hit.
            for obj in list(context.state.battlefield):
                if obj.controller_id == controller_id or obj.controller_id is None:
                    continue
                if obj.is_creature or (
                    self.selector == "each_opponent_and_their_creatures_and_planeswalkers"
                    and obj.is_planeswalker
                ):
                    context.deal_damage(obj, amount, self.source)
            for player in context.state.living_players():
                if player.id != controller_id:
                    context.deal_damage(player, amount, self.source)
            return
        excluded_recipient = None
        if self.selector == "each_other_opponent":
            event = context.trigger_event or {}
            excluded_recipient = event.get("target_id")
        for player in context.state.living_players():
            if self.selector in ("each_opponent", "each_other_opponent") and player.id == controller_id:
                continue
            if player.id == excluded_recipient:
                continue
            context.deal_damage(player, amount, self.source)


#: `DrawCardEffect`'s ``count_selector`` vocabulary — a per-object dynamic
#: draw count (RULE 601.2c-style variable amount), the same "count instead
#: of a flat number" shape `continuous._pt_mod_count` uses for a per-count
#: anthem. Wyleth, Soul of Steel's "draw a card for each Aura and Equipment
#: attached to it"; ``"opponents_you_have"`` (Struggle for Project Purity's
#: Brotherhood mode: "each opponent draws a card. You draw a card for each
#: card drawn this way.") approximates "cards drawn this way" as the
#: opponent count — exact whenever nothing prevented an opponent's draw,
#: the same "auto-resolve the common case" simplification `ProliferateEffect`/
#: `SacrificeEffect` already use elsewhere in this engine.
_DRAW_COUNT_SELECTORS: frozenset[str] = frozenset(
    {
        "auras_and_equipment_attached_to_self", "opponents_you_have", "burden_counters_on_self",
        # "Target player draws cards equal to half the number of cards in
        # their library… Round up." (MEC-43 round 2, Peer into the Abyss)
        # — read off the *resolved drawing player's own* library, not the
        # ability's controller (`amount_from_half_own_life`'s sibling for
        # "half your life" is always the caster; this one is always
        # whoever the target/`player` param resolves to).
        "half_target_library_round_up",
    }
)


def _attached_auras_and_equipment_count(context: GameContext, source: Optional["GameObject"]) -> int:
    if source is None:
        return 0
    return sum(
        1 for o in context.state.battlefield
        if o.attached_to == source.instance_id
        and ("aura" in o.card.type_line.lower() or "equipment" in o.card.type_line.lower())
    )


class DrawIfTriggerObjectGreatestPowerEffect(GameEffect):
    """"…its controller may draw a card if its power is greater than each
    other creature's power." (Selvala, Heart of the Wilds, MEC-43) — "its"
    (RULE 603.1) is the firing `EventType.ENTERS_BATTLEFIELD` event's own
    object, not a fixed subject; the comparison is a strict "greater than
    **each** other creature" (a tie with even one other creature
    disqualifies it), re-evaluated live off the board at resolution rather
    than snapshotted at trigger time.

    **Documented simplification**: "may" is read as unconditional, the same
    accepted convention every other untargeted "you may" trigger with no
    real downside to declining already gets in this engine.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event or {}
        instance_id = event.get("instance_id")
        obj = context.state.find_object(instance_id) if instance_id is not None else None
        if obj is None or not obj.is_creature:
            return
        power = obj.power or 0
        others = [o for o in context.state.permanents() if o.is_creature and o is not obj]
        if any((o.power or 0) >= power for o in others):
            return
        if not obj.controller_id:
            return
        try:
            player = context.state.player_by_id(obj.controller_id)
        except (KeyError, ValueError):
            return
        context.draw(player, 1)


class DrawCardEffect(GameEffect):
    """Draw ``count`` cards for the effect's controller (or a target player)
    — or, with ``count_selector`` set, a per-object dynamic count instead of
    a flat number (Wyleth, Soul of Steel's "draw a card for each Aura and
    Equipment attached to it"). ``selector="each_player"``/``"each_opponent"``
    (Struggle for Project Purity's Brotherhood mode: "each opponent draws a
    card") is instead a mass, untargeted draw for every matching living
    player — mirrors `AddPlayerCountersEffect.selector`'s shape.
    """

    def __init__(
        self,
        count: int = 1,
        player: Any = None,
        source: Optional["GameObject"] = None,
        count_selector: Optional[str] = None,
        target_kind: Optional[str] = None,
        selector: Optional[str] = None,
        amount_from_count_selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.player = player
        self.count_selector = count_selector if count_selector in _DRAW_COUNT_SELECTORS else None
        #: "draw X cards, where X is the number of `<noun phrase>` you
        #: control." (MEC-27's own draw-verb-family gap — Intelligence
        #: Bobblehead-shaped) — the full `continuous.count_selector`
        #: vocabulary (`subgrammars.DEVOTION`), unlike `count_selector`
        #: above's small fixed whitelist; mirrors `LoseLifeEffect.
        #: amount_from_count_selector`'s own "always read as you" scoping.
        self.amount_from_count_selector = amount_from_count_selector
        self.selector = selector if selector in ("each_player", "each_opponent") else None
        # "Target player draws N cards" (Sign in Blood-shaped) — a genuine
        # RULE 115 target, unlike the untargeted default (most draw effects
        # just draw for their own controller).
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector in ("each_player", "each_opponent"):
            controller_id = getattr(self.source, "controller_id", None)
            for p in context.state.living_players():
                if self.selector == "each_opponent" and p.id == controller_id:
                    continue
                context.draw(p, self.count)
            return
        # Like `GainLifeEffect`/`LoseLifeEffect`: only consume the shared
        # `targets` list when this effect actually declared a target_spec
        # of its own (`target_kind` set) — otherwise a `targets[0]` left
        # over from a *different* targeting effect in the same resolution
        # (Deathrite Shaman-shaped "Exile target creature card... Draw a
        # card.", or a delayed trigger that inherited its arming
        # resolution's own targets) would silently get handed to
        # `RulesEngine.draw` as if it were a chosen player.
        player = self.player
        if player is None and self.target_spec is not None and targets:
            player = targets[0]
        if player is None:
            player = _controller_of(self.source, context)
        count = self.count
        if self.count_selector == "auras_and_equipment_attached_to_self":
            count = _attached_auras_and_equipment_count(context, self.source)
        elif self.count_selector == "opponents_you_have":
            controller_id = getattr(self.source, "controller_id", None)
            count = sum(1 for p in context.state.living_players() if p.id != controller_id)
        elif self.count_selector == "burden_counters_on_self":
            # "…draw a card for each burden counter on The One Ring." — read
            # *after* this same activation's own ``add_counters`` effect has
            # already placed this turn's counter (RULE 608.2b, effects in
            # printed order), so the count includes it.
            counters = getattr(self.source, "counters", None) or {}
            count = int(counters.get("burden", 0))
        elif self.count_selector == "half_target_library_round_up":
            library = len(getattr(player, "library", None) or [])
            count = -(-library // 2)  # ceiling division (RULE 107.3 rounds up)
        elif self.amount_from_count_selector:
            from . import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            count = continuous.count_selector(
                context.state, controller_id, self.amount_from_count_selector, source=self.source,
            )
        context.draw(player, count)


class SylvanLibraryEffect(GameEffect):
    """"At the beginning of your draw step, you may draw two additional
    cards. If you do, choose two cards in your hand drawn this turn. For
    each of those cards, pay 4 life or put the card on top of your
    library." (Sylvan Library, MEC-40)

    The whole ability's own `TriggeredAbility.optional=True` already models
    the "you may draw" gate (declining draws nothing, so there's nothing
    left to choose from afterward) — this effect is the "if you do"
    continuation: draw ``count`` more, then hand the *specific just-drawn
    objects* to `RulesEngine.request_pay_life_or_return_to_library`'s own
    sequential per-card chooser.

    **Documented simplification**: doesn't offer a genuine "choose which
    two" decision when more than ``count`` cards were drawn this turn (a
    second simultaneous draw effect, rare) — always processes the most
    recently drawn ``count`` (`GameState.cards_drawn_this_turn_ids`), which
    is always exactly this ability's own two in the overwhelming common
    case (nothing else draws in the same window).
    """

    def __init__(
        self, life: int = 4, count: int = 2, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.life = life
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.draw(player, self.count)
        drawn_ids = set(
            context.state.cards_drawn_this_turn_ids.get(player.id, [])[-self.count:]
        )
        objs = [o for o in player.hand if o.instance_id in drawn_ids]
        context.engine.request_pay_life_or_return_to_library(player, objs, amount=self.life)


class RevealTopConditionalToHandEffect(GameEffect):
    """RULE 701.28's reveal, with a card-type-conditional move to hand
    (Goblin Guide-shaped): a player reveals the top card of their library;
    if it matches ``card_type``, that same player puts it into their hand
    — otherwise it's simply left on top (RULE 701.28's reveal has no
    mechanical weight of its own beyond the visibility, so "no match" does
    nothing rather than needing an explicit "leave it there" clause).

    ``whose="defending_player"`` (this card's only real use so far) reads
    RULE 506.4's per-firing attack defender via `_defending_player_of` —
    who's defending is only known once combat is declared, so it can't be
    a fixed target chosen at cast/trigger time the way an ordinary "target
    player" clause would be.
    """

    def __init__(
        self,
        whose: str = "defending_player",
        card_type: str = "land",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.whose = whose
        self.card_type = card_type

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.whose == "defending_player":
            player = _defending_player_of(self.source, context)
        else:
            player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        checks = {
            "land": top.is_land,
            "creature": top.is_creature,
            "artifact": bool(top.card.is_artifact),
            "permanent": bool(
                top.is_land or top.is_creature or top.card.is_artifact
                or top.card.is_enchantment or top.is_planeswalker
            ),
        }
        if not checks.get(self.card_type, False):
            return
        player.library.pop()
        player.add_to_zone(top, Zone.HAND)


class DiscardEffect(GameEffect):
    """Make a player discard ``count`` cards — an interactive choice (RULE
    701.8: the discarding player, not this effect's controller, picks which
    cards), the looting-shaped template ("draw a card, then discard a
    card") shares with a directly-targeted forced discard (Mind Rot).

    ``target_kind="player"`` ("target player/opponent discards N cards")
    opts into a real RULE 115 target, exactly as `GainLifeEffect`'s own
    ``target_kind`` does — and for the same reason: without a declared
    `target_spec` this effect must *not* read ``targets[0]``, since any
    targets present would belong to a different effect on the same
    ability. ``scope`` ("each_player"/"each_opponent") is the untargeted
    mass form (RULE 601.2c), which hits everyone rather than one pick.
    """

    def __init__(
        self,
        count: int = 1,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        self.scope = scope

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.scope:
            controller = _controller_of(self.source, context)
            for other in context.state.living_players():
                if self.scope == "each_opponent" and other is controller:
                    continue
                context.discard_choice(other, self.count)
            return
        player = self.player
        if player is None and self.target_spec is not None and targets:
            player = targets[0]
        if player is None:
            player = _controller_of(self.source, context)
        context.discard_choice(player, self.count)


class RevealHandChooseDiscardEffect(GameEffect):
    """RULE 119/701.8's iconic hand-disruption template — "Target opponent
    reveals their hand. You choose a `<filter>` card from it. That player
    discards that card." (Duress/Thoughtseize/Coercion/Distress-shaped,
    one of the most repeated templates in the cache).

    "Reveals their hand" isn't a separate step to model (RULE 701.13's
    reveal is a zero-effect visibility action, and this engine has no
    client-visibility layer to update mid-resolution anyway) — the real
    behaviour is that the *chooser* is this effect's controller (the
    caster), not the revealed hand's owner, over that owner's *actual*
    cards. That's exactly `RulesEngine.request_choose_objects`'s shape
    (Tevesh Szat's sacrifice, Cloudstone Curio's bounce, …), just sourced
    from a hand instead of the battlefield, with its pre-existing
    ``action="discard"`` (`_apply_chosen_object` already resolves that
    against the *object's own owner*, regardless of who's choosing).

    ``exclude_land``/``exclude_creature`` are RULE 601.2c "non-X" card-type
    exclusions (composing — Duress's "noncreature, nonland" sets both);
    ``card_types`` is the inclusive opposite ("a creature or planeswalker
    card" — Despise-shaped). No filter at all (Coercion's bare "a card")
    leaves both unset and ``card_types`` `None`.

    ``max_mana_value`` (MEC-43 round 2, Inquisition of Kozilek — "…a
    nonland card from it with mana value 3 or less…") narrows the
    candidate pool further, same "card's own printed `converted_mana_cost`"
    read every other mana-value filter in this file uses.
    """

    def __init__(
        self,
        target_kind: str = "player",
        target: Any = None,
        source: Optional["GameObject"] = None,
        exclude_land: bool = False,
        exclude_creature: bool = False,
        card_types: Optional[list[str]] = None,
        max_mana_value: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind)
        self.target = target
        self.exclude_land = exclude_land
        self.exclude_creature = exclude_creature
        self.card_types = card_types
        self.max_mana_value = max_mana_value

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def _matches(self, obj: "GameObject") -> bool:
        card = obj.card
        if self.exclude_land and obj.is_land:
            return False
        if self.exclude_creature and obj.is_creature:
            return False
        if self.card_types:
            checks = {
                "creature": obj.is_creature,
                "planeswalker": bool(getattr(obj, "is_planeswalker", False)),
                "artifact": bool(card.is_artifact),
                "instant": bool(card.is_instant),
                "sorcery": bool(card.is_sorcery),
                "enchantment": bool(card.is_enchantment),
            }
            if not any(checks.get(t, False) for t in self.card_types):
                return False
        if self.max_mana_value is not None and (card.converted_mana_cost or 0) > self.max_mana_value:
            return False
        return True

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = _chosen_targets(targets, 1, self.target)
        if not chosen:
            return
        revealed_player = chosen[0]
        caster = _controller_of(self.source, context)
        if caster is None:
            return
        candidates = [obj for obj in revealed_player.hand if self._matches(obj)]
        context.choose_objects(caster, candidates, "discard", count=1, source=self.source)


class PutHandCardsOnTopEffect(GameEffect):
    """"Put N cards from your hand on top of your library in any order"
    (Brainstorm's back half — the same loot-shaped template other
    draw-then-filter cards this pool doesn't need yet would share). See
    `RulesEngine.put_hand_cards_on_top` for why the missing "any order"
    choice is inert at this engine's fidelity.
    """

    def __init__(self, count: int = 1, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.put_hand_cards_on_top(player, self.count)


class PutHandCardOnBottomThenDrawEffect(GameEffect):
    """"You may put a card from your hand on the bottom of your library. If
    you do, draw a card." (Volcanic Spite) — see `RulesEngine.put_hand_card_
    on_bottom_then_draw` for why the "may" is auto-taken.
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.put_hand_card_on_bottom_then_draw(player)


#: RULE 601.2c mass "destroy/exile all X" selectors (Wrath of God/Citywide
#: Bust/Farewell-shaped board wipes) — untargeted, unlike every RULE 115
#: target form above, so `DestroyEffect`/`ExileEffect` skip `target_spec`
#: entirely when one of these is set, mirroring `DealDamageEffect.selector`.
_MASS_DESTROY_SELECTORS: frozenset[str] = frozenset(
    {
        "all_creatures", "all_artifacts", "all_enchantments", "all_permanents",
        "all_planeswalkers", "all_lands",
        # "return all nonland permanents with mana value X or less to their
        # owners' hands." (Displacement Wave) — `ReturnToHandEffect`'s own
        # mass-bounce sibling of the destroy/exile board wipes above.
        "all_nonland_permanents",
        # "return all blue creatures your opponents control to their
        # owners' hands." (Llawan, Cephalid Empress, MEC-43) — the
        # opponent-scoped sibling of ``all_creatures``, combined with the
        # new ``color`` ``filt`` key below rather than a wider single-word
        # scope, since no other card here needs "opponents' creatures"
        # alone yet.
        "opponents_creatures",
    }
)


def _mass_selector_objects(
    context: GameContext, selector: str, filt: Optional[dict[str, Any]] = None,
    source: Optional["GameObject"] = None,
) -> list[Any]:
    """The battlefield objects a mass "all X [with condition]" selector
    picks — a snapshot list (the caller destroys/exiles each in turn, which
    mutates ``state.battlefield`` as it goes; iterating this separate list
    keeps that safe). ``filt`` is a small closed vocabulary of optional
    numeric conditions, all AND-combined: ``min_toughness``/``max_mana_
    value``/``min_mana_value`` (Citywide Bust/Austere Command-shaped), plus
    ``color`` (MEC-43, Llawan — a single WUBRG letter, checked against each
    candidate's `GameObject.colors`). ``source`` is only needed by the
    ``"opponents_creatures"`` selector, to know whose opponents.
    """
    # RULE 702.26c: a phased-out permanent is treated as though it doesn't
    # exist — a board wipe leaves it untouched.
    battlefield = context.state.permanents()
    if selector == "all_creatures":
        result = [o for o in battlefield if o.is_creature]
    elif selector == "all_artifacts":
        result = [o for o in battlefield if o.card.is_artifact]
    elif selector == "all_enchantments":
        result = [o for o in battlefield if o.card.is_enchantment]
    elif selector == "all_planeswalkers":
        result = [o for o in battlefield if getattr(o, "is_planeswalker", False)]
    elif selector == "all_permanents":
        result = list(battlefield)
    elif selector == "all_lands":
        result = [o for o in battlefield if o.card.is_land]
    elif selector == "all_nonland_permanents":
        result = [o for o in battlefield if not o.card.is_land]
    elif selector == "opponents_creatures":
        controller_id = getattr(source, "controller_id", None)
        result = [
            o for o in battlefield
            if o.is_creature and controller_id is not None and o.controller_id != controller_id
        ]
    else:
        result = []
    if filt:
        color = filt.get("color")
        if color:
            result = [o for o in result if str(color).upper() in (o.colors or set())]
        min_toughness = filt.get("min_toughness")
        if min_toughness is not None:
            result = [o for o in result if (o.toughness or 0) >= min_toughness]
        max_mv = filt.get("max_mana_value")
        if max_mv is not None:
            result = [o for o in result if o.card.converted_mana_cost <= max_mv]
        min_mv = filt.get("min_mana_value")
        if min_mv is not None:
            result = [o for o in result if o.card.converted_mana_cost >= min_mv]
        # "destroy all creatures with power 3 or greater" (Dusk // Dawn/The
        # Battle of Bywater-shaped) — the power-threshold sibling of
        # ``min_toughness`` above.
        min_power = filt.get("min_power")
        if min_power is not None:
            result = [o for o in result if (o.power or 0) >= min_power]
        max_power = filt.get("max_power")
        if max_power is not None:
            result = [o for o in result if (o.power or 0) <= max_power]
        # "destroy all nonbasic lands." (Ruination-shaped) — paired with
        # ``selector="all_lands"`` rather than its own selector, the same
        # "selector picks the zone/type, filter narrows it" split every
        # other mass-wipe qualifier here uses.
        if filt.get("nonbasic"):
            result = [o for o in result if "basic" not in (o.card.type_line or "").lower()]
        subtype = filt.get("subtype")
        if subtype:
            # "exile all Nightmares." (MEC-43 round 2, Chainer, Dementia
            # Master) — delegates to `combat.matches_object_filter`'s own
            # subtype check rather than a bare type-line read, since the
            # subtype here is often *granted* (Chainer's own reanimated
            # creatures), not printed.
            from . import combat  # local: avoid the combat<->effects import cycle

            result = [o for o in result if combat.matches_object_filter(o, {"subtype": subtype})]
    return result


def _chosen_targets(targets: Optional[list[Any]], count: int, target: Any = None) -> list[Any]:
    """RULE 115.1a "up to N target(s)" resolution: only this effect's own
    ``count`` targets, off the front of a possibly-shared list — a stack
    item's ``targets`` list is shared by every effect on it, so a
    single-target effect (``count=1``, the default) must not swallow entries
    meant for something else sharing the same cast. Falls back to an
    explicit single ``target`` (a resolve-time pronoun/self reference) only
    when no shared list was supplied at all. Shared by `DestroyEffect`,
    `ExileEffect`, `ReturnToHandEffect`, `ReturnFromGraveyardEffect`,
    `TapEffect`, `AddCountersEffect` and `DealDamageEffect`, which otherwise
    each reimplemented this identically.
    """
    if targets:
        return targets[:count]
    return [target] if target is not None else []


class DestroyEffect(GameEffect):
    """Destroy a target permanent — or, with ``count`` > 1, every one of a
    fixed/"up to N" set of chosen target permanents (RULE 115.1a
    generalized to N>=2 — "destroy two target creatures"/"destroy up to two
    target artifacts and/or enchantments") — or, with ``selector`` set, a
    mass "destroy all X [with condition]" board wipe (RULE 601.2c, untargeted,
    same shape as `DealDamageEffect.selector`). ``can_be_regenerated=False``
    is Wrath of God's "They can't be regenerated." tail. ``max_mana_value``
    is Abrupt Decay-shaped "target nonland permanent with mana value 3 or
    less" — a target-offer-time cap (`targeting.TargetSpec.max_mana_value`),
    not a resolve-time check. ``creature_filter`` is the power/toughness/
    keyword quality filter (`targeting.TargetSpec.creature_filter`,
    "destroy target creature with power 4 or greater"/"…with flying"-shaped)
    — a different, orthogonal narrowing from ``filter`` above (which only
    ever applies to the untargeted ``selector`` mass-wipe path).

    ``distinct_controllers`` (Run Away Together/Protector of the Wastes-
    shaped "N target creatures/permanents controlled by **different
    players**") is `targeting.TargetSpec.distinct_controllers` — see its
    docstring; only meaningful with ``count >= 2``.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        optional: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        can_be_regenerated: bool = True,
        color: Optional[str] = None,
        max_mana_value: Optional[int] = None,
        creature_filter: Optional[dict[str, Any]] = None,
        distinct_controllers: bool = False,
        exclude_created: bool = False,
        target_from_trigger_event: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.selector = selector if selector in _MASS_DESTROY_SELECTORS else None
        self.filter = filter
        self.can_be_regenerated = can_be_regenerated
        #: "Whenever a Human deals damage to you, destroy it." (Mikaeus,
        #: the Unhallowed) — "it" is the *source* of the very DAMAGE event
        #: that fired this trigger (a group-subject trigger, so there's no
        #: single chosen creature to fall back on the way a self-subject
        #: "when ~ deals damage" trigger's implicit "it" would be) — the
        #: event field name to read off `GameContext.trigger_event` (its
        #: own ``"source_id"``), resolved fresh at apply-time since the
        #: dealer varies firing to firing. Same "read this firing's own
        #: payload" idiom `DealDamageEffect.amount_from_trigger_event` uses
        #: for a magnitude instead of an object reference.
        self.target_from_trigger_event = target_from_trigger_event
        #: "Create X tokens. If X is 5 or more, destroy all **other**
        #: creatures." (Martial Coup) — RULE 608.2's "the tokens" referent
        #: excluded from a mass wipe in the *same* resolution
        #: (`GameContext.created_objects`), the mirror image of
        #: `AttachEffect`'s ``target_kind="created"`` reading the same list.
        self.exclude_created = exclude_created
        if self.selector is None and target_from_trigger_event is None:
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max, color=color,
                max_mana_value=max_mana_value, creature_filter=creature_filter,
                distinct_controllers=distinct_controllers,
            )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_from_trigger_event:
            event = context.trigger_event or {}
            source_id = event.get(self.target_from_trigger_event)
            target = context.state.find_object(source_id) if source_id is not None else None
            if target is not None:
                context.destroy(target, can_be_regenerated=self.can_be_regenerated)
            return
        if self.selector is not None:
            excluded = set(context.created_objects) if self.exclude_created else ()
            for obj in _mass_selector_objects(context, self.selector, self.filter, source=self.source):
                if obj in excluded:
                    continue
                context.destroy(obj, can_be_regenerated=self.can_be_regenerated)
            return
        chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
        for target in chosen:
            context.destroy(target, can_be_regenerated=self.can_be_regenerated)


class RegenerateEffect(GameEffect):
    """Give a target permanent a regeneration shield (RULE 701.16).

    ``target_kind=None`` (unlike the default ``"creature"``) makes it act on
    the effect's own source with no player choice involved — "Regenerate
    ~."/"Regenerate this creature.", mirroring `TapEffect`'s self mode.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        creature_filter: Optional[dict] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = (
            TargetSpec(kind=target_kind, creature_filter=creature_filter)
            if target_kind is not None else None
        )

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None and self.target_spec is None:
            target = self.source
        if target is not None:
            context.regenerate(target)


class GainLifeEffect(GameEffect):
    """The effect's controller (or an explicitly given ``player``) gains
    ``amount`` life — untargeted by default.

    ``target_kind="player"`` (Abuna's Chant-shaped "target player gains N
    life") opts into a real RULE 115 target, mirroring `LoseLifeEffect`'s
    own ``target_kind``. Without it, this effect declares no `target_spec`
    of its own, so any ``targets`` passed to `apply` belong to a *different*
    effect on the same ability/spell (e.g. Deathrite Shaman's "Exile target
    creature card from a graveyard. You gain 2 life." — the exiled card,
    not a player) — reading `targets[0]` unconditionally would silently hand
    `RulesEngine.gain_life` a `GameObject` instead of a `Player`.
    """

    def __init__(
        self,
        amount: int = 0,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        count_selector: Optional[str] = None,
        amount_from_target_power: bool = False,
        recipient: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        self.count_selector = count_selector
        #: "You gain life equal to target creature's power." (Dazzling
        #: Reflection, MEC-30) — reads a *shared* target this effect never
        #: declares itself (no `target_spec` of its own here; a sibling
        #: clause in the same ability — its own `prevent_damage_from_target`
        #: — is what actually requests the "target creature," and
        #: `_apply_effects_partitioned` hands the same resolved `targets`
        #: list to every effect in the ability when there's only one real
        #: targeting requirement to gather, RULE 608.2). The life-gain
        #: sibling of `DealDamageEffect.amount_from_target_count_selector`.
        self.amount_from_target_power = amount_from_target_power
        #: "**That creature's controller** gains life equal to its power."
        #: (MEC-12, Solitude) — ``"target_controller"`` reads the *same*
        #: shared target `amount_from_target_power` already reads (a
        #: sibling exile clause's own target, not this effect's own), but
        #: for *who receives* the life rather than how much: without this,
        #: an effect with no `target_kind` of its own falls back to
        #: `_controller_of(self.source, ...)` — this ability's own
        #: controller, which is wrong whenever the recipient is the
        #: target's controller instead.
        self.recipient = recipient

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        subject = targets[0] if targets else None
        if player is None and self.recipient == "target_controller" and subject is not None:
            controller_id = getattr(subject, "controller_id", None)
            if controller_id is not None:
                try:
                    player = context.state.player_by_id(controller_id)
                except (KeyError, ValueError):
                    player = None
        if player is None and self.target_spec is not None:
            player = subject
        if player is None:
            player = _controller_of(self.source, context)
        amount = self.amount
        if self.amount_from_target_power:
            amount = int(subject.power or 0) if subject is not None else 0
        elif self.count_selector == "life_lost_this_way":
            # "You gain life equal to the life lost this way." (Gray
            # Merchant of Asphodel-shaped RULE 119 drain) — a per-resolution
            # accumulator (`GameContext.life_lost_this_way`), not a board
            # count, so it's read directly rather than through
            # `continuous.count_selector`'s vocabulary.
            amount = context.life_lost_this_way
        elif self.count_selector and player is not None:
            from . import continuous  # avoid the continuous↔effects import cycle

            amount = continuous.count_selector(
                context.state, player.id, self.count_selector, source=self.source
            )
        context.gain_life(player, amount)


class PreventDamageEffect(GameEffect):
    """RULE 615: "Prevent all/the next N damage that would be dealt to you
    this turn" (Riot Control's spell-level "all"; Thought Lash's own
    repeatable "the next 1") — a one-shot effect that grants its own
    controller a turn-scoped damage-prevention shield, Regenerate-shaped:
    this class just triggers `RulesEngine.prevent_damage_to_player`, which
    builds+attaches the actual `ReplacementEffect` shield (unlike
    `RegenerateEffect`'s shield, this one lives on `Player.player_effects`,
    not a permanent's `replacement_effects` — nothing is being regenerated,
    the target is always the caster/activator, never chosen).

    ``amount="all"`` prevents every point of damage the player would take
    for the rest of the turn; an int prevents a cumulative bank of that
    many points total (Thought Lash's activated ability can be paid
    multiple times, each adding to the same turn's bank).

    PAR-15's targeted sibling ("prevent the next N damage that would be
    dealt this turn to any number of targets, divided as you choose" —
    Embolden/Remedy/Angel of Salvation) sets ``target_kind`` — the pool is
    then divided (RULE 601.2d-shaped, `DealDamageEffect(divided=True)`'s
    same as-evenly-as-possible split) among whichever targets were chosen
    and each gets its own `RulesEngine.prevent_damage_to_target` shield,
    rather than the single fixed "you" shield the untargeted shape above
    grants. ``amount_if_kicked`` is Pollen Remedy's own trailing "if this
    spell was kicked, prevent the next N damage this way instead" —
    an *override*, not an addition, so it's a param on this effect rather
    than a generic kicked-conditional wrapper (RULE 702.33b already covers
    the additive "if kicked, `<effect>`" shape via `ConditionalEffect`;
    this is the narrower override some cards use instead).
    """

    def __init__(
        self,
        amount: Union[int, str] = "all",
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        target: Any = None,
        count: int = 1,
        optional: bool = False,
        divided: bool = False,
        amount_if_kicked: Optional[Union[int, str]] = None,
        self_only: bool = False,
        watched_source_is_self: bool = False,
        recipient_is_activator: bool = False,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.amount_if_kicked = amount_if_kicked
        self.divided = divided
        self.target = target
        #: "Prevent the next N damage that would be dealt to `<this
        #: permanent>` this turn." (Opal-Eye, Konda's Yojimbo, MEC-30) — the
        #: object-recipient sibling of the untargeted "…to you" default:
        #: shields this effect's own source, not its controller.
        self.self_only = self_only
        #: "The next time **this creature** would deal damage to you this
        #: turn, prevent that damage." (Mercenaries, MEC-30) — narrows the
        #: untargeted "…to you" shield to one fixed, already-known source
        #: (this effect's own source), the no-chooser-needed sibling of
        #: `RequestPreventDamageSourceEffect`'s "a source of your choice".
        self.watched_source_is_self = watched_source_is_self
        #: RULE 602.2b: "you" resolves to whoever *activated* this ability,
        #: not this permanent's own printed controller — only ever diverges
        #: from `_controller_of` under a standing `ActivationCost.any_
        #: player_may_activate` exception (Mercenaries is the only card so
        #: far). Read via `GameContext.resolving_controller_id`, falling
        #: back to `_controller_of` when unset (a direct `effect.apply()`
        #: call outside real stack resolution — tests, a fixture).
        self.recipient_is_activator = recipient_is_activator
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional, count=count)
            if target_kind is not None
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        kicker_count = getattr(self.source, "kicker_count", 0) or 0
        amount = self.amount_if_kicked if (self.amount_if_kicked is not None and kicker_count > 0) else self.amount
        if self.self_only:
            if self.source is not None:
                context.prevent_damage_to_target(self.source, amount)
            return
        if self.target_spec is None:
            player = None
            if self.recipient_is_activator and context.resolving_controller_id is not None:
                try:
                    player = context.state.player_by_id(context.resolving_controller_id)
                except (KeyError, ValueError):
                    player = None
            if player is None:
                player = _controller_of(self.source, context)
            if player is not None:
                watched_source_id = self.source.instance_id if self.watched_source_is_self and self.source is not None else None
                context.prevent_damage_to_player(player, amount, watched_source_id=watched_source_id)
            return
        chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
        if not chosen:
            return
        if self.divided:
            total = amount if isinstance(amount, int) else 0
            base, extra = divmod(total, len(chosen))
            shares = [base + (1 if i < extra else 0) for i in range(len(chosen))]
        else:
            shares = [amount] * len(chosen)
        for target, share in zip(chosen, shares):
            if share == "all" or (isinstance(share, int) and share > 0):
                context.prevent_damage_to_target(target, share)


class PreventLifeGainEffect(GameEffect):
    """RULE 119.3/616.1: "Your opponents can't gain life this turn."
    (Roiling Vortex's activated-ability rider). ``recipient`` picks who
    gets the shield — ``"opponents"`` (this effect's own controller's
    opponents, the only printed phrasing so far) — via `RulesEngine.
    prevent_life_gain_this_turn`, the absolute-cancel sibling of
    `PreventDamageEffect`'s numeric shield.
    """

    def __init__(self, recipient: str = "opponents", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.recipient = recipient

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        if self.recipient == "opponents":
            players = [p for p in context.state.living_players() if p.id != controller.id]
        else:
            players = [controller]
        if players:
            context.prevent_life_gain_this_turn(players)


class DisableDamagePreventionEffect(GameEffect):
    """RULE 615: "Damage can't be prevented this turn." (Insult //
    Injury/Isengard Unleashed, MEC-30) — untargeted, no recipient at all;
    just flips `GameState.damage_prevention_disabled` via `RulesEngine.
    disable_damage_prevention_this_turn`.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        context.disable_damage_prevention_this_turn()


class GrantDamageMultiplierThisTurnEffect(GameEffect):
    """RULE 616: "If a source you control would deal damage this turn, it
    deals double/triple that damage instead." (Insult // Injury/Isengard
    Unleashed, MEC-30) — the spell-cast sibling of `_double_damage_
    replacement`'s permanent-attached shape; see `RulesEngine.grant_damage_
    multiplier_this_turn`'s own docstring for why a separate method exists
    rather than reusing that factory directly from here.
    """

    def __init__(
        self, multiplier: int = 2, to_opponent_only: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.multiplier = multiplier
        self.to_opponent_only = to_opponent_only

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None or self.source is None:
            return
        context.grant_damage_multiplier_this_turn(
            controller, self.source, multiplier=self.multiplier,
            to_opponent_only=self.to_opponent_only,
        )


class PreventAllCombatDamageEffect(GameEffect):
    """RULE 615: "Prevent all combat damage that would be dealt this turn."
    (Fog) — deliberately a separate class from `PreventDamageEffect`
    rather than a third mode on it: that class's two modes both shield one
    resolved *recipient* (the caster, or a chosen target); this one has no
    recipient at all — every attacker's and every blocker's combat damage
    to *anyone* is prevented, for the rest of the turn, which is why it
    calls `RulesEngine.prevent_all_combat_damage_this_turn` instead of
    either of that class's per-recipient shield builders.

    ``exclude_subtype`` (Galadhrim Ambush) threads straight through to
    that method's own qualifier — see its docstring.
    """

    def __init__(
        self, source: Optional["GameObject"] = None, exclude_subtype: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.exclude_subtype = exclude_subtype

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.prevent_all_combat_damage_this_turn(player, exclude_subtype=self.exclude_subtype)


class RequestPreventDamageSourceEffect(GameEffect):
    """RULE 615/616.1d: "The next time a source of your choice [matching
    ``source_filter``] would deal damage to `<recipient>` this turn, prevent
    [half] that damage[, rounded up/down]." — the Circle of Protection/Rune
    of Protection family. Opens `RulesEngine.request_choose_objects`'s
    general chooser (a ``"remember_source"`` action) over every battlefield
    permanent matching ``source_filter`` (a `combat.matches_object_filter`-
    shaped dict — a colour, "an artifact source", a creature of an
    ETB-chosen type…), then grants a `RulesEngine.prevent_damage_to_player`/
    `_to_target`-shaped shield scoped to whichever one gets picked (RULE
    615's "next time" — self-expiring even if that source never actually
    deals damage this turn).

    Scoped to battlefield permanents only — RULE 609.7a's other two source
    kinds (a spell or an ability still on the stack) aren't offered, since
    `request_choose_objects` only ever candidates `GameObject`s already on
    the battlefield. No card in this family's real pool needs to name an
    unresolved spell/ability, so this is a deliberate, documented
    simplification rather than a silent gap.

    ``target_kind``/``target`` (Circle of Despair/Martyr's Cause/Sanctum
    Guardian's "…would deal damage to **any target** this turn") route the
    *recipient* through ordinary RULE 115 targeting instead of this effect's
    own controller — the overwhelming majority of real cards ("…would deal
    damage to **you** this turn") leave both unset, so the shield simply
    protects the caster. ``amount``/``rider`` mirror
    `_prevent_damage_replacement`'s own vocabulary (an ``int``, ``"all"``, or
    ``{"half": "up"|"down"}``; `RulesEngine.apply_prevent_rider`'s follow-up
    shape) — Deflecting Palm/Reverse Damage-shaped.
    """

    def __init__(
        self,
        source_filter: Optional[dict] = None,
        target_kind: Optional[str] = None,
        target: Any = None,
        amount: Any = "all",
        rider: Any = None,
        optional: bool = False,
        recipient: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.source_filter = dict(source_filter or {})
        self.amount = amount
        self.rider = list(rider) if isinstance(rider, list) else (dict(rider) if rider else None)
        self.optional = optional
        self.target = target
        #: "…would deal damage to **enchanted creature** this turn" (Kithkin
        #: Armor, MEC-30) — the chosen-source family's own sibling of Family
        #: A's ``to="attached_permanent"``: reads ``self.source.attached_to``
        #: instead of the caster/an RULE 115 target. Mutually exclusive with
        #: ``target_kind`` (no real card needs both).
        self.recipient = recipient
        self.target_spec = (
            TargetSpec(kind=target_kind, count=1) if target_kind is not None else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None:
            return
        player = _controller_of(src, context)
        if player is None:
            return
        # "…would deal damage to you and/or creatures you control this
        # turn" (Shadowbane, MEC-30) — a dynamic recipient *set*, not one
        # resolved object, so it skips the single-``recipient_obj``
        # resolution below entirely; `_apply_chosen_object` reads this
        # scope key straight off ``prevent_shield`` instead of a fixed id.
        # ``"any"`` (Penance, MEC-30 — "…would deal damage this turn,
        # prevent that damage.", no "to you" at all) is the same idea taken
        # further: no recipient qualifier whatsoever, so `recipient_obj`
        # legitimately stays unresolved — `RulesEngine.prevent_damage_from_
        # source`'s own unscoped shape, reached via `_apply_chosen_object`'s
        # matching branch below.
        if self.recipient == "any":
            recipient_obj = None
        elif self.recipient == "you_and_creatures_you_control":
            recipient_obj = player
        elif self.recipient == "attached_permanent":
            host_id = getattr(src, "attached_to", None)
            recipient_obj = context.state.find_object(host_id) if host_id is not None else None
        elif self.target_spec is not None:
            chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
            recipient_obj = chosen[0] if chosen else None
        else:
            recipient_obj = player
        if recipient_obj is None and self.recipient != "any":
            return
        from . import combat  # local: avoid the combat<->effects import cycle

        candidates = [
            obj for obj in context.state.battlefield
            if combat.matches_object_filter(obj, self.source_filter, reference=src)
        ]
        recipient_is_player = recipient_obj is not None and not hasattr(recipient_obj, "instance_id")
        context.engine.request_choose_objects(
            player, candidates, "remember_source", count=1, optional=self.optional,
            prompt=f"{src.name}: Quelle wählen",
            source=src,
            prevent_shield={
                "recipient_id": (
                    (recipient_obj.id if recipient_is_player else recipient_obj.instance_id)
                    if recipient_obj is not None else None
                ),
                "recipient_is_player": recipient_is_player,
                "recipient_scope": (
                    self.recipient
                    if self.recipient in ("you_and_creatures_you_control", "any")
                    else None
                ),
                "amount": self.amount,
                "rider": self.rider,
            },
        )


class RequestRedirectDamageSourceEffect(GameEffect):
    """RULE 616.1c "the next time a source of your choice would deal damage
    this turn, that damage is dealt to `<X>` instead" (Opal-Eye, Konda's
    Yojimbo, MEC-30) — `RequestPreventDamageSourceEffect`'s redirect
    sibling: opens the exact same chooser (a ``"remember_source_redirect"``
    action this time) over every battlefield permanent matching
    ``source_filter``, then grants a `RulesEngine.redirect_damage_from_
    source` shield instead of a prevention one. ``recipient="self"`` (the
    only real printed shape — "dealt to `<this permanent>` instead") reads
    this effect's own source as the new recipient.
    """

    def __init__(
        self,
        source_filter: Optional[dict] = None,
        amount: Any = "all",
        recipient: str = "self",
        optional: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.source_filter = dict(source_filter or {})
        self.amount = amount
        self.recipient = recipient
        self.optional = optional

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None:
            return
        player = _controller_of(src, context)
        if player is None:
            return
        recipient_obj: Any = src if self.recipient == "self" else None
        if recipient_obj is None:
            return
        from . import combat  # local: avoid the combat<->effects import cycle

        candidates = [
            obj for obj in context.state.battlefield
            if combat.matches_object_filter(obj, self.source_filter, reference=src)
        ]
        context.engine.request_choose_objects(
            player, candidates, "remember_source_redirect", count=1, optional=self.optional,
            prompt=f"{src.name}: Quelle wählen",
            source=src,
            redirect_shield={
                "recipient_id": recipient_obj.instance_id,
                "recipient_is_player": False,
                "amount": self.amount,
            },
        )


class ChooseSourceCoinFlipEffect(GameEffect):
    """"Choose a source you control and flip a coin. If you win the flip,
    the next time that source would deal damage this turn, it deals
    double that damage instead. If you lose the flip, the next time it
    would deal damage this turn, prevent that damage." (Desperate Gambit,
    MEC-30 — the last card of the family, closing it out.)

    Structurally the chosen-source chooser family's third member: unlike
    `RequestPreventDamageSourceEffect`/`RequestRedirectDamageSourceEffect`,
    the candidate pool is narrowed to **battlefield permanents this
    effect's own controller controls** ("a source **you control**", RULE
    609.7a — not "of your choice" over anyone's permanents), and nothing
    is decided about win/lose until the pick actually resolves — the
    ``"remember_source_coinflip"`` action flips the coin (`RulesEngine.
    coin_flip`, RULE 705.1) *at that point* and branches into `RulesEngine.
    grant_damage_multiplier_from_source` (win) or the already-shipped
    `prevent_damage_from_source` (lose), both scoped to the one chosen
    permanent. No shield payload needed on the choice itself, since the
    chosen object already carries everything both branches need.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None:
            return
        player = _controller_of(src, context)
        if player is None:
            return
        candidates = list(context.state.permanents_controlled_by(player.id))
        context.engine.request_choose_objects(
            player, candidates, "remember_source_coinflip", count=1,
            prompt=f"{src.name}: Quelle für den Münzwurf wählen",
            source=src,
        )


class PreventDamageFromTargetEffect(GameEffect):
    """RULE 615/616.1d: "The next time target creature would deal damage
    this turn, prevent that damage." (Awe Strike/Dazzling Reflection) — the
    targeted, no-chooser-needed sibling of `RequestPreventDamageSourceEffect`:
    the source is already pinned by ordinary RULE 115 targeting, so this just
    opens `RulesEngine.prevent_damage_from_source`'s unscoped-recipient
    shield directly (protects *whoever* the target would have hit, not one
    fixed recipient) — no interactive "choose a source" step needed.
    """

    def __init__(
        self,
        target_kind: str = "creature",
        target: Any = None,
        count: int = 1,
        amount: Any = "all",
        rider: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.amount = amount
        self.rider = list(rider) if isinstance(rider, list) else (dict(rider) if rider else None)
        self.target_spec = TargetSpec(kind=target_kind, count=count)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
        for obj in chosen:
            context.engine.prevent_damage_from_source(obj, self.amount, rider=self.rider)


class ExtraLandPlayEffect(GameEffect):
    """A one-shot "you may play N additional land(s) this turn" grant
    (Explore/Escape to the Wilds/Kiora's -1-shaped, RULE 305.2) — the
    resolve-time, single-turn sibling of the standing `"extra_land_drop"`
    `StaticAbility` a permanent like Exploration grants continuously
    (`game/continuous.py`'s `extra_land_plays_for`).

    Bumps the controller's `Player.extra_land_plays_this_turn` counter,
    which `GameEngine.can_play_land` adds to the per-turn cap alongside the
    standing static grant; `GameEngine.begin_turn` resets it to 0 each turn
    the same way `lands_played_this_turn` resets.
    """

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            player.extra_land_plays_this_turn += self.count


class GraveyardPlayPermissionThisTurnEffect(GameEffect):
    """"Until end of turn, you may play lands and cast spells from your
    graveyard." (Yawgmoth's Will-shaped, MEC-12) — a *player*-scoped
    standing permission, unlike `GraveyardCastPermissionEffect` (Lurrus-
    shaped), which lives on a permanent's own `static_effects` and vanishes
    the instant that permanent leaves the battlefield. The sorcery granting
    this one is already gone (to the graveyard, or — thanks to Yawgmoth's
    Will's own second clause below — exile) long before end of turn, so the
    permission is tracked on the player directly rather than scanned off a
    permanent. Stamps `Player.graveyard_play_permission_until_turn` to the
    current turn number; `game/graveyard_cast.py`'s `has_temporary_
    graveyard_play_permission` reads it back — a stamped turn number
    naturally "expires" the moment `GameState.turn_number` advances, so
    nothing needs a separate sweep. Unlike every existing graveyard-cast
    permission source, this one covers lands too.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            player.graveyard_play_permission_until_turn = context.state.turn_number


class GraveyardRedirectToExileEffect(GameEffect):
    """"If a card would be put into your graveyard from anywhere this
    turn, exile that card instead." (Yawgmoth's Will's own second clause,
    MEC-12) — the player-scoped, turn-limited sibling of
    `GraveyardCastPermissionEffect.exile_if_would_be_put_into_graveyard`'s
    per-*object* redirect (which only ever catches the one spell cast via
    its own permission): this one catches every card this player *owns*,
    from any zone, for any reason, for the rest of the turn. Stamps
    `Player.graveyard_redirect_to_exile_until_turn`, checked directly in
    `RulesEngine._move_to_graveyard` — the one choke point every
    graveyard-bound move funnels through — against whichever player owns
    the moving card, since a card only ever enters its own owner's
    graveyard (RULE 404.4/700.4), which is exactly what "your graveyard"
    means here.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            player.graveyard_redirect_to_exile_until_turn = context.state.turn_number


class ExchangeLifeTotalsEffect(GameEffect):
    """"Two target players exchange life totals." (Soul Conduit, MEC-43
    round 2) — a genuine simultaneous swap, distinct from every other life
    effect in this file (`GainLifeEffect`/`LoseLifeEffect`, both single-
    player deltas): neither player's life total is set *to* a number, each
    just receives the *other's* current one, in one atomic step so a
    same-resolution "then" clause reading either player's life sees the
    post-swap value.

    Not modeled as a gain/loss for either player (no `GAIN_LIFE`/
    `LOSE_LIFE` event fires) — an exchange is its own RULE 119 category,
    and every real card of this shape prints no "you gain/lose life"
    follow-up that would depend on one firing.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="player", count=2)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = list(targets or [])
        if len(chosen) != 2:
            return
        a, b = chosen
        a.life, b.life = b.life, a.life


#: `LoseLifeEffect`'s mass-selector vocabulary ("each opponent loses N
#: life"/"each player loses N life", RULE 601.2c) — the same closed,
#: untargeted-group shape `DealDamageEffect`'s `_DAMAGE_SELECTORS` uses (no
#: "each_creature" here — life loss never targets a creature).
_LOSE_LIFE_SELECTORS: frozenset[str] = frozenset({"each_player", "each_opponent"})


class LoseLifeEffect(GameEffect):
    """A player loses ``amount`` life (RULE 118/119) — untargeted.

    ``selector="defending_player"`` (afflict, RULE 702.130) resolves the
    player dynamically at apply-time via `_defending_player_of`, since the
    same bound ability fires against a different defender each combat;
    a plain ``player``/target keeps the shape every other simple player
    effect (`GainLifeEffect`, `DiscardEffect`) already uses.
    ``selector="each_opponent"``/``"each_player"`` (RULE 601.2c) instead
    hits every matching player, the same mass-effect shape
    `DealDamageEffect.selector` uses for "~ deals N damage to each player".
    ``selector="event_player"`` (Sheoldred, the Apocalypse's "whenever an
    opponent draws a card, **they** lose 2 life.") resolves against
    whoever the *firing event itself* names (`_event_player`, the same
    "that player" idiom `DealDamageEffect.selector` already uses for a
    damage trigger) rather than this ability's controller.

    Like `GainLifeEffect`, the plain (no-selector) path never falls back to
    a shared ``targets`` list — this effect declares no `target_spec` of
    its own, so any ``targets`` passed to `apply` belong to a *different*
    effect in the same chain (Infernal Grasp's "Destroy target creature.
    You lose 2 life.", Deathrite Shaman's exile-then-drain ability, …).
    """

    def __init__(
        self,
        amount: int = 0,
        player: Any = None,
        selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        player_id: Optional[str] = None,
        amount_from_trigger_event: Optional[str] = None,
        amount_from_life_gained_this_turn: bool = False,
        amount_from_burden_counters_on_self: bool = False,
        amount_from_count_selector: Optional[str] = None,
        amount_from_spells_cast_this_turn: bool = False,
        amount_from_half_own_life: bool = False,
        amount_from_half_target_life: bool = False,
        previous_subject: bool = False,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        #: "Target player draws cards… **and loses** half their life."
        #: (MEC-43 round 2, Peer into the Abyss) — the same player
        #: `DrawCardEffect`'s own target requirement already picked
        #: (`GameContext.previous_targets`, the "It fights…"/"Tap target
        #: land. It doesn't untap…" pronoun idiom `FightEffect`/
        #: `GrantUntilEffect` already use), not a second RULE 115 target of
        #: this effect's own — the real card only ever targets once.
        self.previous_subject = previous_subject
        #: "You lose half your life, rounded up." (MEC-37, Doomsday) —
        #: reads this effect's own controller's *current* life total at
        #: resolution (RULE 107.3 rounds up), independently of the
        #: selector/target resolution below since the real card never
        #: prints one — always the caster themself.
        self.amount_from_half_own_life = amount_from_half_own_life
        #: "Target player… loses half their life. Round up." (MEC-43
        #: round 2, Peer into the Abyss) — the *targeted* sibling of
        #: ``amount_from_half_own_life`` above: reads whichever player the
        #: ordinary target/``player``/controller resolution below picks,
        #: not always the caster.
        self.amount_from_half_target_life = amount_from_half_target_life
        #: "…each opponent loses life equal to the number of tapped
        #: creatures you control." (Throne of the God-Pharaoh) — a live
        #: `continuous.count_selector` read, scoped to this effect's own
        #: controller regardless of which player ends up losing the life
        #: (unlike `PumpEffect.amount_from_count_selector`'s board-wide
        #: reads, this one is always "you", matching every printed card
        #: of this shape).
        self.amount_from_count_selector = amount_from_count_selector
        #: "Whenever a player casts a spell, they lose 1 life for each
        #: spell they've cast this turn." (Rug of Smothering) — unlike
        #: ``amount_from_count_selector`` above (always "you", the
        #: ability's own controller), this reads `GameState.
        #: spells_cast_this_turn` for the *casting* player named by the
        #: firing `SPELL_CAST` event (``selector="event_player"``'s own
        #: ``_event_player`` lookup), including the cast that triggered
        #: this ability — `RulesEngine._track_spell_cast` increments the
        #: counter before triggers are collected off the same event.
        self.amount_from_spells_cast_this_turn = amount_from_spells_cast_this_turn
        self.player = player
        #: "…you lose 1 life for each burden counter on The One Ring."
        #: Reads `GameObject.counters["burden"]` on this effect's own
        #: source, the `LoseLifeEffect` sibling of `DrawCardEffect`'s
        #: ``"burden_counters_on_self"`` count selector.
        self.amount_from_burden_counters_on_self = amount_from_burden_counters_on_self
        #: A specific player named by *id* rather than by object — the only
        #: form a serialized `EffectSpec` can carry (Professor Onyx's
        #: per-opponent "if you don't, they lose 3 life" branch, built fresh
        #: at answer time from spec data).
        self.player_id = player_id
        self.selector = selector
        # "Target player … loses 2 life" (Sign in Blood-shaped, sharing its
        # target with a sibling `DrawCardEffect` on the same spell) — opt-in
        # only, so every existing untargeted/selector caller keeps reading
        # no shared ``targets`` list at all (see the class docstring).
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        #: "Whenever you gain life, target opponent loses that much life."
        #: (Sanguine Bond-shaped) — the event field name (``"amount"``) to
        #: read off `GameContext.trigger_event` at resolution, the same
        #: "read this firing's own payload" idiom `AddManaEffect.
        #: amount_from_trigger_event` uses. Overrides ``amount`` when set.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "…loses life equal to the amount of life you gained this turn."
        #: (Gollum, Obsessed Stalker) — `GameState.life_gained_this_turn`,
        #: a *cumulative-this-turn* total rather than one firing's payload,
        #: so unlike `amount_from_trigger_event` this reads state, not the
        #: triggering event.
        self.amount_from_life_gained_this_turn = amount_from_life_gained_this_turn

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        amount = self.amount
        if self.amount_from_trigger_event:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
        if self.amount_from_life_gained_this_turn:
            player = _controller_of(self.source, context)
            amount = context.state.life_gained_this_turn.get(getattr(player, "id", None), 0)
        if self.amount_from_burden_counters_on_self:
            counters = getattr(self.source, "counters", None) or {}
            amount = int(counters.get("burden", 0))
        if self.amount_from_count_selector:
            from . import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            amount = continuous.count_selector(
                context.state, controller_id, self.amount_from_count_selector, source=self.source,
            )
        if self.amount_from_spells_cast_this_turn:
            caster = _event_player(context, key="player_id")
            count = context.state.spells_cast_this_turn.get(getattr(caster, "id", None), 0)
            amount = self.amount * count
        if self.amount_from_half_own_life:
            controller = _controller_of(self.source, context)
            life = getattr(controller, "life", 0)
            amount = -(-life // 2)  # ceiling division (RULE 107.3 rounds up)
        if self.amount_from_half_target_life:
            # Resolved the same way the ordinary (no-amount-selector) path
            # below picks its player — this just needs to know *before*
            # `context.lose_life` which player's life to read.
            target_player = self.player
            if target_player is None and self.player_id is not None:
                target_player = context.state.player_by_id(self.player_id)
            if target_player is None and self.previous_subject and context.previous_targets:
                target_player = context.previous_targets[0]
            if target_player is None and self.target_spec is not None and targets:
                target_player = targets[0]
            if target_player is None:
                target_player = _controller_of(self.source, context)
            life = getattr(target_player, "life", 0)
            amount = -(-life // 2)  # ceiling division (RULE 107.3 rounds up)
        if amount <= 0:
            return
        if self.selector in _LOSE_LIFE_SELECTORS:
            controller_id = getattr(self.source, "controller_id", None)
            for p in context.state.living_players():
                if self.selector == "each_opponent" and p.id == controller_id:
                    continue
                context.lose_life(p, amount)
            return
        player = self.player
        if player is None and self.player_id is not None:
            player = context.state.player_by_id(self.player_id)
        if player is None and self.previous_subject and context.previous_targets:
            player = context.previous_targets[0]
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None and self.selector == "defending_player":
            player = _defending_player_of(self.source, context)
        if player is None and self.selector == "event_player":
            player = _event_player(context, key="player_id")
        if player is None:
            player = _controller_of(self.source, context)
        context.lose_life(player, amount)


class AddPlayerCountersEffect(GameEffect):
    """"[Player] get[s] N [kind] counters." (RULE 122 — only "rad", RULE
    728, in practice today) — the oracle-text-facing sibling of
    `RulesEngine.add_player_counters`. Same target_kind/selector split as
    `GainLifeEffect`/`LoseLifeEffect`: untargeted (the effect's controller)
    by default, ``target_kind="player"`` for a real RULE 115 target, or
    ``selector="each_player"``/``"each_opponent"``/``"defending_player"``
    for a mass/combat-relative recipient.

    ``selector="defending_player"`` resolves against the *attacking*
    object, which for an Aura/Equipment-hosted "whenever enchanted/equipped
    creature attacks, defending player gets ~" ability (Acquired Mutation)
    is ``self.source``'s *host*, not the Aura/Equipment itself — only the
    actual attacker gets `combat_defender` stamped on it by
    `declare_attackers` (RULE 506.4). Resolved here rather than widening
    the shared `_defending_player_of` helper, since every existing caller
    (afflict) is already the attacking creature itself.
    """

    def __init__(
        self,
        amount: Any = 0,
        kind: str = "rad",
        player: Any = None,
        selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.kind = kind
        self.player = player
        self.selector = selector
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector in ("each_player", "each_opponent"):
            controller_id = getattr(self.source, "controller_id", None)
            for p in context.state.living_players():
                if self.selector == "each_opponent" and p.id == controller_id:
                    continue
                context.add_player_counters(p, self.amount, self.kind, source=self.source)
            return
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None and self.selector == "defending_player":
            host = self.source
            attached_to = getattr(host, "attached_to", None)
            if attached_to is not None:
                resolved = context.state.find_object(attached_to)
                if resolved is not None:
                    host = resolved
            player = _defending_player_of(host, context)
        if player is None:
            player = _controller_of(self.source, context)
        if player is not None:
            context.add_player_counters(player, self.amount, self.kind, source=self.source)


class LoseAllPlayerCountersEffect(GameEffect):
    """"[Player] loses all [kind] counters." (RULE 122's removal sibling —
    Survivor's Med Kit's "Target player loses all rad counters.") Reads the
    live count at apply time and removes exactly that many via
    `RulesEngine.add_player_counters`'s existing non-positive-amount path
    (bypasses RULE 616.1 replacements, same as any other counter removal).
    """

    def __init__(
        self,
        kind: str = "rad",
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        if player is None:
            return
        current = player.counters.get(self.kind, 0)
        if current > 0:
            context.add_player_counters(player, -current, self.kind, source=self.source)


class DiesGrantsRadCountersEqualPowerEffect(GameEffect):
    """"When this creature dies, each opponent gets a number of rad
    counters equal to its power." (Feral Ghoul-shaped) — an atomic effect
    reading the dying creature's own last-known power (RULE 400.7) at
    apply time, the same "read the characteristic directly rather than
    compose two effects" shape `ExileGainLifeToControllerEffect` uses for
    "exile ~; you gain life equal to its power" — a generic
    `AddPlayerCountersEffect` has no way to receive a dynamic amount from
    its own triggering object.
    """

    def __init__(self, kind: str = "rad", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.kind = kind

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        power = getattr(self.source, "power", 0) or 0
        if power <= 0:
            return
        controller_id = getattr(self.source, "controller_id", None)
        for p in context.state.living_players():
            if p.id == controller_id:
                continue
            context.add_player_counters(p, power, self.kind, source=self.source)


class SacrificeEffect(GameEffect):
    """A player sacrifices up to ``count`` permanents matching ``what``
    (RULE 701.17) — untargeted; a real RULE 601.2c-style choice via
    `RulesEngine.sacrifice`/`request_choose_objects`, not an auto-pick
    (`GameEngine._sacrifice_candidate`'s non-interactive convention is a
    *cost*-payment concern, a synchronous call that can't pause for a
    chooser — this is an effect resolving, which can).

    ``selector="defending_player"`` (annihilator, RULE 702.86) resolves the
    player dynamically at apply-time, the same way `LoseLifeEffect` does;
    ``selector="each_opponent"`` runs the sacrifice once per opponent
    (Professor Onyx's −3).

    ``greatest_power`` narrows the choice to "a creature with the greatest
    power among creatures that player controls" (Professor Onyx again) —
    still an auto-pick (`max()`) among the tied leaders rather than routed
    through the chooser, since only a tie among several actually leaves
    anything to decide and no shipped card sacrifices more than one this
    way (recomputing "greatest" between interactive picks isn't modeled).
    """

    def __init__(
        self,
        count: "int | str" = 1,
        what: str = "permanent",
        player: Any = None,
        selector: Optional[str] = None,
        greatest_power: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        #: An int, or the ``"all_but_one"`` sentinel (`RulesEngine.sacrifice`
        #: resolves it against the live candidate count at apply-time).
        self.count = count
        self.what = what
        self.player = player
        self.selector = selector
        self.greatest_power = greatest_power

    #: A resumed continuation's own remaining-players list (see
    #: `_sacrifice_each_in_order`) — never set by a parsed `EffectSpec`
    #: (outside the whitelisted-param security boundary on purpose: this is
    #: pure runtime state, constructed only by this class itself), only by
    #: this class re-scheduling its own remainder.
    _remaining_players: Optional[list["Player"]] = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._remaining_players is not None:
            self._sacrifice_each_in_order(context, self._remaining_players)
            return
        if self.selector == "each_opponent":
            controller_id = getattr(self.source, "controller_id", None)
            players = [p for p in context.state.living_players() if p.id != controller_id]
            self._sacrifice_each_in_order(context, players)
            return
        if self.selector == "each_player":
            # RULE 601.2c mass edict — "each player sacrifices <what> of
            # their choice" (Accursed Marauder/Liliana, Dreadhorde General's
            # -4) — the `each_opponent` sibling that also includes the
            # ability's own controller.
            self._sacrifice_each_in_order(context, list(context.state.living_players()))
            return
        player = self.player or (targets[0] if targets else None)
        if player is None and self.selector == "defending_player":
            player = _defending_player_of(self.source, context)
        if player is None:
            return
        self._sacrifice_one(context, player)

    def _sacrifice_each_in_order(self, context: GameContext, players: list["Player"]) -> None:
        """`each_opponent`/`each_player` — one player's choice at a time.

        `context.sacrifice` opens a real `pending_choice` (RULE 601.2c)
        whenever a player has more matching permanents than ``count``.
        Looping every player synchronously in one `apply()` would silently
        overwrite an earlier player's still-unanswered prompt with a later
        one's — the game state holds exactly one `pending_choice` at a time
        (RULE 608.2, the same reason `_apply_effects_partitioned` parks a
        resolution's remaining *effects*; this is that same idiom one level
        down, for remaining *players* within a single effect). If a choice
        actually opened for this player and others remain, the rest are
        parked on `GameState.deferred_effects` as a fresh `SacrificeEffect`
        carrying just its own remaining-players list, resumed by
        `RulesEngine.resume_deferred_effects` once this one is answered.
        """
        state = context.state
        for i, player in enumerate(players):
            before = getattr(state, "pending_choice", None)
            self._sacrifice_one(context, player)
            opened = getattr(state, "pending_choice", None)
            if opened is not None and opened is not before and i + 1 < len(players):
                remainder = SacrificeEffect(
                    count=self.count, what=self.what, greatest_power=self.greatest_power,
                    source=self.source,
                )
                remainder._remaining_players = players[i + 1:]
                state.deferred_effects.append(
                    {
                        "effects": [remainder],
                        "targets": None,
                        "target_groups": None,
                        "group_index": 0,
                        "source": self.source,
                        "previous_targets": list(getattr(context, "previous_targets", [])),
                        "created_objects": list(getattr(context, "created_objects", [])),
                    }
                )
                return

    def _sacrifice_one(self, context: GameContext, player: "Player") -> None:
        if not self.greatest_power:
            context.sacrifice(player, self.what, self.count)
            return
        creatures = [
            o for o in context.state.permanents_controlled_by(player.id) if o.is_creature
        ]
        for _ in range(self.count):
            if not creatures:
                return
            victim = max(creatures, key=lambda o: o.power or 0)
            creatures.remove(victim)
            context.put_into_graveyard(victim)  # RULE 701.16c: sacrifice


class SacrificeSelfEffect(GameEffect):
    """"Sacrifice ~."/"Sacrifice this enchantment." (Dress Down/Underworld
    Breach-shaped standing end-step self-sac) — the effect's own source
    sacrifices itself, no player choice or RULE 115 target involved (RULE
    701.17). Uses `RulesEngine.put_into_graveyard` rather than `destroy`
    (RULE 701.16c: sacrifice isn't destruction, so it can't be regenerated),
    the same distinction `GameEngine._pay_activation_cost`'s own sacrifice
    cost-payment already makes.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.put_into_graveyard(self.source)


class SacrificeUnlessPayEffect(GameEffect):
    """"Sacrifice ~ unless you pay `<cost>`." (RULE 701.17 + an "unless"
    payment) — the single most common upkeep-trigger body on old cards
    (Arcades Sabboth, Breeding Pit, Child of Gaea, Kuro; Aura Flux/Coral Net
    grant it onto another permanent).

    ``cost`` is the printed cost *text* ("{G}{G}", "1 life", "a card"),
    parsed by `costs.parse_activation_cost` at resolution into the same
    `ActivationCost` an activated ability's cost uses — that's what makes
    the whole real vocabulary these cards print (mana / pay N life /
    discard a card / sacrifice another permanent) work without a bespoke
    cost model. Resolution itself is `RulesEngine.request_sacrifice_unless_
    pay`, which reuses ward's pay-or-lose-it choice machinery.
    """

    def __init__(
        self, cost: str = "", source: Optional["GameObject"] = None,
        target: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")
        #: "…sacrifice **it** unless you pay `<cost>`." naming a *different*
        #: permanent than this ability's own source (Ashling, the
        #: Limitless, MEC-42 — the token its own sacrifice trigger just
        #: made, not Ashling itself) — filled in by `CreateDelayedTrigger
        #: Effect`'s ``capture="created_objects"`` the same way it already
        #: fills `SacrificeSpecificEffect.target`-shaped effects; falls
        #: back to ``source`` (every existing caller's own shape) when unset.
        self.target = target

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        subject = self.target or self.source
        if subject is None:
            return
        player = _controller_of(subject, context)
        if player is None:
            return
        cost = parse_activation_cost(self.cost_text)
        if cost.is_free:
            # `parse_activation_cost` returns a *free* cost for text it
            # doesn't recognize rather than raising. Honouring that here
            # would silently mean "pay nothing to keep it" — do nothing at
            # all instead. (The parser front end only claims cost shapes it
            # can express, so this is a belt-and-braces guard for a
            # hand-authored entry, not a path real oracle text reaches.)
            return
        context.engine.request_sacrifice_unless_pay(player, cost, subject)


class TaxedDrawEffect(GameEffect):
    """"Whenever an opponent casts a spell, you may draw a card unless that
    player pays `<cost>`." (RULE 118.3's "unless" idiom applied to a draw
    rather than a sacrifice/counter — Rhystic Study/Mystic Remora/Esper
    Sentinel-shaped taxes).

    The *payer* is the triggering spell's own caster — read off the firing
    event's ``player_id`` (`GameContext.trigger_event`), not this ability's
    controller — so this only makes sense on a trigger whose condition
    already scopes the firing event to an opponent (``"controller":
    "not_you"``). Reuses `request_pay_cost_then`'s pay-or-lose-it machinery
    exactly like `SacrificeUnlessPayEffect` does: paying does nothing,
    declining (or being unable to pay) draws a card for this ability's own
    controller (`DrawCardEffect`'s untargeted default).

    ``amount_from_source_power`` (Esper Sentinel: "unless that player pays
    {X}, where X is this creature's power") reads the cost's amount off the
    source's own live power instead of a fixed printed value.
    """

    def __init__(
        self,
        cost: str = "",
        amount_from_source_power: bool = False,
        count: int = 1,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")
        self.amount_from_source_power = amount_from_source_power
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        source = self.source
        if source is None:
            return
        event = context.trigger_event or {}
        payer_id = event.get("player_id")
        payer = None
        for p in context.state.players:
            if p.id == payer_id:
                payer = p
                break
        if payer is None:
            return
        cost_text = self.cost_text
        if self.amount_from_source_power:
            power = getattr(source, "power", 0) or 0
            cost_text = "{" + str(power) + "}"
        cost = parse_activation_cost(cost_text)
        if cost.is_free:
            return
        context.engine.request_pay_cost_then(
            payer, cost, [], source,
            else_effect_specs=[{"type": "draw", "params": {"count": self.count}}],
        )


class EachPlayerPayOrEffect(GameEffect):
    """RULE 101.4's APNAP mass "unless" (PAR-13 — "Each player loses N life
    unless they discard a card."/"...unless they sacrifice a creature,
    artifact, or land of their choice." — Bellowing Mauler/Lim-Dûl's Hex/
    Tomb of Annihilation's own two dungeon rooms), the *mass* sibling of
    `SacrificeUnlessPayEffect`: every living player is asked in turn order,
    and ``effects`` lands on whoever doesn't (or can't) pay — never the
    ability's own controller, unlike that class's single fixed subject.

    ``cost`` is printed cost text exactly like `SacrificeUnlessPayEffect`'s
    own; ``effects`` are serialized `EffectSpec` dicts applied with the
    declining player as the sole target (`RulesEngine.
    request_each_player_pay_or` passes ``targets=[player]`` through to
    `request_pay_cost_then`), so a spec here should carry a matching
    ``target_kind`` (``"player"`` for `lose_life`/`discard`/etc.) rather
    than relying on an untargeted default.
    """

    def __init__(
        self,
        cost: str = "",
        effects: Optional[list[dict[str, Any]]] = None,
        scope: str = "each_player",
        effect_targets: str = "decliner",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")
        self.inner_specs = list(effects or [])
        #: "…**for each opponent**, `<effect>` unless that player
        #: `<pays>`." (MEC-43, Acererak the Archlich) — ``"each_player"``
        #: (default, every existing caller's shape) asks every living
        #: player including this ability's own controller; ``"each_
        #: opponent"`` excludes the controller from the sweep entirely.
        self.scope = scope
        #: Who ``effects`` targets when a player doesn't (or can't) pay:
        #: ``"decliner"`` (default) is every existing caller's shape — the
        #: player who declined. ``"controller"`` is Acererak's own "**you**
        #: create a token" — the effect lands on this ability's controller
        #: regardless of which opponent declined, so no ``targets`` are
        #: threaded through and each inner spec resolves against its own
        #: untargeted controller default instead.
        self.effect_targets = effect_targets

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        cost = parse_activation_cost(self.cost_text)
        if cost.is_free:
            return  # see SacrificeUnlessPayEffect's identical guard
        context.engine.request_each_player_pay_or(
            cost, self.inner_specs, self.source,
            scope=self.scope, effect_targets=self.effect_targets,
        )


class CounterSpellEffect(GameEffect):
    """Counter a target spell on the stack (RULE 701.5).

    ``noncreature``/``card_types``/``mana_value`` narrow *which* spells are
    legal targets in the first place (RULE 601.2c/115 — "counter target
    noncreature spell", "… target instant or sorcery spell", "… target spell
    with mana value N"), folded into `target_spec.spell_filter` and enforced
    by `targeting.legal_targets`. ``unless_pays`` (RULE 601's "Mana Leak"
    template — "counter target spell unless its controller pays {N}") is a
    resolve-time condition instead: the target's controller gets an
    interactive choice, handled by `RulesEngine.counter_unless_pays`.
    """

    def __init__(
        self,
        target: Any = None,
        unless_pays: Optional[str] = None,
        noncreature: bool = False,
        card_types: Optional[list[str]] = None,
        mana_value: Optional[int] = None,
        color: Optional[str] = None,
        source: Optional["GameObject"] = None,
        target_from_trigger_event: Optional[str] = None,
        suspend_instead: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.unless_pays = unless_pays
        #: "…if no mana was spent to cast it, counter that spell." (Vexing
        #: Bauble) — "that spell" is the firing SPELL_CAST event's own
        #: object, not a RULE 115 target — the same "resolve off the firing
        #: event" idiom `DestroyEffect.target_from_trigger_event` already
        #: established.
        self.target_from_trigger_event = target_from_trigger_event
        #: RULE 702.62 (Delay, MEC-42): "exile it with N time counters on it
        #: instead of putting it into its owner's graveyard. If it doesn't
        #: have suspend, it gains suspend." Threaded straight through to
        #: `RulesEngine.counter_unless_pays`/`counter_spell`.
        self.suspend_instead = suspend_instead
        spell_filter: dict[str, Any] = {}
        if noncreature:
            spell_filter["noncreature"] = True
        if card_types:
            spell_filter["card_types"] = list(card_types)
        if mana_value is not None:
            spell_filter["mana_value"] = mana_value
        if color:
            spell_filter["color"] = color
        if target_from_trigger_event is None:
            self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_from_trigger_event:
            event = context.trigger_event or {}
            instance_id = event.get(self.target_from_trigger_event)
            target = context.state.find_object(instance_id) if instance_id is not None else None
            if target is not None:
                context.counter(
                    target, unless_pays=self.unless_pays, source=self.source,
                    suspend_instead=self.suspend_instead,
                )
            return
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.counter(
                target, unless_pays=self.unless_pays, source=self.source,
                suspend_instead=self.suspend_instead,
            )


class CounterAbilityEffect(GameEffect):
    """Counter target activated or triggered ability (RULE 701.5b — Stifle/
    Trickbind, ENG-26).

    The stack-item-identity sibling of `CounterSpellEffect`: an ability
    `StackItem` has no `GameObject` of its own (`.obj` is `None`), so
    ``target_spec`` uses `targeting.py`'s ``"ability"`` kind
    (`StackItem.stack_id`-keyed) rather than ``"spell"``
    (`GameObject.instance_id`-keyed). No ``unless_pays``/type-filter
    params — no printed card needing either has reached this yet; add
    them the same way `CounterSpellEffect` carries its own if one does.
    """

    def __init__(self, target: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind="ability")

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.counter_ability(target)


class CopySpellEffect(GameEffect):
    """Copy a target spell on the stack (RULE 707.10 — Dualcaster Mage/Flare
    of Duplication/Reiterate "copy target instant or sorcery spell").

    ``card_types`` narrows which spells are legal targets (default instant/
    sorcery), folded into ``target_spec.spell_filter`` exactly as
    `CounterSpellEffect` does. ``count`` copies are made (Flare of
    Duplication makes one; a hypothetical "copy it twice" would set 2). The
    copy is controlled by *this effect's source's controller* (RULE 707.10c
    — the copier), created by `RulesEngine.copy_spell`. "You may choose new
    targets for the copy" is a legal-but-optional refinement (RULE 707.10c);
    this MVP keeps the original's targets (the default outcome), which every
    real card in scope allows — a genuine new-target choice would open a
    `pending_choice`, deferred until a card needs it.
    """

    def __init__(
        self,
        card_types: Optional[list[str]] = None,
        count: int = 1,
        source: Optional["GameObject"] = None,
        target_count: int = 1,
        optional: bool = False,
        spell_from_trigger_event: Optional[str] = None,
        controller_from_trigger_event: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.spell_from_trigger_event = spell_from_trigger_event
        self.controller_from_trigger_event = controller_from_trigger_event
        spell_filter: dict[str, Any] = {}
        if card_types:
            spell_filter["card_types"] = list(card_types)
        # "Copy any number of target instant and/or sorcery spells." (Display
        # of Power) — ``target_count`` > 1 offers several *distinct* spell
        # targets (each getting ``count`` copies), the RULE 601.2c "any
        # number" idiom Fire Covenant's own ``count=10`` UI cap already
        # established for "any number of target creatures", applied here to
        # a spell target instead of a permanent one. Untargeted when the
        # spell instead comes off the *firing trigger event*
        # (``spell_from_trigger_event`` — "whenever a player casts an
        # instant or sorcery spell, that player copies it", Bonus Round-
        # shaped: RULE 603.1's "it" is the spell that triggered this, not a
        # RULE 601.2c target choice at all) — same ``target_kind=None`` +
        # ``and … is None`` guard `DestroyEffect.target_from_trigger_event`
        # already established.
        if spell_from_trigger_event is None:
            self.target_spec = TargetSpec(
                kind="spell", spell_filter=spell_filter or None, count=target_count, optional=optional,
            )
        else:
            self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.spell_from_trigger_event is not None:
            event = context.trigger_event or {}
            instance_id = event.get(self.spell_from_trigger_event)
            target = context.state.find_object(instance_id) if instance_id is not None else None
            if target is None:
                return
            controller_id = (
                event.get(self.controller_from_trigger_event)
                if self.controller_from_trigger_event
                else getattr(self.source, "controller_id", None)
            )
            if controller_id is None:
                return
            context.copy_spell(target, controller_id, self.count)
            return
        if not targets:
            return
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        for target in targets:
            context.copy_spell(target, controller_id, self.count)


class CopySelfControlledByPreviousTargetEffect(GameEffect):
    """"Target player discards two cards. That player may copy this spell
    and may choose a new target for that copy." (Chain of Smog, MEC-43) —
    the copier is whoever the *preceding* clause of this same spell
    targeted (`GameContext.previous_targets`, the same pronoun idiom
    `FightEffect`/`GoadEffect` use), not this spell's own caster.

    **Documented simplification**, the same one `CopySpellEffect`'s own
    docstring and `CopySelfIfCastFromGraveyardEffect` already establish:
    "may" is read as unconditional (always copies — declining has no real
    downside worth modeling) and "may choose a new target" keeps the
    original target instead of opening a fresh interactive pick.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        previous = list(getattr(context, "previous_targets", []) or [])
        if not previous:
            return
        controller_id = getattr(previous[0], "id", None)
        if controller_id is None:
            return
        context.copy_self_spell(self.source, controller_id, targets=None)


class CopySelfIfCastFromGraveyardEffect(GameEffect):
    """"If this spell was cast from a graveyard, you may copy this spell
    and may choose a new target for the copy." (Sevinne's Reclamation,
    MEC-42) — reads `GameObject.cast_via_flashback` directly off this
    effect's own source: still ``True`` at this point, since `RulesEngine.
    _finish_resolving_stack_item`'s own "exile instead of graveyard"
    branch (which clears it) only runs *after* every one of the spell's
    effects — this one included — has already resolved. Opens
    `RulesEngine.copy_self_spell` rather than `CopySpellEffect`'s ordinary
    `copy_spell` (which looks up a *live* `StackItem` — the original is
    already off the stack by now).

    **Documented simplification**: "you may" is read as unconditional
    (always copies when cast from a graveyard) — the same accepted
    simplification this engine already gives every other untargeted
    "you may" trigger with no real downside to declining.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or not getattr(self.source, "cast_via_flashback", False):
            return
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        context.copy_self_spell(self.source, controller_id, targets=targets)


class ChangeTargetEffect(GameEffect):
    """Change the target of a target spell already on the stack (RULE
    115.4/601.2c — Misdirection/Deflecting Swat).

    The *changing* player (RULE 115.4a: this effect's own controller, not
    the targeted spell's) picks a fresh legal target, recomputed against
    the current board — not whatever was legal when that spell was cast.
    ``single_target`` folds into ``target_spec.spell_filter`` as
    Misdirection's own restriction ("target spell **with a single
    target**"); Deflecting Swat has no such restriction printed, but this
    MVP still only retargets a spell with exactly one existing target —
    see `RulesEngine.change_target`'s docstring for why. ``optional`` is
    Deflecting Swat's "**you may** choose new targets"; Misdirection's own
    "Change the target" is mandatory.

    ``spell_or_ability`` (ENG-26) is Deflecting Swat's actual printed scope
    ("choose new targets for target spell **or ability**") — the union
    `targeting.py` kind covering both a spell `StackItem` (keyed by its own
    `GameObject.instance_id`, as `single_target`'s ``spell_filter`` still
    only narrows) and an ability one (keyed by `StackItem.stack_id`, which
    has no *spell*-shaped filter to narrow by). `RulesEngine.change_target`
    reads whichever one the chosen `StackItem` turns out to be.

    ``card_types`` narrows the *targeted* spell by its own printed types
    ("target **instant or sorcery** spell with a single target" — Hydroelectric
    Specimen), folded into the same ``target_spec.spell_filter`` dict
    ``single_target`` uses (`targeting._spell_matches_filter`'s
    ``card_types`` key).

    ``redirect_to_source`` is Spellskite's actual printed shape ("Change a
    target of target spell or ability **to this creature**") — not a free
    choice among every legal alternative the way Misdirection/Deflecting
    Swat's own player-facing pick is, but a forced redirect to one specific
    permanent (this effect's own source), silently declining (RULE 115.4a's
    "no legal target, doesn't change") if the source isn't itself a legal
    target of whatever's being retargeted.
    """

    def __init__(
        self,
        target: Any = None,
        single_target: bool = False,
        optional: bool = False,
        spell_or_ability: bool = False,
        card_types: Optional[list[str]] = None,
        redirect_to_source: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.optional = optional
        self.redirect_to_source = redirect_to_source
        if spell_or_ability:
            self.target_spec = TargetSpec(kind="spell_or_ability")
        else:
            spell_filter: dict[str, Any] = {}
            if single_target:
                spell_filter["single_target"] = True
            if card_types:
                spell_filter["card_types"] = list(card_types)
            self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.change_target(
                target, optional=self.optional, source=self.source,
                redirect_to_source=self.redirect_to_source,
            )


class GainControlOfSpellEffect(GameEffect):
    """"Gain control of target noncreature spell. You may choose new
    targets for it." (Commandeer) — the still-on-the-stack sibling of the
    ordinary battlefield control-change effects (`GainControlUntilEndOfTurn
    Effect`/`GainControlBySourceEffect`), which all assume the target is
    already a permanent. The retarget reuses `RulesEngine.change_target`
    outright rather than a second `TargetSpec` of its own — it's the exact
    same spell already gained, so there's nothing new to choose *which*
    stack item is affected. Run *before* the control change (not after) so
    RULE 115.4a's "you"/"your" in the target description still resolves
    against the spell's *original* controller, matching `change_target`'s
    own documented reading.
    """

    def __init__(self, target: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind="spell", spell_filter={"noncreature": True})

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        context.change_target(target, optional=True, source=self.source)
        context.gain_control_of_spell(target, controller_id)


class CounterCreateTokenEffect(GameEffect):
    """"Counter target spell. Its controller creates a token." (Swan Song,
    Strix Serenade, An Offer You Can't Refuse) — the stack-side sibling of
    `DestroyCreateTokenEffect`: the token goes to the *countered spell's own
    controller* (the player being answered), read off the stack item before
    it's countered, the same "read something off the target, then act" shape.

    ``noncreature``/``card_types`` narrow which spells are legal targets,
    folded into ``target_spec.spell_filter`` exactly as `CounterSpellEffect`
    does; ``power``/``toughness``/``colors``/``subtypes``/``token_name``
    describe the token exactly as `DestroyCreateTokenEffect`'s do.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        noncreature: bool = False,
        card_types: Optional[list[str]] = None,
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        token_name: Optional[str] = None,
        count: int = 1,
        keywords: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        spell_filter: dict[str, Any] = {}
        if noncreature:
            spell_filter["noncreature"] = True
        if card_types:
            spell_filter["card_types"] = list(card_types)
        self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.token_name = token_name or (subtypes[0] if subtypes else "Token")
        self.count = count
        self.keywords = keywords or []

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..services.token_database import synthesize_token_card

        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.counter(target, source=self.source)
        if controller_id is None:
            return
        card = synthesize_token_card(
            self.token_name, power=self.power, toughness=self.toughness,
            colors=self.colors, subtypes=self.subtypes, keywords=self.keywords,
        )
        context.create_token(controller_id, card, self.count)


class WardEffect(GameEffect):
    """A ward triggered ability's own resolution body (RULE 702.21a):
    "counter that spell or ability unless that player pays [cost]."

    Unlike `CounterSpellEffect`/`CounterSpellEffect.unless_pays` (where the
    *target's controller* decides whether to pay — RULE 601's "Mana Leak"
    template), ward's decision belongs to the *caster* of the countered
    item. ``item``/``caster_id``/``cost`` are fixed the moment the warded
    permanent became a target (RULE 603.3a's trigger-time lock-in), not
    re-derived here — so even if the caster or the item's legality changes
    before this resolves, the ability still asks the right player about the
    right item (RULE 603.6/603.10 "look back in time").

    Never built via `EffectRegistry` — always constructed directly by
    `RulesEngine.check_ward`, one instance per warded target, each wrapped
    in its own `StackItem` placed on top of the triggering spell/ability so
    normal priority-passing carries it (RULE 603.3), rather than resolved
    inline as a synchronous choice.
    """

    def __init__(
        self,
        item: Any,
        caster_id: str,
        cost: Any,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.item = item
        self.caster_id = caster_id
        self.cost = cost

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        ability_controller_id = self.source.controller_id if self.source is not None else None
        context.engine.resolve_ward_effect(
            self.item, self.caster_id, self.cost, ability_controller_id=ability_controller_id
        )


class CounterUnlessPayEffect(GameEffect):
    """MEC-19: "Counter it/that spell[or ability] unless that player/its
    controller pays `<cost>`." — a genuine printed triggered ability's own
    resolution body (RULE 603.1's "whenever ~ becomes the target of a
    spell/ability [an opponent/you control(s)], …" family), for the ~150
    real cards that spell this out as ordinary card text rather than
    printing the **Ward** keyword (RULE 702.21, already handled by
    `WardEffect`/`RulesEngine.check_ward`/`resolve_ward_effect` — this is
    the same rules outcome, just reached as an ordinary triggered ability
    that goes on the stack and gets a normal priority window, rather than
    Ward's own special-cased RULE 702.21c "push straight on top" timing).

    Deliberately a thin adapter onto `resolve_ward_effect`, not a parallel
    implementation: the targeted spell/ability and its caster are looked up
    fresh, off `GameContext.trigger_event`'s own `stack_id`/`controller_id`
    (`EventType.BECOMES_TARGET`), then handed straight to the exact same
    "can they afford it? open a real pay-or-not choice; if not, counter"
    flow ward already has — including reusing its ``"ward"`` `pending_
    choice` kind, since the two are rules-identical from that point on.
    """

    def __init__(self, cost: str = "", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.cost_text = cost

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import parse_activation_cost  # function-scoped: import cycle

        event = context.trigger_event
        if event is None:
            return
        stack_id = event.get("stack_id")
        item = next((i for i in context.state.stack if i.stack_id == stack_id), None)
        if item is None:
            return  # the targeting spell/ability already left the stack
        caster_id = event.get("controller_id")
        if caster_id is None:
            return
        ability_controller_id = self.source.controller_id if self.source is not None else None
        context.engine.resolve_ward_effect(
            item,
            caster_id,
            parse_activation_cost(self.cost_text),
            ability_controller_id=ability_controller_id,
        )


class CantBeCounteredEffect(GameEffect):
    """Marker: "This spell can't be countered." (RULE 118-area).

    Bound like any other one-shot effect — via `spell_effect` on an instant/
    sorcery's own body, or `static` on a permanent's standing line — and so
    lands in ``obj.spell_effects``/``obj.static_effects`` respectively
    (`game/effect_binder.py`'s ordinary dispatch, no special-casing needed).
    It carries no continuous behaviour: `continuous.recompute` only ever
    reads `StaticAbility` instances off `static_effects` (this isn't one), and
    a spell's own resolution just calls `apply()` like every other effect in
    its list. The only consumer is `RulesEngine._is_cant_be_countered`, which
    scans both lists for this marker *before* the object would otherwise
    leave the stack — the one moment "can't be countered" actually matters.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class LookAtCardsEffect(GameEffect):
    """"Look at the top card of target player's library."/"Look at a card at
    random in target player's hand." (Mishra's Bauble/Urza's Bauble) — a
    genuine RULE 115 target (so hexproof/protection still matters), but no
    game-state consequence: this engine has no reason to hide the peeked
    card from the querying player in the first place (a solo/goldfish board
    already shows every zone to its one real player, and a bot never reads
    hidden information regardless), so there's nothing left for "look" to
    actually *do*. Kept as its own effect rather than dropped to an empty
    ``effects`` list precisely so the target requirement survives.
    """

    def __init__(
        self, target: Any = None, source: Optional["GameObject"] = None, target_kind: str = "player",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class MarkCantBeCounteredEffect(GameEffect):
    """Marks a spell handed in via ``targets[0]`` — never a RULE 115 target
    of its own — as "can't be countered", by appending a
    `CantBeCounteredEffect` marker onto its `GameObject.spell_effects` so
    `RulesEngine._is_cant_be_countered`'s existing scan finds it with no new
    consumer-side code. The `arm_spell_watcher`-driven resolve-time
    counterpart to that class's own bind-time marker — "the next spell you
    cast this turn can't be countered" (Mistrise Village) can't dock the
    marker at bind time since the spell it protects hasn't been cast yet;
    `GameState.spell_watchers` hands it over once one is.

    ``target_kind`` (MEC-40, Vexing Shusher's own "{R/G}: Target spell
    can't be countered.") opts this effect into a genuine RULE 115 target
    of its own instead of relying on some other caller to hand a spell in
    via ``targets[0]`` — ``None`` (the default) keeps the Mistrise
    Village/`arm_spell_watcher` shape unchanged.
    """

    def __init__(
        self, source: Optional["GameObject"] = None, target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None:
            return
        # `GameObject.spell_effects` is only ever populated by `effect_
        # binder.bind_from_catalogue` when the card has a genuine
        # ``"spell_effect"``-kind body (MEC-40 — found while testing Domri,
        # Anarch of Bolas's own "creature spells you cast this turn can't
        # be countered": the overwhelming majority of creature/artifact/
        # enchantment spells have *no* such body at all — only triggered/
        # static/activated abilities — so `hasattr` alone silently dropped
        # this marker for any of them, a dormant bug this ability's own
        # printed wording exercises directly, not just an edge case).
        if not hasattr(target, "spell_effects"):
            target.spell_effects = []
        target.spell_effects.append(CantBeCounteredEffect())


class GrantCantBeCounteredEffect(GameEffect):
    """A standing "Spells you control can't be countered." grant (Hexing
    Squelcher-shaped) — unlike `MarkYourSpellsOnStackCantBeCounteredEffect`
    (a *resolve-time*, "this turn" one-shot), this is a bind-time
    `static_effects` marker on the granting permanent itself, scanned by
    `RulesEngine._is_cant_be_countered` for every spell as it's cast
    (never expires while the permanent is in play). ``scope`` is
    ``"you"`` (every spell) or ``"creature_spells_you_control"`` (RULE
    502-area creature-only grants — Rionya/Sarkhan Unbroken-shaped).
    """

    def __init__(
        self, scope: str = "you", color: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.scope = scope
        #: "**Green** spells you control can't be countered." (Allosaurus
        #: Shepherd, MEC-40) — ``scope="color_spells_you_control"``'s own
        #: colour, checked against `GameObject.colors` at `RulesEngine.
        #: _is_cant_be_countered`'s existing scan point.
        self.color = str(color).upper() if color else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class GrantSearchProhibitedEffect(GameEffect):
    """"Your opponents can't search libraries." (Stranglehold-shaped, RULE
    701.19a: an effect that instructs a prohibited player to search simply
    doesn't — the search is skipped, not replaced). A bind-time
    `static_effects` marker, the same minimal shape
    `GrantCantBeCounteredEffect` uses; scanned by `RulesEngine.
    request_search`'s own guard rather than the layer engine (a
    permission, not a characteristic).

    ``scope="opponents"`` (the default, Stranglehold's own shape) prohibits
    only players other than this effect's own controller; ``scope="all"``
    (MEC-35, "**Players** can't search libraries." — Leonin Arbiter) drops
    that exemption, prohibiting the controller too.
    """

    def __init__(self, scope: str = "opponents", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.scope = scope if scope in ("opponents", "all") else "opponents"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class GrantSearchLimitedToTopNEffect(GameEffect):
    """"If an opponent would search a library, that player searches the
    top N cards of that library instead." (Aven Mindcensor-shaped, RULE
    701.19a-adjacent — a *narrowing* of the search rather than
    `GrantSearchProhibitedEffect`'s outright block). A bind-time
    `static_effects` marker, scanned by `RulesEngine._search_zone_objects`
    exactly where `GrantSearchProhibitedEffect` is scanned by `request_
    search` — the library portion of the pool becomes just its top ``n``
    cards (in order) rather than the whole thing, for anyone who isn't this
    effect's own controller.
    """

    def __init__(self, n: int = 4, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.n = n

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class BecomeSaddledEffect(GameEffect):
    """RULE 702.171a: "Saddle N" — "…: This permanent becomes saddled
    until end of turn." (Guardian Sunmare, MEC-40). Not a RULE 613 layer
    effect (being saddled changes no characteristic) — a plain sticky
    `GameObject.saddled_until_turn` stamp, the same "needs no cleanup-step
    reset, just goes stale next turn" idiom `GraveyardCastPermissionEffect.
    expires_turn` uses.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            self.source.saddled_until_turn = context.state.turn_number


class GrantSkipExtraTurnsEffect(GameEffect):
    """"If an opponent would begin an extra turn, that player skips that
    turn instead." (Stranglehold-shaped, RULE 500.7/700.4). A bind-time
    `static_effects` marker; `GameEngine.begin_turn`'s own extra-turn pop
    loop skips a queued taker matching this grant instead of handing them
    the turn.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class MarkYourSpellsOnStackCantBeCounteredEffect(GameEffect):
    """"Spells you control can't be countered this turn." (Veil of
    Summer) — the *immediate* half: every spell this effect's controller
    already has on the stack right now (typically cast in response to an
    opponent's counterspell, the card's own main use case) is marked the
    same way `MarkCantBeCounteredEffect` marks one explicit target.
    Future spells this turn are the separate, repeat-armed `arm_spell_
    watcher` half — this effect only reaches the stack as it exists at
    this moment.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for item in context.state.stack:
            if item.kind == "spell" and item.obj is not None and item.controller_id == player.id:
                item.obj.spell_effects.append(CantBeCounteredEffect())


class MillEffect(GameEffect):
    """Put the top ``count`` cards of a player's library into their graveyard.

    Untargeted ("Mill three cards.") mills the effect's controller; a
    ``target_kind`` of ``"player"`` mills a chosen player (RULE 701.13).

    ``count_selector`` (MEC-43, Altar of Dementia — "target player mills
    cards equal to the sacrificed creature's power") makes ``count``
    dynamic instead of fixed: a `continuous.count_selector` name, evaluated
    for this effect's own **source's controller** (not the milled player —
    "the sacrificed creature's power" is a fact about what *this ability's
    controller* just paid, unrelated to who gets milled), overriding the
    fixed ``count`` when set.
    """

    def __init__(
        self,
        count: int = 1,
        target_kind: Optional[str] = None,
        count_selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.count_selector = count_selector
        if target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            player = targets[0] if targets else None
        else:
            player = context.active_player
        if player is None:
            return
        count = self.count
        if self.count_selector:
            from . import continuous  # function-scoped: avoid an import cycle

            controller_id = getattr(self.source, "controller_id", None)
            count = continuous.count_selector(
                context.state, controller_id, self.count_selector, source=self.source
            )
        context.mill(player, count)


class ExileEffect(GameEffect):
    """Exile a target permanent (RULE 406 / 701.5a) — or, with ``count`` >
    1, every one of a fixed/"up to N" set of chosen targets (RULE 115.1a
    generalized to N>=2 — "exile up to two target creatures you control") —
    or, with ``selector`` set, a mass "exile all X" board wipe (RULE
    601.2c, untargeted — Farewell-shaped), the same shape
    `DestroyEffect.selector` uses.

    ``target_kind=None`` (unlike the default ``"permanent"``) is the *self*
    form — "Exile ~."/"Exile this spell/card." (Teferi's Protection/
    Mnemonic Betrayal-shaped trailing self-exile) — no RULE 115 target at
    all, mirroring `TapEffect`/`RegenerateEffect`'s own self mode.

    ``remember=True`` additionally stamps the exiled target's own
    ``instance_id`` onto this ability's own source (`GameObject.
    linked_exile_id`) — the O-Ring-shaped "when this leaves the
    battlefield, return the exiled card" half (`ReturnLinkedExileEffect`)
    reads it back later, arbitrarily many turns on. Only meaningful with a
    single (``count=1``) real target — a mass/selector exile has nothing
    single to remember.

    ``track_exiled_with=True`` (MEC-21, Agatha's Soul Cauldron) is the
    generalized, *accumulating* sibling of ``remember`` — "exile target
    card. [...] exiled **with** ~" (~185 cached cards print this shape,
    per this ticket's sizing) — appending the exiled target's
    ``instance_id`` onto `GameObject.exiled_with_ids` instead of
    overwriting `linked_exile_id`'s single slot, so a repeatable ability
    (Agatha's Soul Cauldron's own "{T}: Exile target card from a
    graveyard.") builds up a real list across many activations rather than
    only ever remembering its last one. The two flags are independent and
    may combine on a future card; this one is also meaningful with
    ``count > 1`` (unlike ``remember``), appending every target chosen.

    ``distinct_controllers`` (Protector of the Wastes-shaped "up to two
    target artifacts and/or enchantments controlled by **different
    players**") is `targeting.TargetSpec.distinct_controllers` — see its
    docstring; only meaningful with ``count >= 2``.

    ``target_kind="trigger_subject"`` (MEC-38, Necropotence's "whenever
    you discard a card, exile **that card** from your graveyard") is a
    fourth, non-RULE-115 mode alongside the target/self/selector shapes
    above — the acted-on object isn't chosen at all, it's whichever card
    the firing event itself names, read live off `GameContext.
    trigger_event` (``trigger_event_key``, ``"instance_id"`` by default)
    the same way `TapEffect`'s own ``target_kind="trigger_subject"``
    already does. By the time this fires the named card is already
    sitting in the graveyard (`RulesEngine.discard`/`discard_specific`
    move it there before firing), so this is a real zone change, not a
    no-op.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "permanent",
        optional: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        remember: bool = False,
        creature_filter: Optional[dict[str, Any]] = None,
        distinct_controllers: bool = False,
        track_exiled_with: bool = False,
        max_mana_value: Optional[int] = None,
        grant_owner_play_permission: bool = False,
        owner_play_permission_tax: Optional[int] = None,
        trigger_event_key: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.selector = selector if selector in _MASS_DESTROY_SELECTORS else None
        self.filter = filter
        self.remember = remember
        self.track_exiled_with = track_exiled_with
        self._trigger_subject_mode = target_kind == "trigger_subject"
        self.trigger_event_key = trigger_event_key or "instance_id"
        #: "For as long as that card remains exiled, its owner may play
        #: it." (MEC-12, Soul Partition/Praetor's Grasp-shaped) — the
        #: standing, unconditional sibling of Lukka's own board-gated
        #: `GameState.exile_cast_condition` grant (an empty condition dict
        #: always holds, per `static_conditions.condition_holds`'s own "no
        #: condition = always true"), keyed to the exiled card's *owner*
        #: rather than this effect's controller.
        self.grant_owner_play_permission = grant_owner_play_permission
        #: "A spell cast by an opponent this way costs {2} more to cast."
        #: (Soul Partition) — stamped directly onto the exiled card's own
        #: ``affects="self"`` static at the moment it's exiled
        #: (`except_same_controller_as` = the exiler's own id), read back
        #: by `continuous.self_cost_reduction_for`'s new ``caster_id``
        #: param whenever/if it's ever actually cast.
        self.owner_play_permission_tax = owner_play_permission_tax
        self.target_spec: Optional[TargetSpec] = None
        if self.selector is None and target_kind is not None and not self._trigger_subject_mode:
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max, creature_filter=creature_filter,
                distinct_controllers=distinct_controllers,
                # "…permanent … with mana value N or less." (MEC-12, Skyclave
                # Apparition) — the same target-offer-time cap `DestroyEffect`
                # already threads (`targeting.TargetSpec.max_mana_value`).
                max_mana_value=max_mana_value,
            )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            for obj in _mass_selector_objects(context, self.selector, self.filter, source=self.source):
                context.exile(obj)
            return
        if self._trigger_subject_mode:
            event = context.trigger_event
            obj_id = (event or {}).get(self.trigger_event_key)
            target = context.state.find_object(obj_id) if obj_id is not None else None
            if target is not None:
                context.exile(target)
            return
        if self.target_spec is None:
            target = (targets[0] if targets else None) or self.target or self.source
            if target is not None:
                context.exile(target)
            return
        chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
        for target in chosen:
            if self.remember and self.source is not None:
                self.source.linked_exile_id = target.instance_id
            if self.track_exiled_with and self.source is not None:
                self.source.exiled_with_ids.append(target.instance_id)
            context.exile(target)
            if self.grant_owner_play_permission:
                context.state.exile_cast_condition[target.instance_id] = (target.owner_id, {})
                if self.owner_play_permission_tax:
                    from .effect_binder import build_effects  # function-scoped: effects↔binder cycle
                    from ..parser.oracle.spec import EffectSpec

                    exiler_id = getattr(self.source, "controller_id", None)
                    tax = build_effects(
                        [EffectSpec("cost_reduction", {
                            "affects": "self",
                            "generic": self.owner_play_permission_tax,
                            "increase": True,
                            "except_same_controller_as": exiler_id,
                        })],
                        target,
                    )
                    target.static_effects.extend(tax)


class ExileTopOfLibraryEffect(GameEffect):
    """"Exile the top card of your library[, face down]." (MEC-38,
    Necropotence-shaped) — deterministic, no chooser at all, unlike
    `SearchLibraryEffect` (which offers the *whole* zone as a real RULE
    115.1a-ish pick even with ``count=1``): always the literal top card.
    ``face_down=True`` stamps `GameObject.face_down_in_exile`, the same
    flag `RulesEngine._put_searched_card`'s own ``"exile_face_down"``
    destination uses. Appends the exiled card to `GameContext.
    created_objects` so a following clause ("Put that card into your
    hand at the beginning of your next end step.") can reach it — see
    `CreateDelayedTriggerEffect`'s ``capture="created_objects"``.

    ``player_selector="active_player"`` (MEC-33, Omen Machine — "at the
    beginning of **each player's** draw step, **that player** exiles…")
    reads `GameState.active_player` live at resolution instead of this
    effect's own source's controller — a `STEP_BEGIN` trigger with no
    ``phase_relation`` fires once per turn regardless of whose turn it is
    (RULE 500.1: a draw step only ever belongs to the turn's own active
    player, so "each player's draw step" and "the active player's draw
    step, every turn" are the same set of firings), the same "no subject
    of its own, read live off `GameState.active_player`" idiom
    `DealDamageEffect`'s own ``"active_player"`` selector already
    established (Roiling Vortex-shaped).
    """

    def __init__(
        self, face_down: bool = False, player_selector: str = "controller",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.face_down = face_down
        self.player_selector = player_selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.player_selector == "active_player":
            player = context.state.active_player
        else:
            player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        context.exile(top)
        if self.face_down:
            # Set *after* the move: `RulesEngine._remove_from_current_zone`
            # (which `exile()` calls to pull the card out of its old zone)
            # unconditionally clears this flag as its own RULE 400.7 "a
            # card leaving exile turns face up" behavior — harmless for
            # that case, but it would silently undo this card *entering*
            # exile face down if set beforehand.
            top.face_down_in_exile = True
        context.created_objects.append(top)


class LandOrFreeCastEffect(GameEffect):
    """"If it's a land card, the player puts it onto the battlefield.
    Otherwise, the player casts it without paying its mana cost if able."
    (MEC-33 — Omen Machine's own tail; the same tail also prints on Wild
    Evocation off a different source card, "reveals a card at random from
    their hand" instead of an exiled top card, confirming this is a real
    shared template worth its own primitive rather than a one-off).

    Acts on whatever card an earlier effect in the same resolution just
    made available — `GameContext.created_objects[-1]`, the same "read
    what a previous clause created" idiom `AttachEffect(target_kind=
    "created")`/`ReturnFromGraveyardEffect(target_kind=
    "self_enchant_target")` already use, rather than a RULE 115 target of
    its own (nothing here is chosen — it's whichever card the source
    effect surfaced). ``player_selector`` matches `ExileTopOfLibraryEffect`'s
    own param exactly (``"controller"`` default, ``"active_player"`` for
    Omen Machine's "each player's draw step, that player…" scoping).

    A land goes straight to the battlefield (RULE 305.1 — no stack, no
    legality check beyond existing). Anything else is cast via
    `RulesEngine.cast_without_paying` (RULE 118.9/601.3b) — but only when
    "able": a spell requiring a target it has none of simply can't be cast,
    the same RULE 601.2c gate `GameEngine.has_legal_targets` checks before
    ever offering a real cast action, replicated here directly off
    `targeting.py` since an effect has no `GameEngine` to call through
    (`GameContext.engine` is the `RulesEngine`). "If able" names no other
    fallback in either printed card, so an uncastable nonland card is left
    exactly where the source effect left it (in exile, or wherever) —
    neither card's text says to do anything else with it.

    **Documented simplification**: a targeted card is auto-targeted at its
    first legal option per requirement rather than opening a real choice —
    this engine has no "pause mid-resolution for a nested cast+targeting
    cycle" primitive yet (`game/rules/misc_mixin.py`'s own `"grant_free_
    cast"` branch, MEC-20, names the same gap for Expertise's own same-turn
    free cast), so every other automatic-cast primitive in this codebase
    accepts the same "first legal candidate, no prompt" reading rather than
    leaving the card silently uncast whenever it happens to have 2+ legal
    targets.
    """

    def __init__(self, player_selector: str = "controller", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player_selector = player_selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = context.created_objects[-1] if context.created_objects else None
        if obj is None:
            return
        if self.player_selector == "active_player":
            player = context.state.active_player
        else:
            player = _controller_of(self.source, context)
        if player is None:
            return
        if obj.card.is_land:
            obj.summoning_sick = True
            context.engine._remove_from_current_zone(player, obj)
            context.state.add_to_battlefield(obj)
            context.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD,
                    controller_id=player.id,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
            return
        requirements = requirements_with_targets(context.state, player.id, obj)
        if not all_requirements_satisfiable(requirements):
            return  # "if able" — no legal target, so it can't be cast
        cast_targets: list[Any] = []
        for req in requirements:
            options = req.get("options") or []
            if not options:
                continue
            pick = options[0]
            if "instance_id" in pick:
                resolved = context.state.find_object(pick["instance_id"])
            elif "player_id" in pick:
                resolved = context.state.player_by_id(pick["player_id"])
            else:
                resolved = None
            if resolved is not None:
                cast_targets.append(resolved)
        context.engine.cast_without_paying(player, obj, targets=cast_targets or None)


class ExileAnyNumberYouControlEffect(GameEffect):
    """"Exile any number of other nonland permanents you control until ~
    leaves the battlefield." (MEC-12, Abdel Adrian, Gorion's Ward) — a
    *selection* among the controller's own permanents, not a RULE 115
    target at all (the printed line has no "target" word), so it opens
    `RulesEngine.request_choose_objects`'s "choose N of these objects"
    chooser instead of `ExileEffect`'s own target-gathering, offering
    every eligible permanent at once (``count=len(candidates)``) with
    ``optional=True`` so the player may stop after any number, including
    zero. Each pick accumulates onto this ability's own source via the
    chooser's ``track_exiled_with=True`` — the same `GameObject.
    exiled_with_ids` list `ExileEffect(track_exiled_with=True)` uses — read
    back by a following ``create_token`` clause's own ``count_selector=
    "exiled_with_count"`` for "a token for each permanent exiled this way",
    and by `ReturnAllExiledWithEffect` (already shipped for Parallax Wave)
    on this permanent's own leaves-battlefield trigger.
    """

    def __init__(self, other_only: bool = True, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.other_only = other_only

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if player is None:
            return
        candidates = [
            obj for obj in context.state.battlefield
            if not obj.is_land and obj.controller_id == player.id
            and (not self.other_only or obj is not source)
        ]
        context.engine.request_choose_objects(
            player, candidates, "exile", count=len(candidates), optional=True,
            prompt=f"{source.name}: Permanente exilieren?",
            source=source, track_exiled_with=True,
        )


class ImprintEffect(GameEffect):
    """"Imprint — When ~ enters, you may exile a `<filter>` card from your
    hand." (MEC-17, Chrome Mox-shaped) — a resolve-time *choice* among the
    controller's own hand, not a RULE 115 target (the printed line carries
    no "target" word at all, matching every other "exile a card from your
    hand" cost/effect in this codebase).

    Reuses `RulesEngine.request_choose_objects`'s general "choose N of
    these objects" chooser (``action="exile"``) rather than a bespoke
    pending_choice — the same primitive Gemstone Caverns' own "exile a
    card from your hand" pregame tail already rides — with its new
    ``remember=True`` stamping the exiled card's own `instance_id` onto
    this permanent (`GameObject.linked_exile_id`, the same field
    `ExileEffect(remember=True)` uses for the unrelated O-Ring return-
    when-leaves shape) so a later mana ability/static can read back
    *which* card got imprinted — see `ManaAbility.color_selector`'s
    ``"imprinted_card_colors"`` kind (`game/mana_abilities.py`).

    ``exclude_card_types`` is Chrome Mox's own "nonartifact, nonland"
    filter — a list of `Card.is_<word>` flag names to exclude, checked
    against each hand card's printed characteristics.
    """

    def __init__(
        self,
        optional: bool = True,
        exclude_card_types: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.optional = optional
        self.exclude_card_types = [str(t).lower() for t in (exclude_card_types or [])]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if player is None:
            return
        candidates = [
            obj for obj in player.hand
            if not any(getattr(obj.card, f"is_{t}", False) for t in self.exclude_card_types)
        ]
        context.engine.request_choose_objects(
            player, candidates, "exile", count=1, optional=self.optional,
            prompt=f"{source.name}: Karte aus der Hand exilieren?",
            source=source, remember=True,
        )


class ChoosePermanentEffect(GameEffect):
    """"As this creature enters, you may choose a nonland permanent."
    (MEC-26, Scheming Fence) — a resolve-time choice stamped onto this
    permanent's own `GameObject.chosen_permanent_id`, the object-choice
    sibling of `ImprintEffect` just above (same `request_choose_objects`
    reuse, a different action — ``"choose_permanent"`` stamps a pointer
    rather than exiling).

    Unlike `ChooseObjectsEffect`'s candidates (always ``permanents_
    controlled_by(player.id)``), "a nonland permanent" is deliberately
    unscoped by controller — Scheming Fence borrows an *opponent's*
    abilities just as readily as its controller's own, so candidates are
    every nonland permanent on the whole battlefield. Choosing this
    permanent itself is a legal (if pointless) pick; `continuous.
    _apply_borrowed_activated_abilities`'s own donor-is-grantee guard makes
    it a no-op rather than something that needs excluding here.
    """

    def __init__(self, optional: bool = True, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.optional = optional

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if player is None:
            return
        candidates = [obj for obj in context.state.permanents() if not obj.is_land]
        context.engine.request_choose_objects(
            player, candidates, "choose_permanent", count=1, optional=self.optional,
            prompt=f"{source.name}: nichtländliches Bleibendes wählen?",
            source=source,
        )


class BounceOwnLandFromTriggerEffect(GameEffect):
    """"Whenever a player casts a spell, that player returns a land they
    control to its owner's hand." (Mana Breach, MEC-43) — "that player" is
    the firing `SPELL_CAST` event's own caster (``player_id``), not this
    ability's controller (the trigger's own subject condition is a bare
    "group", matching *any* player's cast — RULE 603.1). Not a RULE 115
    target (the printed line has no "target" word — it's the caster's own
    choice among their own lands, the same non-targeted shape `ReturnToHand
    Effect`'s ``"land_you_control"`` kind is for a fixed controller), so
    this reuses `RulesEngine.request_choose_objects`'s general chooser
    (``action="return_to_hand"``) with the *triggering* player passed in
    directly instead of this effect's own controller.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event or {}
        player_id = event.get("player_id")
        if player_id is None:
            return
        try:
            player = context.state.player_by_id(player_id)
        except (KeyError, ValueError):
            return
        candidates = [o for o in context.state.permanents_controlled_by(player.id) if o.is_land]
        if not candidates:
            return
        context.engine.request_choose_objects(
            player, candidates, "return_to_hand", count=1, optional=False,
            prompt="Land auf die Hand zurückgeben?",
        )


class FreeCastFromHandEffect(GameEffect):
    """"You may cast a spell with mana value N or less from your hand
    without paying its mana cost." (RULE 601.2f-adjacent — MEC-20, the
    "Expertise" cycle: Kari Zev's/Sram's/Yahenni's/Baral's/Rishkar's
    Expertise, Electrodominance, Epistolary Librarian.

    A resolve-time *choice* among the controller's own hand (RULE 601.3b
    analogue), not a target — none of the printed lines carry "target".
    Opens `RulesEngine.request_choose_objects`'s general chooser with a new
    ``"grant_free_cast"`` action that only *arms* the chosen card's
    `GameState.free_cast_instance_ids` entry rather than casting it
    immediately (unlike the existing ``"cast_free"`` action's
    `RulesEngine.cast_without_paying`, which puts a chosen card straight on
    the stack with no further interaction) — a hand card is already a
    legal cast zone (`can_cast`'s ``in_castable_zone``), so arming the flag
    is enough; the caster then casts it (or doesn't) through the ordinary
    `legal_actions` cast option, getting its full targeting/modal choices
    exactly like `RulesEngine.grant_free_cast_window_from_exile`'s own
    "goes through the ordinary action loop" shape for an *exiled* card.

    ``criteria={"max_mana_value": ...}`` mirrors `SearchLibraryEffect`'s own
    key so the ``"x"`` sentinel `RulesEngine._substitute_x` already walks
    (``filter``/``criteria`` dicts) resolves Electrodominance's own "mana
    value X or less" for free, no separate wiring needed. ``max_mana_value_
    selector`` (Epistolary Librarian's "where X is the number of attacking
    creatures" — a *triggered* ability, never itself cast for an {X} of its
    own) is the `continuous.count_selector` sibling for a cap read off the
    board instead.
    """

    def __init__(
        self,
        criteria: Optional[dict[str, Any]] = None,
        max_mana_value_selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.criteria = dict(criteria or {})
        self.max_mana_value_selector = max_mana_value_selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if player is None:
            return
        if self.max_mana_value_selector:
            from . import continuous  # function-scoped: avoid the continuous<->effects import cycle

            max_mv = continuous.count_selector(
                context.state, player.id, self.max_mana_value_selector, source=source
            )
        else:
            max_mv = self.criteria.get("max_mana_value")
        if not isinstance(max_mv, int):
            return  # an unresolved "x" sentinel or missing cap — nothing legal to offer
        candidates = [
            obj for obj in player.hand
            if not obj.card.is_land and (obj.card.converted_mana_cost or 0) <= max_mv
        ]
        context.engine.request_choose_objects(
            player, candidates, "grant_free_cast", count=1, optional=True,
            prompt=f"{source.name}: Karte kostenlos zaubern?",
            source=source,
        )


class ExileGainLifeToControllerEffect(GameEffect):
    """Exile a target creature; its controller gains life equal to its power
    (RULE 701.5a / 701.5.f-adjacent — Swords to Plowshares-shaped).

    A single atomic effect rather than a separate `ExileEffect` +
    `GainLifeEffect`: the life total depends on the *same* target's power,
    read before it leaves the battlefield, and — as `GainLifeEffect`'s own
    docstring explains — that effect deliberately never reads a shared
    ``targets`` list, so composing two effects here couldn't pass the power
    along anyway. Also handles the target's *own* controller (not
    necessarily the caster) gaining the life, unlike every other life-gain
    effect in this file, which defaults to the effect's controller.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        power = target.power or 0
        controller_id = getattr(target, "controller_id", None)
        context.exile(target)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        if power > 0:
            context.gain_life(player, power)


class ExileAllGraveyardsEffect(GameEffect):
    """"Exile all graveyards." (RULE 406 mass exile, Farewell-shaped) —
    every card in every player's graveyard, untargeted.

    ``colors`` (MEC-43 round 2, Sanctifier en-Vec — "exile all cards that
    are **black or red** from all graveyards") narrows this to a colour
    subset, OR semantics (matching "black or red", not "black and red");
    reads `GameObject.colors` the same way every other colour filter in
    this file does.
    """

    def __init__(
        self, source: Optional["GameObject"] = None, colors: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.colors = {str(c).upper() for c in colors} if colors else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for player in context.players:
            for obj in list(player.graveyard):
                if self.colors and not ((obj.colors or set()) & self.colors):
                    continue
                context.exile(obj)


class ExileGraveyardCardCounterIfPermanentEffect(GameEffect):
    """"{W}: Exile target card from a graveyard. If it was a permanent
    card, put a +1/+1 counter on this permanent." (Lion Sash) — a single
    atomic effect since the counter is conditional on *what* was exiled,
    not a separately-modeled clause."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "any_graveyard_card",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        card = target.card
        is_permanent = bool(
            card.is_creature or card.is_artifact or card.is_enchantment
            or card.is_land or getattr(card, "is_planeswalker", False)
        )
        context.exile(target)
        if is_permanent and self.source is not None:
            context.add_counters(self.source, 1, "+1/+1", source=self.source)


class ExileGraveyardCreaturesGainLifeEffect(GameEffect):
    """"Exile all creature cards from target player's graveyard. You gain 3
    life for each card exiled this way." (Crypt Incursion)."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
        life_per_card: int = 3,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.life_per_card = life_per_card
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        creatures = [o for o in list(player.graveyard) if o.card.is_creature]
        for obj in creatures:
            context.exile(obj)
        if creatures:
            controller = _controller_of(self.source, context)
            if controller is not None:
                context.gain_life(controller, self.life_per_card * len(creatures))


class ExileTargetGraveyardEffect(GameEffect):
    """"Exile target player's graveyard." (Bojuka Bog/Tormod's Crypt-shaped)
    — every card in that one graveyard, untargeted per-card unlike
    `_exile_from_graveyard`'s single-card family; the untargeted "every
    graveyard" sibling is `ExileAllGraveyardsEffect` above."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        for obj in list(player.graveyard):
            context.exile(obj)


class DestroyLoseLifeEqualManaValueEffect(GameEffect):
    """"Destroy target creature or enchantment an opponent controls. You
    lose life equal to that permanent's mana value." (Feed the Swarm) — a
    single atomic effect since the life total depends on the target's own
    mana value, read before it leaves the battlefield, mirroring
    `ExileGainLifeToControllerEffect`'s "read the target's own
    characteristic, then move it" shape. ``target_kind="permanent"``
    (broader than "creature or enchantment an opponent controls" — no
    target kind unions two card types *and* restricts to opponents at
    once) is the same documented simplification `_TARGET_ROWS`'s "target
    artifact or enchantment" → ``"permanent"`` row already uses elsewhere;
    the life-loss always hits the *caster*, not the target's controller,
    unlike `ExileGainLifeToControllerEffect`.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        mana_value = target.card.converted_mana_cost
        context.destroy(target)
        controller = _controller_of(self.source, context)
        if controller is not None and mana_value:
            context.lose_life(controller, mana_value)


class ExileCreateTokenEffect(GameEffect):
    """"Exile target artifact or creature. Its controller creates a 4/4
    blue and red Elemental creature token." (Resculpt) — a single atomic
    effect: the token goes to the *exiled permanent's own controller*
    (unlike `CreateTokenEffect`, which always creates under the effect's
    own source's controller), so the target's controller must be read
    before/alongside exiling it, the same "read something off the target,
    then act" shape `ExileGainLifeToControllerEffect` uses for life gain
    instead of a token.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        token_name: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.token_name = token_name or (subtypes[0] if subtypes else "Token")

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..services.token_database import synthesize_token_card

        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.exile(target)
        if controller_id is None:
            return
        card = synthesize_token_card(
            self.token_name, power=self.power, toughness=self.toughness,
            colors=self.colors, subtypes=self.subtypes,
        )
        context.create_token(controller_id, card, 1)


class DestroyCreateTokenEffect(GameEffect):
    """"Destroy target permanent. Its controller creates a 3/3 green Beast
    creature token." (Beast Within) — `ExileCreateTokenEffect`'s destroy-
    instead-of-exile sibling: the token still goes to the *destroyed
    permanent's own controller*, read before it leaves the battlefield,
    same "read something off the target, then act" shape.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        token_name: Optional[str] = None,
        can_be_regenerated: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.token_name = token_name or (subtypes[0] if subtypes else "Token")
        self.can_be_regenerated = can_be_regenerated

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..services.token_database import synthesize_token_card

        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.destroy(target, can_be_regenerated=self.can_be_regenerated)
        if controller_id is None:
            return
        card = synthesize_token_card(
            self.token_name, power=self.power, toughness=self.toughness,
            colors=self.colors, subtypes=self.subtypes,
        )
        context.create_token(controller_id, card, 1)


class DestroyGainLifeToControllerEffect(GameEffect):
    """"Destroy target artifact or enchantment. Its controller gains 4
    life." (Nature's Claim-shaped) — a fixed life amount, unlike
    `ExileGainLifeToControllerEffect`'s "equal to its power"; still a single
    atomic effect since the life goes to the *target's own controller*
    (read before it leaves the battlefield), not the caster.
    ``target_kind="permanent"`` (broader than "artifact or enchantment" — no
    target kind unions two card types) is the same documented `_TARGET_
    ROWS` simplification `DestroyLoseLifeEqualManaValueEffect` already uses.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        amount: int = 0,
        can_be_regenerated: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)
        self.amount = amount
        self.can_be_regenerated = can_be_regenerated

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.destroy(target, can_be_regenerated=self.can_be_regenerated)
        if controller_id is None or not self.amount:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        context.gain_life(player, self.amount)


class DestroyExileThenControllerRevealCreatureEffect(GameEffect):
    """"Destroy/Exile target creature. It can't be regenerated
    [destroy mode only]. Its controller reveals cards from the top of
    their library until they reveal a creature card. [That/The] player
    puts that card onto the battlefield, then shuffles [all other cards
    revealed this way/the rest] into their library." (Polymorph/
    Transmogrify-shaped) — one atomic effect, not a two-effect list,
    since the dig is run by the *target's own controller* (read before the
    removal — RULE 400.7's zone change would otherwise leave nothing to
    read a controller off of once it's in the graveyard/exile) rather than
    this ability's own controller, the same "read before it leaves the
    battlefield" idiom `DestroyGainLifeToControllerEffect` already uses.

    ``mode`` picks destroy (``can_be_regenerated=False``, Polymorph) or
    exile (Transmogrify, which has no regeneration clause to carry since
    exile was never regenerable in the first place).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        mode: str = "destroy",
        criteria: Any = "Creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)
        self.mode = mode
        self.criteria = criteria

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        if self.mode == "exile":
            context.exile(target)
        else:
            context.destroy(target, can_be_regenerated=False)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        context.engine.dig_until(
            player, self.criteria,
            hit_destination="battlefield", rest_destination="library_shuffled",
        )


class GainControlUntilEndOfTurnEffect(GameEffect):
    """"Gain control of target permanent until end of turn. Untap that
    permanent. It gains haste until end of turn." (RULE 108.4-adjacent —
    Zealous Conscripts/Coercive Recruiter-shaped) — a single atomic effect
    bundling the control change, the untap, and the haste grant (every real
    printed instance of this exact clause pairs all three on the *same*
    target), rather than composing 3 separate targeting effects that would
    each need their own copy of the shared target (the "two targeting
    effects double-prompt" reason `TargetPlayerDrawLoseLifeEffect`'s
    docstring gives — no plain `pump`/keyword-grant effect can reach the
    exact object this one just changed control of without `target_groups`
    machinery no real card here needs). Reverts control automatically at
    the next cleanup (`GameEngine._step_cleanup`, `GameObject.control_
    change_until_eot` remembers the original controller) — the haste grant
    is a `temp_keywords` entry, cleared at that same cleanup, matching
    "until end of turn" exactly. RULE 302.6's own "summoning sickness
    resets under a new controller" isn't separately modeled, since the
    haste grant makes the distinction unobservable either way. Doesn't move
    the object zones at all (unlike `blink`), so counters/attachments/
    damage marked all carry over exactly as the permanent itself would
    expect.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        haste: bool = True,
        max_mana_value: Optional[int] = None,
        selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "Untap **all creatures** and gain control of them until end of
        #: turn." (Insurrection) — the untargeted RULE 601.2c mass sibling
        #: of the single-target form above, same ``_mass_selector_objects``
        #: vocabulary `DestroyEffect.selector` uses. Only ``"all_creatures"``
        #: is meaningful here (no real card needs a different mass filter),
        #: but the param is named/shaped like every other mass effect's for
        #: consistency.
        self.selector = selector
        if self.selector is None:
            #: "Gain control of target creature **with mana value 3 or
            #: less**" (Claim the Firstborn) — a target-offer-time cap, the
            #: same `TargetSpec.max_mana_value` `DestroyEffect`/`destroy_mv`
            #: already use.
            self.target_spec = TargetSpec(kind=target_kind, max_mana_value=max_mana_value)
        self.haste = haste

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def _take(self, context: GameContext, target: "GameObject", controller: "Player") -> None:
        if target.controller_id != controller.id:
            if target.control_change_until_eot is None:
                target.control_change_until_eot = target.controller_id
            target.controller_id = controller.id
        context.set_tapped(target, tapped=False)
        if self.haste:
            target.temp_keywords.add("haste")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        if self.selector is not None:
            for obj in _mass_selector_objects(context, self.selector, None):
                self._take(context, obj, controller)
            context.recompute()
            return
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        self._take(context, target, controller)
        context.recompute()


class GainControlBySourceEffect(GameEffect):
    """"An opponent gains control of ~." (RULE 701.10-adjacent — Wishclaw
    Talisman-shaped: an activated ability that hands its own permanent away
    as a drawback, rather than the caster grabbing something). Unlike
    `GainControlUntilEndOfTurnEffect` (temporary, a chosen *target*, control
    moves *to* the ability's controller), this is indefinite, always the
    source itself, moves control *away* from the controller, and isn't a
    RULE 115 target at all — the printed line never says "target opponent".

    ``recipient="opponent"`` is the only kind today. With exactly one
    opponent (the common 1v1 goldfish/Replay case) the pick is unambiguous;
    with 2+ (multiplayer), this auto-picks the next player after the
    current controller in seating order — no "choose an opponent" chooser
    exists yet for a *player* (`request_choose_objects` only offers
    `GameObject` candidates), the same "auto-pick, no chooser in this MVP"
    idiom `put_hand_cards_on_top` already documents for a value-neutral
    selection among equally-valid choices.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        recipient: str = "opponent",
    ) -> None:
        super().__init__(source)
        self.recipient = recipient
        self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        players = context.state.players
        opponents = [p for p in players if p.id != controller.id]
        if not opponents:
            return
        idx = players.index(controller)
        ordered = players[idx + 1:] + players[:idx]
        recipient = next((p for p in ordered if p in opponents), opponents[0])
        self.source.controller_id = recipient.id
        context.recompute()


class ReturnLinkedExileEffect(GameEffect):
    """"When this leaves the battlefield, return the exiled card to the
    battlefield under its owner's control." (Leonin Relic-Warder/O-Ring-
    shaped) — the return half of an `ExileEffect(remember=True)` pair:
    reads the linked card's ``instance_id`` off this ability's own source
    (stamped by the earlier ETB exile, survives however long the card
    stays exiled) rather than a RULE 115 target — nothing was ever chosen
    here, "the exiled card" is a fixed reference. A no-op if nothing is
    currently linked (the "may exile" ETB was declined) or the linked card
    already left exile some other way (bounced back by a third effect,
    etc.).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        linked_id = getattr(self.source, "linked_exile_id", None)
        self.source.linked_exile_id = None
        if linked_id is None:
            return
        card_obj = context.state.find_object(linked_id)
        if card_obj is None or card_obj.zone != Zone.EXILE:
            return
        context.return_from_graveyard(card_obj, "battlefield")


class ReturnAllExiledWithEffect(GameEffect):
    """"When this leaves the battlefield, each player returns to the
    battlefield all cards they own exiled with it." (MEC-12, Parallax
    Wave/Abdel Adrian, Gorion's Ward-shaped) — the mass sibling of
    `ReturnLinkedExileEffect`: reads `GameObject.exiled_with_ids` (MEC-21's
    accumulating tracker, stamped by `ExileEffect(track_exiled_with=True)`)
    instead of the single-slot `linked_exile_id`, since a repeatable
    "remove a counter: exile target creature"-shaped ability can link
    arbitrarily many cards over the source's lifetime, potentially owned
    by several different players. Each returns under **its own owner's**
    control (`return_from_graveyard`'s default), not this source's
    controller — "each player" in the printed text, not "you".
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        ids = list(getattr(self.source, "exiled_with_ids", None) or [])
        self.source.exiled_with_ids = []
        for instance_id in ids:
            card_obj = context.state.find_object(instance_id)
            if card_obj is None or card_obj.zone != Zone.EXILE:
                continue
            context.return_from_graveyard(card_obj, "battlefield")


class CreateTokenForLinkedExileEffect(GameEffect):
    """"When this creature leaves the battlefield, the exiled card's owner
    creates an X/X `<colors>` `<subtypes>` creature token, where X is the
    mana value of the exiled card." (MEC-12, Skyclave Apparition) — reads
    the linked card (`GameObject.linked_exile_id`, the same O-Ring-shaped
    field `ExileEffect(remember=True)`/`ReturnLinkedExileEffect` use) one
    last time for its owner and mana value, then hands off to the ordinary
    token-creation choke point (`GameContext.create_token`) under *that*
    owner's control — unlike every `CreateTokenEffect` caller, the
    recipient here is neither "you" nor a fixed "each_player"/
    "each_opponent" but whoever happens to own the specific card that was
    exiled. A no-op if nothing is linked (the "up to one" ETB was
    declined) — matching `ReturnLinkedExileEffect`'s own treatment of that
    case — or if the linked card has since left exile some other way.
    """

    def __init__(
        self,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.keywords = keywords or []

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        linked_id = getattr(self.source, "linked_exile_id", None)
        self.source.linked_exile_id = None
        if linked_id is None:
            return
        card_obj = context.state.find_object(linked_id)
        if card_obj is None or card_obj.zone != Zone.EXILE:
            return
        from ..services.token_database import synthesize_token_card

        x = int(card_obj.card.converted_mana_cost or 0)
        token_card = synthesize_token_card(
            self.subtypes[0] if self.subtypes else "Token",
            power=x, toughness=x, colors=self.colors, subtypes=self.subtypes, keywords=self.keywords,
        )
        made = context.create_token(card_obj.owner_id, token_card) or []
        context.created_objects.extend(made)


class ExileOwnGraveyardCardManaValueXEffect(GameEffect):
    """"Exile target creature card with mana value X from your graveyard.
    ..." (Lazotep Quarry, MEC-41's own ``{X}{2}, {T}, Sacrifice a Desert:``
    activated ability) — opens a `request_choose_objects` pick among the
    controller's own graveyard creature cards whose mana value equals the
    source's own announced ``{X}`` (`GameObject.x_paid`, now stamped for an
    ability's own source too — see `GameEngine.activate_ability`).

    **Documented simplification**: RULE 115's "target" is read as this
    resolve-time pick instead. A genuine RULE 115 target here would need X
    threaded into `legal_targets` *before* targets are gathered (RULE
    601.2b announces X ahead of RULE 602.2b's targets) — no activated
    ability in this engine does that yet (`GameEngine._ability_target_
    requirements` computes every requirement's legal options with no X
    known), and building that sequencing for one card's own graveyard-only
    pick (where hexproof/protection/an opponent's response don't apply
    regardless) is disproportionate. ``then_specs`` fires once a pick is
    made, via ``remember=True``'s `GameObject.linked_exile_id`.
    """

    def __init__(
        self,
        creature_only: bool = True,
        then_specs: Optional[list[dict]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.creature_only = creature_only
        self.then_specs = list(then_specs or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        x = getattr(self.source, "x_paid", 0) or 0
        candidates = [
            o for o in player.graveyard
            if (o.is_creature or not self.creature_only)
            and o.card.converted_mana_cost == x
        ]
        context.engine.request_choose_objects(
            player, candidates, "exile", count=1, source=self.source,
            remember=True, then_specs=self.then_specs,
        )


class CreateTokenCopyOfLinkedExileEffect(GameEffect):
    """The token-*copy* sibling of `CreateTokenForLinkedExileEffect` just
    above: makes a token that's a genuine copy of the linked exiled card's
    own printed characteristics (RULE 707.2) instead of a synthesized X/X,
    reusing the same override vocabulary `CopyPermanentEffect` already
    exposes (``set_power``/``set_toughness``/``add_subtypes``). Lazotep
    Quarry's own "... Create a token that's a copy of it, except it's a 4/4
    ... Zombie." (MEC-41), paired with `ExileOwnGraveyardCardManaValueX
    Effect`'s own ``remember=True`` pick.

    Colour ("black") is dropped, the same documented simplification The
    Jolly Balloon Man's own catalogue entry accepts — `Card.as_copy` has no
    colour-override mechanism (CLAUDE.md's own documented gotcha).
    """

    def __init__(
        self,
        set_power: Optional[int] = None,
        set_toughness: Optional[int] = None,
        add_subtypes: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.set_power = set_power
        self.set_toughness = set_toughness
        self.add_subtypes = add_subtypes

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        linked_id = getattr(self.source, "linked_exile_id", None)
        self.source.linked_exile_id = None
        if linked_id is None:
            return
        card_obj = context.state.find_object(linked_id)
        if card_obj is None or card_obj.zone != Zone.EXILE:
            return
        controller_id = self.source.controller_id
        made = context.engine.copy_permanent(
            controller_id, card_obj, set_power=self.set_power,
            set_toughness=self.set_toughness, add_subtypes=self.add_subtypes,
        )
        context.created_objects.extend(made or [])


class ChooseVoidCounterCardEffect(GameEffect):
    """"Choose an exiled card an opponent owns with a void counter on it.
    You may play it this turn without paying its mana cost." (Dauthi
    Voidwalker, MEC-42) — gathers the live candidate pool (any card in an
    *opponent's* exile zone still carrying `GameState.void_counter_
    holder`, stamped by `continuous.void_counter_redirect_controller_for`'s
    standing replacement) and opens the already-general chooser via the
    ``"grant_free_cast"`` action (MEC-20's "arm a temporary, same-turn
    free-cast window" shape) — just over a different candidate pool than
    that action's own hand-zone origin.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        candidates = [
            obj
            for other in context.state.players
            if other.id != player.id
            for obj in other.exile
            if obj.instance_id in context.state.void_counter_holder
        ]
        if not candidates:
            return
        context.engine.request_choose_objects(
            player, candidates, "grant_free_cast", count=1, optional=True, source=self.source,
        )


class ExileLibraryEffect(GameEffect):
    """"Exile all cards from your library." (Paradigm Shift-shaped) — an
    untargeted, hidden-zone-to-exile mass move: a library's contents are
    never legal RULE 115 targets, and `ExileEffect.selector`'s mass-board-
    wipe vocabulary only ever reads the *battlefield*, so this is its own
    effect rather than a reused selector.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in list(player.library):
            context.exile(obj)


class ShuffleGraveyardIntoLibraryEffect(GameEffect):
    """"Shuffle your graveyard into your library." (RULE 701.20) — the
    graveyard-only sibling of `RulesEngine.shuffle_hand_and_graveyard_
    into_library`'s "hand AND graveyard" wheel template; reused wherever
    only the graveyard moves (Paradigm Shift).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in list(player.graveyard):
            player.remove_from_zone(obj, Zone.GRAVEYARD)
            player.add_to_zone(obj, Zone.LIBRARY)
        context.shuffle_library(player)


class GraveyardToLibraryBottomRandomEffect(GameEffect):
    """"Up to one target player puts all the cards from their graveyard on
    the bottom of their library in a random order." (Endurance-shaped) —
    RULE 701.20-adjacent; unlike a plain `shuffle_library` call (which
    randomizes the *whole* library), this only randomizes the moved batch's
    own relative order among themselves before appending it to the bottom,
    leaving the existing library order above them untouched.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        moved = list(player.graveyard)
        if not moved:
            return
        random.shuffle(moved)
        for obj in moved:
            player.remove_from_zone(obj, Zone.GRAVEYARD)
        for obj in moved:
            player.library.insert(0, obj)
            obj.zone = Zone.LIBRARY


class ReturnToHandDrawIfControlledEffect(GameEffect):
    """"Return target nonland permanent to its owner's hand. If you
    controlled that permanent, draw a card." (Geistwave-shaped) — a single
    atomic effect: the draw is conditioned on the target's own controller,
    read *before* it leaves the battlefield, mirroring
    `ExileGainLifeToControllerEffect`'s "read something off the target,
    then act" shape (composing two separate `EffectSpec`s here couldn't
    check the target's controller after `ReturnToHandEffect` already moved
    it, the same reason that effect's docstring gives for not splitting its
    own life-gain out).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "nonland_permanent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller = _controller_of(self.source, context)
        you_controlled_it = controller is not None and target.controller_id == controller.id
        context.return_to_hand(target)
        if you_controlled_it and controller is not None:
            context.draw(controller, 1)


class TopUpPlayerCounterToThresholdEffect(GameEffect):
    """"If target player has fewer than N [kind] counters, they get a
    number of [kind] counters equal to the difference." (Vraska,
    Betrayal's Sting's -9) — a threshold top-up rather than a flat amount;
    a player already at or past the threshold gets none.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
        kind: str = "poison",
        threshold: int = 9,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.kind = kind
        self.threshold = threshold
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        current = getattr(player, self.kind, None)
        if current is None:
            current = player.counters.get(self.kind, 0)
        diff = self.threshold - int(current or 0)
        if diff > 0:
            context.add_player_counters(player, diff, self.kind, source=self.source)


class TransformNamedTokensEffect(GameEffect):
    """"Transform all Incubator tokens you control." (Glissa, Herald of
    Predation) — applies the same permanent creature-animation every
    Incubator token's own "{2}: Transform this token" ability does
    (`type_change`'s existing power/toughness-animation static, granted
    at ``duration="rest_of_game"``) to every matching token at once, for
    free, rather than one at a time through its own activated ability.
    An already-transformed (already-creature) token is skipped — nothing
    left to transform.
    """

    def __init__(
        self,
        token_name: str = "Incubator",
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        power: int = 0,
        toughness: int = 0,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.token_name = token_name
        self.add_types = list(add_types or ["creature"])
        self.add_subtypes = list(add_subtypes or [])
        self.power = power
        self.toughness = toughness

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        for obj in list(context.state.battlefield):
            if not (
                obj.controller_id == controller_id
                and obj.card.is_token
                and obj.card.name == self.token_name
                and not obj.is_creature
            ):
                continue
            GrantUntilEffect(
                static={
                    "type": "type_change",
                    "params": {
                        "add_types": self.add_types, "add_subtypes": self.add_subtypes,
                        "power": self.power, "toughness": self.toughness,
                    },
                },
                duration="rest_of_game",
                target_kind=None,
                source=obj,
            ).apply(context)


class EachOpponentCounterOwnCreatureEffect(GameEffect):
    """"Each opponent blights N. (They each put N -1/-1 counters on a
    creature they control.)" (High Perfect Morcant) — RULE 122's per-
    opponent fan-out: each opponent independently puts the counters on a
    creature they control. **Documented simplification**: auto-picked (the
    first creature found) rather than routed through a real per-opponent
    chooser — the same "not worth a chooser for a single pick" convention
    `SacrificeEffect.greatest_power` already uses; an opponent with no
    creature simply gets nothing.
    """

    def __init__(
        self, amount: int = 1, kind: str = "-1/-1", source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.kind = kind

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller_id = getattr(self.source, "controller_id", None)
        for player in context.state.living_players():
            if player.id == controller_id:
                continue
            creatures = [o for o in context.state.permanents_controlled_by(player.id) if o.is_creature]
            if creatures:
                context.add_counters(creatures[0], self.amount, self.kind, source=self.source)


class DamageThenInvestigateIfExcessEffect(GameEffect):
    """"~ deals twice X damage to target creature. If excess damage was
    dealt to that creature this way, investigate." (Torch the Witness) —
    RULE 120.9's "excess damage" (more than needed to be lethal): the
    dealt amount compared against the target's toughness net of damage
    already marked, read *before* this damage lands — a single atomic
    effect since the check needs that pre-damage snapshot, not the
    post-damage `GameObject.damage_marked` total (which could already
    include unrelated damage from earlier this turn).
    """

    def __init__(
        self, target: Any = None, source: Optional["GameObject"] = None, target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        x_paid = getattr(self.source, "x_paid", 0) or 0
        amount = x_paid * 2
        remaining = (target.toughness or 0) - target.damage_marked
        context.deal_damage(target, amount, self.source)
        if amount > max(remaining, 0):
            player = _controller_of(self.source, context)
            if player is not None:
                from ..services.token_database import default_token_database

                clue = default_token_database().get_token("Clue")
                if clue is not None:
                    context.create_token(player.id, clue, 1)


class ArmSpellWatcherEffect(GameEffect):
    """"When you next cast an instant or sorcery spell with mana value N
    or less this turn, `<effect>`." (Dual Strike) — the resolve-time
    trigger for `RulesEngine.arm_spell_watcher`; see `GameState.
    spell_watchers`'s docstring for the mechanism itself.
    """

    def __init__(
        self,
        then_specs: Optional[list[dict]] = None,
        max_mana_value: Optional[int] = None,
        card_types: Optional[list[str]] = None,
        repeat: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.then_specs = list(then_specs or [])
        self.max_mana_value = max_mana_value
        self.card_types = card_types
        #: "**Spells you control** can't be countered this turn." (Veil of
        #: Summer) — every matching spell for the rest of the turn, not
        #: just the next one; see `RulesEngine.arm_spell_watcher`'s own
        #: docstring.
        self.repeat = repeat

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.arm_spell_watcher(
            player, self.then_specs, self.source,
            max_mana_value=self.max_mana_value, card_types=self.card_types,
            repeat=self.repeat,
        )


class ExileHandThenDrawThatManyEffect(GameEffect):
    """"Exile all cards from your hand, then draw that many cards."
    (Invasion of Kaldheim) — a plain hand refill/filter. **Documented
    simplification**: the trailing "until the end of your next turn, you
    may play cards exiled this way" isn't modeled — no primitive grants a
    *set* of specific exiled cards a multi-turn play window the way
    `ImpulsiveDrawEffect` does for a *library* exile; the cards are simply
    gone.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        count = len(player.hand)
        for card in list(player.hand):
            context.exile(card)
        if count:
            context.draw(player, count)


class ExileTopFromEachPlayerCastFreeEffect(GameEffect):
    """"Exile the top card of each player's library, then you may cast any
    number of spells from among those cards without paying their mana
    costs." (Etali, Primal Storm) — reuses `RulesEngine.grant_free_cast_
    window_from_exile` (Rebound/Beseech the Mirror's own "cast from exile
    free" window) per exiled card, one per player, all opened for *this*
    effect's own controller (RAW: "**you** may cast any number of spells
    from among those cards" — not each card's owner) rather than the
    method's own default of the card's ``controller_id``, so a control
    reassignment happens first.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for p in context.state.living_players():
            if not p.library:
                continue
            card = p.library[-1]
            context.exile(card)
            card.controller_id = player.id
            context.engine.grant_free_cast_window_from_exile(card)


class GrantDieToExileThisTurnEffect(GameEffect):
    """"If that creature would die this turn, exile it instead." (Lava
    Coil/Smite the Deathless/Torch the Tower-shaped) — the resolve-time,
    single-target, single-turn sibling of `ReplacementRegistry`'s standing
    ``"die_to_exile"`` (a *permanent*'s own printed ability, scoped by
    ``subject`` off ``effect.source``). This instead appends a fresh
    `ReplacementEffect` straight onto the target's own `GameObject.
    replacement_effects` — the same "just add to the list" idiom a bind-
    on-load ability normally arrives by — with the turn number baked into
    its condition at grant time so it expires on its own once the turn
    moves on, no `GameState.floating_statics`/duration-sweep machinery
    needed for a grant this narrow.
    """

    def __init__(
        self, target: Any = None, source: Optional["GameObject"] = None, target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        armed_turn = context.state.turn_number
        target_id = target.instance_id

        def _condition(e: GameEvent, c: GameContext, turn=armed_turn, tid=target_id) -> bool:
            return c.state.turn_number == turn and e.get("target_id") == tid

        def _replace(e: GameEvent, c: GameContext) -> Optional[GameEvent]:
            obj = c.state.find_object(e.get("target_id"))
            if obj is not None:
                c.engine.exile(obj)
            return None

        target.replacement_effects.append(
            ReplacementEffect(
                event_type=EventType.WOULD_DIE,
                replacement_fn=_replace,
                condition=_condition,
                description="exile instead of dying this turn",
            )
        )


class TriggerDoublerEffect(GameEffect):
    """"If a triggered ability of another creature you control of the
    chosen type triggers, it triggers an additional time." (Roaming
    Throne, RULE 603.3d) — a continuous marker like `TopLibraryPermission
    Effect`/`CantBeCounteredEffect` above: no layer/characteristic
    behaviour of its own (``apply()`` is a no-op), just something
    `game/rules/triggers_mixin.py`'s `_collect_triggers` scans for
    (`continuous.trigger_doubler_bonus`) when deciding how many times to
    place a *different* permanent's triggered ability on the stack. "The
    chosen type" is this effect's own source's `GameObject.chosen_type`
    (RULE 601.2b), read live so a Replay/Puzzle-mode change to the choice
    is honoured immediately.

    ``cause_filter`` (Elesh Norn, Mother of Machines, MEC-40 — "If a
    permanent entering causes a triggered ability of a permanent you
    control to trigger, that ability triggers an additional time.") is an
    alternative scoping axis: instead of narrowing *which permanent's*
    triggers double (by creature type, the ``chosen_type`` gate above),
    it narrows *which firing event* doubles (one `EventType`, or a list —
    Gandalf the White's "entering **or leaving**" — matched against the
    very event that caused the trigger), unscoped by the doubled
    permanent's own type — matching the printed "**a** triggered ability",
    not "a triggered ability of an Elf". The two axes are mutually
    exclusive per instance: a ``cause_filter`` doubler skips the
    ``chosen_type`` gate entirely (`continuous.trigger_doubler_bonus`).

    ``cause_type_filter`` (Gandalf the White) additionally narrows *which
    permanent* caused the event — "if a **legendary permanent or an
    artifact** entering or leaving…" — a closed word list
    ("legendary"/"artifact"), union semantics, checked against the causing
    object named by the event's own ``instance_id``.

    ``min_power``/``max_power`` (MEC-43 round 2, Delney, Streetwise
    Lookout — "a triggered ability of a creature you control **with power
    2 or less** triggers") is a third, independent scoping axis alongside
    ``chosen_type``/``cause_filter``: a live board-state gate on the
    doubled permanent's own current power instead of its type or the
    firing event's shape (`continuous.trigger_doubler_bonus`).
    """

    def __init__(
        self,
        cause_filter: Optional[Union[str, list[str]]] = None,
        cause_type_filter: Optional[list[str]] = None,
        min_power: Optional[int] = None,
        max_power: Optional[int] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        if cause_filter is None or isinstance(cause_filter, (list, tuple)):
            self.cause_filter = tuple(cause_filter) if cause_filter else None
        else:
            self.cause_filter = (cause_filter,)
        self.cause_type_filter = (
            [str(w).lower() for w in cause_type_filter] if cause_type_filter else None
        )
        self.min_power = min_power
        self.max_power = max_power

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class GrantFlashUntilEndOfTurnEffect(GameEffect):
    """"You may cast spells this turn as though they had flash." (Borne
    Upon a Wind-shaped) — stamps `GameState.temp_flash_until_turn` for the
    effect's controller, consulted by `GameEngine.can_cast`'s sorcery-speed
    timing gate; naturally expires once the turn number advances, no
    cleanup-step bookkeeping needed (unlike the `temp_*` `GameObject`
    fields `_step_cleanup` clears).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.state.temp_flash_until_turn[player.id] = context.state.turn_number


class ExileControllerSearchesBasicLandEffect(GameEffect):
    """"Exile target creature you don't control. For each creature exiled
    this way, its controller searches their library for a basic land
    card. Those players put those cards onto the battlefield tapped, then
    shuffle." (Winds of Abandon, single-target cast — Overload's "each
    opponent" rewrite isn't modeled, see the catalogue entry) — the search
    is offered to the *exiled creature's own controller*, not the caster,
    the same target-controller resolution `ExileCreateTokenEffect` uses.
    ``target_kind="creature"`` (broader than "you don't control" — no
    target kind carries an ownership exclusion yet) is a documented
    simplification, mirroring `ExileControllerSearchesBasicLandEffect`'s
    siblings elsewhere in this file.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.exile(target)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        context.request_search(player, {"basic": True}, "battlefield_tapped", 1, False)


class DestroyControllerMaySearchBasicLandEffect(GameEffect):
    """"Destroy target artifact, enchantment, or nonbasic land an opponent
    controls. That player may search their library for a land card with a
    basic land type, put it onto the battlefield, then shuffle." (Boseiju,
    Who Endures's Channel ability) — `ExileControllerSearchesBasicLandEffect`'s
    destroy-shaped sibling: destroy (so RULE 616 indestructible/regeneration
    still applies, unlike exile) rather than exile, the search is *optional*
    and untapped rather than Winds of Abandon's mandatory tapped one, and
    "a land card with a basic land type" (any land carrying a basic land
    type, not only a true basic) is `request_search`'s own criteria dict.
    ``target_kind`` drops the "an opponent controls" restriction — no target
    kind carries an ownership exclusion yet, the same documented
    simplification `ExileControllerSearchesBasicLandEffect` uses.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "artifact_enchantment_or_nonbasic_land",
        can_be_regenerated: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.can_be_regenerated = can_be_regenerated
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.destroy(target, can_be_regenerated=self.can_be_regenerated)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        context.request_search(
            # "a land card with a basic land type" — `card_query`'s "basic"
            # criterion (RULE 205.4h supertype) rather than a stricter
            # basic-land-*type* check; the two coincide for every real card
            # in this cache, the same simplification precedent Winds of
            # Abandon's own basic-land search uses.
            player, {"basic": True}, "battlefield", 1, True,
        )


class ReturnTopGraveyardCreatureWithHasteEffect(GameEffect):
    """Return the top creature card of your graveyard to the battlefield;
    that creature gains haste until end of turn (Corpse Dance). A single
    atomic effect, not `ReturnFromGraveyardEffect` (a RULE 115 *target*)
    plus a separate haste grant: the "top card" pick is untargeted/
    positional (the graveyard's own insertion order — the most recently
    added card is "on top"), and "that creature" refers to the exact object
    this same effect just returned — no shared targets-list slot for a
    second effect to reach it, the same "read/act on what I just did" shape
    `LivingWeaponEffect` uses for its own token-then-attach.

    ``delayed_exile_step`` is Corpse Dance's trailing "Exile it at the
    beginning of the next end step." — armed here rather than as a separate
    spec effect for the same "that creature" reason: `CreateDelayedTrigger
    Effect` bakes its targets in at arm time, and only *this* effect knows
    which object was returned. ``scope="any"`` matches "the **next** end
    step", whoever's turn it is.
    """

    def __init__(
        self,
        delayed_exile_step: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.delayed_exile_step = delayed_exile_step

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..models.game_state import DelayedTrigger

        player = _controller_of(self.source, context)
        if player is None:
            return
        creature = next((o for o in reversed(player.graveyard) if o.card.is_creature), None)
        if creature is None:
            return
        context.return_from_graveyard(creature, "battlefield")
        creature.temp_keywords.add("haste")
        if self.delayed_exile_step:
            context.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=player.id,
                    step=self.delayed_exile_step,
                    scope="any",
                    effects=[ExileEffect(target_kind=None, source=self.source)],
                    targets=[creature],
                    description=f"{creature.name}: im nächsten Endsegment exilieren",
                )
            )
        context.recompute()


class TargetPlayerDrawLoseLifeEffect(GameEffect):
    """"Target player draws N cards and loses M life." (Sign in Blood-shaped)
    — a single atomic effect over one shared target, since two independent
    `DrawCardEffect`/`LoseLifeEffect` objects each carrying their own
    ``target_kind`` would offer *two* separate target choices instead of
    one (docs/11 §5's "at most one targeting effect per ability" limit)."""

    def __init__(
        self,
        draw_count: int = 1,
        life_loss: int = 0,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
    ) -> None:
        super().__init__(source)
        self.draw_count = draw_count
        self.life_loss = life_loss
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        context.draw(player, self.draw_count)
        context.lose_life(player, self.life_loss)


class CounterAndFirstStrikeEffect(GameEffect):
    """"Put a +1/+1 counter on up to one target creature. It gains first
    strike until end of turn." (The Wandering Emperor's +1) — a single
    atomic effect over one shared target, the same "two targeting effects
    would double-prompt" reason `TargetPlayerDrawLoseLifeEffect` exists."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        context.add_counters(target, 1, "+1/+1", source=self.source)
        target.temp_keywords.add("first_strike")
        context.recompute()


class CounterUntapGrantKeywordEffect(GameEffect):
    """"Put a +1/+1 counter on up to one target Elf. Untap it. It gains
    deathtouch until end of turn." (Tyvar Kell's +1) — a single atomic
    effect over one shared target, the same "two targeting effects would
    double-prompt" reason `CounterAndFirstStrikeEffect` exists; generalizes
    it with an untap step and a caller-chosen keyword instead of a fixed
    first-strike grant.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        optional: bool = True,
        creature_filter: Optional[dict[str, Any]] = None,
        keyword: str = "deathtouch",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.keyword = keyword
        self.target_spec = TargetSpec(
            kind=target_kind, optional=optional, creature_filter=creature_filter,
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        context.add_counters(target, 1, "+1/+1", source=self.source)
        context.set_tapped(target, tapped=False)
        target.temp_keywords.add(self.keyword)
        context.recompute()


class PeekTopLandBattlefieldTappedEffect(GameEffect):
    """"Look at the top card of your library. If it's a land card, you may
    put it onto the battlefield tapped." (Explorer's Scope) — an "impulse
    peek", distinct from Sword of the Animist's own unconditional library
    *search* for a basic land."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        if top.card.is_land:
            context.engine._put_searched_card(player, top, "battlefield_tapped")


class CreateTokenMayAttachEquipmentEffect(GameEffect):
    """Create a token, then optionally attach a *targeted* Equipment you
    control to it (Nahiri, Heir of the Ancients' +1) — the attach target is
    a real RULE 115 choice (unlike Living Weapon's own token, which always
    self-attaches), so this carries a `target_spec` the way `AttachEffect`
    does, just resolving onto the token this same effect just created
    rather than the effect's own source.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "equipment_you_control",
        optional: bool = True,
        token_name: str = "token",
        power: int = 1,
        toughness: int = 1,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)
        self.token_name = token_name
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        from ..services.token_database import synthesize_token_card

        card = synthesize_token_card(
            self.token_name, power=self.power, toughness=self.toughness,
            colors=self.colors, subtypes=self.subtypes,
        )
        tokens = context.engine.create_token(self.source.controller_id, card)
        if not tokens:
            return
        equipment = targets[0] if targets else self.target
        if equipment is not None:
            context.engine.attach_to_target(equipment, tokens[0])


class ReturnToHandEffect(GameEffect):
    """Return a target permanent to its owner's hand (RULE 701.3 "return").

    ``target_kind`` is usually ``"creature"``/``"permanent"``/``"any"`` (a
    plain "return target X to its owner's hand"), or a controller-restricted
    kind (``"land_you_control"``/``"creature_you_control"``) for a
    non-"target" resolve-time choice among the controller's own permanents —
    a bounce land's "return a land you control to its owner's hand" — see
    `targeting.legal_targets`. ``count`` > 1 targets several independent
    objects (RULE 115.1a generalized to N>=2, the same shape
    `DestroyEffect.count` uses) — "return two target creatures to their
    owners' hands".

    ``distinct_controllers`` (Run Away Together's "choose two target
    creatures controlled by **different players**. Return those creatures
    to their owners' hands.") is `targeting.TargetSpec.distinct_controllers`
    — see its docstring; only meaningful with ``count >= 2``.

    ``previous_subject=True`` (PAR-1) is Run Away Together's own two-sentence
    "choose N target X [constraint]. Verb **those** [referent]s." shape — a
    different, indirect-referent grammar from the single-sentence "destroy/
    exile N target X controlled by different players" `handlers.
    _MULTI_TARGET_DISTINCT_CONTROLLERS` claims: the *targets* are announced
    by a preceding `ChooseTargetsEffect` (RULE 601.2c, "choose N target
    creatures…") and read back here from `GameContext.previous_targets`
    (the same pronoun idiom `FightEffect`'s ``previous_target``/
    ``GrantUntilEffect.previous_subject`` use) instead of opening a fresh
    RULE 115 choice of its own — mutually exclusive with ``target_kind``,
    which is why it forces ``target_spec`` to ``None`` exactly like the self
    form below.

    ``target_kind=None`` is the **self** form — "Return ~ to its owner's
    hand." with no RULE 115 target and no player choice, mirroring
    `TapEffect`/`AddCountersEffect`'s own untargeted mode. It acts on the
    effect's own source wherever that currently is: Rancor's "When ~ dies,
    return it to its owner's hand." resolves with the source already in a
    *graveyard* (RULE 400.7 — it's a new object there), and
    `RulesEngine.return_to_hand` moves an object out of whatever zone it's
    in, so no separate graveyard path is needed. Flickering Ward's "{W}:
    Return ~ to its owner's hand." is the same effect from the
    battlefield.

    ``spell_or_permanent`` (Sink into Stupor's "Return target spell or
    nonland permanent…") routes through `RulesEngine.
    bounce_spell_or_permanent` instead of `return_to_hand` — a target still
    on the stack needs pulling out of `GameState.stack` (which
    `return_to_hand`'s ordinary battlefield/zone removal doesn't know
    exists), not just a hand-ward move.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "permanent",
        optional: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
        distinct_controllers: bool = False,
        previous_subject: bool = False,
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        spell_or_permanent: bool = False,
        creature_filter: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.previous_subject = previous_subject
        self.spell_or_permanent = spell_or_permanent
        # RULE 601.2c mass "return all X [with condition]" (Displacement
        # Wave's "return all nonland permanents with mana value X or less to
        # their owners' hands.") — `DestroyEffect.selector`'s own untargeted
        # board-sweep shape, shared via `_mass_selector_objects`/
        # `_MASS_DESTROY_SELECTORS`.
        self.selector = selector if selector in _MASS_DESTROY_SELECTORS else None
        self.filter = filter
        # ``target_kind=None`` is the self form — no `TargetSpec` at all, the
        # same way `TapEffect`'s own untargeted modes leave it ``None``, so
        # `RulesEngine._trigger_target_specs` doesn't count this as a
        # targeting effect and open a RULE 115 choice with nothing to pick.
        # ``previous_subject``/``selector`` are the same "nothing of its own
        # to announce" shape, for the same reason (PAR-1) — their targets
        # already were the preceding clause's, or there's no RULE 115 choice
        # to begin with.
        self.target_spec = (
            TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max,
                distinct_controllers=distinct_controllers,
                # "target **Human** you control" (Kogla, the Titan Ape,
                # MEC-43) — the same `TargetSpec.creature_filter` narrowing
                # `BlinkEffect`/`CounterUntapGrantKeywordEffect` already
                # thread through; ``"creature_you_control"`` (and every
                # other kind `legal_targets` already checks it against)
                # picks it up with no new target kind needed.
                creature_filter=creature_filter,
            )
            if target_kind is not None and not previous_subject and self.selector is None
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        bounce = context.bounce_spell_or_permanent if self.spell_or_permanent else context.return_to_hand
        if self.selector is not None:
            # "…with mana value X or less" — the ``"x"`` sentinel on
            # ``self.filter`` is already substituted for the spell's real
            # announced {X} by `RulesEngine._substitute_x` at cast time
            # (it walks any effect's ``filter`` dict generically, the same
            # path `DestroyEffect`'s own mass wipes use).
            for obj in _mass_selector_objects(context, self.selector, self.filter, source=self.source):
                bounce(obj)
            return
        if self.previous_subject:
            # "Return those creatures to their owners' hands." (PAR-1) — the
            # whole group the preceding "choose N target …" clause announced.
            for target in list(context.previous_targets):
                bounce(target)
            return
        if self.target_spec is None:
            # Self form — the source itself, from whatever zone it's in.
            if self.source is not None:
                bounce(self.source)
            return
        if self.target_spec.effective_count != 1:
            chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
            for target in chosen:
                bounce(target)
            return
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            bounce(target)


class ReturnToLibraryEffect(GameEffect):
    """"Put target X on top/the bottom of its owner's library." (RULE 701.3
    "put" — Time Ebb/Griptide/Roil Spout/Vedalken Dismisser-shaped tempo
    bounce; 10 SOLO cards on this exact template, `parser_probe.py blocked`).
    `ReturnToHandEffect`'s library-destination sibling — see
    `RulesEngine.return_to_library`.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        position: str = "top",
        optional: bool = False,
        count: int = 1,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.position = position if position in ("top", "bottom") else "top"
        #: ``target_kind=None`` — "Put **this**/~ on top of its owner's
        #: library." (Sensei's Divining Top-shaped) — no RULE 115 target at
        #: all, mirroring `ExileEffect`/`TapEffect`'s own self mode.
        self.target_spec = TargetSpec(kind=target_kind, optional=optional, count=count) if target_kind else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is None:
            target = (targets[0] if targets else None) or self.target or self.source
            if target is not None:
                context.return_to_library(target, self.position)
            return
        if self.target_spec.effective_count != 1:
            chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
            for target in chosen:
                context.return_to_library(target, self.position)
            return
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.return_to_library(target, self.position)


class ReturnToLibraryThenDigSharedTypeEffect(GameEffect):
    """"Put target permanent you own on the bottom of your library. Reveal
    cards from the top of your library until you reveal a card that shares
    a card type with that permanent. Put that card onto the battlefield and
    the rest on the bottom of your library in a random order." (Reality
    Scramble) — the type-matching predicate is read live off the
    just-bottomed permanent's own printed type words (RULE 205's main types
    only; ``GameObject.type_words`` also carries a supertype like
    "legendary" and the always-added "permanent", neither of which counts
    as a "card type" a `card_query` type match should require), so one
    effect covers whatever gets targeted rather than a fixed criteria.
    """

    _MAIN_TYPES = (
        "land", "creature", "artifact", "enchantment",
        "planeswalker", "instant", "sorcery", "battle", "kindred",
    )

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent_you_control",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        player = _controller_of(self.source, context)
        if player is None:
            return
        shared_types = [t for t in self._MAIN_TYPES if t in target.type_words]
        context.return_to_library(target, "bottom")
        if not shared_types:
            return
        context.engine.dig_until(
            player, {"type": shared_types},
            hit_destination="battlefield", rest_destination="library_bottom_random",
        )


class ShuffleSelfIntoLibraryEffect(GameEffect):
    """"Shuffle ~ into its owner's library." (RULE 701.20 — Green Sun's
    Zenith's own trailing sentence, overriding the spell's default RULE
    608.2m "goes to the graveyard as it resolves" routing). Self-only, no
    RULE 115 target, mirroring `ReturnToHandEffect`'s ``target_kind=None``
    self mode; `_apply_stack_item`'s existing ``obj.zone != Zone.STACK``
    check already treats any self-move away from the stack (previously only
    a trailing self-`ExileEffect`) as an override, so nothing else needs to
    know this effect exists.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.shuffle_into_library(self.source)


class ReturnFromGraveyardEffect(GameEffect):
    """Return/put a target card from a graveyard onto the battlefield or to
    a hand (RULE 701.3, the Regrowth/Reanimate/Deathrite-adjacent recursion
    family — see `targeting.legal_targets`'s `_GRAVEYARD_TARGET_KINDS` for
    the full ``target_kind`` vocabulary: own/any/opponent graveyard scope ×
    card/creature/land/artifact/enchantment/instant-or-sorcery/permanent
    type). ``destination`` is ``"battlefield"`` (default) or ``"hand"``.

    ``under_your_control`` is the Reanimate/Rise from the Grave/Virtue of
    Persistence shape — "put target creature card from a graveyard onto
    the battlefield **under your control**" — as opposed to the plain
    Regrowth/Karmic Guide/Kenrith shape (this effect's default), which
    always returns to the card's *owner*'s control, matching how "return
    … to the battlefield"/"under its owner's control" reads. Only
    meaningful with ``destination="battlefield"`` — a card can't go to
    "your hand" when it isn't yours; real cards never combine the two.
    """

    #: Destinations this effect will route to (all handled by the engine's
    #: `_put_searched_card`): battlefield/hand (the recursion default pair)
    #: plus ``library_top`` (Noxious Revival "put … on top of its owner's
    #: library") / ``library_bottom``.
    _DESTINATIONS: frozenset[str] = frozenset(
        {"battlefield", "hand", "library_top", "library_bottom"}
    )

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "graveyard_creature",
        destination: str = "battlefield",
        under_your_control: bool = False,
        optional: bool = False,
        lose_life_equal_mv: bool = False,
        count: int = 1,
        shuffle_after: bool = False,
        subtype: Optional[str] = None,
        haste: bool = False,
        max_mana_value: Optional[int] = None,
        tapped: bool = False,
        trigger_subject_key: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.destination = destination if destination in self._DESTINATIONS else "battlefield"
        self.under_your_control = under_your_control
        #: "It gains haste." (Puppeteer Clique-shaped reanimate-and-exile) —
        #: a temp keyword grant on the returned permanent, same idiom
        #: `CopyPermanentEffect.haste` uses.
        self.haste = haste
        #: "…return it to the battlefield **tapped** under its owner's
        #: control." (MEC-43 round 2, Tenacious Dead) — Persist/Undying-
        #: shaped, but through the graveyard-recursion effect rather than
        #: an in-place return, since this card's own trigger targets no
        #: pre-existing "persist" mechanic.
        self.tapped = tapped
        #: "When ~ dies, you may pay `<cost>`. If you do, return **it** to
        #: the battlefield…" (Tenacious Dead) — the object to return isn't
        #: a fresh RULE 115 target at all, it's whatever fired this
        #: ability's own trigger (mirrors `AddCountersEffect.
        #: trigger_subject_key`'s ``"remembered"`` idiom exactly: reads
        #: `GameObject.remembered_instance_id`, stamped by an outer
        #: `PayCostThenEffect(remember_trigger_subject=True)` since
        #: `context.trigger_event` is no longer live once the interactive
        #: "if you do" choice resolves).
        self.trigger_subject_key = trigger_subject_key
        # RULE 701.3 rider: "You lose life equal to that creature's mana
        # value." (Reanimate) — read off the returned card, paid by the
        # effect's own controller, after the return resolves.
        self.lose_life_equal_mv = lose_life_equal_mv
        # PAR-15: "shuffle target card(s) from your graveyard into your
        # library" (Piper's Melody/Renewing Touch/Perpetual Timepiece) —
        # RULE 701.3's own recursion, just with an unknown final position
        # rather than a fixed top/bottom; modeled as "put on the bottom,
        # then shuffle" (the position `_put_searched_card`'s
        # ``"library_bottom"`` gives it is immediately randomized away, so
        # the result is exactly "shuffled into the library") rather than a
        # third `_DESTINATIONS` entry, mirroring how `SearchLibraryEffect`
        # already treats a shuffle destination as a placement + a follow-up
        # `shuffle_library` call rather than its own zone.
        self.shuffle_after = shuffle_after
        # RULE 303.4f (MEC-34): "Return enchanted creature card to the
        # battlefield…" (Animate Dead-shaped) — a fifth, non-RULE-115 mode
        # alongside the ordinary target/self shapes `AttachEffect`'s own
        # ``target_kind="created"`` mirrors: the card to return isn't a
        # fresh choice at all, it's the *same* graveyard card this Aura's
        # own spell already targeted when cast, stashed on `GameObject.
        # reanimate_target_id` since it can't attach the ordinary way.
        self._self_enchant_mode = target_kind == "self_enchant_target"
        self.target_spec = (
            TargetSpec(
                kind=target_kind, optional=optional, count=count, subtype=subtype,
                max_mana_value=max_mana_value,
            )
            if not self._self_enchant_mode and not self.trigger_subject_key else None
        )

    def _apply_one(self, context: GameContext, target: Any) -> None:
        if self.destination == "battlefield":
            # RULE 601.3a-adjacent: "`<type>` cards in graveyards … can't
            # enter the battlefield." (Grafdigger's Cage/Weathered
            # Runestone) — checked against the target's own printed card
            # while it's still sitting in the graveyard, before anything
            # moves; a prohibited card simply stays put; there's no target
            # to fall back to (RULE 608.2b covers a spell fizzling on an
            # illegal target, but this is a static prevention, not that).
            from . import continuous  # local: continuous imports this module under TYPE_CHECKING

            target_zone = getattr(target, "zone", None)
            if continuous.graveyard_library_entry_prohibited(
                context.state, target.card, zone=getattr(target_zone, "value", None)
            ):
                return
        controller_id = None
        if self.under_your_control and self.destination == "battlefield":
            player = _controller_of(self.source, context)
            controller_id = player.id if player is not None else None
        mv = getattr(getattr(target, "card", None), "converted_mana_cost", 0) or 0
        owner_id = getattr(target, "owner_id", None)
        context.return_from_graveyard(target, self.destination, controller_id=controller_id)
        if self.destination == "battlefield":
            # RULE 400.7: the object's `instance_id` stays stable across
            # the zone change (see `GameObject.reset_as_new_object`'s own
            # docstring), so `target` is still the right reference to hand
            # a following "it gains haste"/"exile it" clause — RULE 608.2's
            # referent, `GameContext.created_objects`, the same list
            # `CreateTokenEffect`/`CopyPermanentEffect` populate.
            context.created_objects.append(target)
            if self.haste:
                target.temp_keywords.add("haste")
            if self.tapped:
                target.tapped = True
        if self.shuffle_after and owner_id is not None:
            owner = context.state.player_by_id(owner_id)
            context.shuffle_library(owner)
        if self.lose_life_equal_mv and mv:
            player = _controller_of(self.source, context)
            if player is not None:
                context.lose_life(player, int(mv))

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._self_enchant_mode:
            target_id = getattr(self.source, "reanimate_target_id", None)
            target = context.state.find_object(target_id) if target_id is not None else None
            if target is None:
                return
            self._apply_one(context, target)
            return
        if self.trigger_subject_key:
            obj_id = (
                getattr(self.source, "remembered_instance_id", None)
                if self.trigger_subject_key == "remembered"
                else (context.trigger_event or {}).get(self.trigger_subject_key)
            )
            target = context.state.find_object(obj_id) if obj_id is not None else None
            if target is None:
                return
            self._apply_one(context, target)
            return
        if self.target_spec.effective_count != 1:
            chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
            for target in chosen:
                self._apply_one(context, target)
            return
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        self._apply_one(context, target)


class BlinkEffect(GameEffect):
    """"Exile target permanent, then return it to the battlefield under its
    owner's control" (RULE 400.7 — Ephemerate/Momentary Blink-shaped).

    Distinct from `ReturnFromGraveyardEffect` (a graveyard-only recursion
    family): this targets a *battlefield* permanent. See `RulesEngine.
    blink`'s docstring for why exiling then re-entering is a genuine RULE
    400.7 "new object" rather than a single no-op move.

    ``under_your_control`` is Restoration Angel's own "return that card to
    the battlefield **under your control**" — this effect's controller
    rather than the target's owner (`RulesEngine.blink`'s ``controller``
    param). Default ``False`` is plain blink, always under the owner.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature_you_control",
        under_your_control: bool = False,
        creature_filter: Optional[dict] = None,
        optional: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(
            kind=target_kind, creature_filter=creature_filter,
            optional=optional, count=count, count_max=count_max,
        )
        self.under_your_control = under_your_control

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = targets if targets else ([self.target] if self.target is not None else [])
        controller = _controller_of(self.source, context) if self.under_your_control else None
        for target in chosen:
            if target is not None:
                context.blink(target, controller=controller)


class AddManaEffect(GameEffect):
    """Add mana straight to the effect's controller's pool (RULE 106.4) — a
    spell's own bare "Add {B}{B}{B}." resolve-time body (Dark Ritual-shaped),
    as opposed to a permanent's mana ability (`game/mana_abilities.py`,
    tapped for mana outside the stack entirely, never a resolve-time effect).
    Also covers a *targeted* activated ability's own "Add one mana of any
    color" body (Deathrite Shaman's graveyard-exile abilities) — RULE 605.1a
    excludes anything that targets from ever being a `mana_abilities.py`
    mana ability at all, so that shape can only ever resolve here.

    ``colors`` is one WUBRGC letter per mana symbol printed, in the order
    printed, or the sentinel ``"ANY"`` for "one mana of any color" — a
    genuine player decision, opened as an interactive `add_mana_any_color`
    `pending_choice` (`RulesEngine.add_mana_any_color`/`resolve_add_mana_
    any_color_choice`) rather than guessed at. Untargeted (mana itself
    can't be targeted, RULE 106.4 — unrelated to whatever cost the
    ability/spell producing it might target).
    """

    def __init__(
        self,
        colors: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
        amount: Optional[int] = None,
        color: str = "C",
        amount_selector: Optional[str] = None,
        amount_from_trigger_event: Optional[str] = None,
        recipient: str = "controller",
        target_kind: Optional[str] = None,
        amount_from_target_hand_size: bool = False,
        amount_from_target_count_selector: Optional[str] = None,
        once_per_turn_ability: bool = False,
        color_from_source_chosen_color: bool = False,
        color_from_source_noted_color: bool = False,
        any_color_choices: Optional[list[str]] = None,
        any_amount_from_context: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        #: "Add X mana in any combination of {B} and/or {G}." (Culling
        #: Ritual, MEC-40) — narrows the ``colors=["ANY"]`` offer to this
        #: fixed set instead of all five WUBRG, mirroring `add_mana_any_
        #: color`'s own ``colors`` narrowing (Kinnan's "any type **that
        #: permanent produced**"). **Documented simplification**: the real
        #: card lets the caster split the total across *both* colours
        #: independently, mana by mana (RULE 106.1); this offers one colour
        #: choice for the whole amount instead — no "how many of each"
        #: interactive shape exists yet (`add_mana_any_color`'s own
        #: `pending_choice` is a single categorical pick, not a per-unit
        #: split). Still fully usable mana, just less flexible than printed.
        self.any_color_choices = list(any_color_choices) if any_color_choices else None
        #: The `GameContext` accumulator name to size the ``"ANY"`` amount
        #: from instead of `amount_from_target_count_selector` — Culling
        #: Ritual's "for each permanent destroyed this way" reads
        #: `GameContext.permanents_destroyed_this_way`, the same
        #: same-resolution-accumulator idiom `life_lost_this_way` already
        #: established.
        self.any_amount_from_context = any_amount_from_context
        #: "…adds an additional one mana of **the chosen color**." (Utopia
        #: Sprawl-shaped RULE 601.2b "as ~ enters, choose a color" Auras) —
        #: reads this effect's own source's `GameObject.chosen_color`
        #: (`RulesEngine._offer_enter_choices`'s existing ETB choice) fresh
        #: at apply time instead of a fixed `colors` list, so a later
        #: Replay/Puzzle-mode change to the choice is honoured too.
        self.color_from_source_chosen_color = color_from_source_chosen_color
        #: "Add one mana of this artifact's last noted type." (Jeweled
        #: Amulet, MEC-43) — the `noted_mana_color` sibling of
        #: `color_from_source_chosen_color` just above; reads `GameObject.
        #: noted_mana_color` fresh at apply time instead of a fixed
        #: ``colors`` list. Produces no mana at all if nothing has been
        #: noted yet (the card's own activation-order gate — "Activate
        #: only if there are no charge counters" on the noting ability —
        #: already guarantees a note exists before this one can fire).
        self.color_from_source_noted_color = color_from_source_noted_color
        #: "…add X mana of any one color, where X is the number of Islands
        #: **target opponent** controls" (ENG-27, Carpet of Flowers) — a
        #: `continuous.count_selector` evaluated for the *resolved target*
        #: (``targets[0].id``), not this effect's own controller the way
        #: ``amount_selector`` below always is. Only meaningful alongside
        #: ``colors=["ANY"]``; scales that colour's own amount instead of
        #: the fixed-``self.color`` slot.
        self.amount_from_target_count_selector = amount_from_target_count_selector
        #: "…if you haven't added mana with this ability this turn, you may
        #: add …" (Carpet of Flowers) — the effect's own source gets the
        #: `GameObject.added_mana_with_ability_this_turn` flag (reset each
        #: untap step); already-used-this-turn is a resolve-time no-op
        #: rather than a full RULE 603.4 intervening-if that keeps the
        #: trigger off the stack in the first place — the "you may" is
        #: still offered, it just does nothing if accepted anyway.
        self.once_per_turn_ability = once_per_turn_ability
        #: "Add {R} for each card in target opponent's hand." (Jeska's
        #: Will) — the one shape here that genuinely targets (RULE 601.2c
        #: opts this effect into a real `target_spec`, unlike every other
        #: untargeted form above); the produced amount is read off that
        #: resolved target's own hand size at resolution, not a board-wide
        #: `continuous.count_selector` scope.
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        self.amount_from_target_hand_size = amount_from_target_hand_size
        #: "add that much {R}" (MEC-11's Raphael, Ninja Destroyer, an
        #: Enrage sibling — "whenever ~ is dealt damage, add that much
        #: {R}") — the event field name (``"amount"``) to read off
        #: `GameContext.trigger_event` at resolution, `MirrorProducedManaEffect`'s
        #: "read this firing's own payload" idiom applied to a plain
        #: numeric amount instead of a produced-colour set. **Documented
        #: simplification**: Raphael's own trailing "until end of turn, you
        #: don't lose this mana as steps and phases end" isn't modeled —
        #: `ManaPool` has no persist-past-a-step mechanism yet — so this
        #: mana empties at the current step's end like any other (RULE
        #: 500.4), rather than lasting the rest of the turn.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: Who the mana goes to: ``"controller"`` (the effect's own source's
        #: controller — every ordinary case) or ``"event_controller"``, the
        #: player named by the triggering event (`GameContext.trigger_event`).
        #: Wild Growth needs the latter: "whenever enchanted land is tapped
        #: for mana, **its controller** adds an additional {G}" — the land's
        #: controller, who need not be the Aura's (RULE 110.2 lets those
        #: diverge under a control-change effect).
        self.recipient = recipient
        self.colors = [str(c).upper() for c in (colors or [])]
        # ``amount``/``color`` are the *variable-count* form ("add an amount of
        # {C} equal to that spell's mana value" — Mana Drain): a resolved count
        # of one colour, threaded through the same ``"x"`` sentinel
        # `RulesEngine._substitute_x` rewrites, instead of one letter per
        # printed symbol. Kept separate from ``colors`` so the fixed-symbol
        # form (Dark Ritual's "{B}{B}{B}") is unchanged.
        self.amount = amount
        self.color = str(color).upper()
        #: A `continuous.count_selector` name resolved *at resolution time*
        #: for the board-dependent form — "then add {R} for each card named ~
        #: in each graveyard" (Rite of Flame). Additive with ``colors``
        #: above, so Rite of Flame's flat "{R}{R}" and its per-copy bonus are
        #: one effect rather than two: ``colors=["R","R"]`` plus this.
        #: Distinct from ``amount`` (a value the *caller* already resolved).
        self.amount_selector = amount_selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.recipient == "event_controller":
            player = _event_player(context)
        else:
            player = _controller_of(self.source, context)
        if player is None:
            return
        if self.once_per_turn_ability and getattr(
            self.source, "added_mana_with_ability_this_turn", False
        ):
            return
        used_this_turn = False
        colors = self.colors
        if self.color_from_source_chosen_color:
            chosen = getattr(self.source, "chosen_color", None)
            colors = [chosen] if chosen else []
        elif self.color_from_source_noted_color:
            noted = getattr(self.source, "noted_mana_color", None)
            colors = [noted] if noted else []
        for color in colors:
            if color == "ANY":
                any_amount = 1
                if self.amount_from_target_count_selector and targets:
                    from . import continuous  # function-scoped: avoid an import cycle

                    target_player = targets[0]
                    any_amount = continuous.count_selector(
                        context.state, getattr(target_player, "id", None),
                        self.amount_from_target_count_selector, source=self.source,
                    )
                elif self.any_amount_from_context:
                    any_amount = int(getattr(context, self.any_amount_from_context, 0) or 0)
                elif self.amount_selector:
                    # "Add X mana in any combination of {B} and/or {R},
                    # where X is the sacrificed creature's mana value."
                    # (MEC-43, Burnt Offering) — the same `amount_selector`
                    # the fixed-``color`` branch below already reads,
                    # widened to also size the ``colors=["ANY"]`` amount
                    # (previously only ``amount_from_target_count_selector``/
                    # ``any_amount_from_context`` could).
                    from . import continuous  # function-scoped: avoid an import cycle

                    any_amount = continuous.count_selector(
                        context.state, player.id, self.amount_selector, source=self.source
                    )
                if any_amount > 0:
                    context.add_mana_any_color(
                        player, colors=self.any_color_choices, amount=any_amount,
                    )
                    used_this_turn = True
            else:
                context.add_mana(player, color)
                used_this_turn = True
        if self.once_per_turn_ability and used_this_turn and self.source is not None:
            self.source.added_mana_with_ability_this_turn = True
        if isinstance(self.amount, int) and self.amount > 0:
            context.add_mana(player, self.color, self.amount)
        if self.amount_from_trigger_event:
            event = context.trigger_event
            extra = int((event or {}).get(self.amount_from_trigger_event) or 0)
            if extra > 0:
                context.add_mana(player, self.color, extra)
        if self.amount_selector:
            from . import continuous  # function-scoped: avoid an import cycle

            extra = continuous.count_selector(
                context.state, player.id, self.amount_selector, source=self.source
            )
            if extra > 0:
                context.add_mana(player, self.color, extra)
        if self.amount_from_target_hand_size and targets:
            extra = len(getattr(targets[0], "hand", []) or [])
            if extra > 0:
                context.add_mana(player, self.color, extra)


def _mana_value_of(target: Any) -> int:
    """The mana value of a targeted spell (a `StackItem` or its `GameObject`
    or a `Card`) — for a delayed trigger capturing "that spell's mana value"
    (Mana Drain) at setup, before the spell leaves the game."""
    obj = getattr(target, "obj", None) or target
    card = getattr(obj, "card", None) or obj
    return int(getattr(card, "converted_mana_cost", 0) or 0)


class CreateDelayedTriggerEffect(GameEffect):
    """Arm a delayed triggered ability (RULE 603.7) at resolution — "at the
    beginning of your next <step>, <effect>." (Mana Drain, the Pacts, Final
    Fortune, Corpse Dance).

    ``step`` is the step-name it waits for (``"upkeep"``/``"main1"``/
    ``"end"``/…); ``scope`` is ``"controller"`` (that controller's next such
    step) or ``"any"`` (the very next one). ``effects`` is a list of
    whitelisted ``{"type", "params"}`` effect descriptors built into live
    one-shot effects here (through the same `effect_binder.build_effects`
    whitelist as any other effect — nothing from card text escapes it) and
    stashed on `GameState.delayed_triggers`; `GameEngine._fire_delayed_
    triggers` places them on the stack when the step arrives.

    ``capture`` reads a dynamic value from this effect's own resolution and
    bakes it into the delayed effects: ``"target_mana_value"`` substitutes the
    ``"x"`` amount/count sentinel with the targeted spell's mana value (Mana
    Drain's "add an amount of {C} equal to that spell's mana value") — captured
    now, since the spell is gone by the time the delayed ability fires.

    ``description`` is a human-readable label for the UI's "planned"
    delayed-trigger panel (`DelayedTrigger.to_dict()`) — e.g. "Mana Drain:
    {C} in Höhe der Manakosten hinzufügen". Optional (defaults to empty);
    hand-authored specs should still set one so the panel isn't blank.
    """

    def __init__(
        self,
        step: str,
        effects: Optional[list[dict[str, Any]]] = None,
        scope: str = "controller",
        capture: Optional[str] = None,
        min_turn_offset: int = 0,
        description: str = "",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.step = str(step)
        self.inner_specs = list(effects or [])
        self.scope = str(scope)
        self.capture = capture
        # ``min_turn_offset`` arms the trigger to fire no earlier than
        # ``turn_number + offset`` — 1 makes "at the beginning of *that*
        # (extra) turn's end step" (Final Fortune) skip the *current* turn's
        # end step, which would otherwise be the very next one.
        self.min_turn_offset = int(min_turn_offset)
        self.description = str(description)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .effect_binder import build_effects  # function-scoped: effects↔binder cycle
        from ..parser.oracle.spec import EffectSpec
        from ..models.game_state import DelayedTrigger

        inner = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in self.inner_specs],
            self.source,
        )
        if self.capture == "target_mana_value" and targets:
            captured = _mana_value_of(targets[0])
            for effect in inner:
                for attr in ("amount", "count"):
                    if getattr(effect, attr, None) == "x":
                        setattr(effect, attr, captured)
        if self.capture == "created_objects":
            # "…Sacrifice it at the beginning of the next end step."
            # (Kiki-Jiki, Mirror Breaker) / "…exile it." (Puppeteer
            # Clique) — "it" names whatever *this same resolution* just
            # created/returned (RULE 608.2's referent, `GameContext.
            # created_objects`), not a fresh RULE 115 target — baked
            # directly into the delayed effect the same way as every other
            # capture here, since the object has to survive until the
            # delayed firing without being re-chosen.
            made = list(context.created_objects)
            for effect in inner:
                if hasattr(effect, "objects"):
                    effect.objects = made
                elif hasattr(effect, "exiled_object") and made:
                    # "…Put that card into your hand at the beginning of
                    # your next end step." (MEC-38, Necropotence) —
                    # `ReturnUncastExiledEffect.exiled_object`, the same
                    # single-object capture `.target` gets just below,
                    # named differently since this effect already uses
                    # `.target`-shaped semantics for something else (RULE
                    # 608.2's referent here is specifically "the card *this
                    # same resolution* just exiled").
                    effect.exiled_object = made[0]
                elif hasattr(effect, "target") and made:
                    effect.target = made[0]
        # "Its controller may draw up to two cards at the beginning of the
        # next turn's upkeep." (Arcane Denial's own first sentence) — the
        # delayed draw belongs to the countered spell's controller, not
        # this ability's caster, so both *whose* upkeep it waits for
        # (`DelayedTrigger.controller_id`, below) and *who* the inner
        # `draw` effect hands cards to need that player instead of the
        # default. Baked directly into the constructed effect objects, the
        # same "capture a resolve-time fact the delayed firing can't see
        # anymore" idiom `target_mana_value` uses just above — by the time
        # this fires, the countered spell is long gone.
        target_controller_id: Optional[str] = None
        if self.capture == "target_controller" and targets:
            target_controller_id = getattr(targets[0], "controller_id", None)
            if target_controller_id is not None:
                target_player = context.state.player_by_id(target_controller_id)
                for effect in inner:
                    if hasattr(effect, "player") and getattr(effect, "player", None) is None:
                        effect.player = target_player
        controller_id = (
            target_controller_id
            or getattr(self.source, "controller_id", None)
            or context.active_player.id
        )
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=controller_id,
                step=self.step,
                effects=inner,
                scope=self.scope,
                targets=list(targets or []),
                description=self.description,
                min_turn=context.state.turn_number + self.min_turn_offset,
            )
        )


class InstallTemporaryPlayerTriggerEffect(GameEffect):
    """Arm a `TemporaryPlayerTrigger` (RULE 603.7-adjacent, but *recurring*
    and player-scoped rather than one-shot and step-scoped) — "until the
    end of defending player's next turn, that player gets two rad counters
    whenever they cast a spell" (Nuka-Nuke Launcher).

    The recipient defaults to the defending player (RULE 506.4). Like
    `AddPlayerCountersEffect.selector="defending_player"`, an Aura/
    Equipment-hosted "whenever equipped creature attacks, ..." trigger's
    own source is the Equipment, not the attacker — `combat_defender` is
    only ever stamped onto the actual attacking creature (RULE 506.4/
    `declare_attackers`), so this resolves the source's own ``attached_to``
    host first, exactly mirroring that effect's own docstring. ``event_type``
    is the `EventType`
    the installed trigger re-fires on (``"SPELL_CAST"`` — the only shape any
    real card in this pool needs); ``effects`` are whitelisted descriptors
    built into live effects immediately (mirroring `CreateDelayedTrigger
    Effect`) and reused for every firing while the trigger stays active —
    each is baked with ``player`` as its recipient (any effect carrying a
    settable, currently-``None`` ``player`` attribute, e.g.
    `AddPlayerCountersEffect`), since the specific player is fixed at
    install time, not re-resolved per firing.
    """

    def __init__(
        self,
        event_type: str,
        effects: Optional[list[dict[str, Any]]] = None,
        description: str = "",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.event_type = str(event_type)
        self.inner_specs = list(effects or [])
        self.description = str(description)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .effect_binder import build_effects  # function-scoped: effects↔binder cycle
        from ..parser.oracle.spec import EffectSpec
        from ..models.game_state import TemporaryPlayerTrigger

        host = self.source
        attached_to = getattr(host, "attached_to", None)
        if attached_to is not None:
            resolved = context.state.find_object(attached_to)
            if resolved is not None:
                host = resolved
        player = _defending_player_of(host, context)
        if player is None:
            return
        inner = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in self.inner_specs],
            self.source,
        )
        for effect in inner:
            if hasattr(effect, "player") and getattr(effect, "player", None) is None:
                effect.player = player
        context.state.temporary_player_triggers.append(
            TemporaryPlayerTrigger(
                player_id=player.id,
                event_type=self.event_type,
                effects=inner,
                install_turn=context.state.turn_number,
                description=self.description,
            )
        )


class PayEnergyThenEffect(GameEffect):
    """RULE 122/601.2b resolve-time optional cost: "you may pay {E}{E}. If you
    do, `<effect>`." (Aether Chaser/Herder/Inspector/Swooper — "…create a 1/1
    colorless Servo artifact creature token"). The controller may pay
    ``amount`` energy counters; only if they do do the ``effects`` follow —
    a genuine player decision (unlike the flat "Pay {E}" *activated-ability
    cost*, `ActivationCost.pay_energy`), so it opens an interactive yes/no
    `pay_energy_then` `pending_choice` at resolution (`RulesEngine.request_
    pay_energy_then`), mirroring the shock-land pay-life choice.

    ``effects`` are whitelisted descriptor dicts, built into live effects
    lazily at resolution (mirroring `InstallTemporaryPlayerTriggerEffect`);
    only untargeted follow-ups are modeled today (every real energy card
    with this rider creates a token / gains life / draws — none needs a
    freely-chosen target here). If the controller can't afford ``amount``
    energy, the payment simply never happens (no choice offered).
    """

    def __init__(
        self,
        amount: int = 0,
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = int(amount)
        self.inner_specs = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or player.counters.get("energy", 0) < self.amount:
            return  # can't pay — the optional payment simply doesn't happen
        context.engine.request_pay_energy_then(player, self.amount, self.inner_specs, self.source)


class PayCostThenEffect(GameEffect):
    """RULE 118.3-style resolve-time optional payment: "you may pay
    `<cost>`. If you do, `<effect>`." — the general form of
    `PayEnergyThenEffect` above, which only ever handled ``{E}`` pips.

    ``cost`` is free-form cost *text* parsed by `game/costs.py`'s
    `parse_activation_cost`, so mana / life / discard / sacrifice all work
    through the one `_can_pay_player_cost`/`_pay_player_cost` path ward and
    "sacrifice ~ unless you pay" already share, rather than a fourth
    parallel payment implementation.

    ``payer`` says *who* is asked: ``"controller"`` (Mana Vault's own
    upkeep untap) or ``"event_controller"``/``"event_player"`` — the player
    named by the triggering event (Wandering Archaic taxes the **opponent
    who cast the spell**, not its own controller).

    ``else_effects`` is the "**If you don't**, `<effect>`." branch, which for
    Wandering Archaic is the entire point: the opponent *declining* is what
    lets you copy their spell.
    """

    def __init__(
        self,
        cost: str = "",
        effects: Optional[list[dict[str, Any]]] = None,
        else_effects: Optional[list[dict[str, Any]]] = None,
        payer: str = "controller",
        source: Optional["GameObject"] = None,
        remember_trigger_subject: bool = False,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost)
        self.inner_specs = list(effects or [])
        self.else_specs = list(else_effects or [])
        self.payer = payer
        #: "Whenever another creature you control enters, you may pay
        #: `<cost>`. If you do, `<effect>` **it**." (Emiel the Blessed) —
        #: ``context.trigger_event`` is only live for this, the *first*,
        #: still-synchronous `apply()` call; the "if you do" branch runs
        #: later, once the interactive choice is answered, by which point
        #: that window has closed. Stamping the subject onto `GameObject.
        #: remembered_instance_id` here lets the deferred branch's own
        #: effects (`AddCountersEffect`'s ``trigger_subject_key="remembered"``)
        #: read it back.
        self.remember_trigger_subject = remember_trigger_subject

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import parse_activation_cost  # function-scoped: import cycle

        if self.remember_trigger_subject and self.source is not None:
            event = context.trigger_event
            self.source.remembered_instance_id = (event or {}).get("instance_id")
        if self.payer == "event_controller":
            player = _event_player(context)
        elif self.payer == "event_player":
            player = _event_player(context, key="player_id")
        elif self.payer == "previous_target_controller":
            # "…that permanent's controller may sacrifice a land…" (Chain of
            # Vapor) — the controller of whatever this same resolution's
            # *previous* clause targeted (RULE 608.2's referent,
            # `GameContext.previous_targets`), not this spell's own caster —
            # a bounce spell almost always targets an opponent's permanent,
            # so it's *them* being asked, not the caster.
            prev = list(context.previous_targets)
            player = (
                context.state.player_by_id(prev[0].controller_id)
                if prev and getattr(prev[0], "controller_id", None)
                else None
            )
        else:
            player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.request_pay_cost_then(
            player,
            parse_activation_cost(self.cost_text),
            self.inner_specs,
            self.source,
            else_effect_specs=self.else_specs,
            # A reflexive trigger's baked-in "that spell" (Wandering
            # Archaic) has to reach the branch effects, which are built
            # fresh when the choice is answered rather than sitting on the
            # stack item where the usual target dispatch would find them.
            targets=list(targets or []),
        )


class RequestAllPlayersDeclineOrEffect(GameEffect):
    """"Any player may pay `<cost>`. If no one does, `<effect>`." (Rhystic
    Circle, MEC-30, RULE 118.3-adjacent) — the multi-player sibling of
    `PayCostThenEffect`: every living player gets an independent chance to
    pay, in turn order, and ``effects`` only resolves — once, for this
    effect's own controller — if literally every one of them declines (or
    can't pay). The first player to actually pay cancels the whole thing.
    See `RulesEngine.request_all_players_decline_or` for the turn-order
    chaining.

    ``cost`` is free-form cost text (`game/costs.py`'s
    `parse_activation_cost`), same as `PayCostThenEffect`.
    """

    def __init__(
        self,
        cost: str = "",
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost)
        self.inner_specs = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import parse_activation_cost  # function-scoped: import cycle

        controller = _controller_of(self.source, context)
        if controller is None:
            return
        context.engine.request_all_players_decline_or(
            parse_activation_cost(self.cost_text), self.inner_specs, self.source, controller.id,
        )


class UntapSelfEffect(GameEffect):
    """"Untap this permanent." (Mana Vault's upkeep payoff) — the untap
    sibling of `TapEffect`'s self mode, scoped to the effect's own source.

    Deliberately bypasses `continuous.has_no_untap_static`: that gate is
    about the *untap step* (RULE 502.4), and a permanent whose whole point
    is "doesn't untap during your untap step, but here's how to untap it
    anyway" (Mana Vault, Winter Orb's cousins) must not have this blocked by
    its own restriction.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.source
        if target is not None:
            context.set_tapped(target, False)


class ReboundFreeCastWindowEffect(GameEffect):
    """RULE 702.88b Rebound's delayed half: "At the beginning of your next
    upkeep, you may cast this card from exile without paying its mana
    cost." Fires as a `DelayedTrigger`'s effect, armed by `RulesEngine.
    resolve_top_of_stack` when a `GameObject.has_rebound` card resolves
    having been cast from hand (Ephemerate-shaped).

    Modeled as a *standing* temp-cast permission (`GameState.temp_play_
    permissions`, already known to `can_cast`/`cast_spell`) plus `GameState.
    free_cast_instance_ids` to zero the mana cost, rather than a forced
    yes/no choice at this trigger's own resolution: RULE 702.88b's delayed
    ability really does ask "you may cast X" right then, but this engine has
    no synchronous mid-resolution chooser for a one-shot optional action
    (`RulesEngine.discard`'s "auto-choose, no chooser in this MVP" is the
    same fidelity level elsewhere). Same-turn-only (swept at this upkeep's
    own cleanup, `GameEngine._step_cleanup`) — "use it this turn or lose
    it", matching Rebound's real one-shot window closely enough without new
    step-scoped cleanup machinery.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        if obj is None or obj.zone != Zone.EXILE:
            return
        context.engine.grant_free_cast_window_from_exile(obj)


class TheRingTemptsYouEffect(GameEffect):
    """"The Ring tempts you." (RULE 701.51a) — untargeted; the tempted
    player is the source's controller unless ``player`` names one.

    Everything the temptation *does* lives in `RulesEngine.
    the_ring_tempts_you`: level the emblem up, then choose a Ring-bearer
    (interactively when there's a real choice to make).
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or _controller_of(self.source, context)
        if player is not None:
            context.engine.the_ring_tempts_you(player)


class ChooseObjectsEffect(GameEffect):
    """"[You] choose N <kind> you control and <do something to it>." — the
    spec-facing front for `RulesEngine.request_choose_objects`.

    The general answer to every clause that names *what kind* of permanent
    to act on but leaves *which one* to a player: Tevesh Szat's "you may
    sacrifice another creature or planeswalker", Professor Onyx's forced
    per-opponent sacrifice. Distinct from `SacrificeEffect`, which picks its
    own victim by criteria — use that where the rules pick (annihilator's
    "sacrifice N permanents" is still the defender's choice, but no shipped
    card cares which), and this where the player does.

    ``then``/``then_if_commander`` are serialized `EffectSpec` dicts applied
    once the picks are in: "**If you do**, draw two cards", and RULE 903's
    "if a commander was sacrificed this way, draw a card" on top. They can't
    be separate effects in the same list, because whether they apply is only
    known *after* the choice — which is exactly what a "you may" clause
    means.
    """

    def __init__(
        self,
        action: str = "sacrifice",
        what: str = "permanent",
        count: int = 1,
        optional: bool = False,
        exclude_self: bool = False,
        prompt: str = "",
        then: Optional[list[dict[str, Any]]] = None,
        then_if_commander: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.action = action
        self.what = what
        self.count = count
        self.optional = optional
        self.exclude_self = exclude_self
        self.prompt = prompt
        self.then = then
        self.then_if_commander = then_if_commander

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .rules_engine import _matches_permanent_type

        player = _controller_of(self.source, context)
        if player is None:
            return
        candidates = [
            obj
            for obj in context.state.permanents_controlled_by(player.id)
            if _matches_permanent_type(obj, self.what)
            and not (self.exclude_self and obj is self.source)
        ]
        context.choose_objects(
            player, candidates, self.action, count=self.count,
            optional=self.optional, prompt=self.prompt, source=self.source,
            then_specs=self.then, then_specs_if_commander=self.then_if_commander,
        )


class SacrificeSpecificEffect(GameEffect):
    """Sacrifice the exact permanents baked into this effect (RULE 701.17).

    The named-object counterpart of `SacrificeEffect`, which picks its
    victims by criteria and selector. Used where the rules already fixed
    *which* permanents ("that creature's controller sacrifices it at end of
    combat" — RULE 701.51a's third Ring ability), so there is nothing to
    choose and nothing to target. Silently skips any that already left the
    battlefield by the time this resolves.

    ``delay_step`` defers the sacrifice to a RULE 603.7 delayed trigger at
    that step instead of doing it now — "…sacrifices it **at end of
    combat**". Armed rather than executed, so a blocker that dies in combat
    first is simply gone when the delayed half fires.
    """

    def __init__(
        self,
        objects: list["GameObject"],
        delay_step: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.objects = objects
        self.delay_step = delay_step

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.delay_step:
            from ..models.game_state import DelayedTrigger

            controller_id = getattr(self.source, "controller_id", None) or (
                context.active_player.id if context.active_player else ""
            )
            context.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=controller_id,
                    step=self.delay_step,
                    scope="any",
                    effects=[SacrificeSpecificEffect(list(self.objects), source=self.source)],
                    description="Opfern am Ende des Kampfes",
                )
            )
            return
        for obj in list(self.objects):
            if obj in context.state.battlefield:
                # RULE 701.17a: a sacrifice is a non-destructive move to the
                # graveyard, so it can't be stopped by a regeneration shield
                # (RULE 701.16c) — `put_into_graveyard`, not `destroy`.
                context.engine.put_into_graveyard(obj)


class SacrificeAttachedPermanentEffect(GameEffect):
    """"When this Aura leaves the battlefield, that creature's controller
    sacrifices it." (MEC-34, RULE 303.4f's reanimator-Aura template —
    Animate Dead/Necromancy) — reads `self.source.attached_to` live at
    resolution rather than baking in a fixed object the way
    `SacrificeSpecificEffect` does, since the acting object here is only
    known once this LEAVES_BATTLEFIELD trigger actually fires.
    `GameState.remove_from_battlefield` never clears `attached_to`, so the
    just-departed Aura's own field still names the creature it was
    attached to the moment it left.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        host_id = getattr(self.source, "attached_to", None)
        if host_id is None:
            return
        host = context.state.find_object(host_id)
        if host is None or host not in context.state.battlefield:
            return
        context.engine.put_into_graveyard(host)


class ExileSpecificEffect(GameEffect):
    """Exile the exact permanents baked into this effect (RULE 406/701.5a).

    The plural counterpart of `SacrificeSpecificEffect` (same "the rules
    already fixed which objects, nothing to choose or target" shape),
    needed for a *delayed* "exile them" tail whose referent is `GameContext.
    created_objects` (MEC-12, Twinflame's "…create a token that's a copy of
    that creature… Exile **those tokens** at the beginning of the next end
    step.") — `CreateDelayedTriggerEffect`'s own ``capture="created_
    objects"`` branch already special-cases any inner effect exposing an
    ``.objects`` list (as `SacrificeSpecificEffect` does for Kiki-Jiki's
    singular "sacrifice it"), but `ExileEffect` only ever carries one
    ``.target``, silently dropping every token past the first for a
    multi-target source like Twinflame. Silently skips any object that
    already left the battlefield by the time this resolves — a token that
    died some other way first has already ceased to exist (RULE 111.7),
    so there is nothing left to move.
    """

    def __init__(
        self,
        objects: list["GameObject"],
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.objects = objects

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for obj in list(self.objects):
            if obj in context.state.battlefield:
                context.engine.exile(obj)


class ReturnUncastExiledEffect(GameEffect):
    """The "…if it wasn't cast this way" tail every optional free-cast-from-
    exile window needs: Beseech the Mirror's "put the exiled card into your
    hand", Possibility Storm's and Tibalt's Trickery's "put it on the bottom
    of their library in a random order".

    Armed as a `DelayedTrigger` alongside the window itself and baked onto
    the exiled card (``exiled_object``) — "the exiled card" names one
    specific object, nothing targetable. Being still in exile when this
    fires *is* "wasn't cast this way": casting it moves the card to the
    stack, so the check is a zone read rather than a flag anything has to
    remember to clear.
    """

    def __init__(
        self,
        exiled_object: "GameObject",
        destination: str = "hand",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.exiled_object = exiled_object
        self.destination = destination

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.exiled_object
        if obj is None or obj.zone != Zone.EXILE:
            return
        obj.face_down_in_exile = False
        if self.destination == "library_bottom":
            owner = context.state.player_by_id(obj.owner_id)
            if owner is None:
                return
            owner.remove_from_zone(obj, Zone.EXILE)
            obj.zone = Zone.LIBRARY
            owner.library.insert(0, obj)
            return
        context.engine.return_to_hand(obj)


class CastExiledFaceDownEffect(GameEffect):
    """"You may cast the exiled card without paying its mana cost if that
    spell's mana value is N or less. Put the exiled card into your hand if
    it wasn't cast this way." (Beseech the Mirror.)

    Runs right after a search whose destination was ``"exile_face_down"``,
    and claims every face-down card in the controller's exile — only that
    destination ever sets `GameObject.face_down_in_exile`, and this effect
    always clears it, so the pairing is unambiguous within one resolution.

    ``require_bargained`` gates the *cast* half on the spell having been
    bargained (RULE 701.x, `GameObject.bargained`) — the "put it into your
    hand" half is unconditional, which is why this isn't the existing
    `ConditionalEffect` wrapper around a cast-only effect.

    The window itself is `RulesEngine.grant_free_cast_window_from_exile`'s
    (Rebound's), so the card is cast through the ordinary action loop with
    full targeting rather than a stripped mid-resolution cast. **Documented
    deviation**: the real card offers that cast *during its own resolution*
    and sends the card to hand immediately afterwards; here the window
    stays open until the beginning of the end step, when the delayed
    `ReturnUncastExiledEffect` performs the "if it wasn't cast this
    way" half. The engine has no synchronous mid-resolution chooser for an
    optional cast (the same fidelity limit `ReboundFreeCastWindowEffect`
    documents), and holding the window open only ever helps the caster —
    who, on this card, has already paid for it.
    """

    def __init__(
        self,
        max_mana_value: Optional[int] = None,
        require_bargained: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.max_mana_value = max_mana_value
        self.require_bargained = require_bargained

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..models.game_state import DelayedTrigger

        source = self.source
        player = None
        if source is not None:
            player = context.state.player_by_id(source.controller_id)
        player = player or context.active_player
        if player is None:
            return
        may_cast = not self.require_bargained or bool(getattr(source, "bargained", False))
        for obj in list(player.exile):
            if not getattr(obj, "face_down_in_exile", False):
                continue
            cheap_enough = (
                self.max_mana_value is None
                or obj.card.converted_mana_cost <= self.max_mana_value
            )
            if not (may_cast and cheap_enough):
                # Never eligible to be cast — the "put it into your hand"
                # half applies straight away rather than at the end step.
                obj.face_down_in_exile = False
                context.engine.return_to_hand(obj)
                continue
            context.engine.grant_free_cast_window_from_exile(obj)
            context.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=player.id,
                    step="end",
                    scope="any",
                    effects=[ReturnUncastExiledEffect(obj, source=source)],
                    description=f"{obj.name}: auf die Hand nehmen, falls nicht gewirkt",
                )
            )


class MarchesaDelayedReturnEffect(GameEffect):
    """RULE 603.7 delayed half of "return that card to the battlefield under
    your control at the beginning of the next end step" (Marchesa, the
    Black Rose-shaped: a creature you control with a counter on it dies).
    ``dying_object`` is baked in at construction — there's nothing left to
    target once the delayed trigger fires (the same RULE 603.4 per-firing
    shape `RulesEngine._collect_impulsive_draw_triggers`/`ImpulsiveDrawEffect`
    already use for Ragavan's per-firing damaged player).
    """

    def __init__(self, dying_object: "GameObject", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.dying_object = dying_object

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..models.game_state import DelayedTrigger

        controller_id = getattr(self.source, "controller_id", None) or context.active_player.id
        inner = ReturnFromGraveyardEffect(
            target=self.dying_object,
            destination="battlefield",
            under_your_control=True,
            source=self.source,
        )
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=controller_id,
                step="end",
                scope="any",
                effects=[inner],
                description=f"{self.dying_object.name}: unter Kontrolle zurück auf das Schlachtfeld",
            )
        )


class ReturnSelfFromGraveyardEffect(GameEffect):
    """"...if this creature is in your graveyard, you may return it to your
    hand." (RULE 112.6a, Infesting Radroach) — ``obj`` is baked in at
    construction (`RulesEngine._collect_mill_return_from_graveyard_
    triggers`, the same per-firing shape `MarchesaDelayedReturnEffect`
    above uses for its own dying object), deliberately with no
    `target_spec` of its own so `_place_or_pause_trigger` never opens a
    target choice for it — "it" is always this ability's own source, never
    a pick. Re-checks ``obj``'s zone at resolution time rather than
    assuming it's still in the graveyard (RULE 603.3c/608.2b: something
    else may have moved it between trigger and resolution, e.g. an
    opponent's graveyard-hate instant).

    ``obj=None`` falls back to ``self.source`` instead — the shape a
    *granted* "when this creature dies, return it to the battlefield…"
    ability needs (Malakir Rebirth-shaped): `continuous.py`'s layer-6
    `grant_triggered_ability` binds a fresh copy of the ability onto each
    affected object with that object as ``source``, so there's no specific
    firing to bake a reference in at — "it" is simply whichever object the
    granted ability ended up on, read live the same way `RegenerateEffect`'s
    self mode reads ``self.source``. ``tapped``/``under_your_control``
    (RULE 400.7's "under **its owner's** control" is the default;
    ``under_your_control`` is only for the rarer "under **your** control"
    phrasing) cover the two real variants beyond the plain Infesting
    Radroach shape.
    """

    def __init__(
        self,
        obj: Optional["GameObject"] = None,
        destination: str = "hand",
        source: Optional["GameObject"] = None,
        tapped: bool = False,
        under_your_control: bool = False,
        transformed: bool = False,
    ) -> None:
        super().__init__(source)
        self.obj = obj
        self.destination = destination
        self.tapped = tapped
        self.under_your_control = under_your_control
        #: "…return it to the battlefield tapped **and transformed** under
        #: its owner's control." (Ojer Axonil, Deepest Might) —
        #: `RulesEngine.return_from_graveyard`'s own ``transformed`` flag.
        self.transformed = transformed

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.obj or self.source
        if obj is None or obj.zone != Zone.GRAVEYARD:
            return
        controller_id = None
        if self.under_your_control and self.destination == "battlefield":
            player = _controller_of(self.source, context)
            controller_id = player.id if player is not None else None
        # `self.tapped` had been accepted (Malakir Rebirth's own granted
        # "return it to the battlefield **tapped**…") but never actually
        # applied — a dormant bug, since `RulesEngine.return_from_graveyard`
        # reads "tapped" off the ``destination`` string itself, not a
        # separate flag.
        destination = (
            "battlefield_tapped" if self.tapped and self.destination == "battlefield"
            else self.destination
        )
        context.return_from_graveyard(
            obj, destination, controller_id=controller_id, transformed=self.transformed,
        )
        if self.tapped and self.destination == "battlefield":
            obj.tapped = True


class SacrificeObjectEffect(GameEffect):
    """Sacrifice one specific, already-known permanent (RULE 701.17) — the
    delayed half of "sacrifice the creature at the beginning of the next end
    step" (Sneak Attack/Meek Attack-shaped): baked in at arm time, since
    there's no target left to choose once the delayed trigger fires.
    """

    def __init__(self, obj: "GameObject", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.obj = obj

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.obj in context.state.battlefield:
            context.engine.put_into_graveyard(self.obj)


class CheatCreatureFromHandEffect(GameEffect):
    """"You may put a creature card from your hand onto the battlefield.
    That creature gains haste. Sacrifice the creature at the beginning of
    the next end step." (Sneak Attack/Meek Attack-shaped — RULE 701 "cheat
    into play" plus a RULE 603.7 delayed sacrifice tail). ``max_total_pt``
    is Meek Attack's own "total power and toughness 5 or less" filter
    (``None`` for Sneak Attack's unrestricted version). The eligible
    creature is auto-picked — no chooser in this MVP, the same idiom
    `RulesEngine.discard` already uses for an un-targeted hand-card pick.
    """

    def __init__(
        self, max_total_pt: Optional[int] = None, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.max_total_pt = max_total_pt

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..models.game_state import DelayedTrigger

        player = _controller_of(self.source, context)
        if player is None:
            return
        creature = context.engine.put_hand_creature_onto_battlefield(player, self.max_total_pt)
        if creature is None:
            return
        creature.temp_keywords.add("haste")
        context.recompute()
        source_name = self.source.name if self.source is not None else None
        label = f"{creature.name}: geopfert" + (f" ({source_name})" if source_name else "")
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=player.id,
                step="end",
                scope="any",
                effects=[SacrificeObjectEffect(creature, source=self.source)],
                description=label,
            )
        )


class TakeExtraTurnEffect(GameEffect):
    """Take an extra turn after this one (RULE 500.7) — Final Fortune, the
    Time Warp family. Queues the effect's controller onto
    `GameState.extra_turns`; `GameEngine.begin_turn` takes it right after the
    current turn."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.take_extra_turn(player)


class ExtraCombatPhaseEffect(GameEffect):
    """"After this combat phase, there is an additional combat phase[,
    followed by an additional main phase]." (RULE 500.4-adjacent —
    Combat Celebrant/Godo/Aurelia-shaped triggered abilities; World at
    War/Aggravated Assault's own activated-ability wording sets
    ``main_phase_too``). The same "queue now, the turn loop drains it
    later" shape `TakeExtraTurnEffect`/`GameState.extra_turns` already
    use — this effect can't reach `GameEngine._turn_steps` directly (only
    `GameContext`/`RulesEngine` are visible to it), so it appends to
    `GameState.pending_extra_combats` instead and `GameEngine.
    advance_step` drains it (via `insert_additional_combat_phase`) before
    running the next step.
    """

    def __init__(self, main_phase_too: bool = False, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.main_phase_too = main_phase_too

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        context.state.pending_extra_combats.append(self.main_phase_too)


class GrantProtectionEffect(GameEffect):
    """"Target creature gains protection from the color of your choice until
    end of turn" (RULE 702.16 — Mother of Runes; Giver of Runes adds a
    "colorless" option and targets *another* creature).

    Opens an interactive `grant_protection_color` choice (`RulesEngine.
    grant_protection_choice`) for the effect's controller; the chosen quality
    lands in ``target.temp_protections`` (cleared at cleanup, RULE 514.2).
    ``allow_colorless`` is Giver of Runes' extra option.
    """

    def __init__(
        self,
        target_kind: str = "creature_you_control",
        allow_colorless: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.allow_colorless = allow_colorless
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None:
            return
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        context.engine.grant_protection_choice(target, controller, self.allow_colorless)


class GrantCantBeTargetOfSpellColorEffect(GameEffect):
    """"Creatures you control can't be the targets of blue or black spells
    this turn." (Autumn's Veil, MEC-41) — an untargeted, group-scoped RULE
    115 targeting restriction, narrower than protection/hexproof (see
    `targeting._targetable_by`'s own docstring for why those don't fit):
    only refuses a *spell* whose own color is in ``colors``, checked
    against the new turn-scoped `GameObject.temp_cant_be_target_of_spell_
    colors` (cleared at cleanup like `temp_protections`).
    """

    def __init__(
        self, colors: Optional[list[str]] = None, selector: str = "creatures_you_control",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.colors = [str(c).upper() for c in (colors or [])]
        self.selector = selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if not self.colors:
            return
        from . import continuous  # avoid the continuous↔effects import cycle

        controller_id = getattr(self.source, "controller_id", None)
        for obj in continuous.group_selector_objects(
            context.state, controller_id, self.selector, src=self.source,
        ):
            obj.temp_cant_be_target_of_spell_colors.update(self.colors)


class LoseGameEffect(GameEffect):
    """The effect's controller loses the game (RULE 104.3a) — Final Fortune's
    "you lose the game" downside, resolved via the same `_player_loses` path
    an SBA loss uses."""

    def __init__(self, reason: str = "effect", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.reason = reason

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.lose_game(player, self.reason)


#: `TapEffect.selector`'s whitelist — a mass "tap/untap all X" effect (RULE
#: 601.2c-style, untargeted, the same shape `DealDamageEffect.selector`/
#: `DestroyEffect.selector` use), not a RULE 115 target at all. Only the one
#: shape a real card needs so far: "untap all creatures you control"
#: (Village Bell-Ringer).
_TAP_SELECTORS: frozenset[str] = frozenset(
    {
        "creatures_you_control", "permanents_you_control", "nonland_permanents_you_control",
        # "Untap each other creature you control." (Copperhorn Scout).
        "other_creatures_you_control",
        # MEC-28: "untap all attacking creatures"/"untap each attacking
        # creature" (Karlach, Fury of Avernus/Hexplate Wallbreaker-shaped) —
        # unscoped by controller, the same `group_selector_objects`
        # `"attacking_creatures"` branch an anthem's own `affects` already
        # reuses (Motivated Pony's "Attacking creatures get +1/+1").
        "attacking_creatures",
    }
)


def _is_valid_tap_selector(selector: Optional[str]) -> bool:
    if selector in _TAP_SELECTORS:
        return True
    # "…untap it and all Samurai you control." (Godo, Bandit Warlord) —
    # `continuous.group_selector_objects`'s own subtype-scoped branch
    # already handles any such name; this just widens the whitelist to
    # admit it rather than growing `_TAP_SELECTORS` one subtype at a time.
    return bool(selector) and selector.startswith("creatures_you_control_of_type_")


class TapEffect(GameEffect):
    """Tap (or untap) a target permanent — or the source itself (RULE 701.21/22).

    ``target_kind=None`` (unlike the default ``"permanent"``) makes it act on
    the effect's own source with no player choice involved — "untap it" in a
    "whenever this creature becomes tapped, untap it" trigger (Dionus, Elvish
    Archdruid), mirroring `AddCountersEffect`'s untargeted mode.

    ``target_kind="attached_permanent"`` is a third, similarly targetless
    mode — "{U}: Tap enchanted creature."/"{U}: Untap enchanted creature."
    (Freed from the Real/Pemmin's Aura-shaped Aura activated abilities):
    acts on whatever the effect's own source (the Aura) is *currently*
    `attached_to`, re-read live at resolution (an Aura can move via
    Reconfigure-adjacent effects), mirroring `effect_binder._subject_
    condition`'s `"attached_permanent"` *trigger*-subject concept — this is
    the same idea applied to an effect's *target* instead.

    ``selector`` (see `_TAP_SELECTORS`) is a fourth mode — "untap all
    creatures you control" (Village Bell-Ringer's ETB) — untargeted, acting
    on every object `continuous.group_selector_objects` picks out for the
    effect's own controller, rather than a single target/self/attached host.

    ``count`` > 1 targets several independent objects (RULE 115.1a
    generalized to N>=2, the same shape `DestroyEffect.count` uses) — "untap
    up to two target lands" (Snap-shaped).

    ``previous_subject=True`` (PAR-15's "Untap those creatures." — Colossal
    Heroics' own trailing sentence, following "Any number of target
    creatures each get +2/+2 until end of turn.") is `ReturnToHandEffect`'s
    same pronoun shape: no target of its own, acting on whatever the
    preceding clause's own multi-target group was (`GameContext.
    previous_targets`).

    ``creature_filter`` narrows a real RULE 115 target the same way
    `DestroyEffect`/`UnblockableEffect`'s own field does — "target attacking
    creature" (`{"attacking": True}`, Raph & Leo, Sibling Rivals' own
    hand-authored simplification, MEC-28).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "permanent",
        untap: bool = False,
        optional: bool = False,
        selector: Optional[str] = None,
        count: int = 1,
        count_max: Optional[int] = None,
        previous_subject: bool = False,
        trigger_event_key: Optional[str] = None,
        creature_filter: Optional[dict] = None,
        subtypes: Optional[list[str]] = None,
        choose_tap_or_untap: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.untap = untap
        #: "You may tap **or untap** target permanent." (Derevi, Empyrial
        #: Tactician, MEC-42) — a real choice at resolution, layered on top
        #: of RULE 115's own "up to one" target optionality (``optional``
        #: above only ever decides *whether there's a target at all*).
        #: Opens `RulesEngine.request_tap_or_untap_choice` instead of
        #: applying ``untap`` directly.
        self.choose_tap_or_untap = choose_tap_or_untap
        self.selector = selector if _is_valid_tap_selector(selector) else None
        #: "Untap them." (Valley Floodcaller, MEC-41), narrowing a
        #: ``selector`` group by subtype the same way `PumpEffect.subtypes`/
        #: `AddCountersEffect.subtypes` already do — Valley Floodcaller's
        #: own trigger duplicates the pump clause's ``["bird", "frog",
        #: "otter", "rat"]`` list rather than a cross-clause pronoun, since
        #: `GameContext.previous_selector` only carries the bare selector
        #: *name* (MEC-28), not any subtype narrowing layered on top of it.
        self.subtypes = [s.lower() for s in subtypes] if subtypes else None
        self._attached_mode = target_kind == "attached_permanent"
        #: ENG-29's sibling: MEC-28's RULE 603.1 "group" subject — "whenever
        #: a creature you control attacks alone, ... untap it/that creature."
        #: — where the acting object isn't a static field on the source (an
        #: Aura's ``attached_to``) but whichever object actually satisfied
        #: *this firing* of a group trigger condition, re-read off
        #: `GameContext.trigger_event` at resolution time (the same "read
        #: the current firing's own payload" idiom `GrantKeywordToTrigger
        #: SubjectEffect` already uses for Tyvar Kell's emblem — this is that
        #: idiom applied to `TapEffect` instead of a keyword grant).
        #: ``trigger_event_key`` names which event field carries the acting
        #: object's id (``instance_id`` by default, `effect_binder.
        #: _subject_event_key`'s same per-event-type lookup — e.g.
        #: ``source_id`` for a DAMAGE-sourced group condition).
        self._trigger_subject_mode = target_kind == "trigger_subject"
        self.trigger_event_key = trigger_event_key or "instance_id"
        self.previous_subject = previous_subject
        self.target_spec = (
            TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max,
                creature_filter=creature_filter,
            )
            if target_kind is not None and not self._attached_mode
            and not self._trigger_subject_mode and self.selector is None and not previous_subject
            else None
        )

    def target_polarity(self) -> Optional[str]:
        # Untapping is a favour (untap your own blocker/attacker); tapping
        # down is a combat trick against whoever's permanent it is (usually
        # an opponent's would-be blocker or attacker).
        return "beneficial" if self.untap else "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.previous_subject:
            for one in list(context.previous_targets):
                context.set_tapped(one, tapped=not self.untap)
            return
        if self.selector is not None:
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            group = group_selector_objects(context.state, controller_id, self.selector, src=self.source)
            if self.subtypes is not None:
                group = [
                    obj for obj in group
                    if any(
                        s in obj.card.type_line.partition("—")[2].strip().lower().split()
                        for s in self.subtypes
                    )
                ]
            for obj in group:
                context.set_tapped(obj, tapped=not self.untap)
            return
        if self._attached_mode:
            host_id = getattr(self.source, "attached_to", None)
            target = context.state.find_object(host_id) if host_id is not None else None
            if target is not None:
                context.set_tapped(target, tapped=not self.untap)
            return
        if self._trigger_subject_mode:
            event = context.trigger_event
            obj_id = (event or {}).get(self.trigger_event_key)
            target = context.state.find_object(obj_id) if obj_id is not None else None
            if target is not None:
                context.set_tapped(target, tapped=not self.untap)
            return
        if self.target_spec is not None and self.target_spec.effective_count != 1:
            chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
            for one in chosen:
                context.set_tapped(one, tapped=not self.untap)
            return
        target = (targets[0] if targets else None) or self.target
        if target is None and self.target_spec is None:
            target = self.source
        if target is not None:
            if self.choose_tap_or_untap:
                context.engine.request_tap_or_untap_choice(target, source=self.source)
            else:
                context.set_tapped(target, tapped=not self.untap)


#: MEC-28: which effect types' own `selector` `_apply_effects_partitioned`
#: tracks into `GameContext.previous_selector` for a following "they" clause
#: — see that function's docstring. `TapEffect`-only today, matching
#: `effect_binder._GROUP_SUBJECT_RETARGET_FIELDS`'s identically narrow,
#: widen-only-as-a-real-card-needs-it convention.
_PREVIOUS_SELECTOR_EFFECT_TYPES: tuple[type, ...] = (TapEffect,)


class UnblockableEffect(GameEffect):
    """"Target creature can't be blocked this turn" (Rogue's Passage) — sets
    `GameObject.temp_unblockable`, read directly by `GameEngine.can_block`
    and cleared at cleanup (RULE 514.2).

    ``creature_filter`` (Access Tunnel's "target creature with power 3 or
    less") mirrors `DestroyEffect`'s own qualified-target filter.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        creature_filter: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, creature_filter=creature_filter)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            target.temp_unblockable = True


class CantBlockEffect(GameEffect):
    """"Target creature can't block this turn" (Falter/Abandon the Post) and
    its untargeted group form ("creatures your opponents control can't block
    this turn") — sets `GameObject.temp_cant_block`, read by
    `GameEngine.can_block` and cleared at cleanup (RULE 514.2).

    The blocker-side mirror of `UnblockableEffect` above, and shaped like it:
    ``selector`` (a `continuous.group_selector_objects` name) switches from
    RULE 115's targeted form to RULE 601.2c's mass one, ``count``
    generalizes the targeted form to N targets (RULE 115.1a — "up to two
    target creatures can't block this turn"), and ``filter`` narrows the mass
    form by characteristics `group_selector_objects`'s own selector params
    can't express ("creatures **without flying** can't block this turn" —
    `combat.matches_object_filter`'s shared vocabulary).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        count: int = 1,
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.selector = selector
        self.filter = dict(filter or {})
        self.target_spec = (
            None if selector else TargetSpec(kind=target_kind, count=count, optional=optional)
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector:
            from . import combat
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            for obj in group_selector_objects(
                context.state, controller_id, self.selector, src=self.source
            ):
                if obj.is_creature and combat.matches_object_filter(obj, self.filter):
                    obj.temp_cant_block = True
            return
        count = self.target_spec.effective_count if self.target_spec is not None else 1
        # Only this effect's own ``count`` targets, off the front of a
        # possibly-shared list — see `DestroyEffect.apply`'s comment.
        chosen = (
            targets[:count] if targets else ([self.target] if self.target is not None else [])
        )
        for one in chosen:
            if one is not None:
                one.temp_cant_block = True


class GrantCombatRestrictionEffect(GameEffect):
    """""~ can't be blocked by creatures with power 2 or less **this turn**"
    (Cavern Stomper) / "target creature can't be blocked by Walls this turn"
    (Tower of Coireall) — the resolve-time sibling of the standing
    ``combat_restriction`` static.

    Grants the *same* clamped param dict onto `GameObject.
    temp_combat_restrictions`, which `combat.combat_restrictions` reads
    alongside the recompute-derived list, so no combat-time check has to know
    which of the two a restriction came from. Cleared at cleanup (RULE 514.2).

    ``restrict_to_source=True`` stamps ``self.source``'s own instance id onto
    the restriction's ``filter`` at apply time (``{"instance_id": ...}``) —
    the pairwise "target creature can't block **~** this turn"/"target
    creature blocks **~** this turn if able" shapes, where the *specific*
    attacker named is this ability's own source and so can't be baked into
    the `AbilitySpec` at parse time (it varies per game object). Combined
    with the ``cant_block_filtered``/``must_block_target`` restriction
    kinds, `combat.matches_object_filter`'s ``instance_id`` key then narrows
    the (otherwise unfiltered) restriction to that one attacker.
    """

    def __init__(
        self,
        restriction: Optional[dict[str, Any]] = None,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        restrict_to_source: bool = False,
    ) -> None:
        super().__init__(source)
        self.restriction = dict(restriction or {})
        self.target = target
        self.restrict_to_source = restrict_to_source
        # No ``target_kind`` at all is the self form ("~ can't be blocked
        # by … this turn"), matching `PumpEffect`'s own self/target split.
        self.target_spec = TargetSpec(kind=target_kind) if target_kind else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is None:
            target = self.source
        else:
            target = (targets[0] if targets else None) or self.target
        if target is None or not self.restriction.get("kind"):
            return
        restriction = dict(self.restriction)
        if self.restrict_to_source and self.source is not None:
            restriction["filter"] = {
                **dict(restriction.get("filter") or {}),
                "instance_id": self.source.instance_id,
            }
        target.temp_combat_restrictions.append(restriction)


class BecomeAuraEffect(GameEffect):
    """"…it becomes an Aura with '`<quoted enchant text>`.'" (RULE 305.1c/
    303.4f — Necromancy-shaped, MEC-44). Stamps `GameObject.
    parametric_keywords["enchant"]` directly onto this effect's own source
    at resolution. Every attachment-family reader (`RulesEngine.
    _attachment_kind`/`_attachment_legal`/`_detach_attachments_from`)
    already reads that dict fresh off the live object each call rather than
    a cached/load-time snapshot — the same dict `effect_binder.py` writes
    exactly once, at bind time, for every ordinary Aura/Equipment/Fortify/
    Reconfigure card — so a plain runtime write here is picked up by every
    consumer for free; no threading needed, despite the field never having
    been *written* to mid-game by anything before this effect.

    ``quality`` is the enchant restriction's *type* word (``"creature"`` by
    default) — `_attachment_legal`'s own quality vocabulary (``"creature"``/
    ``"artifact"``/``"land"``/…) already falls through to permissive
    ``True`` for anything it doesn't recognize, the same simplification
    Animate Dead's own (already-an-Aura-from-load) quality string relies
    on: neither card's *exact* printed restriction ("creature card in a
    graveyard" / "creature put onto the battlefield with `<this>`") is a
    real characteristic this engine's simple word-match vocabulary can
    express, and no shipped card needs it enforced that precisely.

    Scoped to `parametric_keywords["enchant"]` specifically, not a general
    "becomes a `<type>` with `<quoted ability>`" primitive (RULE 305.1c,
    which could grant *any* ability, not just an attachment restriction) —
    that stays real, separate future work; see this card's own catalogue
    entry for why building the fully general version wasn't worth it for
    one card.
    """

    def __init__(self, quality: str = "creature", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.quality = quality

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        self.source.parametric_keywords = dict(self.source.parametric_keywords or {})
        self.source.parametric_keywords["enchant"] = {"quality": self.quality}


class AttachEffect(GameEffect):
    """Attach a permanent to another permanent as an Aura/Equipment-style effect.

    ``target_kind="created"`` is a fourth, non-RULE-115 mode alongside the
    ordinary target/self ``TargetSpec`` shapes below — "create a 1/1 …
    creature token and attach ~ to it." (Auxiliary Boosters/Living Weapon-
    adjacent, Field-Tested Frying Pan): the host is whichever object an
    *earlier* effect in this same resolution just created
    (`GameContext.created_objects`, RULE 608.2's "the tokens/it" referent —
    see `RenownEffect`/goad's own use of the same list), not a chosen or
    printed-source permanent.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self._created_mode = target_kind == "created"
        if not self._created_mode:
            self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._created_mode:
            created = getattr(context, "created_objects", None)
            target = created[-1] if created else None
        else:
            target = (targets[0] if targets else None) or self.target
        if target is None or self.source is None:
            return
        context.engine.attach_to_target(self.source, target)


class AttachTriggeringPermanentEffect(GameEffect):
    """"Whenever a[n] <X> you control enters, you may attach it to target
    creature you control." (Sigarda's Aid-shaped) — RULE 603.3d's "it"
    pronoun for a **group**-subject trigger ("an Equipment you control
    enters", not "this permanent enters"), so unlike `AttachEffect` (always
    attaches the ability's own source) and `CreateTokenMayAttachEquipmentEffect`
    (a *chosen* Equipment onto a token this same resolution just created),
    the permanent being moved here is neither: it's whichever object
    actually fired the trigger this time, read off `GameContext.
    trigger_event`'s own ``instance_id`` (ENG-13's general per-firing
    dynamic reference — the same field `ReturnSharedTypePermanentEffect`
    reads for Cloudstone Curio's own "it").

    Only the destination is a real RULE 115 target (``target_kind``,
    "target creature you control" by default); the mover is never offered
    as one, so this can't be reused for a spell/ability that names the
    moving object as a *chosen* target instead of "it".
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature_you_control",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None:
            return
        mover = context.state.find_object(event.get("instance_id"))
        target = (targets[0] if targets else None) or self.target
        if mover is None or target is None:
            return
        context.engine.attach_to_target(mover, target)


class UnattachTapIndestructibleEffect(GameEffect):
    """Akiri, Fearless Voyager's own "{W}: You may unattach an Equipment
    from a creature you control. If you do, tap that creature and it gains
    indestructible until end of turn."

    ``target_kind="attached_equipment_you_control"`` (`game/targeting.py`)
    only offers an Equipment that's actually attached, so there's always a
    host to act on once one is chosen — unlike `AttachEffect`, the effect's
    own source (Akiri) is neither unattached nor the one gaining
    indestructible; both happen to the *targeted Equipment*'s host.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "attached_equipment_you_control",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        equipment = (targets[0] if targets else None) or self.target
        if equipment is None:
            return
        host_id = getattr(equipment, "attached_to", None)
        if host_id is None:
            return
        host = context.state.find_object(host_id)
        equipment.attached_to = None
        if host is not None:
            context.set_tapped(host, True)
            host.temp_keywords.add("indestructible")


class ReturnCreatureGrantIndestructibleEffect(GameEffect):
    """Temur Sabertooth's own "{1}{G}: You may return another creature you
    control to its owner's hand. If you do, this creature gains
    indestructible until end of turn." — the same "if you do" shape
    `UnattachTapIndestructibleEffect` (Akiri) uses, just returning a target
    to hand instead of unattaching one, and granting indestructible to the
    effect's own *source* instead of the targeted object's host.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature_you_control",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        context.return_to_hand(target)
        if self.source is not None:
            self.source.temp_keywords.add("indestructible")


class TransformEffect(GameEffect):
    """Flip a double-faced permanent to its other face (RULE 712.8/712.9).

    Untargeted, it transforms its own source ("Transform ~." / "transform
    it" on a triggered/activated/loyalty ability); with a ``target_kind`` it
    targets another permanent (rare, but the same shape as `AttachEffect`).
    Delegates to `RulesEngine.transform_permanent`, which also rebinds the
    new face's catalogue-derived abilities/keywords — a bare
    `GameObject.transform()` would leave those pointing at the old face.
    """

    def __init__(
        self,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        if target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            target = targets[0] if targets else None
        else:
            target = self.source
        if target is not None:
            context.engine.transform_permanent(target)


class RevealTopThenTransformEffect(GameEffect):
    """"Look at the top card of your library. If it's a[n] <criteria> card,
    transform ~." (RULE 712.8 conditional flip — Delver of Secrets-shaped).

    Unlike the RULE 731 day/night flip (`RulesEngine.
    apply_day_night_turn_check`, spells-cast-last-turn-driven), this checks
    the top card of the *controller's* library, so it's its own one-shot
    effect rather than routed through the day/night machinery. ``criteria``
    is a `models.card_query` predicate (``{"type": ["instant", "sorcery"]}``
    for Delver; a plain string/dict works the same as `SearchLibraryEffect`)
    so the same effect covers any future card sharing this template, not
    just an instant/sorcery check. The card is only looked at, never moved.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        criteria: Any = "",
    ) -> None:
        super().__init__(source)
        self.criteria = criteria

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        if card_query.matches(top.card, self.criteria):
            context.engine.transform_permanent(self.source)


class ExileReturnTransformedEffect(GameEffect):
    """"Exile ~, then return it to the battlefield transformed under its
    owner's control" (RULE 400.7 + RULE 712.8 combined). Untargeted and
    always self — a transforming Saga's own final chapter (Fable of the
    Mirror-Breaker-shaped) or a transform-flip permanent's activated
    ability phrased this way instead of a plain `TransformEffect`
    (Ayara/Clive/Jin-Gitaxias-shaped). See `RulesEngine.
    exile_return_transformed`'s docstring for why this is a genuine
    RULE 400.7 zone change rather than an in-place flip.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.exile_return_transformed(self.source)


class SiegeDefeatedEffect(GameEffect):
    """A Siege's intrinsic defeat ability (RULE 310.11b): "exile it, then you
    may cast it transformed without paying its mana cost."

    Untargeted and always self, like `ExileReturnTransformedEffect` above —
    but the destination differs in the way that matters: the Siege goes to
    **exile and stays there**, and its back face becomes castable from
    exile for free. It does *not* come back to the battlefield on its own.

    Never bound from oracle text or the catalogue: RULE 310.11b is
    intrinsic to the Siege subtype, so `RulesEngine.check_state_based_
    actions` builds this per firing when a Siege's defense hits 0. That's
    also why it takes its source at construction rather than relying on a
    bind-time one.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.engine.exile_siege_for_transformed_cast(self.source)


class ReturnFromGraveyardTransformedEffect(GameEffect):
    """"Return this card from your graveyard to the battlefield transformed
    under its owner's control." (Bruce Banner-shaped) — the graveyard-
    sourced sibling of `ExileReturnTransformedEffect` above: a dies
    trigger's own subject is always the card that just died, so this is
    untargeted and always acts on ``self.source``, exactly like that
    sibling — never a chosen target. See `RulesEngine.return_from_graveyard`'s
    ``transformed`` param for the RULE 400.7 + RULE 712.8 mechanics (a
    genuine new-object zone change, then a forced flip onto the back face —
    not an in-place face swap). A no-op if ``self.source`` isn't actually
    sitting in a graveyard when this resolves (e.g. something else already
    moved it) or has no back face at all.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(self.source, "battlefield", transformed=True)


class ReturnSelfFromGraveyardToBattlefieldEffect(GameEffect):
    """"Return this card from your graveyard to the battlefield[, tapped]."
    (Dread Wanderer/Bloodsoaked Champion/Drownyard Temple &c) — the plain
    (non-transforming) sibling of `ReturnFromGraveyardTransformedEffect`:
    untargeted, always ``self.source``, since an activated ability's/
    triggered ability's "this card" can only ever mean the permanent whose
    text prints it. A no-op if ``self.source`` isn't actually in a
    graveyard when this resolves.

    Named distinctly from `ReturnSelfFromGraveyardEffect` above (mill's
    RULE 112.6a "return it to your hand", a *different* shape — a per-
    firing ``obj``, not always ``self.source``, and to hand rather than the
    battlefield) rather than reusing that name for an unrelated effect.
    """

    def __init__(self, tapped: bool = False, source: Optional["GameObject"] = None):
        super().__init__(source)
        self.tapped = tapped

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        destination = "battlefield_tapped" if self.tapped else "battlefield"
        context.return_from_graveyard(self.source, destination)


class ReturnSelfFromGraveyardToHandEffect(GameEffect):
    """"Return this card from your graveyard to your hand." (PAR-16 —
    Abzan Devotee/Clay Revenant/Chandra's Phoenix/Aurora Eidolon &c) — the
    hand-destination sibling of `ReturnSelfFromGraveyardToBattlefieldEffect`
    right above: same untargeted, always-``self.source``, no-op-unless-
    still-in-the-graveyard shape, just a different destination (so no
    ``tapped`` param applies here). Two real printed shapes reach it: an
    activated ability living in the graveyard (`ActivationCost.
    graveyard_zone`, the same inference `effect_binder.bind_ability` already
    does for the battlefield sibling) and a *triggered* ability whose
    source likewise sits in the graveyard when it fires (RULE 113.6a — the
    Eidolon/Phoenix family, "Whenever `<event>`, [you may] return this card
    from your graveyard to your hand": `TriggeredAbility.
    functions_from_graveyard`, inferred the same way, and consulted by
    `RulesEngine._collect_triggers`'s graveyard scan since real printings
    carry no explicit "(this ability functions from your graveyard.)"
    reminder to key off instead).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(self.source, "hand")


class PutSelfOntoBattlefieldFromHandEffect(GameEffect):
    """"{N}: Put this card from your hand onto the battlefield." (Talon
    Gates of Madara-shaped — a land's own paid alternative to a land drop,
    RULE 305's special-action family) — untargeted, always ``self.source``;
    a no-op if it isn't actually in hand when this resolves. Doesn't count
    against the controller's land-per-turn allowance (it's an activated
    ability, not RULE 305.1's "play a land" action at all).
    `effect_binder.bind_ability` infers ``ActivationCost.hand_zone``
    whenever an ability's effects include this one, the same way
    ``graveyard_zone`` is inferred for
    `ReturnSelfFromGraveyardToBattlefieldEffect`.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.HAND:
            return
        player = context.state.player_by_id(self.source.owner_id)
        player.remove_from_zone(self.source, Zone.HAND)
        context.state.add_to_battlefield(self.source)
        context.state.fire_event(
            GameEvent(
                EventType.ENTERS_BATTLEFIELD,
                controller_id=self.source.controller_id,
                object=self.source.name,
                instance_id=self.source.instance_id,
                object_types=sorted(self.source.type_words),
            )
        )


class ReturnDiesAsNewPermanentEffect(GameEffect):
    """"When ~ dies, return it to the battlefield. It's a[n] <type> with
    '<ability>'. ~ loses all other abilities." (Harold and Bob, First
    Numens) — a genuinely *different* card, not RULE 712.8's ordinary
    "return transformed" (`ReturnFromGraveyardTransformedEffect`, which
    needs a real printed back face): see `RulesEngine.return_dies_as_new_
    permanent`'s docstring for the mechanics (a synthetic `Card` built from
    ``new_type_line``/``new_oracle_text``, same name/owner/set).

    ``target_kind``, when given, is a real RULE 115 target this dies
    trigger resolves before returning (RULE 303.4a's "enchant Forest you
    control" — the specific permanent the new Aura form attaches to);
    mandatory (no ``target_spec.optional``), so a dying object with no
    legal target at all simply fizzles like any other single-target
    triggered ability, rather than returning unattached.
    """

    def __init__(
        self,
        new_type_line: str,
        new_oracle_text: str,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.new_type_line = new_type_line
        self.new_oracle_text = new_oracle_text
        self.target_spec = TargetSpec(kind=target_kind) if target_kind else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        attach_to = None
        if self.target_spec is not None:
            attach_to = targets[0] if targets else None
            if attach_to is None:
                return  # no legal target — the ability fizzles (RULE 608.2b)
        context.return_dies_as_new_permanent(
            self.source, self.new_type_line, self.new_oracle_text, attach_to=attach_to
        )


class PhaseOutEffect(GameEffect):
    """Phase a permanent out (RULE 702.26) — treated as though it doesn't
    exist until it phases back in at its controller's next untap step
    (`GameEngine._step_untap`'s RULE 702.26a sweep).

    Untargeted with ``target_kind=None`` (the default): phases out whatever
    is currently attached to this effect's own source ("Equipped creature
    phases out" — Robe of Stars' Astral Projection — no RULE 115 target,
    the same "defaults to its own source/host, no targeting" shape
    `TransformEffect`'s "transform ~" uses). ``target_kind="creature"``
    (etc.) targets some other permanent instead, same alternative
    `TransformEffect` offers.

    Any Aura/Equipment attached to the phasing-out permanent becomes
    unattached rather than phasing out together with it (RULE 702.26e-
    family simplification — no card needing a multi-permanent phase chain
    yet, see docs/implementation-state/BACKLOG.md).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        optional: bool = False,
        previous_subject: bool = False,
        self_target: bool = False,
        count: int = 1,
        count_selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "Put a +1/+1 counter on target creature. **It** phases out."
        #: (Slip Out the Back) — the same `GameContext.previous_targets`
        #: pronoun `FightEffect`/`GrantUntilEffect.previous_subject` already
        #: use, rather than a second independent RULE 115 target.
        self.previous_subject = previous_subject
        #: "~ phases out." (Blink Dog/Vaporous Djinn/Crystal Golem-shaped —
        #: the source phasing out *itself*, no attachment involved) —
        #: distinct from the plain untargeted default below, which is
        #: Robe of Stars' Equipment-hosted "**equipped creature** phases
        #: out" instead (`TransformEffect`'s own "self vs. attached host"
        #: split has the identical shape).
        self.self_target = self_target
        if target_kind is not None and not previous_subject:
            #: "Up to X target creatures phase out." (March of Swirling
            #: Mist, MEC-42) — ``count_selector="source_x_paid"`` reads the
            #: spell's own announced {X} fresh at target-gathering time
            #: (`targeting.resolved_count`), the same shape Goad's own
            #: "up to X target creatures" already established (ENG-30-
            #: adjacent, just a different count source).
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_selector=count_selector,
            )

    def _phase_out_one(self, context: GameContext, target: Any) -> None:
        target.phased_out = True
        for obj in context.state.battlefield:
            if obj.attached_to == target.instance_id:
                obj.attached_to = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.previous_subject:
            prev = list(context.previous_targets)
            target = prev[0] if prev else None
            if target is not None:
                self._phase_out_one(context, target)
            return
        if self.target_spec is not None and self.target_spec.count_selector:
            # A dynamic (e.g. X-sized) multi-target count, resolved once at
            # target-gathering time (`targeting.resolved_count`) — every
            # target actually gathered phases out, not just the first.
            # ``effective_count`` can't be used to slice here (it reads
            # only ``count``/``count_max``, not a live ``count_selector``),
            # so every entry the caller already gathered for this one
            # targeting effect is used as-is.
            for one in (targets or []):
                self._phase_out_one(context, one)
            return
        if self.target_spec is not None:
            target = (targets[0] if targets else None) or self.target
        elif self.self_target:
            target = self.source
        elif self.source is not None:
            host_id = getattr(self.source, "attached_to", None)
            target = context.state.find_object(host_id) if host_id is not None else None
        else:
            target = None
        if target is None:
            return
        self._phase_out_one(context, target)


class BecomePreparedEffect(GameEffect):
    """A preparation card's own permanent becomes prepared (RULE 722.3a).

    Always self-only, unlike `TransformEffect` — RULE 722.3a's "~ becomes
    prepared" has no targeted form on any real card. Delegates to
    `RulesEngine.make_prepared`, which creates the exiled prepare-spell
    copy (RULE 722.3c) and is itself a no-op if the source is already
    prepared or has no prepare spell.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.make_prepared(self.source)


#: `AddCountersEffect.selector`'s closed vocabulary — a mass, untargeted
#: "put a counter on each …" (RULE 601.2c), the group `continuous.
#: group_selector_objects` already resolves for pump/anthem clauses.
#: ``each_other_creature_you_control`` (MEC-11's Bellowing Aegisaur — "put a
#: +1/+1 counter on each **other** creature you control") is the RULE 109.5
#: "another" exclusion of the ability's own source, `group_selector_objects`'s
#: existing ``"other_creatures_you_control"`` affects value.
#: ``each_other_planeswalker_you_control`` (Ajani Steadfast's own "-2",
#: MEC-30) — the planeswalker-scoped sibling of ``each_other_creature_you_
#: control`` just above, `group_selector_objects`'s own ``"other_
#: planeswalkers_you_control"`` affects value.
_ADD_COUNTERS_SELECTORS: frozenset[str] = frozenset(
    {
        "each_creature_you_control", "each_other_creature_you_control",
        "each_other_planeswalker_you_control",
    }
)
#: Maps each `_ADD_COUNTERS_SELECTORS` member to the `continuous.
#: group_selector_objects` ``affects`` value it resolves against.
_ADD_COUNTERS_SELECTOR_AFFECTS: dict[str, str] = {
    "each_creature_you_control": "creatures_you_control",
    "each_other_creature_you_control": "other_creatures_you_control",
    "each_other_planeswalker_you_control": "other_planeswalkers_you_control",
}


class AddCountersEffect(GameEffect):
    """Put ``amount`` +1/+1 counters on a target creature — or on the source.

    Untargeted, it buffs the effect's own source (an activated "put a +1/+1
    counter on this creature"); with a ``target_kind`` it targets (RULE 122),
    optionally as an RULE 115.1a "up to one" pick, or ``count`` > 1 several
    independent targets at once (the same shape `DestroyEffect.count` uses —
    "put a +1/+1 counter on each of up to two target creatures", the
    Support-keyword-shaped family; note ``count`` here is the *target*
    count, distinct from ``amount``, the number of counters placed on each).
    ``selector`` (`_ADD_COUNTERS_SELECTORS` — RULE 601.2c, Vastwood Surge's
    "put two +1/+1 counters on each creature you control") is instead a
    mass, untargeted effect over the group `continuous.
    group_selector_objects` already resolves for pump/anthem clauses —
    mirrors `DealDamageEffect.selector`'s "no `target_spec` at all" shape.
    ``subtypes`` (Vault 12: The Necropolis's own chapter III — "each
    creature you control that's a Zombie or Mutant") further narrows that
    same mass group to an OR-combined creature-subtype filter, checked
    against the *live* object (unlike a DIES trigger's own subtype filter,
    every affected creature here is still on the battlefield) — a real,
    broader gap beyond this one card (tribal mass-counter effects are common).
    """

    def __init__(
        self,
        amount: int = 1,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
        kind: str = "+1/+1",
        optional: bool = False,
        selector: Optional[str] = None,
        count: int = 1,
        count_max: Optional[int] = None,
        subtypes: Optional[list[str]] = None,
        trigger_subject_key: Optional[str] = None,
        divided: bool = False,
        amount_from_trigger_event: Optional[str] = None,
        x_multiplier: Optional[int] = None,
        amount_from_count_selector: Optional[str] = None,
        amount_if_trigger_subject_subtype: Optional[list[str]] = None,
        amount_if_trigger_subject_subtype_value: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        #: MEC-27: "put X +1/+1 counters on ~, where X is the number of
        #: `<noun phrase>` you control." — `subgrammars.DEVOTION`'s wider
        #: RULE 613.7c reading, previously wired into damage/lose_life only.
        #: Same `continuous.count_selector` lookup, resolved live at
        #: resolution the same way `DealDamageEffect.amount_from_count_
        #: selector` already does; deliberately only wired into the plain
        #: self/single-target branch below, mirroring `amount_from_trigger_
        #: event`'s own single-recipient scope just above.
        self.amount_from_count_selector = amount_from_count_selector
        #: "Whenever you gain life, put that many +1/+1 counters on ~/target
        #: X." (Ageless Entity/Treebeard-shaped) — the event field name
        #: (``"amount"``) to read off `GameContext.trigger_event` at
        #: resolution, overriding ``amount`` when set. Same idiom as
        #: `LoseLifeEffect.amount_from_trigger_event`; deliberately only
        #: wired into the plain self/single-target branches below, since
        #: "that many" is inherently a single recipient, never a mass
        #: selector or an N>=2 multi-target pick.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "~ enters with twice X +1/+1 counters on it." (Banquet Guests) —
        #: a self-only ETB trigger reading the *source's own* announced
        #: {X} (`GameObject.x_paid`, RULE 107.3c — set at cast time,
        #: already present by the time this same object's own ENTERS_
        #: BATTLEFIELD trigger resolves) times this multiplier. Distinct
        #: from `_substitute_x`'s ``"x"`` sentinel, which only rewrites a
        #: *spell's own* resolution effects — a separately-fired triggered
        #: ability has no `StackItem.x` of its own to substitute against.
        self.x_multiplier = x_multiplier
        # PAR-15: "distribute N +1/+1 counters among any number of target
        # creatures" (Blessings of Nature/Jugan, the Rising Star/Verdurous
        # Gearhulk) — ``amount`` is then a *pool* split across whichever
        # targets were chosen (as evenly as possible, no explicit
        # ``division`` list — same documented simplification
        # `DealDamageEffect.divided`/`_apply_divided` uses for "damage
        # divided as you choose"), unlike the plain ``count`` > 1 shape
        # above where every target gets the *full* ``amount`` independently.
        self.divided = divided
        # The counter type: "+1/+1" (default) or "-1/-1" (RULE 122). Both shift
        # net P/T the same machinery, just with opposite sign.
        self.kind = kind
        self.selector = selector if selector in _ADD_COUNTERS_SELECTORS else None
        self.subtypes = [s.lower() for s in subtypes] if subtypes else None
        #: "Whenever a creature you control is dealt damage, put a +1/+1
        #: counter on **it**." (MEC-11's Rite of Passage) — an untargeted
        #: "it" here is *not* the ability's own source (Rite of Passage
        #: itself, an Enchantment) the way ``target_kind=None`` everywhere
        #: else in this class means, but whichever *group member* the
        #: RULE 603.1 trigger actually fired for. `parser/oracle/
        #: segmenter.py`'s group-subject damage-recipient handler sets this
        #: to the same event key (``"target_id"``) `effect_binder.
        #: _subject_event_key` resolves the trigger's own condition
        #: against, so the two always agree on which object "it" is.
        self.trigger_subject_key = trigger_subject_key
        #: "…put a +1/+1 counter on it. If it's a Unicorn, put 2 +1/+1
        #: counters on it instead." (Emiel the Blessed) — an "instead"
        #: override on the *trigger subject*'s own subtype, checked only
        #: alongside ``trigger_subject_key`` (the "it" both clauses share).
        #: Not a general "if X, do A instead of B" primitive (that stays a
        #: real open gap — see `BACKLOG.md`'s kicker "instead" note) — just
        #: this one recurring "bonus for a named creature type" shape.
        self.amount_if_trigger_subject_subtype = (
            [s.lower() for s in amount_if_trigger_subject_subtype]
            if amount_if_trigger_subject_subtype else None
        )
        self.amount_if_trigger_subject_subtype_value = amount_if_trigger_subject_subtype_value
        if self.selector is None and target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind, optional=optional, count=count, count_max=count_max)

    def target_polarity(self) -> Optional[str]:
        # "-1/-1"/"stun" counters are a downgrade for whoever's stuck with
        # them; every other kind this class ever places (+1/+1 chief among
        # them) is a buff.
        return "harmful" if self.kind in ("-1/-1", "stun") else "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.x_multiplier is not None:
            x_paid = getattr(self.source, "x_paid", 0) or 0
            self.amount = self.x_multiplier * x_paid
        if self.trigger_subject_key:
            if self.trigger_subject_key == "remembered":
                # The deferred sibling of the live-event read below — see
                # `PayCostThenEffect.remember_trigger_subject`.
                obj_id = getattr(self.source, "remembered_instance_id", None)
            else:
                event = context.trigger_event
                obj_id = (event or {}).get(self.trigger_subject_key)
            target = context.state.find_object(obj_id) if obj_id is not None else None
            if target is not None:
                amount = self.amount
                if self.amount_if_trigger_subject_subtype and self.amount_if_trigger_subject_subtype_value is not None:
                    sub = target.card.type_line.partition("—")[2].strip().lower().split()
                    if any(s in sub for s in self.amount_if_trigger_subject_subtype):
                        amount = self.amount_if_trigger_subject_subtype_value
                context.add_counters(target, amount, self.kind, source=self.source)
            return
        if self.selector in _ADD_COUNTERS_SELECTORS:
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            affects = _ADD_COUNTERS_SELECTOR_AFFECTS.get(self.selector, "creatures_you_control")
            for obj in group_selector_objects(context.state, controller_id, affects, src=self.source):
                if self.subtypes is not None:
                    sub = obj.card.type_line.partition("—")[2].strip().lower().split()
                    if not any(s in sub for s in self.subtypes):
                        continue
                context.add_counters(obj, self.amount, self.kind, source=self.source)
            return
        if self.target_spec is not None and self.target_spec.effective_count != 1:
            chosen = _chosen_targets(targets, self.target_spec.effective_count)
            if not chosen:
                return
            if self.divided:
                total = self.amount if isinstance(self.amount, int) else 0
                base, extra = divmod(total, len(chosen))
                shares = [base + (1 if i < extra else 0) for i in range(len(chosen))]
            else:
                shares = [self.amount] * len(chosen)
            for target, share in zip(chosen, shares):
                if share > 0:
                    context.add_counters(target, share, self.kind, source=self.source)
            return
        if self.target_spec is not None:
            target = targets[0] if targets else None
        else:
            target = self.source
        amount = self.amount
        if self.amount_from_trigger_event:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
        if self.amount_from_count_selector:
            from . import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            amount = continuous.count_selector(
                context.state, controller_id, self.amount_from_count_selector, source=self.source,
            )
        if target is not None and self.amount_if_trigger_subject_subtype and self.amount_if_trigger_subject_subtype_value is not None:
            # Same override as the `trigger_subject_key` branch above, for a
            # target reached the ordinary way instead — e.g. `targets`
            # threaded in from a deferred `pay_cost_then` "if you do" branch
            # (Emiel the Blessed), where `context.trigger_event`'s window
            # has already closed by the time this resolves.
            sub = target.card.type_line.partition("—")[2].strip().lower().split()
            if any(s in sub for s in self.amount_if_trigger_subject_subtype):
                amount = self.amount_if_trigger_subject_subtype_value
        if target is not None and amount > 0:
            context.add_counters(target, amount, self.kind, source=self.source)


class RenownEffect(GameEffect):
    """RULE 702.112b: Renown N's own triggered-ability body — put ``amount``
    +1/+1 counters on this creature and it becomes renowned. A single
    atomic effect (not `AddCountersEffect` alone) since the "becomes
    renowned" flag has to flip together with the counters — it's what the
    keyword's own "if it isn't renowned" guard (`effect_binder.
    _keyword_triggered_abilities`) checks to fire only once per creature.
    """

    def __init__(self, amount: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        context.add_counters(self.source, self.amount, "+1/+1", source=self.source)
        self.source.renowned = True
        context.fire_event(GameEvent(EventType.RENOWNED, instance_id=self.source.instance_id))


class AmassEffect(GameEffect):
    """RULE 701.48 Amass `<Type>` N: "If you don't control an Army creature,
    create a 0/0 black Army `<Type>` creature token first. Put N +1/+1
    counters on an Army you control." (Orcish Bowmasters, MEC-42) —
    auto-picks the first Army you control when one already exists and
    there's more than one to choose from (RULE 701.48b does let the
    amassing player choose), the same "no chooser for an equally-valid
    pick" idiom this engine's other untargeted picks already use, since
    nothing here differentiates otherwise-identical Army tokens.
    """

    def __init__(self, subtype: str = "Zombies", count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.subtype = str(subtype)
        self.count = max(0, int(count))

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..services.token_database import synthesize_token_card  # avoid a services↔effects cycle

        player = _controller_of(self.source, context)
        if player is None or self.count <= 0:
            return
        army = next(
            (
                o for o in context.state.battlefield
                if o.controller_id == player.id and o.is_creature
                and "army" in o.card.type_line.partition("—")[2].strip().lower().split()
            ),
            None,
        )
        if army is None:
            card = synthesize_token_card(
                self.subtype, power=0, toughness=0, colors=["B"],
                subtypes=["Army", self.subtype],
            )
            made = context.create_token(player.id, card, 1) or []
            context.created_objects.extend(made)
            army = made[0] if made else None
        if army is not None:
            context.add_counters(army, self.count, "+1/+1", source=self.source)


class PayLifeEqualToOpponentsCombatDamagedDrawThatManyEffect(GameEffect):
    """"You may pay X life, where X is the number of opponents that were
    dealt combat damage this turn. If you do, draw X cards." (Tymna the
    Weaver, MEC-42) — computes X once (`continuous.count_selector`'s new
    ``"opponents_dealt_combat_damage_this_turn"``), then opens the
    general `RulesEngine.request_pay_cost_then` choice with a
    *dynamically built* ``ActivationCost(pay_life=X)`` and a matching
    draw-X-cards follow-up, rather than `PayCostThenEffect`'s own fixed
    cost-text shape (which has no way to plug in a live board count).
    X=0 skips the choice outright — there's nothing to gain from paying
    0 life to draw 0 cards, the same "don't stall on a choice nobody can
    meaningfully act on" idiom `request_pay_cost_then` already applies
    to an unpayable cost.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from . import continuous  # function-scoped: avoid the continuous<->effects import cycle
        from .costs import ActivationCost  # function-scoped: costs<->effects import cycle

        player = _controller_of(self.source, context)
        if player is None:
            return
        x = continuous.count_selector(context.state, player.id, "opponents_dealt_combat_damage_this_turn")
        if x <= 0:
            return
        context.engine.request_pay_cost_then(
            player, ActivationCost(pay_life=x), [{"type": "draw", "params": {"count": x}}], self.source,
        )


class GrantUntilEffect(GameEffect):
    """RULE 611: create a continuous effect that lasts for a stated duration.

    The resolve-time counterpart of a permanent's printed static ability, and
    the general form of every "…until end of turn"-shaped grant: it builds a
    `StaticAbility` (so the grant goes through the RULE 613 layer engine like
    any other, rather than being a special case read by whoever happens to
    look) and parks it in `GameState.floating_statics`, where
    `game/durations.py` sweeps it at the window its ``duration`` names.

    Why this exists next to the ``temp_power``/``temp_keywords`` fields the
    shipped pump/grant effects use: those fields *are* "until end of turn" —
    they're cleared wholesale at cleanup (RULE 514.2) and have nowhere to
    record any other ending. "Until your next turn", "until end of combat"
    and RULE 611.2b's "for as long as `<condition>`" are unreachable that
    way. Existing effects are deliberately left on the old path; anything
    needing a *different* duration comes here.

    ``static`` is the `EffectSpec`-shaped payload for the underlying static
    (``{"type": "grant_keyword", "params": {...}}``), built by the binder
    from the same whitelisted registry every printed static goes through —
    card text never reaches the layer engine except as a registered type.
    """

    def __init__(
        self,
        static: Optional[dict[str, Any]] = None,
        duration: str = "end_of_turn",
        target_kind: Optional[str] = "creature",
        optional: bool = False,
        count: int = 1,
        condition: Optional[dict[str, Any]] = None,
        previous_subject: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.static = dict(static or {})
        self.duration = duration
        self.condition = dict(condition) if condition else None
        #: Apply to whatever the *previous clause* of this ability targeted
        #: ("Tap target land. It doesn't untap … for as long as ~ remains
        #: tapped.") instead of declaring a target of this effect's own.
        self.previous_subject = previous_subject
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional, count=count)
            if target_kind is not None and not previous_subject
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from . import durations  # local: durations imports effects' siblings

        spec_type = self.static.get("type")
        if not spec_type or not EffectRegistry.is_registered(str(spec_type)):
            return  # fail closed — an unregistered static grants nothing
        ability = EffectRegistry.create(str(spec_type), dict(self.static.get("params") or {}))
        if not isinstance(ability, StaticAbility):
            return
        controller_id = getattr(self.source, "controller_id", None)
        ability.source = self.source
        ability.duration = durations.normalize_duration(self.duration)
        ability.duration_data = {"player_id": controller_id}
        if self.condition is not None:
            # RULE 611.2b's condition-bounded duration: the effect *ends*
            # when this stops holding, unlike an ``active_if`` gate, which
            # merely lies dormant and can come back on.
            ability.duration = "for_as_long_as"
            ability.duration_data["condition"] = dict(self.condition)
        if self.target_spec is not None or self.previous_subject:
            # A targeted grant applies to exactly the permanents chosen —
            # `affects="objects"` reads the ids off the ability. With
            # ``previous_subject`` the referent is instead whatever the
            # *previous clause* of this same ability targeted ("Tap target
            # land. **It** doesn't untap … for as long as ~ remains tapped."),
            # the same `GameContext.previous_targets` pronoun `FightEffect`
            # and `GoadEffect` use.
            if self.previous_subject:
                chosen = list(context.previous_targets)
            else:
                chosen = list(targets or [])[: self.target_spec.effective_count]
            ids = [t.instance_id for t in chosen if getattr(t, "instance_id", None) is not None]
            if not ids:
                return
            ability.affects = "objects"
            ability.object_ids = ids
        context.state.floating_statics.append(ability)
        # A new continuous effect changes derived characteristics immediately
        # (RULE 613.1) — the caller's SBA pass would get there anyway, but a
        # grant whose effect isn't visible until then reads as a bug.
        context.recompute()


class EndTheTurnEffect(GameEffect):
    """"End the turn." (Day's Undoing/Time Stop-shaped reminder text) —
    untargeted, no RULE 115 target at all. See `RulesEngine.end_the_turn`'s
    own docstring for what this actually does (exiles the stack now;
    queues `GameState.end_turn_requested` for `GameEngine.advance_step` to
    drain, since a plain `RulesEngine` effect has no reach into the turn
    loop's own `_turn_steps`/`_cursor`).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        context.end_the_turn()


class ExileTopThenGrantConditionalCastEffect(GameEffect):
    """"Exile the top N cards of your library. Creature cards exiled this
    way gain 'You may cast this card from exile as long as `<condition>`.'"
    (Lukka, Coppercoat Outcast's own +1) — unlike every other exile-then-
    maybe-cast grant in this engine (`temp_play_permissions`, all turn-
    windowed), this one never expires on a clock; it holds for as long as
    `GameState.exile_cast_condition`'s `static_conditions` check keeps
    answering yes, which can also mean *starting* to hold again later if
    the board condition returns. No player choice at all — every creature
    card exiled this way gets the grant, unconditionally.
    """

    def __init__(
        self, count: int = 1, condition: Optional[dict[str, Any]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.condition = dict(condition or {})

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for _ in range(max(0, self.count)):
            if not player.library:
                break
            obj = player.library.pop()
            obj.zone = Zone.EXILE
            player.exile.append(obj)
            context.state.fire_event(
                GameEvent(EventType.EXILE, player_id=player.id, object=obj.name, from_zone="library")
            )
            if obj.card.is_creature:
                context.state.exile_cast_condition[obj.instance_id] = (player.id, dict(self.condition))


class RevealTopThenTakeAndLoseLifeEffect(GameEffect):
    """"Reveal the top card of your library and put that card into your
    hand. You lose life equal to its mana value." (MEC-12, Dark Confidant-
    shaped) — fully deterministic, no player choice at all (unlike `look_
    top_select`'s interactive "pick M of these", there is only one card and
    nothing to choose among), so both clauses are one atomic effect rather
    than two sequenced ones needing a resolve-time referent to share.

    Deliberately **not** routed through `RulesEngine.draw`/`DrawCardEffect`
    — RULE 121.4: an effect that moves a card from library to hand without
    the word "draw" isn't a draw at all, so it must never trigger a draw
    replacement/"whenever you draw a card" ability, or count toward "cards
    drawn this turn". Reveal itself has no state to model (this engine has
    no face-up/face-down public-knowledge tracking for a solo/local game);
    only the zone change and the life loss are real, observable effects.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        obj = player.library.pop()
        obj.zone = Zone.HAND
        player.hand.append(obj)
        context.lose_life(player, int(obj.card.converted_mana_cost or 0))


class ExileThenControllerRevealGreaterManaValueEffect(GameEffect):
    """"Exile target creature you control, then reveal cards from the top
    of your library until you reveal a creature card with greater mana
    value. Put that card onto the battlefield and the rest on the bottom
    of your library in a random order." (Lukka, Coppercoat Outcast's own
    −2) — the dynamic-criteria sibling of `DestroyExileThenController
    RevealCreatureEffect`: the mana-value floor is read off the exiled
    target itself at resolution (``target.card.converted_mana_cost + 1``),
    not a fixed threshold, and the dig always runs against the ability's
    own controller's library (the target is already "a creature you
    control", so there's no other controller to read one off of).
    """

    def __init__(
        self, target: Any = None, source: Optional["GameObject"] = None,
        target_kind: str = "creature_you_control",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        player = _controller_of(self.source, context)
        if player is None:
            return
        min_mv = target.card.converted_mana_cost + 1
        context.exile(target)
        context.engine.dig_until(
            player, {"type": "Creature", "min_mana_value": min_mv},
            hit_destination="battlefield", rest_destination="library_bottom_random",
        )


class EachCreatureYouControlDamageEachOpponentEffect(GameEffect):
    """"Each creature you control deals damage equal to its power to each
    opponent." (Lukka, Coppercoat Outcast's own −7 ultimate) — a double
    mass effect (every creature the controller has × every opponent),
    each creature's own amount being its own current power; no existing
    `DealDamageEffect` selector composes two independent mass groups like
    this (``each_creature_controller`` is the single-recipient mirror —
    one hit per creature, to *its own* controller, not every opponent).
    """

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        creatures = [
            o for o in list(context.state.battlefield)
            if o.is_creature and o.controller_id == player.id
        ]
        opponents = [p for p in context.state.living_players() if p.id != player.id]
        for creature in creatures:
            power = creature.power or 0
            if power <= 0:
                continue
            for opponent in opponents:
                context.deal_damage(opponent, power, creature)


class DiesReturnAsEnchantmentEffect(GameEffect):
    """"When ~ dies, if it was a creature, return it to the battlefield
    under its owner's control. It's an enchantment." (Enduring Vitality)
    — untargeted, self-only (the just-died source, a fresh RULE 400.7
    object in the graveyard by the time this trigger resolves). "If it
    was a creature" reads the firing DIES event's own ``object_types``
    snapshot (RULE 400.7 — the object has already left, so a live
    re-lookup would see nothing). "It's an enchantment" is RULE 613.4b's
    permanent characteristic-setting effect: a fresh ``type``
    `StaticAbility` (``remove_types=["creature"]``) appended straight
    onto the *returned* object's own `static_effects` — the same list a
    permanent's printed statics live in, so it's re-derived every
    `continuous.recompute` pass exactly like a real one, rather than a
    one-time field set the next `reset_derived` would silently wipe.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        event = context.trigger_event or {}
        if "creature" not in (event.get("object_types") or ()):
            return
        context.return_from_graveyard(self.source, "battlefield", controller_id=None)
        context.created_objects.append(self.source)
        self.source.static_effects.append(
            StaticAbility(
                "type", affects="self", params={"remove_types": ["creature"]},
                source=self.source,
            )
        )


class ReturnSelfToBattlefieldEffect(GameEffect):
    """"Return it to the battlefield [tapped] under its owner's control."
    (Nezahal, Primal Tide's own delayed-trigger half — "Discard three
    cards: Exile ~. Return it to the battlefield tapped under its owner's
    control at the beginning of the next end step.") — untargeted,
    self-only. Meant to run as a `CreateDelayedTriggerEffect` inner
    effect: that effect rebuilds against the *same* `GameObject` every
    time (RULE 400.7's `instance_id`/Python identity both survive
    `reset_as_new_object`, which mutates in place rather than replacing
    the reference), so `self.source` is still the right object once the
    delayed step arrives, however many zone changes it's been through
    since.
    """

    def __init__(self, tapped: bool = False, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.tapped = tapped

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        context.return_from_graveyard(
            self.source, "battlefield_tapped" if self.tapped else "battlefield"
        )


class RevealTopThenLandBattlefieldOrDrawEffect(GameEffect):
    """"…then reveal the top card of your library. If it's a land card,
    put it onto the battlefield tapped. Otherwise, draw a card."
    (Thrasios, Triton Hero's own activated ability, following a plain
    ``scry`` effect) — untargeted and fully deterministic: the top card's
    own type decides the branch, no player choice involved.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        if top.card.is_land:
            player.library.pop()
            top.zone = Zone.BATTLEFIELD
            top.tapped = True
            context.state.add_to_battlefield(top)
            context.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD, controller_id=player.id, object=top.name,
                    instance_id=top.instance_id, object_types=sorted(top.type_words),
                )
            )
        else:
            context.draw(player, 1)


class RevealTopThenMaybeBattlefieldIfLandOrCheapCreatureEffect(GameEffect):
    """"Look at the top card of your library. If it's a land card or a
    creature card with mana value less than or equal to the number of
    loyalty counters on ~, you may put that card onto the battlefield."
    (Nissa, Steward of Elements' 0 ability, MEC-41) — a genuine "you may"
    (unlike `RevealTopThenLandBattlefieldOrDrawEffect`'s deterministic
    land-or-draw branch just above), offered only when the top card
    actually qualifies; `GameObject.loyalty` is the live loyalty-counter
    count (RULE 606.5b).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or not player.library or self.source is None:
            return
        top = player.library[-1]
        qualifies = top.card.is_land or (
            top.is_creature and top.card.converted_mana_cost <= self.source.loyalty
        )
        if not qualifies:
            return
        context.choose_objects(
            player, [top], "library_to_battlefield", count=1, optional=True, source=self.source,
        )


class MonstrosityEffect(GameEffect):
    """RULE 701.37a: "Monstrosity N" — the body of ``<cost>: Monstrosity N``.

    Untargeted and always about the ability's own source (701.37b: only
    permanents become monstrous, and every printed monstrosity ability is the
    permanent's own), so there is no `TargetSpec` here at all — the
    `RenownEffect` shape rather than the `TapEffect` one.

    ``amount`` accepts the ``"x"`` sentinel `RulesEngine._substitute_x`
    rewrites with the announced {X} ("{X}{X}{R}: Monstrosity X", Fanatic of
    Xenagos-shaped), which is also what makes RULE 701.37c's "other abilities
    may refer to that X" work: `RulesEngine.monstrosity` records the
    substituted value on the permanent.
    """

    def __init__(self, amount: Any = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        # A still-unsubstituted "x" means no {X} was announced (a fixture, or
        # an ability reached outside the stack) — 0 is the honest reading.
        amount = self.amount if isinstance(self.amount, int) else 0
        context.monstrosity(self.source, amount)


class AdaptEffect(GameEffect):
    """RULE 701.46a: "Adapt N" — "if this permanent has no +1/+1 counters on
    it, put N +1/+1 counters on it".

    Deliberately its own effect rather than a conditional `AddCountersEffect`:
    the "has no +1/+1 counters" gate is part of the keyword action itself, and
    every real adapt card is an activated ability on the creature, so like
    `MonstrosityEffect` this is untargeted and self-scoped.
    """

    def __init__(self, amount: Any = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        amount = self.amount if isinstance(self.amount, int) else 0
        context.adapt(self.source, amount)


class GoadEffect(GameEffect):
    """RULE 701.15a: "Goad target creature" — and its "up to N target
    creatures" (RULE 115.1a) and pronoun forms.

    The goader is the effect's *controller* (701.15b: "a player other than
    the controller of the permanent, spell, or ability that caused it to be
    goaded"), read off the source at resolution rather than baked in at bind
    time, so a stolen/copied source goads for whoever controls it now.

    ``target_kind=None`` is the pronoun form — "…deals 2 damage to target
    creature. Goad that creature." (`GameContext.previous_targets`, the same
    referent `FightEffect` uses), or with ``referent="created"`` the tokens an
    earlier clause of this same resolution just made ("…each player creates a
    tapped 2/2 Bird. **The tokens** are goaded for the rest of the game.",
    `GameContext.created_objects`). ``selector`` is the untargeted mass form
    ("Goad all creatures your opponents control").

    ``permanent`` is the "…for the rest of the game" duration: the same
    designation with no expiry (`RulesEngine.goad`), rather than 701.15a's
    printed default of "until your next turn".
    """

    _SELECTORS = frozenset({"creatures_opponents_control"})
    _REFERENTS = frozenset({"previous", "created"})

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        optional: bool = False,
        count: Any = 1,
        selector: Optional[str] = None,
        count_selector: Optional[str] = None,
        referent: str = "previous",
        permanent: bool = False,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.selector = selector if selector in self._SELECTORS else None
        self.referent = referent if referent in self._REFERENTS else "previous"
        self.permanent = bool(permanent)
        self.target_spec = (
            TargetSpec(
                kind=target_kind,
                optional=optional,
                count=count if isinstance(count, int) else 1,
                count_selector=count_selector,
                # "For each opponent, goad up to one target creature **that
                # player** controls" — one requirement of "as many as there
                # are opponents", with the per-opponent half being exactly
                # RULE 115's already-modeled "controlled by different
                # players" constraint.
                distinct_controllers=count_selector == "opponents",
            )
            if target_kind is not None and self.selector is None
            else None
        )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        goader_id = getattr(self.source, "controller_id", None)
        if goader_id is None:
            return
        if self.selector is not None:
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            for obj in group_selector_objects(context.state, goader_id, self.selector):
                context.goad(obj, goader_id, permanent=self.permanent)
            return
        if self.target_spec is None:
            # A pronoun: whatever the previous clause of this same ability
            # targeted, or created (RULE 608.2 resolution order — either way
            # it has already resolved by the time this effect runs).
            chosen = list(
                context.created_objects if self.referent == "created"
                else context.previous_targets
            )
        elif self.target_spec.count_selector or self.target_spec.effective_count != 1:
            # A dynamic count is only known at announce time, so take
            # everything that was actually chosen rather than re-deriving it.
            chosen = list(targets or [])
        else:
            chosen = [targets[0]] if targets else []
        for obj in chosen:
            # A permanent, not a player: `previous_targets` and a shared
            # targets list can both hold either, and only a creature can be
            # goaded (RULE 701.15b). Duck-typed rather than `isinstance` —
            # `game/` must not import `models/` at runtime (the module
            # boundary; `GameObject` here is a TYPE_CHECKING name only).
            if getattr(obj, "instance_id", None) is not None:
                context.goad(obj, goader_id, permanent=self.permanent)


class LivingWeaponEffect(GameEffect):
    """RULE 702.92: "When this Equipment enters, create a 0/0 black
    Phyrexian Germ creature token, then attach this Equipment to it."

    A single atomic effect rather than `CreateTokenEffect` + `AttachEffect`:
    the attach target is the *specific* token this same effect just
    created, not a RULE 115 target or an entry off a shared targets list —
    there's no vocabulary for "whatever the previous effect just made" in
    the ordinary effects-list composition.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        from ..services.token_database import synthesize_token_card

        card = synthesize_token_card(
            "Phyrexian Germ", power=0, toughness=0, colors=["B"], subtypes=["Phyrexian", "Germ"]
        )
        tokens = context.engine.create_token(self.source.controller_id, card)
        if tokens:
            context.engine.attach_to_target(self.source, tokens[0])


class ClassLevelEffect(GameEffect):
    """Set a Class's class level (RULE 716.2c) — the effect of activating one
    of its "Level N: <cost>" abilities, not the cost itself (mirrors how
    Saga's chapter advance is a dedicated step, not a generic counter add).

    Sets the source's ``class_level`` counter directly to ``level`` (never
    incremented — a Class's level-up abilities are only ever legal one level
    at a time, `GameEngine._can_activate_class_level`) and fires
    `EventType.CLASS_LEVEL` so a rare "when this Class becomes level N"
    trigger can scope to it via the same ``chapter`` trigger key Saga's
    chapter triggers already use (`effect_binder._trigger_condition`).
    """

    def __init__(self, level: int, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.level = level

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = self.source
        if target is None:
            return
        target.counters["class_level"] = self.level
        context.state.fire_event(
            GameEvent(
                EventType.CLASS_LEVEL,
                object=target.name,
                instance_id=target.instance_id,
                controller_id=target.controller_id,
                chapter=self.level,
            )
        )


class ProliferateEffect(GameEffect):
    """RULE 701.30: give an additional counter of each kind already there to
    any number of permanents and/or players.

    RULE 701.30a's per-permanent/per-player "choose any number" is a real
    interactive choice this MVP doesn't offer (no counter-proliferation
    picker exists yet) — auto-applies to *every* permanent/player that
    already carries at least one counter, the same "auto-choose, no chooser
    in MVP" simplification `SacrificeEffect`/`GameEngine._sacrifice_
    candidate` use elsewhere. Player-level counters (poison via `Player.
    poison`, everything else — rad/energy/experience — via `Player.
    counters`) proliferate the same way (Vexing Radgull's own "otherwise,
    proliferate" branch needs exactly this: a player who already has rad
    counters gets another).

    ``times`` > 1 repeats the whole pass that many times (Contagion Engine's
    "Proliferate twice."/War of the Spark's "Proliferate three times.") —
    mirrors `ScryEffect.count`'s param shape.
    """

    def __init__(self, times: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.times = times

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for _ in range(self.times):
            for obj in list(context.state.battlefield):
                for kind in list(obj.counters.keys()):
                    if obj.counters.get(kind, 0) > 0:
                        context.add_counters(obj, 1, kind, source=self.source)
            for player in list(context.state.players):
                if player.poison > 0:
                    context.add_player_counters(player, 1, "poison", source=self.source)
                for kind in list(player.counters.keys()):
                    if player.counters.get(kind, 0) > 0:
                        context.add_player_counters(player, 1, kind, source=self.source)


class RemoveCountersEffect(GameEffect):
    """Strip counters from a target permanent (Vampire Hexmage-shaped:
    "Remove all counters from target permanent") or from every permanent on
    the battlefield (Oblivion Stone/Aether Snap/Thief of Blood-shaped:
    "Remove all counters from all permanents") — the unconditional "all"
    shape, ``max_count=None``. Goes through `context.add_counters` with a
    negative amount per kind (not a raw dict mutation), the same idiom
    `ProliferateEffect` uses, so a counter-removed trigger still fires
    correctly (RULE 122's `add_counters` already treats a non-positive
    amount as removal, bypassing replacement effects, which only ever apply
    to counters being *added*).

    ``max_count`` (Glissa Sunslayer/Heartless Act/Render Inert-shaped
    "remove up to N counters from target permanent/creature") switches to a
    genuinely different, interactive **chosen**-quantity shape instead:
    resolution opens a `pending_choice` (`RulesEngine.
    request_remove_counters_choice`) asking how many (0..min(max_count,
    counters present)), then — only if the target carries 2+ counter kinds —
    which kind to remove one at a time, mirroring `request_search`'s
    "open a choice, the engine's `resolve_*_choice` finishes it" shape
    rather than doing anything synchronously here.
    """

    def __init__(
        self,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
        max_count: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self.max_count = max_count
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def _strip(self, context: GameContext, obj: "GameObject") -> None:
        for kind in list(obj.counters.keys()):
            amount = obj.counters.get(kind, 0)
            if amount:
                context.add_counters(obj, -amount, kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.max_count is not None:
            target = targets[0] if targets else None
            if target is not None:
                context.engine.request_remove_counters_choice(
                    target, self.max_count, _controller_of(self.source, context)
                )
            return
        if self.target_spec is not None:
            target = targets[0] if targets else None
            if target is not None:
                self._strip(context, target)
            return
        for obj in list(context.state.battlefield):
            self._strip(context, obj)


class PumpEffect(GameEffect):
    """Give a target creature a temporary P/T boost and/or keywords "until end
    of turn" (Giant Growth; RULE 613.4d layer 7d + layer 6 for keywords).

    ``power``/``toughness`` may be negative (a "-N/-N" debuff). The change is
    an *effect* with a duration, not counters — it lives on the object's
    ``temp_*`` fields, which `continuous.recompute` folds in and the cleanup
    step (RULE 514.2) clears. Untargeted (no ``target_kind``) it pumps its own
    source, e.g. an activated "~ gets +1/+0 until end of turn". ``selector``
    (e.g. ``"creatures_you_control"``) pumps a whole *group* instead — an
    untargeted resolve-time selection (RULE 601.2c — not a target at all), the
    common Saga-chapter/anthem-spell shape "Creatures you control get +N/+N
    until end of turn" (e.g. History of Benalia's chapter III).

    ``unblockable=True`` additionally sets the target's ``temp_unblockable``
    flag (the same one `UnblockableEffect` sets) — "target creature gets
    +1/+0 until end of turn and can't be blocked this turn" (You Come to a
    River-shaped) is one *ability* with one target, not two independent
    targeting effects, so it's folded into this single effect (mirroring how
    a granted keyword already rides along in ``keywords``) rather than paired
    with a second `UnblockableEffect` that would ask for its own target.

    ``target_kind="attached_permanent"`` is a fourth mode — "{U}: Enchanted
    creature gains flying until end of turn." (Pemmin's Aura-shaped Aura
    activated ability): acts on whatever the effect's own source is
    currently `attached_to`, re-read live at resolution, no RULE 115 target
    at all — the same concept `TapEffect`'s own ``"attached_permanent"``
    mode uses, see its docstring.
    """

    def __init__(
        self,
        power: int = 0,
        toughness: int = 0,
        keywords: Optional[list[str]] = None,
        target_kind: Optional[str] = None,
        selector: Optional[str] = None,
        unblockable: bool = False,
        source: Optional["GameObject"] = None,
        count: int = 1,
        count_max: Optional[int] = None,
        optional: bool = False,
        amount_from_trigger_event: Optional[str] = None,
        per_recipient_controller_counter: Optional[str] = None,
        amount_from_count_selector: Optional[str] = None,
        amount_from_count_selector_negative: bool = False,
        creature_filter: Optional[dict] = None,
        previous_subject: bool = False,
        subtypes: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.power = power
        self.toughness = toughness
        self.keywords = list(keywords or [])
        self.selector = selector
        #: "Birds, Frogs, Otters, and Rats you control get +1/+1 until end
        #: of turn." (Valley Floodcaller, MEC-41) — the ``selector``-group
        #: sibling of `AddCountersEffect.subtypes` (same "any of these
        #: subtypes" membership check against the object's own printed
        #: type line), which this effect never had despite sharing the
        #: exact same `group_selector_objects` base.
        self.subtypes = [s.lower() for s in subtypes] if subtypes else None
        self.unblockable = unblockable
        #: ENG-30: "1 or 2 target creatures … . They gain vigilance and
        #: lifelink until end of turn." (A-Bretagard Stronghold-shaped) — the
        #: pump-family sibling of `TapEffect`/`ReturnToHandEffect`'s own
        #: ``previous_subject`` pronoun mode: no target of its own, acting on
        #: whatever group the *preceding* multi-target clause chose
        #: (`GameContext.previous_targets`), which may be a variable-size
        #: range rather than a fixed count — exactly the shape a target-count
        #: *range* creates and the reason no card needed this before.
        self.previous_subject = previous_subject
        #: "Each creature your opponents control gets -1/-1 until end of
        #: turn for each poison counter its controller has." (Phyresis
        #: Outbreak-shaped) — unlike `amount_from_trigger_event` (one
        #: shared magnitude for the whole group), each recipient's own
        #: boost scales independently by *its own controller's* count of
        #: this player-counter kind; ``power``/``toughness`` become the
        #: per-counter multiplier (``-1``) rather than a flat delta.
        #: ``selector``-only (no real card needs this on a single target).
        self.per_recipient_controller_counter = per_recipient_controller_counter
        #: "Whenever you gain life, ~ gets +X/+X until end of turn, where X
        #: is the amount of life you gained." (Field-Tested Frying Pan's
        #: granted ability) — the event field name (``"amount"``) to read
        #: off `GameContext.trigger_event` at resolution, overriding both
        #: ``power`` and ``toughness`` with the same value (always a
        #: symmetric "+X/+X" in practice). Same idiom as `LoseLifeEffect.
        #: amount_from_trigger_event`.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "Creatures you control gain trample and get +X/+X until end of
        #: turn, where X is the number of creatures you control."
        #: (Craterhoof Behemoth-shaped) — one shared magnitude for the
        #: whole group (unlike `per_recipient_controller_counter`'s
        #: per-object scaling), computed live via `continuous.
        #: count_selector` at resolve time rather than read off a firing
        #: event (`amount_from_trigger_event`'s job) — there's no trigger
        #: event to read here, this is the board state itself.
        self.amount_from_count_selector = amount_from_count_selector
        #: "…gets -X/-X until end of turn, where X is your devotion to
        #: black." (Blight-Breath Catoblepas) — `amount_from_count_selector`
        #: always reads a non-negative board count; this flips the sign
        #: after reading it, the "-X/-X" sibling of that always-positive
        #: "+X/+X" default rather than a second, duplicated param.
        self.amount_from_count_selector_negative = amount_from_count_selector_negative
        self._attached_mode = target_kind == "attached_permanent"
        if target_kind is not None and not self._attached_mode and not previous_subject:
            # PAR-15: "any number of target creatures each get +N/+N [and
            # gain `<keyword>`] until end of turn" (Aerial Formation/Ajani's
            # Presence/Colossal Heroics-shaped) — ``count`` > 1 is the same
            # "each of N gets the *full* amount" shape `AddCountersEffect`'s
            # own N>=2 mode uses (as opposed to a *divided* pool), since a
            # pump spell's whole point is every chosen creature getting the
            # stated boost independently.
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max,
                creature_filter=creature_filter,
            )

    def target_polarity(self) -> Optional[str]:
        return "harmful" if (self.power < 0 or self.toughness < 0) else "beneficial"

    def _pump_one(self, obj: "GameObject") -> None:
        obj.temp_power += self.power
        obj.temp_toughness += self.toughness
        obj.temp_keywords.update(self.keywords)
        if self.unblockable:
            obj.temp_unblockable = True
        # Record a per-source breakdown for the board's per-card effect
        # summary (display-only — the aggregate ints above drive the math).
        if self.power or self.toughness or self.keywords:
            obj.temp_effects.append(
                {
                    "source": self.source.name if self.source is not None else "Effekt",
                    "power": self.power,
                    "toughness": self.toughness,
                    "keywords": list(self.keywords),
                }
            )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.previous_subject:
            chosen = list(context.previous_targets)
            for obj in chosen:
                self._pump_one(obj)
            if chosen:
                context.recompute()
            return
        if self.amount_from_trigger_event:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
            self.power = amount
            self.toughness = amount
            if amount <= 0:
                return
        if self.amount_from_count_selector:
            from . import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            amount = continuous.count_selector(context.state, controller_id, self.amount_from_count_selector)
            if self.amount_from_count_selector_negative:
                amount = -amount
            self.power = amount
            self.toughness = amount
            if amount == 0:
                return
        if self.selector is not None:
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            selector = self.selector
            if selector == "previous_selector":
                # MEC-28: "They gain first strike until end of turn."
                # (Karlach, Fury of Avernus) — "they" is whichever group the
                # *preceding clause's own mass selector* acted on, read off
                # `GameContext.previous_selector` (`_apply_effects_
                # partitioned`) rather than a selector name baked in at
                # parse time. No preceding selector clause this resolution
                # (the sentinel is unreachable any other way) → no-op.
                selector = context.previous_selector
                if not selector:
                    return
            controller_id = getattr(self.source, "controller_id", None)
            group = group_selector_objects(context.state, controller_id, selector, src=self.source)
            if self.subtypes is not None:
                group = [
                    obj for obj in group
                    if any(
                        s in obj.card.type_line.partition("—")[2].strip().lower().split()
                        for s in self.subtypes
                    )
                ]
            if self.per_recipient_controller_counter:
                base_power, base_toughness = self.power, self.toughness
                for obj in group:
                    owner = context.state.player_by_id(obj.controller_id)
                    n = getattr(owner, self.per_recipient_controller_counter, 0) if owner else 0
                    self.power, self.toughness = base_power * n, base_toughness * n
                    self._pump_one(obj)
                self.power, self.toughness = base_power, base_toughness
                context.recompute()
                return
            for obj in group:
                self._pump_one(obj)
            context.recompute()
            return
        if self._attached_mode:
            host_id = getattr(self.source, "attached_to", None)
            target = context.state.find_object(host_id) if host_id is not None else None
        elif self.target_spec is not None:
            if self.target_spec.effective_count != 1:
                chosen = _chosen_targets(targets, self.target_spec.effective_count)
                for obj in chosen:
                    self._pump_one(obj)
                if chosen:
                    # Re-derive P/T now so a lethal -X/-X is caught by the
                    # SBA pass the caller runs right after this resolution.
                    context.recompute()
                return
            target = targets[0] if targets else None
        else:
            target = self.source
        if target is None:
            return
        self._pump_one(target)
        # Re-derive P/T now so a lethal -X/-X (toughness → 0) is caught by the
        # SBA pass the caller runs right after this resolution.
        context.recompute()


class ScryEffect(GameEffect):
    """Scry ``count`` for the effect's controller (RULE 701.18)."""

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.scry(player, self.count, source=self.source)


class SurveilEffect(GameEffect):
    """Surveil ``count`` for the effect's controller (RULE 701.31)."""

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.surveil(player, self.count, source=self.source)


class LookTopSelectEffect(GameEffect):
    """"Look at the top N cards of your library. Put M of them into your
    hand and the rest `<destination>`." (RULE 701.19-adjacent — Anticipate/
    Dig Through Time/Diabolic Vision/Ancestral Memories-shaped) — the
    fixed-selection-count sibling of scry/surveil, see
    `RulesEngine.look_top_select`."""

    def __init__(
        self,
        count: int = 1,
        select_count: int = 1,
        rest_destination: str = "library_bottom",
        rest_order: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.select_count = select_count
        self.rest_destination = rest_destination
        self.rest_order = rest_order

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.look_top_select(
                player, self.count, self.select_count, self.rest_destination, self.rest_order
            )


class ManifestEffect(GameEffect):
    """Manifest (RULE 701.40a) or cloak (RULE 701.58a) the top ``count``
    cards of the effect controller's library.

    One effect for both keyword actions because they *are* the same action
    bar one characteristic — a cloaked permanent has ward {2} (701.58a) —
    which `RulesEngine.manifest` takes as its ``kind``, exactly the way the
    engine already parameterizes morph vs. disguise."""

    def __init__(
        self, count: int = 1, kind: str = "manifest", source: Optional["GameObject"] = None
    ) -> None:
        super().__init__(source)
        self.count = count
        self.kind = kind

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.manifest(player, self.count, kind=self.kind)


class ManifestDreadEffect(GameEffect):
    """"Manifest dread": look at the top two cards of your library, put one
    onto the battlefield face down and the other into your graveyard (RULE
    701.40a plus a look-and-choose wrapper).

    The choice is a real interactive one (`RulesEngine.request_manifest_dread`)
    rather than "take the top card", since which of the two is worth
    manifesting — and which is worth *binning*, for a graveyard deck — is
    the whole decision the mechanic exists for."""

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.request_manifest_dread(player)


class CreateTokenEffect(GameEffect):
    """Create one or more token permanents (RULE 111.5 / 701.6).

    A **named** token (``token_name`` with no inline stats) is looked up in the
    curated `TokenDatabase` so it keeps its real abilities (a Treasure's mana
    ability, a Clue's sacrifice-to-draw); an **inline** token (power/toughness
    + colours + subtypes from the oracle clause) is synthesized. Either way the
    created objects are flagged tokens, so RULE 704.5d removes them the instant
    they leave the battlefield. The tokens are created under the effect's
    controller (its source's controller, else the active player).

    ``count_selector``, when given, overrides ``count`` with a live
    `continuous.count_selector` evaluation at resolve time — "create X
    Treasure tokens, where X is the number of artifacts and enchantments
    your opponents control" (Dockside Extortionist-shaped), scoped to the
    effect's own controller the same way a per-count anthem's ``power_
    count`` is.

    ``creators`` is who does the creating: the effect's own controller by
    default, or **every** player / every opponent ("Each player creates three
    tapped 1/1 white Warrior creature tokens." — The War Games), each getting
    their own ``count`` tokens under their own control. ``tapped`` is the
    "creates a **tapped** …" wording (RULE 110.5a — a permanent enters
    untapped unless an effect says otherwise), applied as the token enters
    rather than as a separate tap, so nothing sees it untapped in between.

    Whatever it creates is appended to `GameContext.created_objects`, which
    is how a following clause says "**the tokens** are goaded".
    """

    _CREATORS = frozenset({"you", "each_player", "each_opponent"})

    def __init__(
        self,
        count: int = 1,
        token_name: Optional[str] = None,
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
        count_selector: Optional[str] = None,
        creators: str = "you",
        tapped: bool = False,
        legendary: bool = False,
        pt_from_trigger_event: Optional[str] = None,
        count_from_trigger_event: Optional[str] = None,
        extra_counters: Optional[dict[str, Any]] = None,
        grant_self_anthem: Optional[dict[str, Any]] = None,
        is_artifact: bool = False,
    ) -> None:
        super().__init__(source)
        #: "…colorless Construct **artifact** creature token…" — see
        #: `synthesize_token_card`'s own ``is_artifact`` docstring for why
        #: this can't just be inferred from ``colors=[]``: plenty of
        #: legitimately colorless non-artifact tokens exist too.
        self.is_artifact = is_artifact
        #: "…create a 0/0 … Construct … token with '~ gets +1/+1 for each
        #: artifact you control.'" (Urza's Saga's own chapter II) — a
        #: self-scaling P/T static baked *onto the created token itself*,
        #: not the effect's source. Built via the same ``anthem`` factory
        #: an oracle-parsed "creatures you control get +N/+N" static uses
        #: (``power``/``toughness``/``power_count``/``toughness_count``,
        #: `continuous._pt_mod_count`'s selector vocabulary), appended to
        #: each created token's own `GameObject.static_effects` right after
        #: it enters — the same "append a static at resolve time" idiom
        #: `GrantGraveyardCastPermissionThisTurnEffect` already uses, just
        #: permanent (no ``expires_turn``) since a token's granted ability
        #: is part of its own definition, not a turn-scoped grant.
        self.grant_self_anthem = dict(grant_self_anthem) if grant_self_anthem else None
        self.count = count
        self.token_name = token_name
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.keywords = keywords or []
        self.count_selector = count_selector
        self.creators = creators if creators in self._CREATORS else "you"
        self.tapped = bool(tapped)
        self.legendary = bool(legendary)
        #: "…create an Incubator token with two +1/+1 counters on it…"
        #: (Glissa, Herald of Predation's Incubate) — ``{"kind": "+1/+1",
        #: "count": 2}``, put on each created token right after it enters,
        #: the same shape `request_search`'s own ``extra_counters`` uses
        #: for a found card reaching the battlefield.
        self.extra_counters = dict(extra_counters) if extra_counters else None
        # "…create an X/X blue Shark creature token with flying, where X is
        # that spell's mana value." (Shark Typhoon-shaped) — an X/X token
        # sized off the firing `SPELL_CAST` event's own field, read fresh at
        # resolve time (same idiom as `PumpEffect.amount_from_trigger_event`)
        # rather than a fixed ``power``/``toughness``. Always symmetric X/X
        # in practice, so one field sets both.
        self.pt_from_trigger_event = pt_from_trigger_event
        #: "…create **that many** 1/1 green Elf Warrior creature tokens."
        #: (Lathril, Blade of the Elves-shaped "whenever ~ deals combat
        #: damage to a player" payoff — "that many" always refers back to
        #: the firing event's own ``amount``, RULE 603.1) — the *count*
        #: sibling of ``pt_from_trigger_event`` (a token's stats, not how
        #: many get made). Overrides ``count``/``count_selector`` when set.
        self.count_from_trigger_event = count_from_trigger_event

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..services.token_database import default_token_database, synthesize_token_card

        power, toughness = self.power, self.toughness
        if self.pt_from_trigger_event:
            event = context.trigger_event
            x = int((event or {}).get(self.pt_from_trigger_event) or 0)
            power, toughness = x, x
        card = None
        # A bare named token (no inline stats) → the curated catalogue, so it
        # keeps its printed abilities. Inline stats always synthesize.
        if self.token_name and power is None and toughness is None:
            card = default_token_database().get_token(self.token_name)
        if card is None:
            card = synthesize_token_card(
                self.token_name or (self.subtypes[0] if self.subtypes else "Token"),
                power=power,
                toughness=toughness,
                colors=self.colors,
                subtypes=self.subtypes,
                keywords=self.keywords,
                legendary=self.legendary,
                is_artifact=self.is_artifact,
            )
        controller_id = (
            self.source.controller_id if self.source is not None
            else context.active_player.id
        )
        count = self.count
        if self.count_selector:
            from . import continuous  # avoid the continuous↔effects import cycle

            count = continuous.count_selector(
                context.state, controller_id, self.count_selector, source=self.source
            )
        if self.count_from_trigger_event:
            event = context.trigger_event
            count = int((event or {}).get(self.count_from_trigger_event) or 0)
        if count <= 0:
            return
        if self.creators == "each_player":
            creator_ids = [p.id for p in context.state.living_players()]
        elif self.creators == "each_opponent":
            creator_ids = [p.id for p in context.state.living_players() if p.id != controller_id]
        else:
            creator_ids = [controller_id]
        for creator_id in creator_ids:
            made = context.create_token(creator_id, card, count) or []
            if self.tapped:
                for token in made:
                    token.tapped = True
            if self.extra_counters:
                kind = str(self.extra_counters.get("kind", "+1/+1"))
                amount = int(self.extra_counters.get("count", 1) or 0)
                if amount:
                    for token in made:
                        context.add_counters(token, amount, kind, source=self.source)
            if self.grant_self_anthem:
                from .effect_binder import build_effects  # function-scoped: effects↔binder cycle
                from ..parser.oracle.spec import EffectSpec

                for token in made:
                    anthem = build_effects(
                        [EffectSpec("anthem", {**self.grant_self_anthem, "affects": "self"})],
                        token,
                    )
                    token.static_effects.extend(anthem)
            # The referent for a following "the tokens are …" clause.
            context.created_objects.extend(made)


class CopyPermanentEffect(GameEffect):
    """Create a token that's a copy of a target permanent (RULE 707 / 707.2)
    — or, with ``target_kind=None``, of the effect's own source, untargeted
    (Bloodforged Battle-Axe's "create a token that's a copy of this
    Equipment" — no player choice involved, mirroring `TapEffect`'s/
    `AddCountersEffect`'s same ``target_kind=None`` self-acting mode).

    Targets a permanent (a creature by default — "create a token that's a copy
    of target creature") and makes ``count`` token copies under the effect's
    controller (its source's controller, else the active player). The basic
    version copies the printed card; layered/copy-of-copy nuances (RULE 707.2
    copiable values, other copy effects) are not modeled."""

    def __init__(
        self,
        count: int = 1,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        count_if_kicked: Optional[int] = None,
        count_from_trigger_event: Optional[str] = None,
        haste: bool = False,
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        not_legendary: bool = False,
        referent: str = "source",
        target_count: int = 1,
        target_count_max: Optional[int] = None,
        target_optional: bool = False,
        set_power: Optional[int] = None,
        set_toughness: Optional[int] = None,
        extra_temp_keywords: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        #: PAR-18's own pronoun antecedent — "exile up to 1 target creature
        #: card from a graveyard. Create a token that's a copy of **that
        #: card**." (Ardyn/Anikthea-shaped): the copied object is neither a
        #: fresh RULE 115 target nor this effect's own source, but whatever
        #: an *earlier clause of the same ability* just targeted (RULE
        #: 608.2 resolution order — it has already resolved, in whatever
        #: zone it left the card in). ``target_kind=None`` keeps its
        #: existing "copy the source" default (``referent="source"``);
        #: ``referent="previous"`` is the new pronoun mode, the same
        #: `GameContext.previous_targets` `GoadEffect`/`FightEffect` already
        #: read for "goad it"/pronoun fights.
        #: ``referent="trigger_event"`` (Ashling, the Limitless, MEC-42 —
        #: "Whenever you sacrifice a nontoken Elemental, create a token
        #: that's a copy of **it**.") reads the firing event's own
        #: ``instance_id`` and resolves it via `GameState.find_object`,
        #: which searches every zone, not just the battlefield — unlike
        #: ``"previous"``'s RULE 608.2 pronoun (an earlier clause's own
        #: target), this is the trigger's *subject itself*, already gone
        #: from the battlefield by the time a SACRIFICE/DIES trigger
        #: resolves.
        self.referent = referent if referent in ("source", "previous", "trigger_event") else "source"
        #: "…except it has haste." (Kiki-Jiki, Mirror Breaker-shaped) — a
        #: temp keyword grant on the freshly-made token(s), the same
        #: `temp_keywords` set every other resolve-time haste grant uses.
        self.haste = haste
        #: "…except it's a(n) X in addition to its other types" (the
        #: Cackling Counterpart/artifact-token-cycle "except it's an
        #: artifact…" shape) / "…except it isn't legendary." (Multiversal
        #: Recruitment-shaped) — `Card.as_copy`'s own modifiers, threaded
        #: through `RulesEngine.copy_permanent` rather than applied here, so
        #: the token's bound abilities are derived from the *modified* card
        #: from the start (`create_token` binds off whatever card it's given).
        self.add_types = add_types
        self.add_subtypes = add_subtypes
        self.not_legendary = not_legendary
        #: "…except it's a 1/1 red Balloon creature…" (The Jolly Balloon
        #: Man, MEC-40) — `Card.as_copy`'s own P/T-override params, threaded
        #: through the same way ``add_types``/``add_subtypes`` are.
        self.set_power = set_power
        self.set_toughness = set_toughness
        #: "…and it has flying and haste." (The Jolly Balloon Man, MEC-40)
        #: — ``haste`` above stays its own bool for backward compatibility
        #: (every existing caller already sets it that way); any *other*
        #: keyword granted alongside a copy goes here instead, applied the
        #: same ``temp_keywords`` way.
        self.extra_temp_keywords = list(extra_temp_keywords or [])
        # RULE 702.33b's *override* kicked-conditional ("Create a token
        # that's a copy of target creature. If this spell was kicked,
        # create five of those tokens instead." — Rite of Replication) —
        # same shape as `DealDamageEffect.amount_if_kicked`, just overriding
        # ``count`` instead of ``amount``.
        self.count_if_kicked = count_if_kicked
        #: "…create that many tokens that are copies of equipped
        #: creature." (Mirrormind Crown) — "that many" reads the firing
        #: `CREATE_TOKENS` event's own ``amount``, the same "read this
        #: firing's own payload" idiom `CreateTokenEffect.count_from_
        #: trigger_event` uses. Overrides ``count`` when set.
        self.count_from_trigger_event = count_from_trigger_event
        self.target = target
        #: ``target_kind="attached_permanent"`` (Mirrormind Crown-shaped
        #: "…copies of **equipped** creature") is a third self-acting mode
        #: alongside the plain-target and ``None``-copies-the-source ones:
        #: whatever this Equipment/Aura is currently attached to, re-read
        #: live at resolution, the same concept `TapEffect`'s own
        #: ``"attached_permanent"`` mode uses.
        self._attached_mode = target_kind == "attached_permanent"
        #: "Choose any number of target creatures you control. For each of
        #: them, create a token that's a copy of that creature…" (Twinflame-
        #: shaped, MEC-12) — a genuine *per-target* multi-copy, unlike
        #: ``count``'s existing "N copies of the (one) target" meaning
        #: (Rite of Replication-shaped); named distinctly so both can
        #: combine on some future card without colliding.
        self.target_count = target_count
        self.target_spec = (
            TargetSpec(kind=target_kind, count=target_count, count_max=target_count_max, optional=target_optional)
            if target_kind is not None and not self._attached_mode else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if (
            self.target_spec is not None and not self._attached_mode
            and self.target_spec.effective_count != 1
        ):
            controller_id = (
                self.source.controller_id if self.source is not None
                else context.active_player.id
            )
            for one in _chosen_targets(targets, self.target_spec.effective_count):
                made = context.copy_permanent(
                    controller_id, one, 1,
                    add_types=self.add_types, add_subtypes=self.add_subtypes,
                    not_legendary=self.not_legendary,
                    set_power=self.set_power, set_toughness=self.set_toughness,
                )
                context.created_objects.extend(made)
                if self.haste:
                    for obj in made:
                        obj.temp_keywords.add("haste")
                for kw in self.extra_temp_keywords:
                    for obj in made:
                        obj.temp_keywords.add(kw)
            return
        target = (targets[0] if targets else None) or self.target
        if self._attached_mode:
            attached_to = getattr(self.source, "attached_to", None)
            target = context.state.find_object(attached_to) if attached_to is not None else None
        elif target is None and self.target_spec is None:
            if self.referent == "previous":
                prev = list(context.previous_targets)
                target = prev[0] if prev else None
            elif self.referent == "trigger_event":
                event = context.trigger_event
                iid = (event or {}).get("instance_id")
                target = context.state.find_object(iid) if iid is not None else None
            else:
                target = self.source
        if target is None:
            return
        controller_id = (
            self.source.controller_id if self.source is not None
            else context.active_player.id
        )
        kicker_count = getattr(self.source, "kicker_count", 0) or 0
        count = self.count_if_kicked if (self.count_if_kicked is not None and kicker_count > 0) else self.count
        if self.count_from_trigger_event:
            event = context.trigger_event
            count = int((event or {}).get(self.count_from_trigger_event) or 0)
        if count > 0:
            made = context.copy_permanent(
                controller_id, target, count,
                add_types=self.add_types, add_subtypes=self.add_subtypes,
                not_legendary=self.not_legendary,
                set_power=self.set_power, set_toughness=self.set_toughness,
            )
            # RULE 608.2's "the tokens"/"it" referent for a following
            # clause — `create_token`'s own effect already does this; this
            # class just hadn't needed it until a delayed-sacrifice tail
            # (Kiki-Jiki) had to name what got made.
            context.created_objects.extend(made)
            if self.haste:
                for obj in made:
                    obj.temp_keywords.add("haste")
            for kw in self.extra_temp_keywords:
                for obj in made:
                    obj.temp_keywords.add(kw)


class EnterAsCopyReplacement(GameEffect):
    """"You may have this permanent enter the battlefield as a copy of
    target X" (RULE 614.1c/614.12, Clever Impersonator/Phantasmal Image/Copy
    Artifact/Vesuvan Shapeshifter-style) — a pure data holder, never applied
    imperatively (``apply`` returns ``None``, same "consulted elsewhere"
    idiom as `StaticAbility`/`ReplacementEffect`).

    `RulesEngine._offer_enter_as_copy` reads this off `GameObject.
    enter_as_copy_effects` at the one choke point where the permanent is
    about to be added to the battlefield (`resolve_top_of_stack`/
    `create_token`), *before* `add_to_battlefield`/`ENTERS_BATTLEFIELD` — so
    the object is never observably "itself" first, unlike the previous
    ENTERS_BATTLEFIELD-trigger modeling this replaces. A legal-target check
    there resolves the choice (interactively, if 2+ options) and calls
    `copy_mechanics.become_copy` before finishing battlefield entry.

    ``add_types``/``add_subtypes`` cover a card's own "except it's a(n) X in
    addition to its other types" clause (`Card.as_copy`).
    """

    def __init__(
        self,
        target_kind: str = "permanent",
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        optional: bool = True,
        description: str = "",
        extra_counter_if_creature: Optional[str] = None,
        extra_counter_if_planeswalker: Optional[str] = None,
        grant_mana_option: Optional[dict[str, int]] = None,
        only_types: Optional[list[str]] = None,
        add_keywords: Optional[list[str]] = None,
        add_keywords_if_target_lacks: Optional[list[str]] = None,
        keep_own_abilities: bool = False,
        max_mana_value_from_mana_spent: bool = False,
    ) -> None:
        super().__init__(None)
        self.target_kind = target_kind
        #: "…of any creature on the battlefield with mana value less than
        #: or equal to the amount of mana spent to cast ~." (Mockingbird) —
        #: `GameObject.mana_spent_to_cast`, read live when the choice is
        #: offered (`RulesEngine._offer_enter_as_copy`).
        self.max_mana_value_from_mana_spent = max_mana_value_from_mana_spent
        self.add_types = list(add_types or [])
        self.add_subtypes = list(add_subtypes or [])
        self.optional = optional
        self.description = description
        #: "…except it loses all other card types" (Imposter Mech) — see
        #: `Card.as_copy`'s own ``only_types`` param.
        self.only_types = list(only_types) if only_types is not None else None
        #: "…except it has [keyword]" (Imposter Mech's granted Crew 3) —
        #: unconditional; see `Card.as_copy`'s ``add_keywords``.
        self.add_keywords = list(add_keywords or [])
        #: "…except it has [keyword] if [the copied creature] doesn't have
        #: [keyword]" (Flesh Duplicate's conditional Vanishing 3) — each
        #: entry granted only when the *target*'s own printed keywords
        #: don't already include it, checked in `resolve_enter_as_copy_
        #: choice` before `become_copy` runs.
        self.add_keywords_if_target_lacks = list(add_keywords_if_target_lacks or [])
        #: "…except it has ~'s other abilities" (Sakashima of a Thousand
        #: Faces) — RULE 706.2 would otherwise erase ~'s own printed
        #: abilities entirely; see `resolve_enter_as_copy_choice`.
        self.keep_own_abilities = keep_own_abilities
        #: "…except it's an artifact and it has '{T}: Add {U}.'" (Machine
        #: God's Effigy) — a plain ``{T}``-only mana ability granted
        #: *onto the copy itself*, since RULE 707.2's copy replaces the
        #: original card's own printed text (including its own real
        #: "{T}: Add {U}." line) with the copied creature's, so that
        #: ability has to be re-added as part of this same "except" clause
        #: rather than assumed to survive. `GameObject.granted_mana_
        #: options` is the same plain-option list a layer-6 "Elves you
        #: control have '{T}: Add {B}.'" grant already appends to.
        self.grant_mana_option = dict(grant_mana_option) if grant_mana_option else None
        #: "…except it enters with an additional +1/+1 counter on it if
        #: it's a creature[, or a loyalty counter if it's a planeswalker]."
        #: (Spark Double) — a counter *kind* name (`RulesEngine.
        #: add_counters`'s vocabulary), applied once the copy is made and
        #: only when the resulting permanent is that type — a creature
        #: copy of a planeswalker (or vice versa) never happens, but the
        #: two are independent fields since either alone is a real printed
        #: shape elsewhere.
        self.extra_counter_if_creature = extra_counter_if_creature
        self.extra_counter_if_planeswalker = extra_counter_if_planeswalker

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_as_copy, not applied


class ChooseCreatureTypeReplacement(GameEffect):
    """"As ~ enters, choose a creature type." (RULE 601.2b-style
    characteristic-defining choice made as part of entering — not a
    triggered ability, so it's an ``enter_replacement`` like
    `EnterAsCopyReplacement`, just without a target — a pure data holder
    (``apply`` is never called).

    `RulesEngine._offer_enter_choices` reads this off `GameObject.
    enter_choice_effects` at the same battlefield-entry choke point
    `_offer_enter_as_copy` reads `enter_as_copy_effects` from, and stamps the
    answer onto `GameObject.chosen_type` — read back by `game/continuous.py`'s
    ``subtype_from_source`` selector param (Adaptive Automaton/Arcane
    Adaptation-shaped "creatures you control of the chosen type …"/"~ is the
    chosen type in addition to its other types" lords).
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseBasicLandTypeReplacement(GameEffect):
    """"As ~ enters, choose a basic land type." (RULE 601.2b, PAR-4 —
    Realmwright/A-Thran Portal-shaped) — the basic-land-type sibling of
    `ChooseCreatureTypeReplacement`; see its docstring. Deliberately its own
    class (rather than a flag on `ChooseCreatureTypeReplacement`) so
    `RulesEngine._offer_enter_choices` can tell which fixed option list to
    offer, but it stamps the very same `GameObject.chosen_type` field —
    "the chosen type" grant clause (`continuous.py`'s ``subtype_from_source``
    selector, already shipped for the creature-type family) reads a bare
    subtype string either way and doesn't care which family produced it.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseColorReplacement(GameEffect):
    """"As ~ enters, choose a color." — the colour sibling of
    `ChooseCreatureTypeReplacement`; see its docstring. Stamps
    `GameObject.chosen_color`, read by `continuous.py`'s
    ``color_from_source`` selector param.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseNamedModeReplacement(GameEffect):
    """"As this enters, choose <Label1> or <Label2>." (Struggle for Project
    Purity: "choose Brotherhood or Enclave") — a third `enter_choice_effects`
    sibling of `ChooseCreatureTypeReplacement`/`ChooseColorReplacement`,
    for a small closed set of *named* flavour modes rather than a creature
    type/colour. Each subsequent named-bullet ability ("Brotherhood — ...",
    "Enclave — ...") stays a normal, always-bound ability, just gated by
    `effect_binder._trigger_condition`'s ``"named_mode"`` predicate
    checking the answer this stamps onto `GameObject.chosen_mode` — so the
    "wrong" mode's ability simply never fires, rather than never being
    bound at all.

    ``options`` is the card's own printed label list (``["Brotherhood",
    "Enclave"]``); `RulesEngine._offer_enter_choices` offers them as a
    lowercase-slug choice and stamps the answer onto `chosen_mode`.
    """

    def __init__(self, options: Optional[list[str]] = None, description: str = "") -> None:
        super().__init__(None)
        self.options = list(options or [])
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseCardNameReplacement(GameEffect):
    """"As ~ enters the battlefield, choose a card name." (MEC-12, Pithing
    Needle/Phyrexian Revoker-shaped) — a fourth `enter_choice_effects`
    sibling of `ChooseCreatureTypeReplacement`/`ChooseColorReplacement`/
    `ChooseNamedModeReplacement`, but naming any Magic card rather than
    picking from a small enumerable set: `RulesEngine._offer_enter_choices`
    offers a free-text choice (suggestions only, like `request_name_card`'s
    own "name any card" idiom) and stamps the answer verbatim onto
    `GameObject.chosen_card_name` — read back by `continuous.
    group_selector_objects`'s ``card_name_from_source`` selector param.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseNumberReplacement(GameEffect):
    """"As this creature enters, choose a number." (RULE 601.2b, Sanctum
    Prelate — MEC-43) — a fifth `enter_choice_effects` sibling of
    `ChooseCreatureTypeReplacement`/`ChooseColorReplacement`/
    `ChooseNamedModeReplacement`/`ChooseCardNameReplacement`, the
    free-text-numeric case: `RulesEngine._offer_enter_choices` offers a
    free-text choice (same idiom `ChooseCardNameReplacement` uses for an
    unenumerable answer space) and stamps the parsed integer onto
    `GameObject.chosen_number` — read back by `continuous.cast_prohibited`'s
    ``max_mana_value="chosen_number"`` sentinel.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class BecomeCopyUntilEndOfTurnEffect(GameEffect):
    """*This* permanent becomes a copy of a target creature until end of
    turn (Cursed Mirror-style: "{T}: ~ becomes a copy of target creature
    until end of turn.").

    Unlike `RulesEngine.become_copy` (a permanent mutation, RULE 706.2), this
    reverts automatically at cleanup (RULE 514.2) — see `RulesEngine.
    become_copy_until_end_of_turn` and `GameEngine._step_cleanup`.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None or self.source is None or target is self.source:
            return
        context.become_copy_until_end_of_turn(self.source, target)


class SetCopyTargetEffect(GameEffect):
    """Choose/change the target a layer-1 conditional-copy static ability
    copies (Vesuvan Shapeshifter's "you may have it be a copy of another
    target creature") — sets `GameObject.copy_target_id`, which
    `continuous.recompute`'s layer-1 pass (`_apply_copy_layer`) reads fresh
    every pass. A simplified stand-in for RULE 707.9's "special action"
    timing (the same simplification tier `EnterAsCopyReplacement` uses
    elsewhere) — modeled as a costless activated ability instead.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None or self.source is None or target is self.source:
            return
        context.set_copy_target(self.source, target)


class IntuitionEffect(GameEffect):
    """"Search your library for `<count>` cards and reveal them. Target
    opponent chooses one. Put that card into your hand and the rest into
    your graveyard. Then shuffle." (Intuition) — see
    `RulesEngine.request_intuition` for the two-phase shape (the searcher
    picks the cards, then the *targeted opponent* — a real RULE 115 target,
    not the searcher — picks from among them).

    Generalized (MEC-41, Gifts Ungiven) via the same params `request_
    intuition` gained — ``search_optional``/``distinct_names`` shape the
    *searcher's* phase, ``chosen_count``/``chosen_destination``/
    ``rest_destination`` the *chooser's* one. All default to Intuition's
    own original fixed shape, unchanged.
    """

    def __init__(
        self, count: int = 3, source: Optional["GameObject"] = None,
        search_optional: bool = False, distinct_names: bool = False,
        chosen_count: int = 1, chosen_destination: str = "hand",
        rest_destination: str = "graveyard",
    ) -> None:
        super().__init__(source)
        self.count = count
        self.search_optional = search_optional
        self.distinct_names = distinct_names
        self.chosen_count = chosen_count
        self.chosen_destination = chosen_destination
        self.rest_destination = rest_destination
        self.target_spec = TargetSpec(kind="opponent")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        searcher = _controller_of(self.source, context)
        chooser = targets[0] if targets else None
        chooser_id = getattr(chooser, "id", None)
        if searcher is None or chooser_id is None:
            return
        context.request_intuition(
            searcher, chooser_id, self.count, self.source,
            search_optional=self.search_optional, distinct_names=self.distinct_names,
            chosen_count=self.chosen_count, chosen_destination=self.chosen_destination,
            rest_destination=self.rest_destination,
        )


class SearchLibraryEffect(GameEffect):
    """Search the controller's library for a card (RULE 701.19), tutors.

    The search is parameterized on two independent axes so one effect covers
    the whole tutor family (Demonic Tutor, Rampant Growth, Cultivate, Vampiric
    Tutor, Entomb, …):

    * ``criteria`` — *what* to look for, as pure data understood by
      `models.card_query`: ``""`` for "a card", a type string like
      ``"Creature"``, or a dict like ``{"type": ["Plains", "Island"]}`` /
      ``{"basic": True}`` / ``{"type": "Creature", "max_mana_value": 3}``.
    * ``destination`` — *where* the found card goes: ``"hand"`` (default),
      ``"battlefield"``, ``"battlefield_tapped"``, ``"library_top"``,
      ``"library_bottom"``, ``"graveyard"``, ``"exile"``, ``"cast_free"``
      (casts it immediately, Sunforger-shaped), or ``"exile_free_cast"``
      (exiles it with a *standing* "you may cast it without paying its
      mana cost" permission instead — Bring to Light, MEC-41).
    * ``count`` — how many cards (search for "up to N"); the choice is
      offered one card at a time.
    * ``zones`` — *where* to look: ``["library"]`` (default, RULE 701.19)
      or ``["library", "graveyard"]``/``["graveyard"]`` for "search your
      library and/or graveyard" (backgrounds/Lurrus-shaped).
    * ``destinations`` — an optional per-found-card override list,
      positional against the picks, for a split destination ("put one onto
      the battlefield tapped and the other into your hand" —
      Cultivate/Kodama's Reach); ``destination`` remains the fallback.
    * ``destination_if`` — a *conditional* override instead of a positional
      one: ``[{"criteria": {"type": "Land"}, "destination":
      "battlefield_tapped"}]`` is Archdruid's Charm's "put it onto the
      battlefield tapped if it's a land card. Otherwise, put it into your
      hand." Which branch applies depends on the card the player actually
      found, so it can only be decided once the search is answered.
    * ``exile_rest`` — once the search finishes, exile every remaining
      criteria-matching card still in ``zones`` and skip the shuffle
      entirely (Doomsday-shaped).

    Because *which* card is a player choice, this doesn't move a card itself
    — it asks the engine to open a choice (`GameContext.request_search`); the
    chosen card(s) are moved to their destination(s) and the library
    shuffled (unless ``exile_rest``) when the player answers.

    ``mana_value_from`` makes the criteria's mana-value bound *dynamic*
    rather than printed: ``{"source": "sacrificed_cost", "plus": 2, "cmp":
    "le"}`` is Eldritch Evolution's "with mana value X or less, where X is 2
    plus the sacrificed creature's mana value"; ``"cmp": "eq"`` is Neoform's
    exact "equal to 1 plus …". The base value is read off the spell object's
    own `GameObject.sacrificed_cost_mana_value`, stamped when the RULE
    601.2b additional cost was paid — `StackItem.x` can't carry it (it only
    ever threads an *announced* {X}). ``{"source": "count_selector",
    "count_selector": "lands_you_control"}`` (MEC-43 round 3, Beseech the
    Queen's "mana value less than or equal to the number of lands you
    control") reads the base off a live board count instead
    (`continuous.count_selector`, the same whitelisted vocabulary a
    characteristic-defining P/T uses) — evaluated fresh when the search
    opens, not cached from announcement, since RULE 601.2c legality is
    checked at the *search*'s own resolution. Merged into ``criteria`` at
    resolution time as ``max_mana_value``/``mana_value``, so
    `models.card_query` needs no dynamic vocabulary of its own.

    ``type_restriction`` is accepted as a deprecated alias for a string
    ``criteria`` so older fixtures keep working.
    """

    def __init__(
        self,
        criteria: Any = "",
        destination: str = "hand",
        count: int = 1,
        optional: bool = True,
        player: Any = None,
        source: Optional["GameObject"] = None,
        type_restriction: Optional[str] = None,
        zones: Optional[list[str]] = None,
        destinations: Optional[list[str]] = None,
        exile_rest: bool = False,
        mana_value_from: Optional[dict[str, Any]] = None,
        extra_counters: Optional[dict[str, Any]] = None,
        destination_if: Optional[list[dict[str, Any]]] = None,
        attach_to_creature_you_control: bool = False,
        remember: bool = False,
        total_mana_value_budget: Optional[int] = None,
        player_from_target: bool = False,
        share_land_type: bool = False,
    ) -> None:
        super().__init__(source)
        #: "...basic land cards **that share a land type**." (Myriad
        #: Landscape, MEC-43 round 3) — a cross-pick constraint on a
        #: multi-card search; see `RulesEngine.request_search`'s own
        #: docstring for how it's enforced round by round.
        self.share_land_type = share_land_type
        #: "Search **target opponent's** library for a card…" (Praetor's
        #: Grasp, MEC-42) — ``player`` becomes whichever player this
        #: ability's own RULE 115 target resolved to (the library that gets
        #: searched/shuffled and stays the found card's owner), while the
        #: *chooser* — who actually answers the search — stays this
        #: effect's own controller, via `RulesEngine.request_search`'s
        #: ``chooser`` param. Distinct from every other ``player`` sentinel
        #: above (``"previous_target_controller"`` etc.), which all still
        #: make the target both the searcher *and* the one who answers.
        self.player_from_target = player_from_target
        if player_from_target:
            self.target_spec = TargetSpec(kind="opponent", description="Gegner")
        #: "…for any number of creature cards with **total** mana value 6
        #: or less…" (Protean Hulk, MEC-12) — a running budget shared
        #: across the *whole* multi-pick search, unlike `criteria`'s own
        #: ``max_mana_value`` (a fixed per-card cap): each round's own
        #: eligible pool additionally excludes any card whose mana value
        #: would push the sum of everything picked so far over this total.
        #: See `RulesEngine.request_search`'s own docstring for how the
        #: running total is threaded through the choice loop.
        self.total_mana_value_budget = total_mana_value_budget
        #: "Exile a card from a graveyard. [...] the exiled card." (Cemetery
        #: Gatekeeper) — `ExileEffect.remember`'s own sibling for a search-
        #: shaped exile: stamps the found card's `instance_id` onto this
        #: ability's own source (`GameObject.linked_exile_id`) once the
        #: player's pick is known (`RulesEngine._finish_search`), since
        #: unlike a RULE 115 target a search's result isn't known until the
        #: `pending_choice` round trip finishes.
        self.remember = remember
        #: A per-found-card *conditional* destination (RULE 701.19c), unlike
        #: the positional ``destinations`` above: a list of ``{"criteria":
        #: <card_query>, "destination": <str>}`` rules, first match wins,
        #: falling back to ``destinations``/``destination``. Archdruid's
        #: Charm's "put it onto the battlefield tapped **if it's a land
        #: card**. Otherwise, put it into your hand." — the branch depends
        #: on *which* card the player found, so it can't be decided when the
        #: search is opened.
        self.destination_if = destination_if
        self.criteria = type_restriction if type_restriction is not None else criteria
        self.destination = destination
        self.count = count
        self.optional = optional
        self.player = player
        self.zones = zones
        self.destinations = destinations
        self.exile_rest = exile_rest
        self.mana_value_from = mana_value_from
        #: "…put that card onto the battlefield **with an additional +1/+1
        #: counter on it**" (Neoform) — ``{"kind": "+1/+1", "count": 1}``,
        #: applied by `RulesEngine.resolve_search_choice` right after the
        #: found card reaches the battlefield.
        self.extra_counters = extra_counters
        #: "…put it onto the battlefield, **attach it to a creature you
        #: control**" (Stonehewer Giant/Quest for the Holy Relic) — see
        #: `RulesEngine._finish_search`'s own docstring for the auto-pick.
        self.attach_to_creature_you_control = attach_to_creature_you_control

    def _resolved_criteria(self, context: Optional[GameContext] = None) -> Any:
        """``criteria`` with any `mana_value_from` bound to a real number."""
        if not self.mana_value_from:
            return self.criteria
        if self.mana_value_from.get("source") == "count_selector" and context is not None:
            from . import continuous  # avoid the continuous↔effects import cycle
            base = continuous.count_selector(
                context.state, getattr(self.source, "controller_id", None),
                self.mana_value_from["count_selector"], source=self.source,
            )
        else:
            base = getattr(self.source, "sacrificed_cost_mana_value", None)
            if base is None:
                # RULE 601.2b's cost was never paid (or the record is gone) —
                # fail closed to "nothing matches" rather than silently
                # searching for an unrestricted card.
                base = -1
        value = base + int(self.mana_value_from.get("plus", 0))
        criteria = dict(self.criteria) if isinstance(self.criteria, dict) else (
            {"type": self.criteria} if self.criteria else {}
        )
        criteria["max_mana_value"] = value
        if self.mana_value_from.get("cmp") == "eq":
            # `card_query` has no single "exactly N" key — an equal bound is
            # the two-sided one (Neoform's "mana value equal to 1 plus …").
            criteria["min_mana_value"] = value
        return criteria

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.player == "previous_target_controller":
            # "Its controller may search their library …" (Assassin's
            # Trophy-shaped) — the controller of whatever this same
            # resolution's *previous* clause targeted (RULE 608.2's
            # referent, `GameContext.previous_targets`), the same sentinel
            # `PayCostThenEffect`'s own ``payer`` param already uses for
            # Chain of Vapor. No previous target on record (shouldn't
            # happen for a real card printing this shape, but fails closed
            # rather than guessing) skips the search entirely.
            prev = list(context.previous_targets)
            player = (
                context.state.player_by_id(prev[0].controller_id)
                if prev and getattr(prev[0], "controller_id", None)
                else None
            )
            if player is None:
                return
        elif self.player_from_target:
            chosen = _chosen_targets(targets, 1, None)
            target = chosen[0] if chosen else None
            if target is None or hasattr(target, "instance_id"):
                # Not actually resolved to a player (missing/withered
                # target) — fail closed, same as every other targeted
                # effect with no legal target left.
                return
            player = target
        else:
            player = self.player or context.active_player
        chooser = _controller_of(self.source, context) if self.player_from_target else None
        context.request_search(
            player, self._resolved_criteria(context), self.destination, self.count, self.optional,
            zones=self.zones, destinations=self.destinations, exile_rest=self.exile_rest,
            extra_counters=self.extra_counters, destination_if=self.destination_if,
            attach_to_creature_you_control=self.attach_to_creature_you_control,
            remember_source_id=self.source.instance_id if self.remember and self.source is not None else None,
            total_mana_value_budget=self.total_mana_value_budget,
            chooser=chooser,
            share_land_type=self.share_land_type,
        )


# ---------------------------------------------------------------------------
# Registry (docs/07 PART 4 Option C / PART 6)
# ---------------------------------------------------------------------------


class ImpulsiveLookEffect(GameEffect):
    """"Look at the top N cards, take one matching a filter, rest to Y"
    (Grisly Salvage/Commune with the Gods-shaped) — distinct from
    `SearchLibraryEffect` (searches the *whole* library, always shuffles
    afterwards) and `top_library.py`'s standing "look at/play from the top"
    permission (never moves a card). Peels exactly ``count`` cards, offers a
    choice among only the ones matching ``criteria``, routes the pick to
    ``hit_destination`` and the rest to ``miss_destination`` (see
    `GameContext.impulsive_look`/`RulesEngine.request_impulsive_look`).
    """

    def __init__(
        self,
        count: int = 1,
        criteria: Any = "",
        hit_destination: str = "hand",
        miss_destination: str = "graveyard",
        optional: bool = True,
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.criteria = criteria
        self.hit_destination = hit_destination
        self.miss_destination = miss_destination
        self.optional = optional
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.impulsive_look(
            player, self.count, self.criteria,
            self.hit_destination, self.miss_destination, self.optional,
        )


class ImpulsiveDrawEffect(GameEffect):
    """Exile the top ``count`` cards of the library; their controller may
    play any of them through the end of their next turn (RULE 601.3b
    analogue, Light Up the Stage-shaped "impulsive draw") — every card
    exiled becomes playable, unlike `ImpulsiveLookEffect`'s filtered
    choice-and-route shape (see `GameContext.exile_with_play_permission`/
    `RulesEngine.exile_with_play_permission`).

    ``player`` (whose library is exiled from) and ``permission_player``
    (who may play the exiled card) default to the same player — Light Up
    the Stage's own shape — but can differ (Ragavan, Nimble Pilferer-shaped:
    exile from *the player Ragavan just damaged*, permission to Ragavan's
    own controller). ``same_turn_only`` shortens the window from "until
    the end of your next turn" to "until end of turn" (Ragavan's own,
    shorter clause) — see `RulesEngine.exile_with_play_permission`.
    """

    def __init__(
        self,
        count: int = 1,
        player: Any = None,
        permission_player: Any = None,
        same_turn_only: bool = False,
        source: Optional["GameObject"] = None,
        count_from_trigger_event: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.player = player
        self.permission_player = permission_player
        self.same_turn_only = same_turn_only
        #: "…you may exile that many cards from the top of your library."
        #: (Virtue of Courage — "that many" is the firing event's own
        #: damage amount) — same "read this firing's own payload" idiom
        #: `CreateTokenEffect.count_from_trigger_event` uses. Overrides
        #: ``count`` when set.
        self.count_from_trigger_event = count_from_trigger_event

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        permission_player = self.permission_player or player
        source_name = self.source.name if self.source is not None else None
        count = self.count
        if self.count_from_trigger_event:
            event = context.trigger_event
            count = int((event or {}).get(self.count_from_trigger_event) or 0)
        if count <= 0:
            return
        context.exile_with_play_permission(
            player, count, source_name=source_name,
            permission_player=permission_player, same_turn_only=self.same_turn_only,
        )


class DrawRevealCastOneFreeEffect(GameEffect):
    """"Draw N cards and reveal them. You may cast one of them without
    paying its mana cost." (RULE 121/601.3b combo — Dungeon of the Mad
    Mage's own "Mad Wizard's Lair" room, PAR-13).

    Reveal is purely informational (RULE 701.28 — no hidden-zone state to
    model, since `services/game_session.py`'s own redaction already keeps
    a hand private otherwise), so this only draws, then offers
    `RulesEngine.request_choose_objects`'s ``"cast_free"`` action over
    *exactly* the cards this draw put into hand (never the rest of the
    hand) — snapshotting the hand before/after rather than assuming a
    fixed append count, since a draw can be redirected (RULE 121.5's
    replacement family) or silently capped (a draw-limit static).
    """

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.count <= 0:
            return
        before = list(player.hand)
        context.draw(player, self.count)
        drawn = [c for c in player.hand if c not in before]
        if drawn:
            context.choose_objects(
                player, drawn, "cast_free", count=1, optional=True, source=self.source,
            )


class RevealTopThenFreeCastIfMVMatchEffect(GameEffect):
    """"Whenever an opponent casts a spell, you may reveal the top card of
    your library. If you do, you may cast that card without paying its
    mana cost if the two spells have the same mana value." (Powerbalance)

    Reveal is purely informational (see `DrawRevealCastOneFreeEffect`'s
    own docstring for why this engine has no separate reveal state);
    "you may reveal" is a **documented simplification** to unconditional
    (the same idiom `CoinFlipEffect`'s own "you may" branch uses — a
    real but vanishingly rare decline), so this always looks. The mana-
    value match is checked against `GameContext.trigger_event`'s own
    ``mana_value`` (`SPELL_CAST`'s stamped field, RULE 601.2b), and only
    when it holds does this offer `request_choose_objects`'s existing
    ``"cast_free"`` action over the top card — a genuine interactive "you
    may cast", unlike the reveal half.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        event = context.trigger_event or {}
        cast_mv = event.get("mana_value")
        if cast_mv is None or top.card.converted_mana_cost != cast_mv:
            return
        context.choose_objects(player, [top], "cast_free", count=1, optional=True, source=self.source)


class RevealTopThenCounterIfMVMatchEffect(GameEffect):
    """"Whenever an opponent casts a spell, you may reveal the top card of
    your library. If you do, counter that spell if it has the same mana
    value as the revealed card." (Counterbalance, MEC-41)

    The counter-target sibling of `RevealTopThenFreeCastIfMVMatchEffect`
    (Powerbalance) just above — same reveal-is-informational/"you may"
    simplification and the same `GameContext.trigger_event`-sourced mana
    value, but resolving into `CounterSpellEffect`'s own
    ``target_from_trigger_event="instance_id"`` idiom (the firing
    SPELL_CAST event's own spell) through `context.counter` rather than a
    free cast, so RULE 118 "can't be countered" is still honoured
    (`RulesEngine.counter_unless_pays`).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        event = context.trigger_event or {}
        cast_mv = event.get("mana_value")
        instance_id = event.get("instance_id")
        if cast_mv is None or instance_id is None or top.card.converted_mana_cost != cast_mv:
            return
        target = context.state.find_object(instance_id)
        if target is not None:
            context.counter(target, source=self.source)


class ReturnRemainingExiledEffect(GameEffect):
    """RULE 603.7 delayed cleanup: whichever of ``instance_ids`` are still
    sitting in exile move to their owner's graveyard — Mnemonic Betrayal's
    own "at the beginning of the next end step, if any of those cards
    remain exiled, return them to their owners' graveyards." Anything
    already cast by then is simply gone from the zone check (it resolved,
    or is on the stack/battlefield/graveyard through its own path), so this
    only ever touches leftovers. Plain data (``instance_ids`` are ints), so
    it survives `GameState.clone` like any other armed `DelayedTrigger`.
    """

    def __init__(self, instance_ids: list[int], source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.instance_ids = list(instance_ids)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for iid in self.instance_ids:
            obj = context.state.find_object(iid)
            if obj is None or obj.zone != Zone.EXILE:
                continue
            owner = context.state.player_by_id(obj.owner_id)
            owner.remove_from_zone(obj, Zone.EXILE)
            owner.add_to_zone(obj, Zone.GRAVEYARD)
            context.state.temp_play_permissions.pop(iid, None)
            context.state.temp_play_permission_player.pop(iid, None)
            context.state.temp_play_permission_source.pop(iid, None)
            context.state.mana_wildcard_permission.pop(iid, None)


class GraveyardImpulsiveCastEffect(GameEffect):
    """"Exile all opponents' graveyards. You may cast spells from among
    those cards this turn, and mana of any type can be spent to cast them.
    At the beginning of the next end step, if any of those cards remain
    exiled, return them to their owners' graveyards." (Mnemonic Betrayal) —
    the graveyard-sourced sibling of `ImpulsiveDrawEffect`'s library-top
    exile: the same dual-player permission shape (exile-owner vs.
    permission-holder can differ, `RulesEngine._grant_temp_play_permission`)
    plus RULE 605.1a's broadest "any type" mana-wildcard grant (``ManaPool``'s
    ``wildcard="type"``, see `RulesEngine.cast_spell`) and a RULE 603.7
    delayed cleanup (`ReturnRemainingExiledEffect`) for whatever's left
    unexiled at the next end step.
    """

    def __init__(
        self,
        mana_wildcard: Optional[str] = "type",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.mana_wildcard = mana_wildcard

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..models.game_state import DelayedTrigger  # avoid effects↔game_state cycle

        controller_id = getattr(self.source, "controller_id", None) or context.active_player.id
        controller = context.state.player_by_id(controller_id)
        source_name = self.source.name if self.source is not None else None
        exiled_ids: list[int] = []
        for player in context.state.living_players():
            if player.id == controller_id or not player.graveyard:
                continue
            exiled = context.engine.exile_graveyard_with_cast_permission(
                player, controller, source_name=source_name, mana_wildcard=self.mana_wildcard,
            )
            exiled_ids.extend(obj.instance_id for obj in exiled)
        if not exiled_ids:
            return
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=controller_id,
                step="end",
                scope="any",
                effects=[ReturnRemainingExiledEffect(exiled_ids, source=self.source)],
                description=f"{source_name}: restliche Karten zurückgeben" if source_name else "",
            )
        )


class ShuffleLibraryEffect(GameEffect):
    """Shuffle the controller's (or a target player's) library (RULE 701.20)."""

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or (targets[0] if targets else None) or context.active_player
        context.shuffle_library(player)


class WheelEffect(GameEffect):
    """"Each player shuffles their hand and graveyard into their library,
    then draws seven cards." (Timetwister/Time Reversal/Echo of Eons — the
    identical printed line across all three, so this is a shared, not
    Timetwister-specific, effect.) An RULE 601.2c untargeted "each player"
    effect, unlike `DrawCardEffect`'s single-player default — resolved in
    an arbitrary player order (APNAP order has no observable effect here:
    every player's own shuffle only touches their own zones).
    """

    def __init__(self, draw_count: int = 7, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.draw_count = draw_count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for player in list(context.state.living_players()):
            context.shuffle_hand_and_graveyard_into_library(player)
            context.draw(player, self.draw_count)


class WheelOfFortuneEffect(GameEffect):
    """"Each player discards their hand, then draws seven cards." (Wheel of
    Fortune) — the flat-draw-count sibling of `WindfallEffect`'s
    shared-maximum shape: every player discards their whole hand (RULE
    101.4's simultaneous-turn-based-action idiom, same sequential-loop
    approximation `WheelEffect`/`WindfallEffect` already use), then every
    player draws the same fixed number regardless of how many they held.
    """

    def __init__(self, draw_count: int = 7, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.draw_count = draw_count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for player in list(context.state.living_players()):
            context.discard(player, len(player.hand))
            context.draw(player, self.draw_count)


class WindfallEffect(GameEffect):
    """"Each player discards their hand, then draws cards equal to the
    greatest number of cards a player discarded this way." (Windfall) —
    every player discards first (RULE 101.4's simultaneous-turn-based-action
    idiom this engine approximates with a plain sequential loop, same as
    `WheelEffect`), *then* every player draws the shared maximum, so a
    player who discards zero still draws if anyone else discarded more.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        players = list(context.state.living_players())
        discarded: dict[str, int] = {}
        for player in players:
            discarded[player.id] = len(player.hand)
            context.discard(player, discarded[player.id])
        greatest = max(discarded.values(), default=0)
        if greatest:
            for player in players:
                context.draw(player, greatest)


class CascadeEffect(GameEffect):
    """Cascade (RULE 702.85): free-cast the first cheaper nonland from the top.

    Exiles from the top of the library until a nonland card with mana value
    *less than* the cascade spell's, which the controller may cast without
    paying; the rest go to the bottom in a random order. This is a cast (it
    uses the stack), not a "put onto the battlefield" — the distinction the
    event model draws.

    ``mana_value`` is the threshold; left ``None`` it is read from the
    cascade spell (``source``) at resolution, since cascade's own spell is
    what sets the ceiling.
    """

    def __init__(
        self,
        mana_value: Optional[int] = None,
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.mana_value = mana_value
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        mana_value = self.mana_value
        if mana_value is None and self.source is not None:
            mana_value = self.source.card.converted_mana_cost
        context.cascade(player, mana_value or 0)


class DiscoverEffect(GameEffect):
    """Discover N (RULE 702.164): like cascade, but the hit is a nonland with
    mana value ``N`` *or less*, and the controller casts it for free **or**
    puts it into their hand (never leaves it behind)."""

    def __init__(
        self,
        mana_value: int = 0,
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.mana_value = mana_value
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.discover(player, self.mana_value)


# ---------------------------------------------------------------------------
# cEDH staples cube — player-scoped restrictions & history-driven effects
# ---------------------------------------------------------------------------


class PlayerCastRestrictionEffect(GameEffect):
    """"Until your next turn, target player can't cast noncreature spells."
    (Hope of Ghirapur) — a **player-scoped**, duration-bounded cast
    prohibition (RULE 601.3a), installed on `Player.player_effects` rather
    than derived by the layer engine.

    It isn't a `StaticAbility`: nothing on the battlefield keeps it alive
    (Hope of Ghirapur has *sacrificed itself* to pay for this), so there is
    no permanent for `continuous.recompute` to read it off. The parallel is
    `PreventDamageEffect`'s turn-scoped shield, which lives on
    `player_effects` for the same reason.

    ``until_next_turn_of`` is the player id whose next turn ends it (RULE
    611.2b) — `GameEngine.begin_turn` sweeps every `player_effects` list for
    entries keyed to the incoming active player. ``noncreature`` restricts
    only noncreature spells (leave ``False`` for a blanket "can't cast
    spells"). Consulted by `GameEngine.can_cast` via `_player_cast_
    restricted`.
    """

    #: Marker `GameEngine.can_cast` scans for, so it never has to import
    #: this class (the same duck-typed flag `damage_prevention_shield` uses).
    player_cast_restriction = True

    def __init__(
        self,
        noncreature: bool = True,
        until_next_turn_of: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.noncreature = noncreature
        self.until_next_turn_of = until_next_turn_of
        self.target_spec = TargetSpec(
            kind="player_dealt_combat_damage_by_source",
            description="Spieler, dem diese Kreatur in diesem Zug Kampfschaden zugefügt hat",
        )

    def restricts(self, card: Any) -> bool:
        """Whether this restriction blocks casting ``card`` (RULE 601.3a)."""
        if not self.noncreature:
            return True
        return not getattr(card, "is_creature", False)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None or not hasattr(target, "player_effects"):
            return
        controller = _controller_of(self.source, context)
        installed = PlayerCastRestrictionEffect(
            noncreature=self.noncreature,
            until_next_turn_of=controller.id if controller is not None else None,
            source=self.source,
        )
        # The installed copy is a plain marker read by `can_cast`; it must
        # not carry a `target_spec` that would make it look like a fresh
        # targeting effect if anything ever re-scanned `player_effects`.
        installed.target_spec = None
        target.player_effects.append(installed)


class LookTopKeepOneOnTopEffect(GameEffect):
    """"Look at the top X cards of your library … put up to one of them on
    top of your library and the rest on the bottom in a random order."
    (Thassa's Oracle) — a library-reordering dig with no card ever changing
    zone in the ordinary sense.

    ``count_selector`` (`continuous.count_selector`, e.g. ``"devotion_to_
    blue"``) resolves X live at resolution time rather than baking a number
    in; ``count`` is the fixed fallback when no selector is given.

    ``win_if_count_at_least_library`` is Thassa's Oracle's own alternative
    win condition (RULE 104.2a): checked *before* the reordering, against
    the library size at that moment — X >= library size wins the game
    outright, which is the whole reason the card is a cEDH staple. Routed
    through `RulesEngine.player_wins`, the same choke point Jace, Wielder of
    Mysteries uses, so "you can't win the game" effects stay in one place.

    "Put **up to one** of them on top" is a real choice, offered through
    the general `GameContext.choose_objects` chooser (optional, so declining
    bottoms all X). The rest go to the bottom in a random order, per the
    card — and they are bottomed *before* the choice rather than after, so
    the randomization can't depend on which card was kept; removing one card
    from an already-random sequence leaves the others just as random.
    """

    def __init__(
        self,
        count: int = 0,
        count_selector: Optional[str] = None,
        win_if_count_at_least_library: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.count_selector = count_selector
        self.win_if_count_at_least_library = win_if_count_at_least_library

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        amount = self.count
        if self.count_selector:
            from . import continuous  # function-scoped: avoid an import cycle

            amount = continuous.count_selector(context.state, player.id, self.count_selector)
        library = player.zones[Zone.LIBRARY]
        # RULE 104.2a, checked before anything moves — an empty library
        # satisfies "X >= 0 cards" and wins even with X of 0.
        if self.win_if_count_at_least_library and amount >= len(library):
            context.engine.player_wins(player)
            return
        if amount <= 0:
            return
        # The library's *end* is its top (see `Player.zones`): peel the top
        # ``amount`` and bottom them all in a random order, then let the
        # player lift up to one back onto the top.
        looked = [library.pop() for _ in range(min(amount, len(library)))]
        if not looked:
            return
        random.shuffle(looked)
        for card in looked:
            library.insert(0, card)  # bottom of library
        context.choose_objects(
            player, looked, "library_top", count=1, optional=True,
            prompt="Lege bis zu eine der angesehenen Karten oben auf deine Bibliothek",
            source=self.source,
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — mana-trigger bodies (RULE 605.1b/605.4)
# ---------------------------------------------------------------------------


class MirrorProducedManaEffect(GameEffect):
    """"Add one mana of any type that permanent produced." (Kinnan, Bonder
    Prodigy) — the amount is fixed at one, but the *type* is only knowable
    from the firing itself, read off `GameContext.trigger_event`'s
    ``produced`` payload (the `TAPPED_FOR_MANA` event `GameEngine.
    tap_for_mana` stamps with what actually went into the pool).

    Distinct from `AddManaEffect`'s ``"ANY"`` sentinel, which offers every
    colour: Kinnan is restricted to what that permanent *did* produce, so a
    Basalt Monolith copies {C} and a Bloom Tender copies only the colours it
    actually made.

    When a single tap produced 2+ distinct types (an "any combination of
    colours" ability — `ManaAbility.any_combination`, or a Bloom Tender),
    *which* one to copy is a real choice, offered through the narrowed
    `RulesEngine.add_mana_any_color` menu. One type produced needs no
    prompt, which is the overwhelmingly common case.
    """

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        event = context.trigger_event
        if player is None or event is None:
            return
        produced = event.get("produced") or {}
        colours = [c for c, n in produced.items() if n]
        if not colours:
            return
        # RULE 605.1a: "any type **that permanent produced**" — a real
        # choice whenever one tap made 2+ types (a Bloom Tender, a dual
        # land's "any combination"), narrowed to exactly those. Safe to open
        # a `pending_choice` here even though a triggered mana ability
        # resolves off-stack (RULE 605.4): the firing action, `GameEngine.
        # tap_for_mana`, is a discrete player action, not a mid-payment step.
        for _ in range(max(self.count, 1)):
            context.engine.add_mana_any_color(player, colours)


class TapMatchingLandsEffect(GameEffect):
    """"Tap all lands that player controls that could produce any type of
    mana that land could produce." (Mana Web) — a mana-denial sweep keyed to
    the *specific* land that was just tapped.

    Both halves come from `GameContext.trigger_event` (`TAPPED_FOR_MANA`):
    which player to sweep (``controller_id``) and which land set the
    reference types (``instance_id``). The reference land's *potential*
    production is re-derived from `game/mana_abilities.py`, not from the
    event's ``produced`` payload — RULE 605.1a is explicit that this is
    about what a land *could* produce, so a dual land tapped for {U} still
    locks down every land that makes {U} **or** its other colour.

    Not itself a mana ability (it produces none), so it uses the stack like
    any ordinary triggered ability.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    @staticmethod
    def _producible(obj: Any, state: Any) -> set[str]:
        """Every mana type ``obj`` could produce right now (RULE 605.1a)."""
        from .mana_abilities import mana_abilities_for  # function-scoped: import cycle

        types: set[str] = set()
        for ability in mana_abilities_for(obj, state=state):
            for option in ability.options:
                types.update(c for c, n in option.items() if n)
        return types

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None:
            return
        reference = context.state.find_object(event.get("instance_id"))
        player_id = event.get("controller_id")
        if reference is None or player_id is None:
            return
        wanted = self._producible(reference, context.state)
        if not wanted:
            return
        for obj in context.state.permanents():
            if obj.controller_id != player_id or not obj.is_land or obj.tapped:
                continue
            if self._producible(obj, context.state) & wanted:
                context.set_tapped(obj, True)


# ---------------------------------------------------------------------------
# cEDH staples cube — control exchange, mass phasing, copy+bounce
# ---------------------------------------------------------------------------


class ExchangeControlEffect(GameEffect):
    """"Exchange control of this creature and up to one target creature an
    opponent controls. If you don't or can't make an exchange, sacrifice
    this creature." (Gilded Drake) — RULE 108.4/701.10.

    A genuine *swap*, which neither shipped control shape could express: the
    layer-2 ``control_change`` static reassigns one permanent's controller
    for as long as its source stays around, and
    `GainControlUntilEndOfTurnEffect` is a one-way, duration-bounded grab.
    Exchange is permanent, two-way, and — crucially for Gilded Drake — has a
    failure mode with its own consequence.

    Implemented as a straight `GameObject.controller_id` swap rather than a
    pair of continuous effects, because RULE 701.10c makes an exchange a
    one-shot change of control that doesn't depend on any source remaining
    on the battlefield: Gilded Drake dying afterwards must *not* give the
    creature back, which is precisely why the card is played.

    ``sacrifice_self_if_no_exchange`` is Gilded Drake's own failure clause
    (RULE 701.10d: an exchange with only one exchangeable permanent doesn't
    happen at all). Note the drake's ability "still resolves if its target
    becomes illegal" — with `target_spec.optional` set, no legal target is
    itself a legal choice, so the ability resolves, the exchange doesn't
    happen, and the sacrifice does.
    """

    def __init__(
        self,
        target_kind: str = "creature",
        sacrifice_self_if_no_exchange: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind, optional=True)
        self.sacrifice_self_if_no_exchange = sacrifice_self_if_no_exchange

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        mine = self.source
        theirs = targets[0] if targets else None
        battlefield = context.state.permanents()
        exchangeable = (
            mine is not None
            and theirs is not None
            and mine in battlefield
            and theirs in battlefield
            and mine.controller_id != theirs.controller_id
        )
        if exchangeable:
            mine.controller_id, theirs.controller_id = theirs.controller_id, mine.controller_id
            # RULE 302.6: each permanent is newly under its controller's
            # command, so both are summoning sick until that player's next
            # turn — the same treatment `RulesEngine` gives any other
            # battlefield arrival.
            mine.summoning_sick = True
            theirs.summoning_sick = True
            context.recompute()
            return
        if self.sacrifice_self_if_no_exchange and mine is not None and mine in battlefield:
            # RULE 701.10d + 701.16c: no exchange happened, so the drake
            # sacrifices itself — sacrifice, never destruction.
            context.put_into_graveyard(mine)


class PhaseOutAllYouControlEffect(GameEffect):
    """"Until your next turn, your life total can't change and you gain
    protection from everything. All permanents you control phase out."
    (Teferi's Protection) — RULE 702.26/611.2b.

    Three separate things the card does at once, kept as one effect because
    all three share the same "until your next turn" duration and the same
    player, and because none is meaningful without the others:

    * every permanent the controller controls phases out (RULE 702.26b) —
      the mass form of the shipped, single-permanent `PhaseOutEffect`. The
      RULE 702.26a sweep in `GameEngine._step_untap` already phases them all
      back in at that player's next untap step, so the duration needs no
      separate bookkeeping.
    * their life total can't change (`PlayerLifeLockEffect`-style marker on
      `Player.player_effects`, consulted by `RulesEngine.gain_life`/
      `lose_life`).
    * they gain protection from everything, which for a *player* reduces to
      "can't be dealt damage / targeted" — modeled with the same
      `player_effects` marker so both halves lapse together in
      `GameEngine.begin_turn`.

    Unlike `PhaseOutEffect`, attached Auras/Equipment are *not* unattached:
    here their host and they themselves both phase out together, so the
    attachment stays valid throughout (RULE 702.26e) — which is the whole
    point of Teferi's Protection as a board-preserving answer.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in list(context.state.battlefield):
            if obj.controller_id == player.id:
                obj.phased_out = True
        shield = PlayerShieldEffect(
            life_locked=True,
            protection_from_everything=True,
            until_next_turn_of=player.id,
            source=self.source,
        )
        player.player_effects.append(shield)
        context.recompute()


class PlayerShieldEffect(GameEffect):
    """Teferi's Protection's player-scoped half: "your life total can't
    change and you gain protection from everything", until your next turn
    (RULE 611.2b).

    A marker on `Player.player_effects` — the same home the RULE 615 damage
    shield and `PlayerCastRestrictionEffect` use, and for the same reason:
    the spell that granted it is already in the graveyard, so there is no
    permanent for `continuous.recompute` to derive it from. Read by
    `RulesEngine.gain_life`/`lose_life` (life lock, RULE 119.6) and
    `RulesEngine.deal_damage` (protection from everything, RULE 702.16e);
    swept by `GameEngine.begin_turn` via ``until_next_turn_of``.
    """

    #: Duck-typed markers the engine scans for, so neither `RulesEngine` nor
    #: `GameEngine` needs to import this class (the same convention
    #: `damage_prevention_shield`/`player_cast_restriction` follow).
    player_life_locked = True

    def __init__(
        self,
        life_locked: bool = True,
        protection_from_everything: bool = True,
        until_next_turn_of: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.life_locked = life_locked
        self.player_life_locked = life_locked
        self.player_protected_from_everything = protection_from_everything
        self.until_next_turn_of = until_next_turn_of

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # a marker consulted by the engine, never applied itself


class CopySpellAndBounceEffect(GameEffect):
    """"Copy target instant or sorcery spell, then return it to its owner's
    hand." (Narset's Reversal) — RULE 707.10 + RULE 400.

    A single atomic effect rather than a `CopySpellEffect` plus a bounce,
    for the reason `GainControlUntilEndOfTurnEffect`'s docstring already
    gives about paired clauses: both halves act on the *same* chosen spell,
    and no shipped bounce effect can reach a `StackItem` (they all move a
    battlefield permanent). Order matters and is the card's whole trick —
    the copy is made **first**, so it still resolves after the original has
    been picked up, and the copy's targets are already locked in.
    """

    def __init__(
        self,
        card_types: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        spell_filter: dict[str, Any] = {}
        if card_types:
            spell_filter["card_types"] = list(card_types)
        self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        controller_id = getattr(self.source, "controller_id", None)
        if target is None or controller_id is None:
            return
        context.copy_spell(target, controller_id, 1)
        context.engine.return_spell_to_hand(target)


class ReturnSharedTypePermanentEffect(GameEffect):
    """"You may return another permanent you control that shares a permanent
    type with it to its owner's hand." (Cloudstone Curio) — the bounce half
    of a RULE 603.1 "whenever a permanent enters" trigger.

    "Shares a permanent type **with it**" is why this can't be an ordinary
    `ReturnToHandEffect` with a target kind: the legal set depends on the
    *entering* permanent, which is only known per firing. It is read off
    `GameContext.trigger_event`'s ``instance_id``/``object_types``, and the
    candidate list is narrowed to permanents sharing at least one of those
    main types (RULE 205.2a) excluding the trigger's own subject.

    *Which* matching permanent to return is the controller's own choice,
    offered through the general `GameContext.choose_objects` chooser — and
    optional there as well as on the trigger itself, so declining at either
    prompt leaves the board alone.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None:
            return
        entering = context.state.find_object(event.get("instance_id"))
        if entering is None:
            return
        wanted = {t for t in entering.type_words if t in _PERMANENT_TYPE_WORDS}
        candidates = [
            obj
            for obj in context.state.permanents()
            if obj is not entering
            and obj.controller_id == entering.controller_id
            and wanted & set(obj.type_words)
        ]
        controller = context.state.player_by_id(entering.controller_id)
        if candidates and controller is not None:
            context.choose_objects(
                controller, candidates, "return_to_hand", count=1, optional=True,
                prompt="Cloudstone Curio: Wähle ein bleibendes Objekt zum Zurücknehmen",
                source=self.source,
            )


class ExileTriggerDamagedCreatureEffect(GameEffect):
    """"Whenever this creature deals combat damage to a creature, exile
    that creature." (Kaldra Compleat-shaped — a Living Weapon's granted
    ability, RULE 613.7f) — RULE 603.3d's "that creature" pronoun refers to
    the `DAMAGE` event's *recipient*, not its source: `_GRANTED_EVENT_KEYS`
    scopes *which grantee* reacts off the event's ``source_id`` (the
    equipped creature that dealt the damage — "this creature"), a different
    field from who was hit. No target choice at all — `GameContext.
    trigger_event`'s own ``target_id`` (ENG-13's general per-firing dynamic
    reference) names the exact object, the granted-ability counterpart of
    what `TriggeredAbility.reflexive` does for an ordinary "that
    permanent/spell" off ``instance_id``. A damaged *player* (``is_player``)
    or a since-departed creature is simply nothing to exile.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None or event.get("is_player"):
            return
        creature = context.state.find_object(event.get("target_id"))
        if creature is None:
            return
        context.exile(creature)


class LoseGameTriggerDamagedPlayerEffect(GameEffect):
    """"…that player loses the game…" (Frodo, Sauron's Bane) — RULE 603.3d's
    "that player" pronoun refers to the `DAMAGE` event's *recipient*, the
    exact mirror of `ExileTriggerDamagedCreatureEffect` for a player instead
    of a creature: no target choice, `GameContext.trigger_event`'s own
    ``target_id`` is the damaged player's id (`is_player`). A damaged
    creature or a since-departed player is simply nothing to make lose.
    """

    def __init__(self, reason: str = "effect", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.reason = reason

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None or not event.get("is_player"):
            return
        context.lose_game(context.state.player_by_id(event.get("target_id")), self.reason)


#: RULE 205.2a's permanent card types — the vocabulary "shares a permanent
#: type with it" (Cloudstone Curio) compares against, so a shared *spell*
#: type (instant/sorcery, which no permanent has anyway) can never match.
_PERMANENT_TYPE_WORDS: frozenset[str] = frozenset(
    {"artifact", "creature", "enchantment", "land", "planeswalker", "battle"}
)


class PutFromHandOntoBattlefieldEffect(GameEffect):
    """"Put up to two creature cards from your hand onto the battlefield."
    (Tooth and Nail's second mode) — RULE 701.19-adjacent, but from **hand**.

    Every other "put onto the battlefield" shape in the engine moves a card
    out of a library (a search) or a graveyard (reanimation); none opens an
    arbitrary pick from hand. Reuses `RulesEngine.request_search`'s
    interactive one-at-a-time choice machinery by searching the ``"hand"``
    zone, so the UI, the undo snapshots and the "up to N" semantics are
    identical to every other pick — rather than a parallel choice kind that
    would need its own wiring in the session and the frontend.

    ``tapped=True`` (Horizon of Progress's "…onto the battlefield
    **tapped**") just switches the search destination to the existing
    ``"battlefield_tapped"`` string `_put_searched_card` already handles —
    no new engine behaviour, only Tooth and Nail's own untapped default
    ever exercised the other branch before.
    """

    def __init__(
        self,
        criteria: Any = "",
        count: int = 1,
        tapped: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.criteria = criteria
        self.count = count
        self.tapped = tapped

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        destination = "battlefield_tapped" if self.tapped else "battlefield"
        context.request_search(
            player, self.criteria, destination, self.count, optional=True, zones=["hand"],
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — naming a card, and the three loop shapes
# ---------------------------------------------------------------------------


class NameCardThenEffect(GameEffect):
    """"Choose a card name. `<effect>`" (Demonic Consultation) — RULE 701's
    naming action, which no `pending_choice` could express before: every
    other choice in the engine picks from an enumerable set, and a player
    may name *any* card in Magic, including one nowhere in this game.

    `RulesEngine.request_name_card` therefore offers the names the player
    can actually see (their own hand/library/graveyard) as suggestions while
    accepting an arbitrary string, and substitutes it into the follow-up
    effects' ``"named_card"`` criteria sentinel — the naming counterpart of
    `_substitute_x`'s ``"x"``. The string is only ever *compared against*
    card names, never interpreted, so nothing derived from it becomes
    behaviour (docs/09's security boundary).
    """

    def __init__(
        self,
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.inner_specs = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.request_name_card(player, self.inner_specs, self.source)


class ExileUntilDuplicateNameEffect(GameEffect):
    """"Exile the top card of your library. You may put that card into
    your hand unless it has the same name as another card exiled this
    way. Repeat this process until you put a card into your hand or you
    exile two cards with the same name, whichever comes first." (RULE
    701.19-adjacent — Tainted Pact) — see `RulesEngine.
    exile_until_duplicate_name`'s docstring for why this is a genuinely
    different loop shape from `DigUntilEffect`, not a special case of it.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.exile_until_duplicate_name(player)


class TransmuteArtifactEffect(GameEffect):
    """"Sacrifice an artifact. If you do, search your library for an
    artifact card. If that card's mana value is less than or equal to the
    sacrificed artifact's mana value, put it onto the battlefield. If
    it's greater, you may pay {X}, where X is the difference. If you do,
    put it onto the battlefield. If you don't, put it into its owner's
    graveyard. Then shuffle." (Transmute Artifact) — see `RulesEngine.
    transmute_artifact`'s own docstring for why this is one self-contained
    bespoke sequence rather than composed from the general search/
    sacrifice/`pay_cost_then` primitives.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.transmute_artifact(player)


class DigUntilEffect(GameEffect):
    """"Reveal/exile cards from the top of your library until `<predicate>`"
    (Demonic Consultation, Tibalt's Trickery, Possibility Storm) — the
    generalized form of the cascade/discover dig, which was hard-wired to
    "nonland cheaper than N, may cast it, rest to the bottom".

    Both the predicate (``criteria``, a `models.card_query` dict — including
    the new ``not_name`` for "a different name than that spell") and both
    destinations are parameters here. ``pre_exile`` is Demonic
    Consultation's "exile the top six cards" prologue, which happens before
    the dig and is never part of it.

    ``criteria`` may carry the ``"named_card"`` sentinel — the name just
    chosen (see `NameCardThenEffect`), substituted at answer time rather
    than baked in. The *spell*-derived predicates ("a different name than
    that spell", "shares a card type with it") live on
    `ScrambleSpellEffect` instead, which has the answered spell in hand.
    """

    def __init__(
        self,
        criteria: Any = "",
        hit_destination: str = "hand",
        rest_destination: str = "exile",
        pre_exile: int = 0,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.criteria = criteria
        self.hit_destination = hit_destination
        self.rest_destination = rest_destination
        self.pre_exile = int(pre_exile)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.dig_until(
            player,
            self.criteria,
            hit_destination=self.hit_destination,
            rest_destination=self.rest_destination,
            pre_exile=self.pre_exile,
        )


class MillUntilCreatureEffect(GameEffect):
    """"Target opponent mills a card, then repeats this process until a
    creature card or X cards have been put into their graveyard this way,
    whichever comes first. If one or more creature cards were put into that
    graveyard this way, sacrifice this artifact and put one of them onto the
    battlefield under your control." (Helm of Obedience)

    The engine's first **repeat-until-a-predicate-holds** loop: every other
    repetition primitive here has a count fixed before it starts (mill N,
    draw N, proliferate). Here the count is a *cap* and the real stopping
    condition is what the mill turned up, so the loop has to check after
    each iteration.

    Bounded on both sides by construction — ``X`` caps the iterations and an
    empty library ends it early — so this cannot spin, which is the property
    that makes a "repeat until" primitive safe to have at all.

    Note the reanimated creature comes back under **your** control, not its
    owner's (RULE 110.2), and the Helm sacrifices itself only when the mill
    actually hit a creature (RULE 701.16c: sacrifice, not destruction).
    """

    def __init__(
        self,
        amount: Any = 0,
        target_kind: str = "player",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        victim = targets[0] if targets else None
        cap = self.amount if isinstance(self.amount, int) else 0
        if victim is None or not hasattr(victim, "graveyard") or cap <= 0:
            return  # "X can't be 0."
        found: list[Any] = []
        for _ in range(cap):
            if not victim.library:
                break
            context.mill(victim, 1)
            milled = victim.graveyard[-1] if victim.graveyard else None
            if milled is not None and milled.is_creature:
                found.append(milled)
                break
        if not found:
            return
        controller = _controller_of(self.source, context)
        if self.source is not None and self.source in context.state.permanents():
            context.put_into_graveyard(self.source)
        context.return_from_graveyard(
            found[0], "battlefield",
            controller_id=controller.id if controller is not None else None,
        )


class LookTopPayLifeLoopEffect(GameEffect):
    """"Look at the top five cards of your library. As many times as you
    choose, you may pay 1 life, put those cards on the bottom of your
    library in any order, then look at the top five cards. Then shuffle and
    put the last cards you looked at on top in any order." (Lim-Dûl's Vault)

    The engine's first **open-ended** loop: every other repetition here has
    a fixed count or a hard cap (`MillUntilCreatureEffect`'s X, a search's
    "up to N"). Here the player decides after each iteration whether to go
    again, so it's driven by a `pending_choice` that re-opens itself —
    the same self-re-opening shape a multi-card search already uses, but
    with no counter running down.

    It is still bounded in practice by the payment: each iteration costs 1
    life, so it can run at most `Player.life` - 1 times, and the choice is
    simply not offered once the player can't pay. That is the card's own
    natural bound, not a safety cap bolted on.

    **Documented simplification**: "in any order" is not an interactive
    reorder — the five cards keep their relative order when bottomed, and
    the final five are left on top as they lie. The card is played to *find*
    a specific card, and the top card is what the next draw takes either
    way; a full five-card ordering UI is a separate feature.
    """

    def __init__(
        self,
        count: int = 5,
        life_cost: int = 1,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = int(count)
        self.life_cost = int(life_cost)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.request_look_top_pay_life_loop(player, self.count, self.life_cost)


class RevealTopHandLoseLifeLoopEffect(GameEffect):
    """"Reveal the top card of your library and put that card into your
    hand. You lose life equal to its mana value. You may repeat this
    process any number of times." (Ad Nauseam, MEC-41) — see `RulesEngine.
    request_reveal_top_hand_lose_life_loop`'s own docstring for why this is
    a distinct open-ended loop from `LookTopPayLifeLoopEffect` just above,
    not a parameterization of it.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.request_reveal_top_hand_lose_life_loop(player)


class ScrambleSpellEffect(GameEffect):
    """The "answer a spell, then dig its controller's library for a
    replacement they may cast free" family — Possibility Storm and Tibalt's
    Trickery, which differ only in *how* the original spell is answered and
    what predicate the dig uses.

    One atomic effect rather than a composition, for the reason the paired-
    clause effects in this file already document: every clause acts on the
    *same* spell and on **its controller** (never the effect's own
    controller), and the dig's predicate is derived from that spell — none
    of which a separate `counter` + `mill` + `dig_until` chain could thread
    between its members.

    ``answer`` is ``"counter"`` (Tibalt's Trickery) or ``"exile"``
    (Possibility Storm, whose "that player exiles it" is a zone change, not
    a counter — which is why it also gets around "can't be countered").
    ``mill_random_max``, when set, mills the spell's controller a random
    1..N first (Tibalt's Trickery's "choose 1, 2, or 3 at random" — genuine
    randomness the card itself demands, not an engine shortcut).

    The replacement card is *offered*, never force-cast: the hit gets the
    same exile free-cast window Rebound and Beseech the Mirror use, and a
    delayed trigger performs the printed "put it on the bottom of their
    library" fallback at the next end step if they don't take it.
    ``match`` picks the dig predicate: ``"different_name"`` (a nonland card
    not named like the answered spell) or ``"shares_card_type"`` (RULE
    205.2, read off the answered spell's own main types).
    """

    def __init__(
        self,
        answer: str = "counter",
        match: str = "different_name",
        mill_random_max: int = 0,
        card_types: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.answer = answer
        self.match = match
        self.mill_random_max = int(mill_random_max)
        spell_filter: dict[str, Any] = {}
        if card_types:
            spell_filter["card_types"] = list(card_types)
        self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        item = context.engine._stack_item_for(target)
        if item is None or item.obj is None:
            return
        spell = item.obj
        try:
            caster = context.state.player_by_id(item.controller_id)
        except (KeyError, ValueError):
            return
        # Snapshot before the spell leaves the stack — both the dig
        # predicate and the mill are about *that* spell and *its* controller.
        name = spell.name
        types = [t for t in spell.type_words if t != "permanent"]

        if self.answer == "exile":
            context.engine.move_spell_off_stack(item, "exile")
        else:
            context.engine.counter_spell(item)

        if self.mill_random_max > 0:
            context.mill(caster, random.randint(1, self.mill_random_max))

        if self.match == "shares_card_type":
            criteria: dict[str, Any] = {"type": types or ["__none__"]}
        else:
            criteria = {"not_name": name}
        context.engine.dig_until(
            caster,
            criteria,
            # "That player **may** cast that card without paying its mana
            # cost" — an offer, not a forced cast (see `_place_dig_hit`).
            hit_destination="cast_free_window",
            rest_destination="library_bottom_random",
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — Fading, Soulbond, Mutate (RULE 702.32/702.94/702.140)
# ---------------------------------------------------------------------------


class RemoveCounterOrSacrificeEffect(GameEffect):
    """Fading's upkeep half (RULE 702.32b): "At the beginning of your upkeep,
    remove a fade counter from this permanent. If you can't, sacrifice it."

    Note the "if you can't" is about there being **no counter left**, not
    about any choice — a permanent at 0 fade counters is sacrificed, which
    is why Fading N lasts N+1 of your upkeeps rather than N. ``sacrifice_
    on_last_removed`` switches to Vanishing's (RULE 702.61b) own phrasing —
    "remove a time counter... When the last is removed, sacrifice it" —
    which has no such off-by-one: the removal that empties the counter
    sacrifices the permanent in that same upkeep, one upkeep sooner than
    Fading's "counters already gone" check would.

    Sacrifice, never destruction (RULE 701.16c), so nothing can regenerate
    or "if it would die, exile it instead" its way out.
    """

    def __init__(
        self, kind: str = "fade", source: Optional["GameObject"] = None,
        sacrifice_on_last_removed: bool = False,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.sacrifice_on_last_removed = sacrifice_on_last_removed

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        if obj is None or obj not in context.state.permanents():
            return
        if obj.counters.get(self.kind, 0) > 0:
            obj.add_counters(self.kind, -1)
            if self.sacrifice_on_last_removed and obj.counters.get(self.kind, 0) <= 0:
                context.put_into_graveyard(obj)
            return
        context.put_into_graveyard(obj)


class SuspendUpkeepEffect(GameEffect):
    """RULE 702.62a's 2nd+3rd Suspend abilities, combined the same way
    Vanishing's own upkeep pair already is (`RemoveCounterOrSacrificeEffect`
    above): "At the beginning of your upkeep, if this card is suspended,
    remove a time counter from it," then "When the last time counter is
    removed from this card, if it's exiled, you may play it without paying
    its mana cost if able."

    Unlike Vanishing, ``source`` here is never a permanent — a suspended
    card sits in exile the whole time (RULE 702.62b), so there's nothing to
    sacrifice at zero; instead the free-cast window opens exactly the way
    Rebound's own delayed half does (`ReboundFreeCastWindowEffect` →
    `RulesEngine.grant_free_cast_window_from_exile`), including that
    primitive's documented same-turn-only simplification for the "you may"
    choice. `granted_suspend_haste` arms RULE 702.62a's trailing "if you
    cast a creature spell this way, it gains haste" clause, consumed once
    at resolution by `RulesEngine._resolve_permanent_spell` exactly like
    `cast_via_evoke`.

    Collected fresh each owner's-upkeep by `_collect_suspend_triggers`
    (`game/rules/triggers_mixin.py`) rather than bound once at load time —
    a card can become suspended mid-game with no printed Suspend at all
    (Delay's granted suspend), so there's no permanent `TriggeredAbility`
    to have pre-attached one to.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        if obj is None or obj.zone != Zone.EXILE or obj.counters.get("time", 0) <= 0:
            return
        obj.add_counters("time", -1)
        if obj.counters.get("time", 0) > 0:
            return
        if obj.card.is_creature:
            obj.granted_suspend_haste = True
        context.engine.grant_free_cast_window_from_exile(obj)


def _scale_cumulative_upkeep_cost(cost: "ActivationCost", n: int) -> "ActivationCost":
    """RULE 702.24b: "…unless you pay its upkeep cost **for each age
    counter** on it" — the whole printed cost, paid ``n`` times over, not a
    single payment scaled by a multiplier read elsewhere. For a mana cost
    that's the same thing either way (three payments of ``{G}`` and one
    payment of ``{G}{G}{G}`` cost identically much), so this repeats the
    parsed cost's own mana symbols/``pay_life`` ``n`` times — correct for
    the overwhelming majority of printed Cumulative Upkeep costs (plain
    mana, or "pay N life").

    **Documented simplification**: a non-numeric cost component
    (``sacrifice``/``discard``/``tap_others``/``return_to_hand``/…, "tap an
    untapped white creature you control"-shaped) is left un-scaled — paid
    once regardless of the age-counter count — since "pay this cost N
    *separate* times" (tap N different creatures, sacrifice N different
    permanents) is a distinct, more general primitive genuinely unbuilt
    both here and in `RulesEngine.request_sacrifice_unless_pay`'s existing
    RULE 701.17 machinery this reuses.
    """
    from dataclasses import replace

    from ..models.mana_cost import ManaCost

    scaled_mana = ManaCost(list(cost.mana.symbols) * n, raw=cost.mana.raw)
    return replace(cost, mana=scaled_mana, pay_life=cost.pay_life * n)


class CumulativeUpkeepEffect(GameEffect):
    """RULE 702.24b: "At the beginning of your upkeep, put an age counter
    on this permanent, then sacrifice it unless you pay its upkeep cost
    for each age counter on it."

    The age counter goes on **first, unconditionally** every upkeep — the
    opposite direction from Fading's off-by-one-free "remove, then check"
    shape (`RemoveCounterOrSacrificeEffect`), since this one only ever
    adds, never runs out on its own. The scaled payment
    (`_scale_cumulative_upkeep_cost`) reuses the exact same pay-or-
    sacrifice machinery a plain "Sacrifice ~ unless you pay `<cost>`"
    already rides (RULE 701.17, `SacrificeUnlessPayEffect` →
    `RulesEngine.request_sacrifice_unless_pay`), just with the parsed cost
    multiplied by however many age counters the permanent now carries.
    """

    def __init__(self, cost: str = "", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        obj = self.source
        if obj is None or obj not in context.state.permanents():
            return
        obj.add_counters("age", 1)
        n = obj.counters.get("age", 0)
        base = parse_activation_cost(self.cost_text)
        if base.is_free or n <= 0:
            return
        player = _controller_of(obj, context)
        if player is None:
            return
        context.engine.request_sacrifice_unless_pay(
            player, _scale_cumulative_upkeep_cost(base, n), obj
        )


class TapPermanentsPerCounterEffect(GameEffect):
    """"That player taps an untapped artifact, creature, or land they control
    for each fade counter on this artifact." (Tangle Wire) — a per-player
    tax whose *magnitude* is read live off the source's own counters, so it
    shrinks each upkeep as Fading counts down.

    *Which* permanents get tapped is the taxed player's own choice (RULE
    701.21a) — and on this card it is the whole decision, since leaving the
    right permanents open is what playing against a Tangle Wire consists
    of. Offered through the general `GameContext.choose_objects` chooser,
    one at a time; with N or fewer candidates it taps them all without
    asking, because there is nothing left to decide.
    """

    def __init__(
        self,
        kind: str = "fade",
        types: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.types = [t.lower() for t in (types or ["artifact", "creature", "land"])]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        event = context.trigger_event
        if obj is None or event is None:
            return
        # "each player's upkeep" — the taxed player is whoever's turn it is,
        # since `STEP_BEGIN` carries no player of its own (see the
        # `phase_relation` predicate in `effect_binder`).
        player = context.state.active_player
        remaining = obj.counters.get(self.kind, 0)
        if remaining <= 0:
            return
        candidates = [
            candidate
            for candidate in context.state.permanents_controlled_by(player.id)
            if not candidate.tapped and (set(candidate.type_words) & set(self.types))
        ]
        context.choose_objects(
            player, candidates, "tap", count=remaining,
            prompt=f"{obj.name}: Wähle ein bleibendes Objekt zum Tappen",
            source=obj,
        )


class SoulbondPairEffect(GameEffect):
    """Soulbond's pairing half (RULE 702.94a): "You may pair this creature
    with another unpaired creature when either enters."

    Pairing is a genuine piece of game state, not a continuous effect —
    `GameObject.paired_with` holds the partner's instance id on **both**
    objects, and RULE 702.94c breaks the pair automatically the moment
    either leaves the battlefield or changes controller
    (`RulesEngine.check_state_based_actions`).

    Fires for *either* creature entering (the Soulbond creature itself, or a
    later unpaired one joining it), which is what the printed "when either
    enters" means; a creature already paired is skipped both ways.

    *Which* creature to pair with is the controller's choice (RULE
    702.94a), offered through the general `GameContext.choose_objects`
    chooser — and on Deadeye Navigator it is the entire decision, since the
    partner is whatever you intend to blink all game. Optional there too:
    the printed "you **may** pair" means declining leaves both unpaired.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        entering = (
            context.state.find_object(event.get("instance_id")) if event else None
        )
        obj = self.source
        if obj is None or entering is None:
            return
        # RULE 702.94a: whichever of the two just entered, the pair is always
        # "this creature" + some other unpaired creature.
        if obj.paired_with is not None:
            return
        candidates = [
            o
            for o in context.state.permanents_controlled_by(obj.controller_id)
            if o is not obj and o.is_creature and o.paired_with is None
        ]
        if not candidates:
            return
        controller = context.state.player_by_id(obj.controller_id)
        if controller is None:
            return
        context.choose_objects(
            controller, candidates, "soulbond_pair", count=1, optional=True,
            prompt=f"{obj.name}: Wähle eine Kreatur zum Paaren (Seelenbund)",
            source=obj,
        )
        context.recompute()


class MutateEffect(GameEffect):
    """Mutate's merge (RULE 702.140b-d): "put this creature over or under
    target non-Human creature you own. They mutate into the creature on top
    plus all abilities from under it."

    Both directions are modeled. On top (the usual choice): the mutating
    creature's characteristics (name, P/T, types) replace the host's, and
    the host's abilities merge in underneath. Under: the host keeps its
    characteristics and gains the mutating card's abilities. Which one
    applies is chosen *as the spell is cast* (RULE 702.140a), so it rides
    `GameObject.mutate_under` rather than being decided here.

    Implemented by `RulesEngine.mutate_onto`, which keeps the *host* as the
    surviving `GameObject` either way — so its counters, damage, Auras and
    summoning-sickness state all carry over untouched (RULE 702.140c: the
    merged permanent is the same permanent, never a new object, which is
    exactly why mutate dodges "enters the battlefield" triggers).

    Fires `EventType.MUTATES` afterwards so "whenever this creature mutates"
    (Lore Drakkis) has something to trigger on.
    """

    def __init__(
        self,
        target_kind: str = "non_human_creature_you_own",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        host = targets[0] if targets else None
        if host is None or self.source is None:
            return
        context.engine.mutate_onto(
            self.source, host, under=bool(getattr(self.source, "mutate_under", False))
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — two independently-chosen targets in one clause
# ---------------------------------------------------------------------------


class AttachChosenEffect(GameEffect):
    """"Attach target Equipment you control to target creature you control."
    (Brass Squire; Halvar, God of Battle's combat trigger) — RULE 301.5c.

    The first card in this engine to need **two independently-chosen targets
    of different kinds in one clause**: the thing being attached is itself a
    target, not the ability's own source (which is what the shipped
    `AttachEffect` assumes). Expressed with `GameEffect.extra_target_specs`,
    so both requirements are gathered through the ordinary RULE 115.1
    one-at-a-time machinery and arrive here flattened in printed order:
    ``targets[0]`` is what moves, ``targets[1]`` is where it goes.

    ``what_kind`` widens the first requirement for Halvar, whose clause is
    "target Aura **or** Equipment attached to a creature you control".
    """

    def __init__(
        self,
        what_kind: str = "equipment_you_control",
        to_kind: str = "creature_you_control",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=what_kind)
        self.extra_target_specs = (TargetSpec(kind=to_kind),)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        if len(picks) < 2:
            return
        what, host = picks[0], picks[1]
        if what is None or host is None:
            return
        context.attach_to_target(what, host)


class CounterThenFightlikeDamageEffect(GameEffect):
    """"Put a +1/+1 counter on target creature you control. It deals damage
    equal to its power to target creature you don't control." (Archdruid's
    Charm's second mode) — a fight-adjacent clause with two independently
    chosen targets, the same `extra_target_specs` shape `AttachChosenEffect`
    uses.

    One atomic effect rather than a composition, because the damage amount
    is read off the *first* target **after** the counter lands (RULE 613's
    layer pass runs in between, which is exactly why the counter is worth
    putting on first) — no separate `DealDamageEffect` could see it.
    """

    def __init__(
        self,
        counters: int = 1,
        kind: str = "+1/+1",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.counters = counters
        self.kind = kind
        self.target_spec = TargetSpec(kind="creature_you_control")
        self.extra_target_specs = (TargetSpec(kind="creature_you_dont_control"),)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        if len(picks) < 2:
            return
        mine, theirs = picks[0], picks[1]
        if mine is None:
            return
        context.add_counters(mine, self.counters, self.kind, source=self.source)
        context.recompute()  # so the damage reads the *boosted* power
        if theirs is not None:
            context.deal_damage(theirs, mine.power or 0, mine)


#: Subject names that are *not* a RULE 115 target choice — the four ways a
#: fight/one-sided-damage clause can name a creature without announcing a
#: requirement for it. Shared by `FightEffect` and
#: `DamageEqualToPowerEffect`, which take exactly the same subject vocabulary
#: on either side of the verb (a fight is two of these dealing damage to each
#: other; the one-sided family is one of them dealing to a target).
#:
#: * ``None`` — the effect's own source ("**it** fights …" in a trigger whose
#:   subject is that permanent, "when ~ dies, **it** deals damage equal to its
#:   power to any target");
#: * ``"attached_permanent"`` — an Aura/Equipment's current host ("when this
#:   Aura enters, **enchanted creature** fights …"), re-read live at
#:   resolution the way `TapEffect`'s attached mode does;
#: * ``"previous_target"`` / ``"previous_target_2"`` — the first/second target
#:   the *preceding* clause of this same resolution chose
#:   (`GameContext.previous_targets`): "target creature you control gets
#:   +1/+2 until end of turn. **It** fights target creature you don't
#:   control." (Epic Confrontation) and "Choose target creature you control
#:   and target creature you don't control. … Then **those creatures** fight
#:   each other." (Ancient Animus).
_IMPLICIT_FIGHT_SUBJECTS: frozenset = frozenset(
    {None, "attached_permanent", "previous_target", "previous_target_2"}
)


def _implicit_fight_subject(
    kind: Optional[str], effect: "GameEffect", context: GameContext
) -> Optional[Any]:
    """Resolve one of `_IMPLICIT_FIGHT_SUBJECTS` against the live game."""
    if kind is None:
        return effect.source
    if kind == "attached_permanent":
        host_id = getattr(effect.source, "attached_to", None)
        return context.state.find_object(host_id) if host_id is not None else None
    index = 1 if kind == "previous_target_2" else 0
    previous = getattr(context, "previous_targets", []) or []
    return previous[index] if len(previous) > index else None


class FightEffect(GameEffect):
    """RULE 701.14 — "Target creature you control fights target creature you
    don't control." (Prey Upon), "~ fights up to one target creature you don't
    control." (Kogla's ETB).

    Both creatures deal damage equal to their power to each other (701.14a),
    and it is **not** combat damage (701.14d) — so `context.deal_damage`'s
    default ``combat=False`` is exactly right, and a first-strike/deathtouch-
    style combat concept never enters into it.

    ``fighter_kind``/``other_kind`` each name either a RULE 115 target kind —
    the printed two-target form ("target creature you control fights target
    creature …"), where `extra_target_specs` carries the second requirement
    the same way `AttachChosenEffect` does — or one of the four implicit
    subjects `_IMPLICIT_FIGHT_SUBJECTS` documents (the source, an Aura's host,
    or a pronoun pointing back at the previous clause's target). An implicit
    subject announces no requirement at all, so "it fights target creature you
    don't control" is a *one*-target spell and "those creatures fight each
    other" is a zero-target one.

    RULE 701.14b is the whole reason this is one atomic effect rather than two
    `DealDamageEffect`s: if *either* creature has left the battlefield or
    stopped being a creature by resolution, **neither** deals damage. Both
    powers are also snapshotted before any damage is dealt, since 701.14a's
    two damage events are simultaneous — a creature whose power changes as a
    consequence of the first half (a dies-trigger, an SBA) must still deal
    what it had. A creature fighting itself deals twice its power to itself
    (701.14c), which falls out of dealing both halves to the same object —
    *unless* ``distinct`` marks the clause's RULE 109.5 "**another** target
    creature", where picking the same creature twice was never legal to begin
    with (`TargetSpec.distinct_from_others`); this is that constraint's
    resolve-time backstop.
    """

    def __init__(
        self,
        fighter_kind: Optional[str] = None,
        other_kind: Optional[str] = "creature",
        fighter_optional: bool = False,
        optional: bool = False,
        distinct: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.fighter_kind = fighter_kind
        self.other_kind = other_kind
        self.distinct = distinct
        specs: list[TargetSpec] = []
        if fighter_kind not in _IMPLICIT_FIGHT_SUBJECTS:
            specs.append(TargetSpec(kind=fighter_kind, optional=fighter_optional))
        if other_kind not in _IMPLICIT_FIGHT_SUBJECTS:
            specs.append(
                TargetSpec(kind=other_kind, optional=optional, distinct_from_others=distinct)
            )
        if specs:
            self.target_spec = specs[0]
            self.extra_target_specs = tuple(specs[1:])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        chosen = iter(picks)
        if self.fighter_kind in _IMPLICIT_FIGHT_SUBJECTS:
            fighter = _implicit_fight_subject(self.fighter_kind, self, context)
        else:
            fighter = next(chosen, None)
        if self.other_kind in _IMPLICIT_FIGHT_SUBJECTS:
            other = _implicit_fight_subject(self.other_kind, self, context)
        else:
            other = next(chosen, None)
        # RULE 701.14b: gone from the battlefield, or no longer a creature →
        # neither fights (an "up to one" clause with no target lands here too).
        battlefield = context.state.permanents()
        for creature in (fighter, other):
            if creature is None or creature not in battlefield or not creature.is_creature:
                return
        if fighter is other and (self.distinct or self.fighter_kind == "previous_target"):
            # RULE 109.5: "another" was never a legal pick of itself. The same
            # guard covers a pronoun fighter whose clause declined its own
            # "up to one" target — a caller that sends a *flat* list can't
            # say which requirement was skipped (`targeting.partition_targets`
            # returns None there), so this clause would otherwise read the
            # earlier clause's pick as its own and have the creature fight
            # itself. No printed card means that.
            return
        fighter_power = fighter.power or 0
        other_power = other.power or 0
        context.deal_damage(other, fighter_power, fighter)
        context.deal_damage(fighter, other_power, other)


class DamageEqualToPowerEffect(GameEffect):
    """"Target creature you control deals damage equal to its power to target
    creature you don't control." (Rabid Bite) — the *one-sided* fight, and
    "When ~ dies, it deals damage equal to its power to any target." /
    "… to each opponent." (Ghoulcaller's Accomplice-shaped dies triggers).

    Shares `FightEffect`'s subject vocabulary for the **dealer**
    (`_IMPLICIT_FIGHT_SUBJECTS`, or a target kind) and `DealDamageEffect`'s
    for the **recipient** (a target kind, or an untargeted ``selector`` —
    RULE 601.2c's "each opponent"/"each player"/"each creature").

    Two rules-relevant differences from a fight, both deliberate: the damage
    is one-way, and the dealer is **not** required to still be on the
    battlefield. The commonest printed form of this clause is a dies trigger,
    where the dealer is already in the graveyard as the ability resolves —
    RULE 608.2h's last known information is what its power is read from, which
    is exactly what `GameObject.power` still reports there.
    """

    def __init__(
        self,
        dealer_kind: Optional[str] = None,
        target_kind: Optional[str] = "any",
        selector: Optional[str] = None,
        dealer_optional: bool = False,
        optional: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.dealer_kind = dealer_kind
        self.selector = selector if selector in _DAMAGE_SELECTORS else None
        specs: list[TargetSpec] = []
        if dealer_kind not in _IMPLICIT_FIGHT_SUBJECTS:
            specs.append(TargetSpec(kind=dealer_kind, optional=dealer_optional))
        if self.selector is None and target_kind is not None:
            specs.append(TargetSpec(kind=target_kind, optional=optional))
        if specs:
            self.target_spec = specs[0]
            self.extra_target_specs = tuple(specs[1:])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        chosen = iter(picks)
        if self.dealer_kind in _IMPLICIT_FIGHT_SUBJECTS:
            dealer = _implicit_fight_subject(self.dealer_kind, self, context)
        else:
            dealer = next(chosen, None)
        if dealer is None:
            return
        amount = dealer.power or 0
        if amount <= 0:
            return
        if self.selector is not None:
            for recipient in self._selected_recipients(context, dealer):
                context.deal_damage(recipient, amount, dealer)
            return
        recipient = next(chosen, None)
        if recipient is None:
            return
        if recipient is dealer and self.dealer_kind == "previous_target":
            # The same flat-list guard `FightEffect` makes: a declined "up to
            # one" would otherwise leave this clause reading the previous
            # clause's pick as its own recipient, damaging it with itself.
            return
        # A permanent that has since left the battlefield takes no damage
        # (RULE 608.2b's illegal-target check, the same guard a fight makes);
        # a player recipient (no ``instance_id``) is always still there.
        if hasattr(recipient, "instance_id") and recipient not in context.state.permanents():
            return
        context.deal_damage(recipient, amount, dealer)

    def _selected_recipients(self, context: GameContext, dealer: Any) -> list[Any]:
        """RULE 601.2c's untargeted recipient groups, scoped to the **dealer**
        (not the effect's source — "each opponent" of the creature dealing the
        damage, which for a granted/copied ability need not be the same
        player)."""
        if self.selector == "each_creature":
            return [obj for obj in context.state.permanents() if obj.is_creature]
        controller_id = getattr(dealer, "controller_id", None)
        return [
            player
            for player in context.state.living_players()
            if not (self.selector == "each_opponent" and player.id == controller_id)
        ]


class DamageEqualToCountersEffect(GameEffect):
    """"~ deals damage equal to the number of +1/+1 counters on it to any
    other target." (Red Hulk-shaped) — `DamageEqualToPowerEffect`'s sibling
    for a counter-count amount rather than power (the two aren't always the
    same number: a creature's power can be modified by other statics/pumps
    independently of its counters).

    Red Hulk's own printed shape ("put a +1/+1 counter on him. **When you
    do**, he deals damage equal to the number of +1/+1 counters on him to
    any other target.") is really two abilities under RULE 603.10 — a
    reflexive trigger off the counter-placement, not a plain sequential
    resolution. This engine has no reflexive "when you do" trigger
    primitive yet, so the catalogue entry runs both as one triggered
    ability's effect list instead (RULE 608.2a resolves a list in printed
    order, and nothing has a window to intervene between them either way in
    an automated engine) — a documented simplification, not a rules
    difference a real game could ever observe.
    """

    def __init__(
        self,
        kind: str = "+1/+1",
        target: Any = None,
        target_kind: Optional[str] = "any",
        optional: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional) if target_kind else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        amount = (
            self.source.plus_one_counters if self.kind == "+1/+1"
            else int((getattr(self.source, "counters", None) or {}).get(self.kind, 0) or 0)
        )
        if amount <= 0:
            return
        context.deal_damage(target, amount, self.source)


class ChooseTargetsEffect(GameEffect):
    """"Choose target creature you control **and** target creature you don't
    control." (Ancient Animus, Coven-style fight spells) — a clause that only
    *announces* targets (RULE 601.2c), doing nothing on its own; the clauses
    after it act on them by pronoun ("Then **those creatures** fight each
    other.", `_IMPLICIT_FIGHT_SUBJECTS`' ``previous_target``/
    ``previous_target_2`` via `GameContext.previous_targets`).

    Modeling it as a real, no-op effect rather than folding the targets into
    whichever later clause uses them keeps the announcement where the card
    prints it: the targets are chosen as the spell is *cast* (RULE 601.2c),
    so they must be part of what `targeting.spell_target_specs` reports even
    when the clause consuming them is conditional and may never happen ("if
    you control three or more snow permanents, …").

    ``count``/``distinct_controllers``/``optional`` (PAR-1, only meaningful
    with a single ``kinds`` entry) are Run Away Together's own "**choose two
    target creatures** controlled by different players." shape — one
    quantified requirement picking N objects of the *same* kind, unlike the
    Ancient Animus pair above (two independent, differently-kinded single
    choices). The whole chosen group is then read back — not by a
    positional ``previous_target``/``previous_target_2`` pronoun, which only
    ever names the *first*/*second* of exactly two — by a later clause's own
    ``previous_subject`` flag (`ReturnToHandEffect`'s, for now).
    """

    def __init__(
        self,
        kinds: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
        count: Optional[int] = None,
        distinct_controllers: bool = False,
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        kinds = kinds or []
        if len(kinds) == 1 and count:
            specs = [TargetSpec(
                kind=kinds[0], count=count, distinct_controllers=distinct_controllers,
                optional=optional,
            )]
        else:
            specs = [TargetSpec(kind=kind) for kind in kinds]
        if specs:
            self.target_spec = specs[0]
            self.extra_target_specs = tuple(specs[1:])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        # Nothing happens here; the picks reach the following clauses through
        # `_apply_effects_partitioned`'s `GameContext.previous_targets`.
        return


class DestroyEachWithManaValueEffect(GameEffect):
    """"Destroy each artifact with mana value X." (Dauntless Dismantler's
    ``{X}{X}{W}`` ability) — a mass destroy whose *filter* is the ability's
    own announced X rather than a printed constant.

    The shipped `DestroyEffect`'s ``max_mana_value`` is a printed cap; this
    is an exact match against a value only known at activation, threaded
    through the same ``"x"`` sentinel `RulesEngine._substitute_x` rewrites
    for every other X-scaled magnitude. Untargeted (RULE 601.2c), like every
    other board wipe here.
    """

    def __init__(
        self,
        amount: Any = 0,
        card_type: str = "artifact",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.card_type = card_type

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if not isinstance(self.amount, int):
            return
        doomed = [
            obj
            for obj in context.state.permanents()
            if self.card_type in obj.type_words
            and obj.card.converted_mana_cost == self.amount
        ]
        for obj in doomed:
            context.destroy(obj)


class DiscardOrLoseLifeEffect(GameEffect):
    """"Each opponent may discard a card. If they don't, they lose N life.
    Repeat this process M more times." (Professor Onyx's −8) — RULE 701.8
    plus a fixed-count repetition.

    ``times`` is the total number of rounds (7 for Onyx: the first plus "six
    more"), which makes this a *bounded* loop like `MillUntilCreatureEffect`
    rather than an open-ended one — the count is known before it starts.

    Whether to discard is each opponent's own decision (RULE 118.3-style
    optional payment), so every round is a real `pay_cost_then` prompt —
    the shipped primitive Mana Vault and Wandering Archaic already use,
    with discarding as the cost and losing the life as its "if you don't"
    branch. The loop is driven by making *both* branches carry a
    ``discard_or_lose_life`` spec for the remaining rounds/opponents, so
    resolving one prompt opens the next: `pending_choice` holds one
    decision at a time, which a Python loop here could never respect.

    ``round_index``/``player_index`` are that continuation's bookmark
    (rounds completed so far, and how far through the opponent list this
    round is) — internal, never authored on a card.
    """

    def __init__(
        self,
        count: int = 1,
        amount: int = 3,
        times: int = 1,
        selector: str = "each_opponent",
        round_index: int = 0,
        player_index: int = 0,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.amount = amount
        self.times = int(times)
        self.selector = selector
        self.round_index = int(round_index)
        self.player_index = int(player_index)

    def _continuation_spec(self, round_index: int, player_index: int) -> dict[str, Any]:
        """This same effect, bookmarked one step further on."""
        return {
            "type": "discard_or_lose_life",
            "params": {
                "count": self.count,
                "amount": self.amount,
                "times": self.times,
                "selector": self.selector,
                "round_index": round_index,
                "player_index": player_index,
            },
        }

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import ActivationCost

        controller_id = getattr(self.source, "controller_id", None)
        opponents = [
            p for p in context.state.living_players()
            if not (self.selector == "each_opponent" and p.id == controller_id)
        ]
        round_index, player_index = self.round_index, self.player_index
        # Skip past anyone already handled this round, and past finished
        # rounds — the loop only ever advances, so a re-entry can't repeat.
        while round_index < max(self.times, 0):
            if player_index >= len(opponents):
                round_index += 1
                player_index = 0
                continue
            player = opponents[player_index]
            if not player.hand:
                # Nothing to discard: RULE 118.3's "a player who can't pay
                # isn't asked", so the else-branch applies straight away.
                context.lose_life(player, self.amount)
                player_index += 1
                continue
            cost = ActivationCost(discard=self.count)
            rest = [self._continuation_spec(round_index, player_index + 1)]
            context.engine.request_pay_cost_then(
                player,
                cost,
                effect_specs=rest,
                else_effect_specs=[
                    {
                        "type": "lose_life",
                        "params": {"amount": self.amount, "player_id": player.id},
                    },
                    *rest,
                ],
                source=self.source,
                prompt=f"{player.id}: Eine Karte abwerfen statt {self.amount} Leben zu verlieren?",
            )
            return


class GainControlOfAllCommandersEffect(GameEffect):
    """"Gain control of all commanders. Put all commanders from the command
    zone onto the battlefield under your control." (Tevesh Szat's −10) —
    RULE 903.3/110.2.

    Genuinely Commander-specific, with no near-miss anywhere in the engine:
    the layer-2 ``control_change`` static reassigns one permanent for as
    long as its source stays around, and no shipped effect moves a card out
    of the **command zone** onto the battlefield at all.

    The control change here is permanent (a one-shot RULE 110.2 change, like
    `ExchangeControlEffect`'s), not a duration-bounded grab — Tevesh Szat is
    an ultimate, and the board state it creates is meant to stick.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        for obj in list(context.state.battlefield):
            if obj.is_commander:
                obj.controller_id = controller.id
                obj.summoning_sick = True  # RULE 302.6: new controller
        for player in context.state.players:
            for obj in list(player.command):
                if not obj.is_commander:
                    continue
                player.remove_from_zone(obj, Zone.COMMAND)
                obj.controller_id = controller.id
                obj.zone = Zone.BATTLEFIELD
                obj.summoning_sick = True
                context.state.add_to_battlefield(obj)
                context.fire_event(
                    GameEvent(
                        EventType.ENTERS_BATTLEFIELD,
                        instance_id=obj.instance_id,
                        controller_id=obj.controller_id,
                        object_types=sorted(obj.type_words),
                    )
                )
        context.recompute()


class MultiplyDamageFromTargetEffect(GameEffect):
    """"Choose target creature. Until your next turn, if that creature would
    deal combat damage to one of your opponents, it deals triple that damage
    to that player instead." (Jeska, Thrice Reborn's 0) — RULE 616.1.

    The shipped damage-multiplying replacement family (Furnace of Rath/Fiery
    Emancipation) is standing, board-wide and sourced from a permanent whose
    presence keeps it alive. This is the same *rewrite*, scoped three ways
    that family never needed: to one specific source instance, to combat
    damage only, and to the effect's controller's opponents — and bounded by
    a duration rather than by its source sticking around.

    So it reuses the replacement machinery rather than a new one: a
    turn-scoped `ReplacementEffect` installed on the targeted creature's own
    `GameObject.replacement_effects`, exactly the per-object shield shape
    `RegenerateEffect` already uses.
    """

    def __init__(
        self,
        multiplier: int = 2,
        combat_only: bool = True,
        to: str = "opponents",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.multiplier = int(multiplier)
        self.combat_only = combat_only
        self.to = to
        self.target_spec = TargetSpec(kind="creature")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        controller = _controller_of(self.source, context)
        if target is None or controller is None:
            return
        multiplier = self.multiplier
        combat_only = self.combat_only
        wants_opponents = self.to == "opponents"
        source_id = target.instance_id
        controller_id = controller.id

        def _replace(event: GameEvent, ctx: GameContext) -> Optional[GameEvent]:
            if event.get("source_id") != source_id:
                return event
            if combat_only and not event.get("combat"):
                return event
            if not event.get("is_player"):
                return event
            if wants_opponents and event.get("target_id") == controller_id:
                return event
            return event.copy_with(amount=int(event.get("amount", 0)) * multiplier)

        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=_replace,
            source=self.source,
            description=f"{target.name}: {multiplier}× Kampfschaden",
        )
        # "Until your next turn" (RULE 611.2b) — the same duration key
        # `GameEngine.begin_turn` already sweeps for `PlayerShieldEffect`
        # and Hope of Ghirapur's lock, here on a permanent instead.
        effect.until_next_turn_of = controller_id
        target.replacement_effects.append(effect)


class EffectRegistry:
    """Maps an effect-type name to a factory ``(params) -> GameEffect``.

    The hybrid design from docs/07 PART 4: predefined classes stay
    type-safe, but oracle-text parsing (a later step) can create effects
    by name + params without the engine knowing each card.
    """

    _factories: dict[str, Callable[[dict[str, Any]], GameEffect]] = {}

    @classmethod
    def register(cls, effect_type: str, factory: Callable[[dict[str, Any]], GameEffect]) -> None:
        cls._factories[effect_type] = factory

    @classmethod
    def create(cls, effect_type: str, params: Optional[dict[str, Any]] = None) -> GameEffect:
        if effect_type not in cls._factories:
            raise ValueError(f"unknown effect type: {effect_type!r}")
        return cls._factories[effect_type](params or {})

    @classmethod
    def is_registered(cls, effect_type: str) -> bool:
        return effect_type in cls._factories


# Register the core one-shot effects (RULE R3.1 in docs/02).
EffectRegistry.register(
    "damage",
    lambda p: DealDamageEffect(
        amount=p.get("amount", 0),
        target=p.get("target"),
        target_kind=p.get("target_kind", "any"),
        selector=p.get("selector"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        count_max=p.get("count_max"),
        colors=p.get("colors"),
        divided=bool(p.get("divided", False)),
        double_at=p.get("double_at"),
        amount_if_kicked=p.get("amount_if_kicked"),
        amount_if_bargained=p.get("amount_if_bargained"),
        double_if_bargained=bool(p.get("double_if_bargained", False)),
        amount_if_target_color=(
            (p["amount_if_target_color"]["amount"], list(p["amount_if_target_color"]["colors"]))
            if p.get("amount_if_target_color") else None
        ),
        amount_if_cast_from_exile=p.get("amount_if_cast_from_exile"),
        x_multiplier=p.get("x_multiplier"),
        amount_from_noncreature_spells_cast_this_turn=bool(
            p.get("amount_from_noncreature_spells_cast_this_turn", False)
        ),
        amount_from_count_selector=p.get("amount_from_count_selector"),
        amount_plus_count_selector=int(p.get("amount_plus_count_selector", 0) or 0),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
    ),
)
EffectRegistry.register(
    # "…its controller may draw a card if its power is greater than each
    # other creature's power." (Selvala, Heart of the Wilds, MEC-43) — see
    # `DrawIfTriggerObjectGreatestPowerEffect`.
    "draw_if_trigger_object_greatest_power",
    lambda p: DrawIfTriggerObjectGreatestPowerEffect(),
)
EffectRegistry.register(
    "draw",
    lambda p: DrawCardEffect(
        count=p.get("count", 1), player=p.get("player"), count_selector=p.get("count_selector"),
        target_kind=p.get("target_kind"), selector=p.get("selector"),
        amount_from_count_selector=p.get("amount_from_count_selector"),
    ),
)
EffectRegistry.register(
    "discard",
    lambda p: DiscardEffect(
        count=p.get("count", 1), player=p.get("player"),
        target_kind=p.get("target_kind"), scope=p.get("scope"),
    ),
)
EffectRegistry.register(
    "put_hand_cards_on_top",  # "put N cards from your hand on top of your library" (Brainstorm)
    lambda p: PutHandCardsOnTopEffect(count=p.get("count", 1), player=p.get("player")),
)
EffectRegistry.register(
    "put_hand_card_on_bottom_then_draw",  # "you may put a card from your hand on the bottom of your library. If you do, draw a card." (Volcanic Spite)
    lambda p: PutHandCardOnBottomThenDrawEffect(player=p.get("player")),
)
EffectRegistry.register(
    "reveal_hand_choose_discard",  # Duress/Thoughtseize/Coercion-shaped
    lambda p: RevealHandChooseDiscardEffect(
        target_kind=p.get("target_kind", "player"),
        target=p.get("target"),
        exclude_land=bool(p.get("exclude_land", False)),
        exclude_creature=bool(p.get("exclude_creature", False)),
        card_types=p.get("card_types"),
        max_mana_value=p.get("max_mana_value"),
    ),
)
EffectRegistry.register(
    "reveal_top_conditional_to_hand",  # Goblin Guide-shaped
    lambda p: RevealTopConditionalToHandEffect(
        whose=p.get("whose", "defending_player"),
        card_type=p.get("card_type", "land"),
    ),
)
EffectRegistry.register(
    "destroy",
    lambda p: DestroyEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        count_max=p.get("count_max"),
        selector=p.get("selector"),
        filter=p.get("filter"),
        can_be_regenerated=bool(p.get("can_be_regenerated", True)),
        color=p.get("color"),
        max_mana_value=p.get("max_mana_value"),
        creature_filter=p.get("creature_filter"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        exclude_created=bool(p.get("exclude_created", False)),
        target_from_trigger_event=p.get("target_from_trigger_event"),
    ),
)
EffectRegistry.register(
    "regenerate",
    lambda p: RegenerateEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    "gain_life",
    lambda p: GainLifeEffect(
        amount=p.get("amount", 0), player=p.get("player"), target_kind=p.get("target_kind"),
        count_selector=p.get("count_selector"),
        amount_from_target_power=bool(p.get("amount_from_target_power", False)),
        recipient=p.get("recipient"),
    ),
)
EffectRegistry.register(
    "prevent_damage_shield",
    # RULE 615 one-shot "prevent all/the next N damage that would be dealt
    # to you this turn" (Riot Control/Thought Lash) — NOT the standing-
    # permanent shape; see `ReplacementRegistry`'s own unrelated
    # `"prevent_damage"` factory below for that (the Sphere/absorb/Shield of
    # the Realm family — MEC-30), or `"request_prevent_damage_source"`/
    # `"prevent_damage_from_target"` just below for the *chosen-source*
    # one-shot family (Circle/Rune of Protection).
    lambda p: PreventDamageEffect(
        amount=p.get("amount", "all"),
        target_kind=p.get("target_kind"),
        target=p.get("target"),
        count=p.get("count", 1),
        optional=bool(p.get("optional", False)),
        divided=bool(p.get("divided", False)),
        amount_if_kicked=p.get("amount_if_kicked"),
        self_only=bool(p.get("self_only", False)),
        watched_source_is_self=bool(p.get("watched_source_is_self", False)),
        recipient_is_activator=bool(p.get("recipient_is_activator", False)),
    ),
)
EffectRegistry.register(
    "prevent_all_combat_damage",
    # RULE 615's unscoped Fog-shaped shield — distinct from
    # "prevent_damage_shield" above, which always shields one recipient.
    lambda p: PreventAllCombatDamageEffect(exclude_subtype=p.get("exclude_subtype")),
)
EffectRegistry.register(
    "prevent_life_gain",
    # RULE 119.3's "can't gain life this turn" — distinct from
    # "prevent_damage_shield" above (a damage shield, numeric or "all");
    # this cancels a `LIFE_GAIN` outright, no bank to track.
    lambda p: PreventLifeGainEffect(recipient=p.get("recipient", "opponents")),
)
EffectRegistry.register(
    "disable_damage_prevention",
    # RULE 615 "Damage can't be prevented this turn." (MEC-30 — Insult //
    # Injury/Isengard Unleashed) — see `DisableDamagePreventionEffect`.
    lambda p: DisableDamagePreventionEffect(),
)
EffectRegistry.register(
    "grant_damage_multiplier_this_turn",
    # RULE 616 "…it deals double/triple that damage instead" (MEC-30), the
    # spell-cast sibling of the standing `"double_damage"` replacement
    # below — see `GrantDamageMultiplierThisTurnEffect`.
    lambda p: GrantDamageMultiplierThisTurnEffect(
        multiplier=int(p.get("multiplier", 2)),
        to_opponent_only=bool(p.get("to_opponent_only", False)),
    ),
)
EffectRegistry.register(
    "request_prevent_damage_source",
    # RULE 615/616.1d "the next time a source of your choice would deal
    # damage to `<recipient>` this turn, prevent that damage" (MEC-30 —
    # Circle of Protection/Rune of Protection and siblings) — see
    # `RequestPreventDamageSourceEffect`.
    lambda p: RequestPreventDamageSourceEffect(
        source_filter=p.get("source_filter"),
        target_kind=p.get("target_kind"),
        target=p.get("target"),
        amount=p.get("amount", "all"),
        rider=p.get("rider"),
        optional=bool(p.get("optional", False)),
        recipient=p.get("recipient"),
    ),
)
EffectRegistry.register(
    "request_redirect_damage_source",
    # RULE 616.1c "the next time a source of your choice would deal damage
    # this turn, that damage is dealt to `<X>` instead" (MEC-30 — Opal-Eye,
    # Konda's Yojimbo) — see `RequestRedirectDamageSourceEffect`.
    lambda p: RequestRedirectDamageSourceEffect(
        source_filter=p.get("source_filter"),
        amount=p.get("amount", "all"),
        recipient=p.get("recipient", "self"),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    "choose_source_coinflip",
    # "Choose a source you control and flip a coin. If you win, ... double
    # ... . If you lose, ... prevent ...." (MEC-30 — Desperate Gambit) —
    # see `ChooseSourceCoinFlipEffect`.
    lambda p: ChooseSourceCoinFlipEffect(),
)
EffectRegistry.register(
    "prevent_damage_from_target",
    # RULE 615/616.1d's targeted, no-chooser-needed sibling of
    # "request_prevent_damage_source" above (MEC-30 — Awe Strike/Dazzling
    # Reflection: "the next time **target creature** would deal damage this
    # turn, prevent that damage") — see `PreventDamageFromTargetEffect`.
    lambda p: PreventDamageFromTargetEffect(
        target_kind=p.get("target_kind", "creature"),
        target=p.get("target"),
        count=p.get("count", 1),
        amount=p.get("amount", "all"),
        rider=p.get("rider"),
    ),
)
EffectRegistry.register(
    "extra_land_play",
    lambda p: ExtraLandPlayEffect(count=p.get("count", 1)),
)
EffectRegistry.register(
    "graveyard_play_permission_this_turn",  # Yawgmoth's Will's own first clause
    lambda p: GraveyardPlayPermissionThisTurnEffect(),
)
EffectRegistry.register(
    "graveyard_redirect_to_exile_this_turn",  # Yawgmoth's Will's own second clause
    lambda p: GraveyardRedirectToExileEffect(),
)
EffectRegistry.register(
    "exchange_life_totals",  # "Two target players exchange life totals." (Soul Conduit)
    lambda p: ExchangeLifeTotalsEffect(),
)
EffectRegistry.register(
    "lose_life",
    lambda p: LoseLifeEffect(
        amount=p.get("amount", 0), player=p.get("player"), selector=p.get("selector"),
        target_kind=p.get("target_kind"), player_id=p.get("player_id"),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
        amount_from_life_gained_this_turn=bool(p.get("amount_from_life_gained_this_turn", False)),
        amount_from_burden_counters_on_self=bool(p.get("amount_from_burden_counters_on_self", False)),
        amount_from_count_selector=p.get("amount_from_count_selector"),
        amount_from_spells_cast_this_turn=bool(p.get("amount_from_spells_cast_this_turn", False)),
        amount_from_half_own_life=bool(p.get("amount_from_half_own_life", False)),
        amount_from_half_target_life=bool(p.get("amount_from_half_target_life", False)),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    "add_player_counters",
    lambda p: AddPlayerCountersEffect(
        amount=p.get("amount", 0), kind=p.get("kind", "rad"), player=p.get("player"),
        selector=p.get("selector"), target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    "lose_all_player_counters",
    lambda p: LoseAllPlayerCountersEffect(
        kind=p.get("kind", "rad"), player=p.get("player"), target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    "dies_grants_rad_counters_equal_power",
    lambda p: DiesGrantsRadCountersEqualPowerEffect(kind=p.get("kind", "rad")),
)
EffectRegistry.register(
    "counter",
    lambda p: CounterSpellEffect(
        target=p.get("target"),
        unless_pays=p.get("unless_pays"),
        noncreature=bool(p.get("noncreature", False)),
        card_types=p.get("card_types"),
        mana_value=p.get("mana_value"),
        color=p.get("color"),
        target_from_trigger_event=p.get("target_from_trigger_event"),
        suspend_instead=p.get("suspend_instead"),
    ),
)
EffectRegistry.register(
    # "Counter target activated or triggered ability." (RULE 701.5b —
    # Stifle/Trickbind, ENG-26) — the ability-item sibling of ``"counter"``.
    "counter_ability",
    lambda p: CounterAbilityEffect(target=p.get("target")),
)
EffectRegistry.register(
    "copy_spell",
    lambda p: CopySpellEffect(
        card_types=p.get("card_types"),
        count=p.get("count", 1),
        target_count=int(p.get("target_count", 1) or 1),
        optional=bool(p.get("optional", False)),
        spell_from_trigger_event=p.get("spell_from_trigger_event"),
        controller_from_trigger_event=p.get("controller_from_trigger_event"),
    ),
)
EffectRegistry.register(
    "copy_self_if_cast_from_graveyard",
    lambda p: CopySelfIfCastFromGraveyardEffect(),
)
EffectRegistry.register(
    # "That player may copy this spell…" (Chain of Smog, MEC-43) — see
    # `CopySelfControlledByPreviousTargetEffect`.
    "copy_self_controlled_by_previous_target",
    lambda p: CopySelfControlledByPreviousTargetEffect(),
)
EffectRegistry.register(
    "change_target",
    lambda p: ChangeTargetEffect(
        target=p.get("target"),
        single_target=bool(p.get("single_target", False)),
        optional=bool(p.get("optional", False)),
        spell_or_ability=bool(p.get("spell_or_ability", False)),
        card_types=p.get("card_types"),
        redirect_to_source=bool(p.get("redirect_to_source", False)),
    ),
)
EffectRegistry.register(
    # "Gain control of target noncreature spell. You may choose new targets
    # for it." (Commandeer)
    "gain_control_of_spell",
    lambda p: GainControlOfSpellEffect(target=p.get("target")),
)
EffectRegistry.register(
    # "Return it to the battlefield [tapped] under its owner's control."
    # (Nezahal, Primal Tide's own delayed-trigger half)
    "return_self_to_battlefield",
    lambda p: ReturnSelfToBattlefieldEffect(tapped=bool(p.get("tapped", False))),
)
EffectRegistry.register(
    # "…reveal the top card of your library. If it's a land card, put it
    # onto the battlefield tapped. Otherwise, draw a card." (Thrasios,
    # Triton Hero)
    "reveal_top_then_land_battlefield_or_draw",
    lambda p: RevealTopThenLandBattlefieldOrDrawEffect(),
)
EffectRegistry.register(
    # "Look at the top card of your library. If it's a land card or a
    # creature card with mana value less than or equal to the number of
    # loyalty counters on ~, you may put that card onto the battlefield."
    # (Nissa, Steward of Elements, MEC-41)
    "reveal_top_then_maybe_battlefield_if_land_or_cheap_creature",
    lambda p: RevealTopThenMaybeBattlefieldIfLandOrCheapCreatureEffect(),
)
EffectRegistry.register(
    # "When ~ dies, if it was a creature, return it to the battlefield
    # under its owner's control. It's an enchantment." (Enduring Vitality)
    "dies_return_as_enchantment",
    lambda p: DiesReturnAsEnchantmentEffect(),
)
EffectRegistry.register(
    # "Exile target creature you control, then reveal cards from the top of
    # your library until you reveal a creature card with greater mana
    # value…" (Lukka, Coppercoat Outcast)
    "exile_then_reveal_greater_mana_value",
    lambda p: ExileThenControllerRevealGreaterManaValueEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature_you_control"),
    ),
)
EffectRegistry.register(
    # "Each creature you control deals damage equal to its power to each
    # opponent." (Lukka, Coppercoat Outcast)
    "each_creature_you_control_damages_each_opponent",
    lambda p: EachCreatureYouControlDamageEachOpponentEffect(),
)
EffectRegistry.register(
    # "Exile the top N cards of your library. Creature cards exiled this
    # way gain 'You may cast this card from exile as long as `<condition>`.'"
    # (Lukka, Coppercoat Outcast)
    "exile_top_then_grant_conditional_cast",
    lambda p: ExileTopThenGrantConditionalCastEffect(
        count=int(p.get("count", 1) or 1), condition=p.get("condition"),
    ),
)
EffectRegistry.register(
    # "Reveal the top card of your library and put that card into your
    # hand. You lose life equal to its mana value." (MEC-12, Dark Confidant)
    "reveal_top_then_take_and_lose_life",
    lambda p: RevealTopThenTakeAndLoseLifeEffect(),
)
EffectRegistry.register(
    # "End the turn." (Day's Undoing/Time Stop-shaped reminder text)
    "end_the_turn",
    lambda p: EndTheTurnEffect(),
)
EffectRegistry.register("cant_be_countered", lambda p: CantBeCounteredEffect())
EffectRegistry.register(
    "grant_cant_be_countered",
    lambda p: GrantCantBeCounteredEffect(scope=p.get("scope", "you"), color=p.get("color")),
)
EffectRegistry.register(
    "grant_search_prohibited",
    lambda p: GrantSearchProhibitedEffect(scope=p.get("scope", "opponents")),
)
EffectRegistry.register(
    "grant_search_limited_to_top_n",
    lambda p: GrantSearchLimitedToTopNEffect(n=p.get("n", p.get("count", 4))),
)
EffectRegistry.register("grant_skip_extra_turns", lambda p: GrantSkipExtraTurnsEffect())
EffectRegistry.register(
    "mark_cant_be_countered",
    lambda p: MarkCantBeCounteredEffect(target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    # "Spells you control can't be countered this turn." (Veil of Summer)
    "mark_your_spells_on_stack_cant_be_countered",
    lambda p: MarkYourSpellsOnStackCantBeCounteredEffect(),
)
EffectRegistry.register(
    "look_at_cards",  # "look at the top card of target player's library" (Mishra's Bauble)
    lambda p: LookAtCardsEffect(target=p.get("target"), target_kind=p.get("target_kind", "player")),
)
EffectRegistry.register(
    "mill", lambda p: MillEffect(
        count=p.get("count", 1), target_kind=p.get("target_kind"),
        count_selector=p.get("count_selector"),
    )
)
EffectRegistry.register(
    "sacrifice_self",  # "Sacrifice ~." (Dress Down/Underworld Breach-shaped)
    lambda p: SacrificeSelfEffect(),
)
EffectRegistry.register(
    # "Sacrifice ~ unless you pay <cost>." (Arcades Sabboth/Breeding Pit/
    # Child of Gaea) — an interactive pay-or-lose-it choice, not a plain
    # sacrifice. ``cost`` is the printed cost *text*, parsed to an
    # `ActivationCost` at resolution.
    "sacrifice_unless_pay",
    lambda p: SacrificeUnlessPayEffect(cost=p.get("cost", "")),
)
EffectRegistry.register(
    # "Whenever an opponent casts a spell, you may draw a card unless that
    # player pays <cost>." (Rhystic Study/Mystic Remora/Esper Sentinel) —
    # the payer is the *triggering* event's caster, not this ability's
    # controller.
    "taxed_draw",
    lambda p: TaxedDrawEffect(
        cost=p.get("cost", ""),
        amount_from_source_power=bool(p.get("amount_from_source_power", False)),
        count=int(p.get("count", 1) or 1),
    ),
)
EffectRegistry.register(
    # PAR-13: "Each player loses N life unless they `<pay cost>`." — the
    # APNAP mass sibling of `sacrifice_unless_pay` above.
    "each_player_pay_or",
    lambda p: EachPlayerPayOrEffect(
        cost=p.get("cost", ""), effects=list(p.get("effects", [])),
        scope=p.get("scope", "each_player"), effect_targets=p.get("effect_targets", "decliner"),
    ),
)
EffectRegistry.register(
    "exile",
    lambda p: ExileEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        count_max=p.get("count_max"),
        selector=p.get("selector"),
        filter=p.get("filter"),
        remember=bool(p.get("remember", False)),
        creature_filter=p.get("creature_filter"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        track_exiled_with=bool(p.get("track_exiled_with", False)),
        max_mana_value=p.get("max_mana_value"),
        grant_owner_play_permission=bool(p.get("grant_owner_play_permission", False)),
        owner_play_permission_tax=p.get("owner_play_permission_tax"),
        trigger_event_key=p.get("trigger_event_key"),
    ),
)
EffectRegistry.register(
    # "Exile the top card of your library[, face down]." (MEC-38,
    # Necropotence) — deterministic, no chooser, unlike "exile"/"search".
    "exile_top_of_library",
    lambda p: ExileTopOfLibraryEffect(
        face_down=bool(p.get("face_down", False)),
        player_selector=p.get("player_selector", "controller"),
    ),
)
EffectRegistry.register(
    # "If it's a land card, the player puts it onto the battlefield.
    # Otherwise, the player casts it without paying its mana cost if
    # able." (MEC-33, Omen Machine/Wild Evocation's shared tail) — see
    # `LandOrFreeCastEffect`.
    "land_or_free_cast",
    lambda p: LandOrFreeCastEffect(player_selector=p.get("player_selector", "controller")),
)
EffectRegistry.register(
    # "Put that card into your hand." (MEC-38, Necropotence's own delayed
    # trigger, and Beseech the Mirror/Rebound's existing "if it wasn't
    # cast this way" tail — see `ReturnUncastExiledEffect`'s own
    # docstring) — never built as its own EffectSpec entry point before;
    # every prior use constructed it directly in Python inside another
    # effect's own `apply()`. ``exiled_object`` is set at resolve time by
    # `CreateDelayedTriggerEffect`'s `capture="created_objects"`, never a
    # bare param (a raw object reference can't cross the EffectSpec
    # security boundary).
    "return_uncast_exiled",
    lambda p: ReturnUncastExiledEffect(exiled_object=None, destination=p.get("destination", "hand")),
)
EffectRegistry.register(
    # RULE 702.45-adjacent Imprint: "you may exile a `<filter>` card from
    # your hand." (MEC-17, Chrome Mox-shaped) — see `ImprintEffect`.
    "imprint",
    lambda p: ImprintEffect(
        optional=bool(p.get("optional", True)),
        exclude_card_types=p.get("exclude_card_types"),
    ),
)
EffectRegistry.register(
    # RULE 601.2b-adjacent "as ~ enters, you may choose a nonland
    # permanent." (MEC-26, Scheming Fence) — see `ChoosePermanentEffect`.
    "choose_permanent",
    lambda p: ChoosePermanentEffect(optional=bool(p.get("optional", True))),
)
EffectRegistry.register(
    # "Whenever a player casts a spell, that player returns a land they
    # control to its owner's hand." (Mana Breach, MEC-43) — see
    # `BounceOwnLandFromTriggerEffect`.
    "bounce_own_land_from_trigger",
    lambda p: BounceOwnLandFromTriggerEffect(),
)
EffectRegistry.register(
    # RULE 601.2f-adjacent "you may cast a spell with mana value N or less
    # from your hand without paying its mana cost." (MEC-20, the
    # "Expertise" cycle) — see `FreeCastFromHandEffect`.
    "free_cast_from_hand",
    lambda p: FreeCastFromHandEffect(
        criteria={"max_mana_value": p.get("max_mana_value")},
        max_mana_value_selector=p.get("max_mana_value_selector"),
    ),
)
EffectRegistry.register(
    "exile_gain_life_equal_power",  # Swords to Plowshares-shaped
    lambda p: ExileGainLifeToControllerEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    "exile_all_graveyards", lambda p: ExileAllGraveyardsEffect(colors=p.get("colors")),
)
EffectRegistry.register(
    "exile_graveyard_card_counter_if_permanent",  # Lion Sash
    lambda p: ExileGraveyardCardCounterIfPermanentEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "any_graveyard_card")
    ),
)
EffectRegistry.register(
    "exile_graveyard_creatures_gain_life",  # Crypt Incursion
    lambda p: ExileGraveyardCreaturesGainLifeEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "player"),
        life_per_card=p.get("life_per_card", 3),
    ),
)
EffectRegistry.register(
    "exile_target_graveyard",  # Bojuka Bog/Tormod's Crypt
    lambda p: ExileTargetGraveyardEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "player"),
    ),
)
EffectRegistry.register(
    "destroy_lose_life_equal_mana_value",  # Feed the Swarm
    lambda p: DestroyLoseLifeEqualManaValueEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
    ),
)
EffectRegistry.register(
    "exile_create_token",  # Resculpt
    lambda p: ExileCreateTokenEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
        power=p.get("power"), toughness=p.get("toughness"),
        colors=list(p.get("colors", [])), subtypes=list(p.get("subtypes", [])),
        token_name=p.get("token_name"),
    ),
)
EffectRegistry.register(
    "destroy_create_token",  # Beast Within
    lambda p: DestroyCreateTokenEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
        power=p.get("power"), toughness=p.get("toughness"),
        colors=list(p.get("colors", [])), subtypes=list(p.get("subtypes", [])),
        token_name=p.get("token_name"),
        can_be_regenerated=bool(p.get("can_be_regenerated", True)),
    ),
)
EffectRegistry.register(
    "counter_create_token",  # Swan Song, Strix Serenade, An Offer You Can't Refuse
    lambda p: CounterCreateTokenEffect(
        target=p.get("target"),
        noncreature=bool(p.get("noncreature", False)),
        card_types=list(p.get("card_types", [])) or None,
        power=p.get("power"), toughness=p.get("toughness"),
        colors=list(p.get("colors", [])), subtypes=list(p.get("subtypes", [])),
        token_name=p.get("token_name"),
        count=int(p.get("count", 1)),
        keywords=list(p.get("keywords", [])),
    ),
)
EffectRegistry.register(
    "destroy_gain_life_to_controller",  # Nature's Claim
    lambda p: DestroyGainLifeToControllerEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
        amount=int(p.get("amount", 0)),
        can_be_regenerated=bool(p.get("can_be_regenerated", True)),
    ),
)
EffectRegistry.register(
    # "Destroy/Exile target creature. … Its controller reveals cards from
    # the top of their library until they reveal a creature card, puts it
    # onto the battlefield, then shuffles the rest into their library."
    # (Polymorph destroy-mode / Transmogrify exile-mode)
    "destroy_exile_then_controller_reveal_creature",
    lambda p: DestroyExileThenControllerRevealCreatureEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
        mode=p.get("mode", "destroy"), criteria=p.get("criteria", "Creature"),
    ),
)
EffectRegistry.register(
    "gain_control_until_eot",  # Zealous Conscripts / Coercive Recruiter
    lambda p: GainControlUntilEndOfTurnEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
        haste=bool(p.get("haste", True)), max_mana_value=p.get("max_mana_value"),
        selector=p.get("selector"),
    ),
)
EffectRegistry.register("return_linked_exile", lambda p: ReturnLinkedExileEffect())
EffectRegistry.register("return_all_exiled_with", lambda p: ReturnAllExiledWithEffect())
EffectRegistry.register(
    "exile_any_number_you_control",
    lambda p: ExileAnyNumberYouControlEffect(other_only=bool(p.get("other_only", True))),
)
EffectRegistry.register(
    "create_token_for_linked_exile",
    lambda p: CreateTokenForLinkedExileEffect(
        colors=p.get("colors"), subtypes=p.get("subtypes"), keywords=p.get("keywords"),
    ),
)
EffectRegistry.register(
    "exile_own_graveyard_card_mana_value_x",
    lambda p: ExileOwnGraveyardCardManaValueXEffect(
        creature_only=bool(p.get("creature_only", True)), then_specs=p.get("then_specs"),
    ),
)
EffectRegistry.register(
    "create_token_copy_of_linked_exile",
    lambda p: CreateTokenCopyOfLinkedExileEffect(
        set_power=p.get("set_power"), set_toughness=p.get("set_toughness"),
        add_subtypes=p.get("add_subtypes"),
    ),
)
EffectRegistry.register(
    "choose_void_counter_card",
    lambda p: ChooseVoidCounterCardEffect(),
)
EffectRegistry.register("exile_library", lambda p: ExileLibraryEffect())
EffectRegistry.register(
    "shuffle_graveyard_into_library", lambda p: ShuffleGraveyardIntoLibraryEffect()
)
EffectRegistry.register(
    "graveyard_to_library_bottom_random",  # Endurance
    lambda p: GraveyardToLibraryBottomRandomEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "player"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "return_to_hand_draw_if_controlled",  # Geistwave
    lambda p: ReturnToHandDrawIfControlledEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "nonland_permanent"),
    ),
)
EffectRegistry.register(
    "grant_flash_until_eot", lambda p: GrantFlashUntilEndOfTurnEffect()  # Borne Upon a Wind
)
EffectRegistry.register(
    "become_saddled", lambda p: BecomeSaddledEffect(),  # Guardian Sunmare's own "Saddle N"
)
EffectRegistry.register(
    "sylvan_library",
    lambda p: SylvanLibraryEffect(life=int(p.get("life", 4)), count=int(p.get("count", 2))),
)
EffectRegistry.register(
    "trigger_doubler",  # Roaming Throne / Elesh Norn, Mother of Machines / Delney, Streetwise Lookout
    lambda p: TriggerDoublerEffect(
        cause_filter=p.get("cause_filter"), cause_type_filter=p.get("cause_type_filter"),
        min_power=p.get("min_power"), max_power=p.get("max_power"),
    ),
)
EffectRegistry.register(
    "damage_then_investigate_if_excess",  # Torch the Witness
    lambda p: DamageThenInvestigateIfExcessEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "grant_graveyard_cast_permission_this_turn",  # Backdraft Hellkite
    lambda p: GrantGraveyardCastPermissionThisTurnEffect(),
)
EffectRegistry.register(
    # MEC-24: "target instant or sorcery card in your graveyard gains
    # flashback [<cost>] until end of turn." — Recoup/Snapcaster Mage-shaped.
    # See `GrantFlashbackToTargetEffect`'s own docstring for why this is a
    # per-graveyard-card marker rather than reusing the untargeted grant
    # just above.
    "grant_flashback_to_target",
    lambda p: GrantFlashbackToTargetEffect(cost=p.get("cost")),
)
EffectRegistry.register(
    "grant_self_activated_ability",  # Urza's Saga's own chapter grants
    lambda p: GrantSelfActivatedAbilityEffect(
        cost=p.get("cost"), effects=p.get("effects"),
    ),
)
EffectRegistry.register(
    "exile_hand_then_draw_that_many",  # Invasion of Kaldheim
    lambda p: ExileHandThenDrawThatManyEffect(),
)
EffectRegistry.register(
    "exile_top_from_each_player_cast_free",  # Etali, Primal Storm
    lambda p: ExileTopFromEachPlayerCastFreeEffect(),
)
EffectRegistry.register(
    "arm_spell_watcher",  # Dual Strike
    lambda p: ArmSpellWatcherEffect(
        then_specs=p.get("then_specs"),
        max_mana_value=p.get("max_mana_value"),
        card_types=p.get("card_types"),
        repeat=bool(p.get("repeat", False)),
    ),
)
EffectRegistry.register(
    "grant_die_to_exile_this_turn",  # Lava Coil/Smite the Deathless/Torch the Tower
    lambda p: GrantDieToExileThisTurnEffect(
        target=p.get("target"), target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    "each_opponent_counter_own_creature",  # High Perfect Morcant's "blights"
    lambda p: EachOpponentCounterOwnCreatureEffect(
        amount=int(p.get("amount", 1) or 1), kind=p.get("kind", "-1/-1"),
    ),
)
EffectRegistry.register(
    "transform_named_tokens",  # Glissa, Herald of Predation
    lambda p: TransformNamedTokensEffect(
        token_name=p.get("token_name", "Incubator"),
        add_types=p.get("add_types"),
        add_subtypes=p.get("add_subtypes"),
        power=int(p.get("power", 0) or 0),
        toughness=int(p.get("toughness", 0) or 0),
    ),
)
EffectRegistry.register(
    "top_up_player_counter",  # Vraska, Betrayal's Sting's -9
    lambda p: TopUpPlayerCounterToThresholdEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "player"),
        kind=p.get("kind", "poison"),
        threshold=int(p.get("threshold", 9) or 9),
    ),
)
EffectRegistry.register(
    "exile_controller_searches_basic_land",  # Winds of Abandon
    lambda p: ExileControllerSearchesBasicLandEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "request_choose_player", lambda p: RequestChoosePlayerEffect()  # Stuffy Doll
)
EffectRegistry.register(
    "deal_damage_to_chosen_player", lambda p: DealDamageToChosenPlayerEffect()  # Stuffy Doll
)
EffectRegistry.register(
    "request_choose_creature_type_grant",  # Selfless Safewright
    lambda p: RequestChooseCreatureTypeGrantEffect(then_specs=p.get("then_specs")),
)
EffectRegistry.register(
    "grant_keywords_to_chosen_type_until_eot",  # Selfless Safewright
    lambda p: GrantKeywordsToChosenTypeUntilEotEffect(keywords=p.get("keywords")),
)
EffectRegistry.register(
    "grant_keyword_to_trigger_subject",  # Tyvar Kell's emblem
    lambda p: GrantKeywordToTriggerSubjectEffect(
        keyword=p.get("keyword", "haste"), event_key=p.get("event_key", "instance_id"),
    ),
)
EffectRegistry.register(
    "counter_untap_grant_keyword",  # Tyvar Kell's +1
    lambda p: CounterUntapGrantKeywordEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        optional=bool(p.get("optional", True)),
        creature_filter=p.get("creature_filter"),
        keyword=p.get("keyword", "deathtouch"),
    ),
)
EffectRegistry.register(
    "destroy_controller_may_search_basic_land",  # Boseiju, Who Endures
    lambda p: DestroyControllerMaySearchBasicLandEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "artifact_enchantment_or_nonbasic_land"),
        can_be_regenerated=bool(p.get("can_be_regenerated", True)),
    ),
)
EffectRegistry.register(
    "return_top_graveyard_creature_with_haste",  # Corpse Dance
    lambda p: ReturnTopGraveyardCreatureWithHasteEffect(
        delayed_exile_step=p.get("delayed_exile_step"),
    ),
)
EffectRegistry.register("peek_top_land_battlefield_tapped", lambda p: PeekTopLandBattlefieldTappedEffect())
EffectRegistry.register(
    "target_player_draw_lose_life",  # Sign in Blood
    lambda p: TargetPlayerDrawLoseLifeEffect(
        draw_count=p.get("draw_count", 1), life_loss=p.get("life_loss", 0),
        target=p.get("target"), target_kind=p.get("target_kind", "player"),
    ),
)
EffectRegistry.register(
    "add_counter_first_strike",  # The Wandering Emperor +1
    lambda p: CounterAndFirstStrikeEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "create_token_may_attach_equipment",  # Nahiri, Heir of the Ancients
    lambda p: CreateTokenMayAttachEquipmentEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "equipment_you_control"),
        optional=bool(p.get("optional", True)),
        token_name=p.get("token_name", "token"),
        power=p.get("power", 1),
        toughness=p.get("toughness", 1),
        colors=p.get("colors"),
        subtypes=p.get("subtypes"),
    ),
)
EffectRegistry.register(
    "return_to_hand",  # "return target X to its owner's hand" (RULE 701.3)
    lambda p: ReturnToHandEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        count_max=p.get("count_max"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        previous_subject=bool(p.get("previous_subject", False)),
        selector=p.get("selector"),
        filter=p.get("filter"),
        spell_or_permanent=bool(p.get("spell_or_permanent", False)),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    "return_to_library",  # "put target X on top/bottom of its owner's library" (RULE 701.3)
    lambda p: ReturnToLibraryEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        position=p.get("position", "top"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
    ),
)
EffectRegistry.register(
    # "Shuffle ~ into its owner's library." (Green Sun's Zenith)
    "shuffle_self_into_library",
    lambda p: ShuffleSelfIntoLibraryEffect(),
)
EffectRegistry.register(
    # "Put target permanent you own on the bottom of your library. Reveal
    # cards from the top of your library until you reveal a card that
    # shares a card type with that permanent…" (Reality Scramble)
    "return_to_library_then_dig_shared_type",
    lambda p: ReturnToLibraryThenDigSharedTypeEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent_you_control"),
    ),
)
EffectRegistry.register(
    # "An opponent gains control of ~." (Wishclaw Talisman)
    "gain_control_by_source",
    lambda p: GainControlBySourceEffect(recipient=p.get("recipient", "opponent")),
)
EffectRegistry.register(
    # "return target creature card from your graveyard to the battlefield/
    # your hand" (RULE 701.3, Regrowth/Reanimate-shaped)
    "return_from_graveyard",
    lambda p: ReturnFromGraveyardEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "graveyard_creature"),
        destination=p.get("destination", "battlefield"),
        under_your_control=bool(p.get("under_your_control", False)),
        optional=bool(p.get("optional", False)),
        lose_life_equal_mv=bool(p.get("lose_life_equal_mv", False)),
        count=p.get("count", 1),
        shuffle_after=bool(p.get("shuffle_after", False)),
        subtype=p.get("subtype"),
        max_mana_value=p.get("max_mana_value"),
        haste=bool(p.get("haste", False)),
        tapped=bool(p.get("tapped", False)),
        trigger_subject_key=p.get("trigger_subject_key"),
    ),
)
EffectRegistry.register(
    "add_mana",  # a spell's own bare "Add {B}{B}{B}." body (RULE 106.4, Dark Ritual)
    lambda p: AddManaEffect(
        colors=list(p.get("colors", [])),
        amount=p.get("amount"),
        color=p.get("color", "C"),
        amount_selector=p.get("amount_selector"),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
        recipient=p.get("recipient", "controller"),
        target_kind=p.get("target_kind"),
        amount_from_target_hand_size=bool(p.get("amount_from_target_hand_size", False)),
        amount_from_target_count_selector=p.get("amount_from_target_count_selector"),
        once_per_turn_ability=bool(p.get("once_per_turn_ability", False)),
        color_from_source_chosen_color=bool(p.get("color_from_source_chosen_color", False)),
        color_from_source_noted_color=bool(p.get("color_from_source_noted_color", False)),
        any_color_choices=p.get("any_color_choices"),
        any_amount_from_context=p.get("any_amount_from_context"),
    ),
)
EffectRegistry.register(
    # "Add one mana of any type that permanent produced." (Kinnan) — RULE
    # 605.1b triggered-mana-ability body; the type comes from the firing.
    "mirror_produced_mana",
    lambda p: MirrorProducedManaEffect(count=int(p.get("count", 1) or 1)),
)
EffectRegistry.register(
    # "Tap all lands that player controls that could produce any type of
    # mana that land could produce." (Mana Web)
    "tap_matching_lands",
    lambda p: TapMatchingLandsEffect(),
)
EffectRegistry.register(
    "create_delayed_trigger",  # RULE 603.7 "at the beginning of your next … , …"
    lambda p: CreateDelayedTriggerEffect(
        step=p.get("step", "upkeep"),
        effects=list(p.get("effects", [])),
        scope=p.get("scope", "controller"),
        capture=p.get("capture"),
        min_turn_offset=p.get("min_turn_offset", 0),
        description=p.get("description", ""),
    ),
)
EffectRegistry.register(
    # RULE 603.7-adjacent recurring player-scoped trigger (Nuka-Nuke
    # Launcher's "until the end of defending player's next turn, that
    # player gets rad counters whenever they cast a spell").
    "install_temporary_player_trigger",
    lambda p: InstallTemporaryPlayerTriggerEffect(
        event_type=p.get("event_type", "SPELL_CAST"),
        effects=list(p.get("effects", [])),
        description=p.get("description", ""),
    ),
)
EffectRegistry.register(
    # RULE 122/601.2b resolve-time optional energy payment (Aether Chaser —
    # "you may pay {E}{E}. If you do, create a 1/1 Servo").
    "pay_energy_then",
    lambda p: PayEnergyThenEffect(
        amount=p.get("amount", 0),
        effects=list(p.get("effects", [])),
    ),
)
EffectRegistry.register(
    # RULE 118.3 resolve-time optional payment, generalized past energy:
    # "you may pay <cost>. If you do, <effect>. [If you don't, <effect>.]"
    # (Mana Vault's upkeep untap, Wandering Archaic's per-opponent {2}).
    "pay_cost_then",
    lambda p: PayCostThenEffect(
        cost=p.get("cost", ""),
        effects=list(p.get("effects", [])),
        else_effects=list(p.get("else_effects", [])),
        payer=p.get("payer", "controller"),
        remember_trigger_subject=bool(p.get("remember_trigger_subject", False)),
    ),
)
EffectRegistry.register(
    # MEC-19: "counter it/that spell[or ability] unless that player/its
    # controller pays <cost>" — the un-keyworded-Ward-shaped trigger
    # resolution (EventType.BECOMES_TARGET).
    "counter_unless_pay",
    lambda p: CounterUnlessPayEffect(cost=p.get("cost", "")),
)
EffectRegistry.register(
    # RULE 118.3-adjacent multi-player tax: "Any player may pay <cost>. If
    # no one does, <effect>." (Rhystic Circle, MEC-30) — `pay_cost_then`'s
    # multi-player, aggregate-outcome sibling.
    "all_players_decline_or",
    lambda p: RequestAllPlayersDeclineOrEffect(
        cost=p.get("cost", ""),
        effects=list(p.get("effects", [])),
    ),
)
EffectRegistry.register(
    # RULE 301.5c: "attach target Equipment you control to target creature
    # you control" (Brass Squire, Halvar) — two independently-chosen targets
    # of different kinds in one clause.
    "attach_chosen",
    lambda p: AttachChosenEffect(
        what_kind=p.get("what_kind", "equipment_you_control"),
        to_kind=p.get("to_kind", "creature_you_control"),
    ),
)
EffectRegistry.register(
    # Archdruid's Charm's second mode — counter first, then damage equal to
    # the *boosted* power.
    "counter_then_fightlike_damage",
    lambda p: CounterThenFightlikeDamageEffect(
        counters=int(p.get("counters", 1) or 1), kind=p.get("kind", "+1/+1"),
    ),
)
EffectRegistry.register(
    # RULE 701.14 fight — "target creature you control fights target creature
    # you don't control" (Prey Upon), "it fights up to one target creature you
    # don't control" (Kogla's ETB, ``fighter_kind=None``).
    "fight",
    lambda p: FightEffect(
        fighter_kind=p.get("fighter_kind"),
        other_kind=p.get("other_kind", "creature"),
        fighter_optional=bool(p.get("fighter_optional", False)),
        optional=bool(p.get("optional", False)),
        distinct=bool(p.get("distinct", False)),
    ),
)
EffectRegistry.register(
    # The one-sided fight — "target creature you control deals damage equal to
    # its power to target creature you don't control" (Rabid Bite), "when ~
    # dies, it deals damage equal to its power to any target".
    "damage_equal_to_power",
    lambda p: DamageEqualToPowerEffect(
        dealer_kind=p.get("dealer_kind"),
        target_kind=p.get("target_kind", "any"),
        selector=p.get("selector"),
        dealer_optional=bool(p.get("dealer_optional", False)),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    # "~ deals damage equal to the number of +1/+1 counters on it to any
    # other target." (Red Hulk) — `damage_equal_to_power`'s counter-count
    # sibling.
    "damage_equal_to_counters",
    lambda p: DamageEqualToCountersEffect(
        kind=p.get("kind", "+1/+1"),
        target_kind=p.get("target_kind", "any"),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    # RULE 601.2c target announcement with no effect of its own — "choose
    # target creature you control and target creature you don't control."
    "choose_targets",
    lambda p: ChooseTargetsEffect(
        kinds=list(p.get("kinds", []) or []),
        count=p.get("count"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    # "Destroy each artifact with mana value X." (Dauntless Dismantler)
    "destroy_each_with_mana_value",
    lambda p: DestroyEachWithManaValueEffect(
        amount=p.get("amount", 0), card_type=p.get("card_type", "artifact"),
    ),
)
EffectRegistry.register(
    # RULE 701.17: "each opponent sacrifices a creature with the greatest
    # power among creatures that player controls" (Professor Onyx's −3).
    # Previously only reachable from the annihilator keyword, never the
    # registry.
    "sacrifice",
    lambda p: SacrificeEffect(
        count=p.get("count", 1) if p.get("count") == "all_but_one" else int(p.get("count", 1) or 1),
        what=p.get("what", "permanent"),
        selector=p.get("selector"),
        greatest_power=bool(p.get("greatest_power", False)),
    ),
)
EffectRegistry.register(
    # "Sacrifice it at the beginning of the next end step." (Kiki-Jiki,
    # Mirror Breaker-shaped) — the ``objects`` list is never real
    # card-text data (an empty default here), only ever populated by
    # `CreateDelayedTriggerEffect`'s own ``capture="created_objects"``
    # mutating the constructed effect directly, the same "capture a
    # resolve-time fact the delayed firing can't see anymore" idiom
    # ``target_mana_value``/``target_controller`` use.
    "sacrifice_specific",
    lambda p: SacrificeSpecificEffect(objects=[]),
)
EffectRegistry.register(
    # "Exile those tokens at the beginning of the next end step." (Twinflame-
    # shaped, MEC-12) — the plural sibling of `sacrifice_specific` just
    # above, same "empty default, only ever populated by `CreateDelayedTrigger
    # Effect`'s own `capture='created_objects'`" idiom.
    "exile_specific",
    lambda p: ExileSpecificEffect(objects=[]),
)
EffectRegistry.register(
    # "When this Aura leaves the battlefield, that creature's controller
    # sacrifices it." (MEC-34, Animate Dead/Necromancy) — no params at all,
    # reads `self.source.attached_to` live at resolution.
    "sacrifice_attached_permanent",
    lambda p: SacrificeAttachedPermanentEffect(),
)
EffectRegistry.register(
    # "Each opponent may discard a card. If they don't, they lose N life.
    # Repeat this process M more times." (Professor Onyx's −8)
    "discard_or_lose_life",
    lambda p: DiscardOrLoseLifeEffect(
        count=int(p.get("count", 1) or 1),
        amount=int(p.get("amount", 3) or 3),
        times=int(p.get("times", 1) or 1),
        selector=p.get("selector", "each_opponent"),
        round_index=int(p.get("round_index", 0) or 0),
        player_index=int(p.get("player_index", 0) or 0),
    ),
)
EffectRegistry.register(
    # RULE 903.3/110.2: "gain control of all commanders; put all commanders
    # from the command zone onto the battlefield under your control."
    # (Tevesh Szat, Doom of Fools' −10)
    "gain_control_of_all_commanders",
    lambda p: GainControlOfAllCommandersEffect(),
)
EffectRegistry.register(
    # RULE 616.1, scoped to one source / combat only / your opponents, and
    # duration-bounded (Jeska, Thrice Reborn's 0).
    "multiply_damage_from_target",
    lambda p: MultiplyDamageFromTargetEffect(
        multiplier=int(p.get("multiplier", 2) or 2),
        combat_only=bool(p.get("combat_only", True)),
        to=p.get("to", "opponents"),
    ),
)
EffectRegistry.register(
    "untap_self",  # "Untap this permanent." (Mana Vault)
    lambda p: UntapSelfEffect(),
)
EffectRegistry.register(
    # RULE 702.32b Fading / 702.61b Vanishing: "remove a counter … if you
    # can't, sacrifice it."
    "remove_counter_or_sacrifice",
    lambda p: RemoveCounterOrSacrificeEffect(kind=p.get("kind", "fade")),
)
EffectRegistry.register(
    # RULE 702.24b Cumulative Upkeep: "put an age counter … then sacrifice
    # unless you pay the upkeep cost for each age counter on it." (MEC-16)
    "cumulative_upkeep",
    lambda p: CumulativeUpkeepEffect(cost=p.get("cost", "")),
)
EffectRegistry.register(
    # "That player taps an untapped artifact, creature, or land they control
    # for each fade counter on this artifact." (Tangle Wire)
    "tap_permanents_per_counter",
    lambda p: TapPermanentsPerCounterEffect(
        kind=p.get("kind", "fade"), types=p.get("types"),
    ),
)
EffectRegistry.register(
    "mutate",  # RULE 702.140b merge (Lore Drakkis)
    lambda p: MutateEffect(
        target_kind=p.get("target_kind", "non_human_creature_you_own"),
    ),
)
EffectRegistry.register(
    "name_card_then",  # "Choose a card name. <effect>" (Demonic Consultation)
    lambda p: NameCardThenEffect(effects=list(p.get("effects", []))),
)
EffectRegistry.register(
    # "Exile the top card of your library. You may put that card into your
    # hand unless it has the same name as another card exiled this way.
    # Repeat…" (Tainted Pact).
    "exile_until_duplicate_name",
    lambda p: ExileUntilDuplicateNameEffect(),
)
EffectRegistry.register(
    # "Sacrifice an artifact. If you do, search your library for an
    # artifact card…" (Transmute Artifact).
    "transmute_artifact",
    lambda p: TransmuteArtifactEffect(),
)
EffectRegistry.register(
    # "…reveal/exile cards from the top of your library until <predicate>"
    # — the parameterized form of the cascade/discover dig.
    "dig_until",
    lambda p: DigUntilEffect(
        criteria=p.get("criteria", ""),
        hit_destination=p.get("hit_destination", "hand"),
        rest_destination=p.get("rest_destination", "exile"),
        pre_exile=int(p.get("pre_exile", 0) or 0),
    ),
)
EffectRegistry.register(
    # "…mills a card, then repeats this process until a creature card or X
    # cards…" (Helm of Obedience) — the first repeat-until-predicate loop.
    "mill_until_creature",
    lambda p: MillUntilCreatureEffect(
        amount=p.get("amount", 0), target_kind=p.get("target_kind", "player"),
    ),
)
EffectRegistry.register(
    # Possibility Storm / Tibalt's Trickery: answer a spell, then dig its
    # *controller's* library for a replacement they may cast for free.
    "scramble_spell",
    lambda p: ScrambleSpellEffect(
        answer=p.get("answer", "counter"),
        match=p.get("match", "different_name"),
        mill_random_max=int(p.get("mill_random_max", 0) or 0),
        card_types=p.get("card_types"),
    ),
)
EffectRegistry.register(
    # "As many times as you choose, you may pay 1 life…" (Lim-Dûl's Vault)
    "look_top_pay_life_loop",
    lambda p: LookTopPayLifeLoopEffect(
        count=int(p.get("count", 5) or 5), life_cost=int(p.get("life_cost", 1) or 1),
    ),
)
EffectRegistry.register(
    # "Reveal the top card of your library and put that card into your
    # hand. You lose life equal to its mana value. You may repeat this
    # process any number of times." (Ad Nauseam, MEC-41)
    "reveal_top_hand_lose_life_loop",
    lambda p: RevealTopHandLoseLifeLoopEffect(),
)
EffectRegistry.register(
    # RULE 108.4/701.10: "exchange control of ~ and up to one target
    # creature an opponent controls" (Gilded Drake) — a genuine two-way
    # swap, not a one-way grab.
    "exchange_control",
    lambda p: ExchangeControlEffect(
        target_kind=p.get("target_kind", "creature"),
        sacrifice_self_if_no_exchange=bool(p.get("sacrifice_self_if_no_exchange", False)),
    ),
)
EffectRegistry.register(
    # RULE 702.26b + 611.2b: "all permanents you control phase out", plus
    # the life lock and protection from everything (Teferi's Protection).
    "phase_out_all_you_control",
    lambda p: PhaseOutAllYouControlEffect(),
)
EffectRegistry.register(
    # RULE 707.10 + 400.1: "copy target instant or sorcery spell, then
    # return it to its owner's hand" (Narset's Reversal).
    "copy_spell_and_bounce",
    lambda p: CopySpellAndBounceEffect(card_types=p.get("card_types")),
)
EffectRegistry.register(
    # "return another permanent you control that shares a permanent type
    # with it to its owner's hand" (Cloudstone Curio).
    "return_shared_type_permanent",
    lambda p: ReturnSharedTypePermanentEffect(),
)
EffectRegistry.register(
    # "Whenever this creature deals combat damage to a creature, exile that
    # creature." (Kaldra Compleat's granted ability) — see
    # `ExileTriggerDamagedCreatureEffect`.
    "exile_trigger_damaged_creature",
    lambda p: ExileTriggerDamagedCreatureEffect(),
)
EffectRegistry.register(
    # "Put up to N <criteria> cards from your hand onto the battlefield."
    # (Tooth and Nail's second mode) — a pick from *hand*, unlike every
    # other "put onto the battlefield" (library/graveyard).
    "put_from_hand_onto_battlefield",
    lambda p: PutFromHandOntoBattlefieldEffect(
        criteria=p.get("criteria", p.get("type", "")),
        count=int(p.get("count", 1) or 1),
        tapped=bool(p.get("tapped", False)),
    ),
)
EffectRegistry.register("take_extra_turn", lambda p: TakeExtraTurnEffect())
EffectRegistry.register(
    "extra_combat_phase",
    lambda p: ExtraCombatPhaseEffect(main_phase_too=bool(p.get("main_phase_too", False))),
)
EffectRegistry.register(
    # "You may sacrifice/tap/return a <kind> you control." — the player
    # picks which; see `RulesEngine.request_choose_objects`.
    "choose_objects",
    lambda p: ChooseObjectsEffect(
        action=str(p.get("action", "sacrifice")),
        what=str(p.get("what", "permanent")),
        count=int(p.get("count", 1) or 1),
        optional=bool(p.get("optional", False)),
        exclude_self=bool(p.get("exclude_self", False)),
        prompt=str(p.get("prompt", "")),
        then=p.get("then"),
        then_if_commander=p.get("then_if_commander"),
    ),
)
EffectRegistry.register(
    "the_ring_tempts_you",  # RULE 701.51a
    lambda p: TheRingTemptsYouEffect(),
)
EffectRegistry.register(
    "cast_exiled_face_down",  # Beseech the Mirror (RULE 701.20a)
    lambda p: CastExiledFaceDownEffect(
        max_mana_value=p.get("max_mana_value"),
        require_bargained=p.get("require_bargained", False),
    ),
)
EffectRegistry.register(
    "cheat_creature_from_hand",  # Sneak Attack/Meek Attack
    lambda p: CheatCreatureFromHandEffect(max_total_pt=p.get("max_total_pt")),
)
EffectRegistry.register(
    "grant_protection",
    lambda p: GrantProtectionEffect(
        target_kind=p.get("target_kind", "creature_you_control"),
        allow_colorless=bool(p.get("allow_colorless", False)),
    ),
)
EffectRegistry.register(
    "grant_cant_be_target_of_spell_color",
    lambda p: GrantCantBeTargetOfSpellColorEffect(
        colors=p.get("colors"), selector=p.get("selector", "creatures_you_control"),
    ),
)
EffectRegistry.register(
    "lose_game", lambda p: LoseGameEffect(reason=p.get("reason", "effect"))
)
EffectRegistry.register(
    "lose_game_trigger_damaged_player",
    lambda p: LoseGameTriggerDamagedPlayerEffect(reason=p.get("reason", "effect")),
)
EffectRegistry.register(
    "blink",  # "Exile target permanent, then return it to the battlefield" (Ephemerate)
    lambda p: BlinkEffect(
        target_kind=p.get("target_kind", "creature_you_control"),
        under_your_control=bool(p.get("under_your_control", False)),
        creature_filter=p.get("creature_filter"),
        optional=bool(p.get("optional", False)),
        count=p.get("target_count", 1),
        count_max=p.get("target_count_max"),
    ),
)
EffectRegistry.register(
    "tap",
    lambda p: TapEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        untap=bool(p.get("untap", False)),
        optional=bool(p.get("optional", False)),
        selector=p.get("selector"),
        count=int(p.get("count", 1)),
        count_max=p.get("count_max"),
        previous_subject=bool(p.get("previous_subject", False)),
        trigger_event_key=p.get("trigger_event_key"),
        creature_filter=p.get("creature_filter"),
        subtypes=p.get("subtypes"),
        choose_tap_or_untap=bool(p.get("choose_tap_or_untap", False)),
    ),
)
EffectRegistry.register(
    "unblockable",  # "Target creature can't be blocked this turn" (Rogue's Passage)
    lambda p: UnblockableEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    # "Target creature can't block this turn" (Falter/Abandon the Post) and
    # "creatures your opponents control can't block this turn" (the mass
    # form) — the blocker-side mirror of "unblockable" just above.
    "cant_block_this_turn",
    lambda p: CantBlockEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        selector=p.get("selector"),
        filter=dict(p.get("filter") or {}),
        count=int(p.get("count", 1)),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    # "~ can't be blocked by creatures with power 2 or less this turn"
    # (Cavern Stomper) — the resolve-time sibling of the standing
    # `combat_restriction` static registered further down.
    "combat_restriction_this_turn",
    lambda p: GrantCombatRestrictionEffect(
        restriction=dict(p.get("restriction") or {}),
        target=p.get("target"),
        target_kind=p.get("target_kind"),
        restrict_to_source=bool(p.get("restrict_to_source", False)),
    ),
)
EffectRegistry.register(
    "attach",
    lambda p: AttachEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
    ),
)
EffectRegistry.register(
    # "…it becomes an Aura with '<quoted enchant text>.'" (RULE 305.1c/
    # 303.4f, MEC-44 — Necromancy) — see `BecomeAuraEffect`.
    "become_aura",
    lambda p: BecomeAuraEffect(quality=p.get("quality", "creature")),
)
EffectRegistry.register(
    # "Whenever a[n] <X> you control enters, you may attach it to target
    # creature you control." (Sigarda's Aid) — the mover is the trigger
    # event's own subject, not a chosen target; see
    # `AttachTriggeringPermanentEffect`.
    "attach_triggering_permanent",
    lambda p: AttachTriggeringPermanentEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature_you_control"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "unattach_tap_indestructible",  # Akiri, Fearless Voyager
    lambda p: UnattachTapIndestructibleEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "attached_equipment_you_control"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "return_creature_grant_indestructible",  # Temur Sabertooth
    lambda p: ReturnCreatureGrantIndestructibleEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature_you_control"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "enter_as_copy",  # "You may have this enter as a copy of target X" (RULE 614.1c/614.12)
    lambda p: EnterAsCopyReplacement(
        target_kind=p.get("target_kind", "permanent"),
        add_types=list(p.get("add_types", [])),
        add_subtypes=list(p.get("add_subtypes", [])),
        optional=bool(p.get("optional", True)),
        extra_counter_if_creature=p.get("extra_counter_if_creature"),
        extra_counter_if_planeswalker=p.get("extra_counter_if_planeswalker"),
        grant_mana_option=p.get("grant_mana_option"),
        only_types=p.get("only_types"),
        add_keywords=p.get("add_keywords"),
        add_keywords_if_target_lacks=p.get("add_keywords_if_target_lacks"),
        keep_own_abilities=bool(p.get("keep_own_abilities", False)),
        max_mana_value_from_mana_spent=bool(p.get("max_mana_value_from_mana_spent", False)),
    ),
)
EffectRegistry.register(
    "choose_creature_type_on_enter",  # "As ~ enters, choose a creature type." (RULE 601.2b)
    lambda p: ChooseCreatureTypeReplacement(),
)
EffectRegistry.register(
    "choose_color_on_enter",  # "As ~ enters, choose a color." (RULE 601.2b)
    lambda p: ChooseColorReplacement(),
)
EffectRegistry.register(
    "choose_basic_land_type_on_enter",  # "As ~ enters, choose a basic land type." (RULE 601.2b, PAR-4)
    lambda p: ChooseBasicLandTypeReplacement(),
)
EffectRegistry.register(
    # "As ~ enters the battlefield, choose a card name." (MEC-12, Pithing
    # Needle/Phyrexian Revoker-shaped) — hand-authored only, no oracle-text
    # grammar yet.
    "choose_card_name_on_enter",
    lambda p: ChooseCardNameReplacement(),
)
EffectRegistry.register(
    # "As this enters, choose <Label1> or <Label2>." (Struggle for Project
    # Purity-shaped) — hand-authored only, no oracle-text grammar yet.
    "choose_named_mode",
    lambda p: ChooseNamedModeReplacement(options=list(p.get("options", []))),
)
EffectRegistry.register(
    # "As this creature enters, choose a number." (Sanctum Prelate, MEC-43)
    # — hand-authored only, no oracle-text grammar yet.
    "choose_number_on_enter",
    lambda p: ChooseNumberReplacement(),
)
EffectRegistry.register(
    "become_copy_until_eot",  # "~ becomes a copy of target creature until end of turn" (Cursed Mirror)
    lambda p: BecomeCopyUntilEndOfTurnEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "set_copy_target",  # Vesuvan Shapeshifter's "you may have it be a copy of another target creature"
    lambda p: SetCopyTargetEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "conditional_copy",  # RULE 707/613 layer 1 — "as long as [condition], ~ is a copy of [target]"
    lambda p: StaticAbility(
        "copy",
        affects="self",
        params={
            "requires_untapped": bool(p.get("requires_untapped", False)),
            "add_types": list(p.get("add_types", [])),
            "add_subtypes": list(p.get("add_subtypes", [])),
        },
    ),
)
EffectRegistry.register(
    "text_change",  # RULE 612 layer 3 — word-substitution over effective_oracle_text
    lambda p: StaticAbility(
        "text",
        affects=p.get("affects", "self"),
        params={"replace": {str(k): str(v) for k, v in dict(p.get("replace", {})).items()}},
    ),
)
EffectRegistry.register(
    "add_counters",
    lambda p: AddCountersEffect(
        amount=p.get("amount", p.get("count", 1)),
        target_kind=p.get("target_kind"),
        kind=p.get("kind", "+1/+1"),
        optional=bool(p.get("optional", False)),
        selector=p.get("selector"),
        trigger_subject_key=p.get("trigger_subject_key"),
        # A distinct key from "count"/"amount" (both already the *counter*
        # amount per card) — this is the *target* count (RULE 115.1a N>=2,
        # "put a counter on each of up to two target creatures").
        count=p.get("target_count", 1),
        # ENG-30: "1 or 2" range ceiling — see `target_count`'s own comment.
        count_max=p.get("target_count_max"),
        subtypes=p.get("subtypes"),
        divided=bool(p.get("divided", False)),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
        x_multiplier=p.get("x_multiplier"),
        amount_from_count_selector=p.get("amount_from_count_selector"),
        amount_if_trigger_subject_subtype=p.get("amount_if_trigger_subject_subtype"),
        amount_if_trigger_subject_subtype_value=p.get("amount_if_trigger_subject_subtype_value"),
    ),
)
EffectRegistry.register(
    "class_level",  # RULE 716.2c: activating "Level N: <cost>" sets class level to N
    lambda p: ClassLevelEffect(level=p.get("level", 1)),
)
EffectRegistry.register(
    "pump",  # "target creature gets +N/+N (and gains <kw>) until end of turn"
    lambda p: PumpEffect(
        power=p.get("power", 0),
        toughness=p.get("toughness", 0),
        keywords=list(p.get("keywords", [])),
        target_kind=p.get("target_kind"),
        selector=p.get("selector"),
        unblockable=bool(p.get("unblockable", False)),
        count=p.get("target_count", 1),
        count_max=p.get("target_count_max"),
        optional=bool(p.get("optional", False)),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
        per_recipient_controller_counter=p.get("per_recipient_controller_counter"),
        amount_from_count_selector=p.get("amount_from_count_selector"),
        amount_from_count_selector_negative=bool(p.get("amount_from_count_selector_negative", False)),
        creature_filter=p.get("creature_filter"),
        previous_subject=bool(p.get("previous_subject", False)),
        subtypes=p.get("subtypes"),
    ),
)
EffectRegistry.register(
    "scry", lambda p: ScryEffect(count=p.get("count", p.get("amount", 1)))
)
EffectRegistry.register(
    "surveil", lambda p: SurveilEffect(count=p.get("count", p.get("amount", 1)))
)
EffectRegistry.register(
    "look_top_select",
    lambda p: LookTopSelectEffect(
        count=p.get("count", 1),
        select_count=p.get("select_count", 1),
        rest_destination=p.get("rest_destination", "library_bottom"),
        rest_order=p.get("rest_order"),
    ),
)
EffectRegistry.register(
    # RULE 701.40a manifest / RULE 701.58a cloak — one effect, one ``kind``
    # param (see `ManifestEffect`).
    "manifest",
    lambda p: ManifestEffect(
        count=p.get("count", p.get("amount", 1)), kind=p.get("kind", "manifest")
    ),
)
EffectRegistry.register("manifest_dread", lambda p: ManifestDreadEffect())
EffectRegistry.register(
    "top_library_permission",
    lambda p: TopLibraryPermissionEffect(
        look=p.get("look", False),
        play_lands=p.get("play_lands", False),
        cast_spells=p.get("cast_spells", False),
        min_mana_value=p.get("min_mana_value"),
        requires_attached=p.get("requires_attached", False),
        noncreature_only=p.get("noncreature_only", False),
        grants_flash=p.get("grants_flash", False),
        life_payment=p.get("life_payment", False),
        chosen_type_creature_only=p.get("chosen_type_creature_only", False),
        creature_only=bool(p.get("creature_only", False)),
        subtypes=p.get("subtypes"),
    ),
)
EffectRegistry.register(
    "graveyard_cast_permission",
    lambda p: GraveyardCastPermissionEffect(
        max_mana_value=p.get("max_mana_value"),
        permanent_only=p.get("permanent_only", True),
        once_per_turn=p.get("once_per_turn", True),
        exile_if_would_be_put_into_graveyard=p.get("exile_if_would_be_put_into_graveyard", False),
    ),
)
EffectRegistry.register(
    "self_graveyard_or_exile_cast_permission",
    lambda p: SelfGraveyardOrExileCastPermissionEffect(),
)
EffectRegistry.register(
    "create_token",
    lambda p: CreateTokenEffect(
        count=p.get("count", 1),
        token_name=p.get("token_name"),
        power=p.get("power"),
        toughness=p.get("toughness"),
        colors=list(p.get("colors", [])),
        subtypes=list(p.get("subtypes", [])),
        keywords=list(p.get("keywords", [])),
        count_selector=p.get("count_selector"),
        creators=p.get("creators", "you"),
        tapped=bool(p.get("tapped", False)),
        legendary=bool(p.get("legendary", False)),
        pt_from_trigger_event=p.get("pt_from_trigger_event"),
        count_from_trigger_event=p.get("count_from_trigger_event"),
        extra_counters=p.get("extra_counters"),
        grant_self_anthem=p.get("grant_self_anthem"),
        is_artifact=bool(p.get("is_artifact", False)),
    ),
)
EffectRegistry.register(
    "pay_life_equal_to_opponents_combat_damaged_draw_that_many",
    lambda p: PayLifeEqualToOpponentsCombatDamagedDrawThatManyEffect(),
)
EffectRegistry.register(
    "amass",  # RULE 701.48 "Amass <Type> N" (Orcish Bowmasters, MEC-42)
    lambda p: AmassEffect(subtype=p.get("subtype", "Zombies"), count=int(p.get("count", 1))),
)
EffectRegistry.register(
    "copy_permanent",  # "Create a token that's a copy of target creature" (RULE 707)
    lambda p: CopyPermanentEffect(
        count=p.get("count", 1),
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        count_if_kicked=p.get("count_if_kicked"),
        count_from_trigger_event=p.get("count_from_trigger_event"),
        haste=bool(p.get("haste", False)),
        add_types=p.get("add_types"),
        add_subtypes=p.get("add_subtypes"),
        not_legendary=bool(p.get("not_legendary", False)),
        referent=p.get("referent", "source"),
        target_count=int(p.get("target_count", 1) or 1),
        target_count_max=p.get("target_count_max"),
        target_optional=bool(p.get("target_optional", False)),
        set_power=p.get("set_power"),
        set_toughness=p.get("set_toughness"),
        extra_temp_keywords=p.get("extra_temp_keywords"),
    ),
)
EffectRegistry.register(
    "intuition_search",
    lambda p: IntuitionEffect(
        count=p.get("count", 3),
        search_optional=bool(p.get("search_optional", False)),
        distinct_names=bool(p.get("distinct_names", False)),
        chosen_count=p.get("chosen_count", 1),
        chosen_destination=p.get("chosen_destination", "hand"),
        rest_destination=p.get("rest_destination", "graveyard"),
    ),
)
EffectRegistry.register(
    "search",
    lambda p: SearchLibraryEffect(
        # "criteria" is the general form; "type" stays a shorthand for a
        # type-line restriction so an oracle handler can emit either.
        criteria=p.get("criteria", p.get("type", "")),
        destination=p.get("destination", "hand"),
        count=p.get("count", 1),
        optional=p.get("optional", True),
        player=p.get("player"),
        zones=p.get("zones"),
        destinations=p.get("destinations"),
        destination_if=p.get("destination_if"),
        exile_rest=p.get("exile_rest", False),
        mana_value_from=p.get("mana_value_from"),
        extra_counters=p.get("extra_counters"),
        attach_to_creature_you_control=bool(p.get("attach_to_creature_you_control", False)),
        remember=bool(p.get("remember", False)),
        total_mana_value_budget=p.get("total_mana_value_budget"),
        player_from_target=bool(p.get("player_from_target", False)),
        share_land_type=bool(p.get("share_land_type", False)),
    ),
)
EffectRegistry.register(
    "impulsive_look",
    lambda p: ImpulsiveLookEffect(
        count=p.get("count", 1),
        criteria=p.get("criteria", ""),
        hit_destination=p.get("hit_destination", "hand"),
        miss_destination=p.get("miss_destination", "graveyard"),
        optional=p.get("optional", True),
    ),
)
EffectRegistry.register(
    "impulsive_draw",
    lambda p: ImpulsiveDrawEffect(
        count=p.get("count", 1), same_turn_only=bool(p.get("same_turn_only", False)),
        count_from_trigger_event=p.get("count_from_trigger_event"),
    ),
)
EffectRegistry.register(
    "draw_reveal_cast_one_free",
    lambda p: DrawRevealCastOneFreeEffect(count=p.get("count", 1)),
)
EffectRegistry.register(
    "reveal_top_then_free_cast_if_mv_match",
    lambda p: RevealTopThenFreeCastIfMVMatchEffect(),
)
EffectRegistry.register(
    "reveal_top_then_counter_if_mv_match",
    lambda p: RevealTopThenCounterIfMVMatchEffect(),
)
EffectRegistry.register(
    "exile_opponents_graveyards_impulsive_cast",  # Mnemonic Betrayal
    lambda p: GraveyardImpulsiveCastEffect(mana_wildcard=p.get("mana_wildcard", "type")),
)
EffectRegistry.register("shuffle", lambda p: ShuffleLibraryEffect())
EffectRegistry.register(
    "wheel",  # "Each player shuffles their hand and graveyard into their library, then draws seven cards." (Timetwister)
    lambda p: WheelEffect(draw_count=p.get("draw_count", p.get("count", 7))),
)
EffectRegistry.register(
    "windfall",  # "Each player discards their hand, then draws cards equal to the greatest number discarded." (Windfall)
    lambda p: WindfallEffect(),
)
EffectRegistry.register(
    "wheel_of_fortune",  # "Each player discards their hand, then draws seven cards." (Wheel of Fortune)
    lambda p: WheelOfFortuneEffect(draw_count=p.get("draw_count", 7)),
)
EffectRegistry.register(
    "transform", lambda p: TransformEffect(target_kind=p.get("target_kind"))
)
EffectRegistry.register(
    # "Look at the top card of your library. If it's a[n] <type> card,
    # transform ~." (Delver of Secrets-shaped).
    "reveal_top_then_transform",
    lambda p: RevealTopThenTransformEffect(criteria=p.get("criteria", "")),
)
EffectRegistry.register(
    "exile_return_transformed", lambda p: ExileReturnTransformedEffect()
)
EffectRegistry.register(
    "coin_flip",
    lambda p: CoinFlipEffect(
        win_effects=p.get("win_effects"), lose_effects=p.get("lose_effects"),
    ),
)
EffectRegistry.register(
    "return_from_graveyard_transformed", lambda p: ReturnFromGraveyardTransformedEffect()
)
EffectRegistry.register(
    # "Return this card from your graveyard to the battlefield[, tapped]."
    # (Dread Wanderer/Bloodsoaked Champion/Drownyard Temple &c) — the plain
    # sibling of `return_from_graveyard_transformed` above.
    "return_self_from_graveyard",
    lambda p: ReturnSelfFromGraveyardToBattlefieldEffect(tapped=bool(p.get("tapped", False))),
)
EffectRegistry.register(
    # "…that creature gains 'when this creature dies, return it to the
    # battlefield tapped under its owner's control.'" (Malakir Rebirth's
    # granted death-return, temporary — unlike `return_self_from_graveyard`
    # above, which is a printed permanent's own standing ability) — the
    # untargeted, self-acting sibling of `return_from_graveyard`.
    "return_self_from_graveyard_untargeted",
    lambda p: ReturnSelfFromGraveyardEffect(
        destination=p.get("destination", "hand"),
        tapped=bool(p.get("tapped", False)),
        under_your_control=bool(p.get("under_your_control", False)),
        transformed=bool(p.get("transformed", False)),
    ),
)
EffectRegistry.register(
    # "Return this card from your graveyard to your hand." (PAR-16 —
    # Abzan Devotee/Aurora Eidolon &c) — the hand-destination sibling of
    # `return_self_from_graveyard` right above.
    "return_self_from_graveyard_to_hand",
    lambda p: ReturnSelfFromGraveyardToHandEffect(),
)
EffectRegistry.register(
    # "{N}: Put this card from your hand onto the battlefield." (Talon
    # Gates of Madara-shaped).
    "put_self_onto_battlefield_from_hand",
    lambda p: PutSelfOntoBattlefieldFromHandEffect(),
)
EffectRegistry.register(
    # "return it to the battlefield. It's a[n] <type> with '<ability>'. ~
    # loses all other abilities." (Harold and Bob, First Numens) —
    # hand-authored only, no oracle-text grammar for this shape yet.
    "return_dies_as_new_permanent",
    lambda p: ReturnDiesAsNewPermanentEffect(
        new_type_line=p.get("new_type_line", ""),
        new_oracle_text=p.get("new_oracle_text", ""),
        target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register("become_prepared", lambda p: BecomePreparedEffect())
EffectRegistry.register(
    "phase_out",
    lambda p: PhaseOutEffect(
        target_kind=p.get("target_kind"),
        optional=bool(p.get("optional", False)),
        previous_subject=bool(p.get("previous_subject", False)),
        self_target=bool(p.get("self_target", False)),
        count=int(p.get("count", 1)),
        count_selector=p.get("count_selector"),
    ),
)
EffectRegistry.register("cascade", lambda p: CascadeEffect(mana_value=p.get("mana_value")))
EffectRegistry.register("proliferate", lambda p: ProliferateEffect(times=p.get("times", 1)))
EffectRegistry.register(
    # "remove all counters from target permanent" / "remove all counters
    # from all permanents" (RULE 122 — Vampire Hexmage/Oblivion Stone/
    # Aether Snap/Thief of Blood-shaped); no ``target_kind`` = untargeted,
    # board-wide. ``max_count`` (Glissa Sunslayer/Heartless Act/Render
    # Inert-shaped "remove up to N counters") switches to the interactive
    # chosen-amount shape instead — see `RemoveCountersEffect`.
    "remove_counters",
    lambda p: RemoveCountersEffect(target_kind=p.get("target_kind"), max_count=p.get("max_count")),
)
EffectRegistry.register(
    "discover",
    lambda p: DiscoverEffect(mana_value=p.get("mana_value", p.get("amount", 0))),
)

# Static abilities applied through the layer system (RULE 613). Each becomes a
# `StaticAbility`; `game/continuous.py` folds them into derived characteristics.

#: The extra selector filters a static ability may narrow its `affects` set by —
#: a tribal subtype, tokens-only, a colour, "other" (exclude the source), or a
#: RULE 613.6-style "as long as this source's own <counter> is in range"
#: conditional gate (`min_level`/`max_level`/`level_counter` — Leveler tiers,
#: RULE 711, and cumulative Class levels, RULE 716). `continuous.
#: affected_objects`/`group_selector_objects` read these; only the non-
#: ``None`` ones are carried so a filter is off unless the parser/author set it.
_SELECTOR_KEYS: tuple[str, ...] = (
    "subtype", "tokens", "color", "exclude_self",
    "min_level", "max_level", "level_counter",
    # "During your turn, …" (Nahiri, Storm of Stone).
    "active_player_only",
    # Metalcraft-style "as long as you control N or more <count_selector>"
    # (Indomitable Archangel).
    "min_count_selector", "min_count",
    # A printed-card-type filter ("Artifacts your opponents control enter
    # tapped.", "Nonbasic lands are Mountains.") and its "nonbasic" qualifier
    # — `continuous._has_card_type`/the "basic" substring check.
    "card_type", "nonbasic",
    # RULE 601.2b "… of the chosen type/color …" (Adaptive Automaton/Caged
    # Sun-shaped) — read the ability source's own `chosen_type`/
    # `chosen_color` fresh each recompute instead of a literal `subtype`/
    # `color` baked in at parse time; see `continuous.group_selector_objects`.
    "subtype_from_source", "color_from_source",
    # "Activated abilities of permanents/sources **with the chosen name**
    # can't be activated …" (MEC-12, Pithing Needle/Phyrexian Revoker) — the
    # naming-choice sibling of `subtype_from_source`/`color_from_source`,
    # reading the ability source's own `chosen_card_name` fresh each
    # recompute instead of a literal baked in at parse time.
    "card_name_from_source",
    # A per-object power/toughness qualifier on the scope itself ("Each
    # creature you control **with power 4 or greater** …" — Challenger
    # Troll/Flopsie-shaped); read off each affected object's own *derived*
    # characteristics, unlike every filter above (all about type/colour).
    "min_power", "max_power", "min_toughness", "max_toughness",
    # The same qualifier with a *dynamic* threshold instead of a literal
    # ("Creatures your opponents control with power less than ~'s power are
    # goaded." — Baeloth Barrityl): `continuous.dynamic_threshold`'s
    # vocabulary, strict `<`/`>` to match the printed "less/greater than".
    "power_lt_selector", "power_gt_selector",
    # RULE 613.6's general "as long as <condition>" gate — one whitelisted
    # dict from `game/static_conditions.py`, evaluated live every recompute
    # (`continuous.group_selector_objects`). The three older gates above
    # (`active_player_only`, `min_level`/`max_level`, `min_count_selector`/
    # `min_count`) are the same idea per-card, and are translated into this
    # vocabulary rather than evaluated separately.
    "active_if",
    # RULE 112.7a's printed exception — "As long as this card is in your
    # graveyard, …" (Anger-shaped) — read by `continuous.
    # _battlefield_static_abilities`'s separate graveyard scan, which is
    # also what makes the *source's own zone* gate correct here: nothing
    # else about this static changes, only where it's looked for.
    "from_graveyard",
)


def _selectors(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in _SELECTOR_KEYS if p.get(k) is not None}


EffectRegistry.register(
    "anthem",  # "Creatures you control get +N/+N" (layer 7c); tribal/colour-scoped
    lambda p: StaticAbility(
        "pt_mod",
        affects=p.get("affects", "other_creatures_you_control"),
        params={
            "power": p.get("power", 0), "toughness": p.get("toughness", 0),
            # A per-count anthem ("+1/+1 for each land you control") — see
            # `continuous._pt_mod_count` for the selector vocabulary
            # (controller-scoped `count_selector` names, plus the per-object
            # ``"equipment_attached_to_self"``).
            "power_count": p.get("power_count"), "toughness_count": p.get("toughness_count"),
            # The counter kind ``"counters_on_self"`` (`continuous.
            # _pt_mod_count`) reads — "unity"/other named counters, default
            # "+1/+1" so an unparameterized per-counter anthem is unchanged.
            "counter_kind": p.get("counter_kind", "+1/+1"),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    "pt_set",  # "Each creature is 1/1" (layer 7b)
    lambda p: StaticAbility(
        "pt_set",
        affects=p.get("affects", "all_creatures"),
        params={"power": p.get("power", 0), "toughness": p.get("toughness", 0),
                **_selectors(p)},
    ),
)
EffectRegistry.register(
    # RULE 701.15b goad as a *standing static* ("Enchanted creature gets +2/+2
    # and is goaded.") — not a layer at all: goaded is explicitly neither an
    # ability nor a copiable value, so it can't be a layer-6 grant. Stamped
    # onto `GameObject._goaded_by_static` by `continuous.recompute` in the
    # same non-RULE-613 bucket the combat restrictions use.
    "goaded",
    lambda p: StaticAbility(
        "goaded",
        affects=p.get("affects", "attached_permanent"),
        params={**_selectors(p)},
    ),
)
EffectRegistry.register(
    "grant_keyword",  # "Creatures you control have flying" (layer 6); tribal too
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "creatures_you_control"),
        params={
            "keywords": list(p.get("keywords", [])),
            # RULE 702.21b's quoted grant ("Other creatures you control
            # have 'Ward—Pay 2 life.'") — see `continuous.recompute`'s own
            # `ward_cost` consumer for why this rides `grant_keyword`
            # rather than a dedicated static kind.
            **({"ward_cost": p["ward_cost"]} if p.get("ward_cost") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Equipped creature … loses flying" (Colossus Hammer) — layer 6,
    # ability-*removing* (RULE 613.7f), the mirror image of `grant_keyword`:
    # strips a flag keyword from `_obj_keywords` (`game/combat.py`) instead
    # of adding one, regardless of which of the object's three keyword
    # sources granted it.
    "remove_keyword",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "attached_permanent"),
        params={"remove_keywords": list(p.get("keywords", [])), **_selectors(p)},
    ),
)
EffectRegistry.register(
    # "All creatures lose all abilities" (Humility, Dress Down) — layer 6,
    # RULE 613.7f, stripping *every* ability (keywords via `_obj_keywords`,
    # triggered/activated abilities gated at fire/activate time on
    # `GameObject.loses_all_abilities`), not just a named keyword.
    "remove_all_abilities",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "all_creatures"),
        params={"lose_all_abilities": True, **_selectors(p)},
    ),
)
EffectRegistry.register(
    # "Cats you control have protection from Rats." (Hungry Lynx) /
    # "White creatures you control have protection from black." (Righteous
    # War) / "All creatures have protection from black." (Absolute Grace) /
    # "Enchanted creature has protection from the chosen color."
    # (Flickering Ward/Cho-Manno's Blessing) — layer 6, ability-adding
    # (RULE 613.7f/702.16), the *standing* sibling of the resolve-time
    # "until end of turn" grant `GameObject.temp_protections` already
    # carried (Mother of Runes). `continuous.recompute` folds the qualities
    # onto `obj._granted_protections`; `combat.is_protected_from` unions
    # them with the printed ones.
    #
    # ``protections`` is the printed quality word list, normalized to
    # `combat.protections_of_text` tokens at recompute time (the parser
    # front-end can't do it — no `game/` imports).
    # ``protection_from_chosen_color`` is the RULE 601.2b dynamic variant,
    # re-read off the source's own `chosen_color` every pass.
    #
    # Named ``_static`` to distinguish it from the pre-existing, unrelated
    # one-shot `grant_protection` above (Mother of Runes' resolve-time
    # "until end of turn" grant onto `temp_protections`) — same rule,
    # opposite duration, and `EffectRegistry.register` silently overwrites
    # a duplicate name.
    "grant_protection_static",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "attached_permanent"),
        params={
            "protections": [str(q) for q in p.get("protections", [])],
            "protection_from_chosen_color": bool(
                p.get("protection_from_chosen_color", False)
            ),
            "protection_from_chosen_type": bool(
                p.get("protection_from_chosen_type", False)
            ),
            # RULE 702.16n/p: "This effect doesn't remove this Aura." —
            # exempts the *granting* object's own attachment from RULE
            # 704.5m/n's illegal-attachment fall-off (`continuous.py`'s
            # layer-6 pass sets `GameObject._protection_self_exempt` on the
            # ability's source when this is set).
            "exempt_own_attachment": bool(p.get("exempt_own_attachment", False)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Elves you control have '{T}: Add {B}.'" (Tyvar Kell) — layer 6,
    # ability-adding (RULE 613.7f), same layer/bucket as `grant_keyword`, just
    # granting a mana ability's production options instead of a keyword.
    # `continuous.recompute` folds these onto `obj._granted_mana`; read
    # together with the object's own printed options via
    # `mana_abilities.mana_options_for`.
    #
    # ``cost`` (MEC-25, Goldspan Dragon — an `ActivationCost`-shaped dict,
    # same spelling `AbilitySpec.cost` uses) is the *upgrade* sibling: when
    # given, the granted ability isn't a bare repeatable ``{T}`` (the
    # default, unchanged for every pre-existing caller) but that cost
    # instead, and it *replaces* a printed mana ability of the same cost
    # shape on each affected object rather than adding an independent one
    # alongside it — "Treasures you control have '{T}, Sacrifice this
    # artifact: Add two mana of any one color.'" upgrades the token's own
    # printed one-mana version rather than granting a second, competing
    # ability. See `continuous._apply_layer_6_ability`'s ``mana_ability_
    # cost`` handling and `mana_abilities.mana_abilities_for`'s
    # replace-matching.
    "grant_mana_ability",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "creatures_you_control"),
        params={
            "mana": list(p.get("mana", [])),
            **({"mana_ability_cost": dict(p["cost"])} if p.get("cost") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "You may spend mana as though it were mana of any color to activate
    # abilities of creatures you control." (MEC-21, Agatha's Soul Cauldron)
    # — a standing RULE 605.1a wildcard *permission* over activation-cost
    # mana, not a layer-6 characteristic grant at all (so it rides its own
    # non-RULE-613 bucket, same treatment `no_max_hand_size`/`extra_land_
    # drop` already get). ``creature_abilities_only`` (default ``True``,
    # matching every printed card seen so far) scopes it to abilities whose
    # *source* is a creature — see `continuous.any_color_for_activation`,
    # consulted by the activation-cost payment path in
    # `game/engine/activation_mixin.py` (`ManaPool`'s own ``wildcard`` param,
    # already shipped for RULE 605.1a casting-side grants).
    #
    # ``from_color`` (MEC-23, Quicksilver Elemental's own second ability —
    # "You may spend **blue** mana as though it were mana of any color to
    # pay the activation costs of this creature's abilities.") narrows
    # *which* mana counts as the wildcard: Agatha's grant lets any of the
    # five colors pay any colored pip, but Quicksilver's only lets **blue**
    # mana substitute — a green pip still needs real green (or blue) mana,
    # never white/black/red. ``None`` (every pre-existing card) keeps
    # Agatha's fully unrestricted behaviour. ``self_only`` narrows *whose*
    # abilities the grant covers to this exact permanent's own — Quicksilver
    # scopes to "this creature's abilities", not Agatha's unscoped
    # "creatures you control".
    "grant_any_color_for_activation",
    lambda p: StaticAbility(
        "any_color_for_activation",
        affects=p.get("affects", "you"),
        params={
            "creature_abilities_only": bool(p.get("creature_abilities_only", True)),
            **({"from_color": str(p["from_color"])} if p.get("from_color") else {}),
            **({"self_only": True} if p.get("self_only") else {}),
        },
    ),
)
EffectRegistry.register(
    # "Creatures you control with +1/+1 counters on them have all activated
    # abilities of all creature cards exiled with ~." (MEC-21, Agatha's Soul
    # Cauldron) — a *dynamic* layer-6 ability grant whose granted-ability
    # set isn't fixed at parse time (`grant_activated_ability`'s own
    # ``grant_effects``) but read live off whichever creature cards this
    # static's own source has accumulated via `ExileEffect`'s generalized
    # ``track_exiled_with`` (`GameObject.exiled_with_ids`) — MEC-21's other
    # named primitive, reusable by any future "exile with ~" card (~185
    # cached cards print that shape). ``has_counter_kind`` (``None`` unless
    # given — MEC-26's Drana and Linvala/Scheming Fence print no such
    # qualifier on their own grantee, only Agatha's own "creatures you
    # control **with +1/+1 counters on them**" needs it, so it now passes
    # ``"+1/+1"`` explicitly rather than relying on a default every other
    # caller would silently inherit) is the *grantee* scope's own
    # qualifier — see `continuous.group_selector_objects`'s matching
    # filter — and ``creature_only`` (default ``True``) filters which
    # *donor* permanents contribute, matching the printed "creature cards
    # exiled with ~" (narrowed to ``False`` by Scheming Fence, whose donor
    # can be any nonland permanent type).
    # See `continuous._apply_borrowed_activated_abilities` for how each
    # borrowed ability is actually built.
    #
    # ``source_mode`` (MEC-26, Drana and Linvala / Scheming Fence) picks
    # *which* permanents' abilities get borrowed, generalizing beyond the
    # original ``exiled_with`` (default, unchanged) shape:
    #   - ``"exiled_with"``: `GameObject.exiled_with_ids` (Agatha's Soul
    #     Cauldron's own shape, above).
    #   - ``"group"``: a **standing, live-rederived** `affects` selector on
    #     the *battlefield* itself (``source_affects``, e.g.
    #     ``"creatures_opponents_control"``) — "Drana and Linvala has all
    #     activated abilities of all creatures your opponents control.":
    #     no exiling involved, so `exiled_with_ids` doesn't apply, but the
    #     "read the donor set live every recompute" shape is identical.
    #   - ``"chosen_permanent"``: `GameObject.chosen_permanent_id`
    #     (`continuous.group_selector_objects`'s matching selector) — "This
    #     creature has all activated abilities of the chosen permanent."
    #     (Scheming Fence), a single donor picked once by its own ETB
    #     `request_choose_objects` rather than exiled or group-scoped.
    # ``exclude_loyalty`` (Scheming Fence's own "…except for loyalty
    # abilities" — RULE 606.5c abilities are a planeswalker-only concept
    # that makes no sense borrowed onto a creature) drops any donor ability
    # whose cost `is_loyalty`.
    "grant_borrowed_activated_ability",
    lambda p: StaticAbility(
        "borrowed_activated_ability",
        affects=p.get("affects", "creatures_you_control"),
        params={
            **({"has_counter_kind": str(p["has_counter_kind"])} if p.get("has_counter_kind") else {}),
            "creature_only": bool(p.get("creature_only", True)),
            "source_mode": p.get("source_mode", "exiled_with"),
            **({"source_affects": str(p["source_affects"])} if p.get("source_affects") else {}),
            # "…that is a **Goblin** card…" (MEC-43, Conspicuous Snoop) —
            # ``source_mode="top_of_library"``'s own subtype filter.
            **({"donor_subtype": str(p["donor_subtype"])} if p.get("donor_subtype") else {}),
            **({"exclude_loyalty": True} if p.get("exclude_loyalty") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "~ gains all activated abilities of target creature until end of
    # turn." (MEC-23, Quicksilver Elemental) — the resolve-time, targeted
    # sibling of `grant_borrowed_activated_ability` just above; see
    # `GainActivatedAbilitiesOfTargetEffect`'s own docstring for the
    # snapshot-vs-live-rederive distinction between the two.
    "gain_target_activated_abilities",
    lambda p: GainActivatedAbilitiesOfTargetEffect(),
)
EffectRegistry.register(
    # PAR-8: "Each [<filter>] card in your hand has cycling `<cost>`."
    # (Jo Grant/Rhet-Tomb Mystic/Tectonic Reformation) — layer 6, but its
    # targets are *hand* cards, a zone none of the battlefield `affects`
    # selectors reach; `affects` is left at its unused default ("self") and
    # `continuous._apply_hand_cycling_grants` reads ``cost``/``card_type``
    # directly off the ability instead of going through `affected_objects`.
    "grant_cycling_to_hand",
    lambda p: StaticAbility(
        "ability",
        params={
            "grant_cycling_cost": str(p["cost"]),
            "card_type": p.get("card_type"),
        },
    ),
)
EffectRegistry.register(
    # "Elves you control have '<triggered ability text>'" (Dionus, Elvish
    # Archdruid) — layer 6, ability-adding, granting a full triggered ability
    # rather than a keyword or a mana ability. ``effects`` is a list of
    # ``{"type": ..., "params": {...}}`` one-shot-effect specs, bound through
    # the same whitelisted `EffectRegistry` as everything else (docs/09
    # security boundary) — just invoked per affected object at grant time
    # (`continuous.recompute`) instead of once at bind-on-load.
    "grant_triggered_ability",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "creatures_you_control"),
        params={
            "trigger_event": p.get("trigger_event"),
            "grant_effects": list(p.get("grant_effects", [])),
            "once_per_turn": bool(p.get("once_per_turn", False)),
            "optional": bool(p.get("optional", False)),
            "controllers_turn_only": bool(p.get("controllers_turn_only", False)),
            # RULE 120.3 "deals combat damage to a player/creature" — the
            # DAMAGE event's exact-match filter (`{"combat": ..., "is_player":
            # ...}`), threaded through by `static_handlers.
            # _quoted_ability_grant_effects`; `continuous._granted_trigger_
            # condition` ANDs it the same way `effect_binder._trigger_
            # condition`'s ``"filter"`` does for an ordinary printed trigger.
            # A granted RULE 500.7 phase trigger uses the same key for its
            # own ``{"step": "upkeep"}``.
            **({"filter": dict(p["filter"])} if p.get("filter") else {}),
            # RULE 500.7 "at the beginning of *your* upkeep" granted onto
            # another permanent ("Enchanted creature has '…'", Commander's
            # Authority/Aura Flux) — "you" is the *granted-to* permanent's
            # controller, not the granting source's, so unlike
            # `effect_binder._trigger_condition`'s own `phase_relation`
            # branch (which closes over the printed source) this is resolved
            # per affected object in `continuous._granted_trigger_condition`.
            **({"phase_relation": p["phase_relation"]} if p.get("phase_relation") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Equipped creature/Enchanted land has '{cost}: <effect>.'" (Umbral
    # Mantle/Squirrel Nest-shaped) — layer 6, ability-adding, the activated
    # sibling of `grant_triggered_ability` just above. `continuous.recompute`
    # builds (and per-relationship caches) a real `ActivatedAbility` per
    # affected object onto `GameObject._granted_activated_abilities`, read
    # together with the object's own printed ones by `GameEngine.
    # can_activate`/`activate_ability`/`legal_actions`.
    "grant_activated_ability",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "attached_permanent"),
        params={
            "activated_cost": dict(p.get("cost") or {}),
            "grant_effects": list(p.get("grant_effects", [])),
            "once_per_turn": bool(p.get("once_per_turn", False)),
            "sorcery_speed_only": bool(p.get("sorcery_speed_only", False)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Each nonland card in your graveyard has escape. The escape cost is
    # equal to the card's mana cost plus exile N other cards from your
    # graveyard." (Underworld Breach) — RULE 702.138 as a *granted* keyword
    # onto cards in a graveyard, which no battlefield selector could reach;
    # consulted by `continuous.granted_escape_for` from `GameEngine.
    # _graveyard_cast_keyword`/`_escape_cost`.
    "grant_escape",
    lambda p: StaticAbility(
        "grant_escape",
        affects="all",
        params={
            "nonland_only": bool(p.get("nonland_only", True)),
            "exile_from_graveyard": int(p.get("exile_from_graveyard", 0) or 0),
        },
    ),
)
EffectRegistry.register(
    "type_change",  # "Lands you control are 0/0 creatures" (layer 4)
    lambda p: StaticAbility(
        "type",
        affects=p.get("affects", "self"),
        params={
            "add_types": list(p.get("add_types", [])),
            # "…and loses all other card types…" (Vraska, Betrayal's
            # Sting's -2) — the removal-side mirror of `add_types`.
            "remove_types": list(p.get("remove_types", [])),
            # RULE 601.2b/613.4a "~ is the chosen type in addition to its
            # other types" (Adaptive Automaton/A-Thran Portal-shaped) — a
            # literal `add_subtypes` list and/or the dynamic
            # `add_subtypes_from_source` flag (reads the ability source's
            # own `chosen_type` fresh every recompute); *adds* alongside the
            # object's printed subtypes, unlike `set_subtypes` below.
            "add_subtypes": list(p.get("add_subtypes", [])),
            "add_subtypes_from_source": bool(p.get("add_subtypes_from_source", False)),
            "power": p.get("power"),
            "toughness": p.get("toughness"),
            # "…becomes an artifact creature with power and toughness each
            # equal to its mana value." (Karn, the Great Creator-shaped) —
            # a dynamic sibling of the literal ``power``/``toughness`` ints
            # above, resolved fresh every recompute off the affected
            # object's own printed mana value rather than a fixed number.
            "pt_selector": p.get("pt_selector"),
            # RULE 613.5 full subtype overwrite ("Nonbasic lands are
            # Mountains.", Magus of the Moon/Blood Moon) — unlike
            # `add_types` (only *adds*), this *replaces* the affected
            # object's subtype set (`continuous._has_subtype`), only
            # included when the spec actually sets it so an ordinary
            # "are also creatures" clause is unaffected.
            **({"set_subtypes": list(p["set_subtypes"])} if p.get("set_subtypes") else {}),
            # RULE 613.4a *past* the battlefield — "The same is true for
            # creature spells you control and creature cards you own that
            # aren't on the battlefield" (Arcane Adaptation/Leyline of
            # Transformation, ``"cards_you_own"``) / "Each creature card in
            # your graveyard has the chosen creature type…" (Ashes of the
            # Fallen, ``"your_graveyard"``). The battlefield-side `affects`
            # selector above is independent: Arcane Adaptation sets both
            # (its battlefield half *and* this), Ashes of the Fallen only
            # this. See `continuous._apply_off_battlefield_types`.
            **({"off_battlefield": str(p["off_battlefield"])} if p.get("off_battlefield") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "If you tap a permanent for mana, it produces N times as much of that
    # mana instead." (Nyxbloom Ancient) — not a RULE 613 layer (nothing here
    # is a characteristic), consulted directly by `GameEngine.tap_for_mana`
    # via `continuous.mana_production_multiplier_for`, alongside
    # `activation_prohibition`/`cast_prohibition` in `_NON_RULE_613_LAYERS`.
    "mana_multiplier",
    lambda p: StaticAbility(
        "mana_multiplier",
        affects="self",
        params={"multiplier": int(p.get("multiplier", 2) or 2)},
    ),
)
EffectRegistry.register(
    # "Skip your draw step." (MEC-38, Necropotence) — consulted directly by
    # `RulesEngine.should_skip_step` via `continuous.skipped_steps_for`,
    # the same "not a RULE 613 layer, read live off the battlefield" shape
    # `mana_type_override`/`mana_multiplier` already use.
    "skip_step",
    lambda p: StaticAbility(
        "skip_step",
        affects="self",
        params={"step": p.get("step", "draw")},
    ),
)
EffectRegistry.register(
    # "While an opponent is searching their library, they exile each card
    # they find. You may play those cards..." (MEC-39, Opposition Agent)
    # — consulted directly by `RulesEngine._finish_search` via
    # `continuous.search_redirect_controller_for`.
    "search_redirect",
    lambda p: StaticAbility("search_redirect", affects="self", params={}),
)
EffectRegistry.register(
    # "If a card would be put into an opponent's graveyard from anywhere,
    # instead exile it with a void counter on it." (Dauthi Voidwalker,
    # MEC-42) — consulted by `continuous.void_counter_redirect_controller_
    # for` (`RulesEngine._move_to_graveyard`'s own redirect chain, same
    # choke point Yawgmoth's Will/Lurrus already use).
    "void_counter_redirect",
    lambda p: StaticAbility("void_counter_redirect", affects="self", params={}),
)
EffectRegistry.register(
    # "If a card would be put into an opponent's graveyard from anywhere,
    # exile it instead." (Leyline of the Void)/"If a card or token would be
    # put into a graveyard from anywhere, exile it instead." (Rest in
    # Peace, MEC-43) — the plain-exile sibling of `void_counter_redirect`
    # just above (no counter, no holder tracking); ``scope`` is
    # ``"opponent"`` (default) or ``"any"``. Consulted by `continuous.
    # graveyard_redirect_active`.
    "graveyard_redirect",
    lambda p: StaticAbility(
        "graveyard_redirect", affects="self",
        params={
            "scope": p.get("scope", "opponent"),
            # "…**black or red**…" (Sanctifier en-Vec, MEC-43 round 2) — a
            # colour-scoped redirect instead of/alongside a graveyard-owner
            # one; see `continuous.graveyard_redirect_active`.
            **({"colors": [str(c).upper() for c in p["colors"]]} if p.get("colors") else {}),
        },
    ),
)
EffectRegistry.register(
    # "Each opponent can cast spells only any time they could cast a
    # sorcery." (Teferi, Time Raveler, MEC-42) — consulted by
    # `continuous.forced_sorcery_speed_only` (`GameEngine.can_cast`'s own
    # timing computation).
    "sorcery_speed_only",
    lambda p: StaticAbility("sorcery_speed_only", affects="opponents", params={}),
)
EffectRegistry.register(
    # "As an additional cost to cast this spell, you may exile any number
    # of blue cards from your hand. This spell costs {2} less to cast for
    # each card exiled this way." (March of Swirling Mist, MEC-42) —
    # consulted by `continuous.exile_discount_spec_for`, read straight off
    # the spell's own `static_effects` (still in hand) the same way
    # Delve/Affinity's own `self_cost_reduction_for` static is.
    "exile_discount_cost",
    lambda p: StaticAbility(
        "exile_discount_cost", affects="self",
        params={
            "color": p.get("color", "U"),
            "generic_per_card": int(p.get("generic_per_card", 2)),
        },
    ),
)
EffectRegistry.register(
    # "If a land is tapped for 2 or more mana, it produces {C} instead of
    # any other type and amount." (MEC-36, Damping Sphere) — unscoped
    # (``affects="all_lands"``, matching every land regardless of
    # controller, the same "unqualified reach" `cost_reduction`'s own
    # ``affects="all_spells"`` uses), consulted directly by `GameEngine.
    # tap_for_mana` via `continuous.mana_type_override_for`, alongside
    # `mana_multiplier` above.
    "mana_type_override",
    lambda p: StaticAbility(
        "mana_type_override",
        affects="all_lands",
        params={
            "min_amount": int(p.get("min_amount", 2) or 2),
            "to": p.get("to", "C"),
        },
    ),
)
EffectRegistry.register(
    "cost_reduction",  # "Spells you cast cost {N} less" (RULE 601.2f)
    lambda p: StaticAbility(
        "cost",
        # ``affects="your_spells"`` (default) is self-scoped — see
        # `continuous.cost_reduction_for`'s ownership check. ``"all_spells"``
        # (Thalia, Guardian of Thraben/Thorn of Amethyst/Vryn Wingmare-shaped:
        # an unqualified "<type> spells cost {N} more to cast") isn't scoped
        # by that check at all, so it taxes/discounts *every* player's
        # matching spells, its own controller's included.
        affects=p.get("affects", "your_spells"),
        params={
            "generic": p.get("generic", 1),
            "increase": bool(p.get("increase", False)),
            # Delve/Affinity-shaped "{N} less for each <count_selector>"
            # (`affects="self"`, printed on the spell itself) — see
            # `continuous._cost_static_amount`/`self_cost_reduction_for`.
            **({"per": p["per"]} if p.get("per") else {}),
            # A card-type filter on the spell *being cast* ("noncreature
            # spells…") — `continuous._spell_type_matches`; distinct from
            # `card_type` (a *permanent*-selector filter the other static
            # families above use) since this checks the object on the stack,
            # not a battlefield selector.
            **({"spell_type": p["spell_type"]} if p.get("spell_type") else {}),
            # "Red spells you cast cost {1} less to cast." (the Medallion
            # cycle) — `continuous.cost_reduction_for`'s own colour filter,
            # orthogonal to `spell_type`. ``"colorless"`` is its own special
            # value (Eye of Ugin), an empty-identity check rather than a
            # membership one.
            **({"spell_color": p["spell_color"]} if p.get("spell_color") else {}),
            # "Colorless Eldrazi spells you cast cost {2} less to cast."
            # (Eye of Ugin) — a creature-subtype filter, orthogonal to both
            # `spell_type` (main card types only) and `spell_color` above.
            **({"spell_subtype": p["spell_subtype"]} if p.get("spell_subtype") else {}),
            # ``scope="activation"`` (Power Artifact-shaped "Enchanted
            # artifact's activated abilities cost {2} less to activate.") —
            # a *different* cost this same "cost" layer/StaticAbility shape
            # adjusts: an activated ability's own activation cost (RULE
            # 601.2f-adjacent) rather than a spell's cast cost, consulted by
            # `continuous.activation_cost_reduction_for`/`GameEngine.
            # _reduced_activation_mana` instead of `cost_reduction_for` (which
            # explicitly skips these). ``min_total`` is the "can't reduce the
            # mana in that cost to less than N mana" floor.
            **({"scope": p["scope"]} if p.get("scope") else {}),
            **({"min_total": p["min_total"]} if p.get("min_total") else {}),
            # "Activated abilities of Foods you control cost {1} less to
            # activate." (Sam, Loyal Attendant) — the subtype-scoped
            # ``scope="activation"`` variant `continuous.
            # activation_cost_reduction_for` reads, unlike its "attached
            # Permanent" sibling above.
            **({"subtype": p["subtype"]} if p.get("subtype") else {}),
            # "Activated abilities of creatures you control cost {2} less
            # to activate." (Training Grounds) — the same ``scope=
            # "activation"`` group scope as ``subtype`` above, narrowed by
            # a main card type (`continuous._has_card_type`) instead of a
            # creature subtype.
            **({"card_type": p["card_type"]} if p.get("card_type") else {}),
            # "This spell costs {N} less to cast if `<condition>`."
            # (Ghostfire Slice) — RULE 613.6's ordinary ability-source-
            # relative gate, read both by `self_cost_reduction_for` (a
            # spell's own printed reduction, ``affects="self"``) and — MEC-12
            # fixed a latent gap here — `cost_reduction_for` itself, which had
            # never consulted ``active_if`` at all despite `cost_floor_for`
            # (the very next function) already doing so for the same
            # ``"cost"`` layer. Needed for Tithe Taker's "**during your
            # turn**, spells your opponents cast cost {1} more…".
            **({"active_if": p["active_if"]} if p.get("active_if") else {}),
            # "Each spell that would cost less than N mana to cast costs N
            # mana to cast instead." (Trinisphere) — a floor rather than a
            # delta, read separately by `continuous.cost_floor_for` (not
            # part of the additive ``generic``/``increase`` net above).
            **({"min_generic": p["min_generic"]} if p.get("min_generic") else {}),
            # "Each spell costs {N} more to cast **except during its
            # controller's turn**." (MEC-12, Defense Grid) — unlike
            # ``active_if``'s ``your_turn``/``not_your_turn`` (evaluated
            # against *this static's own* controller), "its controller" here
            # means whichever player is actually casting the taxed spell —
            # so `cost_reduction_for` checks it directly against its own
            # ``player`` argument rather than routing it through the
            # ability-source-relative `static_conditions` vocabulary at all.
            **({"except_caster_own_turn": True} if p.get("except_caster_own_turn") else {}),
            # "…unless they're mana abilities." (MEC-12, Suppression Field/
            # Tithe Taker) — the ``scope="activation"`` cost-tax sibling of
            # `activation_prohibition`'s own identically-named rider; read by
            # `activation_cost_reduction_for`'s new ``is_mana_ability`` param.
            **({"except_mana_abilities": True} if p.get("except_mana_abilities") else {}),
            # "A spell cast by an opponent this way costs {2} more to
            # cast." (MEC-12, Soul Partition) — a per-*instance* tax built
            # dynamically at exile time (`ExileEffect`'s new
            # ``grant_owner_play_permission``/``owner_play_permission_tax``)
            # and stamped straight onto the exiled card's own
            # ``affects="self"`` static, exempting only the value named
            # here (the exiler's own player id) — read by
            # `self_cost_reduction_for`'s new ``caster_id`` param, since
            # "an opponent" is relative to whoever is actually casting,
            # not to this static's own (largely meaningless, off-
            # battlefield) ``controller_id``.
            **(
                {"except_same_controller_as": p["except_same_controller_as"]}
                if p.get("except_same_controller_as") is not None else {}
            ),
        },
    ),
)
EffectRegistry.register(
    # "Activated abilities of artifacts can't be activated." (RULE 602,
    # Collector Ouphe/Stony Silence/Null Rod) — reuses the ordinary
    # `affects`/selector vocabulary (default "all_permanents", global) purely
    # to pick out *which* permanents' activated abilities are silenced;
    # `game/continuous.activation_prohibited` is the actual consult point
    # (`GameEngine.can_activate`), there's no P/T/type/ability layer effect
    # to fold into `continuous.recompute` here.
    "activation_prohibition",
    lambda p: StaticAbility(
        "activation_prohibition",
        affects=p.get("affects", "all_permanents"),
        params={
            # RULE 605.1a's carve-out ("…and its activated abilities can't be
            # activated **unless they're mana abilities**" — Kasmina's
            # Transmutation/Imprisoned in the Moon). Without it the
            # prohibition covers mana abilities too, which is what makes Null
            # Rod stop an artifact's "{T}: Add {C}".
            "except_mana_abilities": bool(p.get("except_mana_abilities", False)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # RULE 508.1a/509.1b's *qualified* combat restrictions — "~ can't be
    # blocked by creatures with power 2 or less", "…except by Walls", "…by
    # more than one creature", "~ can't attack unless defending player
    # controls an Island", "~ can't attack alone". Their unqualified siblings
    # ride synthetic `grant_keyword` flags (`cant_attack`/`cant_block`/
    # `cant_be_blocked`); these carry a parameter a flag can't, so the whole
    # entry is stamped onto `GameObject.combat_restrictions` by
    # `continuous.recompute` and evaluated at *combat* time instead — see
    # `game/combat.py`'s `COMBAT_RESTRICTIONS` for the ``kind`` whitelist and
    # `GameEngine._combat_condition_met` for the ``condition`` one.
    #
    # Not a RULE 613 layer (nothing here is a characteristic), so it sits in
    # `continuous._NON_RULE_613_LAYERS` alongside `activation_prohibition`.
    "combat_restriction",
    lambda p: StaticAbility(
        "combat_restriction",
        affects=p.get("affects", "self"),
        params={
            "kind": str(p.get("kind", "")),
            **({"filter": dict(p["filter"])} if p.get("filter") else {}),
            **({"condition": dict(p["condition"])} if p.get("condition") else {}),
            **({"count": int(p["count"])} if p.get("count") is not None else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Each player can't cast more than N spells each turn." (RULE 601-area,
    # Eidolon of Rhetoric/Rule of Law/Archon of Emeria) — a flat, global cap,
    # not scoped to any particular player's spells; consulted by
    # `continuous.max_spells_per_turn` (`GameEngine.can_cast`).
    "cast_limit",
    lambda p: StaticAbility(
        "cast_limit",
        affects="all",
        params={
            "max_per_turn": p.get("max_per_turn", 1),
            # "…more than N **noncreature** spells…" (Deafening Silence) —
            # `continuous.max_noncreature_spells_per_turn`'s own scope flag.
            "noncreature": bool(p.get("noncreature", False)),
        },
    ),
)
EffectRegistry.register(
    # "Each opponent can't cast noncreature spells with mana value greater
    # than the number of lands that player controls." (Lavinia, Azorius
    # Renegade) — a *conditional* prohibition on a specific spell, unlike
    # `cast_limit`'s flat count; consulted by `continuous.cast_prohibited`.
    # `**_selectors(p)` carries ``active_if`` through ("During your turn,
    # your opponents can't cast spells …" — Grand Abolisher/Myrel, Shield of
    # Argive, RULE 613.6) — omitted before ENG-28, which silently dropped any
    # gate a `cast_prohibition` spec tried to carry.
    "cast_prohibition",
    lambda p: StaticAbility(
        "cast_prohibition",
        affects="all",
        params={
            "scope": p.get("scope", "opponents"),
            "noncreature": bool(p.get("noncreature", False)),
            "max_mana_value_selector": p.get("max_mana_value_selector"),
            # MEC-43: `max_mana_value_selector`'s literal sibling (Gaddock
            # Teeg's flat "4 or greater", or the ``"chosen_number"``
            # sentinel for Sanctum Prelate's RULE 601.2b pick), plus the
            # ``cmp`` mode both knobs share and the two independent
            # restriction families (`has_x_cost`/`nonartifact` +
            # `min_count_selector`) — see `continuous.cast_prohibited`'s
            # own docstring for the full vocabulary.
            **({"max_mana_value": p["max_mana_value"]} if p.get("max_mana_value") is not None else {}),
            "cmp": p.get("cmp", "gt"),
            "has_x_cost": bool(p.get("has_x_cost", False)),
            "nonartifact": bool(p.get("nonartifact", False)),
            # "Your opponents can't cast spells with even mana values.
            # (Zero is even.)" (Void Winnower, MEC-12) — latent bug found
            # while widening this factory for MEC-43: this key was already
            # written by that catalogue entry but never captured here, so
            # it silently fell through `_selectors`' whitelist and the
            # clause prohibited *every* opponent spell regardless of mana
            # value (`cast_prohibited` had no ``max_mana_value``/
            # ``max_mana_value_selector`` to check, so it returned ``True``
            # unconditionally the moment scope/noncreature matched).
            "even_mana_value": bool(p.get("even_mana_value", False)),
            **({"min_count_selector": p["min_count_selector"]} if p.get("min_count_selector") else {}),
            # "…can't cast spells from anywhere other than their hands."
            # (Drannith Magistrate) — `continuous.cast_prohibited`'s own
            # zone check.
            "hand_only": bool(p.get("hand_only", False)),
            # "…can't cast **blue creature** spells." (Llawan, Cephalid
            # Empress, MEC-43) — the first cast_prohibition needing *both* a
            # card-type restriction *and* a colour one at once:
            # ``creature_only`` (the mirror image of ``noncreature`` above)
            # combined with ``color`` (a single WUBRG letter, checked
            # against the spell's own printed `Card.color_identity`).
            "creature_only": bool(p.get("creature_only", False)),
            **({"color": str(p["color"]).upper()} if p.get("color") else {}),
            # "…spells from graveyards or exile." (Soulless Jailer, MEC-43)
            # — a zone allowlist, the sibling of ``hand_only`` above.
            **({"zones": list(p["zones"])} if p.get("zones") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Players can't pay life or sacrifice nonland permanents to cast
    # spells or activate abilities." (Yasharn, Implacable Earth, MEC-40) —
    # consulted by `continuous.cost_restricted` at every cost-payment
    # choke point that offers a pay-life/sacrifice component.
    "cost_restriction",
    lambda p: StaticAbility(
        "cost_restriction", affects="all", params={"kinds": list(p.get("kinds", []))},
    ),
)
EffectRegistry.register(
    # "Each player can't draw more than N cards each turn." (RULE 121.5-
    # adjacent, Spirit of the Labyrinth-shaped) — the draw-side mirror of
    # `cast_limit`, a flat global cap consulted by `continuous.
    # max_draws_per_turn` (`RulesEngine._single_draw`).
    "draw_limit",
    lambda p: StaticAbility(
        "draw_limit",
        # "Each opponent can't draw more than one card each turn." (Narset,
        # Parter of Veils) is ``affects="opponents"``, skipping the static's
        # own controller — Spirit of the Labyrinth's unqualified "each
        # player" stays the default ``"all"``.
        affects=p.get("affects", "all"),
        params={"max_per_turn": p.get("max_per_turn", 1)},
    ),
)
EffectRegistry.register(
    # "~ doesn't untap during your untap step." (RULE 502.3-adjacent, Basalt
    # Monolith/Grim Monolith/Mana Vault — self-scoped) or "Enchanted creature
    # doesn't untap during its controller's untap step." (Paralyzing Grasp —
    # ``affects="attached_permanent"``); consulted by
    # `continuous.has_no_untap_static` (`GameEngine._step_untap`). Also the
    # unattached group shape "Creatures with power N or greater don't untap
    # during their controllers' untap steps." (Meekstone —
    # ``affects="all_creatures"`` + the ordinary ``min_power`` selector),
    # forwarded via ``_selectors`` like every other group-scoped static.
    "no_untap",
    lambda p: StaticAbility("no_untap", affects=p.get("affects", "self"), params={**_selectors(p)}),
)
EffectRegistry.register(
    # "As long as this artifact is untapped, players can't untap more than
    # one land during their untap steps." (Winter Orb) — a flat, unscoped
    # cap consulted by `continuous.active_untap_caps`/`GameEngine.
    # _step_untap`. ``card_type`` (default ``"land"``, Winter Orb's own
    # shape) and ``nonbasic`` (Winter Moon's "…one nonbasic land…") widen
    # the scope beyond lands; any tap-state gate ("as long as this artifact
    # is untapped") rides the ordinary ``active_if`` RULE 613.6 wrapper
    # rather than a hardcoded tapped check, same as every other conditional
    # static.
    "untap_cap",
    lambda p: StaticAbility(
        "untap_cap", affects="all_players", params={"count": p.get("count", 1), **_selectors(p)}
    ),
)
EffectRegistry.register(
    # "You may choose not to untap ~ during your untap step." (RULE 502.1
    # self-scoped opt-out, Rubinia Soulsinger/Hivis of the Scale/The
    # Pandorica-shaped) — unlike `no_untap` (unconditional), this only
    # actually skips untapping once the controller has separately toggled
    # `GameObject.skip_untap` on (`GameEngine.set_skip_untap`, since the
    # engine has no mid-untap-step pause to ask fresh every turn — a
    # standing toggle instead); consulted by `continuous.has_no_untap_static`.
    "no_untap_optional",
    lambda p: StaticAbility("no_untap_optional", affects="self", params={}),
)
EffectRegistry.register(
    # "You may play an additional land on each of your turns." (RULE 305.2,
    # Exploration/Dryad of the Ilysian Grove/Azusa-shaped, ``count`` for
    # Azusa's "two additional lands") or, unscoped, "Each player may play an
    # additional land on each of their turns." (Rites of Flourishing/Ghirapur
    # Orrery/Storm Cauldron, ``affects="each_player"``); consulted by
    # `continuous.extra_land_plays_for` (`GameEngine.can_play_land`). The
    # one-turn, resolve-time sibling is `ExtraLandPlayEffect`/``extra_land_play``.
    "extra_land_drop",
    lambda p: StaticAbility(
        "extra_land_drop", affects=p.get("affects", "you"), params={"count": p.get("count", 1)}
    ),
)
EffectRegistry.register(
    # "You have no maximum hand size." (RULE 402.2, A-Wizard Class/Body of
    # Knowledge-shaped) or "Players have no maximum hand size." (Anvil of
    # Bogardan/Folio of Fancies, ``affects="each_player"``); consulted by
    # `continuous.has_no_maximum_hand_size` (`GameEngine._step_cleanup`). The
    # durational "…for the rest of the game"/"…until your next turn" one-shot
    # variants are a different, resolve-time-granted shape, not modeled here.
    "no_max_hand_size",
    lambda p: StaticAbility("no_max_hand_size", affects=p.get("affects", "you"), params={}),
)
EffectRegistry.register(
    # "The 'legend rule' doesn't apply to permanents you control." (RULE
    # 704.5j, Sakashima of a Thousand Faces-shaped); consulted by
    # `continuous.player_ignores_legend_rule` (`RulesEngine.
    # _apply_legend_rule`). Same ``affects`` convention as `no_max_hand_size`
    # just above.
    "ignore_legend_rule",
    lambda p: StaticAbility("ignore_legend_rule", affects=p.get("affects", "you"), params={}),
)
EffectRegistry.register(
    # "Elemental permanent spells you cast from your hand gain evoke {4} as
    # you cast them." (Ashling, the Limitless, MEC-42) — consulted by
    # `continuous.granted_evoke_cost_for` (`GameEngine.can_cast`/
    # `effective_cast_cost`'s ``evoke`` branch), the hand-cast-cost sibling
    # of ``flash_permission`` right below.
    "grant_evoke",
    lambda p: StaticAbility(
        "grant_evoke",
        affects="self",
        params={
            "cost": str(p.get("cost")) if p.get("cost") else None,
            "subtype": p.get("subtype"),
        },
    ),
)
EffectRegistry.register(
    # "You may cast spells as though they had flash." (High Fae Trickster/
    # Valley Floodcaller-shaped) — consulted by `continuous.has_standing_
    # flash_permission` (`GameEngine.can_cast`'s timing check).
    "flash_permission",
    lambda p: StaticAbility(
        "flash_permission",
        affects="self",
        params={
            "noncreature_only": bool(p.get("noncreature_only", False)),
            "creature_only": bool(p.get("creature_only", False)),
            # "You may cast **legendary spells and artifact spells** as
            # though they had flash." (Gandalf the White, MEC-40) — a
            # closed word list ("legendary"/"artifact"/"creature"), union
            # semantics: a spell qualifies if it matches *any* word.
            "type_filter": list(p["type_filter"]) if p.get("type_filter") else None,
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "You gain life rather than lose life from radiation." (RULE 728.1a,
    # Strong, the Brutish Thespian) — consulted by `RulesEngine.lose_life`
    # (`continuous.has_radiation_life_gain`) before applying a
    # ``cause="radiation"`` life loss, redirecting it into a life *gain* of
    # the same amount instead. A per-player permission static, the same
    # "outside the layer engine proper" treatment as `no_max_hand_size`/
    # `no_untap_optional`.
    "radiation_life_gain",
    lambda p: StaticAbility("radiation_life_gain", affects=p.get("affects", "you"), params={}),
)
EffectRegistry.register(
    # "Players skip their untap steps." (RULE 502.3-adjacent, Stasis) — the
    # last open member of the "players can't `<verb>`" family
    # (`docs/implementation-state/BACKLOG.md`'s MEC-12 entry; untap's own
    # *capped* sibling already shipped as `"untap_cap"`/`active_untap_caps`).
    # Unlike a cap, this is unconditional and total: every player's whole
    # untap step does nothing, themselves included, which is why it's
    # unscoped by ``affects`` (there is no printed "you"-only phrasing of
    # this clause) — consulted by `continuous.all_untap_steps_skipped`
    # (`GameEngine._step_untap`).
    "skip_untap_step",
    lambda p: StaticAbility("skip_untap_step", affects="each_player", params={}),
)
EffectRegistry.register(
    # "Players can't cast spells from graveyards or libraries." (RULE
    # 601.3a-adjacent, Grafdigger's Cage/Weathered Runestone) — a flat,
    # unscoped prohibition over every standing graveyard/library-cast
    # *permission* this engine has (`continuous.
    # graveyard_library_cast_prohibited`, `GameEngine.can_cast`'s single
    # choke point for Flashback/Escape/Jump-start, a Lurrus-shaped grant,
    # and `game/top_library.py`'s play/cast-from-the-top permission alike).
    "graveyard_library_cast_prohibition",
    lambda p: StaticAbility(
        "graveyard_library_cast_prohibition", affects="each_player",
        # MEC-43 round 2 (Kunoros, Hound of Athreos): "Players can't cast
        # spells from **graveyards**" — no "or libraries" — narrows the
        # otherwise-unscoped prohibition to just the named zone(s).
        params={**({"zones": list(p["zones"])} if p.get("zones") else {})},
    ),
)
EffectRegistry.register(
    # "`<type>` cards in graveyards and libraries can't enter the
    # battlefield." (Grafdigger's Cage's "creature", Weathered Runestone's
    # "nonland permanent") — checked at the two real reanimation/tutor-to-
    # battlefield choke points (`continuous.graveyard_library_entry_
    # prohibited`; see its own docstring for why this isn't a universal
    # `add_to_battlefield` hook).
    "graveyard_library_entry_prohibition",
    lambda p: StaticAbility(
        "graveyard_library_entry_prohibition", affects="each_player",
        params={
            "card_type": p.get("card_type", "creature"),
            # MEC-43 round 2 (Kunoros): "creature cards in **graveyards**
            # can't enter the battlefield" — no "and libraries".
            **({"zones": list(p["zones"])} if p.get("zones") else {}),
        },
    ),
)
EffectRegistry.register(
    # "Creatures entering don't cause abilities to trigger." (RULE 603,
    # Tocatli Honor Guard/Hushwing Gryff/Torpor Orb) — global: silences every
    # triggered ability (including the entering object's own) that would fire
    # off a matching event; consulted by `continuous.trigger_suppressed`
    # (`RulesEngine._collect_triggers`), not a `continuous.recompute` layer.
    "trigger_prohibition",
    lambda p: StaticAbility(
        "trigger_prohibition",
        affects="all",
        params={
            "event": p.get("event"), "subject_type": p.get("subject_type"),
            # "Permanents entering don't cause abilities of **permanents
            # your opponents control** to trigger." (Elesh Norn, Mother of
            # Machines, MEC-40) — narrows the otherwise-global suppression
            # to just the entering-object's controller's opponents,
            # relative to this static's own source.
            "scope": p.get("scope", "all"),
        },
    ),
)
EffectRegistry.register(
    # "Artifacts your opponents control enter tapped." (RULE 614.1, board-
    # wide — Manglehorn/Dauntless Dismantler; Archon of Emeria's "Nonbasic
    # lands…" narrows further with ``nonbasic``) — distinct from
    # `ability_catalogue.enters_tapped` (a card's own printed clause about
    # itself): this is a *different* permanent's standing effect, consulted
    # by `continuous.enters_tapped_from_static`
    # (`RulesEngine._resolve_permanent_spell`/token creation).
    "enters_tapped_static",
    lambda p: StaticAbility(
        "enters_tapped",
        affects=p.get("affects", "opponents_permanents"),
        params={**_selectors(p)},
    ),
)
EffectRegistry.register(
    "color_change",  # "Enchanted creature is black" / "All creatures are red" (layer 5)
    lambda p: StaticAbility(
        "color",
        affects=p.get("affects", "attached_permanent"),
        params={
            "colors": [str(c).upper() for c in p.get("colors", [])],
            "set": bool(p.get("set", True)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    "control_change",  # "You control enchanted creature" (Mind Control, layer 2)
    lambda p: StaticAbility(
        "control",
        affects=p.get("affects", "attached_permanent"),
        # No explicit "controller" defaults to the effect's own source's
        # controller (continuous.recompute), which is exactly "you" for a
        # hand-authored "you control enchanted/equipped permanent" clause.
        params={"controller": p.get("controller")},
    ),
)
EffectRegistry.register(
    "pt_cda",  # "*/* creature with power/toughness equal to …" (layer 7a, RULE 604.3)
    lambda p: StaticAbility(
        "pt_cda",
        affects=p.get("affects", "self"),
        params={
            "power_count": p.get("power_count"),
            "toughness_count": p.get("toughness_count"),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    "pt_switch",  # "Switch this creature's power and toughness" (layer 7e, RULE 613.4d/701.28)
    lambda p: StaticAbility(
        "pt_switch",
        affects=p.get("affects", "self"),
        params={**_selectors(p)},
    ),
)
EffectRegistry.register(
    "win_game",  # "you win the game" (Jace, Wielder of Mysteries' -8 tail)
    lambda p: WinGameEffect(if_empty_library=bool(p.get("if_empty_library", False))),
)
EffectRegistry.register(
    "become_monarch",  # "you become the monarch" (RULE 725.1, Palace Jailer-shaped)
    lambda p: BecomeMonarchEffect(target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    "take_initiative",  # "you take the initiative" (RULE 726.1)
    lambda p: TakeInitiativeEffect(target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    "venture",  # "venture into the dungeon" (RULE 701.49)
    lambda p: VentureIntoTheDungeonEffect(dungeon=p.get("dungeon")),
)
EffectRegistry.register(
    # RULE 702.131a: Ascend's spell-ability form — "you get the city's
    # blessing" checked once, at resolution, against the board.
    "get_city_blessing",
    lambda p: GetCityBlessingEffect(),
)
EffectRegistry.register(
    # RULE 611 "…until <duration>" — a continuous effect created on
    # resolution, for any duration the turn-scoped ``temp_*`` fields can't
    # express (`game/durations.py`). ``static`` is the underlying static's
    # own registered ``{"type", "params"}``.
    "grant_until",
    lambda p: GrantUntilEffect(
        static=p.get("static"),
        duration=str(p.get("duration") or "end_of_turn"),
        target_kind=p.get("target_kind", "creature") if "target_kind" in p else "creature",
        optional=bool(p.get("optional", False)),
        count=int(p.get("count", 1) or 1),
        condition=p.get("condition"),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    # RULE 701.37a "monstrosity N" — ``amount`` may be the ``"x"`` sentinel
    # (`RulesEngine._substitute_x`) for "{X}{X}{R}: Monstrosity X".
    "monstrosity",
    lambda p: MonstrosityEffect(amount=p.get("amount", 1)),
)
EffectRegistry.register(
    # RULE 701.46a "adapt N".
    "adapt",
    lambda p: AdaptEffect(amount=p.get("amount", 1)),
)
EffectRegistry.register(
    # RULE 701.15a "goad target creature" — ``target_kind=None`` is the
    # "goad it"/"goad that creature" pronoun form, ``selector`` the mass one.
    "goad",
    lambda p: GoadEffect(
        target_kind=p.get("target_kind", "creature") if "target_kind" in p else "creature",
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        selector=p.get("selector"),
        count_selector=p.get("count_selector"),
        referent=p.get("referent", "previous"),
        permanent=bool(p.get("permanent", False)),
    ),
)
EffectRegistry.register(
    "create_emblem",  # "you get an emblem with '<ability>'" (RULE 114.2)
    lambda p: CreateEmblemEffect(ability=p.get("ability"), target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    # "Until your next turn, target player … can't cast noncreature spells."
    # (Hope of Ghirapur) — a player-scoped cast prohibition, RULE 601.3a.
    "player_cast_restriction",
    lambda p: PlayerCastRestrictionEffect(noncreature=bool(p.get("noncreature", True))),
)
EffectRegistry.register(
    # "Look at the top X cards … put up to one on top and the rest on the
    # bottom in a random order." (+ Thassa's Oracle's own RULE 104.2a win)
    "look_top_keep_one_on_top",
    lambda p: LookTopKeepOneOnTopEffect(
        count=int(p.get("count", 0) or 0),
        count_selector=p.get("count_selector"),
        win_if_count_at_least_library=bool(p.get("win_if_count_at_least_library", False)),
    ),
)


# ---------------------------------------------------------------------------
# Replacement-effect registry (RULE 614) — the binder's whitelist
# ---------------------------------------------------------------------------


def _prevent_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """A standing damage-prevention shield (RULE 615/616.1) — the *permanent*
    sibling of `PreventDamageEffect`'s one-shot spell grant (registered
    separately as ``"prevent_damage_shield"``, Riot Control/Thought Lash;
    unrelated despite the shared name prefix).

    ``to`` selects the recipient, read off the effect's own source: ``"self"``
    (the source permanent itself), ``"controller"`` (its controller — a
    player), ``"any_player"`` (any player at all — Battletide Alchemist),
    ``"opponent_player"`` (any player who isn't the controller — Hostility's
    "an opponent"), ``"attached_permanent"`` (an Aura/Equipment's own host —
    Shield of the Realm/Avatar), or ``"controlled_permanent"`` (any permanent this
    effect's controller controls, optionally narrowed by ``recipient_filter``
    — a `combat.matches_object_filter`-shaped dict, e.g. Daunting Defender's
    ``{"subtype": "cleric"}``, Djeru's ``{"card_type": "planeswalker"}``,
    Temple Altisaur's ``{"subtype": "dinosaur", "exclude_self": True}`` for
    "**another** Dinosaur" — ``exclude_self`` resolves to a
    ``without_instance_id`` filter against the shield's own source at match
    time, since that id isn't known until bind time). ``recipient_union`` (a
    list of ``"controller"``/``"any_player"``/filter-dict entries) is the
    "you or a `<X>` you control" shape (Hyperion/Ajani Steadfast's emblem) —
    matches if *any* entry matches; a filter-dict entry always means "a
    controlled permanent matching this filter", the same as
    ``"controlled_permanent"`` above.

    ``source_filter`` narrows *who's dealing* the damage — ``color`` (a
    single WUBRG letter, checked against the event's own precomputed
    ``source_colors``), ``card_type`` (looked up fresh off the source object
    via `GameState.find_object`, mirroring `_additional_damage_replacement`'s
    own "artifact" check — the event carries no type flag of its own),
    ``is_creature``/``is_spell`` (the event's own ``source_is_creature``/
    ``source_is_instant_or_sorcery`` — RULE 609.7a: a resolving instant/
    sorcery *is* "a spell" for this purpose), and ``controller`` (``"you"``/
    ``"opponent"``, against the event's own ``source_controller_id``).

    ``amount`` is an ``int`` (prevent up to that much — ``dealt - amount``
    survives), the string ``"all"`` (fully prevented), ``{"all_but": N}``
    (Temple Altisaur/Hyperion/Ajani's emblem — only ``N`` survives), or
    ``{"half": "up"|"down"}`` (Gisela's "prevent half, rounded up"; Dark
    Sphere's "rounded down"). ``amount_count_selector`` resolves the ``int``
    amount live via `continuous.count_selector` instead (Shield of the
    Avatar/Battletide Alchemist's "X is the number of creatures/Clerics you
    control").

    ``rider`` (``{"kind": ..., "recipient": ...}``) fires a follow-up off the
    *actual* prevented amount once it's known — see
    `RulesEngine.apply_prevent_rider` (Swans of Bryn Argoll/Hostility-shaped
    "…and `<X>` this way").

    Consulted through the same `RulesEngine.apply_replacements` path
    `deal_damage` already runs, so it needs no new plumbing.
    """
    amount = params.get("amount", "all")
    amount_count_selector = params.get("amount_count_selector")
    to = params.get("to", "self")
    recipient_filter = params.get("recipient_filter")
    recipient_union = params.get("recipient_union")
    source_filter = params.get("source_filter")
    rider = params.get("rider")
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
        description=str(params.get("description", "prevent damage")),
    )
    #: MEC-30: marks this as a prevention-shaped effect for "damage can't be
    #: prevented this turn" (Insult // Injury/Isengard Unleashed) to filter
    #: out generically — distinct from `damage_prevention_shield` (which
    #: means "sweep me at cleanup, I'm one-turn-only" and would be *wrong*
    #: to set here: this factory also builds Family A's standing, permanent
    #: shields and Absorb's structural one, none of which expire after one
    #: turn). Covers Absorb for free — `effect_binder.attach_to_object`'s
    #: Absorb branch reuses this exact factory.
    effect.prevents_damage = True

    def _controlled_permanent_matches(
        filt: Optional[dict], event: GameEvent, context: GameContext, src: Any,
    ) -> bool:
        if event.get("is_player") or src is None:
            return False
        target_obj = context.state.find_object(event.get("target_id"))
        if target_obj is None or target_obj.controller_id != src.controller_id:
            return False
        from . import combat  # local: avoid the combat<->effects import cycle

        resolved_filt = dict(filt or {})
        if resolved_filt.pop("exclude_self", False):
            resolved_filt["without_instance_id"] = src.instance_id
        return combat.matches_object_filter(target_obj, resolved_filt)

    def _recipient_entry_matches(entry: Any, event: GameEvent, context: GameContext, src: Any) -> bool:
        if entry == "controller":
            return bool(event.get("is_player")) and src is not None and event.get("target_id") == src.controller_id
        if entry == "any_player":
            return bool(event.get("is_player"))
        if entry == "opponent_player":
            return (
                bool(event.get("is_player")) and src is not None
                and event.get("target_id") != src.controller_id
            )
        return _controlled_permanent_matches(entry, event, context, src)

    def _recipient_matches(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if recipient_union is not None:
            return any(_recipient_entry_matches(e, event, context, src) for e in recipient_union)
        if to == "self":
            return (
                not event.get("is_player") and src is not None
                and event.get("target_id") == src.instance_id
            )
        if to == "attached_permanent":
            host_id = getattr(src, "attached_to", None)
            return (
                not event.get("is_player") and host_id is not None
                and event.get("target_id") == host_id
            )
        if to == "controlled_permanent":
            return _controlled_permanent_matches(recipient_filter, event, context, src)
        if to in ("any_player", "opponent_player"):
            return _recipient_entry_matches(to, event, context, src)
        if to == "any":
            return True
        return _recipient_entry_matches("controller", event, context, src)  # "controller", the default

    def _source_matches(event: GameEvent, context: GameContext) -> bool:
        if not source_filter:
            return True
        src = effect.source
        color = source_filter.get("color")
        if color is not None and color not in (event.get("source_colors") or ()):
            return False
        card_type = source_filter.get("card_type")
        if card_type is not None:
            source_id = event.get("source_id")
            src_obj = context.state.find_object(source_id) if source_id is not None else None
            if src_obj is None or not bool(getattr(src_obj.card, f"is_{card_type}", False)):
                return False
        if source_filter.get("is_creature") and not event.get("source_is_creature"):
            return False
        if source_filter.get("is_spell") and not event.get("source_is_instant_or_sorcery"):
            return False
        controller = source_filter.get("controller")
        if controller is not None:
            shield_controller_id = getattr(src, "controller_id", None)
            if shield_controller_id is None:
                return False
            if controller == "opponent" and event.get("source_controller_id") == shield_controller_id:
                return False
            if controller == "you" and event.get("source_controller_id") != shield_controller_id:
                return False
        return True

    def _survives(dealt: int, src: Any, context: GameContext) -> int:
        if amount_count_selector:
            from . import continuous  # local: avoid the continuous<->effects import cycle

            n = continuous.count_selector(
                context.state, getattr(src, "controller_id", None), amount_count_selector, source=src
            )
            return max(0, dealt - n)
        if isinstance(amount, dict):
            if "all_but" in amount:
                return min(dealt, int(amount["all_but"]))
            if "half" in amount:
                # "rounded up" prevents the larger half, so survives is the
                # floor; "rounded down" prevents the smaller half, so
                # survives is the ceiling.
                return dealt // 2 if amount["half"] == "up" else (dealt + 1) // 2
            return dealt
        if amount == "all":
            return 0
        return max(0, dealt - int(amount))

    def _applies(event: GameEvent, context: GameContext) -> bool:
        return _recipient_matches(event, context) and _source_matches(event, context)

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        dealt = int(event.get("amount", 0) or 0)
        survives = _survives(dealt, effect.source, context)
        prevented = dealt - survives
        if rider is not None and prevented > 0:
            context.engine.apply_prevent_rider(
                rider, prevented, event, getattr(effect.source, "controller_id", None),
                shield_source=effect.source,
            )
        if survives <= 0:
            return None  # fully prevented — the event doesn't happen
        return event.copy_with(amount=survives)

    effect.replacement_fn = replace
    #: RULE 616.1e (MEC-30 fourth pass): `can_replace` must reflect the
    #: card's real printed condition, not just "same event type" — without
    #: this, Gisela's two unrelated replacements (one scoped to opponents,
    #: one to her own side) both reported "applicable" for *every* damage
    #: event, opening a pointless ordering choice each time only one of them
    #: could ever actually do anything.
    effect.condition = _applies
    return effect


def _prevent_damage_convert_counters_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Prevent damage to the source while it has >=1 ``remove_kind`` counter,
    remove up to that many (capped by how many it actually has), then grant
    ``grant_kind`` counters equal to however many were actually removed
    (RULE 615/616 compound shield — Bloatfly Swarm: "If damage would be dealt
    to this creature while it has a +1/+1 counter on it, prevent that
    damage, remove that many +1/+1 counters from it, then give each player a
    rad counter for each +1/+1 counter removed this way").

    "That many" ties the removed-counter count to the damage amount that
    would have been dealt (not a flat number), so this can't be expressed as
    a plain `_prevent_damage_replacement` + a separate one-shot — the removal
    and the grant both need the *actual* damage amount, known only inside
    the replacement itself. ``to`` is always ``"self"`` in practice (the
    only real card needing this protects only its own source); ``grant_
    selector`` reuses `AddPlayerCountersEffect`'s vocabulary (``"each_
    player"``/``"each_opponent"``), read live off `context.state.players`
    rather than through that effect class, since this fires mid-replacement
    (before any stack item exists to carry an `EffectSpec`).
    """
    remove_kind = str(params.get("remove_kind", "+1/+1"))
    grant_kind = str(params.get("grant_kind", "rad"))
    grant_selector = str(params.get("grant_selector", "each_player"))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
        description=str(params.get("description", "")),
    )
    effect.prevents_damage = True  # MEC-30: "damage can't be prevented" filter

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if src is None or event.get("is_player") or event.get("target_id") != src.instance_id:
            return False
        # "…while it has a +1/+1 counter on it" — literally part of the
        # printed condition, not just a value-based no-op.
        return src.counters.get(remove_kind, 0) > 0

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        src = effect.source
        current = src.counters.get(remove_kind, 0)
        dealt = int(event.get("amount", 0) or 0)
        if dealt <= 0:
            return event
        removed = min(current, dealt)
        context.engine.add_counters(src, -removed, remove_kind)
        for player in context.state.players:
            if grant_selector == "each_opponent" and player.id == src.controller_id:
                continue
            context.engine.add_player_counters(player, removed, grant_kind, source=src)
        return None  # fully prevented (RULE 614.5 — the damage never happens)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _double_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Multiplies damage that would be dealt (RULE 614/616), e.g. Furnace of
    Rath/Dictate of the Twin Gods ("if a source would deal damage, it deals
    double that damage instead" — unscoped), Gratuitous Violence ("a
    *creature* you control", ``creature_only``+``your_sources_only``, no
    combat restriction despite the name), or Fiery Emancipation ("a source
    you control", ``multiplier=3``).

    ``combat_only``/``your_sources_only``/``creature_only`` scope the
    effect; ``your_sources_only`` reads the *replacement's own source's*
    controller (``effect.source``, set at bind time) against the damage
    event's ``source_controller_id`` — so it needs the object it's attached
    to on the battlefield to know whose damage counts as "yours".
    ``multiplier`` defaults to 2 (every real "double" card); Fiery
    Emancipation's "triple" is the only real 3.

    ``to_opponent_only`` (MEC-30, Gisela, Blade of Goldnight's own "…deals
    damage to an opponent or a permanent an opponent controls…", paired
    with a separate ``prevent_damage`` replacement for the "you or a
    permanent you control" mirror) scopes the *recipient* side instead —
    mirrors `_additional_damage_replacement`'s own identically-named/-shaped
    param exactly (the *source* qualifiers, on the other hand, stay
    separate concepts: `_additional_damage_replacement`'s ``colors``/
    ``types`` narrow which sources trigger the bonus, orthogonal to which
    recipients count).
    """
    combat_only = bool(params.get("combat_only", False))
    your_sources_only = bool(params.get("your_sources_only", False))
    creature_only = bool(params.get("creature_only", False))
    to_opponent_only = bool(params.get("to_opponent_only", False))
    multiplier = int(params.get("multiplier", 2))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
        # Left empty by default so `bind_ability` falls back to the card's
        # own (German) `raw_text` for the RULE 616.1 ordering-choice label —
        # only an explicit `description` param overrides that.
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        if combat_only and not event.get("combat"):
            return False
        if creature_only and not event.get("source_is_creature"):
            return False
        if your_sources_only:
            src = effect.source
            if src is None or event.get("source_controller_id") != src.controller_id:
                return False
        if to_opponent_only:
            src = effect.source
            if src is None:
                return False
            if event.get("is_player"):
                if event.get("target_id") == src.controller_id:
                    return False
            else:
                target_obj = context.state.find_object(event.get("target_id"))
                if target_obj is not None and target_obj.controller_id == src.controller_id:
                    return False
        return True

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        dealt = int(event.get("amount", 0) or 0)
        if dealt <= 0:
            return event
        return event.copy_with(amount=dealt * multiplier)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _additional_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Damage that would be dealt is increased by a flat ``amount`` instead
    (RULE 614/616), e.g. Torbran, Thane of Red Fell ("if a red source you
    control would deal damage to an opponent or a permanent an opponent
    controls, it deals that much damage plus 2 instead").

    ``your_sources_only`` mirrors `_double_damage_replacement`; ``color``
    (a single RULE 105 letter, e.g. ``"R"``) further restricts to a damage
    source whose printed `Card.color_identity` includes it — a pragmatic
    stand-in for "is that color" (color identity, not true colour, per
    docs/Reference's existing simplifications elsewhere in this engine).
    ``to_opponent_only`` restricts the *target* side ("to an opponent or a
    permanent an opponent controls") to whoever isn't this effect's own
    source's controller — the only notion of "opponent" a 2-player
    goldfish/Replay board has.

    ``colors``/``types`` (Mechanized Warfare's "a red **or** artifact
    source") generalize ``color`` to an OR-combined compound source filter:
    a source qualifies if it matches *any* listed colour (``event``'s own
    ``source_colors``, same as plain ``color``) or *any* listed type word
    (currently only ``"artifact"`` — looked up fresh off the source object's
    printed card via ``event``'s ``source_id``, since `GameEvent.DAMAGE`
    carries no type flag of its own the way it carries ``source_colors``;
    extend the word list here as a real card needs one, mirroring
    `targeting`'s own "extend as needed" precedent). A single legacy
    ``color`` is still accepted standalone (kept for existing callers/tests);
    when either ``colors`` or ``types`` is given, ``color`` is ignored.
    """
    bonus = int(params.get("amount", 0))
    your_sources_only = bool(params.get("your_sources_only", False))
    to_opponent_only = bool(params.get("to_opponent_only", False))
    colors = list(params.get("colors") or ([params["color"]] if params.get("color") else []))
    types = list(params.get("types") or [])
    is_spell = bool(params.get("is_spell", False))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _source_matches(event: GameEvent, context: GameContext) -> bool:
        # "If a **spell** would deal damage…" (Rem Karolus, Stalwart
        # Slayer, MEC-30) — RULE 609.7a: a resolving instant/sorcery is
        # "a spell" for this purpose, the event's own precomputed flag
        # `_prevent_damage_replacement`'s own ``is_spell`` check already
        # reads for the exact same phrase on this card's paired prevention
        # clause.
        if is_spell and not event.get("source_is_instant_or_sorcery"):
            return False
        if not colors and not types:
            return True
        if colors and any(c in (event.get("source_colors") or ()) for c in colors):
            return True
        if types:
            source_id = event.get("source_id")
            src_obj = context.state.find_object(source_id) if source_id is not None else None
            if src_obj is not None:
                for type_word in types:
                    if type_word == "artifact" and bool(src_obj.card.is_artifact):
                        return True
        return False

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if your_sources_only:
            if src is None or event.get("source_controller_id") != src.controller_id:
                return False
        if to_opponent_only:
            if src is None:
                return False
            if event.get("is_player"):
                if event.get("target_id") == src.controller_id:
                    return False
            else:
                target_obj = context.state.find_object(event.get("target_id"))
                if target_obj is not None and target_obj.controller_id == src.controller_id:
                    return False
        return _source_matches(event, context)

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        dealt = int(event.get("amount", 0) or 0)
        if dealt <= 0:
            return event
        return event.copy_with(amount=dealt + bonus)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _damage_floor_from_source_power_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If a red source you control would deal an amount of noncombat
    damage less than ~'s power to an opponent, that source deals damage
    equal to ~'s power instead." (Ojer Axonil, Deepest Might) —
    `_additional_damage_replacement`'s floor-shaped sibling: unlike a flat
    bonus, the *threshold and the replacement amount are the same live
    value* (this ability's own source's current power, RULE 613.1), read
    fresh every firing rather than baked in at bind time.
    """
    colors = list(params.get("colors") or ([params["color"]] if params.get("color") else []))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if src is None or event.get("source_controller_id") != src.controller_id:
            return False
        if event.get("combat"):
            return False
        if colors and not any(c in (event.get("source_colors") or ()) for c in colors):
            return False
        if event.get("is_player"):
            if event.get("target_id") == src.controller_id:
                return False
        else:
            target_obj = context.state.find_object(event.get("target_id"))
            if target_obj is None or target_obj.controller_id == src.controller_id:
                return False
        # "…damage less than ~'s power" — the threshold comparison is the
        # printed condition itself, not an incidental no-op.
        threshold = int(getattr(src, "power", 0) or 0)
        dealt = int(event.get("amount", 0) or 0)
        return 0 < dealt < threshold

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        threshold = int(getattr(effect.source, "power", 0) or 0)
        return event.copy_with(amount=threshold)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _double_counters_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Counters that would be placed are doubled instead (RULE 122/614/616),
    e.g. Doubling Season's counter clause: "if an effect would put one or
    more counters on a permanent you control, it puts twice that many
    instead" — deliberately *not* scoped by ``kind`` (omitted, every kind is
    doubled) unless ``kind`` narrows it to one (``"+1/+1"``, ``"loyalty"``, …).

    ``your_effects_only`` (Innkeeper's Talent's "if **you** would put one or
    more counters on a permanent or player, put twice that many… instead")
    is a *different* scoping axis from Doubling Season's own real wording —
    Doubling Season reads the counters' **recipient**'s controller (handled
    by whatever `condition`/binder scoping wraps this replacement, not this
    function), while this flag reads who's **causing** the placement: it
    only doubles a `RulesEngine.add_counters`/`add_player_counters` call
    that named this effect's own source as its ``source`` (via the event's
    ``source_controller_id``, mirroring `_additional_damage_replacement`'s
    ``your_sources_only``) — irrespective of whose permanent or player ends
    up with the counters, which is exactly why the same unscoped
    `EventType.COUNTER` handling below already covers "or player" for free
    once a caller (`RulesEngine.add_player_counters`) fires that event for a
    player recipient too.

    ``plus`` (default ``None``) switches from the multiplicative "twice that
    many" to the *additive* "that many plus N" shape (Hardened Scales/
    Conclave Mentor's "that many plus one +1/+1 counters", RULE 616.1);
    ``multiplier`` (default 2) is the "twice"/"triple" factor otherwise.
    ``recipient`` scopes by the counters' recipient rather than the causer:
    ``"creature_you_control"`` (Branching Evolution/Corpsejack Menace/
    Hardened Scales — a creature this effect's source controls) or
    ``"permanent_you_control"`` (Kami of Whispered Hopes — any permanent);
    read off the event's ``recipient_controller_id``/``recipient_is_
    creature`` against ``effect.source``'s controller.
    """
    kind_filter = params.get("kind")
    your_effects_only = bool(params.get("your_effects_only", False))
    plus = params.get("plus")
    multiplier = int(params.get("multiplier", 2))
    recipient = params.get("recipient")
    effect = ReplacementEffect(
        event_type=EventType.COUNTER,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        if kind_filter and event.get("kind") != kind_filter:
            return False
        if your_effects_only:
            src = effect.source
            if src is None or event.get("source_controller_id") != src.controller_id:
                return False
        if recipient is not None:
            src = effect.source
            if src is None or event.get("recipient_controller_id") != src.controller_id:
                return False
            if recipient == "creature_you_control" and not event.get("recipient_is_creature"):
                return False
        return True

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        amount = int(event.get("amount", 0) or 0)
        if amount <= 0:
            return event
        new_amount = amount + int(plus) if plus is not None else amount * multiplier
        return event.copy_with(amount=new_amount)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _draw_exile_face_up_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If a player would draw a card, that player exiles that card face up
    instead. Each player may play lands and cast spells from among cards
    they exiled with ~ this turn." (Uba Mask, MEC-43) — unscoped (every
    player's every draw), fired per-card since `RulesEngine._single_draw`
    is the choke point every draw (including a multi-draw's own per-card
    loop) already funnels through.

    Consumes the `EventType.DRAW` event (returns ``None``) and performs the
    zone move itself as a side effect — the same "the fn *is* the effect,
    not just a rewrite" shape `_die_to_exile_replacement` uses — since
    there's no sensible rewritten *draw* event to hand back (the card never
    reaches hand at all). Grants `GameState.temp_play_permissions` the
    instant the card lands in exile, the same "castable/playable from
    exile this turn" marker `RulesEngine.grant_free_cast_window_from_exile`
    already uses, so both the land-play and the cast-legality checks pick
    it up with no new permission channel needed. An empty library is left
    to the ordinary draw-from-empty loss path (RULE 104.3c) rather than
    redirected — nothing exists yet to exile.
    """
    effect = ReplacementEffect(
        event_type=EventType.DRAW,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        player_id = event.get("player_id")
        try:
            player = context.state.player_by_id(player_id)
        except (KeyError, ValueError):
            return event
        if not player.library:
            return event  # empty library: let the normal draw-loss path see it
        obj = player.library.pop()
        obj.zone = Zone.EXILE
        player.exile.append(obj)
        context.state.temp_play_permissions[obj.instance_id] = context.state.turn_number
        return None  # event consumed — the card never reaches hand

    effect.replacement_fn = replace
    return effect


def _die_to_exile_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If ~ would die, exile it instead" (RULE 616.1) — redirects a
    creature's battlefield→graveyard move to exile. Modeled like
    regeneration's shield: the fn performs the exile as a side effect and
    returns ``None`` to consume the `EventType.WOULD_DIE` event, so
    `RulesEngine._move_to_graveyard` skips the graveyard move.

    ``subject`` scopes which creatures it covers, read off the event's
    ``target_id``/``controller_id`` against ``effect.source``:
    ``"self"`` (Gloomshrieker — only the source itself), ``"you_control"``
    (a creature its controller controls), ``"opponents_control"``
    (Corpseweaver Prodigy — a creature an opponent controls), or ``"any"``.
    """
    subject = params.get("subject", "self")
    effect = ReplacementEffect(
        event_type=EventType.WOULD_DIE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        controller_id = event.get("controller_id")
        target_id = event.get("target_id")
        if subject == "self":
            return src is not None and target_id == getattr(src, "instance_id", None)
        if subject == "you_control":
            return src is not None and controller_id == src.controller_id
        if subject == "opponents_control":
            return src is not None and controller_id not in (None, src.controller_id)
        return True  # "any"

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        obj = context.state.find_object(event.get("target_id"))
        if obj is None:
            return event  # already gone — let the normal path no-op
        context.engine.exile(obj)
        return None  # event consumed; the graveyard move is replaced by exile

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _gain_life_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """A life gain is rewritten instead (RULE 119.3/616.1) — the *additive*
    "you gain that much life plus N instead" (Angel of Vitality, ``plus``)
    or the *multiplicative* "you gain twice that much life instead" (Boon
    Reflection/Alhammarret's Archive/Rhox Faithmender, ``multiplier``,
    default 2). Always scoped to the effect's own controller ("if **you**
    would gain life"), read off the `EventType.LIFE_GAIN` event's
    ``player_id`` against ``effect.source``'s controller — every real card
    with this clause is a permanent whose controller is the gaining player.
    """
    plus = params.get("plus")
    multiplier = int(params.get("multiplier", 2))
    effect = ReplacementEffect(
        event_type=EventType.LIFE_GAIN,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        return src is not None and event.get("player_id") == src.controller_id

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        amount = int(event.get("amount", 0) or 0)
        if amount <= 0:
            return event
        new_amount = amount + int(plus) if plus is not None else amount * multiplier
        return event.copy_with(amount=new_amount)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _double_tokens_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Tokens that would be created under *this effect's controller* are
    doubled instead (RULE 111.5/614/616) — Doubling Season's/Parallel
    Lives' token clause: "if an effect would create one or more tokens
    under your control, it creates twice that many instead". Unlike the
    counter clause above this *is* controller-scoped in the real text.
    """
    effect = ReplacementEffect(
        event_type=EventType.CREATE_TOKENS,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        return src is not None and event.get("controller_id") == src.controller_id

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        amount = int(event.get("amount", 0) or 0)
        if amount <= 0:
            return event
        return event.copy_with(amount=amount * 2)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


#: The named-token vocabulary `_create_one_of_each_named_token_replacement`/
#: `_additional_named_token_replacement` build from — same closed
#: Treasure/Clue/Food set `parser.oracle.catalogue.handlers._NAMED_TOKEN_
#: WORDS` trusts (`services/token_database.py`'s curated `TokenDatabase`,
#: so the extra token keeps its own real activated ability).
_NAMED_TOKEN_DISPLAY_NAMES: tuple[str, ...] = ("Clue", "Food", "Treasure")


def _create_one_of_each_named_token_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If you would create a Clue, Food, or Treasure token, instead create
    one of each." (Academy Manufactor) — the original creation goes through
    unmodified (RULE 616 doesn't need to touch ``amount`` here), and the
    *other two* named tokens are created as a side effect alongside it.

    A side-effect `context.create_token` call is itself a new CREATE_TOKENS
    event this same replacement would otherwise see again — the ``_busy``
    re-entrancy guard on the `ReplacementEffect` instance is what stops that
    from looping (a Clue's own creation, made *by* this replacement, must
    not re-trigger it a second time).
    """
    effect = ReplacementEffect(
        event_type=EventType.CREATE_TOKENS,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )
    effect._busy = False  # type: ignore[attr-defined]

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        if src is None or event.get("controller_id") != src.controller_id:
            return False
        if effect._busy:  # type: ignore[attr-defined]
            return False
        return event.get("token_name") in _NAMED_TOKEN_DISPLAY_NAMES

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        src = effect.source
        token_name = event.get("token_name")
        effect._busy = True  # type: ignore[attr-defined]
        try:
            from ..services.token_database import default_token_database

            db = default_token_database()
            for name in _NAMED_TOKEN_DISPLAY_NAMES:
                if name == token_name:
                    continue
                card = db.get_token(name)
                if card is not None:
                    context.create_token(src.controller_id, card, 1)
        finally:
            effect._busy = False  # type: ignore[attr-defined]
        return event

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _additional_named_token_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If one or more tokens would be created under your control, those
    tokens plus an additional Food token are created instead." (Peregrin
    Took) — ``token_name`` (default "Food") names the extra token; every
    token creation under this effect's controller gets one more of it
    alongside, guarded by the same ``_busy`` re-entrancy flag `_create_
    one_of_each_named_token_replacement` uses (the extra token's own
    creation must not trigger *another* extra token).
    """
    extra_name = str(params.get("token_name", "Food"))
    effect = ReplacementEffect(
        event_type=EventType.CREATE_TOKENS,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )
    effect._busy = False  # type: ignore[attr-defined]

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        if src is None or event.get("controller_id") != src.controller_id:
            return False
        return not effect._busy  # type: ignore[attr-defined]

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        src = effect.source
        effect._busy = True  # type: ignore[attr-defined]
        try:
            from ..services.token_database import default_token_database

            card = default_token_database().get_token(extra_name)
            if card is not None:
                context.create_token(src.controller_id, card, 1)
        finally:
            effect._busy = False  # type: ignore[attr-defined]
        return event

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _win_instead_of_empty_draw_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If you would draw a card while your library has no cards in it, you
    win the game instead." (Jace, Wielder of Mysteries/Laboratory Maniac,
    RULE 104.3a-adjacent alternative win condition) — intercepts the DRAW
    event for this effect's own source's controller: if their library is
    already empty, the draw is replaced with an outright win (`RulesEngine.
    player_wins`) and cancelled (returns ``None`` — RULE 614.5, the draw
    itself never happens, so the ordinary "drew from an empty library ⇒
    loses" state-based action never gets a chance to fire either). A draw
    with cards still in the library passes through unchanged.
    """
    effect = ReplacementEffect(
        event_type=EventType.DRAW,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        controller_id = getattr(src, "controller_id", None)
        if controller_id is None or event.get("player_id") != controller_id:
            return False
        try:
            player = context.state.player_by_id(controller_id)
        except Exception:
            return False
        # "…while your library has no cards in it" — the printed condition
        # itself, not an incidental no-op.
        return not player.library

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        player = context.state.player_by_id(getattr(effect.source, "controller_id"))
        context.engine.player_wins(player)
        return None

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _split_multi_draw_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If an opponent would draw two or more cards, instead you and that
    player each draw a card." (Alms Collector, MEC-32, RULE 616.1) —
    intercepts `EventType.DRAW_INSTRUCTION` (`RulesEngine.draw`'s own
    aggregate event, fired once per ``draw()`` call before it's split into
    individual per-card `EventType.DRAW` events) rather than the ordinary
    per-card event every other draw replacement in this file reads: the
    "two or more" test is about the whole attempted instruction, which no
    per-card event can see. ``min_count`` (default 2) is the printed
    threshold. The whole original instruction is cancelled (returns
    ``None``) and replaced by exactly one fresh, un-doubled `draw()` call
    for each player — so neither resulting draw's own count ever reaches
    ``min_count`` again, and this doesn't re-trigger itself.
    """
    min_count = int(params.get("min_count", 2))
    effect = ReplacementEffect(
        event_type=EventType.DRAW_INSTRUCTION,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if src is None:
            return False
        opponent_id = event.get("player_id")
        if opponent_id is None or opponent_id == src.controller_id:
            return False
        return event.get("count", 1) >= min_count

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        opponent = context.state.player_by_id(event.get("player_id"))
        controller = context.state.player_by_id(src.controller_id)
        context.draw(opponent, 1)
        context.draw(controller, 1)
        return None

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _steal_non_first_draw_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If an opponent would draw a card except the first one they draw in
    each of their draw steps, instead that player skips that draw and you
    draw a card." (Notion Thief, MEC-32, RULE 616.1) — the per-card sibling
    of Alms Collector's instruction-level replacement above: reads the
    ordinary per-card `EventType.DRAW` event's own ``first_in_draw_step``
    flag (`RulesEngine._single_draw`, computed live off the new
    `GameState.first_draw_done_this_step` per-player tracker reset each
    time a player's own draw step begins, `game/engine/turn_loop_mixin.py`'s
    `_run_step`) rather than re-deriving position from `cards_drawn_this_
    turn`, since a draw from an unrelated spell elsewhere in the same turn
    must not count as "the step's own first draw."
    """
    effect = ReplacementEffect(
        event_type=EventType.DRAW,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if src is None:
            return False
        opponent_id = event.get("player_id")
        if opponent_id is None or opponent_id == src.controller_id:
            return False
        return not event.get("first_in_draw_step")

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        controller = context.state.player_by_id(effect.source.controller_id)
        context.draw(controller, 1)
        return None

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _discard_instead_of_non_first_draw_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If a player would draw a card except the first one they draw in
    each of their draw steps, that player discards a card instead. If the
    player discards a card this way, they draw a card. If the player
    doesn't discard a card this way, they mill a card." (Chains of
    Mephistopheles, MEC-32, RULE 616.1) — reads the same ``first_in_draw_
    step`` flag `_steal_non_first_draw_replacement` reads, but applies
    table-wide (no opponent/you scoping at all, unlike Notion Thief) and
    its own compensating draw is a fresh `RulesEngine.draw` call that can
    (and, per the printed card, should) be replaced by this same effect
    again if the affected player's hand still has a card to discard —
    RULE 616.1f's "repeat this process until there are no more applicable
    replacement effects" loop terminates naturally once their hand empties
    (each recursive discard strictly shrinks it), at which point the
    "doesn't discard this way" branch mills instead of drawing. The
    discard itself is the engine's ordinary non-interactive `RulesEngine.
    discard` (auto-chosen, no chooser in MVP) — the same documented
    simplification every other untargeted discard in this engine already
    uses, not something new to this card.
    """
    effect = ReplacementEffect(
        event_type=EventType.DRAW,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        return not event.get("first_in_draw_step")

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        player = context.state.player_by_id(event.get("player_id"))
        if player.hand:
            context.discard(player, 1)
            context.draw(player, 1)
        else:
            context.mill(player, 1)
        return None

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


class ReplacementRegistry:
    """Maps a whitelisted replacement-type name to a `ReplacementEffect` factory.

    The replacement analogue of `EffectRegistry` (docs/09 security boundary):
    the binder turns a ``replacement`` `AbilitySpec` into behaviour only through
    a name registered here, so nothing derived from card text becomes an
    arbitrary callable."""

    _factories: dict[str, Callable[[dict[str, Any]], ReplacementEffect]] = {}

    @classmethod
    def register(cls, name: str, factory: Callable[[dict[str, Any]], ReplacementEffect]) -> None:
        cls._factories[name] = factory

    @classmethod
    def create(cls, name: str, params: Optional[dict[str, Any]] = None) -> ReplacementEffect:
        if name not in cls._factories:
            raise ValueError(f"unknown replacement type: {name!r}")
        return cls._factories[name](params or {})

    @classmethod
    def is_registered(cls, name: str) -> bool:
        return name in cls._factories


ReplacementRegistry.register("prevent_damage", _prevent_damage_replacement)
ReplacementRegistry.register("prevent_damage_convert_counters", _prevent_damage_convert_counters_replacement)
ReplacementRegistry.register("double_damage", _double_damage_replacement)
ReplacementRegistry.register("additional_damage", _additional_damage_replacement)
ReplacementRegistry.register("damage_floor_from_source_power", _damage_floor_from_source_power_replacement)
ReplacementRegistry.register("double_counters", _double_counters_replacement)
ReplacementRegistry.register("gain_life_replacement", _gain_life_replacement)
ReplacementRegistry.register("die_to_exile", _die_to_exile_replacement)
ReplacementRegistry.register("draw_exile_face_up", _draw_exile_face_up_replacement)
ReplacementRegistry.register("double_tokens", _double_tokens_replacement)
ReplacementRegistry.register("create_one_of_each_named_token", _create_one_of_each_named_token_replacement)
ReplacementRegistry.register("additional_named_token", _additional_named_token_replacement)
ReplacementRegistry.register("win_instead_of_empty_draw", _win_instead_of_empty_draw_replacement)
ReplacementRegistry.register("split_multi_draw", _split_multi_draw_replacement)
ReplacementRegistry.register("steal_non_first_draw", _steal_non_first_draw_replacement)
ReplacementRegistry.register("discard_instead_of_non_first_draw", _discard_instead_of_non_first_draw_replacement)
