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

from typing import Any, Optional

from ..models.card import Card
from ..models.events import EventType, GameEvent
from ..models.game_object import GameObject, Zone
from ..models.game_state import GameState, StackItem
from ..models.mana_cost import ManaCost
from ..models.player import Player
from .effects import (
    GameContext,
    ReplacementEffect,
    StaticEffect,
    TriggeredAbility,
    WinConditionEffect,
)


class RulesEngine:
    """Applies MTG rules to a `GameState`."""

    def __init__(self, state: GameState) -> None:
        self.state = state
        self.context = GameContext(state, self)
        #: Triggered abilities that fired and are waiting to be put on the
        #: stack (RULE 603.3 — after the current action, before priority).
        self.pending_triggers: list[tuple[TriggeredAbility, GameEvent]] = []
        # Collect triggers for every event the game fires.
        state.subscribe(self._collect_triggers)

    # ------------------------------------------------------------------
    # Mana cost lookup (RULE 202)
    # ------------------------------------------------------------------

    @staticmethod
    def mana_cost_of(card: Card) -> ManaCost:
        """The structured cost of a card, from its raw mana string."""
        return ManaCost.parse(getattr(card, "mana_cost_string", "") or "")

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
        (RULE 603.3b APNAP ordering — simplified: no intra-player choice).
        """
        if not self.pending_triggers:
            return 0
        active_id = self.state.active_player.id
        triggers = sorted(
            self.pending_triggers,
            key=lambda t: 0 if t[0].controller_id == active_id else 1,
        )
        count = len(triggers)
        for ability, _event in triggers:
            self.state.stack.append(
                StackItem(
                    kind="ability",
                    controller_id=ability.controller_id or active_id,
                    effects=[ability],
                    description=ability.description or "triggered ability",
                )
            )
        self.pending_triggers.clear()
        return count

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
    ) -> StackItem:
        """Pay the cost, move the card to the stack (RULE 601).

        Timing/priority legality is enforced by the caller (game engine /
        `legal_actions`); this performs the mechanical cast. Raises
        ValueError if the mana cost can't be paid.
        """
        cost = self.mana_cost_of(obj.card)
        if not player.mana_pool.can_pay(cost, life_available=player.life):
            raise ValueError(f"{player.id} cannot pay for {obj.name}")
        player.mana_pool.pay(cost, life_available=player.life)

        if obj in player.hand:
            player.remove_from_zone(obj, Zone.HAND)
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
            GameEvent(EventType.SPELL_CAST, player_id=player.id, card_id=obj.card.id, spell=obj.name)
        )
        return item

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
                obj.tapped = False
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
        self, target: Any, amount: int, source: Optional[GameObject] = None
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
            target.lose_life(final)
            self.state.fire_event(
                GameEvent(EventType.LIFE_LOST, player_id=target.id, amount=final)
            )
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

    def destroy(self, obj: GameObject) -> None:
        self._move_to_graveyard(obj)

    def _move_to_graveyard(self, obj: GameObject) -> None:
        was_on_battlefield = obj in self.state.battlefield
        was_creature = obj.is_creature
        self.state.remove_from_battlefield(obj)
        owner = self.state.player_by_id(obj.owner_id)
        obj.tapped = False
        obj.damage_marked = 0
        obj.zone = Zone.GRAVEYARD
        owner.graveyard.append(obj)
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
        # 704.5a/c: player at 0 or less life, or who drew from empty, loses.
        for player in self.state.players:
            if player.has_lost:
                continue
            drew_empty = getattr(player, "attempted_draw_from_empty", False)
            if (player.life <= 0 or drew_empty) and not self._loss_prevented(player):
                reason = player.loss_reason or ("life" if player.life <= 0 else "draw_from_empty")
                self._player_loses(player, reason)
                return True

        # 704.5f: creature with toughness <= 0 goes to graveyard.
        for obj in self.state.permanents():
            if obj.is_creature and obj.toughness is not None and obj.toughness <= 0:
                self._move_to_graveyard(obj)
                return True

        # 704.5g: creature with lethal marked damage is destroyed.
        for obj in self.state.permanents():
            if (
                obj.is_creature
                and obj.toughness is not None
                and obj.damage_marked >= obj.toughness
                and obj.toughness > 0
            ):
                self._move_to_graveyard(obj)
                return True

        # 704.5j: legend rule — same-named legendaries a player controls.
        if self._apply_legend_rule():
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
