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

from ...models.cards import card_query
from ...models.cards.card import Card
from ...models.game.emblem import Emblem
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject, Zone
from ...models.game.game_state import DelayedTrigger, GameState, StackItem
from ...models.mana.mana_cost import ManaCost
from ...models.game.player import Player
from ...parser.oracle.catalogue.keywords import parse_keywords
from ...parser.oracle.catalogue.saga import all_chapter_numbers
from .. import ability_catalogue, combat, continuous, copy_mechanics, dungeons, face_down, variants
from ..combat import is_protected_from
from ..costs import DISCARD_HAND, ActivationCost, parse_activation_cost
from ..mana_abilities import restriction_predicate_for_cast
from .triggers_mixin import _has_suspend
from ..effects.core import (
    _apply_effects_partitioned,
    AddCountersEffect,
    CompleteDungeonEffect,
    VentureIntoTheDungeonEffect,
    AddPlayerCountersEffect,
    BecomeMonarchEffect,
    CantBeCounteredEffect,
    GrantCantBeCounteredEffect,
    ChooseColorReplacement,
    ChooseCreatureTypeReplacement,
    ChooseNamedModeReplacement,
    DiscardEffect,
    DrawCardEffect,
    LoseLifeEffect,
    ReturnUncastExiledEffect,
    SacrificeSpecificEffect,
    SacrificeObjectEffect,
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
    ActivatedAbility,
    StaticAbility,
    StaticEffect,
    TakeInitiativeEffect,
    TriggeredAbility,
    WardEffect,
    WinConditionEffect,
)
from ..targeting import TargetSpec, collapse_groups, expand_counts, legal_targets
from .. import continuations

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
    if what == "nonland":
        # "…sacrifice a nonland permanent of their choice or discard a
        # card." (Tergrid's Lantern, MEC-43 round 4E) — the negated-type
        # sibling of the plain type words above; every permanent that
        # isn't a land qualifies, tokens included (unlike `nontoken_
        # creature` below).
        return not obj.is_land
    if what == "nontoken_creature":
        # RULE 111.8/701.17: "each player sacrifices a nontoken creature of
        # their choice" (Accursed Marauder/Liliana, Dreadhorde General's own
        # -4 — the edict family's most common creature-type qualifier).
        return obj.is_creature and not obj.is_token
    if what == "creature_or_planeswalker":
        # RULE 306/302: Tevesh Szat's "another creature or planeswalker" —
        # the one compound word any shipped card needs.
        return obj.is_creature or obj.card.is_planeswalker
    if what == "artifact_or_creature":
        # Deadly Dispute/Costly Plunder-shaped "sacrifice an artifact or
        # creature" additional cost — the single most-repeated compound
        # sacrifice cost in the cache.
        return obj.is_creature or obj.card.is_artifact
    if what == "creature_artifact_or_land":
        # PAR-13: "sacrifice a creature, artifact, or land of their choice"
        # (Tomb of Annihilation's "Sandfall Cell" dungeon room) — the
        # payer's own choice of *type*, not "any permanent" (which would
        # wrongly also license sacrificing an enchantment/planeswalker).
        return obj.is_creature or obj.card.is_artifact or obj.is_land
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




class MiscSystemsMixin:
    """Designations (goad/monarch/initiative/Ring), planeswalking, dungeons, wards/rampage/dethrone, countering a spell, generic interactive-payment primitives, tokens, Sagas/day-night."""

    def _request_pay_energy_then(
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
        self.open_choice({
            "kind": "pay_energy_then",
            "player_id": player.id,
            "prompt": f"{pips} bezahlen?",
            "options": [
                {"id": "pay", "label": f"{pips} bezahlen"},
                {"id": "decline", "label": "Nicht bezahlen"},
            ],
        })
    @continuations.choice("pay_energy_then", answer=continuations.ANSWER_STR, rule="122")
    def _resume_pay_energy_then(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `pay_energy_then` choice. ``answer == "pay"``
        spends the energy and resolves the follow-up effects; anything else
        (``None``/``"decline"``) does neither."""
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
    def _request_pay_cost_then(
        self,
        player: Player,
        cost: "ActivationCost",
        effect_specs: list[dict],
        source: Optional[GameObject],
        else_effect_specs: Optional[list[dict]] = None,
        prompt: Optional[str] = None,
        targets: Optional[list[Any]] = None,
        then_trigger_specs: Optional[list[dict]] = None,
        then_trigger_modes: Optional[dict[str, Any]] = None,
        then_trigger_event: Optional[GameEvent] = None,
        captured_previous: Optional[list[Any]] = None,
    ) -> None:
        """Open the interactive "you may pay ``cost``. If you do, `<effect>`."
        choice (RULE 118.3-style optional payment mid-resolution).

        The general form of the already-shipped, energy-only
        `_request_pay_energy_then` (Aether Chaser) and the *optional* mirror
        of `_request_sacrifice_unless_pay` — same `_can_pay_player_cost`/
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

        ``then_trigger_specs`` is RULE 603.11's "**When you do**, `<targeted
        payoff>`." — instead of resolving off the stack like ``effect_specs``
        (which can never choose a RULE 115 target), a paid cost enqueues
        these as their own `TriggeredAbility` on `pending_triggers`, so the
        ordinary placement path gathers targets and it goes on the stack.
        ``then_trigger_event`` is the *outer* trigger's event, carried so a
        payoff that names it ("that player") can read it back.

        ``captured_previous`` (MEC-52 — Back from the Brink) bakes in the
        RULE 608.2 referent (`GameContext.previous_targets`, the graveyard
        card whose mana cost this ``cost`` was priced off) so the paid
        branch's `copy_permanent` ``referent="previous"`` still resolves
        against it once the choice is *answered* — same re-seed idiom
        `_resume_villainous_choice` uses.
        """
        specs = [dict(d) for d in effect_specs]
        else_specs = [dict(d) for d in (else_effect_specs or [])]
        then_trigger = [dict(d) for d in (then_trigger_specs or [])]
        modal_trigger = dict(then_trigger_modes or {})
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
            "then_trigger_specs": then_trigger,
            "then_trigger_modes": modal_trigger,
            "then_trigger_event": then_trigger_event,
            "captured_previous": list(captured_previous) if captured_previous else None,
        }
        cost_label = cost.label()
        self.open_choice({
            "kind": "pay_cost_then",
            "player_id": player.id,
            "prompt": prompt or f"{cost_label} bezahlen?",
            "options": [
                {"id": "pay", "label": f"{cost_label} bezahlen"},
                {"id": "decline", "label": "Nicht bezahlen"},
            ],
        })
    @continuations.choice("pay_cost_then", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_pay_cost_then(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `pay_cost_then` choice. ``answer == "pay"``
        charges the cost and resolves the "if you do" effects; anything else
        resolves the "if you don't" branch (usually empty)."""
        pending = self._pending_pay_cost_then
        self._pending_pay_cost_then = None
        if pending is None:
            return
        player = self.state.player_by_id(pending["player_id"])
        targets = pending.get("targets") or None
        if answer != "pay" or not self._can_pay_player_cost(player, pending["cost"]):
            # Re-checked: the board can have changed since the offer was made.
            self._apply_effect_specs(pending["else_effect_specs"], pending["source"], targets)
        else:
            self._pay_player_cost(player, pending["cost"])
            captured = pending.get("captured_previous")
            if captured:
                # MEC-52: re-seed the RULE 608.2 "that card" referent for a
                # `copy_permanent` ``referent="previous"`` in the paid
                # branch (the resolution that opened this choice is gone).
                saved = list(self.context.previous_targets)
                self.context.previous_targets = list(captured)
                try:
                    self._apply_effect_specs(pending["effect_specs"], pending["source"], targets)
                finally:
                    self.context.previous_targets = saved
            else:
                self._apply_effect_specs(pending["effect_specs"], pending["source"], targets)
            self._enqueue_pay_cost_then_trigger(pending)
        # PAR-13: if this single-player choice is one leg of a mass
        # `_request_each_player_pay_or` sweep, move on to whoever's next —
        # a no-op for every ordinary (non-mass) `pay_cost_then` caller,
        # since that dict is only ever populated by the mass primitive.
        if self._pending_each_player_pay_or is not None:
            self._advance_each_player_pay_or()

    def _request_exile_source_then(
        self, player: Player, source: GameObject, then_trigger_specs: list[dict],
        prompt: Optional[str] = None,
    ) -> None:
        """Offer ``You may exile this card. If you do, ...`` during a
        resolution.  This is intentionally separate from ``ActivationCost``:
        a dies trigger's source has already moved to its owner's graveyard.
        The follow-up is a reflexive trigger so its target is chosen only
        after the source was actually exiled (RULE 603.11)."""
        if source.zone != Zone.GRAVEYARD:
            return
        self._pending_exile_source_then = {
            "player_id": player.id,
            "source": source,
            "then_trigger_specs": [dict(d) for d in then_trigger_specs],
        }
        self.open_choice({
            "kind": "exile_source_then",
            "player_id": player.id,
            "prompt": prompt or f"{source.name} ins Exil schicken?",
            "options": [
                {"id": "exile", "label": "Ins Exil schicken"},
                {"id": "decline", "label": "Nicht ins Exil schicken"},
            ],
        })

    @continuations.choice("exile_source_then", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_exile_source_then(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        self.state.pending_choice = None
        pending = self._pending_exile_source_then
        self._pending_exile_source_then = None
        if pending is None or answer != "exile":
            return
        source = pending["source"]
        # Re-check the zone: another replacement or response may have moved it.
        if source.zone != Zone.GRAVEYARD:
            return
        self.exile(source)
        self.enqueue_reflexive_trigger(pending["then_trigger_specs"], source)
    def enqueue_reflexive_trigger(
        self,
        effect_specs: list[dict[str, Any]],
        source: Optional[GameObject],
        event: Optional[GameEvent] = None,
        modes: Optional[dict[str, Any]] = None,
    ) -> None:
        """RULE 603.11: "`<effect with its own condition>`. **When you
        do**, `<targeted payoff>`." fires the payoff as its *own* fresh
        triggered ability rather than resolving it off-stack — the whole
        point being that ``effect_specs``' own RULE 115 target (if any) has
        to go through the ordinary placement path (`put_triggers_on_stack`
        → `_place_triggers`) to be gathered at all; a bare `_apply_effect_
        specs` call resolves immediately and could never open that choice.
        Built fresh per the `TriggeredAbility` docstring's own sanctioned
        "bake per-firing data in at the call site" pattern and queued on
        `pending_triggers`, so it's picked up the next time triggers are
        placed (normally right after the caller's own resolution finishes).

        Two real callers: `_enqueue_pay_cost_then_trigger` (a paid optional
        cost's own "when you do" — RULE 603.11 proper) and PAR-30's
        `ExchangeControlThenCopyTokenEffect` (Arteeoh, Dread Scavenger — "if
        you do" gated on whether a *targeted effect* actually happened,
        not a cost payment).
        """
        if not effect_specs and not modes:
            return
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
        from ...parser.oracle.spec import EffectSpec

        built = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in effect_specs],
            source,
        )
        modal_options = None
        modal = dict(modes or {})
        if modal:
            modal_options = []
            for option in modal.get("options") or []:
                modal_options.append({
                    "effects": build_effects(
                        [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in option], source,
                    ),
                    "description": "",
                })
            descriptions = list(modal.get("descriptions") or [])
            for index, option in enumerate(modal_options):
                option["description"] = descriptions[index] if index < len(descriptions) else f"Modus {index + 1}"
        controller_id = getattr(source, "controller_id", None) or self.state.active_player.id
        ability = TriggeredAbility(
            trigger_event=getattr(event, "type", None) or EventType.SPELL_RESOLVED,
            effects=built,
            source=source,
            controller_id=controller_id,
            optional=False,  # the "may"/"if" was already decided; the payoff itself is not
            description=getattr(source, "name", "") or "reflexive ability",
            modes=modal_options,
            modes_or_both=bool(modal.get("or_both", False)),
            modes_choose=int(modal.get("choose", 1)),
            modes_at_least=bool(modal.get("at_least", False)),
            modes_repeatable=bool(modal.get("repeatable", False)),
        )
        # Carry the outer event so a payoff naming it ("that player") reads
        # it off its own `StackItem.trigger_event`.
        stamped_event = event if isinstance(event, GameEvent) else GameEvent(EventType.SPELL_RESOLVED)
        self.pending_triggers.append((ability, stamped_event))
    def _enqueue_pay_cost_then_trigger(self, pending: dict[str, Any]) -> None:
        """RULE 603.11: a paid "you may `<cost>`" whose card continues "When
        you do, `<targeted payoff>`" fires that payoff via
        `enqueue_reflexive_trigger`."""
        self.enqueue_reflexive_trigger(
            pending.get("then_trigger_specs") or [], pending.get("source"),
            pending.get("then_trigger_event"), pending.get("then_trigger_modes"),
        )
    def _request_pay_life_or_return_to_library(
        self, player: Player, objs: list[GameObject], amount: int = 4,
    ) -> None:
        """"For each of those cards, pay 4 life or put the card on top of
        your library." (Sylvan Library, MEC-40) — a genuine per-card
        mandatory either/or decision (RULE 601.2h-style, not "may"),
        offered one card at a time (`_open_pay_life_or_return_choice`
        re-opens for the next until ``objs`` is exhausted), the same
        "resolve one, re-open for the rest" shape `_request_choose_objects`
        uses for a multi-pick.
        """
        queue = [o.instance_id for o in objs if o is not None]
        if not queue:
            return
        self._open_pay_life_or_return_choice(player, queue, amount)
    def _open_pay_life_or_return_choice(
        self, player: Player, queue: list[int], amount: int,
    ) -> None:
        obj_id = queue[0]
        obj = self.state.find_object(obj_id)
        if obj is None or obj not in player.hand:
            # Left the zone some other way since being queued (rare) —
            # nothing left to ask about this one; move on to the rest.
            self._continue_pay_life_or_return(player, queue[1:], amount)
            return
        self.open_choice({
            "kind": "pay_life_or_return_to_library",
            "player_id": player.id,
            "instance_id": obj_id,
            "amount": amount,
            "remaining": queue[1:],
            "prompt": f"{amount} Leben zahlen oder {obj.name} auf die Bibliothek "
                      f"zurücklegen?",
            "options": [
                {"id": "pay", "label": f"{amount} Leben zahlen"},
                {"id": "return", "label": "Auf die Bibliothek zurücklegen"},
            ],
        })
    def _continue_pay_life_or_return(
        self, player: Player, remaining: list[int], amount: int,
    ) -> None:
        if remaining:
            self._open_pay_life_or_return_choice(player, remaining, amount)
    @continuations.choice(
        "pay_life_or_return_to_library",
        answer=continuations.ANSWER_STR,
        decline="return",
        rule="118.3",
    )
    def _resume_pay_life_or_return_to_library(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `pay_life_or_return_to_library` choice.
        ``answer == "pay"`` pays the life; anything else (including a
        missing/invalid answer — a mandatory choice) puts the card back."""
        player = self.state.player_by_id(choice["player_id"])
        amount = choice["amount"]
        if answer == "pay":
            self.lose_life(player, amount, cause="cost")
        else:
            obj = self.state.find_object(choice["instance_id"])
            if obj is not None and obj in player.hand:
                player.hand.remove(obj)
                obj.zone = Zone.LIBRARY
                player.library.append(obj)
        self._continue_pay_life_or_return(player, choice.get("remaining") or [], amount)
    def _request_each_player_pay_or(
        self,
        cost: "ActivationCost",
        effect_specs: list[dict[str, Any]],
        source: Optional[GameObject],
        scope: str = "each_player",
        effect_targets: str = "decliner",
    ) -> None:
        """RULE 101.4's APNAP mass "unless" (PAR-13 — "Each player loses N
        life unless they `<pay cost>`.", Bellowing Mauler/Lim-Dûl's Hex/
        Tomb of Annihilation's "Veils of Fear"/"Sandfall Cell" dungeon
        rooms): every living player, starting with the active player and
        proceeding in turn order, is asked in turn whether to pay ``cost``;
        anyone who doesn't (or can't) gets ``effect_specs`` applied to
        *them* — not the ability's controller, which is why ``targets``
        (not the effects' own untargeted-controller default) carries each
        player through `_request_pay_cost_then`.

        ``scope`` (MEC-43, Acererak the Archlich — "for each opponent,
        `<effect>` unless that player `<pays>`.") is ``"each_player"``
        (default, unchanged) or ``"each_opponent"`` — excludes ``source``'s
        own controller from the sweep entirely. ``effect_targets`` is
        ``"decliner"`` (default, unchanged) or ``"controller"`` — Acererak's
        "**you** create a token" lands on the ability's own controller
        regardless of who declined, so no ``targets`` are threaded through
        and each inner spec resolves against its own untargeted-controller
        default instead.

        Built as a chain of ordinary single-player `_request_pay_cost_then`
        choices rather than a new chooser: each one either opens a real
        `pending_choice` (this method returns, and `resolve_pay_cost_then_
        choice` calls `_advance_each_player_pay_or` again once it's
        answered) or resolves synchronously because that player can't pay
        at all — the same "don't stall on a choice nobody can act on"
        shortcut every other pay-or-lose-it chooser takes, which is what
        lets this loop keep going without a choice for every player who
        has no way to pay.
        """
        start = self.state.active_player_index
        n = len(self.state.players)
        controller_id = getattr(source, "controller_id", None)
        order = [
            self.state.players[(start + i) % n].id
            for i in range(n)
            if not self.state.players[(start + i) % n].has_lost
            and (scope != "each_opponent" or self.state.players[(start + i) % n].id != controller_id)
        ]
        self._pending_each_player_pay_or = {
            "remaining_ids": order,
            "cost": cost,
            "effect_specs": [dict(d) for d in effect_specs],
            "source": source,
            "effect_targets": effect_targets,
        }
        self._advance_each_player_pay_or()
    def _advance_each_player_pay_or(self) -> None:
        """Ask the next still-pending player in a `_request_each_player_pay_or`
        sweep, or clear it once everyone has answered."""
        pending = self._pending_each_player_pay_or
        if pending is None:
            return
        remaining: list[str] = pending["remaining_ids"]
        effect_targets = pending.get("effect_targets", "decliner")
        while remaining:
            player_id = remaining.pop(0)
            try:
                player = self.state.player_by_id(player_id)
            except (KeyError, ValueError):
                continue
            if player.has_lost:
                continue
            self._request_pay_cost_then(
                player, pending["cost"], [], pending["source"],
                else_effect_specs=pending["effect_specs"],
                targets=[player] if effect_targets == "decliner" else None,
            )
            if self.state.pending_choice is not None:
                return  # a real choice opened — resumed via _resume_pay_cost_then
        self._pending_each_player_pay_or = None
    def _request_all_players_decline_or(
        self,
        cost: "ActivationCost",
        effect_specs: list[dict[str, Any]],
        source: Optional[GameObject],
        controller_id: str,
    ) -> None:
        """RULE 118.3-adjacent multi-player tax: "Any player may pay
        `<cost>`. If no one does, `<effect>`." (Rhystic Circle, MEC-30).

        Every living player, starting with the active player and
        proceeding in turn order, is asked in turn whether to pay ``cost``.
        The *first* player to actually pay cancels the whole thing —
        ``effect_specs`` never resolves at all, since *someone* paid to
        stop it. Only once *every* player has declined (or can't pay —
        the same "don't stall on a choice nobody can act on" shortcut
        `_request_each_player_pay_or` takes) does ``effect_specs`` resolve,
        applied *once*, to ``controller_id`` (the ability's own controller
        — "you" in the printed text, not whoever happened to decline
        last).

        This is the aggregate-outcome mirror image of `request_each_player_
        pay_or` (PAR-13's "each player loses N life unless they pay" —
        that one applies its effect *per decliner*, and a payment simply
        skips that one player while the sweep continues regardless; this
        one applies its effect *once*, and a single payment cancels the
        *entire* sweep). The two can't share one advance loop for exactly
        that reason, but both are built the same way underneath: a chain
        of ordinary single-player pay/decline choices over the same
        `_can_pay_player_cost`/`_pay_player_cost` machinery.
        """
        start = self.state.active_player_index
        n = len(self.state.players)
        order = [
            self.state.players[(start + i) % n].id
            for i in range(n)
            if not self.state.players[(start + i) % n].has_lost
        ]
        self._pending_all_decline_or = {
            "remaining_ids": order,
            "cost": cost,
            "effect_specs": [dict(d) for d in effect_specs],
            "source": source,
            "controller_id": controller_id,
        }
        self._advance_all_decline_or()
    def _advance_all_decline_or(self) -> None:
        """Ask the next still-pending player in a `request_all_players_
        decline_or` sweep; once nobody's left (everyone declined or
        couldn't pay), resolve the "if no one does" effect and clear it."""
        pending = self._pending_all_decline_or
        if pending is None:
            return
        remaining: list[str] = pending["remaining_ids"]
        cost = pending["cost"]
        while remaining:
            player_id = remaining.pop(0)
            try:
                player = self.state.player_by_id(player_id)
            except (KeyError, ValueError):
                continue
            if player.has_lost or not self._can_pay_player_cost(player, cost):
                continue
            cost_label = cost.label()
            self.open_choice({
                "kind": "all_decline_or",
                "player_id": player.id,
                "prompt": f"{cost_label} bezahlen, um dies zu verhindern?",
                "options": [
                    {"id": "pay", "label": f"{cost_label} bezahlen"},
                    {"id": "decline", "label": "Nicht bezahlen"},
                ],
            })
            return  # a real choice opened — resumed via _resume_all_decline_or
        # Every remaining player declined or couldn't pay — the sweep is over.
        self._pending_all_decline_or = None
        try:
            controller = self.state.player_by_id(pending["controller_id"])
        except (KeyError, ValueError):
            return
        self._apply_effect_specs(pending["effect_specs"], pending["source"], targets=[controller])
    @continuations.choice("all_decline_or", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_all_decline_or(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `all_decline_or` choice (`request_all_players_
        decline_or`). ``answer == "pay"`` charges that player and cancels
        the whole sweep — nothing else happens, since someone paid to stop
        it. Anything else (decline, or a re-check finding they no longer
        can pay — the board can have changed since the offer was made)
        moves on to the next player."""
        pending = self._pending_all_decline_or
        if pending is None:
            return
        if answer == "pay":
            try:
                player = self.state.player_by_id(choice["player_id"])
            except (KeyError, ValueError):
                player = None
            if player is not None and self._can_pay_player_cost(player, pending["cost"]):
                self._pay_player_cost(player, pending["cost"])
                self._pending_all_decline_or = None
                return
        self._advance_all_decline_or()
    def _request_vote(
        self,
        source: Optional[GameObject],
        controller_id: str,
        options: list[str],
        majority_specs: Optional[list[list[dict[str, Any]]]] = None,
        tie_index: Optional[int] = None,
        per_vote_specs: Optional[list[dict[str, Any]]] = None,
        winner_specs: Optional[list[Optional[list[dict[str, Any]]]]] = None,
    ) -> None:
        """RULE 701.38: "Starting with you, each player votes for one of
        ``options``." An APNAP sweep — every living player, beginning with
        the active player and proceeding in turn order, picks one option;
        the running tally is kept in ``_pending_vote``. Once everyone has
        voted, `_tally_and_apply_vote` resolves the outcome, applied with
        ``controller_id``'s player as the target (the printed "you").

        Three outcome shapes, exactly one supplied:

        * ``majority_specs`` — one serialized effect list per option (same
          index order as ``options``). The option with the strictly most
          votes has its list applied; ``tie_index`` names the option whose
          branch wins if no option is a sole leader (RULE 701.38d — "or the
          vote is tied").
        * ``per_vote_specs`` — a list of ``{"option": <index>, "effects":
          [...], "scale": <int>}`` entries: each entry's effects are
          applied once, with every ``count``/``amount`` param multiplied by
          ``scale`` × that option's vote total ("put a +1/+1 counter on ~
          for each strength vote"). MEC-46: an entry may instead be
          ``{"option": <index>, "per_voter_gain_control": true}`` —
          Expropriate's "for each money vote, choose a permanent owned by
          the voter and gain control of it", which needs the *individual
          ballots*, not just a total.
        * ``winner_specs`` (MEC-46) — like ``majority_specs``, but applied
          for **every** option that is tied for most votes, not only a sole
          leader ("~ gains protection from each color with the most votes
          or tied for most votes" — Council Guardian).

        Built as a chain of ordinary single-player choices over the same
        `_apply_effect_specs` tail every "if you do" branch already uses,
        the same way `_request_all_players_decline_or` is.
        """
        start = self.state.active_player_index
        n = len(self.state.players)
        order = [
            self.state.players[(start + i) % n].id
            for i in range(n)
            if not self.state.players[(start + i) % n].has_lost
        ]
        self._pending_vote = {
            "remaining_ids": order,
            "tally": {i: 0 for i in range(len(options))},
            # MEC-46: the individual (voter_id, option_index) ballots, in
            # ask order — needed by an outcome that acts per voter rather
            # than per total (Expropriate's per-money-vote gain-control).
            "ballots": [],
            "current_voter_id": None,
            "options": list(options),
            "source": source,
            "controller_id": controller_id,
            "majority_specs": [[dict(d) for d in lst] for lst in majority_specs] if majority_specs else None,
            "tie_index": tie_index,
            "per_vote_specs": [dict(d) for d in per_vote_specs] if per_vote_specs else None,
            "winner_specs": (
                [[dict(d) for d in lst] if lst else None for lst in winner_specs]
                if winner_specs else None
            ),
        }
        self._advance_vote()
    def _advance_vote(self) -> None:
        """Ask the next still-pending voter in a `_request_vote` sweep; once
        everyone has voted, tally and apply the outcome."""
        pending = self._pending_vote
        if pending is None:
            return
        remaining: list[str] = pending["remaining_ids"]
        options: list[str] = pending["options"]
        while remaining:
            player_id = remaining.pop(0)
            try:
                player = self.state.player_by_id(player_id)
            except (KeyError, ValueError):
                continue
            if player.has_lost:
                continue
            pending["current_voter_id"] = player.id
            # RULE 701.38f (MEC-46): "You choose how each player votes this
            # turn." (Illusion of Choice) — while `forced_vote_controller_id`
            # is set, that player answers *every* seat's vote; the real
            # voter's name still rides in the prompt so the deciding player
            # knows whose ballot they are filling in. A missing answer
            # defaults to option 0.
            decider_id, prompt_prefix = self._vote_decider(player)
            self.open_choice({
                "kind": "vote",
                "player_id": decider_id,
                "prompt": prompt_prefix + "Abstimmung: " + " / ".join(options),
                "options": [
                    {"id": str(i), "label": opt} for i, opt in enumerate(options)
                ],
            })
            return  # a real choice opened — resumed via _resume_vote
        self._tally_and_apply_vote()
    def _vote_decider(self, voter: Player) -> tuple[str, str]:
        """Who actually answers ``voter``'s ballot, and a prompt prefix.

        RULE 701.38f: normally the voter themselves; while a forced-vote
        controller is set for the turn (Illusion of Choice), that player
        answers instead and the prompt names whose vote it is."""
        forced_id = getattr(self.state, "forced_vote_controller_id", None)
        if forced_id:
            try:
                forcer = self.state.player_by_id(forced_id)
            except (KeyError, ValueError):
                forcer = None
            if forcer is not None and not forcer.has_lost:
                return forced_id, f"Stimme für {voter.name} — "
        return voter.id, ""
    @continuations.choice("vote", answer=continuations.ANSWER_STR, rule="701.38")
    def _resume_vote(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `vote` choice: record this player's vote for the
        chosen option index (a missing/unknown answer defaults to option 0,
        RULE 701.38b's "each player must choose"), then move on."""
        pending = self._pending_vote
        if pending is None:
            return
        tally: dict[int, int] = pending["tally"]
        try:
            idx = int(answer) if answer is not None else 0
        except (TypeError, ValueError):
            idx = 0
        if idx not in tally:
            idx = 0
        tally[idx] += 1
        voter_id = pending.get("current_voter_id")
        if voter_id is not None:
            pending["ballots"].append((voter_id, idx))
        self._advance_vote()
    def _tally_and_apply_vote(self) -> None:
        """Resolve a finished `_request_vote` sweep's outcome (majority
        branch, per-vote scaling, or per-winning-option) and clear it."""
        pending = self._pending_vote
        self._pending_vote = None
        if pending is None:
            return
        tally: dict[int, int] = pending["tally"]
        source = pending["source"]
        ballots: list[tuple[str, int]] = list(pending.get("ballots") or [])
        try:
            controller = self.state.player_by_id(pending["controller_id"])
        except (KeyError, ValueError):
            controller = None
        targets = [controller] if controller is not None else None

        if pending["majority_specs"] is not None:
            specs_by_option: list[list[dict]] = pending["majority_specs"]
            top = max(tally.values()) if tally else 0
            leaders = [i for i, v in tally.items() if v == top]
            winner = leaders[0] if len(leaders) == 1 else pending.get("tie_index", 0)
            if 0 <= winner < len(specs_by_option):
                self._apply_effect_specs(specs_by_option[winner], source, targets)
            return

        # MEC-46: "~ gains protection from each color with the most votes
        # or tied for most votes" (Council Guardian) — apply every leading
        # option's spec list, not just a sole leader's.
        if pending.get("winner_specs") is not None:
            winner_specs: list[Optional[list[dict]]] = pending["winner_specs"]
            top = max(tally.values()) if tally else 0
            if top > 0:
                for i, v in tally.items():
                    if v == top and 0 <= i < len(winner_specs) and winner_specs[i]:
                        self._apply_effect_specs(winner_specs[i], source, targets)
            return

        for entry in pending["per_vote_specs"] or []:
            opt = int(entry.get("option", 0))
            # MEC-46: Expropriate's "for each money vote, choose a permanent
            # owned by the voter and gain control of it" — one gain-control
            # pick per *ballot* cast for this option, resolved through a
            # `choose_objects` chain (`_advance_expropriate_gain_control`).
            if entry.get("per_voter_gain_control"):
                money_voters = [vid for vid, o in ballots if o == opt]
                self._advance_expropriate_gain_control(source, pending["controller_id"], money_voters)
                continue
            scale = int(entry.get("scale", 1) or 1) * int(tally.get(opt, 0))
            if scale <= 0:
                continue
            def scale_spec(spec: dict) -> dict:
                """Scale quantitative leaves through a composite body."""
                params = dict(spec.get("params") or {})
                for key in ("count", "amount"):
                    if isinstance(params.get(key), int):
                        params[key] *= scale
                for key in ("effects", "then", "else"):
                    if isinstance(params.get(key), list):
                        params[key] = [scale_spec(dict(child)) for child in params[key]]
                return {"type": spec["type"], "params": params}

            scaled = [scale_spec(dict(spec)) for spec in entry.get("effects", [])]
            self._apply_effect_specs(scaled, source, targets)
    def _advance_expropriate_gain_control(
        self, source: Optional[GameObject], controller_id: str, voter_ids: list[str]
    ) -> None:
        """MEC-46 (Expropriate): for the next voter in ``voter_ids``, let
        ``controller_id`` choose one permanent that voter owns and gain
        control of it (RULE 701.38 outcome body), then recurse on the rest.

        The remaining queue rides in the `choose_objects` decision's own
        ``then_specs`` (an `expropriate_gain_control` effect), so it is
        clone-safe for the undo snapshots `GameState` takes — there is no
        engine-side queue object."""
        while voter_ids:
            voter_id, rest = voter_ids[0], voter_ids[1:]
            try:
                caster = self.state.player_by_id(controller_id)
            except (KeyError, ValueError):
                return
            # Every permanent the voter *owns* is a legal pick (RULE
            # 701.38 — "a permanent owned by the voter"); one the caster
            # already controls just makes the gain-control a no-op.
            owned = [
                obj for obj in self.state.permanents()
                if getattr(obj, "owner_id", None) == voter_id
            ]
            if not owned:
                voter_ids = rest
                continue
            self._request_choose_objects(
                caster, owned, action="gain_control", count=1, source=source,
                prompt="Dauerhaften Permanent übernehmen",
                then_specs=[{
                    "type": "expropriate_gain_control",
                    "params": {"voter_ids": list(rest)},
                }],
            )
            return
    def _request_object_vote(
        self,
        source: Optional[GameObject],
        controller_id: str,
        candidates: list[GameObject],
        outcome: str,
        prompt: str = "Abstimmung",
    ) -> None:
        """MEC-46 (RULE 701.38): the tally-over-objects sibling of
        `_request_vote`. "Starting with you, each player votes for `<one of
        these objects>`. `<verb>` each `<object>` with the most votes or
        tied for most votes."

        An APNAP sweep in which every living player picks one of
        ``candidates`` — a board permanent (Council's Judgment) or a
        graveyard card (Custodi Squire) — then every object tied for most
        votes has ``outcome`` applied. ``outcome`` is ``"exile"`` or
        ``"return_to_hand"`` (a graveyard card's owner is its controller —
        "to your hand" for Custodi Squire needs no separate recipient).

        Chained one `vote_object` choice at a time, `_pending_object_vote`
        holding the tally, exactly like `_pending_vote`.
        """
        start = self.state.active_player_index
        n = len(self.state.players)
        order = [
            self.state.players[(start + i) % n].id
            for i in range(n)
            if not self.state.players[(start + i) % n].has_lost
        ]
        pool = [obj for obj in candidates if obj is not None]
        if not pool or not order:
            return
        self._pending_object_vote = {
            "remaining_ids": order,
            "current_voter_id": None,
            "tally": {obj.instance_id: 0 for obj in pool},
            "candidate_ids": [obj.instance_id for obj in pool],
            "source": source,
            "controller_id": controller_id,
            "outcome": outcome,
            "prompt_text": prompt,
        }
        self._advance_object_vote()
    def _advance_object_vote(self) -> None:
        """Ask the next still-pending voter in a `_request_object_vote`
        sweep; once everyone has voted, tally and apply the outcome."""
        pending = self._pending_object_vote
        if pending is None:
            return
        remaining: list[str] = pending["remaining_ids"]
        while remaining:
            player_id = remaining.pop(0)
            try:
                player = self.state.player_by_id(player_id)
            except (KeyError, ValueError):
                continue
            if player.has_lost:
                continue
            options: list[dict[str, Any]] = []
            for iid in pending["candidate_ids"]:
                obj = self._object_by_instance_id(iid)
                if obj is None:
                    continue  # left its zone since the sweep began
                opt: dict[str, Any] = {"id": str(iid), "label": obj.name, "instance_id": iid}
                card = getattr(obj, "card", None)
                if card is not None and getattr(card, "id", None):
                    opt["card_id"] = card.id
                options.append(opt)
            if not options:
                self._pending_object_vote = None
                return
            pending["current_voter_id"] = player.id
            decider_id, prompt_prefix = self._vote_decider(player)
            self.open_choice({
                "kind": "vote_object",
                "player_id": decider_id,
                "prompt": prompt_prefix + pending["prompt_text"],
                "options": options,
            })
            return  # resumed via _resume_vote_object
        self._tally_and_apply_object_vote()
    @continuations.choice("vote_object", answer=continuations.ANSWER_STR, rule="701.38")
    def _resume_vote_object(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `vote_object` choice: record this player's vote
        for the chosen candidate (a missing/unknown answer defaults to the
        first candidate, RULE 701.38b), then move on."""
        pending = self._pending_object_vote
        if pending is None:
            return
        tally: dict[int, int] = pending["tally"]
        try:
            iid: Optional[int] = int(answer) if answer is not None else None
        except (TypeError, ValueError):
            iid = None
        if iid not in tally:
            iid = pending["candidate_ids"][0] if pending["candidate_ids"] else None
        if iid in tally:
            tally[iid] += 1
        self._advance_object_vote()
    def _tally_and_apply_object_vote(self) -> None:
        """Resolve a finished `_request_object_vote` sweep: apply ``outcome``
        to every candidate tied for most votes (RULE 701.38d)."""
        pending = self._pending_object_vote
        self._pending_object_vote = None
        if pending is None:
            return
        tally: dict[int, int] = pending["tally"]
        top = max(tally.values()) if tally else 0
        if top <= 0:
            return
        winners = [iid for iid, v in tally.items() if v == top]
        outcome = pending["outcome"]
        for iid in winners:
            obj = self._object_by_instance_id(iid)
            if obj is None:
                continue
            if outcome == "exile":
                self.exile(obj)
            elif outcome == "return_to_hand":
                self.return_to_hand(obj)
    def _request_word_of_command(
        self,
        controller: Player,
        target: Player,
        source: Optional[GameObject] = None,
    ) -> None:
        """MEC-51b (Word of Command): open a `word_of_command`
        `pending_choice` addressed to ``controller``, listing every card in
        ``target``'s hand. `GameEngine._resume_word_of_command` then
        has ``target`` play the chosen card. No card in hand → nothing to
        choose, the effect fizzles (RULE 720-adjacent "if able")."""
        hand = list(target.hand)
        if not hand:
            return
        self.state.word_of_command = {
            "controller_id": controller.id,
            "target_id": target.id,
            "chosen_instance_id": None,
        }
        self.open_choice({
            "kind": "word_of_command",
            "player_id": controller.id,   # the *controller* picks
            "target_player_id": target.id,
            "prompt": f"Word of Command — wähle eine Karte aus {target.name}s Hand",
            "description": f"Word of Command: Karte aus {target.name}s Hand",
            "eligible": [
                {"instance_id": o.instance_id, "name": o.name} for o in hand
            ],
            "options": [
                {"id": str(o.instance_id), "label": o.name,
                 "instance_id": o.instance_id}
                for o in hand
            ],
        })

    @continuations.choice("word_of_command", answer=continuations.ANSWER_INT, rule="723")
    def _resume_word_of_command(
        self, choice: dict[str, Any], instance_id: Optional[int]
    ) -> None:
        """MEC-51b: the Word of Command caster has picked ``instance_id``
        from the target's hand — now have the target *play* it "if able".

        A land → straight onto the battlefield under the target's control
        (`_put_searched_card`; a documented simplification of RULE 305's
        land-play special action — it doesn't consume the target's
        land-for-turn). Anything else → `cast_without_paying` under the
        target's control (the effect-driven free-cast primitive cascade/
        discover use — no target selection, no mana paid; RULE 720's "only
        land mana, only for that card" restriction is moot under the free
        cast). Then the `word_of_command` window closes.
        """
        woc = self.state.word_of_command
        if woc is None:
            return
        try:
            target = self.state.player_by_id(woc["target_id"])
        except KeyError:
            self.state.word_of_command = None
            return
        obj = next((o for o in target.hand if o.instance_id == instance_id), None)
        # Missing/invalid answer — the first card in hand (RULE 720: the
        # caster must choose, "nothing" isn't an option).
        if obj is None and target.hand:
            obj = target.hand[0]
        if obj is not None:
            woc["chosen_instance_id"] = obj.instance_id
            try:
                if obj.card.is_land:
                    target.remove_from_zone(obj, Zone.HAND)
                    self._put_searched_card(target, obj, "battlefield")
                else:
                    self.cast_without_paying(target, obj)
            except (ValueError, KeyError):
                pass  # "if able" — a play that can't be made simply doesn't
        self.state.word_of_command = None

    def _request_villainous_choice(
        self,
        source: Optional[GameObject],
        controller_id: str,
        facing_ids: Optional[list[str]] = None,
        option_a: Optional[list[dict[str, Any]]] = None,
        option_b: Optional[list[dict[str, Any]]] = None,
        labels: Optional[tuple[str, str]] = None,
        captured_previous: Optional[list[Any]] = None,
        rounds: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """RULE 701.55: "`<player>` faces a villainous choice — `<A>`, or
        `<B>`." Each facing player in ``facing_ids`` (already resolved and
        APNAP-ordered by `FaceVillainousChoiceEffect`) chooses one of the
        two options and that option's effects resolve **for that player** —
        applied with the facing player as the target, so an option's
        `sacrifice`/`discard`/`lose_life` spec (no selector) lands on them.
        A "you …" clause in an option stays scoped to ``controller_id``
        (the effect's own controller default, since those specs carry no
        target).

        The `_request_vote` sweep shape, minus the tally: each player
        applies their own pick rather than everyone feeding one aggregate
        outcome. RULE 701.55b's "if one option is impossible, they must
        choose the other" is a **documented simplification** — both options
        are always offered; an impossible pick simply does as little as
        RULE 608.2b allows.

        ``rounds`` (MEC-52 — Hunted by The Family: "For each of them, that
        creature's controller faces a villainous choice — …") is the
        per-firing sibling of the flat ``facing_ids`` sweep: an explicit
        list of ``{"facing_id", "option_a", "option_b", "labels",
        "captured"}`` dicts, one queued choice each, so *different* option
        bodies / RULE 608.2 referents can face *different* players in one
        resolution (each chosen creature's own controller decides about
        that creature). The flat form builds a one-round-per-id queue
        sharing ``option_a``/``option_b``/``labels``/``captured_previous``.
        """
        default_labels = tuple(labels) if labels else ("Option A", "Option B")
        if rounds is None:
            shared_captured = list(captured_previous) if captured_previous else None
            rounds = [
                {
                    "facing_id": fid,
                    "option_a": [dict(d) for d in (option_a or [])],
                    "option_b": [dict(d) for d in (option_b or [])],
                    "labels": default_labels,
                    "captured": list(shared_captured) if shared_captured else None,
                }
                for fid in (facing_ids or [])
            ]
        else:
            rounds = [
                {
                    "facing_id": rnd["facing_id"],
                    "option_a": [dict(d) for d in rnd.get("option_a", [])],
                    "option_b": [dict(d) for d in rnd.get("option_b", [])],
                    "labels": tuple(rnd.get("labels") or default_labels),
                    "captured": list(rnd["captured"]) if rnd.get("captured") else None,
                }
                for rnd in rounds
            ]
        self._pending_villainous = {
            #: FIFO queue of still-unasked choices; each is popped into
            #: ``current`` when its prompt opens (`_advance_villainous_choice`).
            "rounds": rounds,
            "current": None,
            "source": source,
            "controller_id": controller_id,
        }
        self._advance_villainous_choice()
    def _advance_villainous_choice(self) -> None:
        """Ask the next still-pending facing player in a
        `_request_villainous_choice` sweep, or clear it once done."""
        pending = self._pending_villainous
        if pending is None:
            return
        queue: list[dict[str, Any]] = pending["rounds"]
        while queue:
            rnd = queue.pop(0)
            try:
                player = self.state.player_by_id(rnd["facing_id"])
            except (KeyError, ValueError):
                continue
            if player.has_lost:
                continue
            pending["current"] = rnd
            la, lb = rnd["labels"]
            self.open_choice({
                "kind": "villainous_choice",
                "player_id": player.id,
                "prompt": f"Schurkische Wahl: {la} / {lb}",
                "options": [
                    {"id": "0", "label": la},
                    {"id": "1", "label": lb},
                ],
            })
            return  # a real choice opened — resumed via _resume_villainous_choice
        self._pending_villainous = None
    @continuations.choice("villainous_choice", answer=continuations.ANSWER_STR, rule="701.55")
    def _resume_villainous_choice(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `villainous_choice`: apply the chosen option's
        effects for that facing player (a missing/unknown answer defaults to
        option A, RULE 701.55b's "each player must choose"), then advance."""
        pending = self._pending_villainous
        if pending is None:
            return
        rnd = pending.get("current")
        if rnd is None:
            return
        try:
            facing = self.state.player_by_id(choice["player_id"])
        except (KeyError, ValueError):
            facing = None
        specs = rnd["option_b"] if str(answer) == "1" else rnd["option_a"]
        if facing is not None:
            captured = rnd.get("captured")
            if captured:
                # Re-seed the RULE 608.2 referent for this option's own
                # `copy_permanent` ``referent="previous"`` / pronoun specs
                # (the resolution that opened the choice is long gone).
                saved = list(self.context.previous_targets)
                self.context.previous_targets = list(captured)
                try:
                    self._apply_effect_specs(specs, pending["source"], targets=[facing])
                finally:
                    self.context.previous_targets = saved
            else:
                self._apply_effect_specs(specs, pending["source"], targets=[facing])
        self._advance_villainous_choice()
    def _apply_effect_specs(
        self,
        effect_specs: list[dict],
        source: Optional[GameObject],
        targets: Optional[list[Any]] = None,
    ) -> None:
        """Build and apply serialized `EffectSpec` dicts right now, off the
        stack — the shared tail of every "if you do / if you don't" branch
        (`_resume_pay_cost_then`, `_resume_pay_energy_then`).
        Goes through `build_effects`, so the whitelist still gates every
        effect type (docs/09 security boundary)."""
        if not effect_specs:
            return
        from ...parser.oracle.spec import EffectSpec
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle

        built = build_effects(
            [
                EffectSpec(type=d["type"], params=dict(d.get("params") or {}))
                for d in effect_specs
            ],
            source,
        )
        for effect in built:
            effect.apply(self.context, targets)
    def _request_choose_creature_type_grant(
        self, player: Player, source: GameObject, then_specs: list[dict],
    ) -> None:
        """Open a **resolve-time** "choose a creature type" choice — RULE
        601.2b's "as ~ enters, choose a creature type" happens *during*
        battlefield entry via `_offer_enter_choices`'s own continuation-
        passing pipeline; this is for a triggered ability's own "When ~
        enters, choose a creature type. <effect naming the chosen type>."
        (Selfless Safewright-shaped), where the choice is part of an
        ordinary resolution instead. Stashes the pick onto ``source.
        chosen_type`` (the same field the enter-time choice sets, so a
        later static/effect reading it doesn't care which path set it) and
        runs ``then_specs`` once answered.

        No bespoke continuation needed: `_apply_effects_partitioned`
        already parks the rest of *this* effect list the instant this one
        opens `pending_choice` (RULE 608.2), and `GameEngine.
        resolve_until_stable`'s `resume_deferred_effects` resumes it —
        this method only needs to open the choice and, via
        `_resume_choose_type_for_source`, apply the tail.
        """
        options = _creature_type_options(self.state, player.id)
        if not options:
            # Nothing to choose from (e.g. a puzzle board with no creature
            # cards anywhere) — chosen_type stays None, the same safe
            # fallback RULE 601.2b's own enter-time choice gets.
            source.chosen_type = None
            self._apply_effect_specs(list(then_specs or []), source)
            return
        self.open_choice({
            "kind": "choose_type_for_source",
            "player_id": player.id,
            "prompt": "Kreaturentyp wählen",
            "options": [{"id": t, "label": t} for t in options],
            "source_id": source.instance_id,
            "then_specs": [dict(spec) for spec in (then_specs or [])],
        })
    def _request_choose_player(self, player: Player, source: GameObject) -> None:
        """"As this creature enters, choose a player." (Stuffy Doll) — a
        resolve-time choice, the player-choice sibling of `request_choose_
        creature_type_grant` (see its docstring for why this needs its
        own primitive rather than RULE 601.2b's own enter-time machinery:
        that pipeline only knows creature-type/colour/mode picks). Stashes
        the pick onto `GameObject.chosen_player_id`.
        """
        living = self.state.living_players()
        if not living:
            return
        self.open_choice({
            "kind": "choose_player_for_source",
            "player_id": player.id,
            "prompt": "Spieler wählen",
            "options": [{"id": p.id, "label": p.name} for p in living],
            "source_id": source.instance_id,
        })
    @continuations.choice(
        "choose_player_for_source",
        answer=continuations.ANSWER_STR,
        rule="601.2b",
    )
    def _resume_choose_player_for_source(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a `_request_choose_player` choice."""
        options = choice["options"]
        valid_ids = {str(o["id"]) for o in options}
        chosen = str(answer) if answer is not None and str(answer) in valid_ids else (
            str(options[0]["id"]) if options else None
        )
        source = self._object_by_instance_id(choice.get("source_id"))
        if source is not None:
            source.chosen_player_id = chosen

    def _request_slithermuse_opponent(self, player: Player, source: GameObject) -> None:
        """Slithermuse's non-targeting ``choose an opponent`` resolution."""
        opponents = [p for p in self.state.living_players() if p.id != player.id]
        if not opponents:
            return
        self.open_choice({
            "kind": "slithermuse_opponent", "player_id": player.id,
            "prompt": "Gegner für Slithermuse wählen",
            "options": [{"id": p.id, "label": p.name} for p in opponents],
            "source_id": source.instance_id,
        })

    @continuations.choice(
        "slithermuse_opponent",
        answer=continuations.ANSWER_STR,
        rule="601.2b",
    )
    def _resume_slithermuse_opponent(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        self.state.pending_choice = None
        options = choice.get("options") or []
        ids = {str(option["id"]) for option in options}
        selected = str(answer) if answer is not None and str(answer) in ids else (
            str(options[0]["id"]) if options else None
        )
        if selected is None:
            return
        chooser = self.state.player_by_id(choice["player_id"])
        opponent = self.state.player_by_id(selected)
        if chooser is not None and opponent is not None:
            self.draw(chooser, max(0, len(opponent.hand) - len(chooser.hand)))
    @continuations.choice(
        "choose_type_for_source",
        answer=continuations.ANSWER_STR,
        rule="601.2b",
    )
    def _resume_choose_type_for_source(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a `_request_choose_creature_type_grant` choice."""
        options = choice["options"]
        valid_ids = {str(o["id"]) for o in options}
        chosen = str(answer) if answer is not None and str(answer) in valid_ids else (
            str(options[0]["id"]) if options else None
        )
        source = self._object_by_instance_id(choice.get("source_id"))
        if source is not None:
            source.chosen_type = chosen
        self._apply_effect_specs(list(choice.get("then_specs") or []), source)
    def _request_sacrifice_unless_pay(
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
        self.open_choice({
            "kind": "sacrifice_unless_pay",
            "player_id": player.id,
            "prompt": f"{cost_label} bezahlen, um {source.name} zu behalten?",
            "options": [
                {"id": "pay", "label": f"{cost_label} bezahlen"},
                {"id": "decline", "label": f"{source.name} opfern"},
            ],
        })
    @continuations.choice(
        "sacrifice_unless_pay",
        answer=continuations.ANSWER_STR,
        rule="701.21",
    )
    def _resume_sacrifice_unless_pay(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `sacrifice_unless_pay` choice. ``answer == "pay"``
        charges the cost and keeps the permanent; anything else sacrifices
        it (RULE 701.17)."""
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
    def _request_destroy_unless_pay(
        self, player: Player, cost: "ActivationCost", source: Optional[GameObject]
    ) -> None:
        """Open the interactive "destroy ``source`` unless you pay ``cost``"
        choice — RULE 701.16 destruction gated by an "unless" payment, the
        real-destruction sibling of `_request_sacrifice_unless_pay` above
        (The Tabernacle at Pendrell Vale's granted upkeep trigger, "At the
        beginning of your upkeep, destroy this creature unless you pay
        {1}."). Deliberately a separate method rather than a shared "unless
        pay" verb parameter on the sacrifice one: RULE 701.16c matters here
        — destruction (unlike sacrifice) goes through `destroy`, so a
        regeneration shield can still save the permanent, which sacrifice
        can never be.

        Same pay-or-lose-it machinery as sacrifice/ward
        (`_can_pay_player_cost`/`_pay_player_cost`); a player who can't pay
        isn't asked, the permanent is destroyed outright.
        """
        if source is None:
            return
        if not self._can_pay_player_cost(player, cost):
            self.destroy(source)
            return
        self._pending_destroy_unless_pay = {
            "player_id": player.id,
            "cost": cost,
            "source": source,
        }
        cost_label = cost.label()
        self.open_choice({
            "kind": "destroy_unless_pay",
            "player_id": player.id,
            "prompt": f"{cost_label} bezahlen, um {source.name} zu behalten?",
            "options": [
                {"id": "pay", "label": f"{cost_label} bezahlen"},
                {"id": "decline", "label": f"{source.name} zerstören lassen"},
            ],
        })
    @continuations.choice("destroy_unless_pay", answer=continuations.ANSWER_STR, rule="701.8")
    def _resume_destroy_unless_pay(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `destroy_unless_pay` choice. ``answer == "pay"``
        charges the cost and keeps the permanent; anything else destroys it
        (RULE 701.16, regenerable — see `_request_destroy_unless_pay`)."""
        pending = self._pending_destroy_unless_pay
        self._pending_destroy_unless_pay = None
        if pending is None:
            return
        source = pending["source"]
        try:
            player = self.state.player_by_id(pending["player_id"])
        except KeyError:
            player = None
        if answer == "pay" and player is not None:
            # Re-check: the board can have changed between the offer and the
            # answer, same guard as `_resume_sacrifice_unless_pay`.
            if self._can_pay_player_cost(player, pending["cost"]):
                self._pay_player_cost(player, pending["cost"])
                return
        if source is not None and source in self.state.battlefield:
            self.destroy(source)
    def _request_tap_or_untap_choice(self, target: GameObject, source: Optional[GameObject] = None) -> None:
        """"You may tap or untap target permanent." (Derevi, Empyrial
        Tactician — MEC-42) — a genuine two-way choice layered on top of
        RULE 115's own target (unlike `TapEffect`'s plain ``untap`` bool,
        fixed at bind time), so it needs its own small `pending_choice`
        rather than reusing that effect's target-only optionality.
        """
        self._pending_tap_or_untap_target_id = target.instance_id
        self.open_choice({
            "kind": "tap_or_untap",
            "player_id": getattr(source, "controller_id", None) or self.state.active_player.id,
            "prompt": f"{target.name} tappen oder enttappen?",
            "options": [
                {"id": "tap", "label": "Tappen"},
                {"id": "untap", "label": "Enttappen"},
                {"id": "decline", "label": "Nichts tun"},
            ],
        })
    @continuations.choice("tap_or_untap", answer=continuations.ANSWER_STR, rule="701.26")
    def _resume_tap_or_untap(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `tap_or_untap` choice — ``"tap"``/``"untap"``
        do the obvious thing; anything else (a decline) does nothing."""
        target_id = self._pending_tap_or_untap_target_id
        self._pending_tap_or_untap_target_id = None
        if answer not in ("tap", "untap") or target_id is None:
            return
        target = self.state.find_object(target_id)
        if target is not None and target in self.state.battlefield:
            self.set_tapped(target, tapped=(answer == "tap"))
    def offer_opening_hand_battlefield_choice(self, player: Player, obj: GameObject) -> None:
        """RULE 103.6: a card printing a pregame setup permission
        (`game/ability_catalogue.pregame_setup_permission`) offers
        ``player`` the choice for one such card still in their opening
        hand — RULE 103.6a's plain "you may begin the game with it on the
        battlefield." (the Leyline cycle), or one of the two conditional/
        costed shapes the same module also recognises (Gemstone Caverns'
        "...and you're not the starting player...with a luck counter on
        it. If you do, exile a card from your hand."; Buried Ogre's
        "...in your graveyard. If you do, you lose N life."). `services/
        game_session.py` walks every seat's qualifying cards one at a
        time once the whole table has kept — and, for the conditional
        shape, only once it has confirmed the "not the starting player"
        condition holds, so an unmet condition is never even offered —
        the same queued-`pending_choice` shape Vancouver's post-keep
        scry uses (`_open_next_vancouver_scry`).
        """
        permission = ability_catalogue.pregame_setup_permission(obj.card)
        assert permission is not None  # game_session only queues qualifying cards
        self._pending_opening_hand_obj = obj
        if permission.destination == "battlefield":
            prompt = f"{obj.name}: mit ihr auf dem Schlachtfeld statt in der Hand beginnen?"
            accept_label = "Auf das Schlachtfeld legen"
        else:
            prompt = f"{obj.name}: mit ihr im Friedhof statt in der Hand beginnen?"
            accept_label = "In den Friedhof legen"
        self.open_choice({
            "kind": "opening_hand_battlefield",
            "player_id": player.id,
            "prompt": prompt,
            "options": [
                {"id": permission.destination, "label": accept_label},
                {"id": "decline", "label": "In der Hand behalten"},
            ],
        })
    @continuations.choice(
        "opening_hand_battlefield",
        answer=continuations.ANSWER_STR,
        rule="103.6",
    )
    def _resume_opening_hand_battlefield(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `opening_hand_battlefield` `pending_choice`
        (RULE 103.6). Accepting — ``answer`` equal to the permission's own
        `PregameSetupPermission.destination`, "battlefield" or "graveyard"
        — moves the card there straight from the opening hand (a
        battlefield entry is untapped, summoning sick, the same default a
        search-to-battlefield hit gets; a graveyard one fires no zone-
        change event of its own, since it isn't a discard, a death, or a
        mill, and nothing can be on the battlefield yet with a trigger
        that would care) and applies whatever the clause promises along
        with it: RULE 614.1-style entry counters first (Gemstone Caverns'
        luck counter — the same direct `GameObject.add_counters` call
        `_apply_entry_counters` uses, not routed through replacement
        doubling), then the mandatory "if you do" tail — `lose_life`, or
        an interactive `exile` `choose_objects` pick, since *which* hand
        card is exiled is the player's choice (RULE 601.2c); nothing
        happens if the hand is already empty. Anything else (including the
        card having somehow already left hand) leaves it untouched."""
        obj = self._pending_opening_hand_obj
        self._pending_opening_hand_obj = None
        if obj is None:
            return
        permission = ability_catalogue.pregame_setup_permission(obj.card)
        if permission is None or answer != permission.destination:
            return
        player = self.state.player_by_id(choice["player_id"])
        if obj not in player.hand:
            return  # defensive: shouldn't happen, nothing else touches hands here
        player.remove_from_zone(obj, Zone.HAND)
        if permission.destination == "battlefield":
            obj.zone = Zone.BATTLEFIELD
            obj.summoning_sick = True
            self.state.add_to_battlefield(obj)
            if permission.counter_type and permission.counter_count:
                obj.add_counters(permission.counter_type, permission.counter_count)
            self.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD,
                    controller_id=player.id,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
        else:
            player.add_to_zone(obj, Zone.GRAVEYARD)
        if permission.cost_kind == "lose_life":
            self.lose_life(player, permission.cost_amount, cause="cost")
        elif permission.cost_kind == "exile_hand_card":
            self._request_choose_objects(
                player, list(player.hand), "exile", count=1,
                prompt="Wähle eine Karte aus deiner Hand zum Exilieren",
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
        created later, once `_resume_replacement_order` finishes the
        chain. A token's own `enter_as_copy_effects` choice (below) can pause
        the very same way, for the very same reason.

        Known scoped gap: unlike `resolve_top_of_stack`'s `_resolve_
        permanent_spell`, `enter_choice_effects` (RULE 601.2b "as ~ enters,
        choose a creature type/color") is bound but never offered here —
        every real card with that ability in the pool is a cast permanent,
        never a token, so there's nothing to exercise it against yet.
        """
        from ..binding.core import bind_from_catalogue  # function-scoped: avoid cycle

        def _finish_entry(token: GameObject) -> None:
            token.summoning_sick = True  # RULE 302.6 applies to tokens too
            # RULE 614.1 — see the matching comment in
            # `_resolve_permanent_spell` above.
            token.tapped = ability_catalogue.enters_tapped(
                token_card
            ) or continuous.enters_tapped_from_static(self.state, token)
            self._apply_entry_counters(token)  # a token was never cast, so X is 0
            self._apply_granted_entry_counters(token)
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

        def _build(final_count: int) -> list[GameObject]:
            created: list[GameObject] = []

            def _next(remaining: int) -> None:
                if remaining <= 0:
                    return
                token = GameObject(
                    token_card,
                    owner_id=controller_id,
                    zone=zone,
                    is_token=True,
                )
                bind_from_catalogue(token)  # token abilities are live like any card's
                if zone != Zone.BATTLEFIELD:
                    self.state.player_by_id(controller_id).add_to_zone(token, zone)
                    created.append(token)
                    _next(remaining - 1)
                    return

                def _continuation() -> None:
                    _finish_entry(token)
                    created.append(token)
                    _next(remaining - 1)

                if token.enter_as_copy_effects:
                    # RULE 614.1c/614.12: a token can carry its own "you may
                    # have this enter as a copy of target X" replacement —
                    # e.g. a token copy of Clever Impersonator, via
                    # `copy_permanent`/RULE 707.2 — and gets the same
                    # pre-entry choice a cast permanent does
                    # (`_resolve_permanent_spell`/`_offer_enter_as_copy`).
                    # `_offer_enter_as_copy` calls `_continuation` right away
                    # when there's no legal target to offer, so the common
                    # case (no card in the pool combines "create N token
                    # copies" with a *second* legal target at creation time)
                    # still finishes this whole loop synchronously; a real
                    # choice instead stashes `_continuation` and resumes it
                    # from `_resume_enter_as_copy`, at which point the
                    # remaining tokens in this batch (if any) are built.
                    self._offer_enter_as_copy(token, _continuation)
                else:
                    _continuation()

            _next(max(0, final_count))
            return created

        if zone != Zone.BATTLEFIELD or count <= 0:
            return _build(count)

        event = GameEvent(
            EventType.CREATE_TOKENS, controller_id=controller_id, amount=count,
            # "If you would create a Clue, Food, or Treasure token, instead
            # create one of each." (Academy Manufactor) / "…those tokens
            # plus an additional Food token are created instead." (Peregrin
            # Took) — both need to know *which* token is being made, not
            # just how many; `_double_tokens_replacement`'s own amount-only
            # scaling can't express either.
            token_name=token_card.name,
        )
        result: list[GameObject] = []

        def _finish(resolved: Optional[GameEvent]) -> None:
            nonlocal result
            if resolved is None:
                return
            result = _build(resolved.get("amount", count))
            # "The first time you create one or more tokens each turn, …"
            # (Mirrormind Crown) — same missing broadcast `add_counters`
            # had: `apply_replacements` only used this event to compute the
            # final amount, so nothing ever reached `_collect_triggers`.
            self.state.fire_event(resolved)

        self.apply_replacements(event, on_resolved=_finish)
        return result
    def put_onto_battlefield_attacking(
        self, obj: GameObject, defender: Optional[dict[str, Any]] = None
    ) -> None:
        """RULE 508.4: an already-on-the-battlefield creature is put into
        combat *attacking* without having been declared — it doesn't tap for
        the attack (RULE 508.4) and summoning sickness doesn't stop it (it
        never "attacked"). RULE 508.4a: the effect's controller chooses which
        defender it attacks; with one obvious defender — the common
        two-player combat, or whatever the rest of this combat is already
        attacking — that choice is auto-made here. Fires an `ATTACKS` event
        so "whenever ~ attacks" / battalion-style triggers still see it.

        This is the shared primitive behind "create a … token that's tapped
        **and attacking**" and "put a card … onto the battlefield tapped
        **and attacking**" (RULE 508.4) — the ``tapped`` half is applied
        separately by the caller.
        """
        if not obj.is_creature:
            return
        if defender is None:
            # Attack whoever the rest of this combat is attacking, if that's
            # unambiguous; otherwise the controller's sole/first opponent.
            player_defenders = {
                (o.combat_defender or {}).get("id")
                for o in self.state.battlefield
                if o is not obj and getattr(o, "attacking", False)
                and (o.combat_defender or {}).get("kind") == "player"
            }
            opponents = [
                p for p in self.state.living_players() if p.id != obj.controller_id
            ]
            target_id = player_defenders.pop() if len(player_defenders) == 1 else None
            if target_id is None and opponents:
                target_id = opponents[0].id
            if target_id is not None:
                try:
                    dp = self.state.player_by_id(target_id)
                except (KeyError, ValueError):
                    dp = None
                if dp is not None:
                    defender = {"kind": "player", "id": dp.id, "label": dp.name}
        obj.attacking = True
        obj.attacked_this_turn = True
        obj.combat_defender = defender
        self.state.fire_event(
            GameEvent(
                EventType.ATTACKS,
                attacker=obj.name,
                player_id=obj.controller_id,
                instance_id=obj.instance_id,
                object_types=sorted(obj.type_words),
                defending_player_id=(defender or {}).get("id"),
            )
        )
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
        each call site) covers every cast path from one place. Also flips
        PAR-10's `cast_instant_or_sorcery_this_turn` off the same event's
        ``object_types`` — the front-end front for Hall of Oracles/Jin-
        Gitaxias's activation condition and Haunting Figment/Leapfrog/
        Piston-Fist Cyclops's "as long as" statics."""
        if event.type != EventType.SPELL_CAST:
            return
        player_id = event.get("player_id")
        if player_id is None:
            return
        counts = self.state.spells_cast_this_turn
        counts[player_id] = counts.get(player_id, 0) + 1
        object_types = event.get("object_types") or []
        if "instant" in object_types or "sorcery" in object_types:
            self.state.cast_instant_or_sorcery_this_turn[player_id] = True
            # Rootha, Mastering the Moment (PAR-60) — running max of the
            # instant/sorcery mana values this player has cast this turn.
            mv = int(event.get("mana_value") or 0)
            gmv = self.state.greatest_instant_sorcery_mv_this_turn
            gmv[player_id] = max(gmv.get(player_id, 0), mv)
        if "creature" not in object_types:
            nc_counts = self.state.noncreature_spells_cast_this_turn
            nc_counts[player_id] = nc_counts.get(player_id, 0) + 1
        if "artifact" not in object_types:
            # Ethersworn Canonist (MEC-43) — the nonartifact-scoped sibling
            # of the noncreature tally above.
            na_counts = self.state.nonartifact_spells_cast_this_turn
            na_counts[player_id] = na_counts.get(player_id, 0) + 1
        # Veil of Summer-shaped "if an opponent has cast a blue or black
        # spell this turn" — SPELL_CAST carries no ``colors`` of its own,
        # so this reads the cast object's live colour off the stack it was
        # just pushed onto (still findable by `instance_id`, the same
        # object either way — RULE 400.7 doesn't apply mid-stack).
        instance_id = event.get("instance_id")
        if instance_id is not None:
            obj = self.state.find_object(instance_id)
            if obj is not None:
                colors = self.state.spell_colors_cast_this_turn.setdefault(player_id, set())
                colors.update(obj.colors)
                # MEC-60 (Acolyte of Bahamut): "the first Dragon spell you
                # cast each turn …" — read the cast object's *subtypes*
                # (after the printed em dash), which ``object_types`` above
                # never carries (main card types only).
                subtypes = obj.card.type_line.partition("—")[2].strip().lower().split()
                if subtypes:
                    seen = self.state.creature_type_spells_cast_this_turn.setdefault(player_id, set())
                    seen.update(subtypes)
    def arm_spell_watcher(
        self,
        player: Player,
        then_specs: list[dict],
        source: Optional[GameObject],
        max_mana_value: Optional[int] = None,
        card_types: Optional[list[str]] = None,
        repeat: bool = False,
    ) -> None:
        """"When you next cast an instant or sorcery spell with mana value
        N or less this turn, `<effect>`." (Dual Strike) — see `GameState.
        spell_watchers`'s docstring for why this is its own mechanism
        rather than an ordinary triggered ability or RULE 603.7 delayed
        trigger.

        ``repeat=True`` (Veil of Summer's "**Spells you control** can't be
        countered this turn" — every matching spell for the rest of the
        turn, not just the next one) keeps the watcher armed after it
        fires instead of consuming it — see `_check_spell_watchers`.
        """
        self.state.spell_watchers.append({
            "controller_id": player.id,
            "max_mana_value": max_mana_value,
            "card_types": list(card_types) if card_types else None,
            "then_specs": [dict(spec) for spec in then_specs],
            "source_id": source.instance_id if source is not None else None,
            "expires_turn": self.state.internal_turn.number,
            "repeat": repeat,
        })

    def _check_spell_watchers(self, event: GameEvent) -> None:
        """`SPELL_CAST` subscriber running every matching entry in
        `GameState.spell_watchers`, if any (`arm_spell_watcher`). Runs each
        matched watcher's ``then_specs`` with the just-cast spell's own
        stack item as ``targets[0]`` — `effects.CopySpellEffect.apply`
        reads a plain ``targets[0]`` with no RULE 115 target selection of
        its own, so this reuses it unmodified. A ``repeat`` watcher stays
        armed after matching (Veil of Summer-shaped "for the rest of the
        turn"); every other one is consumed on its first match, same as
        before.
        """
        if event.type != EventType.SPELL_CAST or not self.state.spell_watchers:
            return
        turn = self.state.internal_turn.number
        player_id = event.get("player_id")
        object_types = event.get("object_types") or []
        instance_id = event.get("instance_id")
        mana_value = event.get("mana_value")
        remaining = []
        matched = []
        for watcher in self.state.spell_watchers:
            if watcher["expires_turn"] != turn or watcher["controller_id"] != player_id:
                remaining.append(watcher)
                continue
            if watcher["max_mana_value"] is not None and (mana_value or 0) > watcher["max_mana_value"]:
                remaining.append(watcher)
                continue
            if watcher["card_types"] and not any(t in object_types for t in watcher["card_types"]):
                remaining.append(watcher)
                continue
            matched.append(watcher)
            if watcher.get("repeat"):
                remaining.append(watcher)
        self.state.spell_watchers = remaining
        if not matched or instance_id is None:
            return
        item = self.state.find_object(instance_id)
        if item is None:
            return
        for watcher in matched:
            source = self._object_by_instance_id(watcher.get("source_id"))
            self._apply_effect_specs(watcher["then_specs"], source, targets=[item])
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
        # Intermediate Chirography (PAR-60), level 3 — "if a modified creature
        # died under your control this turn". Documented simplification:
        # "modified" == had one or more counters, read off the DIES event's
        # snapshotted ``counters`` (RULE 400.7).
        if any(int(v) > 0 for v in (event.get("counters") or {}).values()):
            mods = self.state.modified_creatures_died_this_turn
            mods[player_id] = mods.get(player_id, 0) + 1

    def _track_creature_card_to_graveyard(self, event: GameEvent) -> None:
        """PAR-32: record a *creature card* entering a graveyard from
        anywhere this turn (Cloakwood Hermit — `GameState.creature_card_to_
        graveyard_this_turn`, keyed by the card's owner). Listens for
        `DIES` (battlefield), `DISCARD_CARD` (hand) and `MILL_CARD`
        (library); the card sits in its graveyard by the time each fires,
        so `is_creature` is read live where the event doesn't snapshot it."""
        if event.type == EventType.DIES:
            if "creature" not in (event.get("object_types") or []):
                return
            obj = self.state.find_object(event.get("instance_id"))
            owner_id = obj.owner_id if obj is not None else event.get("owner_id")
        elif event.type in (EventType.DISCARD_CARD, EventType.MILL_CARD):
            obj = self.state.find_object(event.get("instance_id"))
            if obj is None or not getattr(obj, "is_creature", False):
                return
            owner_id = obj.owner_id
        else:
            return
        if owner_id is not None:
            self.state.creature_card_to_graveyard_this_turn.add(owner_id)

    def _track_permanent_card_to_graveyard(self, event: GameEvent) -> None:
        """RULE 702.175: remember a permanent card entering its graveyard."""
        if event.type == EventType.DIES:
            types = event.get("object_types") or []
            owner_id = event.get("owner_id")
        elif event.type in (EventType.DISCARD_CARD, EventType.MILL_CARD):
            obj = self.state.find_object(event.get("instance_id"))
            if obj is None:
                return
            types = obj.type_words
            owner_id = obj.owner_id
        else:
            return
        if owner_id is not None and any(
            type_word in {"artifact", "battle", "creature", "enchantment", "land", "planeswalker"}
            for type_word in types
        ):
            self.state.permanent_card_to_graveyard_this_turn.add(owner_id)

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
    def planeswalk(self, player: Player, _depth: int = 0) -> Optional[GameObject]:
        """Planeswalk (RULE 901.10): the face-up plane goes to the bottom of
        the planar deck face down, and the next one turns face up.

        Fires `PLANESWALKED_AWAY` for the plane being left and
        `PLANESWALKED_TO` for the new one, in that order — RULE 901.10's own
        order, and the one that lets a plane's leave-trigger see the board
        before its successor's enter-trigger changes it. Returns the plane
        walked to, or ``None`` outside a Planechase game.
        """
        deck = self.state.planar_deck
        if not deck:
            return None
        leaving = deck.pop()
        deck.insert(0, leaving)  # bottom of the deck (index 0 — see `planar_deck`)
        self.state.fire_event(
            GameEvent(
                EventType.PLANESWALKED_AWAY,
                player_id=player.id,
                controller_id=player.id,
                instance_id=leaving.instance_id,
                plane=leaving.name,
            )
        )
        arriving = deck[-1]
        arriving.controller_id = player.id
        self.state.fire_event(
            GameEvent(
                EventType.PLANESWALKED_TO,
                player_id=player.id,
                controller_id=player.id,
                instance_id=arriving.instance_id,
                plane=arriving.name,
            )
        )
        if variants.is_phenomenon(arriving) and _depth < len(deck):
            # RULE 901.18: "when a phenomenon's triggered ability leaves the
            # stack, its controller planeswalks" — a phenomenon is never
            # somewhere the game stays. Chained straight away rather than
            # after that ability resolves: the ability is already queued with
            # this object bound as its source and reads no zone of its own,
            # so the two orders are indistinguishable (the same call
            # `set_scheme_in_motion` makes for RULE 904.10). ``_depth`` is a
            # loop guard, not a rule: RULE 901.15 caps a legal planar deck at
            # two phenomena, but nothing stops a hand-built one.
            return self.planeswalk(player, _depth=_depth + 1)
        return arriving
    def roll_planar_die(self, player: Player) -> str:
        """Roll the planar die (RULE 901.6) and apply its face.

        Returns the face rolled: ``"chaos"`` (901.13 — the face-up plane's
        chaos ability triggers), ``"planeswalk"`` (901.14 — planeswalk right
        away) or ``"blank"`` (nothing happens, which is four of the six
        faces). Paying the {X} cost and counting the roll is the *special
        action*'s job (`GameEngine.roll_planar_die`); this is the roll
        itself, so a test — or a card that rolls the die for free — can use
        it directly.
        """
        face = self.random_choice(list(variants.PLANAR_DIE_FACES))
        if face == "chaos":
            self.trigger_chaos(player)
        elif face == "planeswalk":
            self.planeswalk(player)
        return face

    def trigger_chaos(self, player: Player) -> None:
        """RULE 901.13: "chaos ensues" — fire `CHAOS_ENSUED` for the
        face-up plane so its chaos-triggered ability goes on the stack.
        Factored out of `roll_planar_die` so a card that says "chaos
        ensues" outright (Path of the Animist/Enigma's vote outcome) can
        reach it too. A no-op with no active plane (outside a Planechase
        game there is no chaos ability to put on the stack)."""
        plane = variants.active_plane(self.state)
        if plane is None:
            return
        self.state.fire_event(
            GameEvent(
                EventType.CHAOS_ENSUED,
                player_id=player.id,
                controller_id=player.id,
                instance_id=plane.instance_id,
                plane=plane.name,
            )
        )
    def set_scheme_in_motion(self, player: Player) -> Optional[GameObject]:
        """RULE 904.7: the archenemy turns the top card of their scheme deck
        face up and it "is set in motion" — its triggered ability fires.

        An **ongoing** scheme (RULE 904.9) stays face up in the command zone
        until abandoned; every other scheme goes back under its deck as soon
        as its ability has resolved (904.10) — done here rather than after
        the resolution, since the ability is already on the stack by then and
        its effects don't read the card's zone.
        """
        if not player.scheme_deck:
            return None
        scheme = player.scheme_deck.pop()
        scheme.controller_id = player.id
        is_ongoing = "ongoing" in (scheme.card.type_line or "").lower()
        # Face up first, *then* the event: a scheme's own ability is found by
        # the same command-zone scan that finds an ongoing one's
        # (`variants.command_zone_ability_sources`), so the card has to be
        # face up while `fire_event` collects triggers. A non-ongoing scheme
        # then goes straight back under its deck — RULE 904.10 times that
        # "after its ability leaves the stack", which is indistinguishable
        # here: the ability is already on the stack with this object bound as
        # its source, and nothing it does reads the card's zone.
        player.ongoing_schemes.append(scheme)
        self.state.fire_event(
            GameEvent(
                EventType.SCHEME_SET_IN_MOTION,
                player_id=player.id,
                controller_id=player.id,
                instance_id=scheme.instance_id,
                scheme=scheme.name,
                ongoing=is_ongoing,
            )
        )
        if not is_ongoing:
            player.ongoing_schemes.remove(scheme)
            player.scheme_deck.insert(0, scheme)  # bottom of the deck (904.10)
        return scheme
    def abandon_scheme(self, player: Player, scheme: GameObject) -> bool:
        """RULE 904.11: an ongoing scheme is abandoned — turned face down and
        put on the bottom of its owner's scheme deck."""
        if scheme not in player.ongoing_schemes:
            return False
        player.ongoing_schemes.remove(scheme)
        player.scheme_deck.insert(0, scheme)
        return True
    def venture_into_the_dungeon(self, player: Player, dungeon_name: Optional[str] = None) -> None:
        """The venture-into-the-dungeon keyword action (RULE 701.49).

        Three branches, exactly as the rule splits them:

        * **701.49a** — not in a dungeon: choose one from outside the game
          (an interactive `pending_choice` when more than one is available),
          put it into the command zone and put the venture marker on its
          topmost room (309.4a).
        * **701.49b** — in a room with arrows leaving it: move the marker
          along one of them, choosing when there are several.
        * **701.49c** — in the bottommost room: that dungeon is completed and
          leaves the game, then a fresh one is entered at its top room.

        ``dungeon_name`` is RULE 701.49d's "venture into [quality]" variant
        (RULE 726.2's "venture into Undercity"): it names which dungeon a
        *new* one must be, and is ignored once the player is already in one —
        which is the rule's own wording, not a simplification.

        Moving the marker into a room is what triggers that room's ability
        (309.4c); this fires `EventType.DUNGEON_ROOM_ENTERED` and
        `_collect_dungeon_room_triggers` builds the ability from it, the same
        source-less way the monarch's and the initiative's own inherent
        abilities are built.
        """
        dungeon = player.dungeon
        if dungeon is None:
            self._enter_new_dungeon(player, dungeon_name)
            return
        if dungeon.on_last_room:
            # RULE 701.49c: complete this one first, then start another.
            self.complete_dungeon(player)
            self._enter_new_dungeon(player, dungeon_name)
            return
        rooms = dungeon.next_rooms()
        if not rooms:
            return
        if len(rooms) == 1:
            self.move_venture_marker(player, rooms[0].name)
            return
        # RULE 701.49b: "if there are multiple arrows … they choose one".
        self.open_choice({
            "kind": "venture_room",
            "player_id": player.id,
            "prompt": f"{dungeon.name}: welchen Raum betrittst du?",
            "options": [
                {"id": room.name, "label": f"{room.name} — {room.effect_text}"}
                for room in rooms
            ],
        })
    @continuations.choice("venture_room", answer=continuations.ANSWER_STR, rule="701.49")
    def _resume_venture_room(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending RULE 701.49b room choice. Mandatory (the marker
        has to move somewhere), so an unrecognized/missing answer takes the
        first arrow rather than staying put."""
        player = self.state.player_by_id(choice["player_id"])
        names = [opt["id"] for opt in choice["options"]]
        self.move_venture_marker(player, answer if answer in names else names[0])
    def _enter_new_dungeon(self, player: Player, dungeon_name: Optional[str] = None) -> None:
        """RULE 309.2a/701.49a: bring a dungeon card into the game.

        A named dungeon (RULE 701.49d) is taken directly; otherwise the pool
        is every dungeon that isn't gated behind its own "venture into
        [quality]" wording, and the player picks when there's more than one.
        """
        if dungeon_name:
            dungeon = dungeons.dungeon_by_name(dungeon_name)
            if dungeon is None:
                return
            self._put_dungeon_into_command_zone(player, dungeon)
            return
        pool = dungeons.choosable_dungeons()
        if not pool:
            return
        if len(pool) == 1:
            self._put_dungeon_into_command_zone(player, pool[0])
            return
        self.open_choice({
            "kind": "choose_dungeon",
            "player_id": player.id,
            "prompt": "In welchen Dungeon begibst du dich?",
            "options": [{"id": d.name, "label": d.name} for d in pool],
        })
    @continuations.choice("choose_dungeon", answer=continuations.ANSWER_STR, rule="309.2")
    def _resume_choose_dungeon(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending RULE 309.2a dungeon choice — mandatory, so an
        unrecognized/missing answer takes the first offered dungeon."""
        player = self.state.player_by_id(choice["player_id"])
        names = [opt["id"] for opt in choice["options"]]
        chosen = answer if answer in names else names[0]
        dungeon = dungeons.dungeon_by_name(chosen)
        if dungeon is not None:
            self._put_dungeon_into_command_zone(player, dungeon)
    def _put_dungeon_into_command_zone(self, player: Player, dungeon: Any) -> None:
        """RULE 309.2b/309.4a: the card goes to the command zone and the
        marker onto its topmost room — which immediately triggers that
        room's ability (309.4c)."""
        self.state._timestamp_counter = getattr(self.state, "_timestamp_counter", 0) + 1
        dungeon.controller_id = player.id
        dungeon.owner_id = player.id
        dungeon.timestamp = self.state._timestamp_counter
        player.dungeon = dungeon
        top = dungeon.top_room
        if top is None:
            return
        self.move_venture_marker(player, top.name)
    def move_venture_marker(self, player: Player, room_name: str) -> None:
        """Move ``player``'s venture marker into ``room_name`` and fire the
        event its room ability triggers off (RULE 309.4c)."""
        dungeon = player.dungeon
        if dungeon is None or dungeon.room(room_name) is None:
            return
        dungeon.current_room = room_name
        self.state.fire_event(
            GameEvent(
                EventType.DUNGEON_ROOM_ENTERED,
                player_id=player.id,
                controller_id=player.id,
                dungeon=dungeon.name,
                room=room_name,
            )
        )
    def complete_dungeon(self, player: Player) -> None:
        """RULE 309.6/309.7: the dungeon card is removed from the game, and
        its owner thereby *completes* it."""
        dungeon = player.dungeon
        if dungeon is None:
            return
        player.dungeon = None
        player.completed_dungeons.append(dungeon.name)
        self.state.fire_event(
            GameEvent(
                EventType.DUNGEON_COMPLETED,
                player_id=player.id,
                controller_id=player.id,
                dungeon=dungeon.name,
            )
        )
    def _collect_dungeon_room_triggers(self, event: GameEvent) -> None:
        """RULE 309.4c: build a room's triggered ability as the venture marker
        moves into it — "When you move your venture marker into this room,
        [effect]".

        Source-less in the same sense the monarch's and the initiative's
        abilities are: there is no permanent for `_collect_triggers`' object
        scan to find, only a dungeon card in the command zone. The ability's
        controller is the dungeon's owner (309.4c), and its source is the
        `Dungeon` itself — which carries `controller_id`/`timestamp` for
        exactly this, the way `models/emblem.py` does.
        """
        if event.type != EventType.DUNGEON_ROOM_ENTERED:
            return
        player = self.state.player_by_id(event.get("player_id"))
        dungeon = getattr(player, "dungeon", None)
        if dungeon is None:
            return
        room = dungeon.room(event.get("room"))
        if room is None:
            return
        specs = dungeons.room_effect_specs(room)
        effects = self._effects_from_specs(specs, source=dungeon)
        if room.is_last:
            # RULE 309.6: "if a player's venture marker is on the bottommost
            # room … and that dungeon card isn't the source of a room ability
            # that has triggered but not yet left the stack, the owner removes
            # it from the game". Modeled as the last thing that room's own
            # ability does, which is precisely the moment that condition first
            # becomes true — rather than as a separate SBA scan that would
            # have to identify "is this stack item this dungeon's ability?".
            effects.append(CompleteDungeonEffect(source=dungeon))
        if not effects:
            return
        ability = TriggeredAbility(
            trigger_event=EventType.DUNGEON_ROOM_ENTERED,
            effects=effects,
            controller_id=player.id,
            description=f"{dungeon.name} — {room.name}: {room.effect_text}",
        )
        # MEC-61 (Dungeon Delver): "Room abilities of dungeons you own
        # trigger an additional time." — same "extra, independent copies"
        # idiom `triggers_mixin`'s own `trigger_doubler_bonus` call uses
        # (RULE 603.3b: each copy is separately orderable once 2+ end up
        # pending together), just via `dungeon_room_trigger_doubler_bonus`
        # since a dungeon room trigger has no `GameObject` source for the
        # general doubler to key off.
        copies = 1 + continuous.dungeon_room_trigger_doubler_bonus(self.state, player.id)
        for _ in range(copies):
            self.pending_triggers.append((ability, event))
    def _effects_from_specs(self, specs: list[dict[str, Any]], source: Any) -> list[Any]:
        """Serialized `EffectSpec` dicts → live one-shot `GameEffect`s bound
        against ``source`` — the same lazily-imported binder path
        `create_emblem` uses for an emblem's quoted ability, and for the same
        reason (a module-level import would cycle through `game/effects/core.py`).
        """
        from ...parser.oracle.spec import EffectSpec
        from ..binding.core import BindError, build_effects

        if not specs:
            return []
        try:
            return build_effects(
                [
                    EffectSpec(
                        type=spec["type"],
                        params=dict(spec.get("params") or {}),
                        condition=spec.get("condition"),
                    )
                    for spec in specs
                ],
                source=source,
            )
        except BindError:
            # Fail closed, exactly as an unmodeled room text does: a spec the
            # registry doesn't know produces no effect rather than a wrong one.
            return []
    def monstrosity(self, obj: GameObject, amount: int) -> bool:
        """RULE 701.37a: "If this permanent isn't monstrous, put ``amount``
        +1/+1 counters on it and it becomes monstrous."

        One atomic primitive rather than counters-plus-a-flag at the call
        site, for the same reason `RenownEffect` is one (RULE 702.112b): the
        701.37a guard, the counters and the designation are a single
        conditional — a monstrosity ability activated a second time must put
        *no* counters on, which two separate steps would get wrong.

        Returns whether it actually became monstrous, so a caller that has
        follow-up behaviour ("monstrosity 3. When it becomes monstrous, …")
        can tell the no-op case apart. ``amount`` is clamped at 0: a
        "monstrosity X" with X=0 still flips the designation (701.37a puts
        zero counters on, which is a legal number of counters to put on) and
        still fires the trigger.
        """
        if obj.is_monstrous:
            return False
        self.add_counters(obj, max(0, int(amount)), "+1/+1", source=obj)
        obj.is_monstrous = True
        # RULE 701.37c: another ability of this permanent may refer to the X
        # it became monstrous with, so remember the announced value.
        obj.monstrosity_x = max(0, int(amount))
        self.state.fire_event(
            GameEvent(
                EventType.BECAME_MONSTROUS,
                instance_id=obj.instance_id,
                controller_id=obj.controller_id,
                object=obj.name,
                object_types=sorted(obj.type_words),
                amount=obj.monstrosity_x,
            )
        )
        return True
    def adapt(self, obj: GameObject, amount: int) -> bool:
        """RULE 701.46a: "If this permanent has no +1/+1 counters on it, put
        ``amount`` +1/+1 counters on it."

        Monstrosity's sibling and deliberately *not* the same primitive: the
        gate is the permanent's current counters, not a designation, so adapt
        can happen again and again as counters come and go, and there is no
        "becomes adapted" event to fire (701.46 defines no designation — the
        real cards' "as long as ~ has a +1/+1 counter on it" statics read the
        counters directly, which the layer engine's existing ``min_level``
        gate already does).
        """
        if obj.counters.get("+1/+1", 0) > 0 or obj.plus_one_counters > 0:
            return False
        self.add_counters(obj, max(0, int(amount)), "+1/+1", source=obj)
        return True
    def harness(self, obj: GameObject) -> bool:
        """MEC-79 / RULE 701.64a: "Harness [this permanent]" — "if this
        permanent isn't harnessed, it becomes harnessed."

        `monstrosity`'s designation-flip half without the counters or the
        amount: the Marvel Infinity Stones' ``{cost}, {T}: Harness ~`` ability.
        Idempotent (701.64a's guard) and returns whether it actually flipped,
        so a caller with follow-up behaviour can tell the no-op apart. Fires
        `HARNESSED` only on the transition. 701.64b's "stays harnessed until it
        leaves the battlefield" is `GameObject.reset_as_new_object` (RULE 400.7).
        """
        if obj.harnessed:
            return False
        obj.harnessed = True
        self.state.fire_event(
            GameEvent(
                EventType.HARNESSED,
                instance_id=obj.instance_id,
                controller_id=obj.controller_id,
                object=obj.name,
                object_types=sorted(obj.type_words),
            )
        )
        return True
    def recruit(self, player: Player) -> None:
        """"Recruit" (RULE 701.70a — Tales of Middle-earth): ``player`` draws
        a card, then discards a card; if the discarded card was a **nonland**
        card, they create a 1/1 white Human Soldier creature token.

        The "which card to discard" is a `recruit` `pending_choice`
        (`_resume_recruit`) whenever the hand has 2+ cards after the
        draw; one card → discarded with no choice, an empty hand → the
        discard simply doesn't happen (RULE 701.70a is "discard a card", not
        "you may"). The nonland check + token are `_recruit_discard`.
        Deliberately its own small primitive rather than reusing
        `_request_choose_objects`'s ``connive`` machinery — the payoff is a
        token, not a counter on a source, and this shape (draw, then a
        mandatory conditional discard) is the same `explore_bin`/`bolster`
        idiom the other PAR-29 keyword actions use.
        """
        self.draw(player, 1)
        if not player.hand:
            return
        if len(player.hand) == 1:
            self._recruit_discard(player, player.hand[0])
            return
        self.open_choice({
            "kind": "recruit",
            "player_id": player.id,
            "prompt": "Rekrutieren: welche Karte abwerfen?",
            "options": [
                {"id": str(o.instance_id), "label": o.name, "instance_id": o.instance_id}
                for o in player.hand
            ],
        })
    def _recruit_discard(self, player: Player, card: GameObject) -> None:
        """The discard + conditional token half of `recruit` (RULE
        701.70a). ``is_land`` is read before the move — a card-type property
        unaffected by zone, but the obviously-correct order (the same one
        `_apply_chosen_object`'s connive branch uses)."""
        is_land = card.is_land
        self.discard_specific(card)
        if not is_land:
            from ...services.token_database import synthesize_token_card  # function-scoped: avoid cycle

            token = synthesize_token_card(
                name="Soldier", power=1, toughness=1, colors=["W"],
                subtypes=["Human", "Soldier"],
            )
            self.create_token(player.id, token, 1)
    @continuations.choice("recruit", answer=continuations.ANSWER_INT, rule="701.70")
    def _resume_recruit(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer a pending `recruit` discard choice. A missing/unknown answer
        defaults to the first card — RULE 701.70a's discard is mandatory."""
        player = self.state.player_by_id(choice["player_id"])
        offered = [opt["instance_id"] for opt in choice["options"]]
        chosen_id = instance_id if instance_id in offered else (offered[0] if offered else None)
        card = next(
            (o for o in player.hand if o.instance_id == chosen_id), None
        )
        if card is None and player.hand:
            card = player.hand[0]
        if card is not None:
            self._recruit_discard(player, card)
        self.check_state_based_actions()
    def learn(self, player: Player, source: Optional[GameObject] = None) -> None:
        """"Learn" (RULE 701.48a — Strixhaven): ``player`` may **either**
        reveal a Lesson card they own from outside the game and put it into
        their hand, **or** discard a card, then — if they discarded a card
        this way — draw a card.

        **Documented simplification:** the "Lesson from outside the game"
        branch is dropped. This engine has no sideboard / outside-the-game
        zone with any Commander-legal use (the same call the `ability_
        catalogue` already makes for Karn's -2, `entries_010.py`), so Learn
        collapses to its other, fully-modelable half: an optional
        discard-a-card-then-draw-a-card, driven straight through
        `_request_choose_objects`'s existing ``optional`` + ``then_specs``
        machinery (a real discard fires the draw; a decline does nothing).
        An empty hand → nothing happens (nothing to discard, and the Lesson
        branch is gone).
        """
        if not player.hand:
            return
        self._request_choose_objects(
            player, list(player.hand), "discard", count=1, optional=True,
            prompt="Lernen — eine Karte abwerfen, dann eine Karte ziehen?",
            source=source,
            then_specs=[{"type": "draw", "params": {"count": 1}}],
        )
    def collect_evidence_possible(self, player: Player, amount: int) -> bool:
        """Whether ``player``'s graveyard holds cards whose **total mana
        value** is ``amount`` or greater (RULE 701.59a) — the affordability
        check shared by every "collect evidence N" cost site."""
        total = sum(c.card.converted_mana_cost for c in player.graveyard)
        return total >= amount

    def collect_evidence(self, player: Player, amount: int) -> bool:
        """RULE 701.59a: exile cards from ``player``'s graveyard whose total
        mana value is ``amount`` or greater, then fire
        `EventType.COLLECTED_EVIDENCE` (701.59b — process-complete, fired
        even if ``amount`` was 0). Returns whether the exile met the
        threshold.

        **Documented simplification:** which cards leave is an auto-choice
        — **highest** mana value first, so the *fewest* cards are spent to
        clear the threshold — rather than an interactive pick. The same
        "auto-pick, no chooser in this MVP" idiom `_pay_escape_graveyard_
        cost` / `discard` / `put_hand_cards_on_top` already use for a
        value-neutral cost selection.
        """
        picked: list[GameObject] = []
        running = 0
        for card in sorted(
            player.graveyard, key=lambda c: c.card.converted_mana_cost, reverse=True
        ):
            if running >= amount:
                break
            picked.append(card)
            running += card.card.converted_mana_cost
        met = running >= amount
        for card in picked:
            self.exile(card)
        self.state.fire_event(GameEvent(
            EventType.COLLECTED_EVIDENCE,
            player_id=player.id, controller_id=player.id, amount=amount,
        ))
        return met
    def forage_possible(self, player: Player) -> bool:
        """Whether ``player`` could forage right now (RULE 701.61a) — three
        cards in their graveyard to exile, or a Food they control to
        sacrifice."""
        if len(player.graveyard) >= 3:
            return True
        return any(
            continuous.has_subtype(o, "Food")
            for o in self.state.permanents_controlled_by(player.id)
        )

    def forage(self, player: Player) -> bool:
        """RULE 701.61a: ``player`` exiles three cards from their graveyard
        **or** sacrifices a Food. Fires `EventType.FORAGED` afterwards
        (701.61b — process-complete, fired even if neither was possible).
        Returns whether either option was actually carried out.

        **Documented simplification:** no interactive choice between the two
        halves — a Food is sacrificed whenever ``player`` controls one
        (keeping the three graveyard cards, the strictly more valuable
        line), otherwise the three oldest graveyard cards are exiled (the
        same "auto-pick, no chooser in this MVP" idiom `collect_evidence` /
        `_pay_escape_graveyard_cost` use).
        """
        did = False
        foods = [
            o for o in self.state.permanents_controlled_by(player.id)
            if continuous.has_subtype(o, "Food")
        ]
        if foods:
            self.put_into_graveyard(foods[0])  # RULE 701.17 sacrifice
            did = True
        elif len(player.graveyard) >= 3:
            for card in list(player.graveyard)[:3]:
                self.exile(card)
            did = True
        self.state.fire_event(GameEvent(
            EventType.FORAGED, player_id=player.id, controller_id=player.id,
        ))
        return did
    #: The four bending keyword actions (RULE 701.6x — Avatar: The Last
    #: Airbender). `record_bend`'s ``kind`` is one of these.
    BEND_KINDS = ("waterbend", "earthbend", "firebend", "airbend")
    def record_bend(
        self, player: Player, kind: str, amount: int = 0,
        source: Optional[GameObject] = None,
    ) -> None:
        """Register that ``player`` has performed a bending keyword action
        (RULE 701.6x — ``kind`` in `BEND_KINDS`): stamp `GameState.
        bends_this_turn` and fire `EventType.BENT`.

        Called from each bending primitive once its own procedure is
        complete — `earthbend` (after the land is animated + countered),
        the waterbend additional-cast-cost payment (RULE 701.67c — "triggers
        whenever that player pays a waterbend cost"), `ExileEffect` with
        ``bend_kind`` set (airbend), and the Firebending attack trigger's
        `RecordBendEffect` marker. Mirrors `collect_evidence`/`forage`/
        `behold`: fire an event so a "whenever you `<bend>`" trigger (Avatar
        Aang) can see an action that otherwise leaves no board trace.
        """
        if kind not in self.BEND_KINDS:
            return
        self.state.bends_this_turn.setdefault(player.id, set()).add(kind)
        self.state.fire_event(GameEvent(
            EventType.BENT,
            player_id=player.id, controller_id=player.id,
            kind=kind, amount=int(amount or 0),
        ))
    def behold(
        self, player: Player, quality: str, source: Optional[GameObject] = None
    ) -> bool:
        """"Behold" (RULE 701.4a — Tarkir: Dragonstorm): ``player`` reveals a
        permanent they control with ``quality``, or a card with ``quality``
        from their hand. Returns whether a behold actually happened (a
        matching object existed to reveal), firing `EventType.BEHELD` in
        that case.

        ``quality`` is a creature-type word for every real card that uses
        this (dragon/elf/kithkin/merfolk), matched case-insensitively via
        `continuous.has_subtype` against the printed type line — the same
        substring approach the "tap N Elves you control" cost uses.

        Beholding has no game-state effect of its own; it's the reveal that
        matters at a real table. In this engine it's reached as an
        *additional cast cost* ("behold a dragon or pay {N}") — see
        `GameEngine._pay_additional_cast_cost` and the **documented
        simplification** there (the "or pay {N}" alternative isn't modeled,
        mirroring the existing `_ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE`
        precedent): a spell casts whether or not the behold succeeds.
        """
        revealed: Optional[GameObject] = None
        for obj in self.state.battlefield:
            if obj.controller_id == player.id and continuous.has_subtype(obj, quality):
                revealed = obj
                break
        if revealed is None:
            for card_obj in player.hand:
                if continuous.has_subtype(card_obj, quality):
                    revealed = card_obj
                    break
        if revealed is None:
            return False
        self.state.fire_event(GameEvent(
            EventType.BEHELD,
            player_id=player.id, controller_id=player.id,
            instance_id=revealed.instance_id, quality=quality,
        ))
        return True
    def time_travel(self, player: Player, times: int = 1) -> None:
        """"Time travel" (RULE 701.56a — Doctor Who): "For each suspended
        card you own and each permanent you control with a time counter on
        it, you may add or remove a time counter." ``times`` repeats the
        whole process ("time travel, then time travel").

        **Documented simplification** — no per-object interactive add/
        remove choice: a **suspended card** ``player`` owns loses one time
        counter (acceleration — the reason to time travel your own
        suspended spells; if that empties it, the RULE 702.62a free-cast
        window opens exactly as the upkeep trigger would), and a
        **Vanishing/Fading**-style permanent ``player`` controls (a time
        counter on a battlefield permanent) gains one (prolongs it — the
        reason to time travel those). Both are the beneficial-to-you
        direction. A time counter on something that is neither is left
        alone.
        """
        for _ in range(max(1, int(times))):
            for obj in list(player.exile):
                if obj.owner_id != player.id or obj.counters.get("time", 0) <= 0:
                    continue
                if not _has_suspend(obj):
                    continue
                obj.add_counters("time", -1)
                if obj.counters.get("time", 0) <= 0:
                    if getattr(obj.card, "is_creature", False):
                        obj.granted_suspend_haste = True
                    self.grant_free_cast_window_from_exile(obj)
            for obj in self.state.permanents_controlled_by(player.id):
                if obj.counters.get("time", 0) > 0:
                    obj.add_counters("time", 1)
        self.check_state_based_actions()
    def _endure_make_token(self, player: Player, amount: int) -> None:
        """The token half of `endure` (RULE 701.63a) — an N/N white Spirit
        creature token."""
        from ...services.token_database import synthesize_token_card  # function-scoped: avoid cycle

        card = synthesize_token_card(
            name="Spirit", power=amount, toughness=amount, colors=["W"]
        )
        self.create_token(player.id, card, 1)
    def endure(
        self, permanent: Optional[GameObject], amount: int, player: Optional[Player] = None
    ) -> None:
        """"Endure N" (RULE 701.63a — Bloomburrow): the controller of
        ``permanent`` **either** puts N +1/+1 counters on it **or** creates an
        N/N white Spirit creature token.

        A genuine modal choice (`endure` `pending_choice`,
        `_resume_endure`) — but only when the counters branch is
        actually possible: if ``permanent`` has left the battlefield or isn't
        a creature, only the token is available (RULE 608.2b), so it resolves
        without asking. Counters go on through `add_counters` so RULE 122.5
        triggers and doublers apply; the token through `create_token`.
        """
        if amount <= 0:
            return
        controller_id = getattr(permanent, "controller_id", None)
        if player is None and controller_id is not None:
            try:
                player = self.state.player_by_id(controller_id)
            except KeyError:
                player = None
        if player is None:
            return
        counters_possible = (
            permanent is not None
            and getattr(permanent, "is_creature", False)
            and permanent in self.state.battlefield
        )
        if not counters_possible:
            self._endure_make_token(player, amount)
            return
        self.open_choice({
            "kind": "endure",
            "player_id": player.id,
            "amount": amount,
            "permanent_id": permanent.instance_id,
            "prompt": f"Ausharren {amount}: {amount} +1/+1-Marken oder ein {amount}/{amount} weißer Geist-Token?",
            "options": [
                {"id": "counters", "label": f"{amount} +1/+1-Marken auf {permanent.name}"},
                {"id": "token", "label": f"{amount}/{amount} weißer Geist-Token"},
            ],
        })
    @continuations.choice(
        "endure",
        answer=continuations.ANSWER_FLAG,
        yes="token",
        rule="701.63",
    )
    def _resume_endure(self, choice: dict[str, Any], to_token: bool = False) -> None:
        """Answer a pending `endure` choice. A missing/unknown answer defaults
        to the counters branch (the permanent is still there — RULE 701.63a
        has no "you may", one of the two must happen)."""
        player = self.state.player_by_id(choice["player_id"])
        amount = int(choice["amount"])
        perm = self._object_by_instance_id(choice.get("permanent_id"))
        if not to_token and perm is not None and perm in self.state.battlefield:
            self.add_counters(perm, amount, "+1/+1", source=perm)
        else:
            # token chosen, or "it" left the battlefield before resolution
            self._endure_make_token(player, amount)
        self.check_state_based_actions()
    def goad(self, obj: GameObject, goader_id: str, permanent: bool = False) -> None:
        """RULE 701.15a: ``goader_id`` goads ``obj`` until their next turn.

        The designation is stored on the creature as the *set* of players who
        have goaded it (RULE 701.15c — several players goading one creature
        each add their own combat requirement; 701.15d — the same player
        goading twice adds nothing, which a set gives for free). Expiry is
        `GameEngine.begin_turn`'s job: "until the next turn of the
        controller" means the entry is dropped as that player's turn begins.

        ``permanent`` is the "…goaded **for the rest of the game**" wording
        (Rendmaw, Jon Irenicus): same designation, no expiry, so it goes in
        the sibling set the turn-begin sweep leaves alone.

        Goading a creature that isn't a creature, or one already goaded by
        this player, is legal and simply records/re-records the designation —
        the event fires either way, since "whenever you goad" cares that the
        action happened (701.15d only makes the *requirement* a no-op).
        """
        (obj.goaded_permanently if permanent else obj.goaded_by).add(goader_id)
        self.state.fire_event(
            GameEvent(
                EventType.GOADED,
                instance_id=obj.instance_id,
                goader_id=goader_id,
                controller_id=goader_id,
                object=obj.name,
                object_types=sorted(obj.type_words),
            )
        )
    def suspect(self, obj: Optional[GameObject]) -> None:
        """RULE 701.60a: ``obj`` becomes **suspected** (menace + can't block,
        RULE 701.60b — both read off `GameObject.is_suspected` at combat
        time, `combat.is_suspected`).

        A no-op if ``obj`` isn't a creature. Re-suspecting an already-
        suspected creature is legal and changes nothing (RULE 701.60c), but
        the event fires either way — "whenever you suspect a creature" cares
        that the action happened, mirroring `goad`.
        """
        if obj is None or not getattr(obj, "is_creature", False):
            return
        # PAR-30 Suspect one-off shapes / RULE 701.60c — a static "can't
        # become suspected" (Airtight Alibi, hand-authored) rides a
        # ``grant_keyword`` slug the layer engine stamps onto the affected
        # creature; honour it here, the one place the designation is applied.
        if "cant_become_suspected" in getattr(obj, "granted_keywords", ()):
            return
        obj.is_suspected = True
        self.state.fire_event(
            GameEvent(
                EventType.SUSPECTED,
                instance_id=obj.instance_id,
                controller_id=obj.controller_id,
                object=obj.name,
                object_types=sorted(obj.type_words),
            )
        )
    def detain(self, obj: Optional[GameObject], detainer_id: str) -> None:
        """RULE 701.35a: ``detainer_id`` detains ``obj`` until their next turn.

        Stored as the *set* of players detaining it (mirroring `goad` — in
        practice always one), so `GameEngine.begin_turn` can drop it the same
        way it drops goad, "until the next turn of the controller of the
        spell or ability" (RULE 701.35b). While detained, RULE 701.35b's
        three consequences — can't attack, can't block, activated abilities
        can't be activated — are enforced by `_can_attack` / `can_block` /
        `can_activate` consulting `combat.is_detained`.

        A no-op-safe re-detain (already detained by this player) still fires
        the event, like `goad`/`suspect`.
        """
        if obj is None or getattr(obj, "instance_id", None) is None:
            return
        obj.detained_by.add(detainer_id)
        self.state.fire_event(
            GameEvent(
                EventType.DETAINED,
                instance_id=obj.instance_id,
                detainer_id=detainer_id,
                controller_id=detainer_id,
                object=obj.name,
                object_types=sorted(obj.type_words),
            )
        )
    def remove_suspected(self, objs: list[GameObject]) -> None:
        """"... is/are no longer suspected." (RULE 701.60a's reverse) — clear
        the designation on each of ``objs``. Used both for the mass
        "all suspected creatures are no longer suspected" (Absolving Lammasu)
        and a single named creature."""
        for obj in objs:
            if obj is not None:
                obj.is_suspected = False
    def clash(self, player: Optional[Player], with_opponent: bool = True) -> bool:
        """RULE 701.30: ``player`` clashes — reveals the top card of their
        library — and, for "clash with an opponent" (``with_opponent``, RULE
        701.30b), one opponent reveals theirs too. Returns whether ``player``
        **won** (RULE 701.30d — their revealed card's mana value is strictly
        higher than every other card revealed in the clash), which the "if
        you win, `<effect>`. / otherwise, `<effect>`." branch reads back via
        `effects.ClashEffect` → `GameContext.clash_won`.

        **Documented simplification** — RULE 701.30a's "may then put that card
        on the bottom of their library" is always declined here: every
        revealed card stays on top. Modeling that optional bottoming means an
        APNAP pair of interactive yes/no pauses (RULE 701.30c) for a keyword
        action ~33 cache cards use, and it never changes *this* resolution's
        win/lose outcome — only a later draw. Same accepted "an undecided
        beneficial *may* is declined" convention `effects.CoinFlipEffect`
        documents.

        With no opponent at all (a 1-player Goldfisch/Replay board) or every
        opponent's library empty, no *other* card is revealed, so ``player``
        wins on the strength of their own reveal alone — a deliberate reading
        of 701.30b's "choose an opponent" when there is none, keeping clash
        cards functional in solo play. If ``player``'s own library is empty
        they reveal nothing and cannot win.

        Fires `EventType.CLASHED` (always, for "whenever you clash") and
        `EventType.WON_CLASH` (only on a win, for "whenever you win a clash").
        """
        if player is None:
            return False
        top = player.library[-1] if player.library else None
        my_mv = top.card.converted_mana_cost if top is not None else -1
        other_mvs: list[int] = []
        #: RULE 701.30b: which opponent this clash was "with" — recorded so a
        #: following "if you win, `<X> that player <does Y>`" / "otherwise,
        #: that player …" branch (Captivating Glance, Pollen Lullaby) has a
        #: referent. **Documented simplification** (same as `GainControlBy
        #: SourceEffect`): the first living opponent, not an interactive
        #: "choose an opponent" pick — unambiguous in 1v1 goldfish/Replay,
        #: auto-picked in multiplayer. Read back via `effects.ClashEffect`
        #: → `GameContext.clashed_opponent`.
        self._last_clash_opponent_id = None
        if with_opponent:
            for opp in self.state.living_players():
                if opp.id == player.id:
                    continue
                if self._last_clash_opponent_id is None:
                    self._last_clash_opponent_id = opp.id
                opp_top = opp.library[-1] if opp.library else None
                if opp_top is not None:
                    other_mvs.append(opp_top.card.converted_mana_cost)
        won = top is not None and all(my_mv > mv for mv in other_mvs)
        self.state.fire_event(GameEvent(
            EventType.CLASHED, player_id=player.id, controller_id=player.id, won=won,
        ))
        if won:
            self.state.fire_event(GameEvent(
                EventType.WON_CLASH, player_id=player.id, controller_id=player.id,
            ))
        return won

    def become_monarch(self, player: Player) -> None:
        """RULE 725.3: ``player`` becomes the monarch; whoever held it
        (possibly ``player`` themself) ceases to."""
        self.state.monarch_id = player.id

    def start_engines(self, player: Player) -> None:
        """RULE 702.179a/c: ``player``'s speed becomes 1 if they currently
        have no speed. Idempotent — a no-op once they have any speed at all
        (the SBA that calls this re-checks every pass)."""
        if int(getattr(player, "speed", 0) or 0) == 0:
            player.speed = 1

    def increase_speed(self, player: Player, amount: int = 1) -> None:
        """RULE 702.179c/d: raise ``player``'s speed by ``amount``, capped at
        the maximum of 4 (RULE 702.179e). A player with no speed who is told
        to increase it has their speed *become* that amount (702.179c)."""
        current = int(getattr(player, "speed", 0) or 0)
        player.speed = min(4, (amount if current == 0 else current + amount))
    def get_city_blessing(self, player: Player) -> None:
        """RULE 702.131a-c: ``player`` gets the city's blessing.

        Unlike Monarch/Initiative this is a plain idempotent per-player flag
        rather than a single shared holder — "any number of players may have
        the city's blessing at the same time", and once granted it lasts
        "for the rest of the game" (702.131c/d), so a second Ascend firing
        while the player already has it is simply a no-op, same as
        `monstrosity`'s "isn't monstrous" gate rather than `take_initiative`'s
        unconditional re-fire.
        """
        if player.has_city_blessing:
            return
        player.has_city_blessing = True
    def take_initiative(self, player: Player) -> None:
        """RULE 726.3: ``player`` takes the initiative; whoever held it
        (possibly ``player`` themself) ceases to.

        RULE 726.5: a player who *already* has the initiative and is told to
        take it doesn't gain a second designation, but the "whenever a player
        takes the initiative" ability still triggers — which is why the event
        is announced unconditionally rather than only on a change of holder.
        """
        self.state.initiative_id = player.id
        self.state.fire_event(
            GameEvent(
                EventType.TOOK_INITIATIVE, player_id=player.id, controller_id=player.id
            )
        )
    #: The closed vocabulary `_request_choose_objects` accepts, mapping each
    #: action name to what it does to a chosen object. Deliberately small
    #: and data-only: the whole choice (candidates, action, how many are
    #: left) lives in `GameState.pending_choice`, so it survives the
    #: `clone()` undo snapshots takes — unlike a callback, which is why
    #: this replaced the "auto-pick the first candidate" convention rather
    #: than passing a continuation closure around.
    CHOOSE_OBJECT_ACTIONS = frozenset(
        {
            "tap", "sacrifice", "return_to_hand", "return_from_graveyard", "soulbond_pair", "library_top", "discard",
            "library_to_hand", "sacrifice_for_descendants_fury",
            # Quandrix Command mode 4 ("target player shuffles up to three
            # target cards from their graveyard into their library") — the
            # pick moves from its owner's graveyard to its owner's library,
            # which is then shuffled (RULE 701.20). A graveyard-zone pick,
            # unlike the battlefield/hand actions around it.
            "graveyard_to_library",
            # PAR-13 (Dungeon of the Mad Mage's "Mad Wizard's Lair" — "Draw
            # three cards and reveal them. You may cast one of them without
            # paying its mana cost."): a hand-zone pick, unlike every other
            # action above (all battlefield picks), cast through the
            # ordinary free-cast path (`RulesEngine.cast_without_paying`) —
            # general enough for any future "reveal some cards, cast one
            # free" template to reuse rather than a one-off.
            "cast_free",
            # Gemstone Caverns' "if you do, exile a card from your hand"
            # pregame-setup tail (`offer_opening_hand_battlefield_choice`) —
            # another hand-zone pick, general enough for any future "exile a
            # card from your hand" cost/effect to reuse.
            "exile",
            # MEC-20 (the "Expertise" cycle): another hand-zone pick, but
            # unlike ``"cast_free"`` this only *arms* the pick's temporary
            # free-cast permission (`GameState.free_cast_instance_ids`)
            # rather than casting it immediately — a hand card is already a
            # legal cast zone, so the caster casts it (or doesn't) through
            # the ordinary `legal_actions` cast option afterward, getting
            # its full targeting/modal choices. See `FreeCastFromHandEffect`.
            "grant_free_cast",
            # MEC-26 (Scheming Fence's "As this creature enters, you may
            # choose a nonland permanent."): stamps the pick onto
            # ``source``'s own `GameObject.chosen_permanent_id` rather than
            # acting on the chosen object at all — the object-choice
            # sibling of ``remember``'s `linked_exile_id` stamp, its own
            # action rather than overloading ``remember`` since nothing
            # here gets exiled.
            "choose_permanent",
            # MEC-30 (RULE 615/616.1d "a source of your choice" — Circle of
            # Protection/Rune of Protection): nothing happens to the chosen
            # permanent either — it opens a `prevent_damage_to_player`/
            # `_to_target`-shaped shield scoped to it, via the choice's own
            # ``prevent_shield`` payload (`_request_choose_objects`'s own
            # docstring).
            "remember_source",
            # MEC-30 (RULE 616.1c "that damage is dealt to `<X>` instead" —
            # Opal-Eye, Konda's Yojimbo): the redirect sibling of
            # ``remember_source`` just above — same chooser, but opens
            # `RulesEngine.redirect_damage_from_source` via the choice's own
            # ``redirect_shield`` payload instead of a prevention shield.
            "remember_source_redirect",
            # MEC-30 (Desperate Gambit — "Choose a source you control and
            # flip a coin. If you win, ... double ... . If you lose, ...
            # prevent ..."): the chosen permanent IS the coin flip's own
            # subject, so no shield payload is needed at all — the coin is
            # flipped and the branch resolved entirely inside
            # `_apply_chosen_object`.
            "remember_source_coinflip",
            # MEC-41 (Nissa, Steward of Elements' 0 ability — "Look at the
            # top card of your library. ... you may put that card onto the
            # battlefield."): a library-zone pick, unlike every other
            # action above — general enough for any future "look at the
            # top card, you may put it onto the battlefield" template to
            # reuse rather than a one-off.
            "library_to_battlefield",
            # MEC-43 round 4D (Kodama of the East Tree — "you may put a
            # permanent card with equal or lesser mana value from your
            # hand onto the battlefield"): a hand-zone pick placed
            # straight onto the battlefield, the hand-zone sibling of
            # ``"library_to_battlefield"`` just above. Stamps
            # `GameObject.entered_via_ability_id` so a Panharmonicon-
            # shaped "if it wasn't put onto the battlefield with this
            # ability" trigger guard (`effect_binder`'s
            # ``not_entered_via_self`` condition) can tell a card THIS
            # ability just placed apart from any other entering permanent.
            "hand_to_battlefield",
            # MEC-73: Sneak Attack / Incandescent Soulstoke's selected hand
            # creature enters with haste and a RULE 603.7 delayed sacrifice.
            "hand_to_battlefield_haste_sacrifice",
            # MEC-46 (Expropriate — "choose a permanent owned by the voter
            # and gain control of it"): the chosen permanent's control
            # moves to the *chooser* (``player``), indefinitely (RULE 701.38
            # outcome body, no duration — a bare `controller_id`
            # reassignment, the same shape `GainControlBySourceEffect`
            # uses). Nothing else happens to it.
            "gain_control",
            # PAR-30 (RULE 701.10i residue — Cultural Exchange): the same
            # bare `controller_id` reassignment as `"gain_control"`, but to
            # a specific *other* player named by `control_recipient_id`
            # rather than to the chooser.
            "gain_control_for",
            # PAR-30 Suspect one-off shapes / RULE 701.60a's reverse ("You
            # may have it become no longer suspected." — Deadly
            # Complication): nothing is created or moved, the pick just
            # clears its own suspected designation. ``optional`` so declining
            # keeps the menace a suspected creature has.
            "remove_suspected",
            # "Remove any number of counters from among permanents on the
            # battlefield. You draw cards and lose life equal to the number
            # of counters removed this way." (Eventide's Shadow) — each
            # chosen permanent has *all* its counters removed (a documented
            # permanent-granularity simplification of "any number of
            # counters", the same RULE 122 precision `MoveCountersEffect`
            # already accepts); the caller tallies the total via a
            # cards-removed delta in its ``then_specs``.
            "strip_all_counters",
            # Immoral Bargain (PAR-60 round 4) — "Destroy X target nonland
            # permanents", where X is only known after the additional-cost
            # sacrifice is resolved: the destroy sibling of ``sacrifice``,
            # applying `RulesEngine.destroy` (RULE 701.7, regeneration- and
            # indestructible-respecting) to any battlefield permanent, not
            # only the chooser's own.
            "destroy",
        }
    )
    def _request_choose_objects(
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
        remember: bool = False,
        track_exiled_with: bool = False,
        prevent_shield: Optional[dict] = None,
        redirect_shield: Optional[dict] = None,
        connive: bool = False,
        else_specs: Optional[list[dict]] = None,
        control_recipient_id: Optional[str] = None,
        rest_ids: Optional[list[int]] = None,
        rest_destination: Optional[str] = None,
        decline_leaves_untouched: bool = False,
    ) -> None:
        """Open a "choose N of these objects" decision (RULE 601.2c-style).

        The general chooser for every effect that names *what kind* of
        object to act on but leaves *which one* to the player: Cloudstone
        Curio's bounce, Tangle Wire's tap, Tevesh Szat's and Professor
        Onyx's sacrifices, Deadeye Navigator's Soulbond partner, Lim-Dûl's
        Vault's and Thassa's Oracle's library reordering. Each of those used
        to auto-pick the first legal candidate.

        Offered one object at a time (`_resume_choose_objects`
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

        ``remember=True`` (MEC-17, Imprint — Chrome Mox's own "you may
        exile a nonartifact, nonland card from your hand") additionally
        stamps whichever object gets ``action="exile"``ed onto ``source``'s
        own `GameObject.linked_exile_id` — the same field an `ExileEffect`
        with its own ``remember=True`` already uses for the O-Ring-shaped
        "when this leaves, return the exiled card" half, reused here so a
        later mana ability/static can read back *which* card this
        permanent has imprinted. Only meaningful with ``count=1`` (a
        multi-pick "remembers" only its own last pick, overwriting the
        rest — no printed Imprint card needs more than one).

        ``track_exiled_with=True`` (MEC-12, Abdel Adrian, Gorion's Ward —
        "exile **any number of** other nonland permanents you control") is
        ``remember``'s accumulating sibling for a *multi*-pick exile,
        mirroring `ExileEffect.track_exiled_with`'s own `GameObject.
        exiled_with_ids` list exactly (every pick appended, not just the
        last), for a "choose N/any number, unlike a RULE 115 target" shape
        `ExileEffect`'s own target-gathering can't express — there is no
        "target" here at all, just a selection among permanents this
        player controls.

        ``prevent_shield`` (MEC-30, ``action="remember_source"`` only —
        RULE 615/616.1d's "a source of your choice") carries the shield to
        open once a pick is made: ``{"recipient_id", "recipient_is_player",
        "amount", "rider"}``, resolved by `_apply_chosen_object` into a
        `RulesEngine.prevent_damage_to_player`/`_to_target` call scoped to
        whichever permanent gets picked. Carried as data on the choice, like
        ``then_specs``, so it survives the state `clone()` undo takes.

        ``redirect_shield`` (MEC-30, ``action="remember_source_redirect"``
        only — RULE 616.1c "that damage is dealt to `<X>` instead", Opal-Eye)
        is ``prevent_shield``'s redirect sibling: ``{"recipient_id",
        "recipient_is_player", "amount"}``, resolved into a `RulesEngine.
        redirect_damage_from_source` call instead.

        ``else_specs`` are ``then_specs``' mirror: serialized `EffectSpec`
        dicts applied only when the choice ends with **nothing** picked —
        the "**If you don't**, incubate 3." half of Traumatic Revelation's
        "you may choose a creature or battle card … If you don't, …". Also
        fires when the candidate pool is empty to begin with (no legal card
        to choose ⇒ "you didn't"). Carried as data on the choice so it
        survives the `clone()` undo takes.

        ``connive=True`` (RULE 701.47, MEC-43 — Ledger Shredder's "this
        creature connives") marks an ``action="discard"`` pick for the
        conditional half connive's own template needs: "if a **nonland**
        card was discarded this way, put a +1/+1 counter on it [the
        conniving permanent]." Unlike ``then_specs_if_commander`` (a plain
        boolean gate on *whether any pick happened to be one*), this
        depends on *which* card was picked, so it's threaded straight
        through to `_apply_chosen_object` rather than tracked as a
        choice-level flag the way ``commander_taken`` is.

        ``control_recipient_id`` (PAR-30 — Cultural Exchange's "choose any
        number of creatures target player controls[.] … control moves to a
        **third** player, not the chooser") is ``action="gain_control_for"``'s
        own payload: unlike the plain ``"gain_control"`` action (control
        moves to ``player``, the chooser), this hands each pick to whichever
        player's id is carried here instead — the caster picks, but someone
        *else* receives.
        """
        if action not in self.CHOOSE_OBJECT_ACTIONS:
            raise ValueError(f"unknown choose-objects action {action!r}")
        pool = [obj for obj in candidates if obj is not None]
        if not pool or count <= 0:
            # Nothing to choose ⇒ "you didn't choose" — run the else branch
            # (Traumatic Revelation's "If you don't, incubate 3." when the
            # revealed hand holds no creature or battle card).
            if not pool and count > 0 and else_specs:
                self._apply_effect_specs(list(else_specs), source)
            return
        if len(pool) <= count and not optional:
            # Forced: every candidate is taken anyway, so asking would be
            # theatre. (An *optional* one still asks — declining matters.)
            commander_taken = False
            for obj in pool:
                commander_taken = commander_taken or obj.is_commander
                self._apply_chosen_object(
                    player, obj, action, source, remember=remember,
                    track_exiled_with=track_exiled_with, prevent_shield=prevent_shield,
                    redirect_shield=redirect_shield, connive=connive,
                    control_recipient_id=control_recipient_id,
                )
            if rest_destination and rest_ids:
                taken_ids = {o.instance_id for o in pool}
                unpicked_rest = [iid for iid in rest_ids if iid not in taken_ids]
                self._handle_rest_inspected(player, unpicked_rest, rest_destination)
            self._apply_choose_objects_tail(
                source, then_specs, then_specs_if_commander, commander_taken
            )
            return
        self.open_choice(self._choose_objects_choice(
            player, pool, action, count, optional, prompt,
            source_id=source.instance_id if source is not None else None,
            picked=[], then_specs=then_specs,
            then_specs_if_commander=then_specs_if_commander, remember=remember,
            track_exiled_with=track_exiled_with,
            prevent_shield=prevent_shield, redirect_shield=redirect_shield,
            connive=connive, else_specs=else_specs,
            control_recipient_id=control_recipient_id,
            rest_ids=rest_ids, rest_destination=rest_destination,
            decline_leaves_untouched=decline_leaves_untouched,
        ))
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
        remember: bool = False,
        track_exiled_with: bool = False,
        prevent_shield: Optional[dict] = None,
        redirect_shield: Optional[dict] = None,
        connive: bool = False,
        else_specs: Optional[list[dict]] = None,
        control_recipient_id: Optional[str] = None,
        rest_ids: Optional[list[int]] = None,
        rest_destination: Optional[str] = None,
        decline_leaves_untouched: bool = False,
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
            # Traumatic Revelation's "If you don't, incubate 3." — applied
            # only when the choice ends with nothing picked (`then_specs`'
            # mirror).
            "else_specs": [dict(spec) for spec in (else_specs or [])],
            # MEC-30: the shield `_apply_chosen_object` opens once a source
            # is picked (``action="remember_source"`` only) — see
            # `_request_choose_objects`'s own docstring.
            "prevent_shield": dict(prevent_shield) if prevent_shield else None,
            # MEC-30: `redirect_shield`'s own sibling — see
            # `_request_choose_objects`'s own docstring.
            "redirect_shield": dict(redirect_shield) if redirect_shield else None,
            # PAR-30: `action="gain_control_for"`'s own recipient payload —
            # see `_request_choose_objects`'s own docstring.
            "control_recipient_id": control_recipient_id,
            "then_specs_if_commander": [
                dict(spec) for spec in (then_specs_if_commander or [])
            ],
            # RULE 903: whether any pick so far was a commander, which the
            # "if a commander was sacrificed this way" tail reads.
            "commander_taken": False,
            # MEC-17: whether this pick should also be remembered onto
            # ``source`` (`GameObject.linked_exile_id`) — see
            # `_request_choose_objects`'s own docstring.
            "remember": remember,
            # MEC-12: whether every ``"exile"`` pick should accumulate onto
            # ``source`` (`GameObject.exiled_with_ids`) — see
            # `_request_choose_objects`'s own docstring.
            "track_exiled_with": track_exiled_with,
            # MEC-43 (RULE 701.47, connive): whether an ``action="discard"``
            # pick should also check the discarded card's own ``is_land``
            # and place a +1/+1 counter on ``source`` — see
            # `_request_choose_objects`'s own docstring.
            "connive": connive,
            "rest_ids": list(rest_ids) if rest_ids else None,
            "rest_destination": rest_destination,
            "decline_leaves_untouched": decline_leaves_untouched,
        }
    @continuations.choice("choose_objects", answer=continuations.ANSWER_INT, rule="601.2b")
    def _resume_choose_objects(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer a pending `choose_objects` decision: apply the action to
        the chosen object, then re-ask while picks remain (or stop on a
        decline — RULE 601.2c's "up to"/"may" shape)."""
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
            self._apply_chosen_object(
                player, chosen, choice["action"], source, remember=bool(choice.get("remember")),
                track_exiled_with=bool(choice.get("track_exiled_with")),
                prevent_shield=choice.get("prevent_shield"),
                redirect_shield=choice.get("redirect_shield"),
                connive=bool(choice.get("connive")),
                control_recipient_id=choice.get("control_recipient_id"),
            )
        remaining_pool = [
            obj
            for obj in self._choose_objects_pool(choice, picked)
            if obj is not None
        ]
        if declined or len(picked) >= choice["count"] or not remaining_pool:
            self.state.pending_choice = None
            if choice.get("rest_destination") and choice.get("rest_ids"):
                if declined and choice.get("decline_leaves_untouched"):
                    pass
                else:
                    unpicked_rest = [iid for iid in choice["rest_ids"] if iid not in picked]
                    self._handle_rest_inspected(player, unpicked_rest, choice["rest_destination"])
            if picked:
                # RULE 601.2c: "if you do, …" only fires when something was
                # actually chosen — a declined optional choice does nothing.
                self._apply_choose_objects_tail(
                    source, choice.get("then_specs"),
                    choice.get("then_specs_if_commander"), commander_taken,
                )
            elif choice.get("else_specs"):
                # "If you don't, incubate 3." (Traumatic Revelation) — the
                # declined-optional-choice branch `then_specs` deliberately
                # skips.
                self._apply_effect_specs(list(choice["else_specs"]), source)
            return
        next_choice = self._choose_objects_choice(
            player, remaining_pool, choice["action"], choice["count"],
            choice["optional"], choice.get("prompt_base", ""),
            source_id=choice.get("source_id"), picked=picked,
            then_specs=choice.get("then_specs"),
            then_specs_if_commander=choice.get("then_specs_if_commander"),
            remember=bool(choice.get("remember")),
            track_exiled_with=bool(choice.get("track_exiled_with")),
            prevent_shield=choice.get("prevent_shield"),
            redirect_shield=choice.get("redirect_shield"),
            connive=bool(choice.get("connive")),
            rest_ids=choice.get("rest_ids"),
            rest_destination=choice.get("rest_destination"),
            decline_leaves_untouched=bool(choice.get("decline_leaves_untouched")),
        )
        next_choice["commander_taken"] = commander_taken
        self.open_choice(next_choice)
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
        remember: bool = False,
        track_exiled_with: bool = False,
        prevent_shield: Optional[dict] = None,
        redirect_shield: Optional[dict] = None,
        connive: bool = False,
        control_recipient_id: Optional[str] = None,
    ) -> None:
        """Do the one thing a `choose_objects` action names to one pick."""
        if action == "tap":
            self.set_tapped(obj, True)
        elif action == "strip_all_counters":
            # Eventide's Shadow: remove every counter from the pick, via the
            # negative-`add_counters` idiom (`ProliferateEffect`/
            # `RemoveCountersEffect`) so a "counter removed" consumer still
            # sees it correctly.
            for kind in list((obj.counters or {}).keys()):
                amount = obj.counters.get(kind, 0)
                if amount:
                    self.add_counters(obj, -amount, kind)
        elif action == "sacrifice":
            # RULE 701.17a: non-destructive, so no regeneration shield saves it.
            self.put_into_graveyard(obj)
        elif action == "destroy":
            # Immoral Bargain (PAR-60 round 4): RULE 701.7 "destroy" — honours
            # regeneration and indestructible, unlike ``sacrifice`` above.
            self.destroy(obj)
        elif action == "return_to_hand":
            self.return_to_hand(obj)
        elif action == "return_from_graveyard":
            self.return_from_graveyard(obj, "battlefield")
        elif action == "graveyard_to_library":
            # Quandrix Command mode 4: move the pick from its owner's
            # graveyard to its owner's library, then shuffle that library
            # (RULE 701.20). ``player`` here is the spell's controller (the
            # chooser), who need not own the card.
            owner = self.state.player_by_id(obj.owner_id)
            if owner is not None and obj in owner.graveyard:
                owner.remove_from_zone(obj, Zone.GRAVEYARD)
                obj.zone = Zone.LIBRARY
                owner.add_to_zone(obj, Zone.LIBRARY)
                self.shuffle_library(owner)
        elif action == "discard":
            # RULE 701.47 (connive, MEC-43 — Ledger Shredder): "if a
            # nonland card was discarded this way, put a +1/+1 counter on
            # it [the conniving permanent]." Checked *before* the move —
            # `GameObject.is_land` is a card-type property unaffected by
            # zone, but reading it off the still-in-hand object is the
            # more obviously-correct order.
            is_land = obj.is_land
            self.discard_specific(obj)
            if connive and not is_land and source is not None:
                self.add_counters(source, 1, kind="+1/+1", source=source)
        elif action == "remember_source" and prevent_shield is not None:
            # MEC-30 (RULE 615/616.1d "a source of your choice" — Circle of
            # Protection/Rune of Protection): the pick becomes a
            # `watched_source_id`, not an action on ``obj`` itself.
            if prevent_shield.get("recipient_scope") == "you_and_creatures_you_control":
                # Shadowbane, MEC-30 — a dynamic recipient set, not one
                # fixed id; ``recipient_id`` still names the player (always
                # a player for this scope).
                player = self.state.player_by_id(prevent_shield["recipient_id"])
                if player is not None:
                    self.prevent_damage_to_player_and_their_creatures(
                        player, prevent_shield.get("amount", "all"),
                        watched_source_id=obj.instance_id, rider=prevent_shield.get("rider"),
                    )
            elif prevent_shield.get("recipient_scope") == "any":
                # Penance, MEC-30 — no recipient qualifier at all ("…would
                # deal damage this turn, prevent that damage."): the
                # unscoped-recipient one-shot shield, which needs only the
                # chosen source, not a resolved recipient.
                self.prevent_damage_from_source(
                    obj, prevent_shield.get("amount", "all"), rider=prevent_shield.get("rider"),
                )
            else:
                recipient = (
                    self.state.player_by_id(prevent_shield["recipient_id"])
                    if prevent_shield.get("recipient_is_player")
                    else self._object_by_instance_id(prevent_shield["recipient_id"])
                )
                if recipient is not None:
                    method = (
                        self.prevent_damage_to_player
                        if prevent_shield.get("recipient_is_player")
                        else self.prevent_damage_to_target
                    )
                    method(
                        recipient, prevent_shield.get("amount", "all"),
                        watched_source_id=obj.instance_id, rider=prevent_shield.get("rider"),
                    )
        elif action == "remember_source_redirect" and redirect_shield is not None:
            # MEC-30 (RULE 616.1c "that damage is dealt to `<X>` instead" —
            # Opal-Eye, Konda's Yojimbo): the pick becomes a redirect's own
            # watched source.
            recipient = (
                self.state.player_by_id(redirect_shield["recipient_id"])
                if redirect_shield.get("recipient_is_player")
                else self._object_by_instance_id(redirect_shield["recipient_id"])
            )
            if recipient is not None:
                self.redirect_damage_from_source(
                    obj, recipient, redirect_shield.get("amount", "all"),
                )
        elif action == "remember_source_coinflip":
            # Desperate Gambit, MEC-30: "Choose a source you control and
            # flip a coin. If you win the flip, ... double .... If you
            # lose the flip, ... prevent ...." — the chosen permanent is
            # both the coin flip's own subject and the shield's watched
            # source, so no shield payload is needed at all.
            if self.coin_flip():
                self.grant_damage_multiplier_from_source(obj)
            else:
                self.prevent_damage_from_source(obj, "all")
        elif action == "exile":
            self.exile(obj)
            # RULE 608.2's "it"/"that card" referent for a following clause
            # (MEC-52 — Back from the Brink prices "pay its mana cost" off
            # the just-exiled graveyard card), the same seeding
            # `ExileEffect`'s own trigger-subject branch does.
            self.context.previous_targets = [obj]
            if remember and source is not None:
                # MEC-17: Imprint's own "remember the exiled card" —
                # `linked_exile_id`'s "keep pointing at the exiled card
                # after this resolves" shape, same field `ExileEffect
                # (remember=True)` uses for the unrelated O-Ring return.
                source.linked_exile_id = obj.instance_id
            if track_exiled_with and source is not None:
                # MEC-12: Abdel Adrian's own "exile any number of…" —
                # `remember`'s accumulating sibling, same field
                # `ExileEffect(track_exiled_with=True)` uses.
                source.exiled_with_ids.append(obj.instance_id)
        elif action == "library_to_battlefield":
            # MEC-41 (Nissa, Steward of Elements' 0 ability): the object is
            # still sitting in the library at this point (unlike every
            # other action above, which acts on a battlefield permanent or
            # a hand card) — `_finish_search`'s own `_remove_search_hit`
            # does the same library-pop-then-move split.
            if obj in player.library:
                player.remove_from_zone(obj, Zone.LIBRARY)
            self._put_searched_card(player, obj, "battlefield")
        elif action == "library_to_hand":
            # MEC-72 (Eclipsed Flamekin): move the picked card from library to hand.
            self._remove_from_current_zone(player, obj)
            obj.zone = Zone.HAND
            player.add_to_zone(obj, Zone.HAND)
        elif action == "sacrifice_for_descendants_fury":
            # MEC-72 (Descendants' Fury): sacrifice the chosen combat damage dealer
            # and reveal cards until a creature sharing a creature type is revealed.
            subtypes: set[str] = set()
            if "changeling" in obj.card.type_line.lower() or "changeling" in obj.intrinsic_keywords:
                subtypes.add("changeling")
            else:
                _, _, sub = obj.card.type_line.lower().partition("—")
                subtypes.update(s.strip() for s in sub.split() if s.strip())
            self.put_into_graveyard(obj)
            self.reveal_until_creature_type(
                player,
                creature_types=subtypes,
                count=1,
                hit_destination="battlefield",
                rest_destination="library_bottom_random",
            )
        elif action == "hand_to_battlefield":
            # MEC-43 round 4D (Kodama of the East Tree): the hand-zone
            # sibling of "library_to_battlefield" just above — the object
            # is still sitting in the controller's hand at this point.
            # Stamps `GameObject.entered_via_ability_id` with ``source``'s
            # own instance_id (Kodama itself) so its own trigger's "if it
            # wasn't put onto the battlefield with this ability" guard
            # (`effect_binder`'s ``not_entered_via_self`` condition) can
            # tell this arrival apart from any other entering permanent.
            if obj in player.hand:
                player.remove_from_zone(obj, Zone.HAND)
            # Stamped *before* the placement below, not after: `_put_
            # searched_card` fires `EventType.ENTERS_BATTLEFIELD`
            # synchronously (`GameState.fire_event` notifies every
            # subscriber, including trigger collection, before returning),
            # so the guard this field feeds (`not_entered_via_self`) must
            # already be true by the time that event goes out or Kodama's
            # own trigger would see an unstamped object and re-fire on its
            # own put.
            if source is not None:
                obj.entered_via_ability_id = source.instance_id
            self._put_searched_card(player, obj, "battlefield")
        elif action == "hand_to_battlefield_haste_sacrifice":
            # RULE 400.7: a hand card entering the battlefield is a new
            # object. It is selected first, then reset before the entry event
            # so its ETB abilities see the fresh permanent.
            if obj not in player.hand:
                return
            player.remove_from_zone(obj, Zone.HAND)
            obj.reset_as_new_object()
            obj.controller_id = player.id
            self._put_searched_card(player, obj, "battlefield")
            obj.temp_keywords.add("haste")
            continuous.recompute(self.state)
            source_name = source.name if source is not None else None
            label = f"{obj.name}: geopfert" + (f" ({source_name})" if source_name else "")
            # RULE 603.7: "the next end step" is the next end step of any
            # player's turn, and captures this particular new object.
            self.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=player.id,
                    step="end",
                    scope="any",
                    effects=[SacrificeObjectEffect(obj, source=source)],
                    description=label,
                )
            )
        elif action == "choose_permanent" and source is not None:
            # MEC-26: Scheming Fence's own ETB pick — nothing happens to
            # ``obj`` itself, just a pointer stamped onto the source
            # (`continuous.group_selector_objects`'s ``"chosen_permanent"``
            # selector reads it back every recompute).
            source.chosen_permanent_id = obj.instance_id
        elif action == "gain_control":
            # MEC-46 (Expropriate): control moves to the chooser,
            # indefinitely — an SBA pass / the session view recompute
            # picks up the new characteristics (RULE 613.1).
            if obj.controller_id != player.id:
                obj.controller_id = player.id
                continuous.recompute(self.state)
        elif action == "gain_control_for" and control_recipient_id is not None:
            # PAR-30 (Cultural Exchange): control moves to a *third*
            # player, not the chooser — see `_request_choose_objects`'s own
            # docstring for ``control_recipient_id``.
            if obj.controller_id != control_recipient_id:
                obj.controller_id = control_recipient_id
                obj.summoning_sick = True
                continuous.recompute(self.state)
        elif action == "soulbond_pair" and source is not None:
            # RULE 702.94a: the pairing is recorded on both creatures.
            source.paired_with = obj.instance_id
            obj.paired_with = source.instance_id
        elif action == "library_top":
            owner = self.state.player_by_id(obj.owner_id) or player
            self._remove_from_current_zone(owner, obj)
            owner.add_to_zone(obj, Zone.LIBRARY)
        elif action == "cast_free":
            self.cast_without_paying(player, obj)
        elif action == "grant_free_cast":
            # MEC-20: arm the pick's free-cast window without casting it —
            # see `CHOOSE_OBJECT_ACTIONS`'s own docstring for why this is
            # deliberately not `cast_without_paying`. Also registered in
            # `temp_play_permissions` (same-turn-only) purely so
            # `GameEngine._step_cleanup`'s existing sweep tears both down
            # together — a hand card needs no actual play-permission grant
            # to be castable (it already is), but `free_cast_instance_ids`'
            # own cleanup only keeps entries also found there.
            #
            # RULE 601.2f/718 rulings actually require this free cast to
            # happen *as the Expertise spell resolves*, not at leisure later
            # in the turn — this engine has no "pause mid-resolution for a
            # full nested cast+targeting cycle" primitive, so a same-turn
            # window is offered instead (documented simplification: strictly
            # more permissive than print, never less).
            self.state.free_cast_instance_ids.add(obj.instance_id)
            self._grant_temp_play_permission(
                obj, player, source.name if source is not None else None,
                same_turn_only=True, mana_wildcard=None,
            )
        elif action == "remove_suspected":
            # PAR-30 Suspect one-off shapes / RULE 701.60a's reverse: "You
            # may have it become no longer suspected." (Deadly Complication).
            # Nothing is created or moved — the pick just clears its own
            # suspected designation.
            self.remove_suspected([obj])
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

        Finally fires `EventType.RING_TEMPTED` (for "whenever the Ring
        tempts you, `<effect>`" triggers) once ``ring_bearer_id`` is
        settled — immediately for the 0/1-candidate paths here, or from
        `_resume_ring_bearer` once the interactive pick resolves, so
        a trigger reading "if you chose a creature other than ~" always
        sees the final bearer.
        """
        player.ring_level = min(4, int(getattr(player, "ring_level", 0) or 0) + 1)
        candidates = [
            obj for obj in self.state.permanents_controlled_by(player.id) if obj.is_creature
        ]
        if not candidates:
            player.ring_bearer_id = None
            self.state.fire_event(GameEvent(EventType.RING_TEMPTED, player_id=player.id))
            return
        if len(candidates) == 1:
            player.ring_bearer_id = candidates[0].instance_id
            self.state.fire_event(GameEvent(EventType.RING_TEMPTED, player_id=player.id))
            return
        self.open_choice({
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
        })
    @continuations.choice(
        "ring_bearer",
        answer=continuations.ANSWER_INT_REQUIRED,
        rule="701.52",
    )
    def _resume_ring_bearer(self, choice: dict[str, Any], instance_id: int) -> None:
        """Answer a pending `ring_bearer` choice (RULE 701.52a).

        Not optional — the choice only ever opens when the player controls
        2+ creatures, and RULE 701.52a makes choosing mandatory then.
        """
        allowed = {o["instance_id"] for o in choice["options"]}
        if instance_id not in allowed:
            raise ValueError(f"{instance_id} is not a legal Ring-bearer")
        player = self.state.player_by_id(choice["player_id"])
        if player is not None:
            player.ring_bearer_id = instance_id
            # `the_ring_tempts_you`'s own RING_TEMPTED firing is deferred to
            # here for this 2+-candidate path — a "whenever the Ring tempts
            # you, if you chose a creature other than ~ as your Ring-bearer,
            # …" trigger (Aragorn, Company Leader/Faramir, Field Commander)
            # needs `ring_bearer_id` already settled when it fires, and this
            # is the only point that's true for an interactive choice.
            self.state.fire_event(GameEvent(EventType.RING_TEMPTED, player_id=player.id))
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
        """RULE 114.2/114.4: bind the emblem's already-parsed quoted
        ability (or, for ``ability`` being a *list* of ability dicts —
        "You get an emblem with 'A' and 'B'.", You Compleat Me — every one
        of them) into live `TriggeredAbility`/`StaticAbility`/`ActivatedAbility`
        objects on a single `Emblem` and file it in ``player``'s command
        zone.

        Binding happens here — once, at resolve time — rather than at
        bind-on-load like every other ability, because an emblem has no
        permanent to bind *onto*: `effect_binder.bind_ability` is imported
        lazily (it imports `game/effects/core.py`, which this module also feeds
        into, so a module-level import would cycle) and given a synthetic
        `Emblem` as its ``source`` instead of a `GameObject` (`models/
        emblem.py` — carries just enough, ``controller_id``/``timestamp``,
        for the existing "you control"/layer-ordering machinery to work
        unchanged).
        """
        from ...parser.oracle.spec import AbilitySpec
        from ..binding.core import bind_ability

        self.state._timestamp_counter = getattr(self.state, "_timestamp_counter", 0) + 1
        emblem = Emblem(controller_id=player.id, timestamp=self.state._timestamp_counter)
        ability_dicts = ability if isinstance(ability, list) else [ability]
        descriptions: list[str] = []
        for one in ability_dicts:
            spec = AbilitySpec.from_dict(one)
            if spec.raw_text:
                descriptions.append(spec.raw_text)
            bound = bind_ability(spec, source=emblem)
            if isinstance(bound, TriggeredAbility):
                emblem.triggered_abilities.append(bound)
            elif isinstance(bound, ActivatedAbility):
                # RULE 114.4 — "functions in the command zone" covers an
                # activated ability too (MEC-8); previously dropped silently
                # since only the triggered/static branches were handled here.
                emblem.activated_abilities.append(bound)
            elif isinstance(bound, list):
                for effect in bound:
                    if isinstance(effect, StaticAbility):
                        emblem.static_effects.append(effect)
                    elif isinstance(effect, TriggeredAbility):
                        # The compound "~ enters or attacks"-shaped multi-event
                        # trigger returns a *list* of `TriggeredAbility` (see
                        # `bind_ability`'s docstring) — the same silent-drop gap
                        # the bare-`TriggeredAbility` branch above already covers
                        # for a single-event trigger.
                        emblem.triggered_abilities.append(effect)
                    elif isinstance(effect, ReplacementEffect):
                        # MEC-30 (Ajani Steadfast's own "-7": "You get an emblem
                        # with 'If a source would deal damage to you or a
                        # planeswalker you control, prevent all but 1 of that
                        # damage.'") — the first emblem to grant a replacement
                        # rather than a triggered/static ability; previously
                        # silently dropped here the same way the activated-
                        # ability branch above used to be, before MEC-8.
                        emblem.replacement_effects.append(effect)
        emblem.description = " / ".join(d for d in descriptions if d)
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
    def change_target(
        self, target: Any, optional: bool = False, source: Optional[GameObject] = None,
        redirect_to_source: bool = False,
    ) -> None:
        """`ChangeTargetEffect`'s resolve-time logic (RULE 115.4/601.2c —
        Misdirection/Deflecting Swat).

        The player *changing* the target is this effect's own controller
        (RULE 115.4a — not the targeted spell's controller, and per
        115.4a a target description's "you"/"your" still refers to the
        original spell's own controller, which is why `legal_targets` is
        computed with ``item.controller_id`` below, not the changer's).
        Legal alternatives are recomputed fresh against the *current*
        board (RULE 115.1c), not whatever was legal when the targeted
        spell was originally cast.

        Scoped to a stack item with exactly one existing target and one
        targeting effect — see `ChangeTargetEffect`'s own docstring for why
        a version retargeting any number of targets at once isn't built.
        ``target`` may be a *spell* (``item.obj``) or, since ENG-26, an
        *ability* (``item.source`` — a plain activated/triggered ability's
        stack image has no `GameObject` of its own; `targeting.py`'s
        ``"ability"`` kind names it by `StackItem.stack_id` instead) — the
        RULE 115.4a legality recompute below reads whichever one is the
        actual source of the effect being retargeted. No legal alternative
        (or an ``optional`` decline) leaves the target untouched, same as
        RULE 115.4a's own "if no legal targets are available, the target
        doesn't change."
        """
        item = self._stack_item_for(target)
        if item is None or source is None:
            return
        stack_source = item.obj if item.obj is not None else item.source
        if stack_source is None:
            return
        if len(item.targets) != 1 or item.target_groups is not None:
            return
        effect = next(
            (e for e in item.effects if getattr(e, "target_spec", None) is not None), None
        )
        if effect is None:
            return
        options = legal_targets(self.state, item.controller_id, effect.target_spec, source=stack_source)
        if not options:
            return
        if redirect_to_source:
            # Spellskite/Hydroelectric Specimen-shaped: the only
            # alternative on offer is this effect's own source — narrow the
            # legal-options list to just that (RULE 115.4a's "no legal
            # target, doesn't change" if it isn't even legal), then fall
            # through to the ordinary mandatory-auto-apply/optional-decline
            # handling below exactly as if that had been the only option
            # `legal_targets` ever returned. Spellskite prints no "you may"
            # (``optional=False``): with one option and not optional, that
            # auto-applies with no prompt. Hydroelectric Specimen's "you
            # may" does need the player's yes/no, which is `optional`'s
            # existing decline branch.
            options = [o for o in options if o.get("instance_id") == source.instance_id]
            if not options:
                return
        if not optional and len(options) == 1:
            item.targets = [self._target_from_descriptor(options[0])]
            return
        self.open_choice(self._change_target_choice(
            source.controller_id, item.stack_id, options, optional
        ))
    def _target_from_descriptor(self, descriptor: dict[str, Any]) -> Any:
        """A `targeting.legal_targets` descriptor, resolved back to the
        live `GameObject`/`Player` it names."""
        if "instance_id" in descriptor:
            return self.state.find_object(descriptor["instance_id"])
        return self.state.player_by_id(descriptor["player_id"])
    def _change_target_choice(
        self,
        changer_id: str,
        stack_id: int,
        options: list[dict[str, Any]],
        optional: bool,
    ) -> dict[str, Any]:
        """Build the `change_target` `pending_choice` — same generic
        ``{"id", "label", "instance_id"?}`` option shape `_trigger_target_
        choice` uses, so the existing choice UI renders it with no new
        frontend work. ``stack_id`` (not a `GameObject` id — ENG-26) is
        the being-retargeted item's own `StackItem.stack_id`, which works
        the same way for a spell or an ability."""
        choice_options: list[dict[str, Any]] = []
        for opt in options:
            if "instance_id" in opt:
                choice_options.append(
                    {"id": str(opt["instance_id"]), "label": opt["name"], "instance_id": opt["instance_id"]}
                )
            else:
                choice_options.append({"id": opt["player_id"], "label": opt["name"]})
        if optional:
            choice_options.append({"id": "decline", "label": "Nichts ändern"})
        return {
            "kind": "change_target",
            "player_id": changer_id,
            "stack_id": stack_id,
            "prompt": "Neues Ziel wählen",
            "options": choice_options,
        }
    @continuations.choice("change_target", answer=continuations.ANSWER_STR, rule="115.4")
    def _resume_change_target(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `change_target` choice (RULE 115.4/601.2c).

        ``answer`` is the chosen new target's option id, same shape as
        `_resume_trigger_target`; a decline (only offered when
        `ChangeTargetEffect.optional` was set) leaves the spell's existing
        target untouched.
        """
        if answer is None or answer == "decline":
            return
        item = next(
            (i for i in self.state.stack if i.stack_id == choice["stack_id"]), None
        )
        if item is None:
            return
        target = self._resolve_choice_option(choice["options"], str(answer))
        if target is not None:
            item.targets = [target]
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
        from ..binding.core import bind_from_catalogue  # function-scoped: avoid cycle

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
    def _is_cant_be_countered(self, obj: GameObject) -> bool:
        """RULE 118-area: does ``obj`` carry a "this spell can't be
        countered" marker (`CantBeCounteredEffect`, docked via either the
        `spell_effect` or `static` ability_kind — see that class's
        docstring for why both feed the same check), or is its controller
        granted one by a standing battlefield permanent (`GrantCantBe
        CounteredEffect` — Hexing Squelcher's "Spells you control can't be
        countered.")?
        """
        effects = list(getattr(obj, "spell_effects", []) or [])
        effects += list(getattr(obj, "static_effects", []) or [])
        if any(isinstance(e, CantBeCounteredEffect) for e in effects):
            return True
        is_creature = "creature" in (getattr(obj, "type_words", None) or set())
        is_enchantment = "enchantment" in (getattr(obj, "type_words", None) or set())
        for permanent in self.state.battlefield:
            for effect in getattr(permanent, "static_effects", None) or []:
                if not isinstance(effect, GrantCantBeCounteredEffect):
                    continue
                if permanent.controller_id != obj.controller_id:
                    continue
                if effect.scope == "creature_spells_you_control" and not is_creature:
                    continue
                if (
                    effect.scope == "creature_or_enchantment_spells_you_control"
                    and not (is_creature or is_enchantment)
                ):
                    # "Creature and enchantment spells you control can't be
                    # countered." (Destiny Spinner, MEC-43) — the two-type
                    # union sibling of the creature-only scope just above.
                    continue
                if effect.scope == "color_spells_you_control":
                    if effect.color not in (getattr(obj, "colors", None) or set()):
                        continue
                return True
        return False
    def counter_spell(self, target: Any, suspend_time_counters: Optional[int] = None) -> None:
        """Remove a spell (a `StackItem` or its game object) from the stack.

        A countered spell goes to its owner's graveyard (RULE 701.5g) and
        never resolves. Unconditional — callers that must honour "can't be
        countered" (RULE 118) or an "unless its controller pays" condition
        (RULE 601) go through `counter_unless_pays` instead, which calls this
        only once both are settled.

        ``suspend_time_counters`` (Delay, MEC-42, RULE 702.62): "exile it
        with N time counters on it instead of putting it into its owner's
        graveyard. If it doesn't have suspend, it gains suspend." — redirects
        the landing zone and arms `GameObject.granted_suspend` when the card
        has no printed Suspend of its own, so `_collect_suspend_triggers`
        (`game/rules/triggers_mixin.py`) picks it up from exile exactly as a
        printed-Suspend card would. The commander-zone-choice replacement
        (RULE 903.9) only ever applies to a graveyard-or-library-bound move,
        so it's skipped on this branch.
        """
        item = self._stack_item_for(target)
        if item is None:
            return
        self.state.stack.remove(item)
        if item.obj is not None:
            owner = self.state.player_by_id(item.obj.owner_id)
            if suspend_time_counters:
                owner.add_to_zone(item.obj, Zone.EXILE)
                if not _has_suspend(item.obj):
                    item.obj.granted_suspend = True
                item.obj.add_counters("time", suspend_time_counters)
            else:
                owner.add_to_zone(item.obj, Zone.GRAVEYARD)
                self._flag_commander_zone_choice(item.obj)
        self.state.fire_event(
            GameEvent(EventType.SPELL_RESOLVED, spell=item.description, countered=True)
        )
    def bounce_spell_or_permanent(self, target: Any) -> None:
        """"Return target spell or nonland permanent … to its owner's
        hand." (Sink into Stupor-shaped) — the RULE 701.3-onto-the-stack
        sibling of `counter_spell`: pulled straight off the stack (never
        resolving) rather than through `return_to_hand`'s battlefield/zone
        removal, which has no idea `GameState.stack` even exists and would
        silently duplicate the object instead of moving it. Not a
        "counter" for any card-text purpose (nothing here checks/marks
        "can't be countered" — this ability's printed template never
        claims to counter anything, it plainly returns).

        Falls back to the ordinary `return_to_hand` when ``target`` isn't
        currently a spell on the stack (a permanent bounce), so one call
        covers "spell or nonland permanent" without the caller needing to
        know which kind of target it got handed.
        """
        item = self._stack_item_for(target)
        if item is None:
            self.return_to_hand(target)
            return
        self.state.stack.remove(item)
        if item.obj is not None:
            owner = self.state.player_by_id(item.obj.owner_id)
            owner.add_to_zone(item.obj, Zone.HAND)
            self._flag_commander_zone_choice(item.obj)
        self.state.fire_event(
            GameEvent(EventType.SPELL_RESOLVED, spell=item.description, countered=False)
        )
    def gain_control_of_spell(self, target: Any, new_controller_id: str) -> None:
        """"Gain control of target noncreature spell." (Commandeer) — RULE
        608.2m/111.5's owner/controller split applied to a spell still on
        the stack rather than a permanent: only `StackItem.controller_id`
        (and the underlying object's own, mirrored so both agree) changes,
        so a spell that goes on to resolve as a permanent (an artifact/
        enchantment/planeswalker, per the card's own reminder text) enters
        under the *new* controller directly — no separate zone-change
        control flip needed the way a permanent already on the battlefield
        would (`gain_control_by_source`/`exchange_control`).
        """
        item = self._stack_item_for(target)
        if item is None:
            return
        item.controller_id = new_controller_id
        if item.obj is not None:
            item.obj.controller_id = new_controller_id
    def end_the_turn(self) -> None:
        """"End the turn." (Day's Undoing/Time Stop-shaped reminder text —
        RULE 500-adjacent, not a printed rule number of its own): "Exile
        all spells and abilities from the stack, including this card" —
        the caster's own resolving spell is exiled *instead of* going to
        its owner's graveyard, the same trailing-self-override idiom
        `ShuffleSelfIntoLibraryEffect` already uses (`_apply_stack_item`'s
        own zone check). The rest of the reminder text ("discard down to
        your maximum hand size. Damage wears off, and 'this turn'/'until
        end of turn' effects end") is RULE 514.1/514.2's own cleanup-step
        body, applied by `GameEngine.advance_step` once `GameState.
        end_turn_requested` is set below — a `RulesEngine` method has no
        back-reference to `GameEngine`'s `_turn_steps`/`_cursor` (or its
        `_step_cleanup`), the same reason `ExtraCombatPhaseEffect` queues
        onto `GameState` instead of reaching the engine directly.
        """
        for item in list(self.state.stack):
            self.state.stack.remove(item)
            if item.obj is not None:
                owner = self.state.player_by_id(item.obj.owner_id)
                owner.add_to_zone(item.obj, Zone.EXILE)
                self.state.fire_event(
                    GameEvent(EventType.EXILE, player_id=owner.id, object=item.obj.name)
                )
        self.state.end_turn_requested = True
    def counter_ability(self, target: Any) -> None:
        """RULE 701.5b: counter a target activated or triggered ability
        (Stifle/Trickbind, ENG-26) — the ability-item sibling of
        `counter_spell`, which already handles an ability `StackItem`
        correctly on its own (no `.obj` to move to a graveyard; RULE
        701.5g's "its owner's graveyard" only ever applies to a spell).
        Refuses a "can't be countered" ability the same way
        `counter_unless_pays` refuses a spell's own.
        """
        item = self._stack_item_for(target)
        if item is None or item.kind != "ability":
            return
        if self._is_cant_be_countered(item.source):
            return
        self.counter_spell(target)
    def counter_unless_pays(
        self,
        target: Any,
        unless_pays: Optional[str],
        source: Optional[GameObject] = None,
        suspend_time_counters: Optional[int] = None,
        on_pay_effect_specs: Optional[list[dict]] = None,
    ) -> None:
        """`CounterSpellEffect`'s resolve-time logic (RULE 118/601/701.5).

        Refuses outright if ``target`` carries a "can't be countered" marker
        (RULE 118 — the spell stays on the stack, unaffected). With no
        ``unless_pays`` cost this is a plain `counter_spell`. Otherwise it's
        RULE 601's "Mana Leak" template: if the target's controller *can*
        pay ``unless_pays``, this opens an interactive `counter_unless_pays`
        `pending_choice` for them (`_resume_counter_unless_pays`
        finishes it); a controller who genuinely cannot pay has no real
        decision, so the spell is simply countered without pausing — this is
        also what keeps a passive goldfish-dummy opponent (who never holds
        mana) from stalling resolution on a choice nobody can act on.

        ``suspend_time_counters`` (Delay, MEC-42) is threaded straight
        through to every `counter_spell` call this method makes, including
        the interactive decline path (stashed as `_pending_counter_suspend`,
        the same convention `_pending_counter_target`/`_pending_counter_cost`
        already use) — no real card combines "unless pays" with Delay's own
        redirect today, but nothing here assumes they're mutually exclusive.

        ``on_pay_effect_specs`` (Assimilate Essence — "…unless its
        controller pays {4}. If they do, you incubate 2.") are serialized
        `EffectSpec` dicts applied *only* on the branch where the target's
        controller pays, from `_resume_counter_unless_pays` — stashed
        alongside the other `_pending_counter_*` fields. Inert on every
        branch that ends in a `counter_spell` (they didn't pay).
        """
        item = self._stack_item_for(target)
        if item is None or item.obj is None:
            return
        obj = item.obj
        if self._is_cant_be_countered(obj):
            return
        if not unless_pays:
            self.counter_spell(target, suspend_time_counters=suspend_time_counters)
            return
        cost = ManaCost.parse(unless_pays)
        if cost.has_variable:
            cost = cost.with_x(getattr(source, "x_paid", 0) or 0)
        controller = self.state.player_by_id(obj.controller_id)
        if controller is None or not controller.mana_pool.can_pay(
            cost, life_available=controller.life
        ):
            self.counter_spell(target, suspend_time_counters=suspend_time_counters)
            return
        self._pending_counter_target = target
        self._pending_counter_cost = cost
        self._pending_counter_suspend = suspend_time_counters
        self._pending_counter_on_pay_specs = list(on_pay_effect_specs or [])
        self._pending_counter_on_pay_source = source
        self.open_choice({
            "kind": "counter_unless_pays",
            "player_id": controller.id,
            "prompt": f"{obj.name}: {unless_pays} zahlen, um es vor dem Countern zu bewahren?",
            "options": [
                {"id": "pay", "label": f"{unless_pays} zahlen"},
                {"id": "decline", "label": "Nicht zahlen"},
            ],
        })
    @continuations.choice("counter_unless_pays", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_counter_unless_pays(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `counter_unless_pays` choice (RULE 601).

        ``answer == "pay"`` deducts the cost from the target spell's
        controller and leaves it on the stack, then applies any
        ``on_pay_effect_specs`` stashed for this choice (Assimilate
        Essence's "If they do, you incubate 2."); anything else (``None``/
        ``"decline"``) counters it and the on-pay effects never fire.
        """
        target = self._pending_counter_target
        cost = self._pending_counter_cost
        suspend_time_counters = getattr(self, "_pending_counter_suspend", None)
        on_pay_specs = list(getattr(self, "_pending_counter_on_pay_specs", None) or [])
        on_pay_source = getattr(self, "_pending_counter_on_pay_source", None)
        self._pending_counter_target = None
        self._pending_counter_cost = None
        self._pending_counter_suspend = None
        self._pending_counter_on_pay_specs = []
        self._pending_counter_on_pay_source = None
        if target is None:
            return
        if answer == "pay" and cost is not None:
            item = self._stack_item_for(target)
            if item is not None and item.obj is not None:
                controller = self.state.player_by_id(item.obj.controller_id)
                if controller is not None:
                    life_spent = controller.mana_pool.pay(cost, life_available=controller.life)
                    self.lose_life(controller, life_spent, cause="cost")
            if on_pay_specs:
                self._apply_effect_specs(on_pay_specs, on_pay_source)
            return
        self.counter_spell(target, suspend_time_counters=suspend_time_counters)
    def _fire_becomes_target_events(self, item: StackItem) -> None:
        """MEC-19: fire `EventType.BECOMES_TARGET` once per target of
        ``item`` — see that constant's own docstring for the full field
        list and the reasoning for piggy-backing on `check_ward`'s own
        choke point rather than a fourth call site. Ward itself is
        untouched by this (still its own direct RULE 702.21 cast-time
        check, right below); this is a parallel, general-purpose event so
        anything else can key a trigger off "became a target" the same way
        it already can for damage/counters/etc.
        """
        for target in item.targets or []:
            if isinstance(target, GameObject):
                is_player = False
                instance_id: Optional[str] = target.instance_id
                target_controller_id: Optional[str] = target.controller_id
            elif isinstance(target, Player):
                is_player = True
                instance_id = None
                target_controller_id = None
            else:
                continue  # not a real RULE 115 target (e.g. an already-resolved value)
            self.state.fire_event(GameEvent(
                EventType.BECOMES_TARGET,
                instance_id=instance_id,
                target_controller_id=target_controller_id,
                is_player=is_player,
                controller_id=item.controller_id,
                item_kind=item.kind,
                stack_id=item.stack_id,
            ))
    def check_ward(self, item: StackItem, caster: Player) -> None:
        """RULE 702.21/601.2c/603.3: after ``item`` (a spell, activated
        ability, or triggered ability) is placed on the stack with its final
        targets — fire MEC-19's RULE 603.1 "becomes the target of a spell/
        ability" event for every target (`_fire_becomes_target_events`, see
        `EventType.BECOMES_TARGET`'s own docstring), then push a genuine ward
        triggered-ability `StackItem` for every target that has ward against
        ``caster`` — one per warded target (RULE 702.21c), each on top of
        ``item``.

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
        after a spell/ability's targets are finalized. The method keeps its
        ward-specific name (every call site already reads it that way) even
        though it's now also the one choke point `BECOMES_TARGET` fires
        from — a second, sibling call at each of the three sites would risk
        a future call site adding one but not the other.
        """
        self._fire_becomes_target_events(item)
        for target in item.targets or []:
            if not isinstance(target, GameObject):
                continue  # ward is on permanents (RULE 702.21) — never a player
            ward = (getattr(target, "parametric_keywords", None) or {}).get("ward")
            cost_text = ward.get("cost") if ward else None
            if not cost_text:
                # A *granted* Ward (`GrantWardEffect` — Hexing Squelcher's
                # "Other creatures you control have 'Ward—Pay 2 life.'"),
                # unlike this object's own printed keyword above — a
                # separate field since `parametric_keywords` is bound once
                # from the card's own text (`models/game_object.py`) and
                # never re-derived by `continuous.recompute` the way a
                # flag `granted_keywords` entry is.
                cost_text = getattr(target, "granted_ward_cost", None)
            if target.controller_id == caster.id:
                continue  # "opponent" doesn't include its own controller
            if not cost_text:
                continue  # no ward, or cost couldn't be recognized from the card text
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
        self.open_choice({
            "kind": "ward",
            "player_id": caster.id,
            "prompt": f"Ward {cost_label} — zahlen, um deinen Zauberspruch/deine Fähigkeit zu "
            "behalten?",
            "options": [
                {"id": "pay", "label": f"{cost_label} zahlen"},
                {"id": "decline", "label": "Nicht zahlen"},
            ],
        })
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
        # RULE 122 energy: "unless you pay an amount of {E} equal to its
        # mana value." (Volatile Stormdrake, MEC-43) — the same
        # affordability check `GameEngine._can_pay_activation_cost` already
        # makes for an activated ability's own `pay_energy` component; this
        # shared pay-or-lose-it machinery (ward/sacrifice_unless_pay/
        # counter_unless_pays) had never gained it before, since no prior
        # card printed an energy-costed "unless" clause.
        if cost.pay_energy and player.counters.get("energy", 0) < cost.pay_energy:
            return False
        # "…sacrifice a nonland permanent of their choice or discard a
        # card." (Tergrid's Lantern, MEC-43 round 4E) — payable when
        # *either* half is (the payer's own later choice, `_pay_player_
        # cost`), not both.
        if cost.sacrifice_or_discard and not self._can_sacrifice_or_discard(player):
            return False
        if cost.collect_evidence and not self.collect_evidence_possible(
            player, cost.collect_evidence
        ):
            return False
        if cost.forage and not self.forage_possible(player):
            return False
        if cost.blight and not self.blight_possible(player):
            return False
        return True
    def _can_sacrifice_or_discard(self, player: Player) -> bool:
        """Whether ``player`` could pay a `sacrifice_or_discard` cost right
        now — a nonland permanent to sacrifice, or a card in hand."""
        has_nonland = any(
            _matches_permanent_type(obj, "nonland")
            for obj in self.state.permanents_controlled_by(player.id)
        )
        return has_nonland or bool(player.hand)
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
        if cost.pay_energy:
            self.add_player_counters(player, -cost.pay_energy, "energy")
        if cost.sacrifice_or_discard:
            self._pay_sacrifice_or_discard(player)
        if cost.collect_evidence:
            self.collect_evidence(player, cost.collect_evidence)
        if cost.forage:
            self.forage(player)
        if cost.blight:
            # RULE 701.68 — auto-pick (payment can't pause for a chooser).
            self.blight(player, cost.blight, interactive=False)
    def _pay_sacrifice_or_discard(self, player: Player) -> None:
        """Pay a `sacrifice_or_discard` cost component — the payer's own
        choice of *which* half (Tergrid's Lantern, MEC-43 round 4E). Forced
        (no prompt) when only one half is actually available, the same
        "asking would be theatre" idiom `_request_choose_objects` uses; with
        both available, opens the small dedicated `sacrifice_or_discard`
        choice below, then `_resume_sacrifice_or_discard` dispatches
        into the existing interactive `sacrifice`/`discard_choice`
        machinery (each already its own "which one" chooser)."""
        can_sacrifice = any(
            _matches_permanent_type(obj, "nonland")
            for obj in self.state.permanents_controlled_by(player.id)
        )
        can_discard = bool(player.hand)
        if can_sacrifice and can_discard:
            self.open_choice({
                "kind": "sacrifice_or_discard",
                "player_id": player.id,
                "prompt": "Eine bleibende Karte opfern oder eine Karte abwerfen?",
                "options": [
                    {"id": "sacrifice", "label": "Bleibende Karte opfern"},
                    {"id": "discard", "label": "Karte abwerfen"},
                ],
            })
            return
        if can_sacrifice:
            self.sacrifice(player, "nonland", 1)
        elif can_discard:
            self.discard_choice(player, 1)
    @continuations.choice(
        "sacrifice_or_discard",
        answer=continuations.ANSWER_STR,
        rule="701.21",
    )
    def _resume_sacrifice_or_discard(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `sacrifice_or_discard` choice — ``"sacrifice"``
        opens the interactive "which permanent" chooser, ``"discard"`` the
        interactive "which card" one; anything else re-checks both halves
        defensively (the board can have changed since the offer was made)
        rather than silently paying nothing."""
        player = self.state.player_by_id(choice["player_id"])
        if answer == "discard":
            self.discard_choice(player, 1)
        elif answer == "sacrifice":
            self.sacrifice(player, "nonland", 1)
        else:
            self._pay_sacrifice_or_discard(player)
    @continuations.choice("ward", answer=continuations.ANSWER_STR, rule="702.21")
    def _resume_ward(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `ward` choice (RULE 702.21).

        ``answer == "pay"`` charges the *caster* the cost and leaves the
        item on the stack; anything else counters it. Either way, if
        another ward ability is still on the stack (RULE 702.21c, a
        different warded target of the same spell/ability), it simply
        becomes the new top of the stack and resolves next through the
        ordinary stack loop — no extra bookkeeping needed here.
        """
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
        eligible player — the same treatment `_resume_choose_creature_type` gives a
        missing answer to a mandatory choice, so a battle is never left
        without one (which RULE 310.10 would then punish with a graveyard
        move)."""
        eligible = self._eligible_protectors(obj)
        if not eligible:
            obj.protector_id = None
            return
        match = next((p for p in eligible if p.id == player_id), None)
        obj.protector_id = (match or eligible[0]).id
    def should_skip_step(self, player: Player, step_name: str) -> bool:
        for effect in player.player_effects:
            if isinstance(effect, StaticEffect) and effect.skips_step(step_name):
                if effect.duration == "once":
                    effect.active = False
                return True
        # MEC-38 (Necropotence's "Skip your draw step."): a standing,
        # battlefield-sourced skip rather than a one-shot/duration-scoped
        # `player_effects` entry — see `continuous.skipped_steps_for`.
        if step_name in continuous.skipped_steps_for(self.state, player):
            return True
        return False
