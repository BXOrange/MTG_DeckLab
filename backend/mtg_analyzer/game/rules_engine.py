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

from ..models.cards import card_query
from ..models.cards.card import Card
from ..models.game.emblem import Emblem
from ..models.game.events import EventType, GameEvent
from ..models.game.game_object import GameObject, Zone
from ..models.game.game_state import DelayedTrigger, GameState, StackItem
from ..models.mana.mana_cost import ManaCost
from ..models.game.player import Player
from ..parser.oracle.catalogue.keywords import parse_keywords
from ..parser.oracle.catalogue.saga import all_chapter_numbers
from . import (
    card_registry, combat, continuations, continuous, copy_mechanics,
    dungeons, face_down, variants,
)
from .combat import is_protected_from
from .costs import DISCARD_HAND, ActivationCost, parse_activation_cost
from .mana_abilities import restriction_predicate_for_cast
from .effects.core import (
    _apply_effects_partitioned,
    AddCountersEffect,
    CompleteDungeonEffect,
    VentureIntoTheDungeonEffect,
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
from .targeting import TargetSpec, collapse_groups, expand_counts, legal_targets
from .rules.casting_mixin import CastingResolutionMixin
from .rules.copies_mixin import CopiesMixin
from .rules.damage_death_mixin import DamageDeathMixin
from .rules.draw_discard_mixin import DrawDiscardMixin
from .rules.mana_counters_mixin import ManaCountersMixin
from .rules.misc_mixin import MiscSystemsMixin
from .rules.sba_mixin import StateBasedActionsMixin
from .rules.search_mixin import SearchMixin
from .rules.triggers_mixin import TriggerCollectionMixin

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
    if what == "planeswalker":
        return obj.card.is_planeswalker
    if what == "battle":
        return obj.card.is_battle
    if what == "nontoken_creature":
        # RULE 111.8/701.17: "each player sacrifices a nontoken creature of
        # their choice" (Accursed Marauder/Liliana, Dreadhorde General's own
        # -4 — the edict family's most common creature-type qualifier).
        return obj.is_creature and not obj.is_token
    if what == "artifact_or_creature":
        # Deadly Dispute/Costly Plunder-shaped "sacrifice an artifact or
        # creature" additional cost.
        return obj.is_creature or obj.card.is_artifact
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


class RulesEngine(
    TriggerCollectionMixin,
    CastingResolutionMixin,
    DrawDiscardMixin,
    DamageDeathMixin,
    ManaCountersMixin,
    CopiesMixin,
    SearchMixin,
    StateBasedActionsMixin,
    MiscSystemsMixin,
):
    """Applies MTG rules to a `GameState`.

    Split into nine per-responsibility mixins (ENG-21) under `game/rules/`
    — this class itself keeps only `__init__` and the replacement-effect
    core (RULE 616), its own central entry point rather than one
    responsibility among several. Every mixin shares this same instance
    state (`self.state`, `self.context`, the `_pending_*` fields below).
    """

    def __init__(self, state: GameState) -> None:
        self.state = state
        self.context = GameContext(state, self)
        #: Triggered abilities that fired and are waiting to be put on the
        #: stack (RULE 603.3 — after the current action, before priority).
        self.pending_triggers: list[tuple[TriggeredAbility, GameEvent]] = []
        #: RULE 701.30b: the opponent the most recent `clash` was "with" —
        #: `effects.ClashEffect` reads it into `GameContext.clashed_opponent`
        #: for a "that player" referent in the win/otherwise branch.
        self._last_clash_opponent_id: Optional[str] = None
        #: RULE 706: the kept natural results (and their sum) of the most
        #: recent `roll_die` call — `effects.RollDieEffect` reads them into
        #: `GameContext.die_results`/`die_result` for a results table or a
        #: following "where X is the result" clause. Plain state, so it
        #: survives a `GameState.clone()`/undo like `_last_clash_opponent_id`.
        self._last_die_roll_results: list[int] = []
        self._last_die_roll_total: int = 0
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
        #: RULE 603.2d: the paid trigger doubler (`TriggerDoublerEffect.tap_cost`) whose
        #: `trigger_doubler_tap` choice is open — the firing, the queue behind it, the
        #: doubler's holder/effect and the permanents picked to tap so far.
        self._pending_doubler_tap: Optional[dict[str, Any]] = None
        self._pending_trigger_ability: Optional[TriggeredAbility] = None
        self._pending_trigger_queue: list[tuple[TriggeredAbility, GameEvent]] = []
        self._pending_trigger_effects: Optional[list[Any]] = None
        #: The `GameEvent` that fired the paused trigger — carried across the
        #: pause so `_place_trigger` can still stamp it onto the `StackItem`
        #: (`StackItem.trigger_event`) after the player answers, exactly as it
        #: would have for a trigger that never paused.
        self._pending_trigger_event: Optional[GameEvent] = None
        #: RULE 603.3d + 603.5 ("Whenever `<event>`, **you may** exchange
        #: control of this creature and **that spell**." — Perplexing
        #: Chimera): a reflexive trigger's target is baked in at fire time
        #: (never a RULE 115 choice), so its own "you may" pauses on
        #: `_trigger_may_choice` with this carrying the already-resolved
        #: object across the pause, the same role `_pending_trigger_event`
        #: plays for the event.
        self._pending_trigger_reflexive_target: Optional[GameObject] = None
        #: Populated only while a `trigger_target_multi` choice is pending
        #: (2+ *different* targeting effects on one trigger, RULE 115.1) —
        #: every spec (`_trigger_target_specs`) and the groups gathered for
        #: it so far, one at a time; see `_continue_trigger_multi_target`/
        #: `_resume_trigger_target_multi`.
        self._pending_trigger_specs: list[TargetSpec] = []
        self._pending_trigger_groups: list[list[Any]] = []
        #: How those specs map back onto the *original* requirements when one
        #: wanting N targets was expanded into a round each
        #: (`targeting.expand_counts`); ``None`` when nothing was expanded.
        self._pending_trigger_spans: Optional[list[int]] = None
        #: The shock land currently awaiting a `land_tapped` pay-life choice
        #: (RULE 614.1), and how much life it costs to keep it untapped —
        #: populated only while that choice is pending.
        self._pending_land_choice_obj: Optional[GameObject] = None
        self._pending_land_choice_amount: int = 0
        #: MEC-108: the "put your choice of a flying counter or a lifelink counter"
        #: effect awaiting its kind pick — see `RulesEngine._request_counter_kind_choice`.
        self._pending_counter_kind: Optional[dict[str, Any]] = None
        #: PAR-102: the "gains your choice of <keyword>, <keyword>, or <keyword>" pump awaiting its pick —
        #: see `RulesEngine._request_keyword_choice`.
        self._pending_keyword_choice: Optional[dict[str, Any]] = None
        #: PAR-140: the "put a counter on a creature you control" pick awaiting its recipient —
        #: see `RulesEngine._request_counter_recipient_choice`.
        self._pending_counter_recipient: Optional[dict[str, Any]] = None
        #: Backing state for an optional "exile this card. If you do, …"
        #: resolution.  Unlike an activation cost the source can already be
        #: in a graveyard when this is offered (Greenwarden of Murasa), so it
        #: deliberately has its own zone-aware primitive.
        self._pending_exile_source_then: Optional[dict[str, Any]] = None
        #: Backing state for a `_request_each_player_pay_or` mass sweep
        #: (PAR-13's "each player loses N life unless they `<pay cost>`" —
        #: Bellowing Mauler/Lim-Dûl's Hex/Tomb of Annihilation's own two
        #: dungeon rooms): the still-to-ask player ids, chained one
        #: `pay_cost_then` choice at a time; see `_advance_each_player_pay_or`.
        self._pending_each_player_pay_or: Optional[dict[str, Any]] = None
        #: Backing state for a `_request_all_players_decline_or` mass sweep
        #: (Rhystic Circle's "Any player may pay {1}. If no one does,
        #: `<effect>`." — RULE 118.3-adjacent, MEC-30): the still-to-ask
        #: player ids, chained one `all_decline_or` choice at a time — the
        #: *aggregate-outcome* mirror of `_pending_each_player_pay_or`
        #: above (that one applies its effect once **per decliner**; this
        #: one applies it once, only if **every** player declined, and the
        #: first player to actually pay cancels the whole sweep with no
        #: effect at all). See `_request_all_players_decline_or`/
        #: `_advance_all_decline_or`/`_resume_all_decline_or`.
        self._pending_all_decline_or: Optional[dict[str, Any]] = None
        #: Backing state for a `_request_vote` APNAP sweep (RULE 701.38 —
        #: "starting with you, each player votes for `<A>` or `<B>`."): the
        #: still-to-ask player ids, the running per-option tally, and the
        #: serialized outcome specs (a `majority` winner/tie branch, or a
        #: `per_vote` set of magnitude-scaled effect lists). Chained one
        #: `vote` choice at a time, the same shape as
        #: `_pending_all_decline_or`. See `_request_vote`/`_advance_vote`/
        #: `_resume_vote`/`_tally_and_apply_vote`.
        self._pending_vote: Optional[dict[str, Any]] = None
        #: MEC-46: backing state for a `_request_object_vote` APNAP sweep
        #: (RULE 701.38 — "each player votes for a nonland permanent you
        #: don't control" / "…a card in your graveyard", then "exile /
        #: return each `<object>` with the most votes or tied for most
        #: votes"): the still-to-ask player ids, the candidate object ids,
        #: a per-object-id tally, and the outcome verb. Chained one
        #: `vote_object` choice at a time, the tally-over-objects sibling of
        #: `_pending_vote`. See `_request_object_vote`/`_advance_object_vote`/
        #: `_resume_vote_object`/`_tally_and_apply_object_vote`.
        self._pending_object_vote: Optional[dict[str, Any]] = None
        #: Backing state for a `_request_villainous_choice` APNAP sweep (RULE
        #: 701.55 — "`<player>` faces a villainous choice — `<A>`, or
        #: `<B>`."): a FIFO ``rounds`` queue of ``{facing_id, option_a,
        #: option_b, labels, captured}`` dicts plus the ``current`` one
        #: being asked. Each facing player picks and applies their *own*
        #: choice (unlike `_pending_vote`, which tallies everyone's and
        #: applies one aggregate outcome). A flat "each opponent" sweep
        #: builds one round per id sharing the option bodies; MEC-52's
        #: per-target form (Hunted by The Family) queues distinct bodies /
        #: RULE 608.2 referents per round. Chained one `villainous_choice`
        #: choice at a time. See `_request_villainous_choice`/
        #: `_advance_villainous_choice`/`_resume_villainous_choice`.
        self._pending_villainous: Optional[dict[str, Any]] = None
        #: Backing state for a `name_card` `pending_choice` (Demonic
        #: Consultation's "choose a card name") — the follow-up effects the
        #: chosen name gets substituted into; see `_request_name_card`/
        #: `_resume_name_card`.
        self._pending_name_card: Optional[dict[str, Any]] = None
        #: Backing state for an `impulsive_look` `pending_choice` whose clause
        #: carries an else-branch ("If you don't put a card onto the
        #: battlefield this way, <body>." — The Joiner of Cats): the source
        #: object + serialized `EffectSpec` dicts, kept off `state.pending_
        #: choice` (non-serializable), the same split `_pending_name_card`
        #: uses. See `_request_impulsive_look`/`_resume_impulsive_look`.
        self._pending_impulsive_look: Optional[dict[str, Any]] = None
        #: Backing state for a `pay_energy_then` `pending_choice` (Aether
        #: Chaser-shaped "you may pay {E}{E}. If you do, …") — see
        #: `_request_pay_energy_then`/`_resume_pay_energy_then`.
        self._pending_pay_energy: Optional[dict[str, Any]] = None
        #: A replacement chain awaiting an interactive `replacement_order`
        #: choice (RULE 616.1e/f — 2+ simultaneously-applicable replacement
        #: effects), and the continuation to resume once it's answered.
        #: Populated only while that choice is pending; see
        #: `apply_replacements`/`_resume_replacement_order`.
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
        #: `_resume_enter_as_copy`.
        self._pending_enter_as_copy_obj: Optional[GameObject] = None
        self._pending_enter_as_copy_effect: Optional[Any] = None
        self._pending_enter_as_copy_continuation: Optional[Callable[[], None]] = None
        #: The permanent currently awaiting an "as ~ enters, choose a
        #: creature type/color" pick (RULE 601.2b — `enter_choice_effects`),
        #: which of its queued choice-effects is open, and the continuation
        #: to resume once it's answered (which may itself open the *next*
        #: queued choice, if the card has more than one) — populated only
        #: while that choice is pending; see `_offer_enter_choices`/
        #: `_resume_choose_creature_type`.
        self._pending_enter_choice_obj: Optional[GameObject] = None
        self._pending_enter_choice_effect: Optional[Any] = None
        self._pending_enter_choice_continuation: Optional[Callable[[], None]] = None
        #: The card just exiled by `exile_until_duplicate_name` (Tainted
        #: Pact) awaiting a "take it or keep digging" answer, its owner, and
        #: the growing "names seen this resolution" set to resume with —
        #: populated only while that choice is pending; see
        #: `_resume_tainted_pact`.
        self._pending_tainted_pact_obj: Optional[GameObject] = None
        self._pending_tainted_pact_player: Optional[Player] = None
        self._pending_tainted_pact_seen: Optional[set] = None
        #: Transmute Artifact's own three-stage bespoke sequence (sacrifice
        #: → search → optional pay-the-difference) — the player, the
        #: sacrificed artifact's mana value, the found card awaiting a
        #: payment answer, and the `ActivationCost` it would take — each
        #: populated only while its matching stage's `pending_choice` is
        #: open; see `RulesEngine.transmute_artifact` and its three
        #: `resolve_transmute_*_choice` methods.
        self._pending_transmute_player: Optional[Player] = None
        self._pending_transmute_sacrificed_mv: Optional[int] = None
        self._pending_transmute_found_obj: Optional[GameObject] = None
        self._pending_transmute_cost: Optional[Any] = None
        #: A permanent spell carrying `GameObject.enter_or_graveyard_discard_
        #: land` (RULE 614.12, "if ~ would enter, you may discard a land
        #: card instead. If you do, put it onto the battlefield. If you
        #: don't, put it into its owner's graveyard." — Mox Diamond), and the
        #: battlefield-entry continuation to resume if the cost is paid —
        #: populated only while that choice is pending, ahead of every other
        #: entry choice (if it's declined, none of them matter — the object
        #: never becomes a permanent at all); see `_offer_enter_or_graveyard`/
        #: `_resume_enter_or_graveyard`.
        self._pending_enter_or_graveyard_obj: Optional[GameObject] = None
        self._pending_enter_or_graveyard_continuation: Optional[Callable[[], None]] = None
        #: The battle currently awaiting its RULE 310.8a/310.11a "choose a
        #: player to protect it" pick, and the battlefield-entry
        #: continuation to resume once it's answered — populated only while
        #: that choice is pending; see `_offer_protector_choice`/
        #: `_resume_choose_protector`.
        self._pending_protector_obj: Optional[GameObject] = None
        self._pending_protector_continuation: Optional[Callable[[], None]] = None
        #: A Saga with Read Ahead (RULE 702.155/714.3b) awaiting its "choose a
        #: number from 1 to this Saga's final chapter number" pick, and the
        #: battlefield-entry continuation to resume once it's answered —
        #: populated only while that choice is pending; see
        #: `_offer_read_ahead`/`_resume_read_ahead`. The chosen count
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
        #: `_resume_counter_unless_pays`.
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
        #: see `resolve_ward_effect`/`_resume_ward`.
        #: The "sacrifice ~ unless you pay `<cost>`" choice currently awaiting
        #: an answer (`_request_sacrifice_unless_pay`/
        #: `_resume_sacrifice_unless_pay`) — the permanent at stake,
        #: whose controller is being asked, and the `ActivationCost`. Only one
        #: can be pending at a time (like every other `pending_choice`); a
        #: second upkeep trigger simply waits its turn on the stack.
        self._pending_sacrifice_unless_pay: Optional[dict[str, Any]] = None
        #: The "destroy ~ unless you pay `<cost>`" choice currently awaiting
        #: an answer (`_request_destroy_unless_pay`/
        #: `_resume_destroy_unless_pay`) — the RULE 701.16 real-
        #: destruction sibling of `_pending_sacrifice_unless_pay` above (a
        #: regeneration shield can still save this one).
        self._pending_destroy_unless_pay: Optional[dict[str, Any]] = None
        #: RULE 103.6: the opening-hand card awaiting a "begin the game
        #: somewhere else" answer (`offer_opening_hand_battlefield_choice`/
        #: `_resume_opening_hand_battlefield` — battlefield or
        #: graveyard, per its own `PregameSetupPermission.destination`) —
        #: only one can be pending at a time, same as every other
        #: `pending_choice`.
        self._pending_opening_hand_obj: Optional[GameObject] = None
        self._pending_ward_item: Optional[StackItem] = None
        self._pending_ward_caster_id: Optional[str] = None
        self._pending_ward_cost: Optional[ActivationCost] = None
        #: The permanent/player awaiting a `remove_counters_amount`/
        #: `remove_counters_kind` choice (RULE 122 — "remove up to N
        #: counters from target permanent"), and how many are still left to
        #: remove once the amount is settled and a per-kind choice is
        #: underway — populated only while one of those choices is pending;
        #: see `_request_remove_counters_choice`/`_continue_remove_counters`.
        self._pending_remove_counters_target: Optional[Union[GameObject, Player]] = None
        self._pending_remove_counters_remaining: int = 0
        # Collect triggers for every event the game fires.
        state.subscribe(self._collect_triggers)
        # RULE 702.55: Haunt abilities function from exile, but only for the
        # creature instance their source is currently haunting.
        state.subscribe(self._collect_haunt_triggers)
    def open_choice(self, choice: dict[str, Any]) -> None:
        """ENG-35: suspend and ask. The other half of `resolve_choice`.

        Every ``pending_choice`` is opened through here so that one
        invariant holds by construction: **a choice may only be asked if
        something can answer it.** Scroll Rack (MEC-43 round 4F) shipped
        without that invariant — it opened a ``"scroll_rack"`` choice that
        the old ``if kind == …`` cascade had no branch for, so the answer
        fell through to the *search* resolver and raised. The board could
        reach a state no input could leave. Only a test calling the private
        resolver directly kept that off anyone's radar.

        Raising here rather than at answer time is deliberate: it fails at
        the point the bug actually is (the ask), while the state is still
        recoverable, instead of stranding a live game on an unanswerable
        prompt.
        """
        kind = choice.get("kind")
        if kind not in continuations.CHOICE_HANDLERS:
            raise ValueError(
                f"refusing to open an unanswerable choice: no continuation "
                f"registered for kind {kind!r} (see game/continuations.py)"
            )
        self.state.pending_choice = choice

    def resolve_choice(self, answer: Any = None) -> None:
        """ENG-35: answer the open choice and resume. **The** continuation.

        This is the general "ask the player and resume" `14_` §3 found
        missing — the reason 97 of this class's 254 public methods were
        `request_*`/`resolve_*_choice` pairs, one hand-written syscall per
        blocking question, dispatched by a 368-line ``if kind == …`` cascade.

        ``answer`` is the chosen option's ``id`` as the client sends it (a
        string), or ``None``/``"decline"`` to decline. The registered
        `game/continuations.py` handler for the pending choice's ``kind``
        says how to read it; `coerce_answer` does the reading, so a caller
        never has to know whether a given kind wants an int, a string or a
        yes/no flag.

        Three things happen here that used to be repeated in every resolver:
        the pending choice is **claimed** (checked, then cleared *before* the
        handler runs, so a handler that re-opens a choice — a multi-pick
        loop, a two-stage search — simply opens a fresh one), the answer is
        **coerced**, and an unknown kind **fails closed**. It deliberately
        does *not* resolve the stack afterwards: `GameEngine.resolve_pending_
        choice` is the client-facing entry point and owns that step, so the
        rules-level primitive stays a single step the way every other
        `RulesEngine` method is.
        """
        choice = self.state.pending_choice
        if not choice:
            raise ValueError("no pending choice to resolve")
        kind = choice.get("kind")
        handler = continuations.CHOICE_HANDLERS.get(kind)
        if handler is None:
            # Fail closed rather than guessing. The old cascade's ``else``
            # branch sent every unrecognized kind to the *search* resolver,
            # which is how ``"scroll_rack"`` came to be unanswerable in a
            # live game (MEC-43 round 4F opened the choice; nothing could
            # answer it). `tests/test_continuations.py` now asserts the
            # registry covers every kind the engine can open.
            raise ValueError(f"no continuation registered for choice kind {kind!r}")
        self.state.pending_choice = None
        handler.func(self, choice, continuations.coerce_answer(handler, answer))

    @staticmethod
    def mana_cost_of(card: Card) -> ManaCost:
        """The structured cost of a card.

        Uses the raw ``mana_cost_string`` when present, else reconstructs
        it from the card's pip tally + mana value (`ManaCost.from_card`),
        so a card cached before that field existed still costs its real
        mana instead of being wrongly free.
        """
        return ManaCost.from_card(card)
    def _all_replacement_effects(self) -> list[ReplacementEffect]:
        effects: list[ReplacementEffect] = []
        for obj in self.state.permanents():
            effects.extend(obj.replacement_effects)
            # MEC-57: a layer-6 grant whose nested static_specs type
            # resolves to a `ReplacementEffect` rather than a
            # `StaticAbility` (Scion of Halaster's granted "first draw
            # each turn" rewrite) — the `_granted_static_abilities`
            # sibling, same "re-derived every recompute" shape.
            effects.extend(getattr(obj, "_granted_replacement_effects", ()))
        for player in self.state.players:
            effects.extend(
                e for e in player.player_effects if isinstance(e, ReplacementEffect)
            )
            # MEC-30: an emblem can grant a replacement too (Ajani
            # Steadfast's own "-7" — the first real one), the same "scan
            # every player's emblems alongside the battlefield" convention
            # `continuous.py`'s static-ability scan already uses.
            for emblem in player.emblems:
                effects.extend(emblem.replacement_effects)
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
        stack`/`_resume_order_triggers`'s RULE 603.3b pause/resume)
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
        prevention_disabled = self.state.damage_prevention_disabled
        if not prevention_disabled:
            # "Damage can't be prevented." (Everlasting Torment) — the
            # standing battlefield-static sibling of the turn-scoped flag
            # above; same RULE 615 effect, no lifecycle of its own.
            from . import continuous  # local: avoid the continuous↔rules cycle

            prevention_disabled = continuous.damage_prevention_globally_disabled(self.state)
        while current is not None:
            applicable = [
                effect
                for effect in self._all_replacement_effects()
                if id(effect) not in applied and effect.can_replace(current, self.context)
                # RULE 615 (MEC-30): "Damage can't be prevented this turn."
                # excludes every prevention-shaped effect from the candidate
                # list outright — `double_damage`/`additional_damage` are
                # never marked `prevents_damage`, so a card's own paired
                # "…deals double damage instead" clause is unaffected.
                and not (prevention_disabled and getattr(effect, "prevents_damage", False))
            ]
            if not applicable:
                break
            if len(applicable) > 1 and on_resolved is not None and not self.state.pending_choice:
                self._pending_replacement_event = current
                self._pending_replacement_applied = applied
                self._pending_replacement_applicable = applicable
                self._pending_replacement_callback = on_resolved
                self.open_choice(self._replacement_order_choice(current, applicable))
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
    @continuations.choice("replacement_order", answer=continuations.ANSWER_INT, rule="616.1")
    def _resume_replacement_order(
        self, choice: dict[str, Any], index: Optional[int]
    ) -> None:
        """Apply the chosen replacement next, then resume the chain (RULE
        616.1e/f) — mirrors `_resume_order_triggers`'s pattern.

        ``index`` selects one of the still-applicable effects by its option
        id; missing/out-of-range defaults to the first. Re-opens a fresh
        `replacement_order` choice if 2+ effects are still simultaneously
        applicable afterward; otherwise finishes the chain and invokes the
        stashed continuation with the final event.
        """
        callback = self._pending_replacement_callback
        if callback is None:
            return
        applicable = self._pending_replacement_applicable
        event = self._pending_replacement_event
        applied = self._pending_replacement_applied
        self._pending_replacement_event = None
        self._pending_replacement_applicable = []
        self._pending_replacement_applied = set()
        self._pending_replacement_callback = None

        if index is None or not 0 <= index < len(applicable):
            index = 0
        chosen = applicable[index]
        applied.add(id(chosen))
        current = chosen.apply_replacement(event, self.context) if event is not None else None
        if current is None:
            callback(None)
            return
        self._run_replacement_loop(current, applied, callback)
