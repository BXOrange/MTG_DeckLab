"""The rules engine: mana, casting, stack, replacements, triggers, SBAs.

Reference: docs/02_MVP_USECASES_REVISED.md R2.2-R2.8,
docs/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2/3).

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
from typing import Any, Optional

from ..models import card_query
from ..models.card import Card
from ..models.events import EventType, GameEvent
from ..models.game_object import GameObject, Zone
from ..models.game_state import GameState, StackItem
from ..models.mana_cost import ManaCost
from ..models.player import Player
from . import ability_catalogue, combat, continuous
from .effects import (
    GameContext,
    ReplacementEffect,
    StaticEffect,
    TriggeredAbility,
    WinConditionEffect,
)

#: Roman-numeral value of each Saga chapter marker, for finding the last one.
_ROMAN: dict[str, int] = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}
#: A Saga chapter marker: a roman numeral (possibly a range/list like "I, II")
#: opening a chapter line, followed by the em dash the ability text starts with.
_SAGA_CHAPTER_RE = re.compile(r"(?:^|\n|,\s*)(VII|VI|IV|V|III|II|I)\b[\s,]*(?=[—\-–IVX])", re.M)


def _saga_final_chapter(card: Card) -> int:
    """The highest chapter number a Saga has (RULE 714.2c), 0 if unreadable.

    Read off the oracle text's roman-numeral chapter markers ("I —", "II, III —",
    "IV —"); the largest is the final chapter. Basic and text-based — enough to
    drive the sacrifice SBA without a per-card table."""
    text = card.oracle_text or ""
    chapters = [_ROMAN[m.group(1)] for m in _SAGA_CHAPTER_RE.finditer(text)]
    return max(chapters) if chapters else 0


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
        # Collect triggers for every event the game fires.
        state.subscribe(self._collect_triggers)

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

    def apply_replacements(self, event: GameEvent) -> Optional[GameEvent]:
        """Rewrite ``event`` through applicable replacement effects.

        RULE 616: each replacement may apply at most once to a given event
        (tracked by identity here), and applying one can expose others
        (a draw→mill chain). Multiple simultaneously-applicable effects are
        ordered by the affected player; this MVP applies them in discovery
        order (a deterministic stand-in until player choice is wired in).
        Returns the final event, or ``None`` if it was prevented.
        """
        applied: set[int] = set()
        current: Optional[GameEvent] = event
        while current is not None:
            applicable = [
                effect
                for effect in self._all_replacement_effects()
                if id(effect) not in applied and effect.can_replace(current, self.context)
            ]
            if not applicable:
                break
            chosen = applicable[0]
            applied.add(id(chosen))
            current = chosen.apply_replacement(current, self.context)
        return current

    # ------------------------------------------------------------------
    # Triggered abilities (RULE 603)
    # ------------------------------------------------------------------

    def _collect_triggers(self, event: GameEvent) -> None:
        for obj in self.state.permanents():
            for ability in obj.triggered_abilities:
                if isinstance(ability, TriggeredAbility) and ability.check_trigger(
                    event, self.context
                ):
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
        for ability, _event in mine + rest:  # active first (bottom of stack)
            self._place_trigger(ability)
        self.pending_triggers.clear()
        return count

    def _place_trigger(self, ability: "TriggeredAbility") -> None:
        self.state.stack.append(
            StackItem(
                kind="ability",
                controller_id=ability.controller_id or self.state.active_player.id,
                effects=[ability],
                description=ability.description or "triggered ability",
            )
        )

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
    ) -> StackItem:
        """Pay the cost, move the card to the stack (RULE 601).

        ``x`` is the announced value (RULE 601.2b) for a cost containing
        ``{X}``; ignored otherwise. ``cost`` lets the caller supply an already
        adjusted cost (X resolved, static reductions applied — RULE 601.2f);
        omitted, the printed cost is used. Timing/priority legality is enforced
        by the caller; this performs the mechanical cast. Raises ValueError if
        the mana cost can't be paid.
        """
        if cost is None:
            cost = self.mana_cost_of(obj.card)
            if cost.has_variable:
                cost = cost.with_x(x)
        if not player.mana_pool.can_pay(cost, life_available=player.life):
            raise ValueError(f"{player.id} cannot pay for {obj.name}")
        life_spent = player.mana_pool.pay(cost, life_available=player.life)
        self.lose_life(player, life_spent, cause="cost")

        if obj in player.hand:
            player.remove_from_zone(obj, Zone.HAND)
        elif obj in player.command:
            player.remove_from_zone(obj, Zone.COMMAND)
        obj.zone = Zone.STACK
        item = StackItem(
            kind="spell",
            controller_id=player.id,
            effects=self._effects_for_spell(obj),
            obj=obj,
            description=obj.name,
            targets=targets,
            x=x,
        )
        self.state.stack.append(item)
        self.state.record_stat(
            player.id, "spell", cmc=obj.card.converted_mana_cost, name=obj.name
        )
        self.state.fire_event(
            GameEvent(EventType.SPELL_CAST, player_id=player.id, card_id=obj.card.id, spell=obj.name)
        )
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
        return item

    def _remove_from_current_zone(self, player: Player, obj: GameObject) -> None:
        """Pull ``obj`` out of whichever zone currently holds it."""
        for cards in player.zones.values():
            if obj in cards:
                cards.remove(obj)
                return
        if obj in self.state.battlefield:
            self.state.remove_from_battlefield(obj)

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

    def resolve_top_of_stack(self) -> Optional[StackItem]:
        """Resolve the topmost stack object (RULE 608). Returns it, or None."""
        if not self.state.stack:
            return None
        item = self.state.stack.pop()  # LIFO

        for effect in item.effects:
            effect.apply(self.context, item.targets)

        if item.kind == "spell" and item.obj is not None:
            obj = item.obj
            if self.is_permanent_spell(obj.card):
                obj.summoning_sick = True
                obj.tapped = ability_catalogue.enters_tapped(obj.card)  # RULE 614.1
                self.state.add_to_battlefield(obj)
                self.state.fire_event(
                    GameEvent(
                        EventType.ENTERS_BATTLEFIELD,
                        controller_id=obj.controller_id,
                        card_id=obj.card.id,
                        object=obj.name,
                    )
                )
            else:
                self._move_to_graveyard(obj)
            self.state.fire_event(
                GameEvent(EventType.SPELL_RESOLVED, spell=obj.name, controller_id=item.controller_id)
            )

        self.check_state_based_actions()
        return item

    # ------------------------------------------------------------------
    # Rules primitives (routed through replacements + events)
    # ------------------------------------------------------------------

    def draw(self, player: Player, count: int = 1) -> None:
        for _ in range(count):
            self._single_draw(player)

    def _single_draw(self, player: Player) -> None:
        event = GameEvent(EventType.DRAW, player_id=player.id, count=1)
        resolved = self.apply_replacements(event)
        if resolved is None:
            return
        if resolved.type == EventType.MILL:
            self.mill(player, resolved.get("count", 1))
            return
        # A DRAW event (possibly with a bumped count).
        n = resolved.get("count", 1)
        if len(player.library) < n:
            # Trying to draw from an empty library is a loss (RULE 704.5c),
            # flagged for the SBA check rather than raising.
            player.loss_reason = player.loss_reason or "draw_from_empty"
            player.attempted_draw_from_empty = True  # type: ignore[attr-defined]
        drawn = player.draw(n)
        if drawn:
            self.state.record_stat(player.id, "draw", amount=len(drawn))
            self.state.fire_event(
                GameEvent(EventType.DRAW, player_id=player.id, count=len(drawn))
            )

    def mill(self, player: Player, count: int) -> None:
        for _ in range(count):
            if not player.library:
                break
            obj = player.library.pop()
            obj.zone = Zone.GRAVEYARD
            player.graveyard.append(obj)
        self.state.fire_event(GameEvent(EventType.MILL, player_id=player.id, count=count))

    def discard(self, player: Player, count: int = 1) -> None:
        discarded = 0
        for _ in range(count):
            if not player.hand:
                break
            obj = player.hand.pop()  # auto-choose (no chooser in MVP)
            obj.zone = Zone.GRAVEYARD
            player.graveyard.append(obj)
            discarded += 1
        if discarded:
            self.state.fire_event(
                GameEvent(EventType.DISCARD, player_id=player.id, count=discarded)
            )

    def deal_damage(
        self,
        target: Any,
        amount: int,
        source: Optional[GameObject] = None,
        combat: bool = False,
    ) -> None:
        is_player = isinstance(target, Player)
        event = GameEvent(
            EventType.DAMAGE,
            amount=amount,
            is_player=is_player,
            target_id=target.id if is_player else target.instance_id,
        )
        resolved = self.apply_replacements(event)
        if resolved is None:
            return
        final = resolved.get("amount", amount)
        if final <= 0:
            return
        if is_player:
            # RULE 120.3: damage dealt to a player causes that much life
            # loss. This is a *consequence* of damage, not a separate event
            # a player chose to trigger — go through the same `lose_life`
            # choke point as any other life loss so triggers watching for
            # "loses life" fire consistently regardless of cause.
            self.lose_life(target, final, cause="damage")
            self.state.record_stat(target.id, "damage_taken", amount=final)
            if source is not None:
                self.state.record_stat(source.controller_id, "damage_dealt", amount=final)
                # RULE 903.10a: combat damage from a commander is tallied
                # separately toward the 21-damage loss threshold.
                if combat and source.is_commander:
                    target.add_commander_damage(source.instance_id, source.name, final)
        elif getattr(target, "is_planeswalker", False):
            # RULE 306.9: damage to a planeswalker removes that many loyalty
            # counters (the 0-loyalty SBA then sends it to the graveyard).
            target.add_counters("loyalty", -final)
        else:
            target.damage_marked += final
        self.state.fire_event(
            GameEvent(
                EventType.DAMAGE,
                amount=final,
                is_player=is_player,
                target_id=target.id if is_player else target.instance_id,
            )
        )

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

    def destroy(self, obj: GameObject) -> None:
        self._move_to_graveyard(obj)

    def exile(self, obj: GameObject) -> None:
        """Move ``obj`` to its owner's exile zone (RULE 406), from anywhere.

        Fires `LEAVES_BATTLEFIELD` when it was in play, then `EXILE`. Unlike
        destroy this never diverts a commander to the command zone — exile is
        a specific zone move, and command-zone replacement is destroy/death's
        rule (903.9).
        """
        was_on_battlefield = obj in self.state.battlefield
        owner = self.state.player_by_id(obj.owner_id)
        if was_on_battlefield:
            self.state.remove_from_battlefield(obj)
        else:
            self._remove_from_current_zone(owner, obj)
        obj.tapped = False
        obj.damage_marked = 0
        owner.add_to_zone(obj, Zone.EXILE)
        if was_on_battlefield:
            self.state.fire_event(
                GameEvent(EventType.LEAVES_BATTLEFIELD, object=obj.name, owner_id=obj.owner_id)
            )
        self.state.fire_event(
            GameEvent(EventType.EXILE, object=obj.name, owner_id=obj.owner_id)
        )

    def set_tapped(self, obj: GameObject, tapped: bool = True) -> None:
        """Tap or untap a permanent (RULE 701.21 / 701.22).

        No TAP/UNTAP event is modeled (no card in scope triggers off it), so
        this is a direct state change — the single choke point regardless.
        """
        obj.tapped = tapped

    def add_counters(self, obj: GameObject, amount: int) -> None:
        """Put ``amount`` +1/+1 counters on ``obj`` (RULE 122); negatives remove.

        Works on any permanent, not just creatures (RULE 122.1a) — a land can
        enter with +1/+1 counters and use them once it later becomes a creature.
        The layer engine (`continuous.recompute`) reads the net counter into
        derived P/T on the next SBA pass, which the caller's resolution already
        triggers.
        """
        obj.plus_one_counters += amount

    def create_token(
        self, controller_id: str, token_card: Card, count: int = 1
    ) -> list[GameObject]:
        """Create ``count`` token permanents under ``controller_id`` (RULE 111.5).

        Each token is a fresh `GameObject` flagged ``is_token`` (so RULE 704.5d
        removes it once it leaves the battlefield), with its abilities bound
        from the token's own definition — exactly like a real permanent — then
        put onto the battlefield firing `ENTERS_BATTLEFIELD`. The token's owner
        *and* controller is the creating player (RULE 111.4). Returns the tokens.
        """
        from .effect_binder import bind_from_catalogue  # function-scoped: avoid cycle

        created: list[GameObject] = []
        for _ in range(max(0, count)):
            token = GameObject(
                token_card,
                owner_id=controller_id,
                zone=Zone.BATTLEFIELD,
                is_token=True,
            )
            bind_from_catalogue(token)  # token abilities are live like any card's
            token.summoning_sick = True  # RULE 302.6 applies to tokens too
            token.tapped = ability_catalogue.enters_tapped(token_card)  # RULE 614.1
            self.state.add_to_battlefield(token)
            self.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD,
                    controller_id=controller_id,
                    card_id=token_card.id,
                    object=token.name,
                    is_token=True,
                )
            )
            created.append(token)
        return created

    def advance_sagas(self, player: Player) -> None:
        """Add a lore counter to each Saga ``player`` controls (RULE 714.2b).

        Called after the controller's draw step. The 0-chapter-remaining Saga
        is sacrificed by a state-based action (`_sba_pass`), so this only
        advances the chapter here."""
        for obj in self.state.permanents_controlled_by(player.id):
            if obj.card.is_saga:
                obj.add_counters("lore", 1)

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

    def gain_life(self, player: Player, amount: int) -> None:
        if amount <= 0:
            return
        player.gain_life(amount)
        self.state.fire_event(
            GameEvent(EventType.LIFE_GAINED, player_id=player.id, amount=amount)
        )

    def counter_spell(self, target: Any) -> None:
        """Remove a spell (a `StackItem` or its game object) from the stack.

        A countered spell goes to its owner's graveyard (RULE 701.5g) and
        never resolves.
        """
        item = None
        for candidate in self.state.stack:
            if candidate is target or candidate.obj is target:
                item = candidate
                break
        if item is None:
            return
        self.state.stack.remove(item)
        if item.obj is not None:
            owner = self.state.player_by_id(item.obj.owner_id)
            destination = Zone.COMMAND if item.obj.is_commander else Zone.GRAVEYARD
            owner.add_to_zone(item.obj, destination)
        self.state.fire_event(
            GameEvent(EventType.SPELL_RESOLVED, spell=item.description, countered=True)
        )

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
    ) -> None:
        """Open a "search your library" choice on the game state (a tutor).

        ``criteria`` says *what* to look for (see `models.card_query`: ``""``
        = "a card", ``"Creature"``, ``{"basic": True}``, ``{"type": [...],
        "max_mana_value": 3}``, …); ``destination`` says *where* the found
        card goes ("hand"/"battlefield"/"battlefield_tapped"/"library_top"/
        "library_bottom"/"graveyard"/"exile"); ``count`` is how many cards
        ("up to N"), offered one at a time.

        Records the eligible library cards as a `state.pending_choice` — the
        engine's resolve loop stops on it and the session surfaces it, and
        `resolve_search_choice` finishes the search once the player picks (or
        declines). Searching (RULE 701.19) always shuffles afterwards (RULE
        701.19e); with nothing eligible it just shuffles, no choice needed.
        """
        self.state.fire_event(
            GameEvent(EventType.LIBRARY_SEARCHED, player_id=player.id)
        )
        eligible = [obj for obj in player.library if card_query.matches(obj.card, criteria)]
        if not eligible or count <= 0:
            self.shuffle_library(player)
            return
        self.state.pending_choice = self._search_choice(
            player, criteria, destination, count, optional, found=[]
        )

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

        declined = instance_id is None
        if not declined:
            eligible_ids = {e["instance_id"] for e in choice["eligible"]}
            if instance_id not in eligible_ids:
                raise ValueError(f"{instance_id} is not a valid search target")
            found.append(instance_id)

        remaining = choice["count"] - len(found)
        still_eligible = [
            obj
            for obj in player.library
            if obj.instance_id not in found
            and card_query.matches(obj.card, choice["criteria"])
        ]
        if not declined and remaining > 0 and still_eligible:
            self.state.pending_choice = self._search_choice(
                player, choice["criteria"], choice["destination"],
                choice["count"], choice["optional"], found=found,
            )
            return

        self.state.pending_choice = None
        self._finish_search(player, found, choice["destination"])

    def _search_choice(
        self,
        player: Player,
        criteria: Any,
        destination: str,
        count: int,
        optional: bool,
        found: list[int],
    ) -> dict[str, Any]:
        """Build the serializable `pending_choice` for a search in progress."""
        eligible = [
            {"instance_id": obj.instance_id, "name": obj.name}
            for obj in player.library
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
        prompt = f"Suche in der Bibliothek nach: {description}"
        if count > 1:
            prompt += f" (noch {count - len(found)})"
        return {
            "kind": "search",
            "player_id": player.id,
            "destination": destination,
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
        self, player: Player, found: list[int], destination: str
    ) -> None:
        """Move every chosen card to ``destination``, then shuffle (RULE 701.19e)."""
        chosen: list[GameObject] = []
        for instance_id in found:
            obj = next((o for o in player.library if o.instance_id == instance_id), None)
            if obj is not None:
                player.library.remove(obj)
                chosen.append(obj)

        # "Shuffle, then put on top/bottom" (RULE 701.19e for a library
        # destination): the found card must land *after* the shuffle, so its
        # position is known — otherwise the shuffle would move it.
        to_library = destination in ("library_top", "library_bottom")
        if to_library:
            self.shuffle_library(player)
        for obj in chosen:
            self._put_searched_card(player, obj, destination)
        if not to_library:
            self.shuffle_library(player)

    def _put_searched_card(self, player: Player, obj: GameObject, destination: str) -> None:
        if destination in ("battlefield", "battlefield_tapped"):
            obj.summoning_sick = True
            obj.tapped = destination == "battlefield_tapped"
            self.state.add_to_battlefield(obj)
            self.state.fire_event(
                GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=player.id, object=obj.name)
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
        else:  # hand (default) — most tutors
            player.add_to_zone(obj, Zone.HAND)

    def shuffle_library(self, player: Player) -> None:
        """Shuffle a player's library and announce it (RULE 701.20)."""
        player.shuffle_library()
        self.state.fire_event(GameEvent(EventType.SHUFFLE, player_id=player.id))

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

    def _move_to_graveyard(self, obj: GameObject) -> None:
        was_on_battlefield = obj in self.state.battlefield
        was_creature = obj.is_creature
        self.state.remove_from_battlefield(obj)
        owner = self.state.player_by_id(obj.owner_id)
        obj.tapped = False
        obj.damage_marked = 0
        # RULE 903.9: a commander's owner may put it into the command zone
        # instead of wherever it would otherwise go. This MVP always takes
        # that near-universal choice rather than modeling it as an actual
        # (optional) player decision.
        destination = Zone.COMMAND if obj.is_commander else Zone.GRAVEYARD
        owner.add_to_zone(obj, destination)
        if was_on_battlefield:
            self.state.fire_event(
                GameEvent(EventType.LEAVES_BATTLEFIELD, object=obj.name, owner_id=obj.owner_id)
            )
            if was_creature:
                self.state.fire_event(
                    GameEvent(EventType.DIES, object=obj.name, owner_id=obj.owner_id)
                )

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
        # Re-derive continuous effects first (RULE 613) so P/T, types and
        # granted keywords are current before any SBA reads them — an anthem
        # dropping a creature to 0 toughness must be seen here.
        continuous.recompute(self.state)

        # 704.5a/c: player at 0 or less life, or who drew from empty, loses.
        for player in self.state.players:
            if player.has_lost:
                continue
            drew_empty = getattr(player, "attempted_draw_from_empty", False)
            if (player.life <= 0 or drew_empty) and not self._loss_prevented(player):
                reason = player.loss_reason or ("life" if player.life <= 0 else "draw_from_empty")
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
        # that lethal). Indestructible (RULE 702.12b) is destroyed by neither.
        for obj in self.state.permanents():
            if not obj.is_creature or obj.toughness is None:
                continue
            if combat.has_indestructible(obj):
                continue
            lethal_marked = obj.toughness > 0 and obj.damage_marked >= obj.toughness
            if lethal_marked or (obj.dealt_deathtouch_damage and obj.damage_marked > 0):
                self._move_to_graveyard(obj)
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

        # 704.5d: a token in any zone other than the battlefield ceases to
        # exist. It *did* reach that zone (its owner's graveyard/exile/…) long
        # enough for its leaves-the-battlefield / dies triggers to have fired
        # when it was moved there — this SBA then removes it from the game, and
        # RULE 111.7-8 keep it from ever returning to another zone.
        if self._remove_stranded_tokens():
            return True

        return False

    def _remove_stranded_tokens(self) -> bool:
        """Remove any token that has left the battlefield (RULE 704.5d)."""
        for player in self.state.players:
            for zone in Player.PERSONAL_ZONES:  # every non-battlefield zone
                cards = player.zones[zone]
                for obj in cards:
                    if obj.is_token:
                        cards.remove(obj)
                        return True
        return False

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
