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
    return True  # unknown type word → any permanent, so the cost is payable


def _main_type_words(card: Card) -> list[str]:
    """A card's printed main (pre-em-dash) type words, lowercase — unlike
    `GameObject.type_words` (which always adds "permanent", correctly for
    a *battlefield* object, RULE 110.1) this is meaningful for a card in
    any zone, including a hand card mid-discard that may not be a
    permanent card at all (an instant/sorcery). Used to stamp `EventType.
    DISCARD_CARD`'s own ``object_types`` so a "discards a **permanent**
    card" RULE 603.1 group condition (Tergrid, God of Fright, MEC-43
    round 4E) can tell the two apart.
    """
    main = card.type_line.partition("—")[0]
    return sorted(w for w in main.strip().lower().split() if w)


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




class DrawDiscardMixin:
    """Draw, mill, discard."""

    def draw(self, player: Player, count: int = 1) -> None:
        if count <= 0:
            return
        if count == 1:
            # The overwhelmingly common case (every turn-based draw-step
            # draw, most card-draw spells) — skip straight to the per-card
            # path below with no instruction-level replacement pass at all.
            # No shipped `DRAW_INSTRUCTION` replacement ever applies to a
            # single-card instruction (Alms Collector's own `min_count` is
            # 2), so this is a pure performance fast path, not a behaviour
            # change — `draw()` is the single most heavily-exercised
            # primitive in the engine, and doubling its replacement-scan
            # cost for every ordinary one-card draw measurably slowed down
            # long games (a bot test's own many-hundred-turn line went from
            # comfortably under the per-test timeout to tripping it).
            self._single_draw(player)
            return
        # MEC-32: fire one event for the whole "draw `count` cards"
        # instruction *before* splitting it into individual card moves
        # below — see `EventType.DRAW_INSTRUCTION`'s own docstring for why
        # this is a separate event type from the per-card `DRAW` each
        # `_single_draw` call fires (so an ordinary per-card replacement
        # can't double-apply against both). Only a replacement that
        # specifically registers against `DRAW_INSTRUCTION` (Alms
        # Collector's "if an opponent would draw two or more cards") ever
        # sees this one; nothing else changes for every other draw
        # replacement already shipped.
        event = GameEvent(EventType.DRAW_INSTRUCTION, player_id=player.id, count=count)

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is None:
                return
            n = resolved.get("count", count)
            for _ in range(n):
                self._single_draw(player)

        self.apply_replacements(event, on_resolved=_finish)
    def _single_draw(self, player: Player) -> None:
        # RULE 121.5-adjacent "each player can't draw more than N cards each
        # turn." (Spirit of the Labyrinth) — a cap checked *before* this draw
        # even starts (the extra draw simply doesn't happen, no replacement
        # rewrite involved), the draw-side mirror of `GameEngine.can_cast`'s
        # `cast_limit` gate. `draw(player, count>1)` calls this once per
        # card, so the cap is naturally enforced cumulatively across a
        # single "draw two cards" effect too.
        draw_limit = continuous.max_draws_per_turn(self.state, player)
        if draw_limit is not None and self.state.cards_drawn_this_turn.get(player.id, 0) >= draw_limit:
            return
        # MEC-32: "the first one they draw in each of their draw steps" only
        # ever means the step's own built-in draw — a card drawn from a
        # spell/ability at any other time (including elsewhere in the same
        # turn) is never exempt, so this stays `False` unless we're
        # literally inside `player`'s own draw step right now.
        first_in_draw_step = False
        if self.state.current_step == "draw" and self.state.active_player.id == player.id:
            first_in_draw_step = not self.state.first_draw_done_this_step.get(player.id, False)
            self.state.first_draw_done_this_step[player.id] = True
        event = GameEvent(
            EventType.DRAW, player_id=player.id, count=1, first_in_draw_step=first_in_draw_step,
        )

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
                self.state.cards_drawn_this_turn_ids.setdefault(player.id, []).extend(
                    o.instance_id for o in drawn if getattr(o, "instance_id", None) is not None
                )
                self.state.record_stat(player.id, "draw", amount=len(drawn))
                self.state.fire_event(
                    GameEvent(
                        EventType.DRAW, player_id=player.id, count=len(drawn),
                        # MEC-42: this is the event trigger-collection
                        # actually sees — `first_in_draw_step` was
                        # previously only ever threaded into the *input*
                        # event `apply_replacements` reads (MEC-32,
                        # Notion Thief/Chains of Mephistopheles), never
                        # forwarded here, so no trigger's own "except the
                        # first ... draw step" condition (Orcish
                        # Bowmasters-shaped) could ever actually read it.
                        first_in_draw_step=first_in_draw_step,
                    )
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
            self.state.fire_event(
                GameEvent(
                    EventType.DISCARD_CARD, player_id=player.id, instance_id=obj.instance_id,
                    # "…discards a permanent card." (Tergrid, God of
                    # Fright's own front face, MEC-43 round 4E) — the main
                    # printed type words *without* `GameObject.type_words`'
                    # always-on "permanent" (that property assumes a
                    # battlefield object; a hand card obviously isn't one),
                    # so a "permanent card" RULE 603.1 group condition can
                    # tell an instant/sorcery discard apart from the rest.
                    object_types=_main_type_words(obj.card),
                )
            )
        if discarded:
            self.state.fire_event(
                GameEvent(EventType.DISCARD, player_id=player.id, count=discarded)
            )
    def discard_choice(
        self,
        player: Player,
        count: int,
        source: Optional[GameObject] = None,
        then_specs: Optional[list[dict]] = None,
    ) -> None:
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

        ``then_specs`` (MEC-43 round 4C, Syphon Mind's "You draw a card for
        each card discarded this way") are serialized `EffectSpec` dicts
        applied once ``player`` actually discards — `request_choose_
        objects`'s own "if you do" tail runs in both the forced and the
        interactive branch, so this fires exactly once per real discard
        (never for a would-be discard against an empty hand), the same
        count `DiscardEffect`'s own ``count`` already asks for.
        """
        self.request_choose_objects(
            player, list(player.hand), "discard", count=count,
            prompt="Wähle eine Karte zum Abwerfen", source=source, then_specs=then_specs,
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
    def put_hand_card_on_bottom_then_draw(self, player: Player) -> None:
        """"You may put a card from your hand on the bottom of your library.
        If you do, draw a card." (Volcanic Spite) — a pure card exchange
        riding an already-resolved removal spell, so the "may" is auto-taken
        whenever the hand isn't empty, the same "auto-pick, no chooser in
        this MVP" idiom `discard`/`put_hand_cards_on_top` already use for a
        value-neutral card selection; unlike `put_hand_cards_on_top`, the
        card goes to library *index 0* (the bottom — "top of deck is the
        list end", the same convention that method's own comment states).
        """
        if not player.hand:
            return
        obj = player.hand.pop()
        obj.zone = Zone.LIBRARY
        player.library.insert(0, obj)
        self.draw(player, 1)
    def put_hand_card_on_top_of_library(self, obj: GameObject) -> None:
        """Put a specific card from its owner's hand on top of their
        library — MEC-30's Penance ("Put a card from your hand on top of
        your library: …"), the chosen-card cost-payment counterpart to
        `put_hand_cards_on_top`'s auto-pick-off-the-back convention (a cost
        is a genuine RULE 602.1 choice, resolved by `ActivationMixin.
        _resolve_put_hand_card_cost` the same way `discard_specific` backs
        a plain discard-N cost's own chosen card)."""
        player = self.state.player_by_id(obj.owner_id)
        player.remove_from_zone(obj, Zone.HAND)
        player.add_to_zone(obj, Zone.LIBRARY)  # top of deck is the list end
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
            GameEvent(
                EventType.DISCARD_CARD, player_id=player.id, instance_id=obj.instance_id,
                object_types=_main_type_words(obj.card),  # see `discard`'s own comment
            )
        )
        self.state.fire_event(
            GameEvent(EventType.DISCARD, player_id=player.id, count=1)
        )
