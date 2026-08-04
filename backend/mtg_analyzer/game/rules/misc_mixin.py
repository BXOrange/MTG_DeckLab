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

from ...models import card_query
from ...models.card import Card
from ...models.emblem import Emblem
from ...models.events import EventType, GameEvent
from ...models.game_object import GameObject, Zone
from ...models.game_state import DelayedTrigger, GameState, StackItem
from ...models.mana_cost import ManaCost
from ...models.player import Player
from ...parser.oracle.catalogue.keywords import parse_keywords
from ...parser.oracle.catalogue.saga import all_chapter_numbers
from .. import ability_catalogue, combat, continuous, copy_mechanics, dungeons, face_down, variants
from ..combat import is_protected_from
from ..costs import DISCARD_HAND, ActivationCost, parse_activation_cost
from ..mana_abilities import restriction_predicate_for_cast
from ..effects import (
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
    ActivatedAbility,
    StaticAbility,
    StaticEffect,
    TakeInitiativeEffect,
    TriggeredAbility,
    WardEffect,
    WinConditionEffect,
)
from ..targeting import TargetSpec, collapse_groups, expand_counts, legal_targets

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
        else:
            self._pay_player_cost(player, pending["cost"])
            self._apply_effect_specs(pending["effect_specs"], pending["source"], targets)
        # PAR-13: if this single-player choice is one leg of a mass
        # `request_each_player_pay_or` sweep, move on to whoever's next —
        # a no-op for every ordinary (non-mass) `pay_cost_then` caller,
        # since that dict is only ever populated by the mass primitive.
        if self._pending_each_player_pay_or is not None:
            self._advance_each_player_pay_or()
    def request_each_player_pay_or(
        self,
        cost: "ActivationCost",
        effect_specs: list[dict[str, Any]],
        source: Optional[GameObject],
    ) -> None:
        """RULE 101.4's APNAP mass "unless" (PAR-13 — "Each player loses N
        life unless they `<pay cost>`.", Bellowing Mauler/Lim-Dûl's Hex/
        Tomb of Annihilation's "Veils of Fear"/"Sandfall Cell" dungeon
        rooms): every living player, starting with the active player and
        proceeding in turn order, is asked in turn whether to pay ``cost``;
        anyone who doesn't (or can't) gets ``effect_specs`` applied to
        *them* — not the ability's controller, which is why ``targets``
        (not the effects' own untargeted-controller default) carries each
        player through `request_pay_cost_then`.

        Built as a chain of ordinary single-player `request_pay_cost_then`
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
        order = [
            self.state.players[(start + i) % n].id
            for i in range(n)
            if not self.state.players[(start + i) % n].has_lost
        ]
        self._pending_each_player_pay_or = {
            "remaining_ids": order,
            "cost": cost,
            "effect_specs": [dict(d) for d in effect_specs],
            "source": source,
        }
        self._advance_each_player_pay_or()
    def _advance_each_player_pay_or(self) -> None:
        """Ask the next still-pending player in a `request_each_player_pay_or`
        sweep, or clear it once everyone has answered."""
        pending = self._pending_each_player_pay_or
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
            self.request_pay_cost_then(
                player, pending["cost"], [], pending["source"],
                else_effect_specs=pending["effect_specs"], targets=[player],
            )
            if self.state.pending_choice is not None:
                return  # a real choice opened — resumed via resolve_pay_cost_then_choice
        self._pending_each_player_pay_or = None
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
        from ...parser.oracle.spec import EffectSpec
        from ..effect_binder import build_effects  # function-scoped: effects↔binder cycle

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
        self.state.pending_choice = {
            "kind": "opening_hand_battlefield",
            "player_id": player.id,
            "prompt": prompt,
            "options": [
                {"id": permission.destination, "label": accept_label},
                {"id": "decline", "label": "In der Hand behalten"},
            ],
        }
    def resolve_opening_hand_battlefield_choice(self, answer: Optional[str]) -> None:
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
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "opening_hand_battlefield":
            raise ValueError("no pending opening-hand-battlefield choice to resolve")
        self.state.pending_choice = None
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
            self.request_choose_objects(
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
        created later, once `resolve_replacement_order_choice` finishes the
        chain. A token's own `enter_as_copy_effects` choice (below) can pause
        the very same way, for the very same reason.

        Known scoped gap: unlike `resolve_top_of_stack`'s `_resolve_
        permanent_spell`, `enter_choice_effects` (RULE 601.2b "as ~ enters,
        choose a creature type/color") is bound but never offered here —
        every real card with that ability in the pool is a cast permanent,
        never a token, so there's nothing to exercise it against yet.
        """
        from ..effect_binder import bind_from_catalogue  # function-scoped: avoid cycle

        def _finish_entry(token: GameObject) -> None:
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
                    # from `resolve_enter_as_copy_choice`, at which point the
                    # remaining tokens in this batch (if any) are built.
                    self._offer_enter_as_copy(token, _continuation)
                else:
                    _continuation()

            _next(max(0, final_count))
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
            plane = variants.active_plane(self.state)
            self.state.fire_event(
                GameEvent(
                    EventType.CHAOS_ENSUED,
                    player_id=player.id,
                    controller_id=player.id,
                    instance_id=plane.instance_id if plane is not None else None,
                    plane=plane.name if plane is not None else None,
                )
            )
        elif face == "planeswalk":
            self.planeswalk(player)
        return face
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
        self.state.pending_choice = {
            "kind": "venture_room",
            "player_id": player.id,
            "prompt": f"{dungeon.name}: welchen Raum betrittst du?",
            "options": [
                {"id": room.name, "label": f"{room.name} — {room.effect_text}"}
                for room in rooms
            ],
        }
    def resolve_venture_room_choice(self, answer: Optional[str]) -> None:
        """Answer a pending RULE 701.49b room choice. Mandatory (the marker
        has to move somewhere), so an unrecognized/missing answer takes the
        first arrow rather than staying put."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "venture_room":
            raise ValueError("no pending venture-room choice to resolve")
        player = self.state.player_by_id(choice["player_id"])
        self.state.pending_choice = None
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
        self.state.pending_choice = {
            "kind": "choose_dungeon",
            "player_id": player.id,
            "prompt": "In welchen Dungeon begibst du dich?",
            "options": [{"id": d.name, "label": d.name} for d in pool],
        }
    def resolve_choose_dungeon_choice(self, answer: Optional[str]) -> None:
        """Answer a pending RULE 309.2a dungeon choice — mandatory, so an
        unrecognized/missing answer takes the first offered dungeon."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "choose_dungeon":
            raise ValueError("no pending dungeon choice to resolve")
        player = self.state.player_by_id(choice["player_id"])
        self.state.pending_choice = None
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
        self.pending_triggers.append((ability, event))
    def _effects_from_specs(self, specs: list[dict[str, Any]], source: Any) -> list[Any]:
        """Serialized `EffectSpec` dicts → live one-shot `GameEffect`s bound
        against ``source`` — the same lazily-imported binder path
        `create_emblem` uses for an emblem's quoted ability, and for the same
        reason (a module-level import would cycle through `game/effects.py`).
        """
        from ...parser.oracle.spec import EffectSpec
        from ..effect_binder import BindError, build_effects

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
    def become_monarch(self, player: Player) -> None:
        """RULE 725.3: ``player`` becomes the monarch; whoever held it
        (possibly ``player`` themself) ceases to."""
        self.state.monarch_id = player.id
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
    #: The closed vocabulary `request_choose_objects` accepts, mapping each
    #: action name to what it does to a chosen object. Deliberately small
    #: and data-only: the whole choice (candidates, action, how many are
    #: left) lives in `GameState.pending_choice`, so it survives the
    #: `clone()` undo snapshots takes — unlike a callback, which is why
    #: this replaced the "auto-pick the first candidate" convention rather
    #: than passing a continuation closure around.
    CHOOSE_OBJECT_ACTIONS = frozenset(
        {
            "tap", "sacrifice", "return_to_hand", "soulbond_pair", "library_top", "discard",
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
        }
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
        elif action == "exile":
            self.exile(obj)
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
        from ...parser.oracle.spec import AbilitySpec
        from ..effect_binder import bind_ability

        self.state._timestamp_counter = getattr(self.state, "_timestamp_counter", 0) + 1
        emblem = Emblem(controller_id=player.id, timestamp=self.state._timestamp_counter)
        spec = AbilitySpec.from_dict(ability)
        emblem.description = spec.raw_text
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
        from ..effect_binder import bind_from_catalogue  # function-scoped: avoid cycle

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
    def should_skip_step(self, player: Player, step_name: str) -> bool:
        for effect in player.player_effects:
            if isinstance(effect, StaticEffect) and effect.skips_step(step_name):
                if effect.duration == "once":
                    effect.active = False
                return True
        return False
