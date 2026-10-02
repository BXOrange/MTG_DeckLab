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

import contextlib
import random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from ...models.cards import card_query
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import Zone
from ...models.mana.mana_cost import ManaCost
from .. import effect_conditions
from ..targeting import TargetSpec, all_requirements_satisfiable, requirements_with_targets

if TYPE_CHECKING:  # avoid an import cycle with rules_engine at runtime
    from ...models.game.game_object import GameObject
    from ...models.game.game_state import GameState, StackItem
    from ...models.game.player import Player
    from ..costs import ActivationCost
    from ..rules_engine import RulesEngine


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
        #: PAR-123: the player "you" means while a body runs *as someone else* — "**its
        #: controller** creates a 1/1 Snake token" is the ordinary "you create a token" done by
        #: the firing object's controller (RULE 109.5: the player an ability's "you" names).
        #: ``None`` (always, outside `TriggerSubjectReferentEffect`'s ``acting`` body) leaves
        #: "you" as the source's controller; `_controller_of` and
        #: `effect_conditions._controller_id` are the two places that read it.
        self.acting_player_id: Optional[str] = None
        #: Which resolution this turn of the ability now resolving this is
        #: (1 = first), set by `RulesEngine.resolve_top_of_stack` for exactly
        #: that window — the ``ability_resolution_count`` condition reads it.
        #: ``None`` outside an ability's resolution.
        self.ability_resolution_count: Optional[int] = None
        #: ENG-35: the item the enclosing `for_each`-style loop is currently
        #: on, or ``None`` outside one. Set and restored by
        #: `RulesEngine._resume_iteration` around each pass of a parked loop
        #: body, so a clause inside the body can name "that creature" /
        #: "that player" for *its* iteration rather than for the whole
        #: selector — the per-iteration sibling of `previous_targets`.
        #:
        #: Deliberately scoped like `trigger_event` (saved, set, restored)
        #: rather than left standing, so a nested loop cannot leak its item
        #: to the outer one, and so a resolution that is not iterating at
        #: all reads ``None`` instead of a stale value.
        self.iteration_item: Any = None
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
        #: Objects a preceding zone-changing instruction moved during this
        #: resolution (the exact "this way" batch for a later measurement).
        self.moved_objects: list[Any] = []
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
        #: The card a `reveal_top` clause earlier in this same resolution
        #: revealed (RULE 701.20), still in its owner's library — the
        #: referent behind "**it**" / "that card" in "reveal the top card …
        #: if it's a land card, put it onto the battlefield". Read by
        #: `effect_conditions`/`effect_amounts` as ``of: "revealed"``.
        #: Same save/reset/restore idiom in `_apply_effects_partitioned` as
        #: `previous_selector`.
        self.revealed_card: Optional[Any] = None
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
        #: "Exile all creatures. Incubate X, where X is the number of
        #: creatures **exiled this way**." (Sunfall) — the exile sibling of
        #: `permanents_destroyed_this_way`, bumped by `exile` below for
        #: every object that actually left its zone this resolution
        #: (a protection/hexproof no-op doesn't reach here — `context.exile`
        #: is only called on objects the effect already resolved onto).
        #: Read by `CreateTokenEffect.extra_counters`' ``count_from_context``
        #: key. Same save/reset/restore idiom in `_apply_effects_partitioned`.
        self.objects_exiled_this_way: int = 0
        #: "Remove all charge counters from ~. Add 1 mana of any color for
        #: each charge counter removed this way." (Coalition Relic/Ventifact
        #: Bottle) — `permanents_destroyed_this_way`'s counter sibling
        #: (PAR-66), bumped by `RemoveCountersEffect` for every counter
        #: actually stripped this resolution (an empty target has nothing to
        #: remove and contributes 0, same as a hexproof/indestructible no-op
        #: elsewhere). Read by a following effect's own
        #: ``count_selector="counters_removed_this_way"`` (`GainLifeEffect`)
        #: or ``amount_from_context="counters_removed_this_way"``
        #: (`AddManaEffect`/`AddCountersEffect`). Same save/reset/restore
        #: idiom as `objects_exiled_this_way`.
        self.counters_removed_this_way: int = 0
        #: MEC-81: the permanents an earlier `deal_damage` clause of this same
        #: resolution **actually dealt damage to** (RULE 616 — "If a creature
        #: dealt damage this way would die this turn, exile it instead."; Anger
        #: of the Gods / Crush the Weak / Serpentine Spike / Demonfire). The
        #: object-list sibling of `previous_targets`, and the reason it isn't
        #: enough: mass damage ("deals N to each creature") and multi-target
        #: damage never populate `previous_targets` with the hit set, so a
        #: `grant_die_to_exile_this_turn` rider after them had to fail closed.
        #: Appended to (not replaced) by `GameContext.deal_damage` for every
        #: `GameObject` whose `damage_marked` actually rose; save/reset/restore
        #: in `_apply_effects_partitioned`, same idiom as `created_objects`.
        self.damaged_this_way: list[Any] = []
        #: RULE 701.30: whether this resolution's most recent `ClashEffect`
        #: won its clash (RULE 701.30d), or ``None`` if no clash has happened
        #: in it. Read by a following `ConditionalEffect(condition=
        #: {"clash_won": True/False})` — the "clash with an opponent. **if you
        #: win**, `<effect>`. **otherwise**, `<effect>`." branch — the same
        #: within-one-resolution referent idiom as `previous_targets`, since
        #: the clash clause and its conditional clause are always siblings in
        #: one effect list. `_apply_effects_partitioned`'s save/reset/restore
        #: idiom (reset to ``None`` per resolution, outer value restored
        #: after, so a nested trigger resolution can't see a stale win).
        self.clash_won: Optional[bool] = None
        #: RULE 701.30b: the opponent the preceding `ClashEffect` in this
        #: resolution clashed "with" (a `Player`), for a "that player"
        #: referent in the win/otherwise branch — Captivating Glance
        #: ("otherwise, that player gains control …"), Pollen Lullaby
        #: ("creatures that player controls don't untap …"). Same
        #: save/reset/restore idiom as `clash_won`.
        self.clashed_opponent: Optional["Player"] = None
        #: RULE 706.3a: the total of this resolution's most recent
        #: `RollDieEffect` roll (the sum of the kept dice — "the result" a
        #: results table is read against), or ``None`` if nothing has rolled
        #: in it. ``die_results`` is every kept die individually (for a
        #: "first result"/"second result" reader), and ``rolled_doubles`` is
        #: RULE 706.5. Read by a following `ConditionalEffect(condition=
        #: {"die_result_at_least": N})` and by the results-table branch
        #: `RollDieEffect` applies itself. Same save/reset/restore idiom as
        #: `clash_won` (reset per resolution, outer value restored after, so
        #: a nested trigger resolution can't see a stale roll).
        self.die_result: Optional[int] = None
        self.die_results: list[int] = []
        self.rolled_doubles: bool = False
        #: RULE 706's other randomization — "a number from A to B chosen at
        #: random" (`RandomNumberEffect`), deliberately separate from
        #: ``die_result`` since only a literal "roll a die" is subject to
        #: RULE 706.11's dice-replacement effects. Same save/reset/restore
        #: idiom as ``die_result`` in `_apply_effects_partitioned`.
        self.random_result: Optional[int] = None

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
        # MEC-81: record the actual hit set for a following "if a creature
        # dealt damage this way would die this turn, exile it instead" rider.
        # Before/after `damage_marked` check, the same "only a real effect
        # counts" idiom as `destroy`/`lose_life` — a prevented or 0 hit, or a
        # hit on a player, does not land in `damaged_this_way`.
        before = int(getattr(target, "damage_marked", 0) or 0) if hasattr(target, "instance_id") else None
        self.engine.deal_damage(target, amount, source, single_target_hint=single_target_hint)
        if before is not None and int(getattr(target, "damage_marked", 0) or 0) > before:
            if target not in self.damaged_this_way:
                self.damaged_this_way.append(target)

    def draw(self, player: "Player", count: int = 1) -> None:
        self.engine.draw(player, count)

    def discard(
        self, player: "Player", count: int = 1, cause: Optional["GameObject"] = None,
    ) -> None:
        self.engine.discard(player, count, cause=cause)

    def discard_random(
        self, player: "Player", count: int = 1, cause: Optional["GameObject"] = None,
    ) -> None:
        self.engine.discard_random(player, count, cause=cause)

    def discard_specific(
        self, target: "GameObject", cause: Optional["GameObject"] = None,
    ) -> None:
        """Discard one already-identified hand card (RULE 701.8)."""
        self.engine.discard_specific(target, cause=cause)

    def discard_choice(
        self,
        player: "Player",
        count: int = 1,
        source: Optional["GameObject"] = None,
        then_specs: Optional[list[dict]] = None,
        optional: bool = False,
    ) -> None:
        self.engine.discard_choice(
            player, count, source=source, then_specs=then_specs, optional=optional
        )

    def discard_matching(
        self, player: "Player", mana_value: Optional[int] = None,
        cause: Optional["GameObject"] = None,
    ) -> None:
        self.engine.discard_matching(player, mana_value=mana_value, cause=cause)

    def look_at_hand(self, player: "Player", owner: "Player", source: Optional["GameObject"] = None) -> None:
        self.engine.look_at_hand(player, owner, source=source)

    def exile_hand_choice(
        self,
        player: "Player",
        count: int = 1,
        source: Optional["GameObject"] = None,
        then_specs: Optional[list[dict]] = None,
        optional: bool = False,
        zone: str = "hand",
    ) -> None:
        self.engine.exile_hand_choice(
            player, count, source=source, then_specs=then_specs, optional=optional, zone=zone
        )

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
        from ...models.game.game_object import Zone

        was_elsewhere = getattr(target, "zone", None) != Zone.EXILE
        self.engine.exile(target)
        # `self.objects_exiled_this_way`'s bookkeeping (Sunfall) — count an
        # object that genuinely moved *into* exile this resolution,
        # mirroring `destroy`'s before/after check.
        if was_elsewhere and getattr(target, "zone", None) == Zone.EXILE:
            self.objects_exiled_this_way += 1

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

    def harness(self, target: "GameObject") -> bool:
        # MEC-79 / RULE 701.64a.
        return self.engine.harness(target)

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

    def increase_speed(self, player: "Player", amount: int = 1) -> None:
        # PAR-28 / RULE 702.179c-d.
        self.engine.increase_speed(player, amount)

    def create_emblem(self, player: "Player", ability: dict) -> None:
        self.engine.create_emblem(player, ability)

    def venture_into_the_dungeon(self, player: "Player", dungeon: Optional[str] = None) -> None:
        # RULE 701.49; ``dungeon`` is 701.49d's "venture into [quality]".
        self.engine.venture_into_the_dungeon(player, dungeon)

    def complete_dungeon(self, player: "Player") -> None:
        # RULE 309.6/309.7.
        self.engine.complete_dungeon(player)

    def manifest(self, player: "Player", count: int = 1, kind: str = "manifest") -> list[Any]:
        # RULE 701.40a manifest / RULE 701.58a cloak.
        return self.engine.manifest(player, count, kind=kind) or []

    def _request_manifest_dread(self, player: "Player") -> list[Any]:
        # RULE 701.40a's look-at-two variant.
        return self.engine._request_manifest_dread(player) or []

    def take_extra_turn(self, player: "Player") -> None:
        # RULE 500.7: queue an extra turn for ``player``, taken after the
        # current one (`GameEngine.begin_turn` consumes `state.extra_turns`).
        self.state.extra_turns.append(player.id)

    def set_tapped(self, target: "GameObject", tapped: bool = True) -> None:
        self.engine.set_tapped(target, tapped)

    def attach_to_target(
        self, source: "GameObject", target: "GameObject", check_control: bool = True
    ) -> None:
        self.engine.attach_to_target(source, target, check_control=check_control)

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

    def look_reorder_top(
        self, player: "Player", count: int = 1, library_owner: Optional["Player"] = None,
        source: Optional["GameObject"] = None, may_shuffle: bool = False,
    ) -> None:
        self.engine.look_reorder_top(
            player, count, library_owner=library_owner, source=source, may_shuffle=may_shuffle,
        )

    def surveil(self, player: "Player", count: int = 1, source: Optional["GameObject"] = None) -> None:
        self.engine.surveil(player, count, source=source)

    def fateseal(
        self, player: "Player", count: int = 1,
        opponent: Optional["Player"] = None, source: Optional["GameObject"] = None,
    ) -> None:
        self.engine.fateseal(player, count, opponent=opponent, source=source)

    def look_top_select(
        self,
        player: "Player",
        count: int,
        select_count: int,
        rest_destination: str,
        rest_order: Optional[str] = None,
        select_optional: bool = False,
        select_filter: Optional[dict[str, Any]] = None,
    ) -> None:
        self.engine.look_top_select(
            player, count, select_count, rest_destination, rest_order,
            select_optional=select_optional, select_filter=select_filter,
        )

    def recompute(self) -> None:
        """Re-derive continuous characteristics now (RULE 613) — used by an
        effect that changes derived P/T mid-resolution (a pump)."""
        from .. import continuous  # function-scoped: avoid an import cycle

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
        set_colors: Optional[list[str]] = None,
        add_colors: Optional[list[str]] = None,
    ) -> list[Any]:
        # Returns what it made, same as `create_token` — see `created_objects`.
        return self.engine.copy_permanent(
            controller_id, source, count,
            add_types=add_types, add_subtypes=add_subtypes, not_legendary=not_legendary,
            set_power=set_power, set_toughness=set_toughness, set_colors=set_colors,
            add_colors=add_colors,
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

    def conjure_duplicate_into_hand(
        self, target: Any, controller_id: str,
    ) -> Optional["GameObject"]:
        return self.engine.conjure_duplicate_into_hand(target, controller_id)

    def copy_ability(
        self, target: Any, controller_id: str, new_targets: Optional[list] = None,
    ) -> None:
        self.engine.copy_ability(target, controller_id, new_targets)

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
        add_keywords: Optional[list] = None,
        not_legendary: bool = False,
    ) -> None:
        self.engine.become_copy(
            obj, target, add_types, add_subtypes, add_keywords=add_keywords, not_legendary=not_legendary,
        )

    def become_copy_until_end_of_turn(
        self,
        obj: "GameObject",
        target: "GameObject",
        add_types: Optional[list] = None,
        add_subtypes: Optional[list] = None,
        add_keywords: Optional[list] = None,
        not_legendary: bool = False,
    ) -> None:
        self.engine.become_copy_until_end_of_turn(
            obj, target, add_types, add_subtypes, add_keywords=add_keywords, not_legendary=not_legendary,
        )

    def set_copy_target(self, obj: "GameObject", target: "GameObject") -> None:
        self.engine.set_copy_target(obj, target)

    def gain_life(self, player: "Player", amount: int) -> None:
        self.engine.gain_life(player, amount)

    def prevent_damage_to_player(
        self, player: "Player", amount: Union[int, str] = "all",
        watched_source_id: Optional[int] = None,
        rider: Optional[dict] = None,
        combat_only: bool = False,
        source_filter: Optional[dict] = None,
    ) -> None:
        self.engine.prevent_damage_to_player(
            player, amount, watched_source_id=watched_source_id,
            rider=rider, combat_only=combat_only, source_filter=source_filter,
        )

    def prevent_life_gain_this_turn(self, players: list["Player"]) -> None:
        self.engine.prevent_life_gain_this_turn(players)

    def grant_cant_lose_this_turn(self, player: "Player") -> None:
        self.engine.grant_cant_lose_this_turn(player)

    def cap_damage_life_floor(self, player: "Player", floor: int = 1) -> None:
        self.engine.cap_damage_life_floor(player, floor)

    def prevent_damage_to_target(
        self, target: Any, amount: Union[int, str] = "all", source_filter: Optional[dict] = None,
        rider: Optional[dict] = None, shield_controller_id: Optional[str] = None,
    ) -> None:
        self.engine.prevent_damage_to_target(
            target, amount, source_filter=source_filter, rider=rider, shield_controller_id=shield_controller_id,
        )

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

    def _request_search(
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
        then_specs_if_none: Optional[list[dict]] = None,
        source: Optional["GameObject"] = None,
        track_exiled_with: bool = False,
        untap_if_lands_at_least: Optional[int] = None,
        then_specs: Optional[list[dict]] = None,
    ) -> None:
        self.engine._request_search(
            player, criteria, destination, count, optional,
            zones=zones, destinations=destinations, exile_rest=exile_rest,
            extra_counters=extra_counters, destination_if=destination_if,
            attach_to_creature_you_control=attach_to_creature_you_control,
            remember_source_id=remember_source_id,
            total_mana_value_budget=total_mana_value_budget,
            chooser=chooser,
            share_land_type=share_land_type,
            then_specs_if_none=then_specs_if_none,
            source=source,
            track_exiled_with=track_exiled_with,
            untap_if_lands_at_least=untap_if_lands_at_least,
            then_specs=then_specs,
        )

    def _request_intuition(
        self, searcher: "Player", chooser_id: str, count: int, source: Optional["GameObject"] = None,
        search_optional: bool = False, distinct_names: bool = False,
        chosen_count: int = 1, chosen_destination: str = "hand",
        rest_destination: str = "graveyard",
    ) -> None:
        self.engine._request_intuition(
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
        else_specs: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Open the general "which of these objects?" choice — see
        `RulesEngine._request_choose_objects`."""
        self.engine._request_choose_objects(
            player, candidates, action, count=count, optional=optional,
            prompt=prompt, source=source, then_specs=then_specs,
            then_specs_if_commander=then_specs_if_commander,
            else_specs=else_specs,
        )

    def impulsive_look(
        self,
        player: "Player",
        count: int,
        criteria: Any = "",
        hit_destination: str = "hand",
        miss_destination: str = "graveyard",
        optional: bool = True,
        hit_grant_keywords: Optional[list[str]] = None,
        miss_effect_specs: Optional[list[dict]] = None,
        hit_effect_specs: Optional[list[dict]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        self.engine._request_impulsive_look(
            player, count, criteria, hit_destination, miss_destination, optional,
            hit_grant_keywords=hit_grant_keywords,
            miss_effect_specs=miss_effect_specs, source=source,
            hit_effect_specs=hit_effect_specs,
        )

    def exile_with_play_permission(
        self,
        player: "Player",
        count: int,
        source_name: Optional[str] = None,
        permission_player: Optional["Player"] = None,
        same_turn_only: bool = False,
        grant: bool = True,
    ) -> list[Any]:
        # MEC-58: returns the exiled objects (rather than discarding them,
        # as before) so a caller — `ImpulsiveDrawEffect.apply` — can seed
        # `created_objects` for a following clause's "that card" referent
        # (Tavern Brawler's "…where X is that card's mana value").
        return self.engine.exile_with_play_permission(
            player, count, source_name=source_name,
            permission_player=permission_player, same_turn_only=same_turn_only, grant=grant,
        )

    def shuffle_library(self, player: "Player") -> None:
        self.engine.shuffle_library(player)

    def shuffle_hand_and_graveyard_into_library(self, player: "Player") -> None:
        self.engine.shuffle_hand_and_graveyard_into_library(player)

    def cascade(self, player: "Player", max_mana_value: int) -> None:
        self.engine._request_cascade(player, max_mana_value)

    def discover(self, player: "Player", max_mana_value: int) -> None:
        self.engine._request_discover(player, max_mana_value)

    def counter(
        self,
        target: Any,
        unless_pays: Optional[str] = None,
        source: Optional["GameObject"] = None,
        suspend_instead: Optional[int] = None,
        on_pay_effect_specs: Optional[list[dict]] = None,
    ) -> None:
        self.engine.counter_unless_pays(
            target, unless_pays, source, suspend_time_counters=suspend_instead,
            on_pay_effect_specs=on_pay_effect_specs,
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

    def apply_effect_specs(
        self, effect_specs: list[dict[str, Any]], source: Optional["GameObject"],
    ) -> None:
        """Build and apply serialized `EffectSpec` dicts right now, off the
        stack — the same "chain a follow-up effect from inside another
        effect's own `apply`" idiom `RulesEngine._apply_effect_specs`
        already offers `_resume_pay_cost_then`/`request_choose_
        objects`' own ``then_specs``/``else_specs``, exposed here so an
        effect can reach it directly too (PAR-30, `CulturalExchangeEffect`'s
        own zero-candidates fallback)."""
        self.engine._apply_effect_specs(effect_specs, source)

    def enqueue_reflexive_trigger(
        self, effect_specs: list[dict[str, Any]], source: Optional["GameObject"],
        event: Optional[GameEvent] = None,
    ) -> None:
        """RULE 603.11's "When you do, `<targeted payoff>`." — see
        `RulesEngine.enqueue_reflexive_trigger`."""
        self.engine.enqueue_reflexive_trigger(effect_specs, source, event or self.trigger_event)

    def end_the_turn(self) -> None:
        self.engine.end_the_turn()

    def return_to_library(self, target: "GameObject", position: str = "top", depth: int = 1) -> None:
        self.engine.return_to_library(target, position, depth)

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

    def blink(self, target: "GameObject", controller: Optional["Player"] = None, tapped: bool = False) -> None:
        self.engine.blink(target, controller=controller, tapped=tapped)

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

    def add_mana(
        self, player: "Player", color: str, amount: int = 1, keep_until: Optional[str] = None,
    ) -> None:
        self.engine.add_mana(player, color, amount, keep_until=keep_until)

    def add_mana_any_color(
        self, player: "Player", colors: Optional[list[str]] = None, amount: int = 1,
        keep_until: Optional[str] = None,
    ) -> None:
        self.engine.add_mana_any_color(player, colors, amount=amount, keep_until=keep_until)


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


#: The players a mass group can be scoped to (PAR-128): "… all lands **target player** controls",
#: "… **defending player** controls" (RULE 506.4), "… **that player** controls" (the trigger's
#: damaged player). The group is written `of: "you"` and evaluated for that player.
GROUP_SCOPE_PLAYERS: tuple[str, ...] = ("player", "opponent", "defending", "event_player")


def _group_scope_player(
    scope: str, context: GameContext, source: Optional["GameObject"],
    chosen: Optional[Any],
) -> Optional["Player"]:
    """The `Player` a ``GROUP_SCOPE_PLAYERS`` value names, or ``None`` when there is none."""
    if scope == "defending":
        player = _defending_player_of(source, context)
    elif scope == "event_player":
        player = _event_player(context, key="target_id")
    else:
        player = chosen
    return player if getattr(player, "id", None) is not None and hasattr(player, "life") else None


def _group_objects(
    context: GameContext, group: dict[str, Any], group_player: Optional[str],
    source: Optional["GameObject"], chosen: Optional[Any] = None,
) -> Optional[list[Any]]:
    """A structured mass ``group`` (`{"zone","of","filter"}`) resolved for a one-shot effect —
    for the source's controller, or for the scoped player. ``None`` when a scoped player can't
    be found (the effect then does nothing)."""
    from ..continuous import group_selector_objects  # avoid the continuous↔effects cycle

    controller_id = getattr(source, "controller_id", None)
    if group_player is not None:
        player = _group_scope_player(group_player, context, source, chosen)
        if player is None:
            return None
        controller_id = player.id
    return list(group_selector_objects(context.state, controller_id, group, src=source))


def _controller_of(source: Optional["GameObject"], context: GameContext) -> Optional["Player"]:
    """The `Player` controlling ``source`` (RULE 109.4), else the active player.

    An untargeted effect ("scry 2", "you draw a card") affects its own
    controller; if the effect has no source yet (a fixture/direct call), fall
    back to the active player.
    """
    controller_id = getattr(context, "acting_player_id", None) or getattr(source, "controller_id", None)
    if controller_id is not None:
        try:
            return context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            pass
    return context.active_player


def _characteristic_of_subject(
    context: GameContext, source: Optional["GameObject"], spec: str
) -> int:
    """A ``"<who>_<char>"`` reading — a characteristic off an object the
    calling effect does *not* itself RULE 115-target (`GainLifeEffect.
    amount_from_subject`'s idiom, shared here with `CreateTokenEffect.
    extra_counters`' ``count_from_subject``).

    ``who`` ∈ ``self`` (the effect's own source), ``previous_subject`` (the
    first entry of `GameContext.previous_targets` — usually already gone, so
    this is RULE 608.2h last-known information), ``trigger_subject`` (the
    object the firing event names by ``instance_id``). ``char`` ∈ ``power``
    / ``toughness`` (derived, layer-engine values) / ``mana_value`` (read
    off the printed card). Anything unrecognised → ``0``, fail-safe.
    """
    # ``char`` may be one word ("power"/"toughness") or two ("mana_value"),
    # so match the known suffixes rather than splitting on the last "_".
    char = "mana_value" if spec.endswith("_mana_value") else spec.rpartition("_")[2]
    who = spec[: -(len(char) + 1)]
    obj = None
    if who == "self":
        obj = source
    elif who == "previous_subject":
        prev = list(getattr(context, "previous_targets", []) or [])
        obj = prev[0] if prev else None
    elif who == "trigger_subject":
        # RULE 400.7: for a DIES trigger the subject is gone by now, so
        # prefer the firing event's snapshot of ``power``/``toughness``
        # (`RulesEngine`'s DIES/LEAVES firing stamps both) over a stale
        # graveyard-object re-lookup.
        event = context.trigger_event or {}
        if char in ("power", "toughness") and event.get(char) is not None:
            return int(event.get(char) or 0)
        # A DAMAGE-shaped group trigger names its acting object as ``source_id``
        # (`effect_conditions.subject_of("entering")`'s own fallback).
        subject_id = event.get("instance_id")
        obj = context.state.find_object(subject_id if subject_id is not None else event.get("source_id"))
    if obj is None:
        return 0
    # PAR-71: "counter target spell. …, where X is that spell's mana
    # value." (Hurl into History) — a "spell" `TargetSpec.kind` resolves to
    # the `StackItem` itself (`targeting.legal_targets`'s own ``"spell"``
    # branch), not a `GameObject` — unwrap to the spell's underlying object
    # for ``.card``/``power``/``toughness`` the same way every other
    # ``who`` above already reads a plain permanent.
    if getattr(obj, "kind", None) == "spell":
        obj = getattr(obj, "obj", None)
        if obj is None:
            return 0
    if char == "mana_value":
        return int(getattr(getattr(obj, "card", None), "converted_mana_cost", 0) or 0)
    return int(getattr(obj, char, 0) or 0)


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

    def _resolve_target_or_controller(
        self,
        context: GameContext,
        targets: Optional[list[Any]],
        explicit: Any = None,
    ) -> Any:
        """The "explicit override -> this effect's own chosen target -> its
        controller" fallback chain several untargeted-by-default effects
        each printed their own copy of (`BecomeMonarchEffect`/
        `TakeInitiativeEffect`'s ``player`` resolution, `DrawCardEffect`'s
        own player fallback, the tail of `GainLifeEffect`'s richer one): a
        caller-supplied ``explicit`` value wins outright; otherwise, if this
        effect actually declared a `target_spec` of its own (``target_kind``
        was set at construction), its first resolved target is used;
        otherwise this effect's own source's controller (the default
        recipient for anything that doesn't target at all). Returns
        ``None`` if none of the three ever resolves to anyone (no source,
        no controller, an empty ``targets``).

        Deliberately narrow: a class whose own fallback chain reads more
        than these three sources (a ``player_id``, a "previous target"
        pronoun, a combat-relative selector — `LoseLifeEffect`'s own final
        player resolution) doesn't fit this helper and isn't migrated onto
        it; see that class's own comments.
        """
        resolved = self._operand_player(context, targets, explicit)
        if resolved is not None or isinstance(explicit, (str, dict)):
            return resolved
        if explicit is not None:
            return explicit
        player = None
        if self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        return player

    def _operand_player(
        self, context: GameContext, targets: Optional[list[Any]], operand: Any
    ) -> Any:
        """A player operand naming a *referent*, resolved — else ``None``.

        ENG-37 axis 4. `14_` §1.1's operand axis had been filling in one flag
        at a time (`GainLifeEffect.recipient="target_controller"`,
        `DrawCardEffect.player_from_trigger_event`,
        `AddPlayerCountersEffect.player_from_target`), which is what kept
        "destroy target permanent, **its controller** gains 4 life" welded
        into a single effect type: the recipient could not be named. A
        ``{"of": …, "as": "controller"}`` dict (or a `PLAYER_SCOPES` string)
        is resolved through the one shared vocabulary in
        `game/effect_operands.py`; anything else — an already-resolved
        `Player`, or ``None`` — is not this helper's business and comes back
        ``None`` so the caller's own fallback chain continues.
        """
        if not isinstance(operand, (str, dict)):
            return None
        from .. import effect_operands  # function-scoped: effects↔operands cycle

        return effect_operands.player_for(operand, context, self.source, targets)

    def _measured(
        self, value: Any, context: "GameContext", targets: Optional[list[Any]] = None
    ) -> Any:
        """A magnitude parameter as a number: an ``int`` / ``"x"`` passes through untouched, an
        `effect_amounts` operand (a dict — ENG-47's one operand for "how much") is measured now,
        against this effect's source and the targets it is resolving with."""
        if isinstance(value, dict):
            from .. import effect_amounts  # function-scoped: effect_amounts imports effect_conditions

            return effect_amounts.amount_of(value, context, self.source, targets)
        return value

    def _resolve_amount_override(
        self,
        base: Union[int, str],
        overrides: list[tuple[bool, Callable[[], Union[int, str]]]],
        *,
        stop_at_first: bool = False,
    ) -> Union[int, str]:
        """Layer ``overrides`` onto ``base`` to compute an effect's live
        magnitude — the "amount/count override priority chain" several
        effects (`DealDamageEffect`, `LoseLifeEffect`, `PreventDamageEffect`,
        `AddCountersEffect`, `GainLifeEffect`, `DrawCardEffect`, …) each
        printed their own copy of: one "if `<a card's own conditional
        clause>`, the amount/count is `<something else>` instead" per
        override, checked in the card's own printed priority.

        Each ``(condition, compute)`` pair is checked **in the order
        given** — ``compute`` only ever runs (lazily) when its own
        ``condition`` is already true, so an override that reads e.g.
        `context.trigger_event` stays safe to list even when its condition
        is false and nothing about the current resolution supports it.

        ``stop_at_first=False`` (the default) mirrors a class whose own
        original code checked each condition with a plain, independent
        ``if`` — nothing ``return``s early, so if two conditions were ever
        both true the *last* one checked would silently win; passing the
        overrides in that same original top-to-bottom order reproduces
        that exactly. ``stop_at_first=True`` mirrors a class that
        originally checked its conditions as an early-return/``elif``
        chain instead (`DealDamageEffect.amount`'s own property,
        `GainLifeEffect`/`DrawCardEffect`'s own amount/count chains) — the
        first true condition's value is returned immediately, nothing
        after it is even evaluated, again reproducing the original order
        exactly.

        Which mode a given class needs is a property of how that class's
        own original chain was written, not a free choice — get it wrong
        and a card with 2+ simultaneously-true overrides (never seen on a
        real card today, per each override's own docstring, but not
        provably impossible) would silently resolve to the wrong one.
        """
        amount = base
        for condition, compute in overrides:
            if condition:
                amount = compute()
                if stop_at_first:
                    return amount
        return amount


def _simultaneous(state: Any) -> Any:
    """RULE 603.2c: one instruction's events happen at once — the objects "create two
    tokens" makes or "destroy all creatures" kills are one batch (`GameState.
    simultaneous`); a bare fixture without a real state gets a no-op scope."""
    scope = getattr(state, "simultaneous", None)
    return scope() if scope is not None else contextlib.nullcontext()


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
    objects_exiled_this_way: int = 0,
    counters_removed_this_way: int = 0,
    damaged_this_way: Optional[list[Any]] = None,
    previous_selector: Optional[str] = None,
    revealed_card: Optional[Any] = None,
    clash_won: Optional[bool] = None,
    clashed_opponent: Optional[Any] = None,
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

    ``revealed_card`` seeds `GameContext.revealed_card` (ENG-37 B5) — the
    card a `RevealTopEffect` clause put on show (RULE 701.20), read by a
    following `if_else`/`bind` as the ``of: "revealed"`` referent. Set by
    the effect, not off a whitelist, but save/reset/restored here so a
    nested resolution neither inherits nor leaks it.

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
    outer_moved = getattr(context, "moved_objects", [])
    outer_milled = getattr(context, "milled_objects", None)
    outer_attachment_hosts = getattr(context, "attachment_hosts", {})
    outer_created = getattr(context, "created_objects", [])
    outer_life_lost = getattr(context, "life_lost_this_way", 0)
    outer_permanents_destroyed = getattr(context, "permanents_destroyed_this_way", 0)
    outer_objects_exiled = getattr(context, "objects_exiled_this_way", 0)
    outer_counters_removed = getattr(context, "counters_removed_this_way", 0)
    outer_damaged_this_way = getattr(context, "damaged_this_way", [])
    outer_previous_selector = getattr(context, "previous_selector", None)
    outer_revealed_card = getattr(context, "revealed_card", None)
    outer_clash_won = getattr(context, "clash_won", None)
    outer_clashed_opponent = getattr(context, "clashed_opponent", None)
    outer_die_result = getattr(context, "die_result", None)
    outer_die_results = getattr(context, "die_results", [])
    outer_rolled_doubles = getattr(context, "rolled_doubles", False)
    outer_random_result = getattr(context, "random_result", None)
    outer_target_groups = getattr(context, "resolution_target_groups", None)
    context.previous_targets = list(previous_targets or [])
    context.moved_objects = list(outer_moved or [])
    context.milled_objects = None
    context.attachment_hosts = dict(outer_attachment_hosts or {})
    context.created_objects = list(created_objects or [])
    context.life_lost_this_way = life_lost_this_way
    context.permanents_destroyed_this_way = permanents_destroyed_this_way
    context.objects_exiled_this_way = objects_exiled_this_way
    context.counters_removed_this_way = counters_removed_this_way
    context.damaged_this_way = list(damaged_this_way or [])
    context.previous_selector = previous_selector
    context.revealed_card = revealed_card
    context.clash_won = clash_won
    context.clashed_opponent = clashed_opponent
    context.die_result = None
    context.die_results = []
    context.rolled_doubles = False
    context.random_result = None
    # A later rider can name a specific earlier target requirement rather
    # than merely the most recently resolved one (Outmuscle's first target
    # survives its intervening fight instruction).
    context.resolution_target_groups = target_groups
    try:
        for position, effect in enumerate(effects):
            if source is not None and effect.source is None:
                effect.source = source
            specs = effect.target_specs
            # Where this list's own remainder belongs on the deferred stack
            # if this effect pauses: *below* anything the effect parks
            # itself. `SacrificeEffect`/`ConniveEffect`/`PopulateEffect` (and
            # every ENG-37 composition node) suspend a loop of their own by
            # pushing a frame from inside `apply`, and `resume_deferred_
            # effects` pops from the top — so appending the remainder
            # afterwards would resume *it* first and run the rest of this
            # list while that loop was still half-finished (RULE 608.2: the
            # effects happen in order). Recording the depth first and
            # inserting there keeps the innermost suspension on top.
            depth = len(state.deferred_effects) if state is not None else 0
            created_before = len(context.created_objects)
            if target_groups is not None and specs:
                # An effect with 2+ requirements consumes that many groups and
                # sees them flattened, so its `apply` reads targets[0],
                # targets[1], … in printed order (see `extra_target_specs`).
                group: list[Any] = []
                for _ in specs:
                    if group_index < len(target_groups):
                        group.extend(target_groups[group_index])
                    group_index += 1
                with _simultaneous(state):
                    effect.apply(context, group)
                used = group
            else:
                with _simultaneous(state):
                    effect.apply(context, targets)
                used = list(targets or [])
            if specs and used:
                context.previous_targets = list(used)
            if (
                getattr(effect, "created_objects_are_referent", False)
                and len(context.created_objects) > created_before
            ):
                # "Create a token that's a copy of target X. It gains haste." — "it" is the copy.
                context.previous_targets = list(context.created_objects[created_before:])
            # A RULE 603.4-gated clause ("if it's the first combat phase …,
            # untap all attacking creatures. They gain …" — Karlach) is a
            # `ConditionalEffect` around the selector effect; "they" still
            # names the inner selector.
            selecting = effect
            while not isinstance(selecting, _PREVIOUS_SELECTOR_EFFECT_TYPES) and isinstance(
                getattr(selecting, "condition", None), dict
            ) and isinstance(getattr(selecting, "inner", None), GameEffect):
                selecting = selecting.inner
            if isinstance(selecting, _PREVIOUS_SELECTOR_EFFECT_TYPES):
                selector = getattr(selecting, "selector", None)
                if selector is None:
                    selector = (getattr(selecting, "static", {}) or {}).get("params", {}).get("affects")
                if selector and not getattr(selecting, "selector_player", None):
                    context.previous_selector = selector  # a player-scoped one set its own
            elif (
                isinstance(selecting, AddCountersEffect)
                and selecting.selector in ADD_COUNTERS_GROUP_AFFECTS
                and selecting.subtypes is None and not selecting.creature_filter
            ):
                # PAR-128: "put a +1/+1 counter on each creature you control.
                # Untap those creatures." (Virtue of Loyalty) — an unnarrowed
                # mass group is replayable by name.
                context.previous_selector = ADD_COUNTERS_GROUP_AFFECTS[selecting.selector]
            elif (
                isinstance(selecting, DealDamageEffect)
                and getattr(selecting, "selector", None) in PREVIOUS_GROUP_DAMAGE_SELECTORS
            ):
                # PAR-128: "~ deals 1 damage to each creature with flying your
                # opponents control. Tap those creatures." (Thundermaw
                # Hellkite) — the group is whoever the hit actually landed on
                # (`damaged_this_way`), not a re-run of the damage selector.
                context.previous_selector = DAMAGED_GROUP_SENTINEL
            if state is None or position + 1 >= len(effects):
                continue
            opened = getattr(state, "pending_choice", None)
            if opened is not None and opened is not already_pending:
                state.deferred_effects.insert(
                    depth,
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
                        "objects_exiled_this_way": context.objects_exiled_this_way,
                        "counters_removed_this_way": context.counters_removed_this_way,
                        "damaged_this_way": list(context.damaged_this_way),
                        "previous_selector": context.previous_selector,
                        "revealed_card": context.revealed_card,
                        "clash_won": context.clash_won,
                        "clashed_opponent": context.clashed_opponent,
                        "stack_item": stack_item,
                    }
                )
                return True
        return False
    finally:
        context.previous_targets = outer_previous
        context.moved_objects = outer_moved
        context.milled_objects = outer_milled
        context.attachment_hosts = outer_attachment_hosts
        context.created_objects = outer_created
        context.life_lost_this_way = outer_life_lost
        context.permanents_destroyed_this_way = outer_permanents_destroyed
        context.objects_exiled_this_way = outer_objects_exiled
        context.counters_removed_this_way = outer_counters_removed
        context.damaged_this_way = outer_damaged_this_way
        context.previous_selector = outer_previous_selector
        context.revealed_card = outer_revealed_card
        context.clash_won = outer_clash_won
        context.clashed_opponent = outer_clashed_opponent
        context.die_result = outer_die_result
        context.die_results = outer_die_results
        context.rolled_doubles = outer_rolled_doubles
        context.random_result = outer_random_result
        context.resolution_target_groups = outer_target_groups


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


class SkipNextStepEffect(GameEffect):
    """One resolving instruction to skip the controller's next named step.

    This is a player-scoped ``StaticEffect`` with a ``once`` duration: the
    skip survives after its source goes away, but consumes itself when the
    turn loop reaches that step (RULE 500.8).
    """

    def __init__(
        self, step: str = "draw", source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None, selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.step = step
        #: "**Target player** skips their next draw step" (Fatigue) / "each opponent skips their next untap
        #: step" (Brine Elemental) / "that player skips their next combat phase" (Blinding Angel): whose step
        #: it is — a RULE 115 player target, ``"each_opponent"``, or ``"event_player"`` (the firing event's
        #: player). Absent, the controller's own.
        self.selector = selector if selector in ("each_opponent", "event_player") else None
        if target_kind in ("player", "opponent"):
            self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.controller_id is None:
            return
        if self.selector == "each_opponent":
            players = [p for p in context.state.living_players() if p.id != self.source.controller_id]
        elif self.selector == "event_player":
            # A damage event names the player it hurt as ``target_id`` ("that player" under "deals combat damage
            # to a player"); other player events name theirs ``player_id``.
            event_player = _event_player(context, key="target_id") or _event_player(context, key="player_id")
            players = [event_player] if event_player is not None else []
        elif self.target_spec is not None:
            chosen = targets[0] if targets else None
            players = [chosen] if chosen is not None and getattr(chosen, "instance_id", None) is None else []
        else:
            players = [context.state.player_by_id(self.source.controller_id)]
        for player in players:
            player.player_effects.append(
                StaticEffect("skip_phase", {"phase": self.step}, duration="once", source=self.source)
            )


class EstablishDayOnEntryEffect(GameEffect):
    """Marker for "it becomes day as this enters" (RULE 731.1)."""

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.description = ""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
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
        #: RULE 613.7b's own ordering key for a *resolving effect's*
        #: continuous grant (`GrantUntilEffect`, MEC-43 round 4E) -- a
        #: bind-time printed static leaves this None and `game/
        #: continuous.py`'s `_in_layer` falls back to `self.source`'s own
        #: `GameObject.timestamp` (RULE 613.7b's ordinary case: the
        #: permanent's own entry time), but a resolve-time grant's real
        #: "when did this continuous effect start existing" is whenever it
        #: was created, which can be long after -- and can't be inferred
        #: from -- whatever permanent it happens to affect.
        self.timestamp = None
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
    `_resume_trigger_mode`, a `trigger_mode` `pending_choice` — the
    same "chosen before target/optional choice" ordering a modal spell's own
    mode gets at cast time); ``modes_or_both`` mirrors RULE 700.2e for a
    triggered ability with exactly two modes. ``modes_choose`` is RULE
    700.2's "choose *N* —" count (``1`` for the ordinary "choose one" case);
    for ``modes_choose > 1`` the choice is made iteratively, one mode per
    round, mirroring how a library search offers "up to N" one card at a
    time (`_resume_trigger_mode`). ``modes_at_least`` is RULE 700.2's
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
        action_key: Optional[str] = None,
        controller_id: Optional[str] = None,
        source: Optional["GameObject"] = None,
        description: str = "",
        modes: Optional[list[dict[str, Any]]] = None,
        modes_or_both: bool = False,
        modes_choose: int = 1,
        modes_at_least: bool = False,
        modes_repeatable: bool = False,
        modes_exhaust_per_turn: bool = False,
        modes_optional: bool = False,
        modes_override: Optional[dict[str, Any]] = None,
        reflexive: bool = False,
        mana_ability: bool = False,
        functions_from_graveyard: bool = False,
        functions_from_stack: bool = False,
        controller_from_trigger_event: bool = False,
        capture_event: Optional[Callable[[GameEvent, GameContext], GameEvent]] = None,
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
        #: RULE 601.2i/603.2 (MEC-43): whether this ability belongs to the
        #: *spell itself* and only ever fires while its source sits on the
        #: **stack**, not the battlefield — "When you cast this spell,
        #: `<effect>`." (Kozilek, Butcher of Truth's own "draw four cards"),
        #: distinct from an ordinary battlefield permanent's "whenever you
        #: cast a spell" static (Bontu's Monument), which must *not* fire
        #: off its own casting since it isn't a permanent yet. Inferred by
        #: `effect_binder.bind_ability` purely from the trigger shape
        #: (``event == SPELL_CAST`` and ``condition == {"subject":
        #: "self"}``) — the same "inferred, no explicit reminder text to
        #: key off" idiom `functions_from_graveyard` uses just above.
        #: Consulted by `RulesEngine._collect_self_cast_triggers`, which —
        #: unlike the ordinary `state.permanents()` scan — only fires
        #: abilities carrying this flag, so an ordinary "you"/"group"
        #: subject condition that happens to also match the object's own
        #: casting (Crypt Ghast's Extort casting itself) is never
        #: mistaken for one.
        self.functions_from_stack = functions_from_stack
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
        # Per-firing measurements belong to the pending trigger, not this reused
        # ability or the shared event (RULE 603.2, PAR-119).
        self.capture_event = capture_event
        self.effects = effects
        self.condition = condition
        self.optional = optional
        self.controller_id = controller_id
        #: RULE 603.1/601.2c (PAR-30 — Confusion in the Ranks' "**its**
        #: controller chooses target permanent…"): a group-subject trigger
        #: whose *chooser* is the firing event's own subject controller, not
        #: this ability's own source's controller (the ordinary case).
        #: `triggers_mixin`'s `_trigger_controller_id` reads
        #: ``event.get("controller_id")`` instead of `self.controller_id`
        #: when this is set and the event actually carries one — every
        #: target-selection/choice-prompt call site that currently reads
        #: ``ability.controller_id or state.active_player.id`` goes through
        #: that helper instead of the bare fallback.
        self.controller_from_trigger_event = controller_from_trigger_event
        self.description = description
        self.modes = modes
        self.modes_or_both = modes_or_both
        self.modes_choose = modes_choose
        self.modes_at_least = modes_at_least
        self.modes_repeatable = modes_repeatable
        #: "Choose a mode that hasn't been chosen this turn" (MEC-68).
        #: This is deliberately separate from `modes_repeatable`: the latter
        #: concerns several picks in one firing, while this excludes choices
        #: made by earlier firings of this exact ability.
        self.modes_exhaust_per_turn = modes_exhaust_per_turn
        #: RULE 700.2's "choose *up to* one —" (Hullbreaker Horror) — the
        #: 0-or-1 sibling of the plain "choose one" (always exactly 1,
        #: `modes_choose == 1` alone) and "choose one **or both**"
        #: (`modes_or_both`, 1 or 2) shapes; only meaningful with
        #: ``modes_choose == 1`` and neither of those other two set.
        self.modes_optional = modes_optional
        self.modes_override = modes_override
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
        #: "…, you may `<action>`. Do this only once each turn." (PAR-135 — Ondu Spiritdancer, Irreverent
        #: Gremlin): unlike ``once_per_turn`` the ability *does* trigger every time; it is the action that
        #: can be performed once a turn. The limit itself lives in the effect list (a gated ``seq`` and an
        #: `ActionStampEffect` at the point the action is accepted — `spec.fold_action_limit`); this is only
        #: its key, so `RulesEngine._place_triggers` can skip a firing whose action is already spent instead
        #: of asking a question whose answer can no longer do anything.
        self.action_key = action_key

    def action_used_this_turn(self, context: GameContext) -> bool:
        """Whether this ability's once-a-turn action has already been performed this turn."""
        if self.action_key is None:
            return False
        performed = getattr(self.source, "action_turns", None) or {}
        return performed.get(self.action_key) == context.state.internal_turn.number

    def check_trigger(self, event: GameEvent, context: GameContext) -> bool:
        """RULE 603.1: does this ability trigger for ``event``?"""
        if event.type != self.trigger_event:
            return False
        if self.condition is not None and not self.condition(event, context):
            return False
        if self.once_per_turn:
            turn = context.state.internal_turn.number
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

    ``modes`` (RULE 700.2, MEC-43 — Umezawa's Jitte's "Remove a charge
    counter: Choose one — …") is the activated-ability sibling of
    `TriggeredAbility.modes`: a list of ``{"effects": [GameEffect, ...],
    "description": str}`` entries, one per printed mode, chosen by
    `GameEngine.activate_ability`'s own ``mode`` param *before* the ability
    goes on the stack (mirroring a modal spell's mode-before-cast/target
    ordering) — never resolved through this ability's own (empty)
    ``effects``. Unlike `TriggeredAbility`, there's no ``modes_or_both``/
    ``modes_choose``/``modes_at_least`` here: `effect_binder.bind_ability`
    only ever builds this field for the plain "choose one" shape, since no
    activated ability in this cache needs more yet.
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
        modes: Optional[list[dict[str, Any]]] = None,
        once_per_game: bool = False,
    ) -> None:
        super().__init__(source)
        self.effects = effects
        if cost is None:
            # Back-compat: build a cost from the old mana/tap parameters.
            from ..costs import ActivationCost

            cost = ActivationCost(mana=mana_cost or ManaCost(), taps_self=taps_source)
        self.cost = cost
        self.description = description
        self.once_per_turn = once_per_turn
        self._last_activated_turn: Optional[int] = None
        self.modes = modes
        #: PAR-28 / RULE 702.177a: Exhaust & Power-up — "Activate only once".
        #: A per-game, per-ability cap (never resets): `GameEngine.
        #: can_activate`/`activate_ability` check/record this ability's
        #: description in `GameObject.used_once_per_game_abilities`.
        self.once_per_game = once_per_game
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



# The concrete mechanics live in focused modules.  `core` remains the
# compatibility import surface for cards, rules code, and third-party callers.
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
        from . import operands  # function-scoped: operands is a leaf module beside this one

        return cls._factories[effect_type](operands.lower(effect_type, params))

    @classmethod
    def is_registered(cls, effect_type: str) -> bool:
        return effect_type in cls._factories


from ._runtime import public_names, register

# Focused modules retain ordinary module globals for their own declarations.
# Their implementations also refer to the shared contracts declared above
# (notably TargetSpec), so publish those before loading the domain modules.
register(globals())

_EFFECT_MODULES = (
    "game_status", "damage_draw", "life_sacrifice", "stack", "exile_control",
    "returns_graveyards", "choices_actions", "attachments_transforms",
    "counters_tokens", "library", "registry", "replacements",
)

for _module_name in _EFFECT_MODULES:
    module = __import__(f"{__package__}.{_module_name}", fromlist=["*"])
    for _name in public_names(module):
        globals()[_name] = getattr(module, _name)

del _module_name, _name, module, register
