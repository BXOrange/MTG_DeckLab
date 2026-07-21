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
from typing import Any, Callable, Optional

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
    AddCountersEffect,
    BecomeMonarchEffect,
    CantBeCounteredEffect,
    ChooseColorReplacement,
    ChooseCreatureTypeReplacement,
    DrawCardEffect,
    GameContext,
    ImpulsiveDrawEffect,
    MarchesaDelayedReturnEffect,
    PumpEffect,
    ReboundFreeCastWindowEffect,
    ReplacementEffect,
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
        self._collect_counter_death_return_triggers(event)

    def _collect_inherent_triggers(self, event: GameEvent) -> None:
        """RULE 725.2/726.2: the Monarch's and the Initiative's triggered
        abilities "have no source" — they aren't attached to any permanent,
        so the object scan above can never find them. Built fresh here
        instead, each time a matching event fires, since who currently holds
        either designation (and so who controls the ability) can change
        turn to turn; RULE 726.2's "venture into the dungeon" trigger isn't
        modeled (dungeons/RULE 309 aren't built yet — see
        `TakeInitiativeEffect`'s docstring).
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
        return [
            spec
            for effect in effects
            for spec in [getattr(effect, "target_spec", None)]
            if spec is not None
        ]

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
                    self._place_trigger(ability, targets=[obj])
                continue
            if ability.modes:
                self._pending_trigger_ability = ability
                self._pending_trigger_queue = queue
                self.state.pending_choice = self._trigger_mode_choice(ability)
                return
            if not self._place_or_pause_trigger(ability, ability.effects, queue):
                return

    def _place_or_pause_trigger(
        self,
        ability: "TriggeredAbility",
        effects: list[Any],
        queue: list[tuple["TriggeredAbility", GameEvent]],
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
                self._place_trigger(ability, effects_override=override)
                return True
            # RULE 603.5: a "you may" with no target still needs a choice
            # of whether to do it at all.
            self._pending_trigger_ability = ability
            self._pending_trigger_effects = override
            self._pending_trigger_queue = queue
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
                return True  # RULE 603.3c: no legal target — never placed
            self._pending_trigger_ability = ability
            self._pending_trigger_effects = override
            self._pending_trigger_queue = queue
            self.state.pending_choice = self._trigger_target_choice(ability, options)
            return False
        # RULE 115.1/603.3c generalized: 2+ *different* targeting effects —
        # gather one target per effect, one choice at a time (mirrors
        # `_trigger_mode_choice`'s "pick up to N, one at a time"), then place
        # with `target_groups` so each effect resolves against its own pick.
        return self._continue_trigger_multi_target(ability, override, queue, specs, [])

    def _continue_trigger_multi_target(
        self,
        ability: "TriggeredAbility",
        override: Optional[list[Any]],
        queue: list[tuple["TriggeredAbility", GameEvent]],
        specs: list[TargetSpec],
        groups: list[list[Any]],
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
            self._place_trigger(ability, target_groups=groups, effects_override=override)
            return True
        spec = specs[idx]
        controller_id = ability.controller_id or self.state.active_player.id
        options = legal_targets(self.state, controller_id, spec, source=ability.source)
        if not options:
            if spec.optional:
                return self._continue_trigger_multi_target(
                    ability, override, queue, specs, groups + [[]]
                )
            return True  # RULE 603.3c: no legal target — never placed
        self._pending_trigger_ability = ability
        self._pending_trigger_effects = override
        self._pending_trigger_queue = queue
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

        options = (ability.modes or []) if ability is not None else []
        if ability is None or not options:
            self.state.pending_choice = None
            self._pending_trigger_ability = None
            self._pending_trigger_queue = []
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
        if self._place_or_pause_trigger(ability, effects, queue):
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
        self._pending_trigger_ability = None
        self._pending_trigger_queue = []
        self._pending_trigger_effects = None

        if answer == "do":
            if ability is not None:
                self._place_trigger(ability, effects_override=effects_override)
            self._place_triggers(queue)
            return

        if answer is not None and answer != "decline" and ability is not None:
            target = self._resolve_choice_option(choice["options"], str(answer))
            if target is not None:
                self._place_trigger(ability, targets=[target], effects_override=effects_override)
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
        self._pending_trigger_ability = None
        self._pending_trigger_queue = []
        self._pending_trigger_effects = None
        self._pending_trigger_specs = []
        self._pending_trigger_groups = []

        if answer is not None and answer != "decline" and ability is not None:
            target = self._resolve_choice_option(choice["options"], str(answer))
            groups = groups + [[target] if target is not None else []]
            if self._continue_trigger_multi_target(ability, effects_override, queue, specs, groups):
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
        self._remove_from_current_zone(player, obj)
        obj.zone = Zone.STACK
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
                free=True,
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
        """
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
        kind = self._attachment_kind(obj)
        if kind is None:
            return False
        if kind == "equip":
            return target.is_creature or target.card.is_artifact
        if kind == "reconfigure":
            return target.is_creature and target is not obj
        if kind == "fortify":
            return target.is_land
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

    def resolve_top_of_stack(self) -> Optional[StackItem]:
        """Resolve the topmost stack object (RULE 608). Returns it, or None."""
        if not self.state.stack:
            return None
        item = self.state.stack.pop()  # LIFO

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
            group_index = 0
            for effect in item.effects:
                if item.target_groups is not None and getattr(effect, "target_spec", None) is not None:
                    # RULE 115.1/601.2c: this effect gets only *its own*
                    # slice of the partitioned targets, not the whole shared
                    # list — see `StackItem.target_groups`.
                    group = (
                        item.target_groups[group_index]
                        if group_index < len(item.target_groups)
                        else []
                    )
                    group_index += 1
                    effect.apply(self.context, group)
                else:
                    effect.apply(self.context, item.targets)

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
            obj.summoning_sick = True
            # RULE 614.1: either the object's own printed tapped-entry
            # clause, or a *different* permanent's board-wide standing
            # effect ("Artifacts your opponents control enter tapped." —
            # Manglehorn/Dauntless Dismantler/Archon of Emeria-shaped).
            obj.tapped = ability_catalogue.enters_tapped(obj.card) or continuous.enters_tapped_from_static(
                self.state, obj
            )
            self._apply_entry_counters(obj, x_paid=getattr(obj, "x_paid", 0) or 0)
            self.state.add_to_battlefield(obj)
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

        def _after_copy_choice() -> None:
            # RULE 601.2b: a "choose a creature type/color" pick (if any)
            # also happens before the object is added to the battlefield —
            # after the enter-as-copy choice (a copy takes on the copied
            # permanent's text, so its own "as ~ enters" clauses, if any,
            # are what should be offered — no real card in the pool combines
            # both, so the ordering is for correctness-in-principle only).
            self._offer_enter_choices(obj, _finish)

        if obj.enter_as_copy_effects:
            self._offer_enter_as_copy(obj, _after_copy_choice)
        else:
            _after_copy_choice()

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
        if not choice or choice.get("kind") not in ("choose_creature_type", "choose_color"):
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
            else:
                obj.chosen_color = chosen
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
        for _ in range(count):
            if not player.library:
                break
            obj = player.library.pop()
            obj.zone = Zone.GRAVEYARD
            player.graveyard.append(obj)
            self._flag_commander_zone_choice(obj)  # RULE 903.9a (rare: a commander milled from the library)
        self.state.fire_event(GameEvent(EventType.MILL, player_id=player.id, count=count))

    def discard(self, player: Player, count: int = 1) -> None:
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
            elif getattr(target, "is_planeswalker", False):
                # RULE 306.9: damage to a planeswalker removes that many
                # loyalty counters (the 0-loyalty SBA then sends it to the
                # graveyard).
                target.add_counters("loyalty", -final)
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
        event.
        """
        if amount <= 0:
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

    def add_mana_any_color(self, player: Player) -> None:
        """Open the interactive colour choice for a resolve-time "add one
        mana of any color" effect (RULE 106.4) — e.g. Deathrite Shaman's
        graveyard-exile ability, which targets and so can never be a
        `mana_abilities.py` mana ability at all (RULE 605.1a excludes any
        ability that requires a target), unlike an ordinary dual land's
        pre-declared tap-for-mana choice.

        Opens an `add_mana_any_color` `pending_choice`;
        `resolve_add_mana_any_color_choice` finishes it by adding one mana
        of the chosen colour to ``player``'s pool.
        """
        self.state.pending_choice = {
            "kind": "add_mana_any_color",
            "player_id": player.id,
            "prompt": "Farbe für die Manaerzeugung wählen",
            "options": [
                {"id": color, "label": label}
                for color, label in self._ANY_COLOR_LABELS.items()
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
        color = answer if answer in self._ANY_COLOR_LABELS else "W"
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
        """Add a lore counter to each Saga ``player`` controls (RULE 714.2b).

        Called after the controller's draw step. Fires `SAGA_CHAPTER` so a
        chapter ability whose number the new count reaches goes on the stack
        through the normal triggered-ability pipeline (RULE 714.2d). The
        0-chapter-remaining Saga is sacrificed by a state-based action
        (`_sba_pass`), so this only advances the chapter here."""
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

    def gain_life(self, player: Player, amount: int) -> None:
        if amount <= 0:
            return
        player.gain_life(amount)
        self.state.fire_event(
            GameEvent(EventType.LIFE_GAINED, player_id=player.id, amount=amount)
        )

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
        if caster is None or not self._can_pay_ward_cost(caster, cost):
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

    def _can_pay_ward_cost(self, player: Player, cost: ActivationCost) -> bool:
        """Whether ``player`` can pay a ward cost (RULE 702.21).

        The same per-component affordability checks
        `GameEngine._can_pay_activation_cost` uses for an activated
        ability's cost, minus the tap/untap-source and remove-counters
        components — those are tied to a specific permanent's own state,
        which doesn't apply here: a ward cost is always paid from the
        caster's own resources (mana, life, hand, permanents they control),
        never "this permanent".
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

    def _pay_ward_cost(self, player: Player, cost: ActivationCost) -> None:
        """Charge ``player`` a ward cost's components (RULE 702.21) — reuses
        the same per-kind payment primitives `GameEngine.activate_ability`
        charges an activated ability's cost with."""
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
                self._pay_ward_cost(caster, cost)
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
        if spec.get("kind") == "planeswalker":
            obj = self.state.find_object(spec["instance_id"])
            if obj is None:
                return None
            try:
                return self.state.player_by_id(obj.controller_id)
            except KeyError:
                return None
        return None

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
        )

    def _search_zone_objects(self, player: Player, zones: list[str]) -> list[GameObject]:
        """The combined pool of cards a (possibly multi-zone) search draws
        from, library before graveyard when both are searched."""
        objs: list[GameObject] = []
        if "library" in zones:
            objs.extend(player.library)
        if "graveyard" in zones:
            objs.extend(player.graveyard)
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
            )
            return

        self.state.pending_choice = None
        self._finish_search(
            player, found, choice["destination"],
            zones=zones, destinations=choice.get("destinations"),
            exile_rest=choice.get("exile_rest", False),
            criteria=choice["criteria"],
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
            {"library": "Bibliothek", "graveyard": "Friedhof"}[z] for z in zones
        )
        prompt = f"Suche in {zone_label} nach: {description}"
        if count > 1:
            prompt += f" (noch {count - len(found)})"
        return {
            "kind": "search",
            "player_id": player.id,
            "destination": destination,
            "destinations": list(destinations) if destinations else None,
            "zones": zones,
            "exile_rest": exile_rest,
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
        effective_destinations = [
            dest_list[i] if i < len(dest_list) else destination
            for i in range(len(chosen))
        ]

        shuffle = "library" in zones and not exile_rest
        # "Shuffle, then put on top/bottom" (RULE 701.19e for a library
        # destination): the found card must land *after* the shuffle, so its
        # position is known — otherwise the shuffle would move it.
        to_library = any(d in ("library_top", "library_bottom") for d in effective_destinations)
        if shuffle and to_library:
            self.shuffle_library(player)
        for obj, dest in zip(chosen, effective_destinations):
            self._put_searched_card(player, obj, dest)
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

    def grant_rebound_free_cast_window(self, obj: GameObject) -> None:
        """RULE 702.88b: open ``obj``'s (already-exiled) "cast it without
        paying its mana cost" window through the rest of its controller's
        current upkeep — reuses `_grant_temp_play_permission`'s same-
        turn-only temp-cast permission (so `can_cast`/`cast_spell` already
        know how to let it be cast from exile) plus `GameState.free_cast_
        instance_ids` to also zero its mana cost. Called by
        `ReboundFreeCastWindowEffect` when a Rebound delayed trigger fires.
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
        the single choke point every genuine sacrifice funnels through."""
        was_on_battlefield = obj in self.state.battlefield
        was_creature = obj.is_creature
        owner = self.state.player_by_id(obj.owner_id)

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
            if was_creature:
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

        # 704.5x: a Saga with lore counters >= its final chapter number and no
        # chapter ability of it on the stack is put into its owner's graveyard.
        for obj in self.state.permanents():
            if not obj.card.is_saga:
                continue
            final = _saga_final_chapter(obj.card)
            if final and obj.lore >= final and not self.state.stack:
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
