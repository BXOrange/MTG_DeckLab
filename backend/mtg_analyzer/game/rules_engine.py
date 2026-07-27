"""The rules engine: mana, casting, stack, replacements, triggers, SBAs.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.2-R2.8,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2/3).

This owns the *rules primitives* — the operations whose consequences are
defined by the Comprehensive Rules — so they live in exactly one place:

* draw / deal damage / destroy / discard, each routed through replacement
  effects (RULE 614/616) and firing events that collect triggers (603).
* the stack (RULE 608, LIFO resolution).
* state-based actions (RULE 704).
* mana cost lookup and payment (RULE 601.2g / 504) via `ManaPool`.

The higher-level turn/phase/priority loop lives in `game_engine.py`; this
engine is the toolbox that loop drives.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional, Union

from ..models import card_query
from ..models.card import Card
from ..models.emblem import Emblem
from ..models.events import EventType, GameEvent
from ..models.game_object import GameObject, Zone
from ..models.game_state import DelayedTrigger, GameState, StackItem
from ..models.mana_cost import ManaCost
from ..models.player import Player
from ..parser.oracle.catalogue.saga import all_chapter_numbers
from . import ability_catalogue, combat, continuous, copy_mechanics
from .combat import is_protected_from
from .costs import DISCARD_HAND, ActivationCost, parse_activation_cost
from .mana_abilities import restriction_predicate_for_cast
from .effects import (
    _apply_effects_partitioned,
    AddCountersEffect,
    AddPlayerCountersEffect,
    BecomeMonarchEffect,
    CantBeCounteredEffect,
    ChooseColorReplacement,
    ChooseCreatureTypeReplacement,
    ChooseNamedModeReplacement,
    DiscardEffect,
    DrawCardEffect,
    LoseLifeEffect,
    ReturnUncastExiledEffect,
    SacrificeSpecificEffect,
    TheRingTemptsYouEffect,
    GameContext,
    GameEffect,
    ImpulsiveDrawEffect,
    MarchesaDelayedReturnEffect,
    ProliferateEffect,
    PumpEffect,
    RadiationMillEffect,
    ReboundFreeCastWindowEffect,
    ReplacementEffect,
    ReturnSelfFromGraveyardEffect,
    SiegeDefeatedEffect,
    StaticAbility,
    StaticEffect,
    TakeInitiativeEffect,
    TriggeredAbility,
    WardEffect,
    WinConditionEffect,
)
from .targeting import TargetSpec, legal_targets

def _saga_final_chapter(card: Card) -> int:
    """The highest chapter number a Saga has (RULE 714.2c), 0 if unreadable.

    Read off the oracle text's roman-numeral chapter markers ("I —", "II, III —",
    "IV —"); the largest is the final chapter. Shares its numeral grammar with
    the oracle-parser front-end's chapter-ability recognition
    (`parser.oracle.catalogue.saga`, RULE 714.2d) rather than duplicating it."""
    return max(all_chapter_numbers(card.oracle_text or ""), default=0)


def _matches_permanent_type(obj: GameObject, what: str) -> bool:
    """Whether ``obj`` matches a sacrifice cost/effect's type word (RULE
    701.17), e.g. ``"creature"``/``"artifact"``/``"enchantment"``/``"land"``/
    ``"permanent"``. Mirrors `GameEngine._matches_sacrifice_type` (the
    cost-payment path) for the effect-driven path (`RulesEngine.sacrifice`);
    kept as its own small copy rather than a cross-module import, since
    `game_engine.py` imports `rules_engine.py`, not the reverse."""
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
        # RULE 306/302: Tevesh Szat's "another creature or planeswalker" —
        # the one compound word any shipped card needs.
        return obj.is_creature or obj.card.is_planeswalker
    return True  # unknown type word → any permanent, so the cost is payable


def _creature_type_options(state: GameState, controller_id: Optional[str]) -> list[str]:
    """The creature-type choices to offer for a RULE 601.2b "as ~ enters,
    choose a creature type" pick.

    RAW technically lets a player name *any* creature type, including one no
    card in the game has — an unbounded, ~300-entry vocabulary this engine
    has no canonical list of (unlike a scoped tribal-lord subtype match,
    which just substring-tests against whatever's actually printed,
    `continuous._has_subtype`). Offering every official type as a button
    isn't a real UI, so this instead offers every creature subtype among
    cards ``controller_id`` actually has anywhere in the game (battlefield,
    hand, library, graveyard, exile, command) — the practically relevant
    set for boosting *their own* creatures, which is what every real card in
    this family (Adaptive Automaton/Arcane Adaptation-shaped) is for. A
    puzzle board with no creature cards anywhere offers nothing — see
    `RulesEngine._offer_enter_choices`'s empty-options handling.
    """
    player = state.player_by_id(controller_id) if controller_id else None
    if player is None:
        return []
    objects = [o for o in state.battlefield if o.owner_id == controller_id]
    objects += list(player.library) + list(player.hand) + list(player.graveyard)
    objects += list(player.exile) + list(player.command)
    types: set[str] = set()
    for obj in objects:
        type_line = (getattr(obj.card, "type_line", "") or "").lower()
        if "creature" not in type_line:
            continue
        _, _, sub = type_line.partition("—")
        for word in re.findall(r"[a-z]+", sub):
            types.add(word.capitalize())
    return sorted(types)


class RulesEngine:
    """Applies MTG rules to a `GameState`."""

    def __init__(self, state: GameState) -> None:
        self.state = state
        self.context = GameContext(state, self)
        #: Triggered abilities that fired and are waiting to be put on the
        #: stack (RULE 603.3 — after the current action, before priority).
        self.pending_triggers: list[tuple[TriggeredAbility, GameEvent]] = []
        #: The active player's triggers awaiting an interactive ordering choice
        #: (RULE 603.3b), and the non-active-player triggers to place after them.
        #: Populated only while `state.interactive_ordering` drives a choice.
        self._ordering_active: list[tuple[TriggeredAbility, GameEvent]] = []
        self._ordering_rest: list[tuple[TriggeredAbility, GameEvent]] = []
        #: The triggered ability currently awaiting a `trigger_target` or
        #: `trigger_mode` choice (RULE 115/603.3c, RULE 700.2), and the
        #: still-to-place queue behind it — populated only while that choice
        #: is pending. ``_pending_trigger_effects`` is the effects list the
        #: choice resolves *against* — the ability's own fixed ``effects``
        #: for an ordinary trigger, or a modal trigger's already-chosen
        #: mode's effects while its own target/"you may" choice is pending
        #: (``None`` selects the ability's own ``effects``, keeping the
        #: non-modal path unchanged).
        self._pending_trigger_ability: Optional[TriggeredAbility] = None
        self._pending_trigger_queue: list[tuple[TriggeredAbility, GameEvent]] = []
        self._pending_trigger_effects: Optional[list[Any]] = None
        #: The `GameEvent` that fired the paused trigger — carried across the
        #: pause so `_place_trigger` can still stamp it onto the `StackItem`
        #: (`StackItem.trigger_event`) after the player answers, exactly as it
        #: would have for a trigger that never paused.
        self._pending_trigger_event: Optional[GameEvent] = None
        #: Populated only while a `trigger_target_multi` choice is pending
        #: (2+ *different* targeting effects on one trigger, RULE 115.1) —
        #: every spec (`_trigger_target_specs`) and the groups gathered for
        #: it so far, one at a time; see `_continue_trigger_multi_target`/
        #: `resolve_trigger_target_multi_choice`.
        self._pending_trigger_specs: list[TargetSpec] = []
        self._pending_trigger_groups: list[list[Any]] = []
        #: The shock land currently awaiting a `land_tapped` pay-life choice
        #: (RULE 614.1), and how much life it costs to keep it untapped —
        #: populated only while that choice is pending.
        self._pending_land_choice_obj: Optional[GameObject] = None
        self._pending_land_choice_amount: int = 0
        #: Backing state for a `pay_cost_then` `pending_choice` — the
        #: general "you may pay <cost>. If you do, <effect>." optional
        #: payment (Mana Vault's upkeep untap, Wandering Archaic's per-
        #: opponent {2}); see `request_pay_cost_then`/
        #: `resolve_pay_cost_then_choice`.
        self._pending_pay_cost_then: Optional[dict[str, Any]] = None
        #: Backing state for a `name_card` `pending_choice` (Demonic
        #: Consultation's "choose a card name") — the follow-up effects the
        #: chosen name gets substituted into; see `request_name_card`/
        #: `resolve_name_card_choice`.
        self._pending_name_card: Optional[dict[str, Any]] = None
        #: Backing state for a `pay_energy_then` `pending_choice` (Aether
        #: Chaser-shaped "you may pay {E}{E}. If you do, …") — see
        #: `request_pay_energy_then`/`resolve_pay_energy_then_choice`.
        self._pending_pay_energy: Optional[dict[str, Any]] = None
        #: A replacement chain awaiting an interactive `replacement_order`
        #: choice (RULE 616.1e/f — 2+ simultaneously-applicable replacement
        #: effects), and the continuation to resume once it's answered.
        #: Populated only while that choice is pending; see
        #: `apply_replacements`/`resolve_replacement_order_choice`.
        self._pending_replacement_event: Optional[GameEvent] = None
        self._pending_replacement_applied: set[int] = set()
        self._pending_replacement_applicable: list[ReplacementEffect] = []
        self._pending_replacement_callback: Optional[
            Callable[[Optional[GameEvent]], None]
        ] = None
        #: The permanent currently awaiting an `enter_as_copy` choice (RULE
        #: 614.1c/614.12), its `EnterAsCopyReplacement`, and the battlefield-
        #: entry continuation to resume once it's answered — populated only
        #: while that choice is pending; see `_offer_enter_as_copy`/
        #: `resolve_enter_as_copy_choice`.
        self._pending_enter_as_copy_obj: Optional[GameObject] = None
        self._pending_enter_as_copy_effect: Optional[Any] = None
        self._pending_enter_as_copy_continuation: Optional[Callable[[], None]] = None
        #: The permanent currently awaiting an "as ~ enters, choose a
        #: creature type/color" pick (RULE 601.2b — `enter_choice_effects`),
        #: which of its queued choice-effects is open, and the continuation
        #: to resume once it's answered (which may itself open the *next*
        #: queued choice, if the card has more than one) — populated only
        #: while that choice is pending; see `_offer_enter_choices`/
        #: `resolve_enter_choice`.
        self._pending_enter_choice_obj: Optional[GameObject] = None
        self._pending_enter_choice_effect: Optional[Any] = None
        self._pending_enter_choice_continuation: Optional[Callable[[], None]] = None
        #: The battle currently awaiting its RULE 310.8a/310.11a "choose a
        #: player to protect it" pick, and the battlefield-entry
        #: continuation to resume once it's answered — populated only while
        #: that choice is pending; see `_offer_protector_choice`/
        #: `resolve_protector_choice`.
        self._pending_protector_obj: Optional[GameObject] = None
        self._pending_protector_continuation: Optional[Callable[[], None]] = None
        #: A Saga with Read Ahead (RULE 702.155/714.3b) awaiting its "choose a
        #: number from 1 to this Saga's final chapter number" pick, and the
        #: battlefield-entry continuation to resume once it's answered —
        #: populated only while that choice is pending; see
        #: `_offer_read_ahead`/`resolve_read_ahead_choice`. The chosen count
        #: itself is stashed separately (`_pending_read_ahead_count`) since it
        #: must survive past the continuation into `_resolve_permanent_spell`'s
        #: `_finish`, which passes it to `GameState.add_to_battlefield` as
        #: ``saga_lore_override`` — RULE 702.155a's "only the exact-count
        #: chapter fires, every lower one is skipped for good" means this
        #: can't be layered on top of the ordinary chapter-1 entry path.
        self._pending_read_ahead_obj: Optional[GameObject] = None
        self._pending_read_ahead_continuation: Optional[Callable[[], None]] = None
        self._pending_read_ahead_count: Optional[int] = None
        #: The spell awaiting a `counter_unless_pays` choice (RULE 601 —
        #: "counter target spell unless its controller pays …"), and the
        #: resolved `ManaCost` it would take to save it — populated only
        #: while that choice is pending; see `counter_unless_pays`/
        #: `resolve_counter_unless_pays_choice`.
        self._pending_counter_target: Any = None
        self._pending_counter_cost: Optional[ManaCost] = None
        #: RULE 702.21 (ward): the item awaiting a `ward` pay-or-be-countered
        #: choice, whose player must decide (the *caster*, unlike
        #: `counter_unless_pays` where it's the target's controller), and
        #: the `ActivationCost` currently being asked about. A ward ability
        #: is a genuine `StackItem` of its own (`check_ward` pushes one per
        #: warded target, on top of the triggering item), so — unlike
        #: `counter_unless_pays` — multiple simultaneous wards need no queue
        #: here: the stack itself sequences them one resolution at a time
        #: (RULE 702.21c). Populated only while a ward choice is pending;
        #: see `resolve_ward_effect`/`resolve_ward_choice`.
        #: The "sacrifice ~ unless you pay `<cost>`" choice currently awaiting
        #: an answer (`request_sacrifice_unless_pay`/
        #: `resolve_sacrifice_unless_pay_choice`) — the permanent at stake,
        #: whose controller is being asked, and the `ActivationCost`. Only one
        #: can be pending at a time (like every other `pending_choice`); a
        #: second upkeep trigger simply waits its turn on the stack.
        self._pending_sacrifice_unless_pay: Optional[dict[str, Any]] = None
        self._pending_ward_item: Optional[StackItem] = None
        self._pending_ward_caster_id: Optional[str] = None
        self._pending_ward_cost: Optional[ActivationCost] = None
        #: The permanent/player awaiting a `remove_counters_amount`/
        #: `remove_counters_kind` choice (RULE 122 — "remove up to N
        #: counters from target permanent"), and how many are still left to
        #: remove once the amount is settled and a per-kind choice is
        #: underway — populated only while one of those choices is pending;
        #: see `request_remove_counters_choice`/`_continue_remove_counters`.
        self._pending_remove_counters_target: Optional[GameObject] = None
        self._pending_remove_counters_remaining: int = 0
        # Collect triggers for every event the game fires.
        state.subscribe(self._collect_triggers)
        # Tally spells cast this turn for the RULE 731.2 day/night check.
        state.subscribe(self._track_spell_cast)
        # Tally creatures that died this turn (RULE 700.4) — see
        # `GameState.creatures_died_this_turn`.
        state.subscribe(self._track_creature_death)

    # ------------------------------------------------------------------
    # Mana cost lookup (RULE 202)
    # ------------------------------------------------------------------

    @staticmethod
    def mana_cost_of(card: Card) -> ManaCost:
        """The structured cost of a card.

        Uses the raw ``mana_cost_string`` when present, else reconstructs
        it from the card's pip tally + mana value (`ManaCost.from_card`),
        so a card cached before that field existed still costs its real
        mana instead of being wrongly free.
        """
        return ManaCost.from_card(card)

    # ------------------------------------------------------------------
    # Replacement effects (RULE 614 / 616)
    # ------------------------------------------------------------------

    def _all_replacement_effects(self) -> list[ReplacementEffect]:
        effects: list[ReplacementEffect] = []
        for obj in self.state.permanents():
            effects.extend(obj.replacement_effects)
        for player in self.state.players:
            effects.extend(
                e for e in player.player_effects if isinstance(e, ReplacementEffect)
            )
        return effects

    def apply_replacements(
        self,
        event: GameEvent,
        on_resolved: Optional[Callable[[Optional[GameEvent]], None]] = None,
    ) -> Optional[GameEvent]:
        """Rewrite ``event`` through applicable replacement effects.

        RULE 616: each replacement may apply at most once to a given event
        (tracked by identity here), and applying one can expose others —
        RULE 616.1f, "repeat this process until there are no more
        applicable replacement … effects" (a draw→mill chain, or Furnace of
        Rath *then* Torbran on the same damage event).

        When exactly one effect applies at a step there's nothing to choose.
        When two or more apply simultaneously, RULE 616.1e says the
        *affected player* (`_event_affected_player_id`) chooses which to
        apply next. If ``on_resolved`` is given, this opens an interactive
        ``replacement_order`` `pending_choice` and returns ``None``
        immediately *without* calling it yet — `resolve_replacement_order_
        choice` finishes the chain later (mirroring `put_triggers_on_
        stack`/`resolve_trigger_order_choice`'s RULE 603.3b pause/resume)
        and invokes ``on_resolved`` with the final event once it settles.
        A choice already pending (e.g. a second ambiguous damage event
        resolving in the same synchronous combat-damage batch) isn't a
        second one to answer — that event falls back to deterministic
        discovery order rather than clobbering the first.

        Without ``on_resolved`` (back-compat for direct callers/tests that
        read the return value), ambiguity always falls back to
        deterministic discovery order, exactly as before this method grew
        the interactive path.
        """
        return self._run_replacement_loop(event, set(), on_resolved)

    def _run_replacement_loop(
        self,
        event: GameEvent,
        applied: set[int],
        on_resolved: Optional[Callable[[Optional[GameEvent]], None]],
    ) -> Optional[GameEvent]:
        current: Optional[GameEvent] = event
        while current is not None:
            applicable = [
                effect
                for effect in self._all_replacement_effects()
                if id(effect) not in applied and effect.can_replace(current, self.context)
            ]
            if not applicable:
                break
            if len(applicable) > 1 and on_resolved is not None and not self.state.pending_choice:
                self._pending_replacement_event = current
                self._pending_replacement_applied = applied
                self._pending_replacement_applicable = applicable
                self._pending_replacement_callback = on_resolved
                self.state.pending_choice = self._replacement_order_choice(current, applicable)
                return None
            chosen = applicable[0]
            applied.add(id(chosen))
            current = chosen.apply_replacement(current, self.context)
        if on_resolved is not None:
            on_resolved(current)
            return None
        return current

    def _event_affected_player_id(self, event: GameEvent) -> Optional[str]:
        """Whose choice a RULE 616.1 replacement-order pick belongs to: the
        player about to draw/discard/mill, take the damage/counters, or (for
        a token-creation event) create the tokens."""
        if event.get("is_player"):
            return event.get("target_id")
        target_id = event.get("target_id")
        if target_id is not None:
            obj = self.state.find_object(target_id)
            if obj is not None:
                return obj.controller_id
        player_id = event.get("player_id")
        if player_id is not None:
            return player_id
        return event.get("controller_id")

    def _replacement_order_choice(
        self, event: GameEvent, applicable: list[ReplacementEffect]
    ) -> dict[str, Any]:
        """Build the `pending_choice` offering ``applicable`` as the next
        replacement effect to apply (RULE 616.1e) — one button per effect,
        matching the generic choice UI's `{"id", "label"}` shape."""
        player_id = self._event_affected_player_id(event) or self.state.active_player.id
        options = [
            {
                "id": str(i),
                "label": effect.description
                or (effect.source.name if effect.source is not None else "Ersetzungseffekt"),
            }
            for i, effect in enumerate(applicable)
        ]
        return {
            "kind": "replacement_order",
            "player_id": player_id,
            "prompt": "Reihenfolge der Ersetzungseffekte wählen",
            "options": options,
        }

    def resolve_replacement_order_choice(self, index: Optional[int]) -> None:
        """Apply the chosen replacement next, then resume the chain (RULE
        616.1e/f) — mirrors `resolve_trigger_order_choice`'s pattern.

        ``index`` selects one of the still-applicable effects by its option
        id; missing/out-of-range defaults to the first. Re-opens a fresh
        `replacement_order` choice if 2+ effects are still simultaneously
        applicable afterward; otherwise finishes the chain and invokes the
        stashed continuation with the final event.
        """
        callback = self._pending_replacement_callback
        if callback is None:
            self.state.pending_choice = None
            return
        applicable = self._pending_replacement_applicable
        event = self._pending_replacement_event
        applied = self._pending_replacement_applied
        self._pending_replacement_event = None
        self._pending_replacement_applicable = []
        self._pending_replacement_applied = set()
        self._pending_replacement_callback = None
        self.state.pending_choice = None

        if index is None or not 0 <= index < len(applicable):
            index = 0
        chosen = applicable[index]
        applied.add(id(chosen))
        current = chosen.apply_replacement(event, self.context) if event is not None else None
        if current is None:
            callback(None)
            return
        self._run_replacement_loop(current, applied, callback)

    # ------------------------------------------------------------------
    # Triggered abilities (RULE 603)
    # ------------------------------------------------------------------

    def _collect_triggers(self, event: GameEvent) -> None:
        if continuous.trigger_suppressed(self.state, event):
            # RULE 603: "Creatures entering don't cause abilities to
            # trigger." (Tocatli Honor Guard/Hushwing Gryff/Torpor Orb) —
            # silences every triggered ability that would otherwise fire off
            # this event, including the entering creature's own, for as long
            # as the static is in play.
            return
        for obj in self.state.permanents():
            # RULE 613.7f: a permanent stripped of all abilities (Humility,
            # Dress Down) has no triggered abilities to fire — not even a
            # layer-6-granted one, which is itself an ability it no longer has.
            if getattr(obj, "loses_all_abilities", False):
                continue
            # `granted_triggered_abilities` (RULE 613.7f — a layer-6 "X have
            # '<triggered ability>'" static grant, e.g. Dionus, Elvish
            # Archdruid) sits alongside the object's own intrinsic abilities;
            # both fire through the same check/place pipeline.
            for ability in obj.triggered_abilities + obj.granted_triggered_abilities:
                if isinstance(ability, TriggeredAbility) and ability.check_trigger(
                    event, self.context
                ):
                    if ability.mana_ability:
                        # RULE 605.4: a *triggered mana ability* never uses
                        # the stack — it resolves right here, so its mana is
                        # in the pool in time for the payment that triggered
                        # it (Wild Growth, Kinnan). Queueing it would make
                        # the extra mana arrive a full stack resolution too
                        # late to spend, which is the entire point of both.
                        self._resolve_mana_trigger(ability, event)
                        continue
                    self.pending_triggers.append((ability, event))
        # RULE 114.4: an emblem's abilities function in the command zone —
        # scanned the same way as a permanent's, just off `Player.emblems`
        # instead of the battlefield (see `models/emblem.py`).
        for player in self.state.players:
            for emblem in player.emblems:
                for ability in emblem.triggered_abilities:
                    if ability.check_trigger(event, self.context):
                        self.pending_triggers.append((ability, event))
        self._collect_inherent_triggers(event)
        self._collect_impulsive_draw_triggers(event)
        self._collect_rad_counter_damage_triggers(event)
        self._collect_attacks_you_rad_counter_triggers(event)
        self._collect_temporary_player_triggers(event)
        self._collect_counter_death_return_triggers(event)
        self._collect_mill_return_from_graveyard_triggers(event)

    def _resolve_mana_trigger(self, ability: "TriggeredAbility", event: GameEvent) -> None:
        """Apply a triggered mana ability immediately (RULE 605.4).

        The stack-free counterpart of `_place_trigger`: no `StackItem`, no
        priority window, no targets (RULE 605.1a forbids a mana ability from
        targeting at all, so there is nothing to choose). The firing event is
        exposed as `GameContext.trigger_event` for the duration, exactly as a
        stack resolution would — Kinnan's "one mana of any type **that
        permanent** produced" and Wild Growth's "**its** controller" both
        read it — and restored afterward, since this can run inside another
        resolution.
        """
        outer = self.context.trigger_event
        self.context.trigger_event = event
        try:
            ability.apply(self.context)
        finally:
            self.context.trigger_event = outer

    def _collect_inherent_triggers(self, event: GameEvent) -> None:
        """RULE 725.2/726.2/728.1: the Monarch's, the Initiative's, and rad
        counters' triggered abilities "have no source" — they aren't
        attached to any permanent, so the object scan above can never find
        them. Built fresh here instead, each time a matching event fires:
        for monarch/initiative, since who currently holds either
        designation (and so who controls the ability) can change turn to
        turn; RULE 726.2's "venture into the dungeon" trigger isn't modeled
        (dungeons/RULE 309 aren't built yet — see `TakeInitiativeEffect`'s
        docstring). Rad counters differ in that the ability is always
        controlled by the active player rather than following a
        designation, so no lookup is needed beyond `state.active_player`.
        """
        monarch = self.state.player_by_id(self.state.monarch_id) if self.state.monarch_id else None
        if monarch is not None and not monarch.has_lost:
            # "At the beginning of the monarch's end step, that player draws
            # a card."
            if (
                event.type == EventType.STEP_BEGIN
                and event.get("step") == "end"
                and self.state.active_player.id == monarch.id
            ):
                ability = TriggeredAbility(
                    trigger_event=EventType.STEP_BEGIN,
                    effects=[DrawCardEffect(count=1, player=monarch)],
                    controller_id=monarch.id,
                    description="The monarch draws a card.",
                )
                self.pending_triggers.append((ability, event))
            # "Whenever a creature deals combat damage to the monarch, its
            # controller becomes the monarch."
            if (
                event.type == EventType.DAMAGE
                and event.get("combat")
                and event.get("is_player")
                and event.get("target_id") == monarch.id
            ):
                new_monarch_id = event.get("source_controller_id")
                if new_monarch_id and new_monarch_id != monarch.id:
                    ability = TriggeredAbility(
                        trigger_event=EventType.DAMAGE,
                        effects=[BecomeMonarchEffect(player=self.state.player_by_id(new_monarch_id))],
                        controller_id=new_monarch_id,
                        description="Whenever a creature deals combat damage to the monarch, its controller becomes the monarch.",
                    )
                    self.pending_triggers.append((ability, event))
        initiative = (
            self.state.player_by_id(self.state.initiative_id) if self.state.initiative_id else None
        )
        if initiative is not None and not initiative.has_lost:
            # "Whenever one or more creatures a player controls deal combat
            # damage to the player who has the initiative, the controller of
            # those creatures takes the initiative." Simplified to one
            # trigger per damage event rather than batching every attacker
            # a single player controls into one firing — RULE 726.2's own
            # wording ("one or more creatures") makes that batching a
            # presentation detail, not a rules difference: either way only
            # one designation change results.
            if (
                event.type == EventType.DAMAGE
                and event.get("combat")
                and event.get("is_player")
                and event.get("target_id") == initiative.id
            ):
                new_holder_id = event.get("source_controller_id")
                if new_holder_id and new_holder_id != initiative.id:
                    ability = TriggeredAbility(
                        trigger_event=EventType.DAMAGE,
                        effects=[TakeInitiativeEffect(player=self.state.player_by_id(new_holder_id))],
                        controller_id=new_holder_id,
                        description=(
                            "Whenever one or more creatures a player controls deal combat "
                            "damage to the player who has the initiative, the controller of "
                            "those creatures takes the initiative."
                        ),
                    )
                    self.pending_triggers.append((ability, event))
        # RULE 728.1: "At the beginning of each player's precombat main
        # phase, if that player has one or more rad counters, that player
        # mills..." — "each player's precombat main phase" just means
        # whichever player's turn this is (there's exactly one precombat
        # main per turn, always the active player's, `game/phases.py`), not
        # an APNAP loop over every player. Controlled by the active player
        # (an explicit exception to RULE 113.8, unlike monarch/initiative
        # which follow whoever currently holds the designation).
        if event.type == EventType.STEP_BEGIN and event.get("step") == "main1":
            active = self.state.active_player
            if not active.has_lost and active.counters.get("rad", 0) > 0:
                ability = TriggeredAbility(
                    trigger_event=EventType.STEP_BEGIN,
                    effects=[RadiationMillEffect(player=active)],
                    controller_id=active.id,
                    description=(
                        "At the beginning of each player's precombat main phase, if that "
                        "player has one or more rad counters, that player mills a number of "
                        "cards equal to the number of rad counters they have. For each "
                        "nonland card milled this way, that player loses 1 life and removes "
                        "one rad counter from themselves."
                    ),
                )
                self.pending_triggers.append((ability, event))

        self._collect_ring_triggers(event)

    def _collect_ring_triggers(self, event: GameEvent) -> None:
        """RULE 701.51a: the Ring emblem's abilities 2–4, which trigger.

        Source-less like the monarch's and the initiative's above — the Ring
        emblem isn't a permanent, and (unlike a RULE 114 emblem) has no
        quoted card text to bind, so there is nothing for the per-permanent
        trigger scan to find. Built fresh here off live state instead, which
        also means each one automatically follows the *current* Ring-bearer
        rather than whichever creature was bearer when the ability was
        gained. Ability 1 is a static and lives in `game/continuous.py`
        (legendary) and `GameEngine.can_block` (the blocking restriction).
        """
        for player in self.state.players:
            level = int(getattr(player, "ring_level", 0) or 0)
            if level < 2 or player.has_lost:
                continue
            bearer = continuous.ring_bearer_of(self.state, player)
            if bearer is None:
                continue

            # 2: "Whenever your Ring-bearer attacks, draw a card, then
            # discard a card."
            if (
                event.type == EventType.ATTACKS
                and event.get("instance_id") == bearer.instance_id
            ):
                self.pending_triggers.append((
                    TriggeredAbility(
                        trigger_event=EventType.ATTACKS,
                        effects=[
                            DrawCardEffect(count=1, player=player),
                            DiscardEffect(count=1, player=player),
                        ],
                        controller_id=player.id,
                        description="Whenever your Ring-bearer attacks, draw a card, then discard a card.",
                    ),
                    event,
                ))

            # 3: "Whenever your Ring-bearer becomes blocked by a creature,
            # that creature's controller sacrifices it at end of combat."
            # BECOMES_BLOCKED fires once per attacker rather than once per
            # blocker (RULE 509.5), and every blocker is already assigned by
            # then, so one trigger carrying the whole set is equivalent to
            # the per-blocker firings the rules describe — the same batching
            # `_collect_inherent_triggers` justifies for the initiative.
            if (
                level >= 3
                and event.type == EventType.BECOMES_BLOCKED
                and event.get("instance_id") == bearer.instance_id
            ):
                blockers = [
                    obj for obj in self.state.battlefield
                    if obj.instance_id in bearer.blocked_by
                ]
                if blockers:
                    self.pending_triggers.append((
                        TriggeredAbility(
                            trigger_event=EventType.BECOMES_BLOCKED,
                            effects=[
                                SacrificeSpecificEffect(blockers, delay_step="end_combat")
                            ],
                            controller_id=player.id,
                            description=(
                                "Whenever your Ring-bearer becomes blocked by a creature, "
                                "that creature's controller sacrifices it at end of combat."
                            ),
                        ),
                        event,
                    ))

            # 4: "Whenever your Ring-bearer deals combat damage to a player,
            # each opponent loses 3 life."
            if (
                level >= 4
                and event.type == EventType.DAMAGE
                and event.get("combat")
                and event.get("is_player")
                and event.get("source_id") == bearer.instance_id
            ):
                self.pending_triggers.append((
                    TriggeredAbility(
                        trigger_event=EventType.DAMAGE,
                        # ``each_opponent`` is relative to the effect's own
                        # source's controller, so the Ring-bearer stands in
                        # as source — "your" opponents are exactly its
                        # controller's, which is what the emblem means.
                        effects=[
                            LoseLifeEffect(amount=3, selector="each_opponent", source=bearer)
                        ],
                        controller_id=player.id,
                        description=(
                            "Whenever your Ring-bearer deals combat damage to a player, "
                            "each opponent loses 3 life."
                        ),
                    ),
                    event,
                ))

    def _collect_impulsive_draw_triggers(self, event: GameEvent) -> None:
        """"Whenever ~ deals combat damage to a player, exile the top card of
        *that player's* library. Until end of turn, you may cast that card."
        (Ragavan, Nimble Pilferer, `AbilitySpec.impulsive_draw_on_combat_
        damage`) — the damaged player varies per firing, which a bind-on-load
        `TriggeredAbility`'s one fixed ``effects`` list can't carry (see that
        class's docstring, `game/effects.py`). Built fresh right here, the
        same "per-firing data baked in right when the event fires" shape
        `_collect_inherent_triggers` above already uses for the Monarch/
        Initiative combat-damage swap — queued through the ordinary
        ``pending_triggers`` pipeline (RULE 603.3 ordering/choices), unlike
        `check_rampage`/`check_ward`'s "place immediately" shortcut, since
        this *is* a genuine source-bound triggered ability, just one no
        object scan could ever find pre-built.
        """
        if event.type != EventType.DAMAGE or not event.get("combat") or not event.get("is_player"):
            return
        source_id = event.get("source_id")
        if source_id is None:
            return
        source = self.state.find_object(source_id)
        if source is None:
            return
        marker = getattr(source, "impulsive_draw_on_combat_damage", None)
        if not marker:
            return
        try:
            damaged_player = self.state.player_by_id(event["target_id"])
            controller = self.state.player_by_id(source.controller_id)
        except KeyError:
            return
        effect = ImpulsiveDrawEffect(
            count=int(marker.get("count", 1)),
            player=damaged_player,
            permission_player=controller,
            same_turn_only=True,
            source=source,
        )
        ability = TriggeredAbility(
            trigger_event=EventType.DAMAGE,
            effects=[effect],
            controller_id=controller.id,
            source=source,
            description=f"{source.name}: verbanne die oberste Karte der gegnerischen Bibliothek",
        )
        self.pending_triggers.append((ability, event))

    def _collect_rad_counter_damage_triggers(self, event: GameEvent) -> None:
        """"Whenever ~ deals combat damage to a player, they get N rad
        counters." (Glowing One)/"...that many rad counters." (Infesting
        Radroach, `AbilitySpec.rad_counters_on_combat_damage`) — the
        damaged player (and, for "that many", the amount itself) varies
        per firing, the same "build fresh right here" shape
        `_collect_impulsive_draw_triggers` above already uses for Ragavan's
        damaged-player-library exile.

        ``marker["else"] == "proliferate"`` (Vexing Radgull: "...if they
        don't have any rad counters. Otherwise, proliferate.") branches on
        whether the damaged player currently has any of the granted
        ``kind`` — checked live against the *pre-damage* count (this fires
        off the same `DAMAGE` event `add_player_counters` would use, before
        this ability's own grant), so "don't have any yet" reads correctly
        even on the very first hit.
        """
        if event.type != EventType.DAMAGE or not event.get("combat") or not event.get("is_player"):
            return
        source_id = event.get("source_id")
        if source_id is None:
            return
        source = self.state.find_object(source_id)
        if source is None:
            return
        marker = getattr(source, "rad_counters_on_combat_damage", None)
        if not marker:
            return
        try:
            damaged_player = self.state.player_by_id(event["target_id"])
            controller = self.state.player_by_id(source.controller_id)
        except KeyError:
            return
        count = marker.get("count", 1)
        amount = int(event.get("amount", 0)) if count == "damage_amount" else int(count)
        kind = marker.get("kind", "rad")
        if marker.get("else") == "proliferate" and damaged_player.counters.get(kind, 0) > 0:
            effect: GameEffect = ProliferateEffect(source=source)
        else:
            effect = AddPlayerCountersEffect(amount=amount, kind=kind, player=damaged_player, source=source)
        ability = TriggeredAbility(
            trigger_event=EventType.DAMAGE,
            effects=[effect],
            controller_id=controller.id,
            source=source,
            description=f"{source.name}: gib der geschädigten Spielerin/dem geschädigten Spieler Rad-Marken",
        )
        self.pending_triggers.append((ability, event))

    def _collect_attacks_you_rad_counter_triggers(self, event: GameEvent) -> None:
        """"Whenever a player attacks you with one or more creatures, that
        player gets twice that many rad counters." (Struggle for Project
        Purity's Enclave mode, `AbilitySpec.rad_counters_on_attacked`) —
        the attacking player and the amount (tied to `EventType.
        PLAYER_ATTACKED`'s own ``count``) vary per firing, the same
        "build fresh right here" shape every other rad-counter marker
        collector uses; scans every permanent for the marker rather than
        reading it off the event's own subject, since the event is about a
        *player* attacking, not this ability's source
        (`_collect_counter_death_return_triggers`'s same "scan every
        permanent" style, for the same reason).
        """
        if event.type != EventType.PLAYER_ATTACKED:
            return
        defending_player_id = event.get("defending_player_id")
        attacking_player_id = event.get("attacking_player_id")
        if defending_player_id is None or attacking_player_id is None:
            return
        for obj in self.state.permanents():
            marker = getattr(obj, "rad_counters_on_attacked", None)
            if not marker:
                continue
            if obj.controller_id != defending_player_id:
                continue
            requires_mode = marker.get("requires_mode")
            if requires_mode and getattr(obj, "chosen_mode", None) != requires_mode:
                continue
            try:
                attacker = self.state.player_by_id(attacking_player_id)
            except KeyError:
                continue
            amount = int(marker.get("multiplier", 1)) * int(event.get("count", 0))
            effect = AddPlayerCountersEffect(amount=amount, kind="rad", player=attacker, source=obj)
            ability = TriggeredAbility(
                trigger_event=EventType.PLAYER_ATTACKED,
                effects=[effect],
                controller_id=obj.controller_id,
                source=obj,
                description=f"{obj.name}: gib der angreifenden Spielerin/dem angreifenden Spieler Rad-Marken",
            )
            self.pending_triggers.append((ability, event))

    def _collect_temporary_player_triggers(self, event: GameEvent) -> None:
        """Re-fire and expire `GameState.temporary_player_triggers` (Nuka-
        Nuke Launcher's "until the end of defending player's next turn,
        that player gets rad counters whenever they cast a spell") — see
        `TemporaryPlayerTrigger`'s own docstring for the phase state
        machine this drives off `EventType.TURN_BEGIN`.
        """
        if not self.state.temporary_player_triggers:
            return
        remaining = []
        for trig in self.state.temporary_player_triggers:
            if trig.phase == "waiting":
                if (
                    event.type == EventType.TURN_BEGIN
                    and event.get("player_id") == trig.player_id
                    and int(event.get("turn", 0)) > trig.install_turn
                ):
                    trig.phase = "active"
                    trig.active_since_turn = int(event.get("turn", 0))
                remaining.append(trig)
                continue
            # phase == "active": the *next* TURN_BEGIN (anyone's) after their
            # own turn started means their turn just ended — drop it.
            if (
                event.type == EventType.TURN_BEGIN
                and trig.active_since_turn is not None
                and int(event.get("turn", 0)) > trig.active_since_turn
            ):
                continue
            if event.type == trig.event_type and event.get("player_id") == trig.player_id:
                ability = TriggeredAbility(
                    trigger_event=trig.event_type,
                    effects=trig.effects,
                    controller_id=trig.player_id,
                    description=trig.description,
                )
                self.pending_triggers.append((ability, event))
            remaining.append(trig)
        self.state.temporary_player_triggers = remaining

    def _collect_counter_death_return_triggers(self, event: GameEvent) -> None:
        """"Whenever a creature you control with a counter of
        ``counter_kind`` on it dies, return that card to the battlefield
        under your control at the beginning of the next end step."
        (Marchesa, the Black Rose, `AbilitySpec.counter_death_return`) — the
        dying creature varies per firing, so this is built fresh here
        exactly like `_collect_impulsive_draw_triggers` above, just scanning
        every permanent for the marker instead of reading it off the
        event's own source (Marchesa isn't the object the `DIES` event is
        about — RULE 603.1's "group" subject shape, not "self").
        """
        if event.type != EventType.DIES:
            return
        if "creature" not in (event.get("object_types") or []):
            return
        dying_controller_id = event.get("controller_id")
        dying_id = event.get("instance_id")
        if dying_controller_id is None or dying_id is None:
            return
        dying_counters = event.get("counters") or {}
        for obj in self.state.permanents():
            marker = getattr(obj, "counter_death_return", None)
            if not marker or obj.controller_id != dying_controller_id:
                continue
            kind = marker.get("counter_kind", "+1/+1")
            if dying_counters.get(kind, 0) <= 0:
                continue
            dying_obj = self.state.find_object(dying_id)
            if dying_obj is None:
                continue
            effect = MarchesaDelayedReturnEffect(dying_object=dying_obj, source=obj)
            ability = TriggeredAbility(
                trigger_event=EventType.DIES,
                effects=[effect],
                controller_id=obj.controller_id,
                source=obj,
                description=f"{obj.name}: {dying_obj.name} zum Ende des Zuges zurückbringen",
            )
            self.pending_triggers.append((ability, event))

    def _collect_mill_return_from_graveyard_triggers(self, event: GameEvent) -> None:
        """"Whenever an opponent mills a nonland card, if this creature is
        in your graveyard, you may return it to your hand." (RULE 112.6a,
        Infesting Radroach, `AbilitySpec.mill_return_from_graveyard`) — the
        only triggered ability in this catalogue that must keep firing
        while its own source sits in a *graveyard*, not the battlefield, so
        it can't ride the ordinary `obj.triggered_abilities` scan
        (`_collect_triggers` only walks `state.permanents()`); scanned here
        instead, exactly like `_collect_counter_death_return_triggers`'s
        own "per-firing marker" style, just over every player's graveyard
        rather than the battlefield.

        "You"/"your" (RULE 108.4: a graveyard card has no controller, only
        an owner) is that graveyard's own player — so a player's *own* mill
        never triggers their own graveyard-sitting Radroach; only somebody
        else's does, matched by skipping the milling player's own graveyard
        entirely below rather than by the usual group-subject "not_you"
        binder machinery (this ability never goes through that pipeline at
        all — it's built fresh per firing, like every other rad-counter
        marker in this file).
        """
        if event.type != EventType.MILL_CARD:
            return
        milling_player_id = event.get("player_id")
        if milling_player_id is None:
            return
        for player in self.state.players:
            if player.id == milling_player_id:
                continue
            for obj in player.graveyard:
                if not getattr(obj, "mill_return_from_graveyard", False):
                    continue
                effect = ReturnSelfFromGraveyardEffect(obj=obj, destination="hand", source=obj)
                ability = TriggeredAbility(
                    trigger_event=EventType.MILL_CARD,
                    effects=[effect],
                    optional=True,
                    controller_id=player.id,
                    source=obj,
                    description=f"{obj.name}: zurück auf die Hand nehmen",
                )
                self.pending_triggers.append((ability, event))

    def put_triggers_on_stack(self) -> int:
        """Move fired triggers onto the stack (RULE 603.3). Returns count.

        Active player's triggers are placed first so they resolve last
        (RULE 603.3b APNAP ordering). When `state.interactive_ordering` is on
        and the active player has two or more simultaneous triggers, they
        choose the intra-player order via a `pending_choice` (RULE 603.3b)
        instead of a deterministic placement.
        """
        if not self.pending_triggers:
            return 0
        active_id = self.state.active_player.id
        mine = [t for t in self.pending_triggers if t[0].controller_id == active_id]
        rest = [t for t in self.pending_triggers if t[0].controller_id != active_id]

        if self.state.interactive_ordering and len(mine) >= 2 and not self.state.pending_choice:
            # Defer to the player: stash the sets and open the ordering choice.
            self._ordering_active = mine
            self._ordering_rest = rest
            self.pending_triggers.clear()
            self.state.pending_choice = self._trigger_order_choice()
            return 0

        count = len(self.pending_triggers)
        self.pending_triggers.clear()
        self._place_triggers(mine + rest)  # active first (bottom of stack)
        return count

    @staticmethod
    def _trigger_target_specs(effects: list[Any]) -> list[TargetSpec]:
        """Every targeting effect's requirement in ``effects``, in order
        (RULE 115.1).

        One `TargetSpec` per targeting effect — `_place_or_pause_trigger`
        gathers one target per spec (via `_continue_trigger_multi_target`
        for the 2+ case, `StackItem.target_groups`-partitioned so each
        effect resolves against its own target, not a shared list). Takes a
        raw effects list rather than an ability, since a modal trigger's
        *chosen mode* — not the ability's own (possibly empty) ``effects``
        — is what actually needs a target; RULE 700.2's mode choice is made
        first (see `_place_triggers`), before this ever runs on the mode's
        effects.
        """
        specs: list[TargetSpec] = []
        for effect in effects:
            # `target_specs` (not ``target_spec``) so a single effect that
            # genuinely needs two differently-typed targets — "attach target
            # Equipment you control to target creature you control" — is
            # gathered as two requirements (`GameEffect.extra_target_specs`).
            specs.extend(getattr(effect, "target_specs", None) or [])
        return specs

    def _place_triggers(self, queue: list[tuple["TriggeredAbility", GameEvent]]) -> None:
        """Place queued triggers (RULE 603.3), pausing on one that's modal
        (RULE 700.2 — the mode is chosen first, before any target/"you may"
        choice its own effects might still need), needs a target, or is a
        "you may" with nothing to target, instead of just resolving/skipping
        it blind (RULE 115/603.3c/603.5).

        A mandatory, non-modal trigger with no targeting effect is placed
        immediately (unaffected — the overwhelming common case). One that's
        modal, targets, or is optional, opens a `pending_choice`:
        `resolve_trigger_mode_choice`/`resolve_trigger_target_choice` places
        it (or not, if declined) and resumes this same queue. A *required*
        target with no legal option at all doesn't go on the stack (RULE
        603.3c) — dropped, not placed.

        Note: a trigger placed via the (opt-in, off-by-default) RULE 603.3b
        interactive-ordering choice (`resolve_trigger_order_choice`) is
        placed directly and does *not* pause for any of these — combining
        manual trigger ordering with a modal/optional/targeted trigger among
        the ordered set is a narrow, undocumented-further edge case, not
        handled here.
        """
        while queue:
            ability, event = queue.pop(0)
            if getattr(ability, "reflexive", False):
                # RULE 603.3d "that permanent/spell": the target is the object
                # that fired ``event``, not a chosen one — bake it in and
                # place directly (no `trigger_target` choice). A vanished
                # object (spell already off the stack) drops the trigger
                # (RULE 603.3c), same as a required target with no legal pick.
                obj = self.state.find_object(event.get("instance_id"))
                if obj is not None:
                    self._place_trigger(ability, targets=[obj], event=event)
                continue
            if ability.modes:
                self._pending_trigger_ability = ability
                self._pending_trigger_queue = queue
                self._pending_trigger_event = event
                self.state.pending_choice = self._trigger_mode_choice(ability)
                return
            if not self._place_or_pause_trigger(ability, ability.effects, queue, event=event):
                return

    def _place_or_pause_trigger(
        self,
        ability: "TriggeredAbility",
        effects: list[Any],
        queue: list[tuple["TriggeredAbility", GameEvent]],
        event: Optional[GameEvent] = None,
    ) -> bool:
        """Place ``ability`` using ``effects`` as its resolve-time effects if
        it can go on the stack immediately; otherwise open the matching
        `pending_choice` and return ``False`` (the caller must stop — the
        choice resolver re-enters `_place_triggers` on ``queue`` once
        answered). Returns ``True`` when the caller's loop may continue
        synchronously (placed, or dropped for lacking a legal required
        target).

        ``effects`` is ``ability.effects`` for an ordinary trigger, or a
        modal trigger's already-chosen mode's effects (`_trigger_mode_
        choice`/`resolve_trigger_mode_choice`) — only in the latter case
        does the placed `StackItem` carry ``effects`` directly instead of
        the `TriggeredAbility` wrapper (`_place_trigger`'s
        ``effects_override``), since the ability's own fixed ``effects``
        (empty for a modal trigger) is never what should resolve.
        """
        specs = self._trigger_target_specs(effects)
        override = effects if effects is not ability.effects else None
        if not specs:
            if not ability.optional:
                self._place_trigger(ability, effects_override=override, event=event)
                return True
            # RULE 603.5: a "you may" with no target still needs a choice
            # of whether to do it at all.
            self._pending_trigger_ability = ability
            self._pending_trigger_effects = override
            self._pending_trigger_queue = queue
            self._pending_trigger_event = event
            self.state.pending_choice = self._trigger_may_choice(ability)
            return False
        if len(specs) == 1:
            # The overwhelming common case — one targeting effect, unchanged
            # from before `target_groups` existed (a flat ``targets`` list
            # of exactly this one effect's picks).
            spec = specs[0]
            controller_id = ability.controller_id or self.state.active_player.id
            options = legal_targets(self.state, controller_id, spec, source=ability.source)
            if not options:
                if spec.optional:
                    # RULE 115.1a: "up to one target" is satisfied by
                    # choosing *zero* targets, so an empty board doesn't
                    # stop the ability going on the stack — it resolves with
                    # nothing chosen. Gilded Drake depends on exactly this:
                    # with no opponent's creature to exchange with, the
                    # ability must still resolve in order to make it
                    # sacrifice itself. Only a *required* target the board
                    # can't supply drops the trigger (RULE 603.3c, below).
                    self._place_trigger(ability, effects_override=override, event=event)
                return True  # RULE 603.3c: no legal target — never placed
            self._pending_trigger_ability = ability
            self._pending_trigger_effects = override
            self._pending_trigger_queue = queue
            self._pending_trigger_event = event
            self.state.pending_choice = self._trigger_target_choice(ability, options)
            return False
        # RULE 115.1/603.3c generalized: 2+ *different* targeting effects —
        # gather one target per effect, one choice at a time (mirrors
        # `_trigger_mode_choice`'s "pick up to N, one at a time"), then place
        # with `target_groups` so each effect resolves against its own pick.
        return self._continue_trigger_multi_target(ability, override, queue, specs, [], event)

    def _continue_trigger_multi_target(
        self,
        ability: "TriggeredAbility",
        override: Optional[list[Any]],
        queue: list[tuple["TriggeredAbility", GameEvent]],
        specs: list[TargetSpec],
        groups: list[list[Any]],
        event: Optional[GameEvent] = None,
    ) -> bool:
        """Gather the next not-yet-filled spec's target (RULE 115.1), one at
        a time, for a trigger with 2+ *different* targeting effects.

        ``groups`` is what's been picked so far, in spec order; once every
        spec has a group, the ability is placed with `target_groups=groups`
        (`_place_trigger`). A spec with no legal option is skipped (empty
        group) if it's "up to N" (``optional``), or drops the whole ability
        (RULE 603.3c — a required target the board can't supply) otherwise.
        """
        idx = len(groups)
        if idx >= len(specs):
            self._place_trigger(
                ability, target_groups=groups, effects_override=override, event=event
            )
            return True
        spec = specs[idx]
        controller_id = ability.controller_id or self.state.active_player.id
        options = legal_targets(self.state, controller_id, spec, source=ability.source)
        if not options:
            if spec.optional:
                return self._continue_trigger_multi_target(
                    ability, override, queue, specs, groups + [[]], event
                )
            return True  # RULE 603.3c: no legal target — never placed
        self._pending_trigger_ability = ability
        self._pending_trigger_effects = override
        self._pending_trigger_queue = queue
        self._pending_trigger_event = event
        self._pending_trigger_specs = specs
        self._pending_trigger_groups = groups
        # RULE 603.5: "you may" is asked once, on the *first* target — from
        # then on the ability is already committed to, so later specs are
        # never declinable on their own.
        self.state.pending_choice = self._trigger_target_choice(
            ability, options, kind="trigger_target_multi", allow_decline=(idx == 0 and ability.optional)
        )
        return False

    def _trigger_mode_choice(
        self, ability: "TriggeredAbility", chosen: Optional[list[int]] = None
    ) -> dict[str, Any]:
        """Build the `pending_choice` for a modal triggered ability's mode
        (RULE 700.2) — chosen as it's put on the stack, before any target/
        "you may" choice the chosen mode's own effects might still need
        (`resolve_trigger_mode_choice` hands off to `_place_or_pause_
        trigger` for that).

        ``chosen`` is the indices already picked in an earlier round of a
        "choose *N*" (``N>=2``) or "choose *N* or more" ability — excluded
        from this round's offer so the same mode can't be picked twice,
        mirroring the library search's "pick up to N, one at a time"
        pattern (`_search_choice`). Absent/empty for the first round and for
        the ordinary "choose one" case (``modes_choose == 1`` and not
        ``modes_at_least``).
        """
        options = ability.modes or []
        picked = set(chosen or [])
        choice_options: list[dict[str, Any]] = [
            {"id": str(i), "label": opt.get("description") or f"Modus {i + 1}"}
            for i, opt in enumerate(options)
            if i not in picked
        ]
        if ability.modes_or_both and ability.modes_choose == 1 and len(options) == 2 and not picked:
            # RULE 700.2e — only offered for the fixed choose-1-of-2 case.
            choice_options.append({"id": "both", "label": "Beides"})
        if ability.modes_at_least and len(picked) >= ability.modes_choose and len(picked) < len(options):
            # RULE 700.2 "choose N or more" — the minimum is met, so the
            # player may stop here instead of picking every remaining mode.
            choice_options.append({"id": "done", "label": "Fertig"})
        return {
            "kind": "trigger_mode",
            "player_id": ability.controller_id or self.state.active_player.id,
            "prompt": ability.description or "Modus für ausgelöste Fähigkeit wählen",
            "options": choice_options,
            "chosen": list(chosen or []),
        }

    def resolve_trigger_mode_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `trigger_mode` choice (RULE 700.2): pick which
        mode(s) this firing uses, then continue exactly like a non-modal
        trigger via `_place_or_pause_trigger` — the chosen mode's own
        effects may still need their own target/"you may" choice next, so
        this doesn't necessarily place anything itself. ``answer`` is a
        mode's index (as a string), ``"both"`` (RULE 700.2e), or ``"done"``
        (RULE 700.2 "choose N or more", only once the minimum is met); an
        unrecognized/missing answer defaults to the first not-yet-chosen
        mode rather than dropping a mandatory choice.

        For a "choose *N*" ability (``modes_choose > 1``, RULE 700.2) this
        picks one mode per call — once fewer than ``modes_choose`` are
        picked, the choice re-opens (excluding what's already picked)
        instead of placing anything, exactly like `resolve_search_choice`
        offering a library search "one card at a time". For "choose *N* or
        more" (``modes_at_least``) the choice keeps re-opening past the
        minimum too, until either every mode is picked or the player answers
        "done". Once enough are picked, every chosen mode's effects combine
        **in printed order** (not pick order) — RULE 700.2's modes resolve
        in the order the ability's text lists them, same as RULE 700.2e
        "both" already did.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "trigger_mode":
            raise ValueError("no pending trigger mode choice to resolve")
        ability = self._pending_trigger_ability
        queue = self._pending_trigger_queue
        event = self._pending_trigger_event

        options = (ability.modes or []) if ability is not None else []
        if ability is None or not options:
            self.state.pending_choice = None
            self._pending_trigger_ability = None
            self._pending_trigger_queue = []
            self._pending_trigger_event = None
            self._place_triggers(queue)
            return

        already_chosen: list[int] = list(choice.get("chosen") or [])

        if answer == "both" and ability.modes_or_both and ability.modes_choose == 1 and len(options) == 2:
            effects: list[Any] = []
            for opt in options:
                effects.extend(opt["effects"])
        elif (
            answer == "done"
            and ability.modes_at_least
            and len(already_chosen) >= ability.modes_choose
        ):
            effects = []
            for i in sorted(already_chosen):
                effects.extend(options[i]["effects"])
        else:
            available = [i for i in range(len(options)) if i not in already_chosen]
            try:
                idx = int(answer) if answer is not None else available[0]
            except (TypeError, ValueError):
                idx = available[0]
            if idx not in available:
                idx = available[0]
            picked = already_chosen + [idx]
            more_needed = len(picked) < ability.modes_choose or (
                ability.modes_at_least and len(picked) < len(options)
            )
            if more_needed:
                # RULE 700.2 "choose N"/"choose N or more": re-open, excluding what's picked.
                self.state.pending_choice = self._trigger_mode_choice(ability, chosen=picked)
                return
            # Enough modes picked — combine in printed order, not pick order.
            effects = []
            for i in sorted(picked):
                effects.extend(options[i]["effects"])

        self.state.pending_choice = None
        self._pending_trigger_ability = None
        self._pending_trigger_queue = []
        self._pending_trigger_event = None
        if self._place_or_pause_trigger(ability, effects, queue, event=event):
            self._place_triggers(queue)

    def _trigger_target_choice(
        self,
        ability: "TriggeredAbility",
        options: list[dict[str, Any]],
        kind: str = "trigger_target",
        allow_decline: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Build the `pending_choice` offering ``options`` as an ability's
        target — one button per legal permanent/player, matching the generic
        choice UI's `{"id", "label", "instance_id"?}` option shape (the same
        one search/cascade/discover/order_triggers already use).

        ``kind``/``allow_decline`` are only overridden by
        `_continue_trigger_multi_target` (2+ *different* targeting effects,
        ``"trigger_target_multi"`` — its own resolver,
        `resolve_trigger_target_multi_choice`, so the single-spec path below
        stays byte-for-byte unchanged); ``allow_decline=None`` keeps this
        method's original behaviour of following ``ability.optional``
        (RULE 603.5 "you may").
        """
        choice_options: list[dict[str, Any]] = []
        for opt in options:
            if "instance_id" in opt:
                choice_options.append(
                    {"id": str(opt["instance_id"]), "label": opt["name"], "instance_id": opt["instance_id"]}
                )
            else:
                choice_options.append({"id": opt["player_id"], "label": opt["name"]})
        decline = ability.optional if allow_decline is None else allow_decline
        if decline:
            choice_options.append({"id": "decline", "label": "Nichts wählen"})
        return {
            "kind": kind,
            "player_id": ability.controller_id or self.state.active_player.id,
            "prompt": ability.description or "Ziel für ausgelöste Fähigkeit wählen",
            "options": choice_options,
        }

    def _trigger_may_choice(self, ability: "TriggeredAbility") -> dict[str, Any]:
        """Build the `pending_choice` for a targetless "you may" trigger
        (RULE 603.5) — do it, or don't. Reuses the ``trigger_target`` kind
        (same resolver, same generic choice UI); ``"do"`` is the sentinel
        `resolve_trigger_target_choice` recognizes as "yes, without a
        target"."""
        return {
            "kind": "trigger_target",
            "player_id": ability.controller_id or self.state.active_player.id,
            "prompt": ability.description or "Ausgelöste Fähigkeit ausführen?",
            "options": [
                {"id": "do", "label": "Ausführen"},
                {"id": "decline", "label": "Nichts tun"},
            ],
        }

    def resolve_trigger_target_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `trigger_target` choice, then resume `_place_
        triggers` on whatever was still queued behind it.

        ``answer`` is the chosen option's ``id`` — a permanent's stringified
        ``instance_id``, a player's id, or ``"do"`` for a targetless "you
        may" — or `None`/``"decline"`` to not do the (optional) ability at
        all, which simply never goes on the stack.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "trigger_target":
            raise ValueError("no pending trigger target choice to resolve")
        self.state.pending_choice = None
        ability = self._pending_trigger_ability
        queue = self._pending_trigger_queue
        effects_override = self._pending_trigger_effects
        event = self._pending_trigger_event
        self._pending_trigger_ability = None
        self._pending_trigger_queue = []
        self._pending_trigger_effects = None
        self._pending_trigger_event = None

        if answer == "do":
            if ability is not None:
                self._place_trigger(ability, effects_override=effects_override, event=event)
            self._place_triggers(queue)
            return

        if answer is not None and answer != "decline" and ability is not None:
            target = self._resolve_choice_option(choice["options"], str(answer))
            if target is not None:
                self._place_trigger(
                    ability, targets=[target], effects_override=effects_override, event=event
                )
        self._place_triggers(queue)

    def resolve_trigger_target_multi_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `trigger_target_multi` choice — one target for
        the *next* not-yet-filled targeting effect of a trigger with 2+
        *different* targeting effects (`_continue_trigger_multi_target`).

        ``answer`` is the chosen option's ``id``, same shape as
        `resolve_trigger_target_choice`. A decline (only ever offered on the
        first spec, RULE 603.5 "you may") abandons the whole ability — every
        spec after the first is already committed to. Once every spec has a
        target (or an empty pick for one that's "up to N" with nothing
        legal), the ability is placed with `target_groups` so each effect
        resolves against its own pick, not a shared list.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "trigger_target_multi":
            raise ValueError("no pending multi-target trigger choice to resolve")
        self.state.pending_choice = None
        ability = self._pending_trigger_ability
        queue = self._pending_trigger_queue
        effects_override = self._pending_trigger_effects
        specs = self._pending_trigger_specs
        groups = self._pending_trigger_groups
        event = self._pending_trigger_event
        self._pending_trigger_ability = None
        self._pending_trigger_queue = []
        self._pending_trigger_effects = None
        self._pending_trigger_specs = []
        self._pending_trigger_groups = []
        self._pending_trigger_event = None

        if answer is not None and answer != "decline" and ability is not None:
            target = self._resolve_choice_option(choice["options"], str(answer))
            groups = groups + [[target] if target is not None else []]
            if self._continue_trigger_multi_target(
                ability, effects_override, queue, specs, groups, event
            ):
                self._place_triggers(queue)
            return
        # Declined (or nothing left to resolve against) — the whole ability
        # is abandoned, same as a single-spec "you may" decline.
        self._place_triggers(queue)

    def _resolve_choice_option(self, options: list[dict[str, Any]], answer: str) -> Any:
        """The permanent/spell/player a `trigger_target` option ``answer``
        names.

        ``instance_id`` options aren't always a *battlefield* permanent —
        ``kind="spell"`` (`targeting.legal_targets`, Nether Void-shaped
        "whenever a player casts a spell, counter it unless…") offers a
        `StackItem`'s own object, which `state.permanents()` alone would
        never find (RULE 111.7: a spell isn't a permanent). `state.
        find_object` already searches every zone, stack included.
        """
        match = next((o for o in options if o["id"] == answer), None)
        if match is None:
            return None
        if "instance_id" in match:
            return self.state.find_object(match["instance_id"])
        try:
            return self.state.player_by_id(match["id"])
        except KeyError:
            return None

    def _place_trigger(
        self,
        ability: "TriggeredAbility",
        targets: Optional[list[Any]] = None,
        effects_override: Optional[list[Any]] = None,
        target_groups: Optional[list[list[Any]]] = None,
        event: Optional[GameEvent] = None,
    ) -> None:
        """Push ``ability`` onto the stack. ``effects_override``, when given,
        replaces the usual ``[ability]`` wrapper with a raw effects list — a
        modal trigger's already-chosen mode (`_place_or_pause_trigger`),
        which resolves those effects directly rather than through
        `TriggeredAbility.apply()` reading the ability's own (empty)
        ``effects``. `StackItem._derive_category` still classifies the item
        as ``"triggered_ability"`` either way (any non-spell ability item
        defaults to that), so nothing downstream needs to know.

        ``target_groups``, when given (2+ *different* targeting effects,
        gathered one at a time by `_continue_trigger_multi_target`),
        partitions ``targets`` per effect — see `StackItem.target_groups`.
        ``targets`` itself is then derived as the flattened union (unless
        explicitly given) so every existing flat-``targets`` consumer
        (`check_ward` below, Aura attachment, the stack display) still sees
        every chosen target, same as before ``target_groups`` existed.
        """
        if target_groups is not None and targets is None:
            targets = [t for group in target_groups for t in group]
        controller_id = ability.controller_id or self.state.active_player.id
        item = StackItem(
            kind="ability",
            controller_id=controller_id,
            effects=effects_override if effects_override is not None else [ability],
            description=ability.description or "triggered ability",
            targets=targets,
            target_groups=target_groups,
            source=ability.source,
            trigger_event=event,
        )
        self.state.stack.append(item)
        try:
            controller = self.state.player_by_id(controller_id)
        except KeyError:
            controller = None
        if controller is not None:
            self.check_ward(item, controller)

    def _trigger_order_choice(self) -> dict[str, Any]:
        """Build the `pending_choice` for ordering the active player's triggers.

        Each option is one still-to-be-placed trigger; the player picks the one
        to put on the stack next (RULE 603.3b). Picked first → placed first →
        resolves last (the stack is LIFO)."""
        options = [
            {"id": str(i), "label": ability.description or "Ausgelöste Fähigkeit"}
            for i, (ability, _event) in enumerate(self._ordering_active)
        ]
        return {
            "kind": "order_triggers",
            "player_id": self.state.active_player.id,
            "prompt": "Reihenfolge der ausgelösten Fähigkeiten wählen",
            "options": options,
        }

    def resolve_trigger_order_choice(self, index: Optional[int]) -> None:
        """Place the chosen trigger next, then re-ask or finish (RULE 603.3b).

        ``index`` selects one of the remaining active-player triggers (by its
        option id). When one is left it is placed automatically, then the
        non-active-player triggers go on top; the choice is cleared."""
        if not self._ordering_active:
            self.state.pending_choice = None
            return
        # Default to the first if the index is missing/out of range.
        if index is None or not 0 <= index < len(self._ordering_active):
            index = 0
        ability, _event = self._ordering_active.pop(index)
        self._place_trigger(ability)

        if len(self._ordering_active) > 1:
            self.state.pending_choice = self._trigger_order_choice()
            return
        # One (or none) left: place it and the non-active triggers, then finish.
        for remaining, _e in self._ordering_active:
            self._place_trigger(remaining)
        for ability, _e in self._ordering_rest:
            self._place_trigger(ability)
        self._ordering_active = []
        self._ordering_rest = []
        self.state.pending_choice = None

    # ------------------------------------------------------------------
    # "Enters with N counters" (RULE 614.1-style replacement clause)
    # ------------------------------------------------------------------

    def _apply_entry_counters(self, obj: GameObject, x_paid: int = 0) -> None:
        """Put ``obj``'s RULE 614.1-style "enters with N counters" starting
        counters on it, read off its printed text.

        Called at every battlefield-entry site right after the tapped-entry
        check (`ability_catalogue.enters_tapped`) and before ``obj`` is
        actually added to the battlefield, so the counters are already
        present when ENTERS_BATTLEFIELD fires and any trigger/continuous
        pass reads them. ``x_paid`` is the object's actual paid X (RULE
        107.3c) — 0 for anything that didn't just resolve off a cast-for-X
        (a token, a card reanimated/searched onto the battlefield, …).
        """
        # RULE 702.32a Fading N / RULE 702.61a Vanishing N: "this permanent
        # enters with N <fade|time> counters on it". Read off the parsed
        # keyword rather than the reminder text — the keyword *is* the rule,
        # and the reminder sentence isn't guaranteed to be printed.
        for kind, keyword in (("fade", "fading"), ("time", "vanishing")):
            param = (getattr(obj, "parametric_keywords", None) or {}).get(keyword)
            if param and int(param.get("n", 0) or 0) > 0:
                obj.add_counters(kind, int(param["n"]))

        condition = ability_catalogue.entry_counters(obj.card)
        if condition is None:
            return
        if condition.get("kicked_gate") or condition.get("kicked_scale"):
            # RULE 702.33b: gated/scaled on how many times Kicker was paid
            # (`GameObject.kicker_count`, stamped at cast time) — 0 for
            # anything that didn't just resolve off a kicked cast (a token,
            # a card reanimated/searched onto the battlefield, …).
            kicker_count = getattr(obj, "kicker_count", 0) or 0
            if condition.get("kicked_gate"):
                amount = condition["count"] if kicker_count > 0 else 0
            else:
                amount = condition["count"] * kicker_count
            grant_keyword = condition.get("grant_keyword")
            if grant_keyword and kicker_count > 0:
                # The same kicked gate as the counters, applied to a granted
                # keyword instead (RULE 702.33b's "...and with <keyword>."
                # tail) — a one-time additive mutation onto `intrinsic_
                # keywords`, not a continuous static: `kicker_count` never
                # changes after cast, so this is exact, not an
                # approximation, and it's read fresh every layer-engine
                # pass the same way a card's own printed flag keywords are
                # (`effect_binder.attach_to_object`'s flag-keyword handling).
                obj.intrinsic_keywords.add(grant_keyword)
        else:
            amount = x_paid if condition["is_x"] else condition["count"]
        if amount > 0:
            obj.add_counters(condition["counter_type"], amount)

    # ------------------------------------------------------------------
    # Conditional tap-lands (RULE 614.1)
    # ------------------------------------------------------------------

    def enter_land_tapped(self, obj: GameObject) -> None:
        """Resolve ``obj``'s RULE 614.1 tapped-entry as it's played.

        The deterministic conditional shapes — check lands ("unless you
        control a Mountain or a Forest"), fast/slow lands ("unless you
        control two or fewer/more other lands", or the basic-land-counting
        variant, "… two or more basic lands") and Commander "Battlebond"
        lands ("unless you have two or more opponents") — are decided
        immediately off the board/game state ``obj``'s controller already
        has (`land_tap_condition` is read *before* ``obj`` itself is added
        to the battlefield, so "other lands" naturally excludes it). A
        shock land's "you may pay N life" is a genuine choice: ``obj``
        defaults tapped (as if declined) and a `land_tapped` `pending_choice`
        opens; `resolve_land_tapped_choice` flips it untapped if the
        controller pays.
        """
        condition = ability_catalogue.land_tap_condition(obj.card)
        kind = condition["kind"]
        if kind == "unless_types":
            types = condition["types"]
            controlled = [
                o
                for o in self.state.battlefield
                if o.is_land and o.controller_id == obj.controller_id
            ]
            obj.tapped = not any(
                any(t in o.card.type_line.lower() for t in types) for o in controlled
            )
        elif kind == "unless_count":
            if condition.get("basic"):
                other_lands = sum(
                    1
                    for o in self.state.battlefield
                    if o.is_land
                    and o.controller_id == obj.controller_id
                    and "basic" in o.card.type_line.lower()
                )
            else:
                other_lands = sum(
                    1
                    for o in self.state.battlefield
                    if o.is_land and o.controller_id == obj.controller_id
                )
            if condition["cmp"] == "le":
                obj.tapped = not (other_lands <= condition["count"])
            else:
                obj.tapped = not (other_lands >= condition["count"])
        elif kind == "unless_opponents":
            # RULE 614.1 / Battlebond lands: untapped iff the game itself has
            # enough opponents — a property of the game, not the board.
            opponents = [
                p for p in self.state.living_players() if p.id != obj.controller_id
            ]
            obj.tapped = not (len(opponents) >= condition["count"])
        elif kind == "unless_opponents_count":
            # "Turbulent" land cycle: untapped iff the *total* lands across
            # all opponents (not the controller's own) compares as stated.
            opponent_lands = sum(
                1
                for o in self.state.battlefield
                if o.is_land and o.controller_id != obj.controller_id
            )
            if condition["cmp"] == "le":
                obj.tapped = not (opponent_lands <= condition["count"])
            else:
                obj.tapped = not (opponent_lands >= condition["count"])
        elif kind == "pay_life":
            obj.tapped = True
            self._pending_land_choice_obj = obj
            self._pending_land_choice_amount = condition["amount"]
            self.state.pending_choice = self._land_tapped_choice(obj, condition["amount"])
        elif kind == "optional_bonus_rad":
            # Mariposa Military Base: the mirror image of a shock land —
            # untapped by default, with the controller able to choose
            # tapped instead for a rad-counter bonus.
            obj.tapped = False
            self._pending_land_choice_obj = obj
            self._pending_land_choice_amount = condition["amount"]
            self.state.pending_choice = self._land_tapped_bonus_choice(obj, condition["amount"])
        else:
            obj.tapped = kind == "always"
        if not obj.tapped:
            # RULE 614.1, board-wide: a *different* permanent's standing
            # effect ("Nonbasic lands your opponents control enter tapped."
            # — Archon of Emeria) can still force this land tapped even when
            # its own printed clause (if any) would have left it untapped —
            # a shock land's pending pay-life choice already defaults tapped
            # above, so this only ever adds a tap, never removes the choice.
            obj.tapped = continuous.enters_tapped_from_static(self.state, obj)

    def _land_tapped_choice(self, obj: GameObject, amount: int) -> dict[str, Any]:
        """Build the `pending_choice` for a shock land's pay-life decision."""
        return {
            "kind": "land_tapped",
            "player_id": obj.controller_id,
            "prompt": f"{obj.name}: {amount} Leben zahlen, um ungetappt ins Spiel zu kommen?",
            "options": [
                {"id": "pay", "label": f"{amount} Leben zahlen"},
                {"id": "decline", "label": "Getappt ins Spiel kommen lassen"},
            ],
        }

    def resolve_land_tapped_choice(self, answer: Optional[str]) -> None:
        """Answer a pending shock-land `land_tapped` choice.

        ``answer`` is ``"pay"`` to pay the life and keep it untapped, or
        anything else (``None``/``"decline"``) to leave it tapped — already
        the default `enter_land_tapped` set while the choice was open.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "land_tapped":
            raise ValueError("no pending land-tapped choice to resolve")
        self.state.pending_choice = None
        obj = self._pending_land_choice_obj
        amount = self._pending_land_choice_amount
        self._pending_land_choice_obj = None
        self._pending_land_choice_amount = 0
        if obj is not None and answer == "pay":
            player = self.state.player_by_id(obj.controller_id)
            self.lose_life(player, amount, cause="cost")
            obj.tapped = False

    def _land_tapped_bonus_choice(self, obj: GameObject, amount: int) -> dict[str, Any]:
        """Build the `pending_choice` for Mariposa Military Base's own
        "you may have this enter tapped, for a bonus" decision — the
        mirror image of `_land_tapped_choice`'s shock-land prompt."""
        return {
            "kind": "land_tapped_bonus",
            "player_id": obj.controller_id,
            "prompt": f"{obj.name}: getappt ins Spiel kommen lassen, um {amount} "
                      "Rad-Marken zu erhalten?",
            "options": [
                {"id": "tap", "label": f"Getappt ins Spiel kommen lassen ({amount} Rad-Marken)"},
                {"id": "decline", "label": "Ungetappt ins Spiel kommen lassen"},
            ],
        }

    def resolve_land_tapped_bonus_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `land_tapped_bonus` choice (Mariposa Military
        Base). ``answer`` is ``"tap"`` to enter tapped and get the rad
        counters, or anything else (``None``/``"decline"``) to stay
        untapped (already the default `enter_land_tapped` set while the
        choice was open) with no bonus.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "land_tapped_bonus":
            raise ValueError("no pending land-tapped-bonus choice to resolve")
        self.state.pending_choice = None
        obj = self._pending_land_choice_obj
        amount = self._pending_land_choice_amount
        self._pending_land_choice_obj = None
        self._pending_land_choice_amount = 0
        if obj is not None and answer == "tap":
            obj.tapped = True
            player = self.state.player_by_id(obj.controller_id)
            self.add_player_counters(player, amount, "rad", source=obj)

    def request_pay_energy_then(
        self, player: Player, amount: int, effect_specs: list[dict], source: Optional[GameObject]
    ) -> None:
        """Open the interactive "you may pay {E}×N. If you do, `<effect>`."
        choice (RULE 122, Aether Chaser-shaped) — the resolve-time energy
        sibling of the shock-land pay-life choice. Assumes the caller
        (`PayEnergyThenEffect`) already checked the player can afford it."""
        self._pending_pay_energy = {
            "player_id": player.id,
            "amount": int(amount),
            "effect_specs": [dict(d) for d in effect_specs],
            "source": source,
        }
        pips = "{E}" * int(amount)
        self.state.pending_choice = {
            "kind": "pay_energy_then",
            "player_id": player.id,
            "prompt": f"{pips} bezahlen?",
            "options": [
                {"id": "pay", "label": f"{pips} bezahlen"},
                {"id": "decline", "label": "Nicht bezahlen"},
            ],
        }

    def resolve_pay_energy_then_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `pay_energy_then` choice. ``answer == "pay"``
        spends the energy and resolves the follow-up effects; anything else
        (``None``/``"decline"``) does neither."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "pay_energy_then":
            raise ValueError("no pending pay-energy choice to resolve")
        self.state.pending_choice = None
        pending = self._pending_pay_energy
        self._pending_pay_energy = None
        if pending is None or answer != "pay":
            return
        player = self.state.player_by_id(pending["player_id"])
        amount = pending["amount"]
        if player.counters.get("energy", 0) < amount:
            return  # energy changed since the offer — decline by default
        self.add_player_counters(player, -amount, "energy")
        self._apply_effect_specs(pending["effect_specs"], pending["source"])

    def request_pay_cost_then(
        self,
        player: Player,
        cost: "ActivationCost",
        effect_specs: list[dict],
        source: Optional[GameObject],
        else_effect_specs: Optional[list[dict]] = None,
        prompt: Optional[str] = None,
        targets: Optional[list[Any]] = None,
    ) -> None:
        """Open the interactive "you may pay ``cost``. If you do, `<effect>`."
        choice (RULE 118.3-style optional payment mid-resolution).

        The general form of the already-shipped, energy-only
        `request_pay_energy_then` (Aether Chaser) and the *optional* mirror
        of `request_sacrifice_unless_pay` — same `_can_pay_player_cost`/
        `_pay_player_cost` machinery all three share, so an arbitrary
        `ActivationCost` (mana, life, discard, sacrifice) works without a
        fourth parallel payment path. Covers Mana Vault's upkeep untap and
        Wandering Archaic's per-opponent {2} tax.

        ``else_effect_specs`` is the "**If you don't**, `<effect>`." branch
        (Wandering Archaic: the opponent declining is what lets you copy
        their spell). A player who *can't* pay is never asked — the
        else-branch resolves straight away, the same "don't stall on a
        choice nobody can act on" shortcut ward and `counter_unless_pays`
        take.

        ``targets`` are handed to whichever branch resolves — a reflexive
        trigger's already-baked "that spell" (Wandering Archaic's copy),
        which the branch effects would otherwise never see, since they are
        built fresh at answer time rather than sitting on the stack item.
        """
        specs = [dict(d) for d in effect_specs]
        else_specs = [dict(d) for d in (else_effect_specs or [])]
        if not self._can_pay_player_cost(player, cost):
            self._apply_effect_specs(else_specs, source, targets)
            return
        self._pending_pay_cost_then = {
            "player_id": player.id,
            "cost": cost,
            "effect_specs": specs,
            "else_effect_specs": else_specs,
            "source": source,
            "targets": list(targets or []),
        }
        cost_label = cost.label()
        self.state.pending_choice = {
            "kind": "pay_cost_then",
            "player_id": player.id,
            "prompt": prompt or f"{cost_label} bezahlen?",
            "options": [
                {"id": "pay", "label": f"{cost_label} bezahlen"},
                {"id": "decline", "label": "Nicht bezahlen"},
            ],
        }

    def resolve_pay_cost_then_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `pay_cost_then` choice. ``answer == "pay"``
        charges the cost and resolves the "if you do" effects; anything else
        resolves the "if you don't" branch (usually empty)."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "pay_cost_then":
            raise ValueError("no pending pay-cost-then choice to resolve")
        self.state.pending_choice = None
        pending = self._pending_pay_cost_then
        self._pending_pay_cost_then = None
        if pending is None:
            return
        player = self.state.player_by_id(pending["player_id"])
        targets = pending.get("targets") or None
        if answer != "pay" or not self._can_pay_player_cost(player, pending["cost"]):
            # Re-checked: the board can have changed since the offer was made.
            self._apply_effect_specs(pending["else_effect_specs"], pending["source"], targets)
            return
        self._pay_player_cost(player, pending["cost"])
        self._apply_effect_specs(pending["effect_specs"], pending["source"], targets)

    def _apply_effect_specs(
        self,
        effect_specs: list[dict],
        source: Optional[GameObject],
        targets: Optional[list[Any]] = None,
    ) -> None:
        """Build and apply serialized `EffectSpec` dicts right now, off the
        stack — the shared tail of every "if you do / if you don't" branch
        (`resolve_pay_cost_then_choice`, `resolve_pay_energy_then_choice`).
        Goes through `build_effects`, so the whitelist still gates every
        effect type (docs/09 security boundary)."""
        if not effect_specs:
            return
        from ..parser.oracle.spec import EffectSpec
        from .effect_binder import build_effects  # function-scoped: effects↔binder cycle

        built = build_effects(
            [
                EffectSpec(type=d["type"], params=dict(d.get("params") or {}))
                for d in effect_specs
            ],
            source,
        )
        for effect in built:
            effect.apply(self.context, targets)

    def request_sacrifice_unless_pay(
        self, player: Player, cost: "ActivationCost", source: Optional[GameObject]
    ) -> None:
        """Open the interactive "sacrifice ``source`` unless you pay ``cost``"
        choice (RULE 701.17 + RULE 118.3-style "unless" payment).

        The single biggest remaining upkeep-trigger template — Arcades
        Sabboth/Breeding Pit/Child of Gaea's "At the beginning of your
        upkeep, sacrifice ~ unless you pay `<cost>`.", and (granted onto
        another permanent) Aura Flux/Coral Net's quoted form.

        Deliberately built on the *same* pay-or-lose-it machinery ward
        already uses (`_can_pay_player_cost`/`_pay_player_cost`, generalized
        out of `resolve_ward_effect` for exactly this) rather than a second
        parallel one: both are "a rule asks a player for an arbitrary cost
        mid-resolution, and something bad happens if they don't", and
        `ActivationCost` already covers the whole real cost vocabulary these
        cards print (mana, life, discard, sacrifice-another-permanent).

        A player who *can't* pay is not asked — the permanent is sacrificed
        outright, the same "don't stall a passive goldfish opponent on a
        choice nobody can act on" shortcut ward and `counter_unless_pays`
        take. As with ward, a mana component has to be paid out of the pool
        as it stands at resolution (RULE 605.3a mana abilities during
        resolution aren't modeled for either).
        """
        if source is None:
            return
        if not self._can_pay_player_cost(player, cost):
            self.put_into_graveyard(source)  # RULE 701.16c: sacrifice, not destruction
            return
        self._pending_sacrifice_unless_pay = {
            "player_id": player.id,
            "cost": cost,
            "source": source,
        }
        cost_label = cost.label()
        self.state.pending_choice = {
            "kind": "sacrifice_unless_pay",
            "player_id": player.id,
            "prompt": f"{cost_label} bezahlen, um {source.name} zu behalten?",
            "options": [
                {"id": "pay", "label": f"{cost_label} bezahlen"},
                {"id": "decline", "label": f"{source.name} opfern"},
            ],
        }

    def resolve_sacrifice_unless_pay_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `sacrifice_unless_pay` choice. ``answer == "pay"``
        charges the cost and keeps the permanent; anything else sacrifices
        it (RULE 701.17)."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "sacrifice_unless_pay":
            raise ValueError("no pending sacrifice-unless-pay choice to resolve")
        self.state.pending_choice = None
        pending = self._pending_sacrifice_unless_pay
        self._pending_sacrifice_unless_pay = None
        if pending is None:
            return
        source = pending["source"]
        try:
            player = self.state.player_by_id(pending["player_id"])
        except KeyError:
            player = None
        if answer == "pay" and player is not None:
            # Re-check: the board can have changed between the offer and the
            # answer (an interactive session hands control back to the UI in
            # between), and a promise to pay we can't honour must not
            # silently keep the permanent for free.
            if self._can_pay_player_cost(player, pending["cost"]):
                self._pay_player_cost(player, pending["cost"])
                return
        if source is not None and source in self.state.battlefield:
            self.put_into_graveyard(source)

    # ------------------------------------------------------------------
    # Casting & the stack (RULE 601 / 608)
    # ------------------------------------------------------------------

    def is_permanent_spell(self, card: Card) -> bool:
        """A spell that becomes a permanent on resolution (RULE 608.3)."""
        return not (card.is_instant or card.is_sorcery)

    def cast_spell(
        self,
        player: Player,
        obj: GameObject,
        targets: Optional[list[Any]] = None,
        x: int = 0,
        cost: Optional[ManaCost] = None,
        target_groups: Optional[list[list[Any]]] = None,
    ) -> StackItem:
        """Pay the cost, move the card to the stack (RULE 601).

        ``x`` is the announced value (RULE 601.2b) for a cost containing
        ``{X}``; ignored otherwise. ``cost`` lets the caller supply an already
        adjusted cost (X resolved, static reductions applied — RULE 601.2f);
        omitted, the printed cost is used. Timing/priority legality is enforced
        by the caller; this performs the mechanical cast. Raises ValueError if
        the mana cost can't be paid.

        ``target_groups``, when given, partitions ``targets`` per targeting
        effect — see `StackItem.target_groups`. Needed only when ``obj``
        carries 2+ *different* targeting effects; omitted (``None``), every
        effect reads ``targets`` directly, unchanged from before this existed.
        ``targets`` itself is derived as the flattened union when not given
        explicitly, so `check_ward` below and every other flat-``targets``
        consumer still sees every chosen target.
        """
        if target_groups is not None and targets is None:
            targets = [t for group in target_groups for t in group]
        if cost is None:
            cost = self.mana_cost_of(obj.card)
            if cost.has_variable:
                cost = cost.with_x(x)
        # RULE 702.88b Rebound: cast from hand arms the "exile instead of
        # graveyard, then reopen a free-cast window next upkeep" behaviour
        # `resolve_top_of_stack` checks for below — recast later from that
        # same window (zone already EXILE here), Rebound doesn't repeat.
        if getattr(obj, "has_rebound", False) and obj.zone == Zone.HAND:
            obj.rebound_pending = True
        # RULE 702.88b's own free-cast window (`ReboundFreeCastWindowEffect`)
        # — consumed the instant it's used, same "check, then discard" shape
        # `mana_wildcard_permission`'s per-card grant already uses.
        free_cast = obj.instance_id in self.state.free_cast_instance_ids
        if free_cast:
            life_spent = 0
        else:
            allows_restriction = restriction_predicate_for_cast(obj, has_x=cost.has_variable)
            # RULE 605.1a "you may spend mana as though it were mana of any
            # color/type" (Mnemonic Betrayal-shaped), scoped to casting this
            # one exiled card — see `GameState.mana_wildcard_permission`.
            wildcard = self.state.mana_wildcard_permission.get(obj.instance_id)
            if not player.mana_pool.can_pay(
                cost, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard
            ):
                raise ValueError(f"{player.id} cannot pay for {obj.name}")
            life_spent = player.mana_pool.pay(
                cost, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard
            )
        self.lose_life(player, life_spent, cause="cost")
        if free_cast:
            self.state.free_cast_instance_ids.discard(obj.instance_id)
        # RULE 601.2b: remember the announced X on the object itself (not
        # just this ephemeral StackItem) — an "unless its controller pays
        # {X}" tied to *this* spell's own X (Logic Knot's Delve-adjacent
        # template) needs it after the spell has already left the stack.
        obj.x_paid = x
        # RULE 202.1/601.2h: how much mana was actually spent — 0 for a free
        # cast, otherwise the converted value of the cost that was paid
        # (already X-resolved and reduction-adjusted by the caller). Read by
        # the "if no mana was spent to cast it" trigger family via the
        # `SPELL_CAST` event's ``mana_spent`` key below.
        obj.mana_spent_to_cast = 0 if free_cast else cost.converted_mana_cost

        # RULE 601.2a: which zone the spell was cast *from* — snapshotted
        # before the move below, since by the time `SPELL_CAST` fires the
        # object already sits on the stack. "Whenever a player casts a spell
        # from their hand" (Possibility Storm) reads it as the event's
        # ``from_hand`` key.
        from_hand = obj.zone == Zone.HAND
        # Zone-agnostic (not just hand/command) so an Adventure creature can
        # be cast from exile (RULE 715.3d) with no dedicated branch here.
        self._remove_from_current_zone(player, obj)
        obj.adventure_castable = False
        if obj.prepared_source_id is not None:
            # RULE 722.3c: the source loses "prepared" the moment its
            # exiled copy becomes cast — not when the copy later resolves.
            source = self.state.find_object(obj.prepared_source_id)
            if source is not None:
                source.prepared = False
        obj.zone = Zone.STACK
        item = StackItem(
            kind="spell",
            controller_id=player.id,
            effects=self._effects_for_spell(obj),
            obj=obj,
            description=obj.name,
            targets=targets,
            x=x,
            target_groups=target_groups,
        )
        self.state.stack.append(item)
        self.state.record_stat(
            player.id, "spell", cmc=obj.card.converted_mana_cost, name=obj.name
        )
        self.state.fire_event(
            GameEvent(
                EventType.SPELL_CAST, player_id=player.id, card_id=obj.card.id, spell=obj.name,
                instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                mana_spent=obj.mana_spent_to_cast,
                from_hand=from_hand,
            )
        )
        self.check_ward(item, player)
        return item

    def cast_without_paying(
        self,
        player: Player,
        obj: GameObject,
        targets: Optional[list[Any]] = None,
    ) -> StackItem:
        """Cast a card *without paying its mana cost* (RULE 118.9 / 601.3b).

        The free-cast half of the cast/put/draw split: unlike a "put onto the
        battlefield" (a direct zone change, no stack), this is a real cast —
        the card goes on the **stack** and resolves normally (a permanent ends
        up on the battlefield firing `ENTERS_BATTLEFIELD`, an instant/sorcery
        applies its effects then hits the graveyard). It fires `SPELL_CAST`
        with ``free=True`` so a "when you cast" trigger still sees it.

        Reusable by every free-cast mechanic — cascade, discover, "you may
        cast it without paying its mana cost", suspend — from whatever zone
        the card currently sits in (hand, exile, library, graveyard).
        """
        from_hand = obj.zone == Zone.HAND
        self._remove_from_current_zone(player, obj)
        obj.zone = Zone.STACK
        # RULE 202.1: a free cast spends no mana at all — the "if no mana was
        # spent to cast it" family (Lavinia/Boromir) keys off this rather
        # than ``free``, since a *paid* cast can also come to 0 (see
        # `EventType.SPELL_CAST`).
        obj.mana_spent_to_cast = 0
        item = StackItem(
            kind="spell",
            controller_id=player.id,
            effects=self._effects_for_spell(obj),
            obj=obj,
            description=obj.name,
            targets=targets,
        )
        self.state.stack.append(item)
        self.state.fire_event(
            GameEvent(
                EventType.SPELL_CAST,
                player_id=player.id,
                card_id=obj.card.id,
                spell=obj.name,
                instance_id=obj.instance_id,
                object_types=sorted(obj.type_words),
                free=True,
                mana_spent=0,
                from_hand=from_hand,
            )
        )
        self.check_ward(item, player)
        return item

    def _remove_from_current_zone(self, player: Player, obj: GameObject) -> None:
        """Pull ``obj`` out of whichever zone currently holds it.

        Checks *every* player's zones, not just ``player``'s own — usually
        the same thing (a card sits in its owner's zone, and ``player`` is
        that owner), but not always: a Ragavan/Mnemonic Betrayal-shaped
        temp play/cast permission (`exile_with_play_permission`/
        `exile_graveyard_with_cast_permission`) can let ``player`` cast a
        card actually sitting in a *different* player's exile zone (RULE
        400.3: a card's zone is keyed by its owner, not by whoever currently
        has permission to play it).

        RULE 400.7: leaving its zone also turns a face-down exiled card
        (Beseech the Mirror) face up — nothing stays face down across a zone
        change, and this is the one point every cast path funnels through.
        """
        obj.face_down_in_exile = False
        for candidate in self.state.players:
            for cards in candidate.zones.values():
                if obj in cards:
                    cards.remove(obj)
                    return
        if obj in self.state.battlefield:
            self.state.remove_from_battlefield(obj)

    def _attachment_kind(self, obj: GameObject) -> Optional[str]:
        """The attachment family this object uses (Aura/Equipment/etc.)."""
        if not hasattr(obj, "parametric_keywords"):
            return None
        keywords = obj.parametric_keywords or {}
        for name in ("enchant", "equip", "fortify", "reconfigure"):
            if name in keywords:
                return name
        return None

    def _attachment_legal(self, obj: GameObject, target: GameObject) -> bool:
        """Whether ``obj`` can legally attach to ``target`` (basic MVP rules)."""
        if target not in self.state.permanents():
            return False  # RULE 702.26c: can't attach to a phased-out permanent
        if target.is_battle:
            # RULE 310.9: a battle can't be attached to, full stop. The
            # equip/reconfigure branches below already exclude it by
            # requiring a creature; this is what stops a broadly-worded Aura
            # ("enchant permanent") from landing on one.
            return False
        kind = self._attachment_kind(obj)
        if kind is None:
            return False
        if kind == "equip":
            # RULE 301.5b/702.6a: "target creature you control" — control
            # of the creature matters both when the ability is activated
            # and when it resolves, which is why this is re-checked here
            # rather than only at offer time (`targeting.legal_targets`).
            # Only the Equipment's own controller may activate its equip
            # ability (RULE 301.5d), so that's the controller who must
            # match — not necessarily the target's *owner*.
            return target.is_creature and target.controller_id == obj.controller_id
        if kind == "reconfigure":
            # RULE 702.151a: "another target creature you control."
            return (
                target.is_creature
                and target.controller_id == obj.controller_id
                and target is not obj
            )
        if kind == "fortify":
            # RULE 702.67a: "target land you control."
            return target.is_land and target.controller_id == obj.controller_id
        if kind == "enchant":
            quality = ((obj.parametric_keywords or {}).get(kind) or {}).get("quality", "")
            quality = str(quality).strip().lower()
            if not quality or quality in {"permanent", "anything"}:
                return True
            if quality == "creature":
                return target.is_creature
            if quality == "artifact":
                return target.card.is_artifact
            if quality == "enchantment":
                return target.card.is_enchantment
            if quality == "land":
                return target.is_land
            if quality == "planeswalker":
                return target.is_planeswalker
            return True
        return True

    def attach_to_target(self, obj: GameObject, target: GameObject) -> bool:
        """Attach an Aura/Equipment-like object to a legal target (RULE 303/301.5)."""
        if not self._attachment_legal(obj, target):
            return False
        obj.attached_to = target.instance_id
        return True

    def _detach_attachments_from(self, host: GameObject) -> None:
        """Unattach permanents attached to ``host`` when it leaves the battlefield.

        RULE 704.5m: an Aura not attached to a legal object goes to its
        owner's graveyard. RULE 704.5n: an Equipment or Fortification (which
        includes a Reconfigure permanent acting as one, RULE 702.151b) merely
        becomes unattached and remains on the battlefield.
        """
        for attached in list(self.state.permanents()):
            if attached.attached_to != host.instance_id:
                continue
            attached.attached_to = None
            if self._attachment_kind(attached) == "enchant":
                self._move_to_graveyard(attached)

    @staticmethod
    def _effects_for_spell(obj: GameObject) -> list[Any]:
        """Effects a spell applies when it resolves.

        For a permanent spell this is empty (resolving just puts it onto
        the battlefield); instants/sorceries carry their oracle-derived
        effects here once oracle-text parsing exists (docs/07 PART 5). The
        game object's own ``static_effects`` list is used as a hook so
        tests/fixtures can attach behavior without a parser yet.
        """
        return list(getattr(obj, "spell_effects", []))

    @staticmethod
    def _substitute_x(effects: list[Any], x: int) -> None:
        """Replace the ``"x"``/``"-x"`` sentinel amount/count/power/
        toughness on any of ``effects`` with the spell/ability's actually-
        announced {X} (RULE 107.3c/601.2b) — ``"-x"`` is its negation, for
        an X-scaled *debuff* whose X isn't itself negative (Toxic Deluge's
        "All creatures get -X/-X", where X comes from an ``additional_cost``
        life payment, not a mana ``{X}``, but is threaded through the exact
        same ``obj.x_paid``/`StackItem.x` mechanism regardless).
        ``"half_x_up"``/``"half_x_down"`` are the division-of-X sentinels
        (Contaminated Drink's "you get half X rad counters, rounded up") —
        no real card needs a plain (non-X) division yet, so this only
        covers the {X}-scaled case.

        Mirrors `_apply_entry_counters`'s ``is_x``-flag idiom, just generic
        over every one-shot effect's magnitude field instead of one
        hand-authored counter clause — a real int param never equals the
        literal string ``"x"``/``"-x"``, so this can't misfire on an
        unrelated ``amount``/``count``/``power``/``toughness`` value.
        """
        for effect in effects:
            for attr in ("amount", "count", "power", "toughness"):
                value = getattr(effect, attr, None)
                if value == "x":
                    setattr(effect, attr, x)
                elif value == "-x":
                    setattr(effect, attr, -x)
                elif value == "half_x_up":
                    setattr(effect, attr, -(-x // 2))  # ceiling division
                elif value == "half_x_down":
                    setattr(effect, attr, x // 2)

    def resolve_top_of_stack(self) -> Optional[StackItem]:
        """Resolve the topmost stack object (RULE 608). Returns it, or None."""
        if not self.state.stack:
            return None
        item = self.state.stack.pop()  # LIFO
        # RULE 603.1: expose the firing event for exactly this resolution, so
        # an effect that genuinely depends on *this* firing can read it
        # (`GameContext.trigger_event`). Restored rather than cleared,
        # because resolving one item can recursively resolve another.
        outer_trigger_event = self.context.trigger_event
        self.context.trigger_event = item.trigger_event
        try:
            return self._apply_stack_item(item)
        finally:
            self.context.trigger_event = outer_trigger_event

    def resume_deferred_effects(self) -> bool:
        """Pick a suspended effect list back up (RULE 608.2), innermost first.

        `_apply_effects_partitioned` parks the remainder of a resolution
        whenever one of its effects opens a `pending_choice`, because the
        game state holds only one at a time — a second interactive effect
        running now would overwrite the first player's prompt. Called by
        `GameEngine.resolve_until_stable` once nothing is pending, it drains
        one entry (which may itself pause again and re-park what's left of
        it). Returns whether anything was resumed.

        The resumed effects run *outside* the `GameContext.trigger_event`
        window their original resolution had — an effect that reads the
        firing event has to be the one that pauses, not one after it. No
        shipped card is shaped that way; the alternative (persisting the
        event through the suspension) would have to survive the state
        `clone()` that undo takes, which the event object isn't built for.
        """
        if self.state.pending_choice or not self.state.deferred_effects:
            return False
        resumed = self.state.deferred_effects.pop()
        _apply_effects_partitioned(
            resumed["effects"],
            self.context,
            resumed["targets"],
            resumed["target_groups"],
            source=resumed.get("source"),
            group_index=resumed.get("group_index", 0),
        )
        return True

    def _apply_stack_item(self, item: StackItem) -> Optional[StackItem]:
        """Apply an already-popped stack item's effects and route the card
        that produced it (RULE 608.2m/608.3) — `resolve_top_of_stack`'s body,
        split out only so that method can wrap it in the
        `GameContext.trigger_event` window."""
        if len(item.effects) == 1 and hasattr(item.effects[0], "effects"):
            # A single `TriggeredAbility`/`ActivatedAbility` wrapper — it
            # owns its *own* sub-effects list (`self.effects`, invisible to
            # this loop), so the per-effect partitioning has to happen one
            # level down, inside its own `apply()` (`_apply_effects_
            # partitioned`). Pass `target_groups` straight through rather
            # than treating the wrapper itself as "one targeting effect".
            self._substitute_x(item.effects[0].effects, item.x)
            item.effects[0].apply(self.context, item.targets, item.target_groups)
        else:
            self._substitute_x(item.effects, item.x)
            # RULE 115.1/601.2c: each effect gets only *its own* slice of
            # the partitioned targets, not the whole shared list — see
            # `StackItem.target_groups`. Shared with the nested (wrapper)
            # path above so both get the same partitioning *and* the same
            # RULE 608.2 suspend-on-pending-choice behaviour.
            _apply_effects_partitioned(
                item.effects, self.context, item.targets, item.target_groups
            )

        if item.kind == "spell" and item.obj is not None:
            obj = item.obj
            if self.is_permanent_spell(obj.card):
                # Self-contained: fires its own SPELL_RESOLVED (may pause on
                # an `enter_as_copy` choice first — RULE 614.1c/614.12 — so
                # it can't rely on the shared tail below).
                self._resolve_permanent_spell(item, obj)
                return item
            if obj.adventure_snapshot is not None:
                # RULE 715.3d: the Adventure instant/sorcery resolved — exile
                # the card (as the creature, not the spell half) instead of
                # the graveyard; it may be cast as the creature from there.
                snapshot = obj.adventure_snapshot
                obj.adventure_snapshot = None
                self.restore_face(obj, snapshot)
                self.exile(obj)
                obj.adventure_castable = True
            elif obj.buyback_paid:
                # RULE 702.27a: Buyback's additional cost was paid at cast
                # time — return the card to its owner's hand instead of the
                # graveyard, reusing the same zone-routing `return_to_hand`
                # an Unsummon-style bounce uses.
                obj.buyback_paid = False
                self.return_to_hand(obj)
            elif obj.cast_via_flashback:
                # RULE 702.34a: a spell cast via Flashback is exiled instead
                # of going to the graveyard when it resolves.
                obj.cast_via_flashback = False
                self.exile(obj)
            elif obj.rebound_pending:
                # RULE 702.88b: a Rebound spell cast from hand is exiled
                # instead of going to the graveyard, then a delayed trigger
                # reopens its free-cast window at the controller's next
                # upkeep (`ReboundFreeCastWindowEffect`).
                obj.rebound_pending = False
                self.exile(obj)
                self.state.delayed_triggers.append(
                    DelayedTrigger(
                        controller_id=obj.controller_id,
                        step="upkeep",
                        scope="controller",
                        effects=[ReboundFreeCastWindowEffect(source=obj)],
                        description=f"{obj.name}: ohne Bezahlen der Manakosten aus dem Exil wirken",
                    )
                )
            elif obj.zone != Zone.STACK:
                # One of this instant/sorcery's own resolving effects already
                # moved it elsewhere — a trailing "Exile ~." self-exile
                # clause (Mnemonic Betrayal/Teferi's Protection-shaped,
                # `ExileEffect`'s ``target_kind=None`` self mode) is the only
                # shape that does this today. Honour it instead of also
                # routing the card to the graveyard afterward.
                pass
            else:
                self._move_to_graveyard(obj)
            self.state.fire_event(
                GameEvent(EventType.SPELL_RESOLVED, spell=obj.name, controller_id=item.controller_id)
            )

        self.check_state_based_actions()
        return item

    def _resolve_permanent_spell(self, item: StackItem, obj: GameObject) -> None:
        """Finish resolving a permanent spell (RULE 608.3): summoning
        sickness, RULE 614.1 tapped-entry, the battlefield zone change,
        Aura attachment, and the ENTERS_BATTLEFIELD/SPELL_RESOLVED events.

        If ``obj`` carries an `enter_as_copy_effects` "you may have this
        enter as a copy of target X" (RULE 614.1c/614.12) and/or
        `enter_choice_effects` "as ~ enters, choose a creature type/color"
        (RULE 601.2b), those choices must be resolved *first* — before the
        object is ever added to the battlefield/fires ENTERS_BATTLEFIELD as
        itself — unlike every other resolution path here, this can pause on
        a `pending_choice` (possibly more than one, in sequence) and resume
        later from `resolve_enter_as_copy_choice`/`resolve_enter_choice`.
        """
        def _finish() -> None:
            if obj.cast_via_mutate:
                # RULE 702.140b-d: a mutate spell never enters the
                # battlefield as its own permanent — it merges onto the
                # creature it targeted, which stays the surviving object
                # (and so fires no ENTERS_BATTLEFIELD, RULE 702.140c).
                obj.cast_via_mutate = False
                host = next((t for t in item.targets if isinstance(t, GameObject)), None)
                if host is not None and host in self.state.permanents():
                    self.mutate_onto(obj, host, under=obj.mutate_under)
                else:
                    # RULE 608.2b: the mutate target is gone, so the spell
                    # resolves as an ordinary creature spell instead.
                    obj.summoning_sick = True
                    self.state.add_to_battlefield(obj)
                self.state.fire_event(
                    GameEvent(
                        EventType.SPELL_RESOLVED,
                        spell=obj.name,
                        controller_id=item.controller_id,
                    )
                )
                self.check_state_based_actions()
                return
            obj.summoning_sick = True
            # RULE 614.1: either the object's own printed tapped-entry
            # clause, or a *different* permanent's board-wide standing
            # effect ("Artifacts your opponents control enter tapped." —
            # Manglehorn/Dauntless Dismantler/Archon of Emeria-shaped).
            obj.tapped = ability_catalogue.enters_tapped(obj.card) or continuous.enters_tapped_from_static(
                self.state, obj
            )
            self._apply_entry_counters(obj, x_paid=getattr(obj, "x_paid", 0) or 0)
            # RULE 702.155b/714.3b: Read Ahead's chosen count (if any —
            # `_offer_read_ahead` stashes it here) replaces the ordinary
            # single lore counter `add_to_battlefield` would otherwise seed —
            # RULE 702.155a means only the chapter matching that exact count
            # fires; every lower chapter is skipped outright, not merely
            # delayed, so this must never let the default chapter-1 firing
            # happen first.
            read_ahead_count = self._pending_read_ahead_count
            self._pending_read_ahead_count = None
            self.state.add_to_battlefield(obj, saga_lore_override=read_ahead_count)
            if self._attachment_kind(obj) == "enchant":
                targets = [t for t in item.targets if isinstance(t, GameObject)]
                if not (targets and self.attach_to_target(obj, targets[0])):
                    self._move_to_graveyard(obj)
                    self.state.fire_event(
                        GameEvent(
                            EventType.SPELL_RESOLVED,
                            spell=obj.name,
                            controller_id=item.controller_id,
                        )
                    )
                    self.check_state_based_actions()
                    return
            self.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD,
                    controller_id=obj.controller_id,
                    card_id=obj.card.id,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
            self.state.fire_event(
                GameEvent(EventType.SPELL_RESOLVED, spell=obj.name, controller_id=item.controller_id)
            )
            self.check_state_based_actions()

        def _after_enter_choices() -> None:
            # RULE 702.155/714.3b: Read Ahead's "choose a number" pick (if
            # any) is the last of this pipeline's entry choices, offered
            # right before the object actually joins the battlefield.
            self._offer_read_ahead(obj, _finish)

        def _after_protector_choice() -> None:
            # RULE 601.2b: a "choose a creature type/color" pick (if any)
            # also happens before the object is added to the battlefield —
            # after the enter-as-copy choice (a copy takes on the copied
            # permanent's text, so its own "as ~ enters" clauses, if any,
            # are what should be offered — no real card in the pool combines
            # both, so the ordering is for correctness-in-principle only).
            self._offer_enter_choices(obj, _after_enter_choices)

        def _after_copy_choice() -> None:
            # RULE 310.8a/310.11a: a battle's protector is chosen "as it
            # enters", the same pre-entry window as every choice around it,
            # so it joins this pipeline rather than getting a bespoke one.
            self._offer_protector_choice(obj, _after_protector_choice)

        if obj.enter_as_copy_effects:
            self._offer_enter_as_copy(obj, _after_copy_choice)
        else:
            _after_copy_choice()

    def _offer_protector_choice(self, obj: GameObject, continuation: Callable[[], None]) -> None:
        """RULE 310.8a/310.11a: offer a battle's "choose a player to protect
        it" pick *before* it's added to the battlefield — the `_offer_enter_
        choices` sibling for battles, same continuation-passing shape.

        Calls ``continuation`` immediately when there's nothing to ask: a
        non-battle, or a battle with fewer than two eligible players. The
        one-eligible case still *sets* the protector (RULE 310.8a is
        mandatory, and a Siege with no protector would be swept up by RULE
        310.10's SBA) — it just doesn't stop to ask about a choice of one.
        With none eligible at all (a Siege in a solo goldfish, where its
        controller has no opponents) the protector stays ``None`` and that
        same SBA moves it to the graveyard, which is the rules-correct
        outcome rather than a special case worth coding around here.
        """
        if not obj.is_battle:
            continuation()
            return
        eligible = self._eligible_protectors(obj)
        if len(eligible) < 2:
            obj.protector_id = eligible[0].id if eligible else None
            continuation()
            return

        self._pending_protector_obj = obj
        self._pending_protector_continuation = continuation
        self.state.pending_choice = {
            "kind": "choose_protector",
            "player_id": obj.controller_id,
            "prompt": f"{obj.name}: Beschützer wählen (Regel 310.11a)",
            "options": [{"id": p.id, "label": p.name} for p in eligible],
        }

    def resolve_protector_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `choose_protector` choice (RULE 310.8a), then
        resume whatever `_offer_protector_choice` deferred.

        Mandatory, with no "decline" option offered — an unrecognized or
        missing ``answer`` falls back to the first eligible player, the same
        treatment `resolve_enter_choice` gives a skipped mandatory pick.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "choose_protector":
            raise ValueError("no pending protector choice to resolve")
        self.state.pending_choice = None
        obj = self._pending_protector_obj
        continuation = self._pending_protector_continuation
        self._pending_protector_obj = None
        self._pending_protector_continuation = None
        if obj is not None:
            self.choose_protector(obj, str(answer) if answer is not None else None)
        if continuation is not None:
            continuation()

    def _offer_enter_as_copy(self, obj: GameObject, continuation: Callable[[], None]) -> None:
        """RULE 614.1c/614.12: offer ``obj``'s "you may have this enter as a
        copy of target X" choice *before* it's added to the battlefield.

        Calls ``continuation`` immediately if there's no legal target to
        offer (RULE 603.3c-style: nothing to choose, nothing pauses);
        otherwise opens an ``enter_as_copy`` `pending_choice` and stashes
        ``continuation`` for `resolve_enter_as_copy_choice` to resume.
        ``obj`` is not yet on the battlefield at this point — `legal_targets`
        only needs it for exclusion/protection checks, both fine against an
        object that isn't in ``state.battlefield`` yet.
        """
        effect = obj.enter_as_copy_effects[0]
        spec = TargetSpec(kind=effect.target_kind)
        options = legal_targets(self.state, obj.controller_id, spec, source=obj)
        if not options:
            continuation()
            return
        choice_options = [
            {"id": str(o["instance_id"]), "label": o["name"], "instance_id": o["instance_id"]}
            for o in options
            if "instance_id" in o
        ]
        if effect.optional:
            choice_options.append({"id": "decline", "label": "Nichts wählen"})
        self._pending_enter_as_copy_obj = obj
        self._pending_enter_as_copy_effect = effect
        self._pending_enter_as_copy_continuation = continuation
        self.state.pending_choice = {
            "kind": "enter_as_copy",
            "player_id": obj.controller_id,
            "prompt": effect.description or "Als Kopie ins Spiel kommen lassen?",
            "options": choice_options,
        }

    def resolve_enter_as_copy_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `enter_as_copy` choice, then resume whatever
        battlefield-entry work `_offer_enter_as_copy` deferred.

        ``answer`` is a target's stringified ``instance_id``, or
        ``None``/``"decline"`` to enter as itself."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "enter_as_copy":
            raise ValueError("no pending enter-as-copy choice to resolve")
        self.state.pending_choice = None
        obj = self._pending_enter_as_copy_obj
        effect = self._pending_enter_as_copy_effect
        continuation = self._pending_enter_as_copy_continuation
        self._pending_enter_as_copy_obj = None
        self._pending_enter_as_copy_effect = None
        self._pending_enter_as_copy_continuation = None

        if answer is not None and answer != "decline" and obj is not None and effect is not None:
            target = self._resolve_choice_option(choice["options"], str(answer))
            if target is not None and target is not obj:
                copy_mechanics.become_copy(obj, target, effect.add_types, effect.add_subtypes)
        if continuation is not None:
            continuation()

    def _offer_enter_choices(self, obj: GameObject, continuation: Callable[[], None]) -> None:
        """RULE 601.2b: offer ``obj``'s queued "as it enters, choose a
        creature type/color" pick(s) *before* it's added to the battlefield —
        the `enter_choice_effects` sibling of `_offer_enter_as_copy`.

        Offers one at a time (a card only ever has one in the pool this
        engine models, but the queue shape mirrors `enter_choice_effects`
        exactly in case a future card stacks two): pops the first queued
        effect, opens its `pending_choice`, and stashes a continuation that
        re-enters this method for whatever remains before finally calling
        ``continuation``. Calls ``continuation`` immediately once the queue
        is empty (or was empty to begin with — nothing to choose, nothing
        pauses), same as `_offer_enter_as_copy`'s no-legal-target case.
        """
        if not obj.enter_choice_effects:
            continuation()
            return
        effect = obj.enter_choice_effects[0]
        remaining = obj.enter_choice_effects[1:]

        def _next() -> None:
            obj.enter_choice_effects = remaining
            self._offer_enter_choices(obj, continuation)

        if isinstance(effect, ChooseCreatureTypeReplacement):
            kind = "choose_creature_type"
            prompt = "Kreaturentyp wählen"
            options = [{"id": t, "label": t} for t in _creature_type_options(self.state, obj.controller_id)]
        elif isinstance(effect, ChooseNamedModeReplacement):
            kind = "choose_named_mode"
            prompt = "Modus wählen"
            options = [{"id": label.strip().lower(), "label": label} for label in effect.options]
        else:
            kind = "choose_color"
            prompt = "Farbe wählen"
            options = [{"id": color, "label": label} for color, label in self._ANY_COLOR_LABELS.items()]

        if not options:
            # RULE 601.2b's choice still has to happen in principle, but
            # with no legal answer (e.g. a puzzle board with no creature
            # cards anywhere) there's nothing to pause on — chosen_type/
            # chosen_color stays None, and every dependent selector then
            # just matches nothing, the same safe fallback an ordinary
            # unset subtype/colour filter already gets.
            _next()
            return

        self._pending_enter_choice_obj = obj
        self._pending_enter_choice_effect = effect
        self._pending_enter_choice_continuation = _next
        self.state.pending_choice = {
            "kind": kind,
            "player_id": obj.controller_id,
            "prompt": prompt,
            "options": options,
        }

    def resolve_enter_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `choose_creature_type`/`choose_color` choice
        (RULE 601.2b), then resume whatever `_offer_enter_choices` deferred —
        which may open the *next* queued choice rather than finishing entry
        outright.

        A mandatory choice (there's no "decline" option offered at all): an
        unrecognized/missing ``answer`` defaults to the first offered option,
        the same treatment `resolve_add_mana_any_color_choice` gives a
        missing mandatory answer, so a dependent selector is never silently
        starved by a skipped pick.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") not in (
            "choose_creature_type", "choose_color", "choose_named_mode",
        ):
            raise ValueError("no pending enter-choice to resolve")
        self.state.pending_choice = None
        obj = self._pending_enter_choice_obj
        continuation = self._pending_enter_choice_continuation
        self._pending_enter_choice_obj = None
        self._pending_enter_choice_effect = None
        self._pending_enter_choice_continuation = None

        options = choice["options"]
        valid_ids = {str(o["id"]) for o in options}
        chosen = str(answer) if answer is not None and str(answer) in valid_ids else (
            str(options[0]["id"]) if options else None
        )
        if obj is not None and chosen is not None:
            if choice["kind"] == "choose_creature_type":
                obj.chosen_type = chosen
            elif choice["kind"] == "choose_named_mode":
                obj.chosen_mode = chosen
            else:
                obj.chosen_color = chosen
        if continuation is not None:
            continuation()

    def _offer_read_ahead(self, obj: GameObject, continuation: Callable[[], None]) -> None:
        """RULE 702.155/714.3b: a Saga with Read Ahead lets its controller
        choose a number from 1 to its final chapter number as it enters,
        instead of the ordinary single lore counter — offered *before*
        battlefield entry, alongside `_offer_enter_as_copy`/
        `_offer_enter_choices` (same continuation-passing shape).

        RULE 702.155a: only the chapter ability whose number *exactly*
        matches the chosen count fires — every lower chapter is skipped for
        good (not merely delayed), so a choice of N doesn't replay chapters
        1..N-1 first. `_finish` in `_resolve_permanent_spell` reads the
        stashed `_pending_read_ahead_count` and passes it straight to
        `GameState.add_to_battlefield`'s ``saga_lore_override``, which seeds
        the Saga with that many counters and fires one `SAGA_CHAPTER` event
        for that exact count — the same single-event shape an ordinary
        Saga's entry uses for chapter 1.
        """
        final = _saga_final_chapter(obj.card)
        if (
            obj.is_token
            or not obj.card.is_saga
            or final <= 1
            or "read_ahead" not in obj.intrinsic_keywords
        ):
            continuation()
            return
        self._pending_read_ahead_obj = obj
        self._pending_read_ahead_continuation = continuation
        self.state.pending_choice = {
            "kind": "read_ahead",
            "player_id": obj.controller_id,
            "prompt": f"{obj.name}: Voraus lesen — Kapitelmarke wählen (1-{final})",
            "options": [{"id": str(n), "label": f"Kapitel {n}"} for n in range(1, final + 1)],
        }

    def resolve_read_ahead_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `read_ahead` choice (RULE 702.155), then resume
        whatever `_offer_read_ahead` deferred.

        A mandatory choice (no "decline" option is ever offered): an
        unrecognized/missing ``answer`` defaults to 1 (no read-ahead), the
        same missing-mandatory-answer treatment `resolve_enter_choice` gives.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "read_ahead":
            raise ValueError("no pending read-ahead choice to resolve")
        self.state.pending_choice = None
        obj = self._pending_read_ahead_obj
        continuation = self._pending_read_ahead_continuation
        self._pending_read_ahead_obj = None
        self._pending_read_ahead_continuation = None

        valid_ids = {str(o["id"]) for o in choice["options"]}
        chosen = str(answer) if answer is not None and str(answer) in valid_ids else "1"
        self._pending_read_ahead_count = int(chosen) if obj is not None else None
        if continuation is not None:
            continuation()

    # ------------------------------------------------------------------
    # Rules primitives (routed through replacements + events)
    # ------------------------------------------------------------------

    def draw(self, player: Player, count: int = 1) -> None:
        for _ in range(count):
            self._single_draw(player)

    def _single_draw(self, player: Player) -> None:
        # RULE 121.5-adjacent "each player can't draw more than N cards each
        # turn." (Spirit of the Labyrinth) — a cap checked *before* this draw
        # even starts (the extra draw simply doesn't happen, no replacement
        # rewrite involved), the draw-side mirror of `GameEngine.can_cast`'s
        # `cast_limit` gate. `draw(player, count>1)` calls this once per
        # card, so the cap is naturally enforced cumulatively across a
        # single "draw two cards" effect too.
        draw_limit = continuous.max_draws_per_turn(self.state)
        if draw_limit is not None and self.state.cards_drawn_this_turn.get(player.id, 0) >= draw_limit:
            return
        event = GameEvent(EventType.DRAW, player_id=player.id, count=1)

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is None:
                return
            if resolved.type == EventType.MILL:
                self.mill(player, resolved.get("count", 1))
                return
            # A DRAW event (possibly with a bumped count).
            n = resolved.get("count", 1)
            if len(player.library) < n:
                # Trying to draw from an empty library is a loss (RULE
                # 704.5c), flagged for the SBA check rather than raising.
                player.loss_reason = player.loss_reason or "draw_from_empty"
                player.attempted_draw_from_empty = True  # type: ignore[attr-defined]
            drawn = player.draw(n)
            if drawn:
                self.state.cards_drawn_this_turn[player.id] = (
                    self.state.cards_drawn_this_turn.get(player.id, 0) + len(drawn)
                )
                self.state.record_stat(player.id, "draw", amount=len(drawn))
                self.state.fire_event(
                    GameEvent(EventType.DRAW, player_id=player.id, count=len(drawn))
                )

        self.apply_replacements(event, on_resolved=_finish)

    def mill(self, player: Player, count: int) -> None:
        milled: list[GameObject] = []
        for _ in range(count):
            if not player.library:
                break
            obj = player.library.pop()
            obj.zone = Zone.GRAVEYARD
            player.graveyard.append(obj)
            self._flag_commander_zone_choice(obj)  # RULE 903.9a (rare: a commander milled from the library)
            milled.append(obj)
        self.state.fire_event(GameEvent(EventType.MILL, player_id=player.id, count=count))
        for obj in milled:
            if not obj.is_land:
                self.state.fire_event(
                    GameEvent(EventType.MILL_CARD, player_id=player.id, instance_id=obj.instance_id)
                )

    def discard(self, player: Player, count: int = 1) -> None:
        """Non-interactive discard: cost payment (`GameEngine._pay_activation_
        cost`/`_pay_additional_cast_cost`, ward, RULE 514.3 cleanup) pays a
        cost or resolves an SBA in one synchronous call, so it can't pause
        for a chooser — see `discard_choice` for the interactive, effect-
        resolution version looting-shaped effects use instead."""
        discarded = 0
        for _ in range(count):
            if not player.hand:
                break
            obj = player.hand.pop()  # auto-choose (no chooser in MVP)
            obj.zone = Zone.GRAVEYARD
            player.graveyard.append(obj)
            self._flag_commander_zone_choice(obj)  # RULE 903.9a
            discarded += 1
        if discarded:
            self.state.fire_event(
                GameEvent(EventType.DISCARD, player_id=player.id, count=discarded)
            )

    def discard_choice(self, player: Player, count: int, source: Optional[GameObject] = None) -> None:
        """Interactive discard (RULE 701.8): ``player`` — the one discarding,
        not necessarily an effect's controller (Mind Rot targets an
        opponent) — picks which ``count`` cards leave their own hand,
        through the same `request_choose_objects` chooser that replaced
        "auto-pick the first candidate" for sacrifice/tap/bounce effects.
        Forced with no prompt when the hand has at most ``count`` cards left
        (a "discard your hand" effect, or `count` >= hand size) — nothing to
        choose between. Used by looting-shaped effects (`DiscardEffect`);
        cost payment still uses the plain, non-interactive `discard` (see
        its own docstring) since a cost is paid in one synchronous call.
        """
        self.request_choose_objects(
            player, list(player.hand), "discard", count=count,
            prompt="Wähle eine Karte zum Abwerfen", source=source,
        )

    def put_hand_cards_on_top(self, player: Player, count: int) -> None:
        """Put up to ``count`` cards from ``player``'s hand on top of their
        library, "in any order" (RULE 701 — Brainstorm's "then put two cards
        from your hand on top of your library"). Auto-picks off the back of
        hand — no chooser in this MVP, the same idiom `discard` above uses;
        the actual *order* among the returned cards isn't anything this
        engine's library model exposes a distinction for, so the missing
        choice is inert either way.
        """
        for _ in range(count):
            if not player.hand:
                break
            obj = player.hand.pop()
            obj.zone = Zone.LIBRARY
            player.library.append(obj)  # top of deck is the list end

    def discard_specific(self, obj: GameObject) -> None:
        """Discard ``obj`` itself out of its owner's hand — Channel (RULE
        702.29)/Cycling (RULE 702.28)'s own "Discard this card" cost, unlike
        `discard` (a player-scoped count with no chooser, RULE 701.8's
        general form)."""
        player = self.state.player_by_id(obj.owner_id)
        player.remove_from_zone(obj, Zone.HAND)
        player.add_to_zone(obj, Zone.GRAVEYARD)
        self._flag_commander_zone_choice(obj)  # RULE 903.9a
        self.state.fire_event(
            GameEvent(EventType.DISCARD, player_id=player.id, count=1)
        )

    def deal_damage(
        self,
        target: Any,
        amount: int,
        source: Optional[GameObject] = None,
        combat: bool = False,
    ) -> None:
        is_player = isinstance(target, Player)
        # RULE 702.16c: protection prevents *all* damage from a source of the
        # stated quality, not just combat damage — a burn spell from a
        # protected colour fizzles here same as a blocked attacker would.
        # Players carry no protection in this model.
        if not is_player and source is not None and is_protected_from(target, source):
            return
        # RULE 702.16e: a *player* with protection from everything (Teferi's
        # Protection) is dealt no damage at all — the player-side mirror of
        # the permanent check above, which `is_protected_from` can't answer
        # because players carry no printed protection.
        if is_player and self._player_protected_from_everything(target):
            return
        target_id = target.id if is_player else target.instance_id
        event = GameEvent(
            EventType.DAMAGE,
            amount=amount,
            is_player=is_player,
            target_id=target_id,
            # Carried so a doubling/additional-damage replacement (RULE
            # 616.1, e.g. Furnace of Rath/Torbran) can filter by "a source
            # you control" / "combat damage" / "a red source" — see
            # `_double_damage_replacement`/`_additional_damage_replacement`.
            source_id=source.instance_id if source is not None else None,
            source_controller_id=source.controller_id if source is not None else None,
            source_colors=tuple(getattr(source.card, "color_identity", None) or ()) if source is not None else (),
            # Gratuitous Violence-shaped "a *creature* you control" doubling
            # (as opposed to Furnace of Rath's unscoped "a source") needs
            # this to tell the two apart — see `_double_damage_replacement`.
            source_is_creature=bool(getattr(source, "is_creature", False)),
            combat=combat,
        )

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is None:
                return
            final = resolved.get("amount", amount)
            if final <= 0:
                return
            if is_player:
                # RULE 120.3: damage dealt to a player causes that much life
                # loss. This is a *consequence* of damage, not a separate
                # event a player chose to trigger — go through the same
                # `lose_life` choke point as any other life loss so triggers
                # watching for "loses life" fire consistently regardless of
                # cause.
                self.lose_life(target, final, cause="damage")
                self.state.record_stat(target.id, "damage_taken", amount=final)
                if source is not None:
                    self.state.record_stat(source.controller_id, "damage_dealt", amount=final)
                    # RULE 903.10a: combat damage from a commander is tallied
                    # separately toward the 21-damage loss threshold.
                    if combat and source.is_commander:
                        target.add_commander_damage(source.instance_id, source.name, final)
                    if combat:
                        # RULE 120.3: remember *who* this source hit this turn
                        # — "target player who was dealt combat damage by ~
                        # this turn" (Hope of Ghirapur) is asked long after
                        # the damage step, when no live state records it. See
                        # `GameState.combat_damage_to_players_this_turn`.
                        self.state.combat_damage_to_players_this_turn.setdefault(
                            source.instance_id, set()
                        ).add(target.id)
            elif getattr(target, "is_planeswalker", False):
                # RULE 306.9: damage to a planeswalker removes that many
                # loyalty counters (the 0-loyalty SBA then sends it to the
                # graveyard).
                target.add_counters("loyalty", -final)
            elif getattr(target, "is_battle", False):
                # RULE 310.6: damage to a battle removes that many defense
                # counters — combat *and* non-combat alike (a burn spell
                # chips a battle down exactly like an attacker does), which
                # is why this sits here rather than in the combat path.
                # Hitting zero isn't handled here: the SBA pass owns both
                # the Siege's own RULE 310.11b defeat trigger and RULE
                # 310.7's graveyard move, so *every* route to zero defense
                # (a "remove a defense counter" effect as much as damage)
                # goes through one place. `add_counters` floors at zero, so
                # overkill damage can't leave a negative count behind.
                target.add_counters("defense", -final)
            else:
                target.damage_marked += final
            # `copy_with` (not a fresh `GameEvent`) so `source_id`/`combat`/
            # `source_controller_id` survive onto the broadcast event — a
            # "whenever equipped creature deals combat damage to a player"
            # trigger (`effect_binder._trigger_condition`'s ``filter``) reads
            # exactly these fields, and they'd otherwise be silently dropped
            # here even though the pre-replacement ``event`` above carried them.
            self.state.fire_event(resolved.copy_with(amount=final))

        self.apply_replacements(event, on_resolved=_finish)

    def lose_life(self, player: Player, amount: int, cause: str = "effect") -> None:
        """A player loses life (RULE 118-119), outside of the damage system.

        The single choke point for life loss, whatever causes it — damage
        (`deal_damage`, RULE 120.3), a cost paid with life (Phyrexian mana,
        RULE 118.4), or a direct effect (e.g. "target player loses 2 life").
        `cause` is metadata only ("damage" / "cost" / "effect") for
        logging/UI; nothing in the rules distinguishes *why* life was lost
        for trigger purposes, so every path fires the same `LIFE_LOST`
        event — except RULE 728.1a's ``cause="radiation"`` (rad counters'
        own inherent mill trigger, `RadiationMillEffect`), which a player
        can redirect into a life *gain* instead via "You gain life rather
        than lose life from radiation." (Strong, the Brutish Thespian,
        `continuous.has_radiation_life_gain`) — checked here rather than
        through the ordinary `ReplacementEffect`/`apply_replacements`
        machinery, since that only ever rewrites an event's amount, never
        redirects it into a different engine call.
        """
        if amount <= 0:
            return
        if self._life_locked(player):
            # RULE 119.6/611.2b: "your life total can't change" (Teferi's
            # Protection) — a continuous effect that simply forbids the
            # change, not a replacement that rewrites its amount, so it is
            # checked at this choke point rather than via
            # `apply_replacements`.
            return
        if cause == "radiation" and continuous.has_radiation_life_gain(self.state, player):
            self.gain_life(player, amount)
            return
        player.lose_life(amount)
        self.state.fire_event(
            GameEvent(EventType.LIFE_LOST, player_id=player.id, amount=amount, cause=cause)
        )

    def destroy(self, obj: GameObject, can_be_regenerated: bool = True) -> None:
        """RULE 701.6: destroy ``obj`` — replaceable (RULE 616), chiefly by a
        regeneration shield (RULE 701.16, `regenerate`) consuming the event
        instead of letting the permanent reach the graveyard. Not the entry
        point for a *non*-destruction move to the graveyard (sacrifice, 0
        toughness, …) — those go through `put_into_graveyard`/
        `_move_to_graveyard` directly, since RULE 701.16c says regeneration
        never applies to them.

        ``can_be_regenerated=False`` (Wrath of God's "They can't be
        regenerated.") skips the replacement pass entirely — a card-specific
        override of RULE 701.16, not RULE 701.16c (which is about sacrifice/
        0-toughness, unrelated to this) — so an existing shield simply
        doesn't get a chance to intercept this particular destroy.
        """
        if not can_be_regenerated:
            self._move_to_graveyard(obj)
            return
        event = GameEvent(EventType.DESTROY, target_id=obj.instance_id, object=obj.name)

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is not None:
                self._move_to_graveyard(obj)

        self.apply_replacements(event, on_resolved=_finish)

    def regenerate(self, obj: GameObject) -> None:
        """RULE 701.16: give ``obj`` a regeneration shield.

        The next time this turn ``obj`` would be destroyed (`destroy`, e.g.
        via RULE 704.5g lethal damage), the shield replaces that event with:
        remove it from combat, tap it, and remove all damage marked on it —
        instead of moving it to the graveyard. RULE 701.16c: this never
        applies to sacrifice, 0 toughness, or any other non-destruction move
        to the graveyard.

        Consumed on first use; each call adds its own independent shield
        (RULE 701.16a — several activations stack several shields). Any
        shield still unused simply sits in ``replacement_effects`` until
        `GameEngine._step_cleanup` sweeps it at end of turn (RULE 514.2),
        identified by the ``regeneration_shield`` marker so cleanup doesn't
        touch a card's own bind-time replacement effects living in the same
        list.
        """
        effect = ReplacementEffect(
            event_type=EventType.DESTROY,
            replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
            condition=lambda e, c: e.get("target_id") == obj.instance_id,
            source=obj,
            description=f"{obj.name}: Regenerationsschild",
        )
        effect.regeneration_shield = True

        def _replace(event: GameEvent, _context: GameContext) -> Optional[GameEvent]:
            if effect in obj.replacement_effects:
                obj.replacement_effects.remove(effect)
            obj.attacking = False
            obj.combat_defender = None
            obj.blocking = None
            obj.additional_blocking = []
            obj.blocked_by = []
            obj.dealt_deathtouch_damage = False
            obj.tapped = True
            obj.damage_marked = 0
            return None

        effect.replacement_fn = _replace
        obj.replacement_effects.append(effect)

    def put_into_graveyard(self, obj: GameObject) -> None:
        """Move ``obj`` to its owner's graveyard *without* going through
        `destroy` (RULE 701.16c: sacrifice is not destruction and can't be
        replaced by regeneration) — the entry point for a specific,
        already-chosen sacrifice victim (`GameEngine`'s cost-payment
        sacrifice path). `sacrifice`'s own auto-picked effect-driven
        sacrifice (RULE 701.17) uses this too, for the same reason.
        """
        self._move_to_graveyard(obj, cause="sacrifice")

    def sacrifice(self, player: Player, what: str = "permanent", count: int = 1) -> None:
        """``player`` sacrifices up to ``count`` permanents matching ``what``
        (RULE 701.17) — an effect-driven sacrifice (annihilator, RULE
        702.86), not a cost payment (`GameEngine._sacrifice_candidate`
        handles that separate path). Auto-picks the first matching permanent
        each time, the same non-interactive MVP convention the cost path
        uses; stops early if the player runs out of matching permanents.
        """
        for _ in range(count):
            candidate = next(
                (
                    obj
                    for obj in self.state.permanents_controlled_by(player.id)
                    if _matches_permanent_type(obj, what)
                ),
                None,
            )
            if candidate is None:
                return
            self.put_into_graveyard(candidate)

    def exile(self, obj: GameObject) -> None:
        """Move ``obj`` to its owner's exile zone (RULE 406), from anywhere.

        Fires `LEAVES_BATTLEFIELD` when it was in play, then `EXILE`. RULE
        903.9a covers a commander landing in exile exactly like one landing
        in a graveyard — `_flag_commander_zone_choice` marks it for the same
        SBA-offered move to the command zone.
        """
        was_on_battlefield = obj in self.state.battlefield
        owner = self.state.player_by_id(obj.owner_id)
        if was_on_battlefield:
            # RULE 603.6a "look back in time" — fire before removal, see
            # `_move_to_graveyard` for the full rationale.
            self.state.fire_event(
                GameEvent(
                    EventType.LEAVES_BATTLEFIELD,
                    object=obj.name,
                    owner_id=obj.owner_id,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
            self.state.remove_from_battlefield(obj)
        else:
            self._remove_from_current_zone(owner, obj)
        obj.tapped = False
        obj.damage_marked = 0
        owner.add_to_zone(obj, Zone.EXILE)
        self._flag_commander_zone_choice(obj)
        self.state.fire_event(
            GameEvent(EventType.EXILE, object=obj.name, owner_id=obj.owner_id)
        )

    def return_to_hand(self, obj: GameObject) -> None:
        """Return ``obj`` to its owner's hand (RULE 701.3 "return"), from
        anywhere — the Unsummon/bounce-land shape. Mirrors `exile`'s "move to
        another zone, from wherever it is" shape: fires `LEAVES_BATTLEFIELD`
        when it was in play. A token bounced this way never really "reaches"
        hand — the next SBA pass's RULE 704.5d stranded-token cleanup
        (`_remove_stranded_tokens`) reaps it the instant it's off the
        battlefield.

        RULE 903.9b: unlike graveyard/exile (903.9a, an *SBA* offered after
        the fact), a commander headed to hand (or library) gets a
        *replacement* choice — conceptually offered before the move, so it
        may never touch hand at all. This MVP applies the same
        default-then-fixup shape `enters_tapped`'s shock-land choice already
        uses: ``obj`` lands in hand as normal (the "declined" outcome) and a
        `commander_zone` `pending_choice` opens immediately to redirect it to
        the command zone if the owner chooses to.
        """
        was_on_battlefield = obj in self.state.battlefield
        owner = self.state.player_by_id(obj.owner_id)
        if was_on_battlefield:
            # RULE 603.6a "look back in time" — fire before removal, see
            # `_move_to_graveyard` for the full rationale.
            self.state.fire_event(
                GameEvent(
                    EventType.LEAVES_BATTLEFIELD,
                    object=obj.name,
                    owner_id=obj.owner_id,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
            self.state.remove_from_battlefield(obj)
        else:
            self._remove_from_current_zone(owner, obj)
        obj.tapped = False
        obj.damage_marked = 0
        owner.add_to_zone(obj, Zone.HAND)
        if obj.is_commander:
            self.state.pending_choice = self._commander_zone_choice(obj, Zone.HAND)

    def blink(self, obj: GameObject) -> None:
        """Exile ``obj``, then immediately return it to the battlefield under
        its owner's control (RULE 400.7's "leaves and re-enters" — Ephemerate/
        Momentary Blink-shaped "exile target permanent, then return it").

        Reuses `exile` (a real zone visit, so `LEAVES_BATTLEFIELD`/`EXILE`
        fire like any other exile) then `_put_searched_card`'s battlefield-
        entry handling — the same choke point `return_from_graveyard` uses —
        so the object re-enters as a fresh `ENTERS_BATTLEFIELD` occurrence
        (RULE 400.7: a new object, ETB triggers refire, summoning sickness
        resets) rather than a no-op move. Always under the owner's own
        control — no real blink spell lets the caster keep an opponent's
        creature.
        """
        owner = self.state.player_by_id(obj.owner_id)
        # RULE 400.7: a new object remembers nothing of the old one — unlike
        # `exile` on its own (which leaves counters/attachments alone, e.g.
        # for a card that's merely *staying* in exile), drop everything
        # before re-entry. `exile` doesn't call `_detach_attachments_from`
        # itself (only `_move_to_graveyard` does today), so any Aura/
        # Equipment that was on ``obj`` falls off here.
        self._detach_attachments_from(obj)
        self.exile(obj)
        # `exile()` appended ``obj`` onto `owner.exile`; `_put_searched_card`'s
        # battlefield branch only appends to `state.battlefield` (its usual
        # callers already popped the card off whatever zone held it), so
        # without this it would linger in `owner.exile` too — a phantom
        # duplicate reference (the object's own `.zone` reads BATTLEFIELD
        # correctly either way, but the exile *zone list* itself wouldn't).
        owner.remove_from_zone(obj, Zone.EXILE)
        obj.reset_as_new_object()
        obj.controller_id = owner.id
        self._put_searched_card(owner, obj, "battlefield")

    def return_from_graveyard(
        self,
        obj: GameObject,
        destination: str = "battlefield",
        controller_id: Optional[str] = None,
        transformed: bool = False,
    ) -> None:
        """Return ``obj`` from a graveyard to ``destination`` (RULE 701.3,
        the Regrowth/Reanimate-shaped recursion family).

        Reuses `_put_searched_card`'s battlefield-entry handling (the same
        choke point RULE 701.19's search-to-battlefield destination uses) so
        a reanimated permanent's `ENTERS_BATTLEFIELD` triggers fire exactly
        like a tutored one's, rather than reimplementing that zone-entry
        machinery here.

        ``controller_id``, when given, is the Reanimate/Virtue of
        Persistence "put … onto the battlefield **under your control**"
        shape: ``obj`` enters under that player's control (stamped onto
        ``obj.controller_id`` before the battlefield add, so triggers/layer
        effects see it too) instead of its owner's — real Magic only ever
        pairs this with ``destination="battlefield"``, never "hand" (a card
        can't go to a hand that isn't its owner's).

        ``transformed`` (RULE 400.7 + RULE 712.8, Bruce Banner-shaped "return
        this card to the battlefield transformed") flips ``obj`` onto its
        back face (`transform_permanent`) right after it lands — mirroring
        `exile_return_transformed`'s "new object enters already transformed"
        treatment, just sourced from a graveyard instead of an exile-and-
        blink; only meaningful with a battlefield-shaped ``destination``,
        and a no-op flip for a card with no back face at all
        (`transform_permanent` already handles that gracefully).

        RULE 400.7: leaving the graveyard makes this a new object regardless
        of destination — `GameObject.reset_as_new_object` drops whatever it
        died with (most visibly counters: a creature that died with +1/+1
        counters must not bring them back via Reanimate/Regrowth) before it
        lands anywhere.
        """
        owner = self.state.player_by_id(obj.owner_id)
        self._remove_from_current_zone(owner, obj)
        obj.reset_as_new_object()
        if controller_id is not None and destination in ("battlefield", "battlefield_tapped"):
            obj.controller_id = controller_id
            self._put_searched_card(self.state.player_by_id(controller_id), obj, destination)
        else:
            # RULE 108.4: absent an explicit new controller, a new object
            # defaults to its owner's control — ``obj.controller_id`` could
            # otherwise still read a stale prior controller (e.g. it died
            # while under a "gain control" effect; `_move_to_graveyard`
            # never resets this field, since most graveyard visits aren't
            # followed by a return at all).
            obj.controller_id = owner.id
            self._put_searched_card(owner, obj, destination)
        if transformed and destination in ("battlefield", "battlefield_tapped"):
            self.transform_permanent(obj)

    def return_dies_as_new_permanent(
        self,
        obj: GameObject,
        new_type_line: str,
        new_oracle_text: str,
        attach_to: Optional[GameObject] = None,
    ) -> None:
        """RULE 400.7: "When ~ dies, return it to the battlefield. It's a[n]
        <type> with '<ability>'. ~ loses all other abilities." (Harold and
        Bob, First Numens) — a *different* card entirely, not RULE 712.8's
        ordinary "return transformed" (`return_from_graveyard(transformed=
        True)`/`exile_return_transformed`, both of which need a real
        printed back face): ``obj`` becomes a synthetic `Card` built here
        from ``new_type_line``/``new_oracle_text`` — same name/owner/set,
        everything else is now this new printed text. "Loses all other
        abilities" is made literal by simply never re-attaching the old
        card's catalogue specs (`effect_binder.bind_from_catalogue` is only
        ever called once, when a `GameObject` is first built — this method
        doesn't call it again) — only whatever the new oracle text itself
        implies (a plain mana ability is read live off it,
        `game/mana_abilities.py`; anything needing catalogue/parser
        specs would need an explicit re-bind, not needed by the one real
        card using this shape today.

        ``attach_to``, when given, is stamped directly onto the returned
        object (RULE 303.4a's own "target what it will enchant" — already
        resolved by the calling effect's own target choice before this
        runs, mirroring `AttachEffect`).

        Reuses `return_from_graveyard`'s own `_remove_from_current_zone` +
        `reset_as_new_object` + `_put_searched_card` sequence, just with
        the card swap slotted in between the identity reset and the
        battlefield add, so `ENTERS_BATTLEFIELD`'s own ``object_types``
        payload already reflects the new permanent type.
        """
        owner = self.state.player_by_id(obj.owner_id)
        self._remove_from_current_zone(owner, obj)
        obj.reset_as_new_object()
        obj.controller_id = owner.id
        obj.card = Card(
            id=obj.card.id,
            name=obj.card.name,
            type_line=new_type_line,
            oracle_text=new_oracle_text,
            set_code=obj.card.set_code,
        )
        # "~ loses all other abilities" — unlike an ordinary blink/return-
        # transformed object (`reset_as_new_object`'s own docstring: bound-
        # once abilities are deliberately left alone there, since they'd
        # come back byte-identical from a re-bind), this card's own printed
        # text says the *old* card's abilities are gone for good, not just
        # not-yet-rebound. Clears every bind-on-load field so nothing of
        # the original creature (vigilance/reach, the DIES trigger itself)
        # lingers on the new permanent.
        obj.triggered_abilities = []
        obj.activated_abilities = []
        obj.static_effects = []
        obj.replacement_effects = []
        obj.intrinsic_keywords = set()
        obj.parametric_keywords = {}
        if attach_to is not None:
            obj.attached_to = attach_to.instance_id
        self._put_searched_card(owner, obj, "battlefield")

    def add_mana(self, player: Player, color: str, amount: int = 1) -> None:
        """Add ``amount`` mana of ``color`` straight to ``player``'s pool
        (RULE 106.4) — a spell's own bare "Add {B}." resolve-time body
        (Dark Ritual-shaped), as opposed to a permanent's mana ability
        (`game/mana_abilities.py`, tapped for mana outside the stack
        entirely, never routed through this engine at all).
        """
        player.mana_pool.add(color, amount)

    #: German labels for the interactive "add one mana of any color" choice.
    _ANY_COLOR_LABELS: dict[str, str] = {
        "W": "Weiß", "U": "Blau", "B": "Schwarz", "R": "Rot", "G": "Grün",
    }

    #: Labels for a narrowed mana-*type* offer. RULE 106.1b: colorless isn't
    #: a colour, so a plain "add one mana of any color" never offers {C} —
    #: but "any type that permanent produced" (Kinnan) can, since a Basalt
    #: Monolith produces exactly that.
    _MANA_TYPE_LABELS: dict[str, str] = {**_ANY_COLOR_LABELS, "C": "Farblos"}

    def add_mana_any_color(
        self, player: Player, colors: Optional[list[str]] = None
    ) -> None:
        """Open the interactive colour choice for a resolve-time "add one
        mana of any color" effect (RULE 106.4) — e.g. Deathrite Shaman's
        graveyard-exile ability, which targets and so can never be a
        `mana_abilities.py` mana ability at all (RULE 605.1a excludes any
        ability that requires a target), unlike an ordinary dual land's
        pre-declared tap-for-mana choice.

        ``colors`` narrows the offer to a specific set — Kinnan's "one mana
        of any type **that permanent produced**", where the menu is whatever
        the land or rock actually just made rather than all five colours.
        With a single option there is nothing to decide, so the mana is
        added outright; with none, nothing happens at all.

        Opens an `add_mana_any_color` `pending_choice`;
        `resolve_add_mana_any_color_choice` finishes it by adding one mana
        of the chosen colour to ``player``'s pool.
        """
        offered = list(colors) if colors is not None else list(self._ANY_COLOR_LABELS)
        if not offered:
            return
        if len(offered) == 1:
            self.add_mana(player, offered[0])
            return
        self.state.pending_choice = {
            "kind": "add_mana_any_color",
            "player_id": player.id,
            "prompt": "Farbe für die Manaerzeugung wählen",
            "options": [
                {"id": color, "label": self._MANA_TYPE_LABELS.get(color, color)}
                for color in offered
            ],
        }

    def resolve_add_mana_any_color_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `add_mana_any_color` choice.

        A mandatory choice (RULE 106.4 mana must have a colour) — an
        unrecognized or missing ``answer`` defaults to the first colour
        ("W") rather than adding nothing, the same "defaults instead of
        dropping the effect" treatment `resolve_trigger_mode_choice` gives
        a missing mode answer.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "add_mana_any_color":
            raise ValueError("no pending add-mana-any-color choice to resolve")
        self.state.pending_choice = None
        player = self.state.player_by_id(choice["player_id"])
        offered = [o["id"] for o in choice.get("options") or []]
        color = answer if answer in offered else (offered[0] if offered else "W")
        self.add_mana(player, color)

    def grant_protection_choice(
        self, target: GameObject, player: Player, allow_colorless: bool = False
    ) -> None:
        """Open the interactive "protection from the colour of your choice"
        pick (RULE 702.16, Mother/Giver of Runes) for ``target``.

        Opens a `grant_protection_color` `pending_choice` carrying the target's
        instance id; `resolve_grant_protection_choice` finishes it by adding
        the chosen quality to ``target.temp_protections`` (cleared at cleanup).
        ``allow_colorless`` adds Giver of Runes' extra "colorless" option.
        """
        options = [{"id": color, "label": label} for color, label in self._ANY_COLOR_LABELS.items()]
        if allow_colorless:
            options.append({"id": "colorless", "label": "Farblos"})
        self.state.pending_choice = {
            "kind": "grant_protection_color",
            "player_id": player.id,
            "target_id": target.instance_id,
            "prompt": "Farbe für den Schutz wählen",
            "options": options,
        }

    def resolve_grant_protection_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `grant_protection_color` choice — a mandatory pick
        (an unrecognized/missing answer defaults to the first colour "W",
        the same treatment `resolve_add_mana_any_color_choice` gives)."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "grant_protection_color":
            raise ValueError("no pending grant-protection choice to resolve")
        self.state.pending_choice = None
        target = self.state.find_object(choice["target_id"])
        if target is None:
            return  # RULE 608.2b: target left — the grant simply does nothing
        quality = answer if answer in self._ANY_COLOR_LABELS or answer == "colorless" else "W"
        target.temp_protections.add(quality)

    def random_int(self, n: int) -> int:
        """A uniform random integer in ``[0, n)`` (RULE 706 randomization —
        "choose … at random", coin flips), reproducible from the game state.

        Derives the value from ``(rng_seed, rng_counter)`` and advances the
        counter, so a given seed produces a fixed sequence that survives a
        `GameState.clone()`/undo unchanged (a live `random.Random` on the
        engine wouldn't travel with the cloned state). ``n <= 0`` returns 0.
        """
        import random  # stdlib, function-scoped: only the rare random effect needs it

        if n <= 0:
            return 0
        # Combine seed + counter into a single int seed (a tuple isn't a valid
        # `random.Random` seed) — a large odd multiplier keeps successive
        # counters well-separated in the sequence.
        combined = self.state.rng_seed * 6364136223846793005 + self.state.rng_counter
        value = random.Random(combined).randrange(n)
        self.state.rng_counter += 1
        return value

    def random_choice(self, options: list[Any]) -> Any:
        """One uniformly-random element of ``options`` (RULE 706), reproducibly
        — the list form of `random_int`. Returns ``None`` for an empty list."""
        if not options:
            return None
        return options[self.random_int(len(options))]

    def coin_flip(self) -> bool:
        """A reproducible coin flip (RULE 705) — ``True`` for "heads"."""
        return self.random_int(2) == 0

    def set_tapped(self, obj: GameObject, tapped: bool = True) -> None:
        """Tap or untap a permanent (RULE 701.21 / 701.22) — the choke point
        for a genuine tap/untap transition (attacking, a tap cost, a mana
        ability), so it's also where a "becomes tapped" trigger (RULE 603.2,
        e.g. Dionus, Elvish Archdruid's granted ability) fires from. Not used
        by a permanent entering the battlefield already tapped (RULE 614.1) —
        that never transitions from untapped, so it correctly never fires
        this event either.
        """
        was_tapped = obj.tapped
        obj.tapped = tapped
        if tapped and not was_tapped:
            self.state.fire_event(
                GameEvent(
                    EventType.TAPPED,
                    object=obj.name,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                )
            )

    def add_counters(
        self, obj: GameObject, amount: int, kind: str = "+1/+1", source: Optional[GameObject] = None
    ) -> None:
        """Put ``amount`` counters of ``kind`` on ``obj`` (RULE 122).

        Works on any permanent, not just creatures (RULE 122.1a) — a land can
        enter with +1/+1 counters and use them once it later becomes a creature.
        The layer engine (`continuous.recompute`) reads the net of +1/+1 and
        -1/-1 counters into derived P/T on the next SBA pass, which the caller's
        resolution already triggers; a later SBA also annihilates coexisting
        +1/+1 and -1/-1 counters (RULE 704.5q).

        ``kind`` defaults to +1/+1 (a negative ``amount`` then removes them via
        the net-counter setter, preserving old callers). A ``kind`` of "-1/-1"
        places actual -1/-1 counters, kept as their own type so annihilation
        and "remove a -1/-1 counter" effects stay correct.

        A positive ``amount`` (counters being *placed*, RULE 122.1) is routed
        through `apply_replacements` first, so a "put twice that many
        instead" replacement (RULE 616.1, e.g. Doubling Season) can rewrite
        it — a non-positive ``amount`` (removal, or the +1/-1 annihilation
        SBA's own direct calls) bypasses that entirely, since replacement
        effects only ever apply to counters being added, never removed.

        ``source``, when given, is the permanent/spell/ability *whose effect*
        is putting these counters — carried on the event as
        ``source_controller_id`` (mirroring `deal_damage`'s own
        ``source_controller_id``) so a "if **you** would put counters…"
        replacement (Innkeeper's Talent-shaped, scoped by who's causing the
        placement — a different axis from Doubling Season's "on a permanent
        **you control**", which reads the *target*'s controller instead and
        needs no ``source`` at all) can tell whose effect this is. Omitted by
        most callers, same as `deal_damage`'s optional ``source``.
        """

        def _place(final_amount: int) -> None:
            if kind == "+1/+1":
                obj.plus_one_counters += final_amount
            else:
                obj.add_counters(kind, final_amount)

        if amount <= 0:
            _place(amount)
            return

        event = GameEvent(
            EventType.COUNTER,
            target_id=obj.instance_id,
            kind=kind,
            amount=amount,
            source_controller_id=source.controller_id if source is not None else None,
            # Recipient scoping for a "on a creature/permanent **you control**"
            # replacement (Hardened Scales/Branching Evolution/Kami of
            # Whispered Hopes) — the counters' *recipient*'s controller and
            # whether it's a creature, a different axis from the causer-scoped
            # ``source_controller_id`` above (Innkeeper's Talent).
            recipient_controller_id=obj.controller_id,
            recipient_is_creature=bool(getattr(obj, "is_creature", False)),
        )

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is None:
                return
            _place(resolved.get("amount", amount))

        self.apply_replacements(event, on_resolved=_finish)

    def add_player_counters(
        self, player: Player, amount: int, kind: str = "poison", source: Optional[GameObject] = None
    ) -> None:
        """Put ``amount`` counters of ``kind`` on ``player`` (RULE 122.1) —
        poison/energy/experience/etc., the player-level sibling of
        `add_counters`. ``kind`` defaults to "poison" (`Player.poison`);
        anything else lands in `Player.counters` (`Player.add_counters`).

        Mirrors `add_counters` exactly: a positive ``amount`` is routed
        through `apply_replacements` first (RULE 616.1) via the same
        `EventType.COUNTER` shape, ``is_player=True`` and ``target_id`` the
        player's id (mirroring `deal_damage`'s own player/permanent split) so
        a doubling replacement (Innkeeper's Talent's "…on a permanent or
        player") applies here too, without that replacement needing to know
        or care whether the recipient is an object or a player; a
        non-positive ``amount`` (removal) bypasses replacements entirely,
        same as `add_counters`.
        """

        def _place(final_amount: int) -> None:
            player.add_counters(kind, final_amount)

        if amount <= 0:
            _place(amount)
            return

        event = GameEvent(
            EventType.COUNTER,
            target_id=player.id,
            kind=kind,
            amount=amount,
            is_player=True,
            source_controller_id=source.controller_id if source is not None else None,
            # A player recipient is never a creature; scoped-"you control"
            # counter replacements (Hardened Scales et al.) never apply to a
            # player anyway, but carry the fields for shape-consistency with
            # `add_counters`'s own COUNTER event.
            recipient_controller_id=player.id,
            recipient_is_creature=False,
        )

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is None:
                return
            _place(resolved.get("amount", amount))

        self.apply_replacements(event, on_resolved=_finish)

    # ------------------------------------------------------------------
    # "Remove up to N counters from target permanent/creature" (RULE 122,
    # Glissa Sunslayer/Heartless Act/Render Inert-shaped) — an interactive
    # chosen amount, unlike `RemoveCountersEffect`'s unconditional "all"
    # shape. Two sequential `pending_choice`s: how many (0..max), then —
    # only if 2+ counter kinds are present — which kind, one at a time
    # (mirroring `_search_choice`'s "re-ask for the next" pattern).
    # ------------------------------------------------------------------

    def request_remove_counters_choice(
        self, target: GameObject, max_count: int, chooser: Player
    ) -> None:
        """Open the "how many counters to remove" choice for ``target``.

        A no-op if ``target`` carries no counters at all — nothing to
        choose, same as an empty-eligible `request_search`.
        """
        total = sum(v for v in target.counters.values() if v > 0)
        if total <= 0:
            return
        upper = min(max_count, total)
        self._pending_remove_counters_target = target
        self.state.pending_choice = {
            "kind": "remove_counters_amount",
            "player_id": chooser.id,
            "prompt": f"Wie viele Marker entfernen (bis zu {upper})?",
            "max": upper,
            "options": [{"id": str(n), "label": str(n)} for n in range(upper, -1, -1)],
        }

    def resolve_remove_counters_amount_choice(self, answer: Optional[str]) -> None:
        """Answer the "how many" choice, then either finish (0 chosen, or
        only one counter kind present — no further choice needed) or open
        the "which kind" choice for the first of the chosen counters.

        An unrecognized/missing answer defaults to 0 (remove nothing) —
        unlike a mandatory pick (`resolve_enter_choice`'s default-to-first),
        0 is always itself a legal answer here (RULE 115.1a's "up to N"),
        so the safe default is the no-op rather than a guessed nonzero
        amount.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "remove_counters_amount":
            raise ValueError("no pending remove-counters-amount choice to resolve")
        self.state.pending_choice = None
        target = self._pending_remove_counters_target
        self._pending_remove_counters_target = None

        upper = choice["max"]
        try:
            amount = int(answer) if answer is not None else 0
        except (TypeError, ValueError):
            amount = 0
        amount = max(0, min(amount, upper))
        if amount <= 0 or target is None:
            return
        self._continue_remove_counters(target, amount)

    def _continue_remove_counters(self, target: GameObject, remaining: int) -> None:
        kinds = sorted(k for k, v in target.counters.items() if v > 0)
        if not kinds or remaining <= 0:
            return
        if len(kinds) == 1:
            take = min(remaining, target.counters.get(kinds[0], 0))
            self.add_counters(target, -take, kinds[0])
            return
        self._pending_remove_counters_target = target
        self._pending_remove_counters_remaining = remaining
        self.state.pending_choice = {
            "kind": "remove_counters_kind",
            "player_id": target.controller_id,
            "prompt": f"Von welcher Markerart einen entfernen? (noch {remaining})",
            "options": [{"id": kind, "label": kind} for kind in kinds],
        }

    def resolve_remove_counters_kind_choice(self, answer: Optional[str]) -> None:
        """Answer a pending "which kind" choice: remove one counter of the
        chosen kind, then re-open the choice for the next one if any remain
        (a mandatory pick — an unrecognized/missing answer defaults to the
        first offered kind, same treatment `resolve_enter_choice` gives)."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "remove_counters_kind":
            raise ValueError("no pending remove-counters-kind choice to resolve")
        self.state.pending_choice = None
        target = self._pending_remove_counters_target
        remaining = self._pending_remove_counters_remaining
        self._pending_remove_counters_target = None
        self._pending_remove_counters_remaining = None

        options = choice["options"]
        valid_ids = {str(o["id"]) for o in options}
        kind = str(answer) if answer is not None and str(answer) in valid_ids else (
            str(options[0]["id"]) if options else None
        )
        if target is None or kind is None:
            return
        self.add_counters(target, -1, kind)
        if remaining > 1:
            self._continue_remove_counters(target, remaining - 1)

    def scry(self, player: Player, count: int) -> None:
        """Scry ``count`` (RULE 701.18): look at the top ``count`` cards and
        reorder / bottom them.

        A goldfish/solo session has no interactive chooser, so this performs a
        *legal* scry that keeps every looked-at card on top (always a valid
        outcome — a player may keep any of them on top). It fires `SCRY` so the
        UI and any "when you scry" trigger can observe it.
        """
        looked = min(count, len(player.library))
        self.state.fire_event(
            GameEvent(EventType.SCRY, player_id=player.id, count=looked)
        )

    def surveil(self, player: Player, count: int) -> None:
        """Surveil ``count`` (RULE 701.31): look at the top ``count`` cards,
        put any number into the graveyard, the rest staying on top in any
        order (no bottoming option, unlike `scry`).

        Same non-interactive-session shape as `scry`: a goldfish/solo session
        has no chooser, so this performs the *legal* resolution that puts
        nothing in the graveyard and keeps every looked-at card on top
        (always a valid outcome). Fires `SURVEIL` so the UI and any "when
        you surveil"/"whenever you surveil" trigger can observe it.
        """
        looked = min(count, len(player.library))
        self.state.fire_event(
            GameEvent(EventType.SURVEIL, player_id=player.id, count=looked)
        )

    def create_token(
        self,
        controller_id: str,
        token_card: Card,
        count: int = 1,
        zone: Zone = Zone.BATTLEFIELD,
    ) -> list[GameObject]:
        """Create ``count`` tokens under ``controller_id`` (RULE 111.5).

        Each token is a fresh `GameObject` flagged ``is_token`` (so RULE 704.5d
        removes it once it's stranded outside the battlefield), with its
        abilities bound from the token's own definition — exactly like a real
        permanent. The token's owner *and* controller is the creating player
        (RULE 111.4). Returns the tokens.

        ``zone`` defaults to the battlefield (the common case: entering play
        firing `ENTERS_BATTLEFIELD`, summoning sickness, RULE 614.1
        enters-tapped). Passing e.g. ``Zone.EXILE`` instead (RULE 722.3c's
        prepared copy, `make_prepared`) skips all of that battlefield-entry
        handling and just adds the token straight to the given zone — it
        never "enters the battlefield" at all, and (matching that: it was
        never really "created under a player's control" in the RULE 111.5
        sense either) isn't subject to token-doubling replacements below.

        A battlefield-bound ``count`` is routed through `apply_replacements`
        first, so a "create twice that many instead" replacement (RULE
        616.1, e.g. Doubling Season/Parallel Lives) can rewrite it before any
        token exists. No caller of `create_token`/`copy_permanent` currently
        depends on the *synchronous* return value beyond the common
        zero-ambiguity case (where it still resolves and returns
        immediately, same as before) — if a RULE 616.1 choice opens instead,
        this returns an empty list right away and the actual tokens are
        created later, once `resolve_replacement_order_choice` finishes the
        chain.

        Known scoped gap: unlike `resolve_top_of_stack`'s `_resolve_
        permanent_spell`, a token's own `enter_as_copy_effects` (RULE
        614.1c/614.12 — e.g. a token copy of Clever Impersonator, via
        `copy_permanent`) is bound but never offered here — interactively
        pausing *inside* the ``final_count``-token creation loop is real
        added complexity for a case no card in the pool needs (a copy of a
        copy-effect creature). Revisit if one ever does. Same gap, same
        reasoning, for `enter_choice_effects` (RULE 601.2b "as ~ enters,
        choose a creature type/color") — every real card with that ability
        in the pool is a cast permanent, never a token.
        """
        from .effect_binder import bind_from_catalogue  # function-scoped: avoid cycle

        def _build(final_count: int) -> list[GameObject]:
            created: list[GameObject] = []
            for _ in range(max(0, final_count)):
                token = GameObject(
                    token_card,
                    owner_id=controller_id,
                    zone=zone,
                    is_token=True,
                )
                bind_from_catalogue(token)  # token abilities are live like any card's
                if zone == Zone.BATTLEFIELD:
                    token.summoning_sick = True  # RULE 302.6 applies to tokens too
                    # RULE 614.1 — see the matching comment in
                    # `_resolve_permanent_spell` above.
                    token.tapped = ability_catalogue.enters_tapped(
                        token_card
                    ) or continuous.enters_tapped_from_static(self.state, token)
                    self._apply_entry_counters(token)  # a token was never cast, so X is 0
                    self.state.add_to_battlefield(token)
                    self.state.fire_event(
                        GameEvent(
                            EventType.ENTERS_BATTLEFIELD,
                            controller_id=controller_id,
                            card_id=token_card.id,
                            object=token.name,
                            is_token=True,
                            instance_id=token.instance_id,
                            object_types=sorted(token.type_words),
                        )
                    )
                else:
                    self.state.player_by_id(controller_id).add_to_zone(token, zone)
                created.append(token)
            return created

        if zone != Zone.BATTLEFIELD or count <= 0:
            return _build(count)

        event = GameEvent(EventType.CREATE_TOKENS, controller_id=controller_id, amount=count)
        result: list[GameObject] = []

        def _finish(resolved: Optional[GameEvent]) -> None:
            nonlocal result
            if resolved is None:
                return
            result = _build(resolved.get("amount", count))

        self.apply_replacements(event, on_resolved=_finish)
        return result

    def advance_sagas(self, player: Player) -> None:
        """Add a lore counter to each Saga ``player`` controls (RULE 714.3c).

        A turn-based action as the controller's precombat main phase begins
        (`GameEngine._step_main1`) — not off the draw step, despite this
        living there before it was fixed to match the CR. Fires
        `SAGA_CHAPTER` so a chapter ability whose number the new count
        reaches goes on the stack through the normal triggered-ability
        pipeline (RULE 714.2d). The 0-chapter-remaining Saga is sacrificed by
        a state-based action (`check_state_based_actions`), so this only
        advances the chapter here."""
        for obj in self.state.permanents_controlled_by(player.id):
            if obj.card.is_saga:
                obj.add_counters("lore", 1)
                self.state.fire_event(
                    GameEvent(
                        EventType.SAGA_CHAPTER,
                        object=obj.name,
                        instance_id=obj.instance_id,
                        controller_id=player.id,
                        chapter=obj.lore,
                    )
                )

    def _track_spell_cast(self, event: GameEvent) -> None:
        """Tally `SPELL_CAST` toward RULE 731.2's "spells cast this turn"
        count — both a paid `cast_spell` and a free `cast_without_paying`
        fire that event, so subscribing here (rather than incrementing at
        each call site) covers every cast path from one place."""
        if event.type != EventType.SPELL_CAST:
            return
        player_id = event.get("player_id")
        if player_id is None:
            return
        counts = self.state.spells_cast_this_turn
        counts[player_id] = counts.get(player_id, 0) + 1

    def _track_creature_death(self, event: GameEvent) -> None:
        """Tally `DIES` toward `GameState.creatures_died_this_turn` (RULE
        700.4). Subscribed rather than incremented at `_move_to_graveyard`,
        so every path a creature can die by is covered from one place — the
        same reason `_track_spell_cast` above listens for `SPELL_CAST`.

        `DIES` fires for *every* permanent type (an Aura/land dying is a real
        dies-trigger too), so this narrows to creatures off the event's own
        snapshotted ``object_types`` — the object is already out of the
        battlefield by the time a subscriber runs (RULE 400.7), so its types
        can't be re-read live. ``controller_id`` is what "died **under your
        control**" asks about, not the owner."""
        if event.type != EventType.DIES:
            return
        if "creature" not in (event.get("object_types") or []):
            return
        player_id = event.get("controller_id")
        if player_id is None:
            return
        counts = self.state.creatures_died_this_turn
        counts[player_id] = counts.get(player_id, 0) + 1

    def apply_day_night_turn_check(self) -> None:
        """RULE 731.2: as the second part of the untap step, maybe flip
        day/night based on how many spells the *previous* turn's active
        player cast during that turn.

        A no-op on turn 1 (no previous turn) or once a designation is set
        but the check doesn't apply (RULE 731.2c — neither day nor night:
        the check simply doesn't run at all). Any flip is applied
        immediately, including transforming now-mismatched daybound/
        nightbound permanents (RULE 702.145c/f aren't state-based actions)."""
        if self.state._last_turn_player_id is None:
            return
        count = self.state._last_turn_spell_count
        if self.state.day_night == "day" and count == 0:
            self.state.day_night = "night"
        elif self.state.day_night == "night" and count >= 2:
            self.state.day_night = "day"
        else:
            return
        self._transform_mismatched_daynight_permanents()

    def _transform_mismatched_daynight_permanents(self) -> bool:
        """Flip any permanent whose daybound/nightbound keyword (RULE
        702.145b/e) no longer matches the current day/night designation.
        Returns whether anything changed."""
        if self.state.day_night == "night":
            for obj in self.state.permanents():
                if combat.has(obj, "daybound"):
                    self.transform_permanent(obj)
                    return True
        elif self.state.day_night == "day":
            for obj in self.state.permanents():
                if combat.has(obj, "nightbound"):
                    self.transform_permanent(obj)
                    return True
        return False

    def _check_day_night(self) -> bool:
        """RULE 702.145c/d/f/g: establish/maintain the day/night designation
        "any time" a player controls a (mis)matched daybound/nightbound
        permanent. Not itself a state-based action, but checked at the
        `_sba_pass` cadence — the same "any time" simplification already used
        for the Saga-sacrifice check. Returns whether anything changed, so
        `_sba_pass`'s fixpoint loop re-runs."""
        if self.state.day_night is None:
            battlefield = self.state.permanents()
            if any(combat.has(o, "daybound") for o in battlefield):
                self.state.day_night = "day"
                return True
            if any(combat.has(o, "nightbound") for o in battlefield):
                self.state.day_night = "night"
                return True
            return False
        return self._transform_mismatched_daynight_permanents()

    def copy_permanent(
        self, controller_id: str, source: GameObject, count: int = 1
    ) -> list[GameObject]:
        """Create ``count`` token copies of ``source`` (RULE 707.2 / 111.5).

        A token copy takes ``source``'s *copiable* characteristics — for this
        basic version, its printed `Card` (the front face if it's transformed,
        RULE 712.4a) — and enters as a token under ``controller_id``. Reuses
        `create_token`, so the copy's own abilities bind and it follows the
        token cease-to-exist lifecycle (RULE 704.5d)."""
        copiable = getattr(source, "_front_card", source.card)
        return self.create_token(controller_id, copiable, count)

    def copy_spell(
        self,
        target: Any,
        controller_id: str,
        count: int = 1,
        new_targets: Optional[list[Any]] = None,
    ) -> list[StackItem]:
        """Put ``count`` copies of the spell ``target`` onto the stack (RULE
        707.10 — Dualcaster Mage/Reiterate/Flare of Duplication "copy target
        instant or sorcery spell").

        ``target`` is the spell's `StackItem` or its underlying `GameObject`
        (whatever `CopySpellEffect` was handed). A copy is a brand-new
        `StackItem` controlled by ``controller_id`` (RULE 707.10c — the
        copier, who may differ from the original's controller), carrying a
        fresh token `GameObject` of the spell's copiable card so its own
        resolve-time effects rebind cleanly (`_effects_for_spell`) rather
        than sharing the original's effect instances. The copy keeps the
        original's targets by default (RULE 707.10c "the copy has the same
        targets") and its announced {X} (RULE 707.10e) — ``new_targets``
        overrides the former for the "you may choose new targets" clause.
        Copies are pushed **above** the original so they resolve first
        (RULE 608.2 — LIFO). A copy of a permanent spell resolves into a
        token permanent; a copy of an instant/sorcery applies its effects
        then ceases to exist (its token `GameObject` is reaped by the RULE
        704.5d stranded-token SBA the moment the resolve path routes it off
        the stack).
        """
        from .effect_binder import bind_from_catalogue  # function-scoped: avoid cycle

        item = self._stack_item_for(target)
        if item is None or item.obj is None:
            return []
        copiable = getattr(item.obj, "_front_card", item.obj.card)
        copies: list[StackItem] = []
        for _ in range(count):
            copy_obj = GameObject(
                copiable.as_copy(), owner_id=controller_id, zone=Zone.STACK
            )
            copy_obj.is_token = True
            copy_obj.is_copy = True
            copy_obj.x_paid = item.x
            bind_from_catalogue(copy_obj)
            copy_item = StackItem(
                kind="spell",
                controller_id=controller_id,
                effects=self._effects_for_spell(copy_obj),
                obj=copy_obj,
                description=f"{item.obj.name} (Kopie)",
                targets=list(item.targets) if new_targets is None else list(new_targets),
                x=item.x,
                target_groups=item.target_groups if new_targets is None else None,
            )
            self.state.stack.append(copy_item)
            copies.append(copy_item)
        return copies

    def make_prepared(self, obj: GameObject) -> None:
        """``obj`` becomes prepared (RULE 722.3a — a preparation card's
        "~ becomes prepared" effect).

        A no-op if ``obj`` is already prepared (RULE 722.3a: "can't gain
        this designation if the permanent already has it") or has no
        prepare spell at all (``back_face()`` is ``None``). Otherwise sets
        the `prepared` designation and creates one token copy of the
        prepare spell's characteristics directly into ``obj``'s
        controller's exile (RULE 722.3c) — not the battlefield, so
        `create_token`'s battlefield-entry handling (summoning sickness,
        `ENTERS_BATTLEFIELD`) correctly never runs for it. The copy is
        linked back via `prepared_source_id`; `_remove_stranded_tokens`
        keeps it alive only for as long as ``obj`` stays on the battlefield
        with `prepared` still set — no separate cleanup/expiry needed here.
        """
        if obj.prepared:
            return
        prepare_spell = obj.card.back_face()
        if prepare_spell is None:
            return
        obj.prepared = True
        copies = self.create_token(obj.controller_id, prepare_spell, zone=Zone.EXILE)
        copies[0].prepared_source_id = obj.instance_id

    def become_copy(
        self,
        obj: GameObject,
        target: GameObject,
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
    ) -> None:
        """``obj`` itself becomes a copy of ``target`` (RULE 706/707.2).

        Delegates to `copy_mechanics.become_copy` — moved there so
        `game/continuous.py`'s layer-1 conditional-copy pass can call the
        same mutate/rebind logic without importing this module (which would
        be circular)."""
        copy_mechanics.become_copy(obj, target, add_types, add_subtypes)

    def become_copy_until_end_of_turn(
        self,
        obj: GameObject,
        target: GameObject,
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
    ) -> None:
        """``obj`` becomes a copy of ``target`` until end of turn (Cursed
        Mirror-style: "{T}: ~ becomes a copy of target creature until end of
        turn."). Unlike `become_copy`'s permanent mutation, `GameEngine.
        _step_cleanup` (RULE 514.2, the same step that ends pump/keyword
        "until end of turn" effects) reverts this via the snapshot stashed
        here — taken only the *first* time this turn, so a second activation
        before cleanup doesn't overwrite the true original with an
        already-copied state."""
        if obj._copy_until_eot_base is None:
            obj._copy_until_eot_base = copy_mechanics.snapshot_face(obj)
        copy_mechanics.become_copy(obj, target, add_types, add_subtypes)

    def set_copy_target(self, obj: GameObject, target: GameObject) -> None:
        """Choose/change the target a layer-1 conditional-copy static ability
        copies (Vesuvan Shapeshifter's "you may have it be a copy of another
        target creature") — `continuous.recompute`'s layer-1 pass reads
        `obj.copy_target_id` fresh every recompute, the same idiom
        `attached_to` uses."""
        if target is not None and target is not obj:
            obj.copy_target_id = target.instance_id

    def snapshot_face(self, obj: GameObject) -> dict[str, Any]:
        """Capture ``obj``'s current `Card` + catalogue-derived bindings.

        Pairs with `restore_face` to undo a `switch_to_face` — used when
        previewing or attempting a modal DFC's un-chosen face (RULE 712.10)
        so a rejected cast never leaves the object silently switched.
        Delegates to `copy_mechanics.snapshot_face`."""
        return copy_mechanics.snapshot_face(obj)

    def restore_face(self, obj: GameObject, snapshot: dict[str, Any]) -> None:
        """Undo a `switch_to_face`, restoring exactly what `snapshot_face`
        saved. Delegates to `copy_mechanics.restore_face`."""
        copy_mechanics.restore_face(obj, snapshot)

    def switch_to_face(self, obj: GameObject, card: Card) -> None:
        """Rebind ``obj`` onto ``card`` — another face of the same physical
        object (RULE 712.10, choosing a modal DFC's face to cast/play).

        Mirrors `become_copy`'s "clear + rebind catalogue-derived abilities"
        treatment: a face's activated/triggered/static/spell effects and
        keywords are its own, not shared with the other face, so they must be
        rebound from ``card`` rather than left pointing at the old face's.
        Unlike `become_copy` this doesn't touch counters/zone/control — it's
        a face choice, not a copy effect."""
        from .effect_binder import bind_from_catalogue  # function-scoped: avoid a cycle

        obj.card = card
        obj.spell_effects = []
        obj.triggered_abilities = []
        obj.activated_abilities = []
        obj.static_effects = []
        obj.replacement_effects = []
        obj.enter_as_copy_effects = []
        obj.intrinsic_keywords = set()
        obj.parametric_keywords = {}
        bind_from_catalogue(obj)

    def transform_permanent(self, obj: GameObject) -> bool:
        """Flip a double-faced permanent to its other face (RULE 712.8).

        Mirrors `switch_to_face`'s "clear + rebind catalogue-derived
        abilities" treatment: `GameObject.transform` only swaps ``card``, so
        without this a transformed permanent would keep its *other* face's
        keywords/triggered/activated/static abilities forever (e.g. a
        daybound/nightbound permanent's own daybound/nightbound keyword,
        RULE 702.145, would never update). Returns whether it flipped — a
        no-op (``False``) for a card with no back face, same as
        `GameObject.transform`."""
        from .effect_binder import bind_from_catalogue  # function-scoped: avoid a cycle

        if not obj.transform():
            return False
        obj.spell_effects = []
        obj.triggered_abilities = []
        obj.activated_abilities = []
        obj.static_effects = []
        obj.replacement_effects = []
        obj.enter_as_copy_effects = []
        obj.intrinsic_keywords = set()
        obj.parametric_keywords = {}
        bind_from_catalogue(obj)
        return True

    def exile_return_transformed(self, obj: GameObject) -> bool:
        """"Exile ~, then return it to the battlefield transformed under its
        owner's control" (RULE 400.7 + RULE 712.8 combined — a transforming
        Saga's own final chapter, Fable of the Mirror-Breaker-shaped, or a
        transform-flip permanent's activated ability that phrases its flip
        this way instead of a plain in-place `transform_permanent`,
        Ayara/Clive/Jin-Gitaxias-shaped).

        Unlike `transform_permanent` (an in-place face swap on the same
        object), this is a genuine RULE 400.7 zone change — `blink` plus a
        forced flip onto the back face: a brand-new object enters directly
        already transformed, so leaves/enters-the-battlefield triggers
        refire, counters/attachments/"until end of turn" effects fall off,
        and it re-enters with summoning sickness. Always ends up on the back
        face regardless of which face ``obj`` started on
        (`reset_as_new_object` always presents the front face first, RULE
        711.8, then `transform_permanent` flips it exactly once). Returns
        whether it flipped — ``False`` (a no-op, nothing exiled) for a card
        with no back face at all — checked against ``_front_card`` rather
        than ``obj.card`` so it's correct even if ``obj`` happened to
        already be on its back face when this resolves.
        """
        if obj._front_card.back_face() is None:
            return False
        owner = self.state.player_by_id(obj.owner_id)
        self._detach_attachments_from(obj)
        self.exile(obj)
        obj.reset_as_new_object()
        obj.controller_id = owner.id
        self.transform_permanent(obj)
        self._put_searched_card(owner, obj, "battlefield")
        return True

    @staticmethod
    def _life_locked(player: Player) -> bool:
        """RULE 119.6: "your life total can't change" (Teferi's Protection),
        a marker on `Player.player_effects` — see `PlayerShieldEffect`."""
        return any(getattr(e, "player_life_locked", False) for e in player.player_effects)

    @staticmethod
    def _player_protected_from_everything(player: Player) -> bool:
        """RULE 702.16e: "you gain protection from everything" (Teferi's
        Protection) — for a *player* this reduces to "can't be dealt
        damage", the only half a player can actually be subject to here."""
        return any(
            getattr(e, "player_protected_from_everything", False)
            for e in player.player_effects
        )

    def gain_life(self, player: Player, amount: int) -> None:
        if amount <= 0:
            return
        if self._life_locked(player):
            return  # RULE 119.6 — see `lose_life`
        # RULE 119.3/616.1: a life gain is routed through `apply_replacements`
        # first, so a "you gain that much life plus N / twice that much
        # instead" replacement (Angel of Vitality/Boon Reflection) can
        # rewrite the amount before any life lands — mirroring `deal_damage`/
        # `add_counters`'s own pre-event replacement hook. With no such
        # replacement active (the overwhelmingly common case) `_finish` runs
        # synchronously with the unchanged amount, exactly as before.
        event = GameEvent(EventType.LIFE_GAIN, player_id=player.id, amount=amount)

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is None:
                return
            final = int(resolved.get("amount", amount) or 0)
            if final <= 0:
                return
            player.gain_life(final)
            self.state.fire_event(
                GameEvent(EventType.LIFE_GAINED, player_id=player.id, amount=final)
            )

        self.apply_replacements(event, on_resolved=_finish)

    def prevent_damage_to_player(self, player: Player, amount: Union[int, str] = "all") -> None:
        """RULE 615: grant ``player`` a turn-scoped damage-prevention shield
        (Riot Control's "all", Thought Lash's repeatable "the next 1") —
        Regenerate-shaped (a `ReplacementEffect` built and attached at
        resolve time, not bind time), but player- rather than object-scoped:
        it lives on `Player.player_effects` (already `_all_replacement_
        effects`'s second collection source, see `regenerate` for the
        permanent-scoped sibling) since nothing is being regenerated here.

        ``amount="all"`` prevents every point of damage dealt to ``player``
        for the rest of the turn and never self-removes (an "all" shield
        has no bank to exhaust). An int opens a cumulative bank of that
        many points, spent (possibly across several `EventType.DAMAGE`
        events) until exhausted, then self-removes — Thought Lash's own
        activated ability can be paid more than once a turn, each call
        opening an *independent* shield exactly like `regenerate`'s own
        multiple-activations-stack behaviour. Either shape is swept at
        cleanup regardless of remaining balance (RULE 514.2 "this turn"
        expiry) by `GameEngine._step_cleanup`'s `damage_prevention_shield`
        marker check, mirroring the existing unused-regeneration-shield
        sweep.
        """
        remaining = None if amount == "all" else int(amount)
        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
            condition=lambda e, c: bool(e.get("is_player")) and e.get("target_id") == player.id,
            description=f"{player.name}: Schadensverhinderung",
        )
        effect.damage_prevention_shield = True

        def _replace(event: GameEvent, _context: Any) -> Optional[GameEvent]:
            nonlocal remaining
            dealt = int(event.get("amount", 0) or 0)
            if remaining is None:
                return None  # "all" — every point prevented, shield persists
            prevented = min(remaining, dealt)
            remaining -= prevented
            if remaining <= 0 and effect in player.player_effects:
                player.player_effects.remove(effect)
            new_amount = dealt - prevented
            return event.copy_with(amount=new_amount) if new_amount > 0 else None

        effect.replacement_fn = _replace
        player.player_effects.append(effect)

    def become_monarch(self, player: Player) -> None:
        """RULE 725.3: ``player`` becomes the monarch; whoever held it
        (possibly ``player`` themself) ceases to."""
        self.state.monarch_id = player.id

    def take_initiative(self, player: Player) -> None:
        """RULE 726.3: ``player`` takes the initiative; whoever held it
        (possibly ``player`` themself) ceases to. RULE 726.5's "venture into
        the dungeon" companion trigger isn't fired — see
        `TakeInitiativeEffect`'s docstring."""
        self.state.initiative_id = player.id

    #: The closed vocabulary `request_choose_objects` accepts, mapping each
    #: action name to what it does to a chosen object. Deliberately small
    #: and data-only: the whole choice (candidates, action, how many are
    #: left) lives in `GameState.pending_choice`, so it survives the
    #: `clone()` undo snapshots takes — unlike a callback, which is why
    #: this replaced the "auto-pick the first candidate" convention rather
    #: than passing a continuation closure around.
    CHOOSE_OBJECT_ACTIONS = frozenset(
        {"tap", "sacrifice", "return_to_hand", "soulbond_pair", "library_top", "discard"}
    )

    def request_choose_objects(
        self,
        player: Player,
        candidates: list[GameObject],
        action: str,
        count: int = 1,
        optional: bool = False,
        prompt: str = "",
        source: Optional[GameObject] = None,
        then_specs: Optional[list[dict]] = None,
        then_specs_if_commander: Optional[list[dict]] = None,
    ) -> None:
        """Open a "choose N of these objects" decision (RULE 601.2c-style).

        The general chooser for every effect that names *what kind* of
        object to act on but leaves *which one* to the player: Cloudstone
        Curio's bounce, Tangle Wire's tap, Tevesh Szat's and Professor
        Onyx's sacrifices, Deadeye Navigator's Soulbond partner, Lim-Dûl's
        Vault's and Thassa's Oracle's library reordering. Each of those used
        to auto-pick the first legal candidate.

        Offered one object at a time (`resolve_choose_objects_choice`
        re-opens until ``count`` are picked or the pool runs dry), exactly
        like a library search — same UI shape, same undo granularity.
        ``optional`` adds a decline option ("you **may** return…"); a
        mandatory choice with nothing to choose between still resolves
        without a prompt, since there's no decision to make.

        ``action`` names what happens to each pick, from
        `CHOOSE_OBJECT_ACTIONS`. ``source`` is only needed by
        ``soulbond_pair``, which pairs each pick *with* it (RULE 702.94a).

        ``then_specs`` are serialized `EffectSpec` dicts to apply once at
        least one pick was made — the "**If you do**, draw two cards" half
        of an optional sacrifice (Tevesh Szat), which can only be decided
        after the choice rather than before it.
        ``then_specs_if_commander`` adds RULE 903's "if a commander was
        sacrificed this way" tail on top; both are carried as data on the
        choice, so they survive the state `clone()` undo takes.
        """
        if action not in self.CHOOSE_OBJECT_ACTIONS:
            raise ValueError(f"unknown choose-objects action {action!r}")
        pool = [obj for obj in candidates if obj is not None]
        if not pool or count <= 0:
            return
        if len(pool) <= count and not optional:
            # Forced: every candidate is taken anyway, so asking would be
            # theatre. (An *optional* one still asks — declining matters.)
            commander_taken = False
            for obj in pool:
                commander_taken = commander_taken or obj.is_commander
                self._apply_chosen_object(player, obj, action, source)
            self._apply_choose_objects_tail(
                source, then_specs, then_specs_if_commander, commander_taken
            )
            return
        self.state.pending_choice = self._choose_objects_choice(
            player, pool, action, count, optional, prompt,
            source_id=source.instance_id if source is not None else None,
            picked=[], then_specs=then_specs,
            then_specs_if_commander=then_specs_if_commander,
        )

    def _apply_choose_objects_tail(
        self,
        source: Optional[GameObject],
        then_specs: Optional[list[dict]],
        then_specs_if_commander: Optional[list[dict]],
        commander_taken: bool,
    ) -> None:
        """Apply a `choose_objects` decision's "if you do" follow-up."""
        self._apply_effect_specs(list(then_specs or []), source)
        if commander_taken:
            self._apply_effect_specs(list(then_specs_if_commander or []), source)

    def _choose_objects_choice(
        self,
        player: Player,
        pool: list[GameObject],
        action: str,
        count: int,
        optional: bool,
        prompt: str,
        source_id: Optional[int],
        picked: list[int],
        then_specs: Optional[list[dict]] = None,
        then_specs_if_commander: Optional[list[dict]] = None,
    ) -> dict[str, Any]:
        """Build the serializable `choose_objects` `pending_choice`."""
        options = [
            {"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id}
            for obj in pool
            if obj.instance_id not in picked
        ]
        if optional:
            options.append({"id": "decline", "label": "Nichts wählen"})
        remaining = count - len(picked)
        label = prompt or "Wähle ein Objekt"
        return {
            "kind": "choose_objects",
            "player_id": player.id,
            "action": action,
            "source_id": source_id,
            "count": count,
            "optional": optional,
            "picked": list(picked),
            "remaining": remaining,
            "prompt": f"{label} (noch {remaining})" if count > 1 else label,
            "prompt_base": label,
            "options": options,
            "then_specs": [dict(spec) for spec in (then_specs or [])],
            "then_specs_if_commander": [
                dict(spec) for spec in (then_specs_if_commander or [])
            ],
            # RULE 903: whether any pick so far was a commander, which the
            # "if a commander was sacrificed this way" tail reads.
            "commander_taken": False,
        }

    def resolve_choose_objects_choice(self, instance_id: Optional[int]) -> None:
        """Answer a pending `choose_objects` decision: apply the action to
        the chosen object, then re-ask while picks remain (or stop on a
        decline — RULE 601.2c's "up to"/"may" shape)."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "choose_objects":
            raise ValueError("no pending object choice to resolve")
        player = self.state.player_by_id(choice["player_id"])
        picked: list[int] = list(choice["picked"])
        offered = {o["instance_id"] for o in choice["options"] if "instance_id" in o}
        if instance_id is not None:
            if instance_id not in offered:
                raise ValueError(f"{instance_id} is not a legal choice")
            picked.append(instance_id)
        source = self._object_by_instance_id(choice.get("source_id"))
        declined = instance_id is None
        chosen = self._object_by_instance_id(instance_id) if instance_id is not None else None
        # Applied as each pick is made rather than all at the end: tapping
        # or sacrificing one permanent can change what the remaining
        # candidates even are (RULE 608.2's "as the effect resolves").
        commander_taken = bool(choice.get("commander_taken"))
        if chosen is not None and player is not None:
            commander_taken = commander_taken or chosen.is_commander
            self._apply_chosen_object(player, chosen, choice["action"], source)
        remaining_pool = [
            obj
            for obj in self._choose_objects_pool(choice, picked)
            if obj is not None
        ]
        if declined or len(picked) >= choice["count"] or not remaining_pool:
            self.state.pending_choice = None
            if picked:
                # RULE 601.2c: "if you do, …" only fires when something was
                # actually chosen — a declined optional choice does nothing.
                self._apply_choose_objects_tail(
                    source, choice.get("then_specs"),
                    choice.get("then_specs_if_commander"), commander_taken,
                )
            return
        next_choice = self._choose_objects_choice(
            player, remaining_pool, choice["action"], choice["count"],
            choice["optional"], choice.get("prompt_base", ""),
            source_id=choice.get("source_id"), picked=picked,
            then_specs=choice.get("then_specs"),
            then_specs_if_commander=choice.get("then_specs_if_commander"),
        )
        next_choice["commander_taken"] = commander_taken
        self.state.pending_choice = next_choice

    def _choose_objects_pool(
        self, choice: dict[str, Any], picked: list[int]
    ) -> list[GameObject]:
        """The still-offerable objects from a `choose_objects` choice."""
        return [
            self._object_by_instance_id(o["instance_id"])
            for o in choice["options"]
            if "instance_id" in o and o["instance_id"] not in picked
        ]

    def _object_by_instance_id(self, instance_id: Optional[int]) -> Optional[GameObject]:
        """Any `GameObject` anywhere in the game, by id — the reverse lookup
        a serialized `pending_choice` needs to get back to real objects."""
        if instance_id is None:
            return None
        for obj in self.state.battlefield:
            if obj.instance_id == instance_id:
                return obj
        for player in self.state.players:
            for cards in player.zones.values():
                for obj in cards:
                    if obj.instance_id == instance_id:
                        return obj
        return None

    def _apply_chosen_object(
        self,
        player: Player,
        obj: GameObject,
        action: str,
        source: Optional[GameObject],
    ) -> None:
        """Do the one thing a `choose_objects` action names to one pick."""
        if action == "tap":
            self.set_tapped(obj, True)
        elif action == "sacrifice":
            # RULE 701.17a: non-destructive, so no regeneration shield saves it.
            self.put_into_graveyard(obj)
        elif action == "return_to_hand":
            self.return_to_hand(obj)
        elif action == "discard":
            self.discard_specific(obj)
        elif action == "soulbond_pair" and source is not None:
            # RULE 702.94a: the pairing is recorded on both creatures.
            source.paired_with = obj.instance_id
            obj.paired_with = source.instance_id
        elif action == "library_top":
            owner = self.state.player_by_id(obj.owner_id) or player
            self._remove_from_current_zone(owner, obj)
            owner.add_to_zone(obj, Zone.LIBRARY)

    def the_ring_tempts_you(self, player: Player) -> None:
        """RULE 701.51a: the Ring tempts ``player``.

        Two things happen, in this order. First the Ring emblem gains its
        next ability (`Player.ring_level`, capped at 4 — RULE 701.51b: a
        fifth temptation adds nothing, it still just re-chooses the bearer).
        The level *is* the emblem: unlike a RULE 114 emblem there's no
        quoted card text to parse, the four abilities are fixed by the rules
        and all read live state, so nothing is created in the command zone.

        Then RULE 701.52a's Ring-bearer choice: "you choose a creature you
        control as your Ring-bearer". Mandatory when the player controls a
        creature (the previous bearer may be re-chosen, and with exactly one
        candidate the choice is forced, so it's made outright); with 2+
        candidates it's a genuine `ring_bearer` `pending_choice`. Controlling
        no creature means no bearer at all — the emblem's abilities simply
        have nothing to apply to until the next temptation picks one.
        """
        player.ring_level = min(4, int(getattr(player, "ring_level", 0) or 0) + 1)
        candidates = [
            obj for obj in self.state.permanents_controlled_by(player.id) if obj.is_creature
        ]
        if not candidates:
            player.ring_bearer_id = None
            return
        if len(candidates) == 1:
            player.ring_bearer_id = candidates[0].instance_id
            return
        self.state.pending_choice = {
            "kind": "ring_bearer",
            "player_id": player.id,
            "prompt": "Wähle eine Kreatur als deinen Ringträger (RULE 701.52a).",
            "options": [
                {
                    "id": str(obj.instance_id),
                    "label": obj.name,
                    "instance_id": obj.instance_id,
                }
                for obj in candidates
            ],
        }

    def resolve_ring_bearer_choice(self, instance_id: int) -> None:
        """Answer a pending `ring_bearer` choice (RULE 701.52a).

        Not optional — the choice only ever opens when the player controls
        2+ creatures, and RULE 701.52a makes choosing mandatory then.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "ring_bearer":
            raise ValueError("no pending Ring-bearer choice to resolve")
        allowed = {o["instance_id"] for o in choice["options"]}
        if instance_id not in allowed:
            raise ValueError(f"{instance_id} is not a legal Ring-bearer")
        player = self.state.player_by_id(choice["player_id"])
        self.state.pending_choice = None
        if player is not None:
            player.ring_bearer_id = instance_id

    def _sweep_ring_bearer(self) -> None:
        """RULE 701.52d: a Ring-bearer that stops being a creature its
        designator controls stops being the Ring-bearer. Run as part of the
        SBA pass, next to the Soulbond sweep, since both are "the state that
        made this designation true is gone" cleanups rather than anything a
        player did."""
        for player in self.state.players:
            if player.ring_bearer_id is None:
                continue
            if continuous.ring_bearer_of(self.state, player) is None:
                player.ring_bearer_id = None

    def create_emblem(self, player: Player, ability: dict) -> None:
        """RULE 114.2/114.4: bind the emblem's one already-parsed quoted
        ability into a live `TriggeredAbility`/`StaticAbility` and file it in
        ``player``'s command zone.

        Binding happens here — once, at resolve time — rather than at
        bind-on-load like every other ability, because an emblem has no
        permanent to bind *onto*: `effect_binder.bind_ability` is imported
        lazily (it imports `game/effects.py`, which this module also feeds
        into, so a module-level import would cycle) and given a synthetic
        `Emblem` as its ``source`` instead of a `GameObject` (`models/
        emblem.py` — carries just enough, ``controller_id``/``timestamp``,
        for the existing "you control"/layer-ordering machinery to work
        unchanged).
        """
        from ..parser.oracle.spec import AbilitySpec
        from .effect_binder import bind_ability

        self.state._timestamp_counter = getattr(self.state, "_timestamp_counter", 0) + 1
        emblem = Emblem(controller_id=player.id, timestamp=self.state._timestamp_counter)
        spec = AbilitySpec.from_dict(ability)
        emblem.description = spec.raw_text
        bound = bind_ability(spec, source=emblem)
        if isinstance(bound, TriggeredAbility):
            emblem.triggered_abilities.append(bound)
        elif isinstance(bound, list):
            for effect in bound:
                if isinstance(effect, StaticAbility):
                    emblem.static_effects.append(effect)
        player.emblems.append(emblem)

    def _stack_item_for(self, target: Any) -> Optional[StackItem]:
        """The `StackItem` a counter effect's ``target`` names, or ``None``.

        ``target`` is either a `StackItem` itself or its underlying
        `GameObject` — `CounterSpellEffect` (and the search/choice machinery
        upstream) pass whichever it was handed.
        """
        for candidate in self.state.stack:
            if candidate is target or candidate.obj is target:
                return candidate
        return None

    def mutate_onto(
        self, mutating: GameObject, host: GameObject, under: bool = False
    ) -> None:
        """RULE 702.140b-d: merge ``mutating`` onto ``host``.

        The **host** stays the surviving `GameObject` — RULE 702.140c is
        explicit that the merged permanent is the *same* permanent, not a
        new one, which is exactly why mutate keeps counters, damage marked,
        attachments and summoning-sickness state, and why it fires no
        enters-the-battlefield trigger. So this rewrites the host's card
        rather than creating anything.

        "The creature on top plus all abilities from under it": the host
        takes on ``mutating``'s printed characteristics (name, P/T, types)
        while its own previous oracle text is banked on
        `GameObject.merged_oracle_text` and folded back in when abilities are
        re-derived — so the pile keeps accumulating abilities as further
        creatures mutate onto it, which is the mechanic's whole point.

        ``under=True`` is the other half of RULE 702.140b's "over **or
        under**": the pile keeps the *host's* characteristics and gains the
        mutating card's abilities instead. Same merge, opposite direction —
        which card's text ends up banked in ``merged_oracle_text`` and which
        supplies the printed face simply swap, so one code path covers both.

        The mutating spell's own object is left in exile: it has become part
        of the merged permanent and must not linger on the battlefield or in
        a graveyard as a second permanent.
        """
        from .effect_binder import bind_from_catalogue  # function-scoped: avoid cycle

        # Whichever card ends up *under* contributes only its abilities; the
        # one on top supplies the printed face the pile shows.
        beneath = mutating.card if under else host.card
        merged = list(host.merged_oracle_text)
        under_text = (beneath.oracle_text or "").strip()
        if under_text and under_text not in merged:
            merged.append(under_text)
        under_keywords = list(beneath.keywords or [])
        # Always work on a private copy of the top face: the printed `Card`
        # is shared by every instance of that card, and the merge below
        # rewrites its text.
        top_card = (mutating.card if not under else host.card).as_copy()
        if not under:
            # A fresh top face, so its own text is the base and every banked
            # under-text is folded back in on top of it.
            top_card.oracle_text = "\n".join(
                [top_card.oracle_text or ""] + merged
            ).strip()
        else:
            # The top face is unchanged and already carries everything
            # merged before now — only the new under-text is appended, or
            # earlier merges would be duplicated.
            top_card.oracle_text = "\n".join(
                [top_card.oracle_text or "", under_text]
            ).strip()
        top_card.keywords = list(
            dict.fromkeys(list(top_card.keywords or []) + under_keywords)
        )
        host.card = top_card
        host._front_card = top_card
        host.merged_oracle_text = merged
        # Re-derive the merged pile's abilities through the ordinary bind
        # path, so nothing about mutate needs its own ability-construction
        # code. Both halves of "abilities" have to carry: the oracle text
        # (parsed into triggered/activated/static abilities) *and* the RULE
        # 702 keyword list, which the keyword catalogue reads directly
        # rather than off the text.
        bind_from_catalogue(host)

        owner = self.state.player_by_id(mutating.owner_id)
        self._remove_from_current_zone(owner, mutating)
        mutating.zone = Zone.EXILE
        owner.add_to_zone(mutating, Zone.EXILE)

        continuous.recompute(self.state)
        self.state.fire_event(
            GameEvent(
                EventType.MUTATES,
                instance_id=host.instance_id,
                controller_id=host.controller_id,
                object_types=sorted(host.type_words),
            )
        )

    def break_illegal_soulbond_pairs(self) -> bool:
        """RULE 702.94c: a pair breaks the moment either creature leaves the
        battlefield, stops being a creature, or the two stop sharing a
        controller. Swept as a state-based action so nothing has to remember
        to tear a pair down at each of those sites."""
        changed = False
        for obj in list(self.state.battlefield):
            partner_id = getattr(obj, "paired_with", None)
            if partner_id is None:
                continue
            partner = self.state.find_object(partner_id)
            still_legal = (
                partner is not None
                and partner in self.state.battlefield
                and partner.is_creature
                and obj.is_creature
                and partner.controller_id == obj.controller_id
            )
            if not still_legal:
                obj.paired_with = None
                if partner is not None:
                    partner.paired_with = None
                changed = True
        return changed

    def move_spell_off_stack(self, target: Any, destination: str = "hand") -> bool:
        """Pull a spell off the stack into ``destination`` (RULE 400.1).

        Distinct from `return_to_hand`/`exile`, which move a *battlefield*
        permanent: this removes a `StackItem` entirely, so the spell never
        resolves at all. Practically it is a counter that sends the card
        somewhere other than the graveyard — which is exactly why Narset's
        Reversal ("…then return it to its owner's hand") and Possibility
        Storm ("that player exiles it") both dodge "can't be countered".

        A *copy* on the stack (RULE 707.10a/111.7) isn't a card and has
        nowhere to go: it simply ceases to exist. Returns whether anything
        was moved.
        """
        item = self._stack_item_for(target)
        if item is None or item.obj is None:
            return False
        self.state.stack.remove(item)
        obj = item.obj
        owner = self.state.player_by_id(obj.owner_id)
        if obj.is_token or destination == "exile":
            obj.zone = Zone.EXILE
            if not obj.is_token:
                owner.add_to_zone(obj, Zone.EXILE)
            return True
        obj.zone = Zone.HAND
        owner.add_to_zone(obj, Zone.HAND)
        return True

    def return_spell_to_hand(self, target: Any) -> bool:
        """`move_spell_off_stack` to hand — Narset's Reversal's own clause."""
        return self.move_spell_off_stack(target, "hand")

    @staticmethod
    def _is_cant_be_countered(obj: GameObject) -> bool:
        """RULE 118-area: does ``obj`` carry a "this spell can't be
        countered" marker (`CantBeCounteredEffect`, docked via either the
        `spell_effect` or `static` ability_kind — see that class's
        docstring for why both feed the same check)?
        """
        effects = list(getattr(obj, "spell_effects", []) or [])
        effects += list(getattr(obj, "static_effects", []) or [])
        return any(isinstance(e, CantBeCounteredEffect) for e in effects)

    def counter_spell(self, target: Any) -> None:
        """Remove a spell (a `StackItem` or its game object) from the stack.

        A countered spell goes to its owner's graveyard (RULE 701.5g) and
        never resolves. Unconditional — callers that must honour "can't be
        countered" (RULE 118) or an "unless its controller pays" condition
        (RULE 601) go through `counter_unless_pays` instead, which calls this
        only once both are settled.
        """
        item = self._stack_item_for(target)
        if item is None:
            return
        self.state.stack.remove(item)
        if item.obj is not None:
            owner = self.state.player_by_id(item.obj.owner_id)
            owner.add_to_zone(item.obj, Zone.GRAVEYARD)
            self._flag_commander_zone_choice(item.obj)
        self.state.fire_event(
            GameEvent(EventType.SPELL_RESOLVED, spell=item.description, countered=True)
        )

    def counter_unless_pays(
        self, target: Any, unless_pays: Optional[str], source: Optional[GameObject] = None
    ) -> None:
        """`CounterSpellEffect`'s resolve-time logic (RULE 118/601/701.5).

        Refuses outright if ``target`` carries a "can't be countered" marker
        (RULE 118 — the spell stays on the stack, unaffected). With no
        ``unless_pays`` cost this is a plain `counter_spell`. Otherwise it's
        RULE 601's "Mana Leak" template: if the target's controller *can*
        pay ``unless_pays``, this opens an interactive `counter_unless_pays`
        `pending_choice` for them (`resolve_counter_unless_pays_choice`
        finishes it); a controller who genuinely cannot pay has no real
        decision, so the spell is simply countered without pausing — this is
        also what keeps a passive goldfish-dummy opponent (who never holds
        mana) from stalling resolution on a choice nobody can act on.
        """
        item = self._stack_item_for(target)
        if item is None or item.obj is None:
            return
        obj = item.obj
        if self._is_cant_be_countered(obj):
            return
        if not unless_pays:
            self.counter_spell(target)
            return
        cost = ManaCost.parse(unless_pays)
        if cost.has_variable:
            cost = cost.with_x(getattr(source, "x_paid", 0) or 0)
        controller = self.state.player_by_id(obj.controller_id)
        if controller is None or not controller.mana_pool.can_pay(
            cost, life_available=controller.life
        ):
            self.counter_spell(target)
            return
        self._pending_counter_target = target
        self._pending_counter_cost = cost
        self.state.pending_choice = {
            "kind": "counter_unless_pays",
            "player_id": controller.id,
            "prompt": f"{obj.name}: {unless_pays} zahlen, um es vor dem Countern zu bewahren?",
            "options": [
                {"id": "pay", "label": f"{unless_pays} zahlen"},
                {"id": "decline", "label": "Nicht zahlen"},
            ],
        }

    def resolve_counter_unless_pays_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `counter_unless_pays` choice (RULE 601).

        ``answer == "pay"`` deducts the cost from the target spell's
        controller and leaves it on the stack; anything else (``None``/
        ``"decline"``) counters it.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "counter_unless_pays":
            raise ValueError("no pending counter-unless-pays choice to resolve")
        self.state.pending_choice = None
        target = self._pending_counter_target
        cost = self._pending_counter_cost
        self._pending_counter_target = None
        self._pending_counter_cost = None
        if target is None:
            return
        if answer == "pay" and cost is not None:
            item = self._stack_item_for(target)
            if item is not None and item.obj is not None:
                controller = self.state.player_by_id(item.obj.controller_id)
                if controller is not None:
                    life_spent = controller.mana_pool.pay(cost, life_available=controller.life)
                    self.lose_life(controller, life_spent, cause="cost")
            return
        self.counter_spell(target)

    def check_ward(self, item: StackItem, caster: Player) -> None:
        """RULE 702.21/603.3: after ``item`` (a spell, activated ability, or
        triggered ability) is placed on the stack with its final targets,
        push a genuine ward triggered-ability `StackItem` for every target
        that has ward against ``caster`` — one per warded target (RULE
        702.21c), each on top of ``item``.

        This is what makes ward rules-accurate rather than an inline choice:
        like any triggered ability, it becomes its own object on the stack
        (RULE 603.3 — "the next time a player would receive priority"), so
        both players get a normal priority window to respond to *it* (cast
        an instant, activate an ability) before it resolves, and it resolves
        before ``item`` since it went on top (RULE 608.1 LIFO) — see
        `resolve_ward_effect` for the resolution itself. Constructed and
        pushed directly here (not via the generic `TriggeredAbility`/event
        pipeline `_collect_triggers` drives) because each firing needs its
        own per-instance data (which item, which caster) baked in — a
        `TriggeredAbility` binds one fixed `effects` list once at
        bind-on-load and reuses it for every firing, which can't carry that.

        Controlled by the warded permanent (RULE 603.3a: a triggered
        ability's controller is whoever controlled its source when it
        triggered) — the caster only *pays* it, they don't control it.

        A no-op when ``item`` targets nothing warded — the overwhelming
        common case — so every call site can call this unconditionally right
        after a spell/ability's targets are finalized.
        """
        for target in item.targets or []:
            if not isinstance(target, GameObject):
                continue  # ward is on permanents (RULE 702.21) — never a player
            ward = (getattr(target, "parametric_keywords", None) or {}).get("ward")
            if not ward or target.controller_id == caster.id:
                continue  # no ward, or "opponent" doesn't include its own controller
            cost_text = ward.get("cost")
            if not cost_text:
                continue  # cost couldn't be recognized from the card text — skip, don't guess
            cost = parse_activation_cost(cost_text)
            self.state.stack.append(
                StackItem(
                    kind="ability",
                    controller_id=target.controller_id,
                    effects=[WardEffect(item, caster.id, cost, source=target)],
                    description=f"Ward {cost.label()} ({target.name})",
                    source=target,
                )
            )

    def resolve_ward_effect(
        self,
        item: StackItem,
        caster_id: str,
        cost: ActivationCost,
        ability_controller_id: Optional[str] = None,
    ) -> None:
        """A ward ability's own resolution (RULE 702.21a) — the caster pays
        ``cost`` (any mix of mana/life/discard/sacrifice, the same
        vocabulary `costs.parse_activation_cost` gives an activated
        ability's cost) or ``item`` is countered.

        A no-op if ``item`` already left the stack (RULE 608.2b: nothing
        left to counter — e.g. an earlier simultaneous ward already
        countered it, RULE 702.21c) — this is also where "look back in
        time" naturally falls out: the caster and cost were fixed when
        `check_ward` triggered, so nothing about the warded permanent's
        current state matters here — *except* an unresolved ``{X}`` in
        ``cost.mana`` (RULE 702.21b): "some ward abilities include an X in
        their cost and state what X is equal to. This value is determined
        at the time the ability resolves, not locked in as the ability
        triggers" — resolved fresh right here, against the *current* board,
        scoped to ``ability_controller_id`` (the warded permanent's
        controller — RULE 603.3a, who controls this ability — not the
        caster who pays it). ``cost.x_selector`` is `None` when the "where X
        is …" clause wasn't recognized from the card's own text; X then
        stays 0 (RULE 107.3c's safe default) rather than guessed.
        """
        if self._stack_item_for(item) is None:
            return
        if cost.mana.has_variable:
            x_value = (
                continuous.count_selector(self.state, ability_controller_id, cost.x_selector)
                if cost.x_selector
                else 0
            )
            cost.mana = cost.mana.with_x(x_value)
        try:
            caster = self.state.player_by_id(caster_id)
        except KeyError:
            caster = None
        if caster is None or not self._can_pay_player_cost(caster, cost):
            # No real decision — countered outright, same "don't stall a
            # passive goldfish opponent on a choice nobody can act on"
            # shortcut `counter_unless_pays` uses.
            self.counter_spell(item)
            return
        self._pending_ward_item = item
        self._pending_ward_caster_id = caster_id
        self._pending_ward_cost = cost
        cost_label = cost.label()
        self.state.pending_choice = {
            "kind": "ward",
            "player_id": caster.id,
            "prompt": f"Ward {cost_label} — zahlen, um deinen Zauberspruch/deine Fähigkeit zu "
            "behalten?",
            "options": [
                {"id": "pay", "label": f"{cost_label} zahlen"},
                {"id": "decline", "label": "Nicht zahlen"},
            ],
        }

    def _can_pay_player_cost(self, player: Player, cost: ActivationCost) -> bool:
        """Whether ``player`` can pay ``cost`` out of their own resources.

        The same per-component affordability checks
        `GameEngine._can_pay_activation_cost` uses for an activated
        ability's cost, minus the tap/untap-source and remove-counters
        components — those are tied to a specific permanent's own state,
        which doesn't apply to any of the "pay this or else" costs a *rule
        or resolving effect* asks a player for: ward (RULE 702.21), and
        cumulative upkeep-shaped "sacrifice ~ unless you pay `<cost>`"
        (`sacrifice_unless_pay`). Those are always paid from the player's
        own resources (mana, life, hand, permanents they control), never
        "this permanent".
        """
        if cost.mana.symbols and not player.mana_pool.can_pay(
            cost.mana, life_available=player.life
        ):
            return False
        if cost.pay_life and player.life < cost.pay_life:
            return False
        if cost.discard and cost.discard != DISCARD_HAND and len(player.hand) < cost.discard:
            return False
        if cost.sacrifice and not any(
            _matches_permanent_type(obj, cost.sacrifice)
            for obj in self.state.permanents_controlled_by(player.id)
        ):
            return False
        return True

    def _pay_player_cost(self, player: Player, cost: ActivationCost) -> None:
        """Charge ``player`` a cost's components — reuses the same per-kind
        payment primitives `GameEngine.activate_ability` charges an activated
        ability's cost with. The payment half of `_can_pay_player_cost`."""
        if cost.mana.symbols:
            life_spent = player.mana_pool.pay(cost.mana, life_available=player.life)
            self.lose_life(player, life_spent, cause="cost")
        if cost.pay_life:
            self.lose_life(player, cost.pay_life, cause="cost")
        if cost.discard:
            self.discard(player, len(player.hand) if cost.discard == DISCARD_HAND else cost.discard)
        if cost.sacrifice:
            self.sacrifice(player, cost.sacrifice, 1)

    def resolve_ward_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `ward` choice (RULE 702.21).

        ``answer == "pay"`` charges the *caster* the cost and leaves the
        item on the stack; anything else counters it. Either way, if
        another ward ability is still on the stack (RULE 702.21c, a
        different warded target of the same spell/ability), it simply
        becomes the new top of the stack and resolves next through the
        ordinary stack loop — no extra bookkeeping needed here.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "ward":
            raise ValueError("no pending ward choice to resolve")
        self.state.pending_choice = None
        item = self._pending_ward_item
        cost = self._pending_ward_cost
        caster_id = self._pending_ward_caster_id
        self._pending_ward_item = None
        self._pending_ward_cost = None
        self._pending_ward_caster_id = None
        if answer == "pay" and cost is not None and caster_id:
            try:
                caster = self.state.player_by_id(caster_id)
            except KeyError:
                caster = None
            if caster is not None:
                self._pay_player_cost(caster, cost)
            return
        if item is not None:
            self.counter_spell(item)

    def check_rampage(self, attacker: GameObject, blocker_count: int) -> None:
        """RULE 702.23: place Rampage's triggered ability, if any, right when
        ``attacker`` becomes blocked — built directly (not via the generic
        `TriggeredAbility`/`_collect_triggers` event pipeline `_place_trigger`
        normally drives *from*, though it still ends by calling that same
        method to go on the stack) because its pump amount is fixed *at
        trigger time* to this specific block's blocker count (RULE 603.4),
        which a bind-on-load `TriggeredAbility` — one fixed `effects` list,
        reused for every firing — can't carry. The identical "per-firing
        data" problem `check_ward` solves the same way, for the same reason.

        A no-op when ``attacker`` has no Rampage, or wasn't blocked by more
        than one creature (RULE 702.23a: "for each creature blocking it
        beyond the first" — zero bonus for a single blocker, so nothing to
        place).
        """
        param = (getattr(attacker, "parametric_keywords", None) or {}).get("rampage")
        if not param or param.get("n") is None:
            return
        bonus = int(param["n"]) * max(0, blocker_count - 1)
        if bonus <= 0:
            return
        ability = TriggeredAbility(
            trigger_event=EventType.BECOMES_BLOCKED,
            effects=[PumpEffect(power=bonus, toughness=bonus)],
            controller_id=attacker.controller_id,
            source=attacker,
            description=f"Rampage {param['n']}",
        )
        self._place_trigger(ability)

    def check_dethrone(self, attacker: GameObject) -> None:
        """RULE 702.107: place Dethrone's own triggered ability, if any,
        right when ``attacker`` is declared — built directly (like
        `check_rampage`, for the same "per-firing dynamic" reason) rather
        than as a bind-on-load `TriggeredAbility`
        (`effect_binder._keyword_triggered_abilities`) since `combat.has`
        must be read fresh at attack-declaration time: Dethrone isn't only
        ever printed on the attacker itself, it's also grantable to "other
        creatures you control" by a layer-6 static (Marchesa, the Black
        Rose) that never runs the bind-on-load machinery on those other
        creatures — only a check at the moment of the actual attack sees a
        dynamically-granted keyword at all.

        A no-op when ``attacker`` doesn't currently have dethrone, or the
        defending player (its controller, for a planeswalker/battle attack —
        RULE 702.107a's ruling that Dethrone cares about the defending
        *player*'s life regardless of what's actually being attacked) isn't
        at or tied for the game's highest life total.
        """
        if not combat.has(attacker, "dethrone"):
            return
        defender = self._dethrone_defending_player(attacker)
        if defender is None:
            return
        living = self.state.living_players()
        if not living or defender.life < max(p.life for p in living):
            return
        ability = TriggeredAbility(
            trigger_event=EventType.ATTACKS,
            effects=[AddCountersEffect(amount=1, source=attacker)],
            controller_id=attacker.controller_id,
            source=attacker,
            description="Dethrone",
        )
        self._place_trigger(ability)

    def _dethrone_defending_player(self, attacker: GameObject) -> Optional[Player]:
        """Resolve ``attacker.combat_defender`` (`GameEngine.declare_attackers`/
        `_assign_defender`) to the defending *player*, for `check_dethrone`.
        Distinct from `GameEngine._resolve_combat_defender` — that one
        returns the actual damage-assignment target (a planeswalker object
        itself), while Dethrone needs that permanent's *controller*.
        """
        spec = getattr(attacker, "combat_defender", None)
        if not spec:
            return None
        if spec.get("kind") == "player":
            try:
                return self.state.player_by_id(spec["id"])
            except KeyError:
                return None
        if spec.get("kind") in ("planeswalker", "battle"):
            obj = self.state.find_object(spec["instance_id"])
            if obj is None:
                return None
            # RULE 310.8d: a battle's defending player is its protector, not
            # its controller — see `GameEngine._defending_player`.
            player_id = obj.protector_id if obj.is_battle else obj.controller_id
            if player_id is None:
                return None
            try:
                return self.state.player_by_id(player_id)
            except KeyError:
                return None
        return None

    # ------------------------------------------------------------------
    # Battles (RULE 310)
    # ------------------------------------------------------------------

    def _eligible_protectors(self, obj: GameObject) -> list[Player]:
        """Who may be ``obj``'s protector (RULE 310.8a), by battle type.

        RULE 310.11a: a Siege's protector must be an **opponent** of its
        controller — which is what makes a Siege attackable by its own
        controller (310.8b). A battle with no battle type at all falls back
        to 310.8a's "its controller becomes its protector".

        Losers are excluded: a player who's out of the game can neither be
        attacked nor block, so leaving them as protector would strand the
        battle. That's exactly the case RULE 310.10's SBA exists to repair.
        """
        alive = [p for p in self.state.players if not p.has_lost]
        if obj.card.is_siege:
            return [p for p in alive if p.id != obj.controller_id]
        return [p for p in alive if p.id == obj.controller_id]

    def battle_is_being_attacked(self, obj: GameObject) -> bool:
        """Whether any creature is currently attacking ``obj`` (RULE 310.10's
        "a battle that isn't being attacked" carve-out — the protector of a
        battle already under attack must not be swapped out from under the
        combat that's resolving)."""
        return any(
            other.attacking
            and (other.combat_defender or {}).get("kind") == "battle"
            and (other.combat_defender or {}).get("instance_id") == obj.instance_id
            for other in self.state.battlefield
        )

    def exile_siege_for_transformed_cast(self, obj: GameObject) -> bool:
        """RULE 310.11b: exile a defeated Siege, then open its controller's
        "you may cast it transformed without paying its mana cost" window.

        The exile half is a genuine RULE 400.7 zone change (a new object, so
        `reset_as_new_object` drops the spent defense counters and the
        protector), after which the object is flipped onto its **back** face
        — so the card sitting in exile simply *is* the transformed card, and
        the ordinary cast path needs no notion of "cast this face instead".
        The free-cast permission is `grant_free_cast_window_from_exile`, the
        same one Rebound and Beseech the Mirror use.

        Simplification worth knowing: that permission lasts the rest of the
        turn, whereas RULE 310.11b's "you may cast it" is strictly a
        window *during this ability's resolution*. Declining and casting it
        two spells later is therefore legal here and wouldn't be in paper.
        This is the shape the engine already had, shared with the two
        callers above rather than a second, stricter mechanism.

        Returns whether the Siege actually flipped — ``False`` (exiled, but
        no free cast offered) for a battle with no back face at all, which
        no real Siege is but a Replay-editor board could produce.
        """
        controller = self.state.player_by_id(obj.controller_id)
        self._detach_attachments_from(obj)
        self.exile(obj)
        obj.reset_as_new_object()
        obj.controller_id = controller.id
        if not self.transform_permanent(obj):
            return False
        self.grant_free_cast_window_from_exile(obj)
        return True

    def choose_protector(self, obj: GameObject, player_id: Optional[str]) -> None:
        """Set ``obj``'s protector (RULE 310.8a), validated against its battle
        type. An unrecognized/missing ``player_id`` falls back to the first
        eligible player — the same treatment `resolve_enter_choice` gives a
        missing answer to a mandatory choice, so a battle is never left
        without one (which RULE 310.10 would then punish with a graveyard
        move)."""
        eligible = self._eligible_protectors(obj)
        if not eligible:
            obj.protector_id = None
            return
        match = next((p for p in eligible if p.id == player_id), None)
        obj.protector_id = (match or eligible[0]).id

    # ------------------------------------------------------------------
    # Library search + shuffle + the pending-choice it needs (RULE 701.19/20)
    # ------------------------------------------------------------------

    def request_search(
        self,
        player: Player,
        criteria: Any = "",
        destination: str = "hand",
        count: int = 1,
        optional: bool = True,
        zones: Optional[list[str]] = None,
        destinations: Optional[list[str]] = None,
        exile_rest: bool = False,
        extra_counters: Optional[dict[str, Any]] = None,
        destination_if: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Open a "search your library" choice on the game state (a tutor).

        ``criteria`` says *what* to look for (see `models.card_query`: ``""``
        = "a card", ``"Creature"``, ``{"basic": True}``, ``{"type": [...],
        "max_mana_value": 3}``, …); ``destination`` says *where* the found
        card goes ("hand"/"battlefield"/"battlefield_tapped"/"library_top"/
        "library_bottom"/"graveyard"/"exile"); ``count`` is how many cards
        ("up to N"), offered one at a time.

        ``zones`` says *where* to look — ``["library"]`` (default, RULE
        701.19) or ``["library", "graveyard"]``/``["graveyard"]`` for
        "search your library and/or graveyard" (the ~50-card family
        including backgrounds/Lurrus-shaped effects). ``destinations``, if
        given, is a per-found-card override list, positional against the
        picks ("put one onto the battlefield tapped and the other into your
        hand" — Cultivate/Kodama's Reach); any pick past its end falls back
        to ``destination``. ``exile_rest``, once the search finishes, exiles
        every remaining criteria-matching card still in ``zones`` and
        suppresses the shuffle entirely (Doomsday-shaped: its own text puts
        the chosen cards "on top of your library in any order" with no
        shuffle — RULE 701.19e's shuffle is for an *ordinary* search).

        ``extra_counters`` (``{"kind": "+1/+1", "count": 1}``) puts counters
        on each found card once it reaches the battlefield — Neoform's "put
        that card onto the battlefield **with an additional +1/+1 counter on
        it**". Ignored for any non-battlefield destination, since a card in
        hand/library has nothing to carry counters.

        ``destination_if`` (``[{"criteria": …, "destination": …}, …]``) is a
        *conditional* destination override, checked per found card, first
        match winning and taking precedence over ``destinations`` —
        Archdruid's Charm's "put it onto the battlefield tapped if it's a
        land card. Otherwise, put it into your hand." Unlike ``destinations``
        it can't be resolved when the search opens, only once the player has
        said which card they found.

        Records the eligible cards (across ``zones``) as a `state.
        pending_choice` — the engine's resolve loop stops on it and the
        session surfaces it, and `resolve_search_choice` finishes the search
        once the player picks (or declines). An ordinary search (RULE
        701.19) always shuffles the library afterwards (RULE 701.19e) as
        long as ``"library"`` is among ``zones``; with nothing eligible it
        just shuffles (if applicable), no choice needed.
        """
        zones = list(zones) if zones else ["library"]
        if "library" in zones:
            self.state.fire_event(
                GameEvent(EventType.LIBRARY_SEARCHED, player_id=player.id)
            )
        eligible = [
            obj
            for obj in self._search_zone_objects(player, zones)
            if card_query.matches(obj.card, criteria)
        ]
        if not eligible or count <= 0:
            if "library" in zones and not exile_rest:
                self.shuffle_library(player)
            return
        self.state.pending_choice = self._search_choice(
            player, criteria, destination, count, optional, found=[],
            zones=zones, destinations=destinations, exile_rest=exile_rest,
            extra_counters=extra_counters, destination_if=destination_if,
        )

    def _search_zone_objects(self, player: Player, zones: list[str]) -> list[GameObject]:
        """The combined pool of cards a (possibly multi-zone) search draws
        from, library before graveyard when both are searched.

        ``"hand"`` is a *choice* rather than a search in the RULE 701.19
        sense (Tooth and Nail's "put up to two creature cards from your hand
        onto the battlefield") — it reuses this same machinery so the pick
        is offered one card at a time with the same UI/undo shape as every
        other, but `request_search` never shuffles for it and never fires
        `LIBRARY_SEARCHED`, both of which are keyed to ``"library"``."""
        objs: list[GameObject] = []
        if "library" in zones:
            objs.extend(player.library)
        if "graveyard" in zones:
            objs.extend(player.graveyard)
        if "hand" in zones:
            objs.extend(player.hand)
        return objs

    def resolve_search_choice(self, instance_id: Optional[int]) -> None:
        """Answer a pending search: pick a card, re-ask for the next, or finish.

        ``instance_id`` names the chosen card, or is None to decline (which
        ends the search even with picks still available — RULE 701.19c "up
        to"). When ``count`` > 1 and cards remain, this re-opens the choice
        for the next card; otherwise it moves every chosen card to the
        destination and shuffles. Clears the pending choice when done.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "search":
            raise ValueError("no pending search to resolve")
        player = self.state.player_by_id(choice["player_id"])
        found: list[int] = list(choice["found"])
        zones = choice.get("zones") or ["library"]

        declined = instance_id is None
        if not declined:
            eligible_ids = {e["instance_id"] for e in choice["eligible"]}
            if instance_id not in eligible_ids:
                raise ValueError(f"{instance_id} is not a valid search target")
            found.append(instance_id)

        remaining = choice["count"] - len(found)
        still_eligible = [
            obj
            for obj in self._search_zone_objects(player, zones)
            if obj.instance_id not in found
            and card_query.matches(obj.card, choice["criteria"])
        ]
        if not declined and remaining > 0 and still_eligible:
            self.state.pending_choice = self._search_choice(
                player, choice["criteria"], choice["destination"],
                choice["count"], choice["optional"], found=found,
                zones=zones, destinations=choice.get("destinations"),
                exile_rest=choice.get("exile_rest", False),
                extra_counters=choice.get("extra_counters"),
                destination_if=choice.get("destination_if"),
            )
            return

        self.state.pending_choice = None
        self._finish_search(
            player, found, choice["destination"],
            zones=zones, destinations=choice.get("destinations"),
            exile_rest=choice.get("exile_rest", False),
            criteria=choice["criteria"],
            extra_counters=choice.get("extra_counters"),
            destination_if=choice.get("destination_if"),
        )

    def _search_choice(
        self,
        player: Player,
        criteria: Any,
        destination: str,
        count: int,
        optional: bool,
        found: list[int],
        zones: Optional[list[str]] = None,
        destinations: Optional[list[str]] = None,
        exile_rest: bool = False,
        extra_counters: Optional[dict[str, Any]] = None,
        destination_if: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Build the serializable `pending_choice` for a search in progress."""
        zones = list(zones) if zones else ["library"]
        eligible = [
            {"instance_id": obj.instance_id, "name": obj.name}
            for obj in self._search_zone_objects(player, zones)
            if obj.instance_id not in found and card_query.matches(obj.card, criteria)
        ]
        # Each eligible card is one option; declining an optional search is a
        # further option. `options` is the general form the UI renders (as a
        # popup); `eligible` is kept for the pre-options callers/tests.
        options = [
            {"id": str(e["instance_id"]), "label": e["name"], "instance_id": e["instance_id"]}
            for e in eligible
        ]
        if optional:
            options.append({"id": "decline", "label": "Nichts wählen"})
        description = card_query.describe(criteria)
        zone_label = " oder ".join(
            {"library": "Bibliothek", "graveyard": "Friedhof", "hand": "Hand"}[z]
            for z in zones
        )
        prompt = (
            f"Wähle aus deiner {zone_label}: {description}" if zones == ["hand"]
            else f"Suche in {zone_label} nach: {description}"
        )
        if count > 1:
            prompt += f" (noch {count - len(found)})"
        return {
            "kind": "search",
            "player_id": player.id,
            "destination": destination,
            "destinations": list(destinations) if destinations else None,
            "zones": zones,
            "exile_rest": exile_rest,
            "extra_counters": dict(extra_counters) if extra_counters else None,
            "destination_if": [dict(rule) for rule in destination_if] if destination_if else None,
            "criteria": card_query.normalize(criteria),
            "description": description,
            "prompt": prompt,
            # Kept for the pre-criteria UI/tests; a plain label of the search.
            "type_restriction": criteria if isinstance(criteria, str) else "",
            "optional": optional,
            "count": count,
            "found": list(found),
            "remaining": count - len(found),
            "eligible": eligible,
            "options": options,
        }

    def _finish_search(
        self,
        player: Player,
        found: list[int],
        destination: str,
        zones: Optional[list[str]] = None,
        destinations: Optional[list[str]] = None,
        exile_rest: bool = False,
        criteria: Any = "",
        extra_counters: Optional[dict[str, Any]] = None,
        destination_if: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Move every chosen card to its destination, then shuffle the
        library (RULE 701.19e) — unless ``exile_rest`` suppresses it
        entirely (Doomsday-shaped, see `request_search`). ``destinations``,
        if given, overrides ``destination`` per chosen card, positionally
        (Cultivate/Kodama's Reach-shaped split destinations)."""
        zones = list(zones) if zones else ["library"]
        chosen: list[GameObject] = []
        for instance_id in found:
            obj = self._remove_search_hit(player, instance_id, zones)
            if obj is not None:
                chosen.append(obj)

        dest_list = list(destinations) if destinations else []
        rules = list(destination_if) if destination_if else []
        effective_destinations: list[str] = []
        for index, obj in enumerate(chosen):
            dest = dest_list[index] if index < len(dest_list) else destination
            # RULE 701.19c: a *conditional* destination branches on the card
            # that was actually found ("onto the battlefield tapped if it's
            # a land card. Otherwise, …"), so it can only be resolved here,
            # and it wins over the positional list above. First rule that
            # matches applies.
            for rule in rules:
                if card_query.matches(obj.card, rule.get("criteria", "")):
                    dest = str(rule.get("destination", dest))
                    break
            effective_destinations.append(dest)

        shuffle = "library" in zones and not exile_rest
        # "Shuffle, then put on top/bottom" (RULE 701.19e for a library
        # destination): the found card must land *after* the shuffle, so its
        # position is known — otherwise the shuffle would move it.
        to_library = any(d in ("library_top", "library_bottom") for d in effective_destinations)
        if shuffle and to_library:
            self.shuffle_library(player)
        for obj, dest in zip(chosen, effective_destinations):
            self._put_searched_card(player, obj, dest)
            if extra_counters and dest in ("battlefield", "battlefield_tapped"):
                # Neoform: "…onto the battlefield **with an additional +1/+1
                # counter on it**" — RULE 614.1c-adjacent, but applied here
                # rather than as an entry replacement because the counters
                # come from the *searching effect*, not the card's own text.
                self.add_counters(
                    obj,
                    int(extra_counters.get("count", 1)),
                    str(extra_counters.get("kind", "+1/+1")),
                )
        if shuffle and not to_library:
            self.shuffle_library(player)

        if exile_rest:
            rest = [
                obj
                for obj in self._search_zone_objects(player, zones)
                if card_query.matches(obj.card, criteria)
            ]
            for obj in rest:
                player.remove_from_zone(obj, obj.zone)
                self._put_searched_card(player, obj, "exile")

    def _remove_search_hit(
        self, player: Player, instance_id: int, zones: list[str]
    ) -> Optional[GameObject]:
        """Locate a chosen card's `GameObject` by instance id and remove it
        from whichever searched ``zones`` actually holds it."""
        obj = next(
            (o for o in self._search_zone_objects(player, zones) if o.instance_id == instance_id),
            None,
        )
        if obj is not None:
            player.remove_from_zone(obj, obj.zone)
        return obj

    def _put_searched_card(self, player: Player, obj: GameObject, destination: str) -> None:
        if destination in ("battlefield", "battlefield_tapped"):
            obj.summoning_sick = True
            obj.tapped = destination == "battlefield_tapped"
            self.state.add_to_battlefield(obj)
            self.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD,
                    controller_id=player.id,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
        elif destination == "library_bottom":
            obj.zone = Zone.LIBRARY
            player.library.insert(0, obj)  # bottom (index 0 — see Player.library)
        elif destination == "library_top":
            player.add_to_zone(obj, Zone.LIBRARY)  # top of deck is the list end
        elif destination == "graveyard":
            player.add_to_zone(obj, Zone.GRAVEYARD)
        elif destination == "exile":
            player.add_to_zone(obj, Zone.EXILE)
            self.state.fire_event(
                GameEvent(EventType.EXILE, player_id=player.id, object=obj.name, from_zone="library")
            )
        elif destination == "exile_face_down":
            # RULE 701.20a: Beseech the Mirror's "exile it face down" — the
            # same exile as above, but the card's identity stays hidden from
            # everyone but its owner until it's cast or returned to hand.
            obj.face_down_in_exile = True
            player.add_to_zone(obj, Zone.EXILE)
            self.state.fire_event(
                GameEvent(EventType.EXILE, player_id=player.id, object=obj.name, from_zone="library")
            )
        elif destination == "cast_free":
            # Sunforger-shaped: "search your library for X and cast that
            # card without paying its mana cost" (RULE 118.9/601.3b) — the
            # same free-cast primitive cascade/discover use, just reached
            # from a genuine library search instead of an exile-until-hit.
            self.cast_without_paying(player, obj)
        else:  # hand (default) — most tutors
            player.add_to_zone(obj, Zone.HAND)

    def request_impulsive_look(
        self,
        player: Player,
        count: int,
        criteria: Any = "",
        hit_destination: str = "hand",
        miss_destination: str = "graveyard",
        optional: bool = True,
    ) -> None:
        """"Look at the top N cards, take one matching ``criteria``, put the
        rest into ``miss_destination``" (Grisly Salvage/Commune with the
        Gods-shaped, RULE 701-adjacent — not RULE 701.19's "search", which
        looks through the *whole* library and always shuffles afterwards).

        Peels exactly ``count`` cards off the top into exile (a temporary
        holding area, the same shape `_exile_top_until` uses for cascade/
        discover) and opens a choice among only the ones matching
        ``criteria``. With nothing eligible, every peeled card goes straight
        to ``miss_destination`` — no choice needed.
        """
        peeled: list[GameObject] = []
        for _ in range(max(0, count)):
            if not player.library:
                break
            obj = player.library.pop()
            obj.zone = Zone.EXILE
            player.exile.append(obj)
            peeled.append(obj)
            self.state.fire_event(
                GameEvent(EventType.EXILE, player_id=player.id, object=obj.name, from_zone="library")
            )
        eligible = [obj for obj in peeled if card_query.matches(obj.card, criteria)]
        if not eligible:
            for obj in peeled:
                player.remove_from_zone(obj, Zone.EXILE)
                self._put_searched_card(player, obj, miss_destination)
            return
        self.state.pending_choice = {
            "kind": "impulsive_look",
            "player_id": player.id,
            "optional": optional,
            "hit_destination": hit_destination,
            "miss_destination": miss_destination,
            "description": f"Von den obersten {len(peeled)} Karten: {card_query.describe(criteria)}",
            "prompt": f"Eine passende Karte ({card_query.describe(criteria)}) auf die Hand nehmen?",
            "eligible": [{"instance_id": o.instance_id, "name": o.name} for o in eligible],
            "peeled": [o.instance_id for o in peeled],
            "options": (
                [
                    {"id": str(o.instance_id), "label": o.name, "instance_id": o.instance_id}
                    for o in eligible
                ]
                + ([{"id": "decline", "label": "Nichts wählen"}] if optional else [])
            ),
        }

    def resolve_impulsive_look_choice(self, instance_id: Optional[int]) -> None:
        """Answer a pending `request_impulsive_look` choice: take the chosen
        card (or none, if optional), then route every other peeled card to
        ``miss_destination``."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "impulsive_look":
            raise ValueError("no pending impulsive-look choice to resolve")
        player = self.state.player_by_id(choice["player_id"])
        self.state.pending_choice = None

        chosen_id: Optional[int] = None
        if instance_id is not None:
            eligible_ids = {e["instance_id"] for e in choice["eligible"]}
            if instance_id not in eligible_ids:
                raise ValueError(f"{instance_id} is not a valid impulsive-look target")
            chosen_id = instance_id

        peeled_ids = set(choice["peeled"])
        for obj in [o for o in list(player.exile) if o.instance_id in peeled_ids]:
            destination = choice["hit_destination"] if obj.instance_id == chosen_id else choice["miss_destination"]
            player.remove_from_zone(obj, Zone.EXILE)
            self._put_searched_card(player, obj, destination)

    def _grant_temp_play_permission(
        self,
        obj: GameObject,
        permission_player: Player,
        source_name: Optional[str],
        same_turn_only: bool,
        mana_wildcard: Optional[str],
    ) -> None:
        """Shared bookkeeping for a "you may play/cast this exiled card"
        grant (RULE 601.3b analogue) — factored out since both
        `exile_with_play_permission` (Light Up the Stage/Ragavan-shaped, top
        of a library) and `exile_graveyard_with_cast_permission` (Mnemonic
        Betrayal-shaped, a whole graveyard) need it identically per object.

        ``same_turn_only`` stores the *comparison-adjusted* turn value
        `GameEngine._step_cleanup`'s existing ``turn >= state.turn_number``
        sweep already uses, rather than changing that sweep itself: storing
        ``turn_number`` (the default) survives through this turn's own
        cleanup plus all of next turn ("until the end of your next turn");
        storing ``turn_number - 1`` instead makes the very next cleanup
        (this same turn's) already sweep it — "until end of turn" (Ragavan/
        Mnemonic Betrayal's own, shorter window).
        """
        granted_value = self.state.turn_number - 1 if same_turn_only else self.state.turn_number
        self.state.temp_play_permissions[obj.instance_id] = granted_value
        self.state.temp_play_permission_player[obj.instance_id] = permission_player.id
        if source_name:
            self.state.temp_play_permission_source[obj.instance_id] = source_name
        if mana_wildcard:
            self.state.mana_wildcard_permission[obj.instance_id] = mana_wildcard

    def exile_with_play_permission(
        self,
        player: Player,
        count: int,
        source_name: Optional[str] = None,
        permission_player: Optional[Player] = None,
        same_turn_only: bool = False,
        mana_wildcard: Optional[str] = None,
    ) -> list[GameObject]:
        """Exile the top ``count`` cards of ``player``'s library; every one
        of them becomes playable by ``permission_player`` (``player``
        itself, when omitted) through the end of ``player``'s *next* turn —
        or, with ``same_turn_only=True``, only through the end of this turn
        (RULE 601.3b analogue — Light Up the Stage-shaped "impulsive draw";
        Ragavan, Nimble Pilferer's own shorter window and *different*
        permission-holder, its own controller rather than the damaged
        player whose library was exiled), tracked in `GameState.
        temp_play_permissions`/`temp_play_permission_player`.

        Distinct from `request_impulsive_look`: no filter, no choice, and
        nothing is routed to a miss destination — every card exiled here
        stays in exile, playable, until its window lapses (swept by
        `GameEngine._step_cleanup`) or it's actually cast/played.

        ``source_name`` (the granting spell/ability's name, e.g. "Light Up
        the Stage") is recorded in the sibling `GameState.
        temp_play_permission_source` so the board can explain *why* the
        card is castable — purely cosmetic, no effect on legality.
        ``mana_wildcard`` — see `GameState.mana_wildcard_permission`.
        """
        holder = permission_player or player
        exiled: list[GameObject] = []
        for _ in range(max(0, count)):
            if not player.library:
                break
            obj = player.library.pop()
            obj.zone = Zone.EXILE
            player.exile.append(obj)
            self._grant_temp_play_permission(obj, holder, source_name, same_turn_only, mana_wildcard)
            exiled.append(obj)
            self.state.fire_event(
                GameEvent(EventType.EXILE, player_id=player.id, object=obj.name, from_zone="library")
            )
        return exiled

    def exile_graveyard_with_cast_permission(
        self,
        player: Player,
        permission_player: Player,
        source_name: Optional[str] = None,
        mana_wildcard: Optional[str] = None,
    ) -> list[GameObject]:
        """Exile every card currently in ``player``'s graveyard; each becomes
        castable by ``permission_player`` through the end of this turn
        (Mnemonic Betrayal-shaped: "Exile all opponents' graveyards. You may
        cast spells from among those cards this turn…") — the graveyard-
        sourced sibling of `exile_with_play_permission`'s library-top exile,
        sharing its `_grant_temp_play_permission` bookkeeping. Always
        "this turn only" (RULE 601.3b analogue has no "next turn" variant
        printed for this shape, unlike Light Up the Stage's).

        Grants the same `GameState.temp_play_permissions` a "play" (not
        strictly "cast"-only) permission — a card in a graveyard is
        overwhelmingly a nonland spell, so this doesn't distinguish a
        hypothetical land card there from every other exiled card; a
        documented, narrow simplification (see `GameEngine.can_play_land`'s
        shared zone check) rather than a second dict just for that edge case.
        """
        exiled: list[GameObject] = []
        for obj in list(player.graveyard):
            player.remove_from_zone(obj, Zone.GRAVEYARD)
            obj.zone = Zone.EXILE
            player.exile.append(obj)
            self._grant_temp_play_permission(
                obj, permission_player, source_name, same_turn_only=True, mana_wildcard=mana_wildcard,
            )
            exiled.append(obj)
            self.state.fire_event(
                GameEvent(EventType.EXILE, player_id=player.id, object=obj.name, from_zone="graveyard")
            )
        return exiled

    def grant_free_cast_window_from_exile(self, obj: GameObject) -> None:
        """Open ``obj``'s (already-exiled) "cast it without paying its mana
        cost" window for the rest of the turn — reuses
        `_grant_temp_play_permission`'s same-turn-only temp-cast permission
        (so `can_cast`/`cast_spell` already know how to let it be cast from
        exile) plus `GameState.free_cast_instance_ids` to also zero its mana
        cost. Casting it that way goes through the ordinary action loop, so
        the spell gets its full targeting/modal choices rather than a
        stripped-down mid-resolution cast.

        Two callers, both "you may cast this card from exile without paying
        its mana cost": RULE 702.88b Rebound's delayed half
        (`ReboundFreeCastWindowEffect`) and Beseech the Mirror's bargained
        clause (`CastExiledFaceDownEffect`).
        """
        controller = self.state.player_by_id(obj.controller_id)
        if controller is None:
            return
        self._grant_temp_play_permission(
            obj, controller, obj.name, same_turn_only=True, mana_wildcard=None,
        )
        self.state.free_cast_instance_ids.add(obj.instance_id)

    def put_hand_creature_onto_battlefield(
        self, player: Player, max_total_pt: Optional[int] = None
    ) -> Optional[GameObject]:
        """"You may put a creature card from your hand onto the
        battlefield." (RULE 701 "cheat into play" — Sneak Attack/Meek
        Attack-shaped). Auto-picks the first eligible creature in hand — no
        chooser in this MVP, the same idiom `discard`/`put_hand_cards_on_
        top` already use for an un-targeted hand-card pick — optionally
        filtered by ``max_total_pt`` (Meek Attack's own "total power and
        toughness 5 or less"). Returns the object placed, or ``None`` if no
        eligible creature was in hand. RULE 400.7: leaving the hand makes
        this a new object.
        """
        creature = next(
            (
                o for o in player.hand
                if o.card.is_creature
                and (
                    max_total_pt is None
                    or (o.card.power or 0) + (o.card.toughness or 0) <= max_total_pt
                )
            ),
            None,
        )
        if creature is None:
            return None
        self._remove_from_current_zone(player, creature)
        creature.reset_as_new_object()
        creature.controller_id = player.id
        self._put_searched_card(player, creature, "battlefield")
        return creature

    def shuffle_library(self, player: Player) -> None:
        """Shuffle a player's library and announce it (RULE 701.20)."""
        player.shuffle_library()
        self.state.fire_event(GameEvent(EventType.SHUFFLE, player_id=player.id))

    def shuffle_hand_and_graveyard_into_library(self, player: Player) -> None:
        """"Shuffle your hand and graveyard into your library." (RULE 701.20,
        Timetwister/Time Reversal/Echo of Eons's "wheel" template — all three
        print the identical line). Every hand/graveyard card leaves its zone,
        goes to the library, then the whole thing is shuffled and announced
        the ordinary way (`shuffle_library`)."""
        for obj in list(player.hand):
            player.remove_from_zone(obj, Zone.HAND)
            player.add_to_zone(obj, Zone.LIBRARY)
        for obj in list(player.graveyard):
            player.remove_from_zone(obj, Zone.GRAVEYARD)
            player.add_to_zone(obj, Zone.LIBRARY)
        self.shuffle_library(player)

    # ------------------------------------------------------------------
    # Cascade / Discover: reveal from the top, free-cast a hit (RULE 702.85 / .164)
    # ------------------------------------------------------------------

    def request_cascade(self, player: Player, max_mana_value: int) -> None:
        """Cascade (RULE 702.85): exile from the top until a nonland spell
        cheaper than the cascade spell, which its controller *may* cast for
        free; the rest go to the bottom in a random order.

        Exiles eagerly, then — if a hit was found — opens a "may cast" choice
        (`resolve_cascade_choice`). With no hit it just bottoms what it
        exiled. The bottoming is deferred to the choice so a card that is cast
        leaves exile first (RULE 702.85e ordering).
        """
        criteria = {"max_mana_value": max_mana_value - 1}
        matched, exiled = self._exile_top_until(player, criteria, exclude_lands=True)
        if matched is None:
            self._bottom_exiled(player, exiled)
            return
        self.state.pending_choice = {
            "kind": "cascade",
            "player_id": player.id,
            "optional": True,  # "you may cast it"
            "description": f"Cascade: {matched.name}",
            "prompt": f"Cascade — {matched.name} kostenlos wirken?",
            "matched_id": matched.instance_id,
            "eligible": [{"instance_id": matched.instance_id, "name": matched.name}],
            # A yes/no decision (RULE 702.85d "you may cast it").
            "options": [
                {"id": "cast", "label": f"„{matched.name}“ kostenlos wirken",
                 "instance_id": matched.instance_id},
                {"id": "decline", "label": "Nicht wirken (unter die Bibliothek)"},
            ],
            "exiled": [o.instance_id for o in exiled],
        }

    def resolve_cascade_choice(self, cast: bool = True) -> None:
        """Finish a cascade: ``cast`` the hit for free (or not), then bottom
        every still-exiled card from this cascade in a random order."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "cascade":
            raise ValueError("no pending cascade to resolve")
        player = self.state.player_by_id(choice["player_id"])
        self.state.pending_choice = None

        if cast:
            obj = self._exiled_by_id(player, choice["exiled"], choice["matched_id"])
            if obj is not None:
                self.cast_without_paying(player, obj)
        self._bottom_remaining(player, choice["exiled"])

    def request_discover(self, player: Player, max_mana_value: int) -> None:
        """Discover N (RULE 702.164): exile from the top until a nonland spell
        with mana value ≤ N; its controller either casts it for free **or**
        puts it into their hand (never nothing). The rest go to the bottom.

        Unlike cascade this is *not* a yes/no — it's a two-way decision, so the
        choice carries two positive options ("cast" / "hand") rather than a
        decline.
        """
        criteria = {"max_mana_value": max_mana_value}
        matched, exiled = self._exile_top_until(player, criteria, exclude_lands=True)
        if matched is None:
            self._bottom_exiled(player, exiled)
            return
        self.state.pending_choice = {
            "kind": "discover",
            "player_id": player.id,
            "optional": False,  # you must cast it or take it — never nothing
            "description": f"Discover: {matched.name}",
            "prompt": f"Discover — „{matched.name}“ kostenlos wirken oder auf die Hand?",
            "matched_id": matched.instance_id,
            "eligible": [{"instance_id": matched.instance_id, "name": matched.name}],
            "options": [
                {"id": "cast", "label": f"„{matched.name}“ kostenlos wirken",
                 "instance_id": matched.instance_id},
                {"id": "hand", "label": "Auf die Hand nehmen",
                 "instance_id": matched.instance_id},
            ],
            "exiled": [o.instance_id for o in exiled],
        }

    def resolve_discover_choice(self, to_hand: bool = False) -> None:
        """Finish a discover: cast the hit for free, or (``to_hand``) put it
        into hand. Either way the card leaves exile; bottom the rest."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "discover":
            raise ValueError("no pending discover to resolve")
        player = self.state.player_by_id(choice["player_id"])
        self.state.pending_choice = None

        matched = self._exiled_by_id(player, choice["exiled"], choice["matched_id"])
        if matched is not None:
            if to_hand:
                player.remove_from_zone(matched, Zone.EXILE)
                player.add_to_zone(matched, Zone.HAND)
            else:
                self.cast_without_paying(player, matched)
        self._bottom_remaining(player, choice["exiled"])

    def _exile_top_until(
        self, player: Player, criteria: Any, exclude_lands: bool
    ) -> tuple[Optional[GameObject], list[GameObject]]:
        """Exile cards from the top of the library until one matches ``criteria``.

        Returns the matching object (or None if the library ran out) and the
        full list exiled (the match is its last element). Lands never match
        when ``exclude_lands`` (cascade/discover want a nonland spell).
        """
        exiled: list[GameObject] = []
        matched: Optional[GameObject] = None
        while player.library:
            obj = player.library.pop()  # top of deck
            obj.zone = Zone.EXILE
            player.exile.append(obj)
            exiled.append(obj)
            self.state.fire_event(
                GameEvent(EventType.EXILE, player_id=player.id, object=obj.name, from_zone="library")
            )
            is_land = exclude_lands and obj.card.is_land
            if not is_land and card_query.matches(obj.card, criteria):
                matched = obj
                break
        return matched, exiled

    def request_name_card(
        self,
        player: Player,
        effect_specs: list[dict],
        source: Optional[GameObject],
        prompt: str = "Kartennamen wählen",
    ) -> None:
        """Open a "choose a card name" choice (RULE 701.x's naming action) —
        Demonic Consultation's opener.

        Unlike every other `pending_choice` in the engine, the answer space
        is *not* enumerable from the game state: a player may name any card
        in Magic, including one that appears nowhere in this game. So the
        offered ``options`` are a convenience list (the distinct names among
        the player's own hand, library and graveyard — which is what a real
        Consultation player is choosing between anyway), while the resolver
        accepts an **arbitrary string** and never validates the answer
        against them. Nothing derived from that string becomes behaviour: it
        is only ever compared against card names (`models.card_query`'s
        ``name``/``not_name``), never interpreted.

        ``effect_specs`` are the follow-up effects; each gets the chosen
        name substituted into any ``"named_card"`` sentinel param it carries
        (`_substitute_named_card`), the same sentinel-rewrite shape
        `_substitute_x` uses for an announced {X}.
        """
        known = {
            obj.name
            for zone in (player.hand, player.library, player.graveyard)
            for obj in zone
        }
        self._pending_name_card = {
            "player_id": player.id,
            "effect_specs": [dict(d) for d in effect_specs],
            "source": source,
        }
        self.state.pending_choice = {
            "kind": "name_card",
            "player_id": player.id,
            "prompt": prompt,
            # Suggestions only — `resolve_name_card_choice` takes any string.
            "free_text": True,
            "options": [{"id": name, "label": name} for name in sorted(known)],
        }

    def resolve_name_card_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `name_card` choice with an arbitrary card name.

        A missing/declined answer names the empty string, which matches no
        card — for Demonic Consultation that means the dig finds nothing and
        exiles the library, which is the correct (if catastrophic) outcome of
        naming a card that isn't there, not an error.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "name_card":
            raise ValueError("no pending name-a-card choice to resolve")
        self.state.pending_choice = None
        pending = self._pending_name_card
        self._pending_name_card = None
        if pending is None:
            return
        name = "" if answer is None or answer == "decline" else str(answer)
        specs = [
            {**d, "params": self._substitute_named_card(dict(d.get("params") or {}), name)}
            for d in pending["effect_specs"]
        ]
        self._apply_effect_specs(specs, pending["source"])

    @staticmethod
    def _substitute_named_card(params: dict[str, Any], name: str) -> dict[str, Any]:
        """Replace the ``"named_card"`` sentinel in a criteria dict with the
        actually-chosen name — the naming counterpart of `_substitute_x`'s
        ``"x"`` sentinel, and equally unable to misfire (a real criteria
        value is a card name, never the literal string ``"named_card"``)."""
        criteria = params.get("criteria")
        if not isinstance(criteria, dict):
            return params
        rewritten = {
            k: (name if v == "named_card" else v) for k, v in criteria.items()
        }
        return {**params, "criteria": rewritten}

    def request_look_top_pay_life_loop(
        self, player: Player, count: int = 5, life_cost: int = 1
    ) -> None:
        """Open Lim-Dûl's Vault's open-ended "as many times as you choose"
        loop — the engine's only repetition with neither a fixed count nor a
        cap, driven by a `pending_choice` that re-opens itself after each
        iteration.

        It is still bounded, by the payment rather than by a safety valve:
        each iteration costs ``life_cost`` life and the choice simply isn't
        offered once the player can't survive another (RULE 118.4 — you may
        not pay more life than you have). That is the card's own natural
        bound.
        """
        if player.life <= life_cost:
            self.shuffle_library(player)
            return
        self.state.pending_choice = {
            "kind": "look_top_pay_life",
            "player_id": player.id,
            "count": int(count),
            "life_cost": int(life_cost),
            "prompt": (
                f"{life_cost} Lebenspunkt bezahlen und die nächsten {count} Karten "
                "ansehen?"
            ),
            # The top ``count`` cards, shown so the decision is informed —
            # this is a "look at", so the information *is* the effect.
            "looking_at": [
                {"instance_id": o.instance_id, "name": o.name}
                for o in list(player.library)[-count:][::-1]
            ],
            "options": [
                {"id": "again", "label": f"{life_cost} Leben zahlen, neu ansehen"},
                {"id": "decline", "label": "Aufhören (mischen, diese Karten nach oben)"},
            ],
        }

    def resolve_look_top_pay_life_loop_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `look_top_pay_life` choice — go again (pay the
        life, bottom what you just looked at, look at the next batch) or
        stop (shuffle, then put the last batch back on top).

        Stopping shuffles *first* and replaces the batch afterwards (RULE
        701.19e's ordering, the same one `_finish_search` uses for a
        library destination) — otherwise the shuffle would scatter the very
        cards the card promises to leave on top.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "look_top_pay_life":
            raise ValueError("no pending look-top-pay-life choice to resolve")
        self.state.pending_choice = None
        player = self.state.player_by_id(choice["player_id"])
        count = int(choice["count"])
        life_cost = int(choice["life_cost"])
        batch = list(player.library)[-count:]

        if answer != "again":
            # "Then shuffle and put the last cards you looked at this way on
            # top in any order." The order here is the whole payoff — it is
            # the player's next `count` draws — so it is a real choice,
            # unlike the intermediate bottomings below (which a shuffle
            # follows, making their order unobservable).
            for obj in batch:
                player.remove_from_zone(obj, Zone.LIBRARY)
            self.shuffle_library(player)
            for obj in batch:
                obj.zone = Zone.LIBRARY
                player.library.append(obj)
            self.request_choose_objects(
                player, list(batch), "library_top", count=len(batch),
                prompt="Lege die angesehenen Karten zurück (von unten nach oben)",
            )
            return

        self.lose_life(player, life_cost, cause="cost")
        for obj in batch:
            player.remove_from_zone(obj, Zone.LIBRARY)
        for obj in batch:
            obj.zone = Zone.LIBRARY
            # Bottom, keeping their relative order: "in any order" is
            # unobservable here, since the card shuffles before anything is
            # drawn again.
            player.library.insert(0, obj)
        self.request_look_top_pay_life_loop(player, count, life_cost)

    def dig_until(
        self,
        player: Player,
        criteria: Any,
        hit_destination: str = "hand",
        rest_destination: str = "exile",
        pre_exile: int = 0,
    ) -> Optional[GameObject]:
        """Reveal cards from the top of ``player``'s library until one
        matches ``criteria``; put it at ``hit_destination`` and everything
        else revealed at ``rest_destination``.

        The generalized form of the cascade/discover dig (`_exile_top_until`,
        which is fixed to "nonland cheaper than N, hit may be cast, rest to
        the bottom"). Here both the predicate and both destinations are
        parameters, which is what lets one primitive cover Demonic
        Consultation ("until you reveal a card with the chosen name" → hand,
        rest exiled) and Tibalt's Trickery/Possibility Storm ("until a
        nonland card with a different name" / "a card that shares a card
        type with it" → free cast, rest to the bottom in a random order).

        ``pre_exile`` is Demonic Consultation's "exile the top six cards"
        prologue, which happens *before* the dig and is never part of it.

        Returns the matching object, or ``None`` if the library ran out —
        which for Demonic Consultation means the library is now empty, the
        exact state Thassa's Oracle then wins on.
        """
        for _ in range(min(pre_exile, len(player.library))):
            self.exile(player.library[-1])
        matched, revealed = self._exile_top_until(player, criteria, exclude_lands=False)
        if matched is not None and hit_destination != "exile":
            self._place_dig_hit(player, matched, hit_destination)
        rest_ids = [o.instance_id for o in revealed if o is not matched]
        if rest_destination == "library_bottom_random":
            self._bottom_remaining(player, rest_ids)
        return matched

    def _place_dig_hit(self, player: Player, obj: GameObject, destination: str) -> None:
        """Move a `dig_until` hit out of exile to its destination."""
        if destination == "cast_free":
            self.cast_without_paying(player, obj)
            return
        if destination == "cast_free_window":
            # "That player **may** cast that card without paying its mana
            # cost." — a genuine option, not a forced free cast: the same
            # exile window Rebound and Beseech the Mirror use, so the spell
            # gets its full targeting/modal choices through the ordinary
            # action loop. The card stays in exile until cast, and the
            # delayed half below performs the printed "if they don't cast
            # it" fallback at the next end step.
            self.grant_free_cast_window_from_exile(obj)
            self.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=player.id,
                    step="end",
                    scope="any",
                    effects=[ReturnUncastExiledEffect(obj, destination="library_bottom")],
                    description=f"{obj.name}: unter die Bibliothek, falls nicht gewirkt",
                )
            )
            return
        player.remove_from_zone(obj, Zone.EXILE)
        if destination == "battlefield":
            obj.zone = Zone.BATTLEFIELD
            self.state.add_to_battlefield(obj)
            return
        obj.zone = Zone.HAND
        player.add_to_zone(obj, Zone.HAND)

    def _exiled_by_id(
        self, player: Player, exiled_ids: list[int], instance_id: int
    ) -> Optional[GameObject]:
        if instance_id not in exiled_ids:
            return None
        return next((o for o in player.exile if o.instance_id == instance_id), None)

    def _bottom_exiled(self, player: Player, exiled: list[GameObject]) -> None:
        self._bottom_remaining(player, [o.instance_id for o in exiled])

    def _bottom_remaining(self, player: Player, exiled_ids: list[int]) -> None:
        """Put every still-exiled card from this effect on the bottom of the
        library in a random order (RULE 702.85e). Cards already cast/taken to
        hand are no longer in exile and are skipped."""
        import random

        remaining = [o for o in list(player.exile) if o.instance_id in set(exiled_ids)]
        random.shuffle(remaining)
        for obj in remaining:
            player.remove_from_zone(obj, Zone.EXILE)
            obj.zone = Zone.LIBRARY
            player.library.insert(0, obj)  # bottom (index 0 — see Player.library)

    def _move_to_graveyard(self, obj: GameObject, cause: Optional[str] = None) -> None:
        """Put ``obj`` into its owner's graveyard (RULE 704.5), firing the
        leave/dies triggers. ``cause="sacrifice"`` additionally fires
        `EventType.SACRIFICE` (RULE 701.17) — set only by `put_into_graveyard`,
        the single choke point every genuine sacrifice funnels through.

        Lurrus-shaped redirect first (RULE 616): this is the one function
        every graveyard-bound move funnels through regardless of cause
        (destroy, sacrifice, SBA "dies") — while `obj.cast_via_graveyard_
        cast_permission_until_turn` still matches the current turn, exile
        it instead of proceeding, per the permission source's own trailing
        "if a spell cast this way would be put into a graveyard this turn,
        exile it instead" clause (`GraveyardCastPermissionEffect.exile_
        if_would_be_put_into_graveyard`).
        """
        if obj.cast_via_graveyard_cast_permission_until_turn == self.state.turn_number:
            self.exile(obj)
            return
        was_on_battlefield = obj in self.state.battlefield
        was_creature = obj.is_creature
        owner = self.state.player_by_id(obj.owner_id)

        # RULE 616.1: a "if ~ would die, exile it instead" replacement
        # (Gloomshrieker/Corpseweaver Prodigy) intercepts a creature's
        # battlefield→graveyard move before any DIES trigger fires. Modeled
        # like regeneration's shield: the matching replacement's own fn does
        # the exile as a side effect and returns None (event consumed), so a
        # None result here means "already redirected — don't also move it to
        # the graveyard". Only fired for a creature actually leaving the
        # battlefield (RULE 700.4 "dies"); every other graveyard path is
        # untouched.
        if was_on_battlefield and was_creature:
            would_die = GameEvent(
                EventType.WOULD_DIE,
                target_id=obj.instance_id,
                controller_id=obj.controller_id,
            )
            if self.apply_replacements(would_die) is None:
                return

        if was_on_battlefield:
            # RULE 603.6a "look back in time": fire while `obj` is still on
            # the battlefield so `_collect_triggers` (which only scans
            # `state.permanents()`) finds this object's own leave/dies
            # triggers. Mirrors `GameState.add_to_battlefield`'s
            # append-then-fire ordering for SAGA_CHAPTER/CLASS_LEVEL.
            self.state.fire_event(
                GameEvent(
                    EventType.LEAVES_BATTLEFIELD,
                    object=obj.name,
                    owner_id=obj.owner_id,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
            # RULE 700.4: "dies" means "is put into a graveyard from the
            # battlefield" — for *any* permanent, not just a creature
            # (Rancor's "When this Aura dies, return it to its owner's
            # hand.", Ashiok's Reaper's "Whenever an enchantment you control
            # dies, …"). Every consumer that does mean creatures
            # specifically already narrows on the event's own
            # ``object_types`` (`effect_binder._build_group_ok`'s ``type``
            # filter, `_collect_counter_death_return_triggers`'s explicit
            # check), so widening the firing condition can't over-fire them.
            self.state.fire_event(
                GameEvent(
                    EventType.DIES,
                    object=obj.name,
                    owner_id=obj.owner_id,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                    # Snapshotted live (before `remove_from_battlefield`
                    # below): a "dies with a counter on it" trigger
                    # condition (Marchesa, the Black Rose-shaped,
                    # `_collect_counter_death_return_triggers`) needs
                    # this off the event, not a live re-lookup — the
                    # dying object may already be gone from the
                    # battlefield by the time that check runs.
                    counters=dict(obj.counters),
                    # A tribal "another nontoken Zombie or Mutant you
                    # control dies" subject filter (The Ghoul, Gunslinger,
                    # `effect_binder._build_group_ok`) needs both off the
                    # event for the same reason — the object is already
                    # gone from the battlefield by the time that check
                    # runs.
                    is_token=obj.is_token,
                    subtypes=obj.card.type_line.partition("—")[2].strip().lower().split(),
                )
            )
            if cause == "sacrifice":
                # RULE 701.17: a sacrifice both leaves/dies *and* is a
                # distinct "was sacrificed" occurrence — fire it last so a
                # dies-trigger and a sacrifice-trigger batch in that order.
                self.state.fire_event(
                    GameEvent(
                        EventType.SACRIFICE,
                        object=obj.name,
                        owner_id=obj.owner_id,
                        controller_id=obj.controller_id,
                        instance_id=obj.instance_id,
                        object_types=sorted(obj.type_words),
                    )
                )
            self.state.remove_from_battlefield(obj)
            self._detach_attachments_from(obj)

        obj.tapped = False
        obj.damage_marked = 0
        owner.add_to_zone(obj, Zone.GRAVEYARD)
        self._flag_commander_zone_choice(obj)

    def _flag_commander_zone_choice(self, obj: GameObject) -> None:
        """RULE 903.9a: a commander that just landed in a graveyard or exile
        may be moved to the command zone by its owner instead — offered once,
        as a state-based action (`_sba_pass`), not baked into the move
        itself. Marks ``obj`` eligible; the SBA consumes and clears the flag
        the moment it opens the `pending_choice`."""
        if obj.is_commander and obj.zone in (Zone.GRAVEYARD, Zone.EXILE):
            obj.commander_zone_choice_pending = True

    _COMMANDER_ZONE_LABELS = {
        Zone.GRAVEYARD: "Friedhof",
        Zone.EXILE: "Exil",
        Zone.HAND: "Hand",
    }

    def _commander_zone_choice(self, obj: GameObject, zone: str) -> dict[str, Any]:
        """Build the RULE 903.9a/9b `pending_choice` offering to move a
        commander from ``zone`` (graveyard/exile — 903.9a, already there; or
        hand — 903.9b, about to land there) into the command zone instead."""
        label = self._COMMANDER_ZONE_LABELS.get(zone, str(zone))
        return {
            "kind": "commander_zone",
            "player_id": obj.owner_id,
            "instance_id": obj.instance_id,
            "prompt": f"{obj.name}: aus {'dem' if zone != Zone.HAND else 'der'} {label} "
            "in die Kommandozone legen?",
            "options": [
                {"id": "command", "label": "In die Kommandozone legen"},
                {"id": "decline", "label": f"Im {label} bleiben"},
            ],
        }

    def resolve_commander_zone_choice(self, answer: Optional[str]) -> None:
        """Answer a pending RULE 903.9a/9b `commander_zone` choice.

        ``"command"`` moves the commander into the command zone from
        whichever zone currently holds it; anything else (``None``/
        ``"decline"``) leaves it exactly where it already is.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "commander_zone":
            raise ValueError("no pending commander-zone choice to resolve")
        self.state.pending_choice = None
        if answer != "command":
            return
        obj = self.state.find_object(choice["instance_id"])
        if obj is None:
            return
        owner = self.state.player_by_id(obj.owner_id)
        self._remove_from_current_zone(owner, obj)
        owner.add_to_zone(obj, Zone.COMMAND)

    # ------------------------------------------------------------------
    # State-based actions (RULE 704)
    # ------------------------------------------------------------------

    def check_state_based_actions(self) -> bool:
        """Apply SBAs until none apply (RULE 704.3). Returns whether any did.

        Covers the MVP subset (docs/02 R2.8): life <= 0 loss, drawing from
        an empty library loss, 0-toughness creatures, lethal marked damage,
        and the legend rule.
        """
        any_action = False
        while True:
            acted = self._sba_pass()
            if not acted:
                break
            any_action = True
        return any_action

    def _sba_pass(self) -> bool:
        # A pending_choice (e.g. the RULE 903.9a commander-zone choice just
        # below) pauses SBA processing until it's answered — mirrors the
        # guard `resolve_until_stable`/`pass_priority` already apply after
        # calling `check_state_based_actions`.
        if self.state.pending_choice:
            return False

        # Re-derive continuous effects first (RULE 613) so P/T, types and
        # granted keywords are current before any SBA reads them — an anthem
        # dropping a creature to 0 toughness must be seen here.
        continuous.recompute(self.state)

        # 702.145c/d/f/g: not itself a state-based action, but "any time" is
        # otherwise unmodeled continuous timing — checked at SBA cadence.
        if self._check_day_night():
            return True

        # RULE 702.94c: a Soulbond pair breaks the moment either creature
        # leaves the battlefield, stops being a creature, or the two stop
        # sharing a controller — swept here so none of those sites has to
        # remember to tear the pair down itself.
        if self.break_illegal_soulbond_pairs():
            return True

        # RULE 701.52d: likewise for the Ring-bearer designation — no
        # re-check needed afterwards, since dropping it can't itself change
        # anything else on the board.
        self._sweep_ring_bearer()

        # 704.5a/c: player at 0 or less life, or who drew from empty, loses.
        for player in self.state.players:
            if player.has_lost:
                continue
            drew_empty = getattr(player, "attempted_draw_from_empty", False)
            # 704.5c: 0-or-less life, drawing from empty, or 10+ poison loses.
            poisoned = player.poison >= 10
            if (player.life <= 0 or drew_empty or poisoned) and not self._loss_prevented(player):
                if player.loss_reason:
                    reason = player.loss_reason
                elif player.life <= 0:
                    reason = "life"
                elif poisoned:
                    reason = "poison"
                else:
                    reason = "draw_from_empty"
                self._player_loses(player, reason)
                return True
            # 704.5m / 903.10a: 21+ combat damage from a single commander.
            if not self._loss_prevented(player) and any(
                entry["amount"] >= 21 for entry in player.commander_damage.values()
            ):
                self._player_loses(player, "commander_damage")
                return True

        # 704.5f: creature with toughness <= 0 goes to graveyard.
        for obj in self.state.permanents():
            if obj.is_creature and obj.toughness is not None and obj.toughness <= 0:
                self._move_to_graveyard(obj)
                return True

        # 704.5i: a planeswalker with 0 loyalty is put into its owner's
        # graveyard. Only planeswalkers with a printed starting loyalty are
        # subject to this (they always enter with loyalty counters).
        for obj in self.state.permanents():
            if obj.is_planeswalker and obj.card.loyalty is not None and obj.loyalty <= 0:
                self._move_to_graveyard(obj)
                return True

        # RULE 310.11b: a Siege's intrinsic "when the last defense counter is
        # removed from this permanent, exile it, then you may cast it
        # transformed without paying its mana cost". A *triggered* ability,
        # not an SBA — but noticing the transition is what an SBA pass is
        # for, and doing it here (rather than in `deal_damage`) means every
        # route to zero defense is covered, not just damage. Placed straight
        # on the stack like `check_ward`/`check_rampage` rather than through
        # the RULE 603.3 queue, since it's built per firing; the latch stops
        # the next pass from re-firing it while it's still on the stack.
        for obj in self.state.permanents():
            if (
                obj.card.is_siege
                and obj.card.defense
                and obj.defense <= 0
                and not obj.battle_defeat_triggered
            ):
                obj.battle_defeat_triggered = True
                self._place_trigger(
                    TriggeredAbility(
                        trigger_event=EventType.BATTLE_DEFEATED,
                        effects=[SiegeDefeatedEffect(source=obj)],
                        controller_id=obj.controller_id,
                        source=obj,
                        description=f"{obj.name}: besiegt — ins Exil, dann transformiert wirken",
                    )
                )
                # Announced *after* the trigger is placed so anything else
                # watching a battle's defeat sees a stack that already holds
                # the Siege's own ability, matching RULE 603.3's ordering.
                self.state.fire_event(
                    GameEvent(
                        EventType.BATTLE_DEFEATED,
                        instance_id=obj.instance_id,
                        controller_id=obj.controller_id,
                        object=obj.name,
                    )
                )
                return True

        # RULE 310.7: a battle with 0 defense that isn't itself the source of
        # an ability which has triggered but not yet left the stack is put
        # into its owner's graveyard — the exact shape of the Saga check
        # below, and the reason a defeated Siege survives long enough for its
        # own 310.11b trigger above to exile it instead. Only battles with a
        # printed defense are subject (mirroring the loyalty check above: a
        # battle that never had defense counters was never at "0 defense" in
        # the 310.4c sense).
        for obj in self.state.permanents():
            if not (obj.is_battle and obj.card.defense and obj.defense <= 0):
                continue
            if any(item.source is obj for item in self.state.stack):
                continue
            self._move_to_graveyard(obj)
            return True

        # RULE 310.10: a battle that isn't being attacked and has no valid
        # protector gets a fresh one chosen by its controller; with no
        # eligible player at all it's put into its owner's graveyard. For the
        # only real battle type (Siege, 310.11a) "eligible" means an opponent
        # of the controller, so this is what cleans up a Siege whose
        # protector has left the game — and what makes a Siege cast in a solo
        # goldfish (no opponents at all) fall off the battlefield rather than
        # sit there unattackable forever.
        for obj in self.state.permanents():
            if not obj.is_battle or self.battle_is_being_attacked(obj):
                continue
            eligible = self._eligible_protectors(obj)
            if obj.protector_id is not None and any(p.id == obj.protector_id for p in eligible):
                continue
            if not eligible:
                self._move_to_graveyard(obj)
                return True
            # A single eligible player is no choice at all (RULE 310.10's
            # "chooses" degenerates); with several, the same auto-pick this
            # engine already makes for a non-interactive pick applies, since
            # an SBA has no window to open a `pending_choice` in.
            obj.protector_id = eligible[0].id
            return True

        # 704.5x/RULE 714.4: a Saga with lore counters >= its final chapter
        # number, and not itself the source of one of its own chapter
        # abilities that has triggered but not yet left the stack, is put
        # into its owner's graveyard. Checked against *this Saga's own*
        # chapter trigger specifically (its `StackItem.source`/
        # `trigger_event`, stamped by `_place_trigger_on_stack`) rather than
        # "is the whole stack empty" — an unrelated spell/ability sitting on
        # the stack (an opponent's instant, another permanent's trigger)
        # must not delay this Saga's own sacrifice.
        for obj in self.state.permanents():
            if not obj.card.is_saga:
                continue
            final = _saga_final_chapter(obj.card)
            if final and obj.lore >= final and not any(
                item.source is obj
                and item.trigger_event is not None
                and item.trigger_event.type == EventType.SAGA_CHAPTER
                for item in self.state.stack
            ):
                self._move_to_graveyard(obj)
                return True

        # 704.5g: creature with lethal marked damage is destroyed — or one
        # that was dealt any damage by a deathtouch source (RULE 702.2b makes
        # that lethal). Indestructible (RULE 702.12b) is destroyed by
        # neither. Routed through `destroy` (not a raw `_move_to_graveyard`)
        # so a regeneration shield (RULE 701.16) gets a chance to intercept
        # it — the classic regenerate-a-blocker use case.
        for obj in self.state.permanents():
            if not obj.is_creature or obj.toughness is None:
                continue
            if combat.has_indestructible(obj):
                continue
            lethal_marked = obj.toughness > 0 and obj.damage_marked >= obj.toughness
            if lethal_marked or (obj.dealt_deathtouch_damage and obj.damage_marked > 0):
                self.destroy(obj)
                return True

        # 704.5q: a permanent with both +1/+1 and -1/-1 counters removes an
        # equal number of each. Done before the toughness/damage checks would
        # normally settle, so a creature that nets out to 0 toughness after
        # annihilation is then caught by 704.5f on the next pass.
        for obj in self.state.permanents():
            plus = obj.counters.get("+1/+1", 0)
            minus = obj.counters.get("-1/-1", 0)
            if plus > 0 and minus > 0:
                removed = min(plus, minus)
                obj.add_counters("+1/+1", -removed)
                obj.add_counters("-1/-1", -removed)
                return True

        # 704.5j: legend rule — same-named legendaries a player controls.
        if self._apply_legend_rule():
            return True

        # 903.9a: a commander freshly landed in a graveyard or exile may be
        # moved to the command zone by its owner instead — a one-time SBA
        # offer (`_flag_commander_zone_choice` marks eligibility at the
        # moment it lands there; consumed and cleared here the instant it's
        # offered, so it isn't re-asked on every subsequent SBA pass).
        for player in self.state.players:
            for zone in (Zone.GRAVEYARD, Zone.EXILE):
                for obj in player.zones[zone]:
                    if obj.commander_zone_choice_pending:
                        obj.commander_zone_choice_pending = False
                        self.state.pending_choice = self._commander_zone_choice(obj, zone)
                        return True

        # 704.5d: a token in any zone other than the battlefield ceases to
        # exist. It *did* reach that zone (its owner's graveyard/exile/…) long
        # enough for its leaves-the-battlefield / dies triggers to have fired
        # when it was moved there — this SBA then removes it from the game, and
        # RULE 111.7-8 keep it from ever returning to another zone.
        if self._remove_stranded_tokens():
            return True

        return False

    def _remove_stranded_tokens(self) -> bool:
        """Remove any token that has left the battlefield (RULE 704.5d) —
        except a prepared copy still exempt under RULE 722.3c."""
        for player in self.state.players:
            for zone in Player.PERSONAL_ZONES:  # every non-battlefield zone
                cards = player.zones[zone]
                for obj in cards:
                    if obj.is_token and not self._is_prepared_copy(obj):
                        cards.remove(obj)
                        return True
        return False

    def _is_prepared_copy(self, obj: GameObject) -> bool:
        """RULE 722.3c: a prepared copy is exempt from the RULE 704.5d token
        cleanup for as long as its source stays on the battlefield with the
        prepared designation — the instant either stops being true (the
        source is unprepared some other way, or leaves the battlefield), the
        next SBA pass reaps the copy via `_remove_stranded_tokens` above.
        """
        if obj.prepared_source_id is None:
            return False
        source = self.state.find_object(obj.prepared_source_id)
        return source is not None and source in self.state.battlefield and source.prepared

    def _apply_legend_rule(self) -> bool:
        seen: dict[tuple[str, str], GameObject] = {}
        for obj in self.state.permanents():
            if not obj.is_legendary:
                continue
            key = (obj.controller_id, obj.name)
            if key in seen:
                # Keep the first seen, put this duplicate in the graveyard.
                self._move_to_graveyard(obj)
                return True
            seen[key] = obj
        return False

    def _loss_prevented(self, player: Player) -> bool:
        return any(
            isinstance(e, WinConditionEffect) and e.prevents_loss()
            for e in player.player_effects
        )

    def _player_loses(self, player: Player, reason: str) -> None:
        player.has_lost = True
        player.loss_reason = reason
        self.state.fire_event(
            GameEvent(EventType.PLAYER_LOST, player_id=player.id, reason=reason)
        )
        self._check_game_over()

    def concede(self, player: Player) -> None:
        """RULE 104.3a: ``player`` concedes and leaves the game immediately.

        Conceding is the one thing a player may do at *any* time, without
        holding priority — it is not an action that uses the stack, so
        unlike every other action here it isn't gated on timing.

        The RULE 800.4a cleanup (their objects leave the game with them) is
        deliberately **deferred** rather than run here, because conceding is
        in practice a sorcery-speed act and pulling a whole board out from
        under the remaining players mid-turn is disorienting: the id is
        parked on `GameState.pending_leave_ids` and swept by
        `GameEngine.begin_turn` when the next player's turn starts. Once
        only one living player is left the game is over anyway, so the
        board is simply left standing for the end-of-match review and the
        sweep never runs.
        """
        if player.has_lost:
            return
        self._player_loses(player, "conceded")
        if not self.state.game_over and player.id not in self.state.pending_leave_ids:
            self.state.pending_leave_ids.append(player.id)

    def remove_player_from_game(self, player: Player) -> None:
        """RULE 800.4a: every object a departing player owns leaves the game.

        Their permanents (and anything they control that they don't own —
        RULE 800.4a hands those back, but with no exchange-of-control
        modeled at this level the simple reading is used: only *owned*
        objects go) leave the battlefield, their personal zones empty, and
        anything of theirs still on the stack ceases to exist. Called by
        `GameEngine.begin_turn` for each id `concede` parked on
        `GameState.pending_leave_ids`, not directly by the concession.
        """
        for obj in [o for o in self.state.battlefield if o.owner_id == player.id]:
            self.state.remove_from_battlefield(obj)
        self.state.stack = [
            item for item in self.state.stack if getattr(item.source, "owner_id", None) != player.id
        ]
        for zone in Player.PERSONAL_ZONES:
            player.zones[zone].clear()

    def player_wins(self, player: Player) -> None:
        """RULE 104.2: ``player`` wins the game outright (Jace, Wielder of
        Mysteries/Laboratory Maniac-shaped alternative win condition) —
        every other living player loses, the same "someone wins" case a
        solo/2-player match already reduces to via `_player_loses`. Fires
        no separate "won" event of its own today (no card needs one); the
        derived `GameState.game_over`/`winner_id` `_check_game_over` sets
        is the externally-visible signal, same as any other win/loss path.
        A solo (1-player) match has no "other player" to lose, so the
        win/game-over state is set directly instead.
        """
        for other in list(self.state.living_players()):
            if other is not player:
                self._player_loses(other, "opponent_won")
        if len(self.state.players) == 1:
            self.state.game_over = True
            self.state.winner_id = player.id
        else:
            self._check_game_over()

    def _check_game_over(self) -> None:
        living = self.state.living_players()
        if len(self.state.players) > 1 and len(living) <= 1:
            self.state.game_over = True
            self.state.winner_id = living[0].id if living else None

    # ------------------------------------------------------------------
    # Phase-skip helper (RULE overrides, docs/07 PART 8)
    # ------------------------------------------------------------------

    def should_skip_step(self, player: Player, step_name: str) -> bool:
        for effect in player.player_effects:
            if isinstance(effect, StaticEffect) and effect.skips_step(step_name):
                if effect.duration == "once":
                    effect.active = False
                return True
        return False
