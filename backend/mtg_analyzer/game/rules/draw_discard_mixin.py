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

import random
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
from ..effects.core import (
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
    MadnessToGraveyardEffect,
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




def _dredge_value(obj: Any) -> Optional[int]:
    """The N in ``obj``'s Dredge N (RULE 702.52a), or ``None`` if it has no
    dredge ability. Dredge is a ``NUMBER``-shaped parametric keyword — like
    Toxic/Annihilator it never joins `combat._obj_keywords`; `effect_binder.
    attach_keyword` docks it onto ``parametric_keywords["dredge"] = {"n":
    N}`` instead (PAR-25)."""
    if getattr(obj, "loses_all_abilities", False):
        return None
    n = ((getattr(obj, "parametric_keywords", None) or {}).get("dredge") or {}).get("n")
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


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
            #
            # RULE 702.52a: Dredge replaces a *would-draw*, and is "you
            # may" — offered here (the single-card path only; a multi-card
            # `draw()` is a documented simplification) as an interactive
            # `dredge` `pending_choice`. If it opens, the draw is deferred:
            # `GameEngine._resume_dredge` either mills+returns the
            # dredged card or falls back to `_single_draw`.
            if self._maybe_offer_dredge(player):
                return
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
                # RULE 702.94a Miracle (PAR-26): "You may cast this card for
                # its miracle cost when you draw it if it's the first card
                # you've drawn this turn." Arm the same-turn miracle-cost
                # cast window on the first drawn card, before the count is
                # bumped below (see `_arm_miracle`).
                if self.state.cards_drawn_this_turn.get(player.id, 0) == 0:
                    self._arm_miracle(player, drawn[0])
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
    def _maybe_offer_dredge(self, player: Player) -> bool:
        """RULE 702.52a-c — if ``player`` would draw a card and has one or
        more Dredge cards in their graveyard with at least that card's N in
        their library, open a `dredge` `pending_choice` and return ``True``
        (the caller then defers the draw). "You may", so "draw a card" is
        always an option too. Returns ``False`` when there is nothing to
        offer, leaving the ordinary draw to proceed.
        """
        if self.state.pending_choice is not None:
            return False
        candidates = [
            o for o in player.graveyard
            if (_dredge_value(o) or 0) > 0 and _dredge_value(o) <= len(player.library)
        ]
        if not candidates:
            return False
        options = [
            {
                "id": str(o.instance_id),
                "instance_id": o.instance_id,
                "label": f"{o.name} (Dredge {_dredge_value(o)})",
            }
            for o in candidates
        ]
        options.append({"id": "draw", "label": "Eine Karte ziehen"})
        self.open_choice({
            "kind": "dredge",
            "player_id": player.id,
            "prompt": "Statt zu ziehen aufmahlen (Dredge)?",
            "options": options,
        })
        return True
    @continuations.choice("dredge", answer=continuations.ANSWER_STR, rule="702.52")
    def _resume_dredge(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a `dredge` `pending_choice` (RULE 702.52b): ``"draw"`` /
        ``None`` draws the deferred card normally; a card's instance id
        mills that card's N and, if it milled anything or not, returns the
        card from the graveyard to its owner's hand."""
        player = self.state.player_by_id(choice["player_id"])
        if answer in (None, "draw", "decline"):
            self._single_draw(player)
            return
        try:
            card = self.state.find_object(int(answer))
        except (TypeError, ValueError):
            card = None
        n = _dredge_value(card) if card is not None else None
        if card is None or n is None or card.zone != Zone.GRAVEYARD:
            self._single_draw(player)
            return
        self.mill(player, n)
        if card.zone == Zone.GRAVEYARD:  # RULE 702.52b "return this card"
            self.return_from_graveyard(card, "hand")
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
    def _maybe_madness(self, player: Player, obj: GameObject) -> bool:
        """RULE 702.35a: a discarded Madness card is exiled instead of going
        to the graveyard, becomes castable from exile for its madness cost
        (`obj.alt_cast_cost`, bound alongside `obj.madness`) this turn, and
        — RULE 702.35b — is put into the graveyard if it hasn't been cast by
        the next end step (`MadnessToGraveyardEffect`, a delayed trigger).
        Returns ``True`` when it intercepted the move (the caller then skips
        the graveyard step but still fires the DISCARD_CARD event). PAR-26.
        """
        if not getattr(obj, "madness", False):
            return False
        if obj in player.hand:  # `discard` has already popped it; `discard_specific` hasn't
            player.remove_from_zone(obj, Zone.HAND)
        player.add_to_zone(obj, Zone.EXILE)
        obj.madness_exiled = True  # `_offer_cast` reads this to suppress the printed-cost offer
        self.state.temp_play_permissions[obj.instance_id] = self.state.internal_turn.number
        self.state.temp_play_permission_player[obj.instance_id] = player.id
        self.state.temp_play_permission_source[obj.instance_id] = obj.name
        self.state.temp_play_permission_same_turn_only.add(obj.instance_id)
        self.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=player.id,
                step="end",
                scope="any",
                effects=[MadnessToGraveyardEffect(source=obj)],
                targets=[obj],
                description=f"{obj.name}: Madness — in den Friedhof, falls nicht gewirkt",
            )
        )
        return True

    def _arm_miracle(self, player: Player, obj: GameObject) -> None:
        """RULE 702.94a-b: if ``obj`` (the first card ``player`` drew this
        turn) has Miracle, make it castable from hand for its miracle cost
        (`obj.alt_cast_cost`, bound alongside `obj.miracle`) this turn.
        Deliberately a whole-turn window rather than RULE 702.94b's narrow
        "before you get priority" one — a documented simplification (PAR-26).
        The window is torn down at cleanup (`GameEngine._step_cleanup`) and
        the moment the card is cast or otherwise leaves the hand.
        """
        if not getattr(obj, "miracle", False):
            return
        obj.miracle_armed = True
        self.state.miracle_armed_ids.add(obj.instance_id)

    def _note_discarded(self, player_id: str, n: int = 1) -> None:
        """Bump `GameState.cards_discarded_this_turn` — called at every
        `DISCARD_CARD` fire site so "for each card you've discarded this
        turn" (Living Laser, Change of Fortune) counts every route."""
        counts = self.state.cards_discarded_this_turn
        counts[player_id] = counts.get(player_id, 0) + max(0, n)

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
            madness = self._maybe_madness(player, obj)  # RULE 702.35a
            if not madness:
                obj.zone = Zone.GRAVEYARD
                player.graveyard.append(obj)
                self._flag_commander_zone_choice(obj)  # RULE 903.9a
            discarded += 1
            self._note_discarded(player.id)
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

    def discard_random(self, player: Player, count: int = 1) -> None:
        """"…discards a card at random." (RULE 701.8d — Black Cat / Bottomless
        Pit / Hypnotic Specter family). Non-interactive like `discard`, but
        the card is chosen uniformly at random from ``player``'s hand rather
        than auto-picking the last one (which, for a random discard, would
        be a real rules difference — a chosen random card can be a bomb the
        player would never have pitched). Fires the same per-card
        `DISCARD_CARD` + aggregate `DISCARD` events and honours Madness
        (RULE 702.35a) exactly as `discard` does.
        """
        discarded = 0
        for _ in range(count):
            if not player.hand:
                break
            obj = random.choice(player.hand)
            player.hand.remove(obj)
            madness = self._maybe_madness(player, obj)  # RULE 702.35a
            if not madness:
                obj.zone = Zone.GRAVEYARD
                player.graveyard.append(obj)
                self._flag_commander_zone_choice(obj)  # RULE 903.9a
            discarded += 1
            self._note_discarded(player.id)
            self.state.fire_event(
                GameEvent(
                    EventType.DISCARD_CARD, player_id=player.id, instance_id=obj.instance_id,
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
        optional: bool = False,
    ) -> None:
        """Interactive discard (RULE 701.8): ``player`` — the one discarding,
        not necessarily an effect's controller (Mind Rot targets an
        opponent) — picks which ``count`` cards leave their own hand,
        through the same `_request_choose_objects` chooser that replaced
        "auto-pick the first candidate" for sacrifice/tap/bounce effects.
        Forced with no prompt when the hand has at most ``count`` cards left
        (a "discard your hand" effect, or `count` >= hand size) — nothing to
        choose between. Used by looting-shaped effects (`DiscardEffect`);
        cost payment still uses the plain, non-interactive `discard` (see
        its own docstring) since a cost is paid in one synchronous call.

        ``optional`` makes ``count`` a ceiling rather than a quota — "discard
        **up to** N cards" (Cathartic Pyre / Kinetic Augur / Daretti +2),
        the RULE 601.2b "you may" over each pick.

        ``then_specs`` (MEC-43 round 4C, Syphon Mind's "You draw a card for
        each card discarded this way") are serialized `EffectSpec` dicts
        applied once ``player`` actually discards — `request_choose_
        objects`'s own "if you do" tail runs in both the forced and the
        interactive branch, so this fires exactly once per real discard
        (never for a would-be discard against an empty hand), the same
        count `DiscardEffect`'s own ``count`` already asks for.
        """
        self._request_choose_objects(
            player, list(player.hand), "discard", count=count, optional=optional,
            prompt="Wähle eine Karte zum Abwerfen", source=source, then_specs=then_specs,
        )

    def discard_matching(self, player: Player, mana_value: Optional[int] = None) -> None:
        """Non-interactive "discards all cards with `<X>` mana value" (PAR-74
        — Infernal Kirin: "target player reveals their hand and discards all
        cards with that spell's mana value."). RULE 601.2c's "all" leaves
        nothing to choose between, unlike `discard_choice`'s RULE 701.8 pick
        — every matching card leaves, via the same non-interactive
        `discard_specific` Channel/Cycling costs use, rather than opening a
        chooser over a foregone conclusion.
        """
        if mana_value is None:
            return
        for obj in list(player.hand):
            if obj.card.converted_mana_cost == mana_value:
                self.discard_specific(obj)

    def exile_hand_choice(
        self,
        player: Player,
        count: int = 1,
        source: Optional[GameObject] = None,
        then_specs: Optional[list[dict]] = None,
        optional: bool = False,
    ) -> None:
        """Interactive exile-from-hand (PAR-74 — Kyoki, Sanity's Eclipse:
        "target opponent exiles a card from their hand."). The exile sibling
        of `discard_choice` just above: ``player`` — not necessarily an
        effect's controller — picks which ``count`` cards leave their own
        hand, through the same `_request_choose_objects` chooser, whose
        ``"exile"`` action already exists for the Gemstone Caverns opening-
        hand pick (`offer_opening_hand_battlefield_choice`) and simply calls
        `RulesEngine.exile` on whatever object is chosen, hand card or not.
        """
        self._request_choose_objects(
            player, list(player.hand), "exile", count=count, optional=optional,
            prompt="Wähle eine Karte aus deiner Hand zum Exilieren",
            source=source, then_specs=then_specs,
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
        if not self._maybe_madness(player, obj):  # RULE 702.35a
            player.remove_from_zone(obj, Zone.HAND)
            player.add_to_zone(obj, Zone.GRAVEYARD)
            self._flag_commander_zone_choice(obj)  # RULE 903.9a
        self._note_discarded(player.id)
        self.state.fire_event(
            GameEvent(
                EventType.DISCARD_CARD, player_id=player.id, instance_id=obj.instance_id,
                object_types=_main_type_words(obj.card),  # see `discard`'s own comment
            )
        )
        self.state.fire_event(
            GameEvent(EventType.DISCARD, player_id=player.id, count=1)
        )
