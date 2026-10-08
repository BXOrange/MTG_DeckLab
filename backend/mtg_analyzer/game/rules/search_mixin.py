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
from .. import card_registry, combat, continuous, copy_mechanics, dungeons, face_down, variants
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
    DrawCardEffect,
    LoseLifeEffect,
    ReturnUncastExiledEffect,
    SacrificeSpecificEffect,
    TheRingTemptsYouEffect,
    GameContext,
    GameEffect,
    GrantSearchLimitedToTopNEffect,
    GrantSearchProhibitedEffect,
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


#: RULE 305.6's five basic land types — a local copy of `continuous.
#: _BASIC_LAND_TYPES` rather than an import (that name is module-private,
#: and this module already keeps a few other rules constants as small local
#: copies rather than cross-module imports — see `_matches_permanent_type`'s
#: own docstring just above).
_BASIC_LAND_TYPE_WORDS: frozenset[str] = frozenset(
    {"plains", "island", "swamp", "mountain", "forest"}
)


def _land_types_of(card: Card) -> frozenset[str]:
    """The basic land type word(s) printed on ``card``'s type line."""
    type_line = (card.type_line or "").lower()
    return frozenset(w for w in _BASIC_LAND_TYPE_WORDS if w in type_line)


def _shares_land_type(
    candidate: GameObject, found: list[GameObject], share_land_type: bool,
) -> bool:
    """"...basic land cards that share a land type." (Myriad Landscape,
    MEC-43 round 3) — whether ``candidate`` shares a basic land type with at
    least one already-found card in this same multi-pick search. Vacuously
    true when the constraint isn't active, or nothing's been found yet (the
    *first* pick is always unconstrained — nothing to share with)."""
    if not share_land_type or not found:
        return True
    candidate_types = _land_types_of(candidate.card)
    return any(candidate_types & _land_types_of(f.card) for f in found)


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




class SearchMixin:
    def _request_resolution_play(self, player: Player, cards: list[GameObject], *, repeat: bool = False,
                                 only_spells: bool = False, max_mana_value: Optional[int] = None,
                                 bottom_remaining: Optional[list[int]] = None, zone: str = "exile",
                                 free: bool = True, exile_after_cast: bool = False,
                                 lock_casting: bool = False, mana_wildcard: Optional[str] = None,
                                 owner_life_loss: bool = False, owner_life_losses: Optional[list[dict]] = None,
                                 cast_rider: Optional[str] = None) -> None:
        """RULE 608.2g: offer a cast/play from the specified zone during this resolution."""
        if self.state.pending_choice or self.state.resolution_play_choice:
            raise ValueError("another resolution choice is already pending")
        cards = [obj for obj in cards if obj.zone.value == zone]
        if not cards:
            if owner_life_loss:
                for loss in owner_life_losses or []:
                    self.lose_life(self.state.player_by_id(loss["owner_id"]), loss["amount"])
            return
        choice = {
            "kind": "play_during_resolution", "player_id": player.id,
            "zone": zone, "free": free, "exile_after_cast": exile_after_cast, "lock_casting": lock_casting,
            "repeat": repeat, "only_spells": only_spells, "max_mana_value": max_mana_value,
            "mana_wildcard": mana_wildcard, "cast_rider": cast_rider,
            "owner_life_loss": bool(owner_life_loss), "owner_life_losses": list(owner_life_losses or []),
            "prior_wildcard": {obj.instance_id: self.state.mana_wildcard_permission.get(obj.instance_id)
                               for obj in cards},
            "bottom_remaining": list(bottom_remaining or []),
            "instance_ids": [obj.instance_id for obj in cards],
            "options": [{"id": "decline", "label": "Decline"}],
            "prior_free": [obj.instance_id for obj in cards
                           if obj.instance_id in self.state.free_cast_instance_ids],
            "prior_timing": [obj.instance_id for obj in cards
                             if obj.instance_id in self.state.free_cast_ignore_timing_instance_ids],
        }
        self.state.resolution_play_choice = choice
        self.state.resolution_play_waiting = True
        if free:
            self.state.free_cast_instance_ids.update(choice["instance_ids"])
        self.state.free_cast_ignore_timing_instance_ids.update(choice["instance_ids"])
        if mana_wildcard in {"color", "type"}:
            self.state.mana_wildcard_permission.update({iid: mana_wildcard for iid in choice["instance_ids"]})
        self.open_choice(choice)

    def _finish_resolution_play_permission(self, played_id: Optional[int] = None) -> None:
        choice = self.state.resolution_play_choice
        if choice is None:
            return
        if choice.get("miracle"):
            for iid in choice["instance_ids"]:
                obj = self.state.find_object(iid)
                if obj is not None:
                    obj.miracle_armed = False
                    obj.miracle_revealed_incarnation = None
                    if getattr(obj, "miracle_granted", False):
                        obj.miracle = obj.miracle_granted = False
                        obj.alt_cast_cost = None
                self.state.miracle_armed_ids.discard(iid)
        ids = set(choice["instance_ids"])
        self.state.free_cast_instance_ids.difference_update(ids)
        self.state.free_cast_instance_ids.update(iid for iid in choice["prior_free"] if iid != played_id)
        self.state.free_cast_ignore_timing_instance_ids.difference_update(ids)
        self.state.free_cast_ignore_timing_instance_ids.update(iid for iid in choice["prior_timing"] if iid != played_id)
        for iid, prior in choice.get("prior_wildcard", {}).items():
            if prior is None or iid == played_id:
                self.state.mana_wildcard_permission.pop(iid, None)
            else:
                self.state.mana_wildcard_permission[iid] = prior
        # RULE 608.2c/g: the "then" payoff follows the entire repeated casting sequence.
        if (choice.get("owner_life_loss") and (played_id is None or not choice.get("repeat")
                or not any(iid != played_id for iid in choice["instance_ids"]))):
            with self.state.simultaneous():
                for loss in choice.get("owner_life_losses", []):
                    self.lose_life(self.state.player_by_id(loss["owner_id"]), loss["amount"])
            choice["owner_life_losses"] = []
        self.state.resolution_play_choice = None
        if choice.get("bottom_remaining"):
            self._bottom_remaining(self.state.player_by_id(choice["player_id"]), choice["bottom_remaining"],
                                   zone=choice.get("zone", "exile"))

    @continuations.choice("play_during_resolution", answer=continuations.ANSWER_STR, rule="608.2g")
    def _resume_play_during_resolution(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        if answer not in (None, "decline"):
            self.state.pending_choice = choice
            raise ValueError("play the card through the ordinary casting or land action")
        self._finish_resolution_play_permission()

    """Library search/dig/cascade/discover, scry/surveil, and every other 'look at N cards' shape."""

    #: Scry (RULE 701.18) and surveil (RULE 701.31) are one keyword action
    #: with one parameter changed: look at the top N cards of your library,
    #: send any number of them *somewhere*, and put the rest back on top in
    #: any order. Scry's "somewhere" is the bottom of the same library,
    #: surveil's is the graveyard — everything else about them, including
    #: the shape of the decision, is identical, so they share one
    #: implementation (`_look_top_choice`/`_resolve_look_top_choice`/
    #: `_finish_look_top`) and differ only by this table.
    #:
    #: Each entry: the event fired when the player looks, the German prompt
    #: and decline label for the **away** phase (which cards leave the top)
    #: and for the **order** phase (how the kept ones go back), and the label
    #: the away pile is described by. The away phase repeats until the player
    #: declines or runs out of cards; the order phase only opens with 2+
    #: cards still headed for the top, since one card has only one order.
    #: Both phases can be declined, and the two declines mean different
    #: things: declining the away phase keeps what's left and *moves on to
    #: ordering it*, while declining the order phase keeps the cards in the
    #: order they were already in — the one-click answer for the
    #: overwhelmingly common "fine as it is".
    _LOOK_TOP_KINDS: dict[str, dict[str, Any]] = {
        "scry": {
            "event": EventType.SCRY,
            "away": ("Hellsicht: welche Karte kommt unter die Bibliothek?", "Rest oben lassen"),
            "order": ("Hellsicht: welche Karte kommt zuoberst?", "Reihenfolge behalten"),
        },
        "surveil": {
            "event": EventType.SURVEIL,
            "away": ("Überwachen: welche Karte kommt auf den Friedhof?", "Rest oben lassen"),
            "order": ("Überwachen: welche Karte kommt zuoberst?", "Reihenfolge behalten"),
        },
        # RULE 701.29a Fateseal — scry on an *opponent's* library: the
        # looked-at cards' "away" pile goes to the bottom exactly like scry,
        # the only difference is *whose* library is reordered (`library_
        # owner`, threaded through the whole `_look_top` chain) versus who
        # makes the decision (`player`, the fatesealer). `event` fires
        # `FATESEALED` for convention parity with the other keyword actions
        # (no cached card triggers on it yet). MEC-76.
        "fateseal": {
            "event": EventType.FATESEALED,
            "away": ("Schicksalszeichnung: welche Karte kommt unter die Bibliothek?", "Rest oben lassen"),
            "order": ("Schicksalszeichnung: welche Karte kommt zuoberst?", "Reihenfolge behalten"),
        },
        # "Look at the top N cards of [target player's] library, then put them back in any order"
        # (Sensei's Divining Top, Elemental Augury, Architects of Will): no keyword action, so no
        # event and no "away" pile — just the "order" phase, over that library (`library_owner`).
        "reorder_top": {
            "event": None,
            "away": None,
            "order": ("Oberste Karten: welche kommt zuoberst?", "Reihenfolge behalten"),
        },
        "hand_bottom": {
            "event": None,
            "away": None,
            "order": ("Hand unter die Bibliothek: welche Karte liegt oben?", "Reihenfolge behalten"),
        },
        # MEC-43 round 4F (Scroll Rack): "look at the exiled cards and put
        # them on top of your library in any order" — the order-only
        # sibling of scry/surveil's own ordering phase (`open_scroll_rack_
        # order_choice` opens straight into "order", skipping "away"
        # entirely — every card here is always headed back to the library,
        # never elsewhere, so that entry is never used and left as
        # ``None``).
        "scroll_rack": {
            "event": None,
            "away": None,
            "order": ("Scroll Rack: welche Karte kommt zuoberst?", "Reihenfolge behalten"),
        },
    }
    def scry(self, player: Player, count: int, source: Optional["GameObject"] = None) -> None:
        """Scry ``count`` (RULE 701.18): look at the top ``count`` cards, put
        any number of them on the bottom and the rest back on top in any order.

        A real, interactive decision — see `_LOOK_TOP_KINDS` for the shape it
        shares with `surveil`. That is what makes Vancouver's "scry 1 after
        keeping a mulliganed hand" a real choice rather than theatre
        (`services/game_session.py`'s ``vancouver`` mulligan style). ``source``
        is the permanent/spell whose ability caused the scry, if any — carried
        through only so the pending-choice popup can say where it came from.
        """
        self._look_at_top(player, count, "scry", source=source)
    def surveil(self, player: Player, count: int, source: Optional["GameObject"] = None) -> None:
        """Surveil ``count`` (RULE 701.31): look at the top ``count`` cards,
        put any number into the *graveyard* and the rest back on top in any
        order — scry with a different destination (`_LOOK_TOP_KINDS`).

        Note this is deliberately not `mill`: RULE 701.31b puts these cards
        into the graveyard *from a look*, and the rules keep the two keyword
        actions distinct (nothing that watches milling should see a surveil),
        so no `MILL`/`MILL_CARD` event fires here.
        """
        self._look_at_top(player, count, "surveil", source=source)
    def fateseal(
        self,
        player: Player,
        count: int,
        opponent: Optional[Player] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        """Fateseal ``count`` (RULE 701.29a): ``player`` looks at the top
        ``count`` cards of an **opponent's** library, then puts any number on
        the bottom of that library and the rest back on top in any order —
        scry, pointed at someone else's deck.

        **Documented simplification**: ``opponent`` defaults to the first
        living opponent of ``player`` (auto-picked, not an interactive
        "choose an opponent" — unambiguous in 1v1 goldfish/Replay, the same
        convention `GainControlBySourceEffect`/`RulesEngine.clash` use for
        their own "an opponent"). With no opponent at all, nothing happens
        but the `FATESEALED` event still fires with ``count`` 0.
        """
        if opponent is None:
            opponent = next(
                (p for p in self.state.living_players() if p.id != player.id), None
            )
        self._look_at_top(
            player, count, "fateseal", source=source, library_owner=opponent
        )
    def _look_at_top(
        self,
        player: Player,
        count: int,
        kind: str,
        source: Optional["GameObject"] = None,
        library_owner: Optional[Player] = None,
    ) -> None:
        """The shared body of `scry`/`surveil`/`fateseal`: fire the keyword's
        event, then open its decision.

        The event fires *before* the decision, so "whenever you scry/surveil"
        triggers see it at the moment the player looks — the same point the
        old non-interactive stubs fired it, and the point RULE 603.2 means.
        An empty library is still a scry/surveil/fateseal of 0: the event
        fires (with ``count`` 0) and nothing is asked.

        ``library_owner`` is whose library is looked at and reordered — the
        same as ``player`` for scry/surveil (a player looks at their own
        top), but a *different* player for fateseal (`player` decides,
        ``library_owner`` is the opponent). ``None`` means "same as
        ``player``", so scry/surveil callers are unchanged.
        """
        owner = library_owner if library_owner is not None else player
        looked = owner.library[-count:] if (count > 0 and owner is not None) else []
        event_data: dict[str, Any] = {"player_id": player.id, "count": len(looked)}
        if owner is not None and owner.id != player.id:
            event_data["opponent_id"] = owner.id
        self.state.fire_event(
            GameEvent(self._LOOK_TOP_KINDS[kind]["event"], **event_data)
        )
        if not looked:
            return
        # Top card first, which is the order a player reads them in.
        remaining = [obj.instance_id for obj in reversed(looked)]
        source_name = source.name if source is not None else None
        self.open_choice(self._look_top_choice(
            player, kind, "away", remaining, [], [], source_name,
            library_owner=owner,
        ))
    def explore(self, permanent: GameObject, player: Optional[Player] = None) -> None:
        """RULE 701.44a: ``permanent``'s controller reveals the top card of
        their library. If a land is revealed, it goes to that player's hand;
        otherwise a +1/+1 counter is put on ``permanent`` and the player may
        put the revealed card into their graveyard (an interactive
        ``explore_bin`` choice — the only branch that pauses).

        RULE 701.44b: the `EventType.EXPLORED` event fires once the whole
        process is complete — inline here when nothing was revealed or a land
        went to hand, and from `_resume_explore_bin` otherwise — even
        if some or all of the steps were impossible. RULE 701.44c: last known
        information (``controller_id`` off ``permanent``) identifies the
        explorer if it has already left the battlefield.
        """
        inst = getattr(permanent, "instance_id", None)
        controller_id = getattr(permanent, "controller_id", None)
        if player is None and controller_id is not None:
            try:
                player = self.state.player_by_id(controller_id)
            except KeyError:
                player = None
        if player is None:
            return

        top = player.library[-1] if player.library else None
        if top is None:
            self._fire_explored(inst, controller_id, found_land=False)
            return
        # RULE 701.20a: revealing is a public move; no hidden-zone bookkeeping
        # is needed here since the card immediately changes zone either way.
        if top.card.is_land:
            player.library.pop()
            player.add_to_zone(top, Zone.HAND)
            self._fire_explored(inst, controller_id, found_land=True)
            return

        if inst is not None:
            self.add_counters(permanent, 1, "+1/+1", source=permanent)
        # RULE 701.44a's "may put the revealed card into their graveyard" —
        # a genuine yes/no; declining leaves it on top of the library.
        self.open_choice({
            "kind": "explore_bin",
            "player_id": player.id,
            "optional": True,
            "description": f"Erkunden: {top.card.name}",
            "prompt": f"Erkunden — „{top.card.name}“ auf den Friedhof legen?",
            "card_id": top.instance_id,
            "explorer_id": inst,
            "explorer_controller_id": controller_id,
            "options": [
                {"id": "graveyard", "label": "Auf den Friedhof",
                 "instance_id": top.instance_id},
                {"id": "top", "label": "Oben lassen (Bibliothek)"},
            ],
        })
    def _fire_explored(
        self, inst: Optional[str], controller_id: Optional[str], *, found_land: bool
    ) -> None:
        self.state.fire_event(GameEvent(
            EventType.EXPLORED, instance_id=inst,
            controller_id=controller_id, found_land=found_land,
        ))
    @continuations.choice(
        "explore_bin",
        answer=continuations.ANSWER_FLAG,
        yes="graveyard",
        rule="701.44",
    )
    def _resume_explore_bin(self, choice: dict[str, Any], to_graveyard: bool = False) -> None:
        """Finish an explore (RULE 701.44a): ``to_graveyard`` puts the
        revealed nonland card into its owner's graveyard; otherwise it stays
        on top of the library. Fires `EventType.EXPLORED` afterward (701.44b).
        """
        player = self.state.player_by_id(choice["player_id"])

        if to_graveyard:
            card_id = choice["card_id"]
            revealed = next(
                (o for o in player.library if o.instance_id == card_id), None
            )
            if revealed is not None:
                # A library → graveyard move from a look (like surveil,
                # `_look_at_top`/`_dig_until`); no leave-the-battlefield
                # triggers, so the zone fields are set directly rather than
                # through `_move_to_graveyard`.
                player.library.remove(revealed)
                revealed.zone = Zone.GRAVEYARD
                player.graveyard.append(revealed)
        self._fire_explored(
            choice.get("explorer_id"), choice.get("explorer_controller_id"),
            found_land=False,
        )
    def peek_top_land_battlefield_tapped(
        self, player: Player, source: Optional[GameObject] = None,
        otherwise_hand: bool = False,
        reveal_then: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """"Look at the top card of your library. If it's a land card, you
        may put it onto the battlefield tapped." (Explorer's Scope) — RULE
        701.20's "look" (this player only; unlike `explore`'s *reveal*,
        nothing here is shown to anyone else).

        Bug report, 2026-09-04, two issues: the old implementation put a
        found land onto the battlefield *unconditionally* — no "may" at
        all, so `_resume_peek_top_land` below is what actually makes
        this interactive now — and, since it never opened any choice, a
        *non*-land top card produced no visible feedback whatsoever (the
        player "looked" at nothing they could ever see). Both branches now
        open a `peek_top_land` `pending_choice` naming the card, whether or
        not there's an actual decision to make.
        """
        if not player.library:
            return
        top = player.library[-1]
        source_name = source.name if source is not None else None
        prefix = f"{source_name}: " if source_name else ""
        if reveal_then is not None:
            # "Look at the top card of your library. You may reveal it if it's a land card. <effects> if you
            # revealed it this way." (Fisher's Talent) — a land is offered to be revealed (and the effects then
            # run); anything else is only shown to its owner.
            if top.card.is_land:
                options = [
                    {"id": "reveal", "label": "Aufdecken", "instance_id": top.instance_id},
                    {"id": "decline", "label": "Nicht aufdecken"},
                ]
                prompt = f'{prefix}„{top.card.name}“ aufdecken?'
            else:
                options = [{"id": "ok", "label": "OK", "instance_id": top.instance_id}]
                prompt = f'{prefix}Oberste Karte: „{top.card.name}“ (kein Land).'
            self.open_choice({
                "kind": "peek_top_land", "player_id": player.id, "prompt": prompt,
                "source_name": source_name, "card_id": top.instance_id, "options": options,
                "source_id": getattr(source, "instance_id", None),
                "then_specs": [dict(spec) for spec in reveal_then],
            })
            return
        if top.card.is_land:
            options = [
                {"id": "put", "label": "Getappt ins Spiel legen", "instance_id": top.instance_id},
                ({"id": "hand", "label": "Auf die Hand nehmen"}
                 if otherwise_hand else {"id": "decline", "label": "Oben liegen lassen"}),
            ]
            prompt = f'{prefix}„{top.card.name}“ getappt ins Spiel legen?'
        else:
            # No real decision — a single acknowledgement button just so
            # the peeked card is actually shown (see docstring above).
            options = ([{"id": "hand", "label": "Auf die Hand nehmen", "instance_id": top.instance_id}]
                       if otherwise_hand else [{"id": "ok", "label": "OK", "instance_id": top.instance_id}])
            prompt = (f'{prefix}„{top.card.name}“ auf die Hand nehmen?'
                      if otherwise_hand else f'{prefix}Oberste Karte: „{top.card.name}“ (kein Land).')
        self.open_choice({
            "kind": "peek_top_land",
            "player_id": player.id,
            "prompt": prompt,
            "source_name": source_name,
            "card_id": top.instance_id,
            "options": options,
        })
    @continuations.choice("peek_top_land", answer=continuations.ANSWER_STR, rule="601.2b")
    def _resume_peek_top_land(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `peek_top_land` choice (Explorer's Scope):
        ``"put"`` removes the peeked land from the library and puts it onto
        the battlefield tapped (`_put_searched_card`, the same mover a real
        search uses — see that method's own docstring for why the removal
        has to happen here, before it's called); any other answer
        (``"decline"``, the non-land ``"ok"``, or a decline) leaves the
        library untouched.
        """
        player = self.state.player_by_id(choice["player_id"])
        top = next((o for o in player.library if o.instance_id == choice["card_id"]), None)
        if top is None:
            return
        if answer == "put":
            player.remove_from_zone(top, top.zone)
            self._put_searched_card(player, top, "battlefield_tapped")
        elif answer == "hand":
            player.remove_from_zone(top, top.zone)
            player.add_to_zone(top, Zone.HAND)
        elif answer == "reveal":
            # RULE 701.20: revealing shows the card to everyone (the card stays on top of the library), then
            # the effects that depend on having revealed it run.
            self.state.fire_event(GameEvent(
                EventType.REVEAL, player_id=player.id, object=top.name, instance_id=top.instance_id,
                from_zone=Zone.LIBRARY.value,
            ))
            self._apply_effect_specs(
                list(choice.get("then_specs") or []), self._object_by_instance_id(choice.get("source_id")),
            )
    def _look_top_choice(
        self,
        player: Player,
        kind: str,
        phase: str,
        remaining: list[int],
        away: list[int],
        top: list[int],
        source_name: Optional[str] = None,
        library_owner: Optional[Player] = None,
        may_shuffle: bool = False,
    ) -> dict[str, Any]:
        """Build one step of the serializable `scry`/`surveil` decision.

        ``remaining`` are the looked-at cards still undecided (top of library
        first), ``away`` the ones already sent to the bottom/graveyard and
        ``top`` the ones already placed, topmost first. All three are instance
        ids rather than objects, so the choice survives the state `clone()`
        undo takes. ``source_name`` is the causing permanent/spell's name, if
        known, carried along so the frontend can show where the scry/surveil
        came from — the same purpose `_trigger_order_choice`'s own
        ``source_name`` serves.
        """
        prompt, decline_label = self._LOOK_TOP_KINDS[kind][phase]
        looked = [(iid, self._object_by_instance_id(iid)) for iid in remaining]
        options: list[dict[str, Any]] = [
            {"id": str(iid), "label": obj.name, "instance_id": iid, "card_id": obj.card.id}
            for iid, obj in looked
            if obj is not None
        ]
        options.append({"id": "decline", "label": decline_label})
        choice: dict[str, Any] = {
            "kind": kind,
            "player_id": player.id,
            "phase": phase,
            "remaining": list(remaining),
            "away": list(away),
            "top": list(top),
            "prompt": prompt,
            "options": options,
            "source_name": source_name,
        }
        # Only set for fateseal (RULE 701.29a) — scry/surveil look at the
        # *chooser's* own library, so its absence means "same as player_id"
        # and every existing caller/serialized choice is unchanged.
        if library_owner is not None and library_owner.id != player.id:
            choice["library_owner_id"] = library_owner.id
        # `reorder_top` only: "…put them back in any order. You may shuffle." — offered once the order is set.
        if may_shuffle:
            choice["may_shuffle"] = True
        return choice
    @continuations.choice(
        "scry", "surveil", "scroll_rack", "fateseal", "reorder_top", "hand_bottom",
        answer=continuations.ANSWER_INT,
        rule="701.22",
    )
    def _resume_look_top(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer one step of a look-at-the-top-N decision.

        One handler for all three kinds in `_LOOK_TOP_KINDS`: scry (RULE
        701.22), surveil (RULE 701.25) and Scroll Rack's ordering-only
        sibling (MEC-43 round 4F). They were three one-line wrappers around
        this body, differing only in the ``kind`` they passed — which is
        already on the choice, so registering the one handler for three
        kinds is the whole collapse.

        **This is also where Scroll Rack became answerable.** Its kind was
        never wired into the old ``if kind == …`` cascade, so a live game's
        answer fell through to the *search* resolver and raised; only a test
        calling the private wrapper directly hid it. A registry cannot have
        that bug shape — `tests/test_continuations.py` asserts totality.

        In the ``away`` phase a card id sends that card to the bottom (scry)
        or the graveyard (surveil) and re-asks; declining ends that phase and
        moves on to ordering whatever is left. In the ``order`` phase a card
        id places that card next from the top; declining there keeps the rest
        in the order they already were and finishes. Either phase also
        finishes on its own as soon as there is nothing left to decide.
        """
        kind = choice["kind"]
        player = self.state.player_by_id(choice["player_id"])
        # Fateseal (RULE 701.29a) reorders the *opponent's* library while
        # ``player`` stays the decision-maker; absent for scry/surveil, where
        # the two are the same person.
        owner_id = choice.get("library_owner_id", choice["player_id"])
        owner = self.state.player_by_id(owner_id)
        remaining: list[int] = list(choice["remaining"])
        away: list[int] = list(choice["away"])
        top: list[int] = list(choice["top"])
        phase = choice["phase"]
        source_name = choice.get("source_name")

        may_shuffle = bool(choice.get("may_shuffle"))
        if instance_id is None:
            if phase == "order":
                self._finish_look_top(owner, kind, away, top + remaining)
                self._offer_shuffle_after_look(player, owner, may_shuffle)
                return
            phase = "order"  # declined: what's left stays on top
        elif instance_id in remaining:
            remaining.remove(instance_id)
            (away if phase == "away" else top).append(instance_id)
        else:
            raise ValueError(f"{instance_id} is not a legal choice")

        # One card left needs no ordering, and no cards left needs nothing at
        # all — either way the decision is over.
        if not remaining or (phase == "order" and len(remaining) == 1):
            self._finish_look_top(owner, kind, away, top + remaining)
            self._offer_shuffle_after_look(player, owner, may_shuffle)
            return
        self.open_choice(self._look_top_choice(
            player, kind, phase, remaining, away, top, source_name,
            library_owner=owner, may_shuffle=may_shuffle,
        ))
    def _finish_look_top(
        self, player: Player, kind: str, away: list[int], top: list[int]
    ) -> None:
        """Put the looked-at cards where they were sent. ``player`` is the
        owner of the library being reordered — the same person who scried
        for scry/surveil, but the *opponent* for fateseal (RULE 701.29a),
        since `_resume_look_top` resolves it from ``library_owner_id``.

        ``top`` goes back on top with its first entry topmost (`Player.
        library` is ordered bottom-first, so the kept pile goes back
        reversed); ``away`` goes under the library (scry) or into the
        graveyard (surveil, RULE 701.31b). MEC-43 round 4F: Scroll Rack's
        own ``"scroll_rack"`` kind starts from *exile*, not the library
        (its cards left the library step earlier, when the ability's own
        first half exiled them) — ``away`` is always empty for it, and
        every ``top`` entry gets a real zone change plus its face-down
        flag cleared, on top of the ordinary reordering every other kind
        already does in place.
        """
        self.state.pending_choice = None
        if kind == "hand_bottom":
            # `top` is topmost first, matching every other ordering choice.
            # A commander redirect can pause each move, so park remaining
            # moves before the outer draw rather than overwriting a choice.
            from ..effects.core import ReturnToLibraryEffect

            effects = []
            for iid in top:
                obj = self._object_by_instance_id(iid)
                if obj is not None and obj in player.hand:
                    effects.append(ReturnToLibraryEffect(
                        target=obj, target_kind=None, position="bottom",
                    ))
            _apply_effects_partitioned(effects, self.context, None, None)
            return
        objects = {iid: self._object_by_instance_id(iid) for iid in (*away, *top)}
        source_zone = player.exile if kind == "scroll_rack" else player.library
        for obj in objects.values():
            if obj is not None and obj in source_zone:
                source_zone.remove(obj)
        for iid in away:
            obj = objects.get(iid)
            if obj is None:
                continue
            if kind == "surveil":
                obj.zone = Zone.GRAVEYARD
                player.graveyard.append(obj)
                self._flag_commander_zone_choice(obj)  # RULE 903.9a
            else:
                player.library.insert(0, obj)  # bottom of library
        for iid in reversed(top):
            obj = objects.get(iid)
            if obj is not None:
                if kind == "scroll_rack":
                    obj.zone = Zone.LIBRARY
                    obj.face_down_in_exile = False
                player.library.append(obj)

    def _offer_shuffle_after_look(self, player: Player, owner: Player, may_shuffle: bool) -> None:
        """"You may shuffle" / "you may have that player shuffle" (Omen, Natural Selection, Portent): a yes/no
        once the looked-at cards are back in order. Only the decider is asked (``player``); ``owner`` is whose
        library shuffles."""
        if not may_shuffle or len(owner.library) < 2:
            return
        self.open_choice({
            "kind": "shuffle_offer",
            "player_id": player.id,
            "library_owner_id": owner.id,
            "prompt": "Bibliothek mischen?" if owner.id == player.id else f"Bibliothek von {owner.name} mischen?",
            "options": [{"id": "do", "label": "Mischen"}, {"id": "decline", "label": "Nicht mischen"}],
        })

    @continuations.choice("shuffle_offer", answer=continuations.ANSWER_STR, rule="701.24")
    def _resume_shuffle_offer(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        if answer == "do":
            self.shuffle_library(self.state.player_by_id(choice["library_owner_id"]))

    def look_reorder_top(
        self,
        player: Player,
        count: int,
        library_owner: Optional[Player] = None,
        source: Optional["GameObject"] = None,
        may_shuffle: bool = False,
    ) -> None:
        """"Look at the top ``count`` cards of a library, then put them back in any order" —
        ``player`` decides, ``library_owner`` (default: ``player``) is whose library it is.
        Unlike scry nothing may leave the top, so only the ordering decision opens (and not at
        all for a single card, which has one order)."""
        owner = library_owner if library_owner is not None else player
        looked = owner.library[-count:] if count > 0 else []
        if len(looked) < 2:
            self._offer_shuffle_after_look(player, owner, may_shuffle)
            return
        remaining = [obj.instance_id for obj in reversed(looked)]  # top card first
        self.open_choice(self._look_top_choice(
            player, "reorder_top", "order", remaining, [], [],
            source.name if source is not None else None, library_owner=owner, may_shuffle=may_shuffle,
        ))
    def open_hand_bottom_order_choice(
        self, player: Player, source: Optional["GameObject"] = None,
    ) -> None:
        remaining = [obj.instance_id for obj in player.hand]
        if len(remaining) < 2:
            self._finish_look_top(player, "hand_bottom", [], remaining)
            return
        self.open_choice(self._look_top_choice(
            player, "hand_bottom", "order", remaining, [], [],
            source.name if source is not None else None,
        ))

    def open_scroll_rack_order_choice(
        self, player: Player, instance_ids: list[int], source: Optional["GameObject"] = None,
    ) -> None:
        """RULE 701.20a-adjacent (MEC-43 round 4F — Scroll Rack): "look at
        the exiled cards and put them on top of your library in any
        order." ``instance_ids`` are the cards this ability's own first
        half (`ScrollRackFinishEffect`) already exiled face down — this
        just opens the ordering decision for them, reusing scry/surveil's
        own ``"order"`` phase (`_LOOK_TOP_KINDS`/`_look_top_choice`/
        `_resolve_look_top_choice`) rather than a bespoke chooser, since
        "N known objects, pick their final order" is exactly that shape;
        `_finish_look_top`'s ``kind == "scroll_rack"`` branch is what makes
        the destination a zone change out of exile instead of an in-place
        library reorder. No "away" phase exists for this kind at all — Scroll
        Rack never sends a card anywhere but back to the library.
        """
        if not instance_ids:
            return
        if len(instance_ids) == 1:
            # One card has only one order — finish immediately, matching
            # `_resolve_look_top_choice`'s own "1 card left" shortcut.
            self._finish_look_top(player, "scroll_rack", [], list(instance_ids))
            return
        source_name = source.name if source is not None else None
        self.open_choice(self._look_top_choice(
            player, "scroll_rack", "order", list(instance_ids), [], [], source_name
        ))

    def look_top_select(
        self,
        player: Player,
        count: int,
        select_count: int,
        rest_destination: str,
        rest_order: Optional[str] = None,
        select_optional: bool = False,
        select_filter: Optional[dict[str, Any]] = None,
    ) -> None:
        """"Look at the top N cards of your library. Put M of them into
        your hand and the rest `<destination>`." (Anticipate/Dig Through
        Time/Diabolic Vision/Ancestral Memories-shaped) — the fixed-count
        sibling of `scry`/`surveil`'s per-card away/stay decision
        (`_LOOK_TOP_KINDS`): there the count going *away* is the player's
        own choice made one card at a time, here the count going to *hand*
        is fixed by the card text, so the shape is instead "pick exactly M
        of these for your hand", then — only when the card says "in any
        order" — order what's left before it goes to
        ``rest_destination`` (``"library_bottom"``/``"library_top"``/
        ``"graveyard"``). A ``"random"`` ``rest_order`` shuffles with no
        choice at all, and ``"graveyard"`` is never ordered either way
        (RULE 701.31b's own precedent — a surveil/mill pile is never
        ordered, which is also why none of these cards ever pair
        "graveyard" with "in any order").

        ``select_filter`` (Water Tribe Rallier — "you may reveal **a
        creature card with power 3 or less** from among them") restricts
        which of the looked-at cards may be picked for hand
        (`combat.matches_object_filter`); ``select_optional`` makes the
        pick a "you **may**" (0 up to ``select_count``, with a decline
        option) rather than mandatory. A revealed pick is public info at a
        real table; this engine has no reveal step, so the card simply goes
        to hand.
        """
        looked = player.library[-count:] if count > 0 else []
        if not looked:
            return
        remaining = [obj.instance_id for obj in reversed(looked)]  # top of library first
        eligible = self._look_top_select_eligible(remaining, select_filter)
        select_count = max(0, min(select_count, len(eligible)))
        if select_count <= 0:
            self._advance_look_top_select(player, remaining, [], rest_destination, rest_order)
            return
        self.open_choice(self._look_top_select_choice(
            player, "select", remaining, [], select_count, [], rest_destination, rest_order,
            select_optional=select_optional, select_filter=select_filter,
        ))

    def _look_top_select_eligible(
        self, instance_ids: list[int], select_filter: Optional[dict[str, Any]]
    ) -> list[int]:
        """The subset of ``instance_ids`` a `look_top_select` pick may take
        (`select_filter`, or all of them when there is none)."""
        if not select_filter:
            return list(instance_ids)
        from .. import combat  # function-scoped: avoid a load-time cycle

        out = []
        for iid in instance_ids:
            obj = self._object_by_instance_id(iid)
            if obj is not None and combat.matches_object_filter(obj, dict(select_filter)):
                out.append(iid)
        return out

    def _look_top_select_choice(
        self,
        player: Player,
        phase: str,
        remaining: list[int],
        selected: list[int],
        select_count: int,
        ordered: list[int],
        rest_destination: str,
        rest_order: Optional[str],
        select_optional: bool = False,
        select_filter: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Build one step of the serializable `look_top_select` decision —
        ``phase`` is ``"select"`` (choosing the hand cards — mandatory per
        RULE 701.19's "put M of them", unless ``select_optional``, a "you
        may reveal…" — and narrowed to ``select_filter`` when set) or
        ``"order"`` (placing what's left one at a time, decline keeps the
        rest in their looked-at order, same convention as `_look_top_choice`)."""
        looked = [(iid, self._object_by_instance_id(iid)) for iid in remaining]
        if phase == "order":
            options = [
                {"id": str(iid), "label": obj.name, "instance_id": iid}
                for iid, obj in looked if obj is not None
            ]
            options.append({"id": "decline", "label": "Reihenfolge behalten"})
            prompt = (
                "Wähle die Karte, die zuoberst auf die Bibliothek kommt"
                if rest_destination == "library_top_bottom" and not ordered
                else "Wähle die nächste Karte für die Bibliothek"
            )
        else:
            eligible = set(self._look_top_select_eligible(remaining, select_filter))
            options = [
                {"id": str(iid), "label": obj.name, "instance_id": iid}
                for iid, obj in looked if obj is not None and iid in eligible
            ]
            if select_optional:
                options.append({"id": "decline", "label": "Keine offenbaren"})
            prompt = f"Wähle eine Karte für deine Hand ({select_count - len(selected)} übrig)"
        return {
            "kind": "look_top_select",
            "player_id": player.id,
            "phase": phase,
            "remaining": list(remaining),
            "selected": list(selected),
            "select_count": select_count,
            "ordered": list(ordered),
            "rest_destination": rest_destination,
            "rest_order": rest_order,
            "select_optional": select_optional,
            "select_filter": dict(select_filter) if select_filter else None,
            "prompt": prompt,
            "options": options,
        }

    @continuations.choice("look_top_select", answer=continuations.ANSWER_INT, rule="701.20")
    def _resume_look_top_select(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer one step of a `look_top_select` decision — see
        `_look_top_select_choice` for the two phases."""
        player = self.state.player_by_id(choice["player_id"])
        remaining: list[int] = list(choice["remaining"])
        selected: list[int] = list(choice["selected"])
        select_count: int = choice["select_count"]
        ordered: list[int] = list(choice["ordered"])
        rest_destination: str = choice["rest_destination"]
        rest_order: Optional[str] = choice["rest_order"]
        select_optional: bool = bool(choice.get("select_optional", False))
        select_filter: Optional[dict[str, Any]] = choice.get("select_filter")
        phase = choice["phase"]

        if phase == "select":
            eligible = set(self._look_top_select_eligible(remaining, select_filter))
            if instance_id is None:
                # RULE 601.2 "you may reveal…" declined — take whatever was
                # already picked and place the rest. A mandatory pick has no
                # decline (the caller only offers one when select_optional).
                if not select_optional:
                    raise ValueError("a look_top_select pick is not optional")
                self._advance_look_top_select(
                    player, remaining, selected, rest_destination, rest_order
                )
                return
            if instance_id not in remaining or instance_id not in eligible:
                raise ValueError(f"{instance_id} is not a legal choice")
            remaining.remove(instance_id)
            selected.append(instance_id)
            still_eligible = [i for i in remaining if i in eligible]
            if len(selected) < select_count and still_eligible:
                self.open_choice(self._look_top_select_choice(
                    player, "select", remaining, selected, select_count, ordered,
                    rest_destination, rest_order,
                    select_optional=select_optional, select_filter=select_filter,
                ))
                return
            self._advance_look_top_select(player, remaining, selected, rest_destination, rest_order)
            return

        # phase == "order"
        if instance_id is None:
            self._finish_look_top_select(player, selected, ordered + remaining, rest_destination)
            return
        if instance_id not in remaining:
            raise ValueError(f"{instance_id} is not a legal choice")
        remaining.remove(instance_id)
        ordered.append(instance_id)
        if not remaining:
            self._finish_look_top_select(player, selected, ordered, rest_destination)
            return
        self.open_choice(self._look_top_select_choice(
            player, "order", remaining, selected, select_count, ordered,
            rest_destination, rest_order,
        ))

    def _advance_look_top_select(
        self,
        player: Player,
        remaining: list[int],
        selected: list[int],
        rest_destination: str,
        rest_order: Optional[str],
    ) -> None:
        """Selection done — order the rest (only when the card said "in any
        order" and 2+ remain), shuffle it (``"random"``), or just place it."""
        if rest_order == "any" and len(remaining) >= 2:
            self.open_choice(self._look_top_select_choice(
                player, "order", remaining, selected, len(selected), [],
                rest_destination, rest_order,
            ))
            return
        if rest_order == "random":
            import random

            random.shuffle(remaining)
        self._finish_look_top_select(player, selected, remaining, rest_destination)

    def _finish_look_top_select(
        self, player: Player, selected: list[int], rest: list[int], rest_destination: str,
    ) -> None:
        """Put the selected cards in hand and the rest at
        ``rest_destination`` — the bottom/top-of-library conventions match
        `_finish_look_top` exactly (bottom: `insert(0, …)` per card; top:
        appended in reverse so the list's first entry ends up topmost)."""
        self.state.pending_choice = None
        objects = {iid: self._object_by_instance_id(iid) for iid in (*selected, *rest)}
        for obj in objects.values():
            if obj is not None and obj in player.library:
                player.library.remove(obj)
        for iid in selected:
            obj = objects.get(iid)
            if obj is None:
                continue
            obj.zone = Zone.HAND
            player.hand.append(obj)
        if rest_destination == "graveyard":
            for iid in rest:
                obj = objects.get(iid)
                if obj is None:
                    continue
                obj.zone = Zone.GRAVEYARD
                player.graveyard.append(obj)
                self._flag_commander_zone_choice(obj)  # RULE 903.9a
        elif rest_destination == "library_top":
            for iid in reversed(rest):
                obj = objects.get(iid)
                if obj is not None:
                    player.library.append(obj)
        elif rest_destination == "library_top_bottom":
            # "…one on top of your library, and one on the bottom" (Telling Time): the first card of the (chosen)
            # order goes on top, every other one to the bottom.
            for position, iid in enumerate(rest):
                obj = objects.get(iid)
                if obj is None:
                    continue
                if position == 0:
                    player.library.append(obj)
                else:
                    player.library.insert(0, obj)
        else:  # "library_bottom"
            for iid in rest:
                obj = objects.get(iid)
                if obj is not None:
                    player.library.insert(0, obj)

    def _has_search_exemption(self, player: Player) -> bool:
        """RULE 116.2a (MEC-35, Leonin Arbiter): has ``player`` paid {2}
        this turn to ignore a search prohibition? See `GameState.
        search_exempt_until_turn`'s own docstring."""
        return self.state.search_exempt_until_turn.get(player.id) == self.state.internal_turn.number

    def is_search_prohibited_for(self, player: Player) -> bool:
        """Whether ``player`` is currently barred from searching at all
        (RULE 701.19a — Stranglehold's ``scope="opponents"``/Leonin
        Arbiter's ``scope="all"``), accounting for this turn's RULE 116.2a
        exemption if any. The same check `_request_search`'s own guard
        makes, factored out so `GameEngine.pay_search_exemption_actions`
        can decide whether the special action is even worth offering.
        """
        if self._has_search_exemption(player):
            return False
        return any(
            isinstance(e, GrantSearchProhibitedEffect)
            and (e.scope == "all" or permanent.controller_id != player.id)
            for permanent in self.state.battlefield
            for e in getattr(permanent, "static_effects", None) or []
        )

    def _request_search(
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
        attach_to_creature_you_control: bool = False,
        remember_source_id: Optional[int] = None,
        total_mana_value_budget: Optional[int] = None,
        chooser: Optional[Player] = None,
        share_land_type: bool = False,
        then_specs_if_none: Optional[list[dict]] = None,
        source: Optional[GameObject] = None,
        track_exiled_with: bool = False,
        untap_if_lands_at_least: Optional[int] = None,
        then_specs: Optional[list[dict]] = None,
        reveal: bool = False,
    ) -> None:
        """Open a "search your library" choice on the game state (a tutor).

        ``criteria`` says *what* to look for (see `models.cards.card_query`: ``""``
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

        ``chooser`` (Praetor's Grasp-shaped RULE 701.19a "search **target
        opponent's** library" — MEC-42) lets the picking player differ from
        ``player``, whose library is actually searched/shuffled and who
        stays the found card's owner throughout; defaults to ``player``
        (every other caller's existing behaviour, unchanged). Stored as the
        pending choice's own ``player_id`` (the general "who answers"
        convention `_intuition_choose_choice` already established), with
        ``player``'s id kept alongside as ``library_owner_id``.

        ``attach_to_creature_you_control=True`` (Stonehewer Giant/Quest for
        the Holy Relic's own "…put it onto the battlefield, **attach it to a
        creature you control**") attaches the found card, once it reaches
        the battlefield, to one of the searching player's own creatures —
        auto-picked (the first eligible one found), the same "no chooser for
        an equally-valid pick" idiom `put_hand_cards_on_top` already uses,
        since real Equipment attachment has no RULE 115 target of its own
        here (the printed line never says "target creature"). Silently
        stays unattached if the player controls no creature at all — RULE
        301.5c: an unattached Equipment is always legal to *have*, just
        does nothing. Ignored for any non-battlefield destination.

        ``total_mana_value_budget`` (Protean Hulk's own "search your
        library for **any number** of creature cards with **total** mana
        value 6 or less" — MEC-12) is a running budget shared across the
        *whole* multi-pick search, unlike ``criteria``'s own
        ``max_mana_value`` (a fixed per-card cap checked in isolation):
        each round's eligible pool additionally excludes any card whose own
        mana value would push the sum of everything picked so far over this
        total. Pair with a generously large ``count`` (the established
        ``99`` sentinel other "any number of" searches already use) so the
        budget, not the count, is what actually ends the search.

        ``share_land_type`` ("...basic land cards **that share a land
        type**." — Myriad Landscape, MEC-43 round 3) is a cross-pick
        constraint rather than a per-card one: the *first* pick is
        unconstrained, but every pick after that must share a basic land
        type (RULE 305.6) with at least one card already found this same
        search (`_shares_land_type`) — unlike ``criteria``, which is
        checked against each candidate in isolation and can't express "in
        relation to what was already picked."

        Records the eligible cards (across ``zones``) as a `state.
        pending_choice` — the engine's resolve loop stops on it and the
        session surfaces it, and `_resume_search` finishes the search
        once the player picks (or declines). An ordinary search (RULE
        701.19) always shuffles the library afterwards (RULE 701.19e) as
        long as ``"library"`` is among ``zones``; with nothing eligible it
        just shuffles (if applicable), no choice needed.
        """
        # RULE 701.19a: "Your opponents can't search libraries."
        # (Stranglehold-shaped) / "Players can't search libraries." (MEC-35,
        # Leonin Arbiter's own unscoped variant, `scope="all"`) — an effect
        # instructing a prohibited player to search simply doesn't; skipped
        # here rather than at every call site, the same "one choke point"
        # idiom `deal_damage`/`gain_life` use for their own replacement
        # checks. A player who's paid this turn's RULE 116.2a exemption
        # (`GameEngine.pay_search_exemption`) ignores every such effect,
        # not just one — the printed clause says "ignore **this** effect",
        # but no shipped card yet combines Leonin Arbiter with a second,
        # independent search-prohibition source, so the simpler "ignore
        # them all" reading costs nothing today.
        if self.is_search_prohibited_for(player):
            return
        zones = list(zones) if zones else ["library"]
        if "library" in zones:
            self.state.fire_event(
                GameEvent(EventType.LIBRARY_SEARCHED, player_id=player.id)
            )
        eligible = [
            obj
            for obj in self._search_zone_objects(player, zones)
            if card_query.matches(obj.card, criteria)
            and (
                total_mana_value_budget is None
                or obj.mana_value <= total_mana_value_budget
            )
        ]
        if not eligible or count <= 0:
            if "library" in zones and not exile_rest:
                self.shuffle_library(player)
            # "…if you don't put a card … this way, <body>." (The Vast
            # Scrier) — nothing eligible counts as "didn't".
            self._apply_effect_specs(list(then_specs_if_none or []), source)
            return
        self.open_choice(self._search_choice(
            player, criteria, destination, count, optional, found=[],
            zones=zones, destinations=destinations, exile_rest=exile_rest,
            extra_counters=extra_counters, destination_if=destination_if,
            attach_to_creature_you_control=attach_to_creature_you_control,
            remember_source_id=remember_source_id,
            total_mana_value_budget=total_mana_value_budget,
            chooser=chooser,
            share_land_type=share_land_type,
            untap_if_lands_at_least=untap_if_lands_at_least,
            then_specs_if_none=then_specs_if_none,
            then_specs=then_specs,
            then_source_id=getattr(source, "instance_id", None),
            track_exiled_with=track_exiled_with,
            reveal=reveal,
        ))

    def _request_intuition(
        self, searcher: Player, chooser_id: str, count: int, source: Optional[GameObject] = None,
        search_optional: bool = False, distinct_names: bool = False,
        chosen_count: int = 1, chosen_destination: str = "hand",
        rest_destination: str = "graveyard",
    ) -> None:
        """"Search your library for three cards and reveal them. Target
        opponent chooses one. Put that card into your hand and the rest
        into your graveyard. Then shuffle." (Intuition) — self-contained
        (two chained `pending_choice`s: ``searcher`` picks ``count`` cards
        first, then ``chooser_id`` — a real RULE 115 target, not the
        searcher — picks from among them) rather than composed from
        `_request_search`, whose single ``destination`` has no way to
        express "hold these aside for a *second* player's pick".

        Generalized (MEC-41, Gifts Ungiven) past Intuition's own fixed
        shape: ``search_optional`` is RULE 701.19's "up to `<count>`"
        (a decline option stops the search early); ``distinct_names``
        excludes from each round's options any card sharing a name with
        one already found ("with different names"); ``chosen_count``/
        ``chosen_destination``/``rest_destination`` let the *chooser's*
        own pick move more than one card, and to swap which pile is which
        — Gifts Ungiven's opponent choice sends the *chosen* pair to the
        graveyard and the *rest* to the searcher's hand, the mirror image
        of Intuition's own "chosen → hand, rest → graveyard".
        """
        if not searcher.library or count <= 0:
            self.shuffle_library(searcher)
            return
        self.open_choice(self._intuition_search_choice(
            searcher, chooser_id, count, [], source, search_optional, distinct_names,
            chosen_count, chosen_destination, rest_destination,
        ))

    def _intuition_search_choice(
        self, searcher: Player, chooser_id: str, count: int, found: list[int],
        source: Optional[GameObject], search_optional: bool, distinct_names: bool,
        chosen_count: int, chosen_destination: str, rest_destination: str,
    ) -> dict[str, Any]:
        found_names = {
            self._object_by_instance_id(iid).name
            for iid in found if self._object_by_instance_id(iid) is not None
        }
        options = [
            {"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id}
            for obj in searcher.library
            if obj.instance_id not in found
            and not (distinct_names and obj.name in found_names)
        ]
        if search_optional:
            options.append({"id": "decline", "label": "Aufhören"})
        return {
            "kind": "intuition_search",
            "player_id": searcher.id,
            "chooser_id": chooser_id,
            "count": count,
            "found": list(found),
            "source_id": source.instance_id if source is not None else None,
            "search_optional": search_optional,
            "distinct_names": distinct_names,
            "chosen_count": chosen_count,
            "chosen_destination": chosen_destination,
            "rest_destination": rest_destination,
            "prompt": f"Intuition: wähle {count - len(found)} Karte(n) aus deiner Bibliothek",
            "options": options,
        }

    @continuations.choice("intuition_search", answer=continuations.ANSWER_INT, rule="701.23")
    def _resume_intuition_search(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer one pick of the search phase — ``None`` (only legal when
        ``search_optional``, RULE 701.19's "up to") stops early; otherwise
        mandatory (Intuition's own plain "search for `<count>` cards")."""
        searcher = self.state.player_by_id(choice["player_id"])
        found = list(choice["found"])
        if instance_id is None:
            if not choice.get("search_optional"):
                raise ValueError("this intuition search isn't optional")
        else:
            eligible_ids = {
                int(e["instance_id"]) for e in choice["options"] if "instance_id" in e
            }
            if instance_id not in eligible_ids:
                raise ValueError(f"{instance_id} is not a valid search target")
            found = found + [instance_id]
            if len(found) < choice["count"] and len(found) < len(searcher.library):
                self.open_choice(self._intuition_search_choice(
                    searcher, choice["chooser_id"], choice["count"], found,
                    self._object_by_instance_id(choice["source_id"]),
                    choice.get("search_optional", False), choice.get("distinct_names", False),
                    choice["chosen_count"], choice["chosen_destination"], choice["rest_destination"],
                ))
                return
        chooser = self.state.player_by_id(choice["chooser_id"])
        self.open_choice(self._intuition_choose_choice(
            searcher, chooser, found, [], choice["chosen_count"],
            choice["chosen_destination"], choice["rest_destination"],
        ))

    def _intuition_choose_choice(
        self, searcher: Player, chooser: Player, found: list[int], picked: list[int],
        chosen_count: int, chosen_destination: str, rest_destination: str,
    ) -> dict[str, Any]:
        options = [
            {"id": str(iid), "label": self._object_by_instance_id(iid).name, "instance_id": iid}
            for iid in found
            if iid not in picked and self._object_by_instance_id(iid) is not None
        ]
        return {
            "kind": "intuition_choose",
            "player_id": chooser.id,
            "searcher_id": searcher.id,
            "found": list(found),
            "picked": list(picked),
            "chosen_count": chosen_count,
            "chosen_destination": chosen_destination,
            "rest_destination": rest_destination,
            "prompt": f"Intuition: welche Karte(n) kommen in {searcher.name}s "
                      f"{'Hand' if chosen_destination == 'hand' else 'Friedhof'}?",
            "options": options,
        }

    @continuations.choice(
        "intuition_choose",
        answer=continuations.ANSWER_INT_REQUIRED,
        rule="701.23",
    )
    def _resume_intuition_choose(self, choice: dict[str, Any], instance_id: int) -> None:
        """The opponent's mandatory pick (RULE 601.2c — "chooses `<N>`" has
        no decline): re-opens until ``chosen_count`` are picked, the same
        "one at a time" shape `_request_choose_objects` uses. Once done, the
        picked cards go to ``chosen_destination``, the rest to
        ``rest_destination``, then the library is shuffled."""
        found = list(choice["found"])
        if instance_id not in found or instance_id in choice["picked"]:
            raise ValueError(f"{instance_id} is not a legal choice")
        picked = list(choice["picked"]) + [instance_id]
        searcher = self.state.player_by_id(choice["searcher_id"])
        chooser = self.state.player_by_id(choice["player_id"])
        if len(picked) < choice["chosen_count"] and len(picked) < len(found):
            self.open_choice(self._intuition_choose_choice(
                searcher, chooser, found, picked, choice["chosen_count"],
                choice["chosen_destination"], choice["rest_destination"],
            ))
            return
        for iid in found:
            obj = self._object_by_instance_id(iid)
            if obj is None or obj not in searcher.library:
                continue
            searcher.library.remove(obj)
            dest = choice["chosen_destination"] if iid in picked else choice["rest_destination"]
            if dest == "hand":
                obj.zone = Zone.HAND
                searcher.hand.append(obj)
            else:
                obj.zone = Zone.GRAVEYARD
                searcher.graveyard.append(obj)
                self._flag_commander_zone_choice(obj)  # RULE 903.9a
        self.shuffle_library(searcher)

    def _search_zone_objects(self, player: Player, zones: list[str]) -> list[GameObject]:
        """The combined pool of cards a (possibly multi-zone) search draws
        from, library before graveyard when both are searched.

        ``"hand"`` is a *choice* rather than a search in the RULE 701.19
        sense (Tooth and Nail's "put up to two creature cards from your hand
        onto the battlefield") — it reuses this same machinery so the pick
        is offered one card at a time with the same UI/undo shape as every
        other, but `_request_search` never shuffles for it and never fires
        `LIBRARY_SEARCHED`, both of which are keyed to ``"library"``."""
        objs: list[GameObject] = []
        if "library" in zones:
            # RULE 701.19a-adjacent narrowing: "If an opponent would search
            # a library, that player searches the top N cards of that
            # library instead." (Aven Mindcensor) — take the smallest N
            # among every such grant that isn't ``player``'s own, mirroring
            # `GrantSearchProhibitedEffect`'s own scan just above in
            # `_request_search`. `player.library[-n:]` since the list end is
            # the top of the deck (`.pop()`'s own convention).
            limits = [
                e.n
                for permanent in self.state.battlefield
                if permanent.controller_id != player.id
                for e in getattr(permanent, "static_effects", None) or []
                if isinstance(e, GrantSearchLimitedToTopNEffect)
            ]
            if limits:
                n = max(0, min(limits))
                objs.extend(player.library[len(player.library) - n:])
            else:
                objs.extend(player.library)
        if "graveyard" in zones:
            objs.extend(player.graveyard)
        if "hand" in zones:
            objs.extend(player.hand)
        if "exile" in zones:
            # "…choose a face-up artifact card you own in exile." (Karn,
            # the Great Creator's -2) — a *choice* among public information
            # the same "hand" is above, not RULE 701.19's hidden search;
            # face-down exile (morph/Beseech the Mirror-shaped) is excluded
            # since only a face-up card is ever visible to choose among.
            objs.extend(o for o in player.exile if not getattr(o, "face_down_in_exile", False))
        return objs
    @continuations.choice("search", answer=continuations.ANSWER_INT, rule="701.23")
    def _resume_search(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer a pending search: pick a card, re-ask for the next, or finish.

        ``instance_id`` names the chosen card, or is None to decline (which
        ends the search even with picks still available — RULE 701.19c "up
        to"). When ``count`` > 1 and cards remain, this re-opens the choice
        for the next card; otherwise it moves every chosen card to the
        destination and shuffles. Clears the pending choice when done.
        """
        player = self.state.player_by_id(choice.get("library_owner_id", choice["player_id"]))
        chooser_id = choice["player_id"]
        found: list[int] = list(choice["found"])
        zones = choice.get("zones") or ["library"]
        total_mana_value_budget = choice.get("total_mana_value_budget")
        spent_mana_value = choice.get("spent_mana_value", 0)
        share_land_type = choice.get("share_land_type", False)

        declined = instance_id is None
        if not declined:
            eligible_ids = {e["instance_id"] for e in choice["eligible"]}
            if instance_id not in eligible_ids:
                raise ValueError(f"{instance_id} is not a valid search target")
            found.append(instance_id)
            if total_mana_value_budget is not None:
                picked = next(
                    o for o in self._search_zone_objects(player, zones)
                    if o.instance_id == instance_id
                )
                spent_mana_value += picked.mana_value

        remaining = choice["count"] - len(found)
        remaining_budget = (
            None if total_mana_value_budget is None else total_mana_value_budget - spent_mana_value
        )
        found_objs = [
            o for o in (self._object_by_instance_id(iid) for iid in found) if o is not None
        ]
        still_eligible = [
            obj
            for obj in self._search_zone_objects(player, zones)
            if obj.instance_id not in found
            and card_query.matches(obj.card, choice["criteria"])
            and (remaining_budget is None or obj.mana_value <= remaining_budget)
            and _shares_land_type(obj, found_objs, share_land_type)
        ]
        if not declined and remaining > 0 and still_eligible:
            self.open_choice(self._search_choice(
                player, choice["criteria"], choice["destination"],
                choice["count"], choice["optional"], found=found,
                zones=zones, destinations=choice.get("destinations"),
                exile_rest=choice.get("exile_rest", False),
                extra_counters=choice.get("extra_counters"),
                destination_if=choice.get("destination_if"),
                attach_to_creature_you_control=choice.get("attach_to_creature_you_control", False),
                remember_source_id=choice.get("remember_source_id"),
                total_mana_value_budget=total_mana_value_budget,
                spent_mana_value=spent_mana_value,
                chooser=self.state.player_by_id(chooser_id),
                share_land_type=share_land_type,
                untap_if_lands_at_least=choice.get("untap_if_lands_at_least"),
                then_specs_if_none=choice.get("then_specs_if_none"),
                then_specs=choice.get("then_specs"),
                then_source_id=choice.get("then_source_id"),
                track_exiled_with=choice.get("track_exiled_with", False),
                reveal=choice.get("reveal", False),
            ))
            return

        self._finish_search(
            player, found, choice["destination"],
            zones=zones, destinations=choice.get("destinations"),
            exile_rest=choice.get("exile_rest", False),
            criteria=choice["criteria"],
            extra_counters=choice.get("extra_counters"),
            destination_if=choice.get("destination_if"),
            attach_to_creature_you_control=choice.get("attach_to_creature_you_control", False),
            remember_source_id=choice.get("remember_source_id"),
            chooser_id=chooser_id,
            track_exiled_with=choice.get("track_exiled_with", False),
            track_source_id=choice.get("then_source_id"),
            untap_if_lands_at_least=choice.get("untap_if_lands_at_least"),
            reveal=choice.get("reveal", False),
        )
        # "…if you don't put a card … this way, <body>." (The Vast Scrier) —
        # the search finished and nothing was picked.
        if not found and choice.get("then_specs_if_none"):
            self._apply_effect_specs(
                list(choice["then_specs_if_none"]),
                self._object_by_instance_id(choice.get("then_source_id")),
            )
        elif not declined and choice.get("then_specs"):
            self._apply_effect_specs(
                list(choice["then_specs"]),
                self._object_by_instance_id(choice.get("then_source_id")),
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
        attach_to_creature_you_control: bool = False,
        remember_source_id: Optional[int] = None,
        total_mana_value_budget: Optional[int] = None,
        spent_mana_value: int = 0,
        chooser: Optional[Player] = None,
        share_land_type: bool = False,
        untap_if_lands_at_least: Optional[int] = None,
        then_specs_if_none: Optional[list[dict]] = None,
        then_specs: Optional[list[dict]] = None,
        then_source_id: Optional[int] = None,
        track_exiled_with: bool = False,
        reveal: bool = False,
    ) -> dict[str, Any]:
        """Build the serializable `pending_choice` for a search in progress."""
        zones = list(zones) if zones else ["library"]
        remaining_budget = (
            None if total_mana_value_budget is None else total_mana_value_budget - spent_mana_value
        )
        found_objs = [
            o for o in (self._object_by_instance_id(iid) for iid in found) if o is not None
        ]
        eligible = [
            {"instance_id": obj.instance_id, "name": obj.name}
            for obj in self._search_zone_objects(player, zones)
            if obj.instance_id not in found and card_query.matches(obj.card, criteria)
            and (remaining_budget is None or obj.mana_value <= remaining_budget)
            and _shares_land_type(obj, found_objs, share_land_type)
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
            {"library": "Bibliothek", "graveyard": "Friedhof", "hand": "Hand", "exile": "Exil"}[z]
            for z in zones
        )
        prompt = (
            f"Wähle aus deiner {zone_label}: {description}" if zones in (["hand"], ["exile"])
            else f"Suche in {zone_label} nach: {description}"
        )
        if count > 1:
            prompt += f" (noch {count - len(found)})"
        return {
            "kind": "search",
            "reveal": bool(reveal),
            "player_id": (chooser or player).id,
            "library_owner_id": player.id,
            "destination": destination,
            "destinations": list(destinations) if destinations else None,
            "zones": zones,
            "exile_rest": exile_rest,
            "extra_counters": dict(extra_counters) if extra_counters else None,
            "destination_if": [dict(rule) for rule in destination_if] if destination_if else None,
            "attach_to_creature_you_control": bool(attach_to_creature_you_control),
            # "…then if you control N or more lands, untap that land."
            # (Fabled Passage) — applied to the fetched land in
            # `_finish_search`; only meaningful for battlefield_tapped.
            "untap_if_lands_at_least": untap_if_lands_at_least,
            "remember_source_id": remember_source_id,
            "total_mana_value_budget": total_mana_value_budget,
            "spent_mana_value": spent_mana_value,
            "share_land_type": share_land_type,
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
            # "…if you don't put a card … this way, <body>." (The Vast
            # Scrier) — run once the search finishes with nothing picked.
            "then_specs_if_none": [dict(d) for d in (then_specs_if_none or [])],
            "then_specs": [dict(d) for d in (then_specs or [])],
            "then_source_id": then_source_id,
            # "…exile them, then incubate 2 **that many times**." (Phyrexian
            # Incubator) — every card sent to exile by this search is
            # appended to the source's `GameObject.exiled_with_ids`, so a
            # later `create_token` with ``count_selector="exiled_with_count"``
            # in the same effect list can read the count back after the
            # RULE 608.2 pending-choice suspension (the id list lives on the
            # permanent, not the resolution's `GameContext`).
            "track_exiled_with": bool(track_exiled_with),
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
        attach_to_creature_you_control: bool = False,
        remember_source_id: Optional[int] = None,
        chooser_id: Optional[str] = None,
        track_exiled_with: bool = False,
        track_source_id: Optional[int] = None,
        untap_if_lands_at_least: Optional[int] = None,
        reveal: bool = False,
    ) -> None:
        """Move every chosen card to its destination, then shuffle the
        library (RULE 701.19e) — unless ``exile_rest`` suppresses it
        entirely (Doomsday-shaped, see `_request_search`). ``destinations``,
        if given, overrides ``destination`` per chosen card, positionally
        (Cultivate/Kodama's Reach-shaped split destinations)."""
        zones = list(zones) if zones else ["library"]
        chosen: list[GameObject] = []
        for instance_id in found:
            if reveal:
                # RULE 701.20a/b: publicly show the find before moving it;
                # revealing itself does not change its zone.
                hit = next((o for o in self._search_zone_objects(player, zones)
                            if o.instance_id == instance_id), None)
                if hit is not None:
                    self.state.fire_event(GameEvent(
                        EventType.REVEAL, player_id=player.id, object=hit.name,
                        instance_id=hit.instance_id, card_id=hit.card.id,
                        from_zone=hit.zone.value,
                    ))
            obj = self._remove_search_hit(player, instance_id, zones)
            if obj is not None:
                chosen.append(obj)
        if remember_source_id is not None and chosen:
            # "Exile a card from a graveyard. [...] the exiled card."
            # (Cemetery Gatekeeper) — `ExileEffect.remember`'s search-shaped
            # sibling; only meaningful with a single real find.
            source_obj = self.state.find_object(remember_source_id)
            if source_obj is not None:
                source_obj.linked_exile_id = chosen[0].instance_id

        # MEC-39 (Opposition Agent): "While an opponent is searching their
        # library, they exile each card they find. You may play those
        # cards..." — a standing redirect that overrides *every* found
        # card's destination to exile and grants the redirect's own
        # controller (not the searching player) the play/mana permissions
        # for it, regardless of what the search itself asked for.
        redirect_controller_id = continuous.search_redirect_controller_for(self.state, player)
        dest_list = list(destinations) if destinations else []
        rules = list(destination_if) if destination_if else []
        effective_destinations: list[str] = []
        for index, obj in enumerate(chosen):
            if redirect_controller_id is not None:
                effective_destinations.append("exile")
                continue
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
        to_library = any(
            d in ("library_top", "library_bottom", "library_third") for d in effective_destinations
        )
        if shuffle and to_library:
            self.shuffle_library(player)
        for obj, dest in zip(chosen, effective_destinations):
            if dest in ("battlefield", "battlefield_tapped") and continuous.graveyard_library_entry_prohibited(
                self.state, obj.card, zone=obj.zone.value
            ):
                # RULE 601.3a-adjacent: "`<type>` cards in graveyards and
                # libraries can't enter the battlefield." (Grafdigger's
                # Cage/Weathered Runestone) — the card was already pulled
                # out of its zone's list above (`_remove_search_hit`)
                # without touching `obj.zone` itself, which still names
                # where it came from, so putting it back there is a plain
                # re-add rather than a real "return" move.
                player.add_to_zone(obj, obj.zone)
                continue
            if dest in ("battlefield", "battlefield_tapped") and continuous.uncast_creature_entry_exiled(
                self.state, obj.card
            ):
                # "If a nontoken creature would enter and it wasn't cast,
                # exile it instead." (MEC-43 round 4D, Containment Priest)
                # — the same choke point as the prohibition above, just a
                # redirect instead of a plain no-op: the card was already
                # pulled out of its zone's list, so this sends it to exile
                # rather than putting it back.
                self.exile(obj)
                continue
            self._put_searched_card(player, obj, dest, chooser_id=chooser_id)
            if (
                untap_if_lands_at_least is not None
                and dest == "battlefield_tapped"
                and obj.is_land
            ):
                # "…then if you control N or more lands, untap that land."
                # (Fabled Passage) — RULE 701.19-adjacent: the fetched land
                # has already entered (it counts itself), and this trailing
                # conditional untaps it only when the controller now has at
                # least N lands on the battlefield.
                own_lands = sum(
                    1 for o in self.state.battlefield
                    if o.is_land and o.controller_id == player.id
                )
                if own_lands >= untap_if_lands_at_least:
                    obj.tapped = False
            if redirect_controller_id is not None:
                # RULE 605.1a/601.3a-adjacent: "you may play those cards for
                # as long as they remain exiled, and you may spend mana as
                # though it were mana of any color to cast them" — the same
                # standing exile-cast + any-color-mana permission pair every
                # other "play from exile" card grants, just to a *different*
                # player than the card's own owner.
                self.state.exile_cast_condition[obj.instance_id] = (redirect_controller_id, {})
                self.state.mana_wildcard_permission[obj.instance_id] = "color"
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
            if attach_to_creature_you_control and dest in ("battlefield", "battlefield_tapped"):
                # Stonehewer Giant/Quest for the Holy Relic: "…put it onto
                # the battlefield, **attach it to a creature you control**"
                # — auto-picks the first eligible creature (see
                # `_request_search`'s docstring for why); silently stays
                # unattached (RULE 301.5c-legal) if there is none.
                host = next(
                    (
                        o for o in self.state.permanents()
                        if o.is_creature and o.controller_id == player.id and o is not obj
                    ),
                    None,
                )
                if host is not None:
                    self.attach_to_target(obj, host)
        if shuffle and not to_library:
            self.shuffle_library(player)

        if track_exiled_with and track_source_id is not None:
            # "…exile them, then incubate 2 **that many times**." (Phyrexian
            # Incubator) — record every card this search sent to exile onto
            # the source so a following `count_selector="exiled_with_count"`
            # reads the count back across the RULE 608.2 suspension.
            track_source = self.state.find_object(track_source_id)
            if track_source is not None:
                for obj, dest in zip(chosen, effective_destinations):
                    if dest == "exile":
                        track_source.exiled_with_ids.append(obj.instance_id)

        if exile_rest:
            # MEC-37 (Doomsday): when ``destination`` is itself one of the
            # searched ``zones`` ("library_top" while zones includes
            # "library"), a chosen card is already back in a searched zone
            # by this point (`_put_searched_card` above) — excluded here by
            # id, or this sweep would immediately re-catch and exile the
            # very cards it just found and placed.
            chosen_ids = {obj.instance_id for obj in chosen}
            rest = [
                obj
                for obj in self._search_zone_objects(player, zones)
                if obj.instance_id not in chosen_ids
                and card_query.matches(obj.card, criteria)
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
    def _put_searched_card(
        self, player: Player, obj: GameObject, destination: str,
        chooser_id: Optional[str] = None,
    ) -> None:
        from_zone = obj.zone.value
        if destination in ("battlefield", "battlefield_tapped", "battlefield_attacking", "battlefield_attacking_triggering"):
            obj.summoning_sick = True
            # RULE 614.1: a permanent's own "enters with" replacement applies
            # no matter whether it was cast or put onto the battlefield.
            self._apply_entry_counters(obj)
            self._apply_granted_entry_counters(obj)
            if obj.is_land and destination == "battlefield":
                # RULE 614.1 (bug report, 2026-09-04): an *unqualified*
                # "put it onto the battlefield" (Wooded Foothills/Prismatic
                # Vista-shaped true fetchlands — as opposed to
                # ``"battlefield_tapped"``'s own explicit instruction,
                # Evolving Wilds-shaped) doesn't itself say tapped or
                # untapped, so the found land's *own* printed entry
                # condition still governs — a check/fast/slow land's
                # board-state test, or a shock land's genuine "you may pay
                # N life" choice (`enter_land_tapped`, the same dispatcher
                # `GameEngine.play_land` already routes an ordinary land
                # play through). Previously this branch just hardcoded
                # ``obj.tapped = False``, so a fetched shock land always
                # entered untapped for free, no choice offered at all.
                # ``"battlefield_tapped"`` stays a plain unconditional tap
                # below — real-card ruling (Evolving Wilds vs. a shock
                # land): the fetch effect's own explicit "tapped" already
                # decides it, so the land's own conditional ability isn't
                # separately offered.
                self.enter_land_tapped(obj)
            else:
                obj.tapped = destination != "battlefield"
            self.state.add_to_battlefield(obj)
            self.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD,
                    from_zone=from_zone,
                    controller_id=player.id,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
            if destination in ("battlefield_attacking", "battlefield_attacking_triggering"):
                # RULE 508.4: "…onto the battlefield tapped **and attacking**"
                # (Preeminent Captain, Kaalia of the Vast). The tap is set
                # above; this puts it into the current combat.
                entered_attacking = self.put_onto_battlefield_attacking(obj)
                # The Vast Scrier's explicit post-entry instruction, not the
                # generic RULE 508.3a path: make this creature's printed
                # attack triggers fire without changing declaration history.
                if destination == "battlefield_attacking_triggering" and entered_attacking:
                    self.state.fire_event(GameEvent(
                        EventType.ATTACKS, attacker=obj.name, player_id=obj.controller_id,
                        instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                        defending_player_id=(obj.combat_defender or {}).get("id"),
                    ))
        elif destination == "library_bottom":
            obj.zone = Zone.LIBRARY
            player.library.insert(0, obj)  # bottom (index 0 — see Player.library)
        elif destination == "library_top":
            player.add_to_zone(obj, Zone.LIBRARY)  # top of deck is the list end
        elif destination == "library_third":
            # Long-Term Plans: "put that card third from the top" (RULE 401.7).
            self._insert_library_nth_from_top(player, obj, 3)
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
        elif destination == "exile_free_cast":
            # "…exile that card…. You may cast that card without paying
            # its mana cost." (Bring to Light, MEC-41) — unlike
            # ``"cast_free"`` above, the found card doesn't cast
            # immediately: it sits in exile with a **standing** (never
            # turn-swept) free-cast permission, the same combination
            # `ExileEffect.grant_owner_play_permission`'s `GameState.
            # exile_cast_condition` uses for ordinary-cost exile-casting
            # (an empty condition dict always holds — `static_conditions.
            # condition_holds`) plus `GameState.free_cast_instance_ids` so
            # the eventual cast costs nothing when it happens.
            player.add_to_zone(obj, Zone.EXILE)
            self.state.fire_event(
                GameEvent(EventType.EXILE, player_id=player.id, object=obj.name, from_zone="library")
            )
            self.state.exile_cast_condition[obj.instance_id] = (player.id, {})
            self.state.free_cast_instance_ids.add(obj.instance_id)
        elif destination == "exile_face_down_standing_cast":
            # "Search target opponent's library for a card and exile it
            # face down. [...] You may play that card for as long as it
            # remains exiled." (Praetor's Grasp, MEC-42) — the same
            # face-down-in-exile marker as ``"exile_face_down"`` above, but
            # the standing (never turn-swept) cast permission goes to
            # ``chooser_id`` (the caster, RULE 701.19a's "target opponent"
            # shape — the found card's *owner* never changes, it stays
            # exiled among ``player``'s own cards) rather than to
            # ``player`` itself the way ``"exile_free_cast"``'s same-player
            # search grants it to. Ordinary mana cost still applies —
            # unlike ``"exile_free_cast"``, `GameState.free_cast_instance_
            # ids` is never touched.
            obj.face_down_in_exile = True
            player.add_to_zone(obj, Zone.EXILE)
            self.state.fire_event(
                GameEvent(EventType.EXILE, player_id=player.id, object=obj.name, from_zone="library")
            )
            self.state.exile_cast_condition[obj.instance_id] = (chooser_id or player.id, {})
        else:  # hand (default) — most tutors
            player.add_to_zone(obj, Zone.HAND)
    def _request_impulsive_look(
        self,
        player: Player,
        count: int,
        criteria: Any = "",
        hit_destination: str = "hand",
        miss_destination: str = "graveyard",
        optional: bool = True,
        hit_grant_keywords: Optional[list[str]] = None,
        miss_effect_specs: Optional[list[dict]] = None,
        source: Optional[GameObject] = None,
        hit_effect_specs: Optional[list[dict]] = None,
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
            if miss_destination == "library_bottom_random":
                # "…put the rest on the bottom of your library in a random
                # order." (Narset, Parter of Veils) — a *group* shuffle
                # among just these cards, not each one independently
                # bottomed in reveal order; `_bottom_remaining` already
                # does exactly this for `dig_until`'s own rest destination.
                self._bottom_remaining(player, [o.instance_id for o in peeled])
            else:
                for obj in peeled:
                    player.remove_from_zone(obj, Zone.EXILE)
                    self._put_searched_card(player, obj, miss_destination)
            # "If you don't put a card onto the battlefield this way, <body>."
            # (The Joiner of Cats) — nothing eligible counts as "didn't".
            self._apply_effect_specs(list(miss_effect_specs or []), source)
            return
        self._pending_impulsive_look = {
            "source": source,
            "miss_effect_specs": [dict(d) for d in (miss_effect_specs or [])],
            "hit_effect_specs": [dict(d) for d in (hit_effect_specs or [])],
        }
        self.open_choice({
            "kind": "impulsive_look",
            "player_id": player.id,
            "optional": optional,
            "hit_destination": hit_destination,
            "miss_destination": miss_destination,
            "hit_grant_keywords": list(hit_grant_keywords or []),
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
        })
    @continuations.choice("impulsive_look", answer=continuations.ANSWER_INT, rule="601.2b")
    def _resume_impulsive_look(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer a pending `_request_impulsive_look` choice: take the chosen
        card (or none, if optional), then route every other peeled card to
        ``miss_destination``."""
        player = self.state.player_by_id(choice["player_id"])
        pending_else = self._pending_impulsive_look
        self._pending_impulsive_look = None

        chosen_id: Optional[int] = None
        if instance_id is not None:
            eligible_ids = {e["instance_id"] for e in choice["eligible"]}
            if instance_id not in eligible_ids:
                raise ValueError(f"{instance_id} is not a valid impulsive-look target")
            chosen_id = instance_id

        peeled_ids = set(choice["peeled"])
        exiled = [o for o in list(player.exile) if o.instance_id in peeled_ids]
        if choice["miss_destination"] == "library_bottom_random":
            miss_ids = [o.instance_id for o in exiled if o.instance_id != chosen_id]
            if chosen_id is not None:
                hit = next(o for o in exiled if o.instance_id == chosen_id)
                player.remove_from_zone(hit, Zone.EXILE)
                self._put_searched_card(player, hit, choice["hit_destination"])
                self._apply_impulsive_look_hit_grants(hit, choice.get("hit_grant_keywords"))
            self._bottom_remaining(player, miss_ids)
            if chosen_id is not None:
                self._apply_impulsive_look_hit_effects(hit, pending_else)
            self._apply_impulsive_look_miss_branch(chosen_id, pending_else)
            return
        for obj in exiled:
            is_hit = obj.instance_id == chosen_id
            destination = choice["hit_destination"] if is_hit else choice["miss_destination"]
            player.remove_from_zone(obj, Zone.EXILE)
            self._put_searched_card(player, obj, destination)
            if is_hit:
                self._apply_impulsive_look_hit_grants(obj, choice.get("hit_grant_keywords"))
        if chosen_id is not None:
            self._apply_impulsive_look_hit_effects(
                next(obj for obj in exiled if obj.instance_id == chosen_id), pending_else
            )
        self._apply_impulsive_look_miss_branch(chosen_id, pending_else)

    def _apply_impulsive_look_hit_effects(self, hit: GameObject, pending: Optional[dict]) -> None:
        """RULE 608.2: subsequent instructions about the library choice's own card."""
        if not pending or not pending.get("hit_effect_specs"):
            return
        from ..binding.core import build_effects
        from ...parser.oracle.spec import EffectSpec

        source = pending.get("source")
        effects = build_effects([EffectSpec.from_dict(spec) for spec in pending["hit_effect_specs"]], source)
        _apply_effects_partitioned(effects, self.context, None, None, source=source, created_objects=[hit])

    def _apply_impulsive_look_miss_branch(
        self, chosen_id: Optional[int], pending_else: Optional[dict]
    ) -> None:
        """"If you don't put a card onto the battlefield this way, <body>."
        (The Joiner of Cats) — run the else-branch specs when the look placed
        nothing (the player declined; the nothing-eligible case is handled
        inline in `_request_impulsive_look`)."""
        if chosen_id is not None or not pending_else:
            return
        self._apply_effect_specs(
            list(pending_else.get("miss_effect_specs") or []),
            pending_else.get("source"),
        )

    def _apply_impulsive_look_hit_grants(
        self, obj: "GameObject", keywords: Optional[list[str]]
    ) -> None:
        """RULE 514.2 — "It gains <keyword> until end of turn." on the card an
        `impulsive_look` places onto the battlefield (Winota, Joiner of
        Forces). A no-op unless the card actually landed on the battlefield."""
        if not keywords or obj not in self.state.battlefield:
            return
        for kw in keywords:
            obj.temp_keywords.add(kw)
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

        ``same_turn_only`` marks the entry in `GameState.temp_play_
        permission_same_turn_only` for `GameEngine._step_cleanup`'s sweep:
        the *granting* turn number is always what's stored in
        `temp_play_permissions` (needed either way, to tell "still this
        turn" apart from "a later turn" — see that sweep's own comment for
        why "until the end of **your** next turn" can't be a flat turn-
        number comparison the way "until end of turn" can).
        """
        self.state.temp_play_permissions[obj.instance_id] = self.state.internal_turn.number
        if same_turn_only:
            self.state.temp_play_permission_same_turn_only.add(obj.instance_id)
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
        grant: bool = True,
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

        Distinct from `_request_impulsive_look`: no filter, no choice, and
        nothing is routed to a miss destination — every card exiled here
        stays in exile, playable, until its window lapses (swept by
        `GameEngine._step_cleanup`) or it's actually cast/played.

        ``source_name`` (the granting spell/ability's name, e.g. "Light Up
        the Stage") is recorded in the sibling `GameState.
        temp_play_permission_source` so the board can explain *why* the
        card is castable — purely cosmetic, no effect on legality.
        ``mana_wildcard`` — see `GameState.mana_wildcard_permission`.

        ``grant=False`` only exiles (PAR-137, "exile the top two cards of your library. Choose 1 of
        them. You may play that card this turn."): the caller then offers the pick and grants the
        permission to that one card alone via the ``grant_temp_play*`` choose-object actions.
        """
        holder = permission_player or player
        exiled: list[GameObject] = []
        for _ in range(max(0, count)):
            if not player.library:
                break
            obj = player.library.pop()
            obj.zone = Zone.EXILE
            player.exile.append(obj)
            if grant:
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
    def grant_free_cast_window_from_exile(
        self, obj: GameObject, caster: Optional[Player] = None, ignore_timing: bool = False,
    ) -> None:
        """Open ``obj``'s (already-exiled) "cast it without paying its mana
        cost" window for the rest of the turn — reuses
        `_grant_temp_play_permission`'s same-turn-only temp-cast permission
        (so `can_cast`/`cast_spell` already know how to let it be cast from
        exile) plus `GameState.free_cast_instance_ids` to also zero its mana
        cost. Casting it that way goes through the ordinary action loop, so
        the spell gets its full targeting/modal choices rather than a
        stripped-down mid-resolution cast.

        Callers, all "you may cast this card from exile without paying its
        mana cost": RULE 702.88b Rebound's delayed half
        (`ReboundFreeCastWindowEffect`), Beseech the Mirror's bargained
        clause (`CastExiledFaceDownEffect`), MEC-52's `dig_until`
        ``cast_free_window``, and Etali, Primal Storm/Primal Conqueror's
        own `exile_top_from_each_player_cast_free`. ``caster``, when given,
        is a *different* player than the card's owner (Ensnared by the
        Mara — "**you** may cast that card" off an opponent's library):
        they become its controller for the window (RULE 601.3e).

        ``ignore_timing`` (Etali's own ruling: "timing permissions based on
        a card's type are ignored, and the spells resolve before blockers
        are declared") also stamps `GameState.free_cast_ignore_timing_
        instance_ids`, so `GameEngine.can_cast` offers even a sorcery-speed
        card the instant this window opens — mid-combat included — rather
        than only once a later main phase with an empty stack comes
        around. **Documented simplification** shared with every other
        caller above: the window still lasts the rest of the turn rather
        than being a use-it-now-or-lose-it decision at the exact moment of
        resolution (Etali's own ruling: "you do so as part of the
        resolution of the triggered ability... you can't wait to cast them
        later in the turn") — forcing an immediate multi-card, ordered,
        fully-targeted "cast any number of these" decision inline with
        resolving one triggered ability would need a dedicated interactive
        chooser this engine doesn't have yet, so a same-turn window (this
        primitive's one existing shape) is used instead, same trade-off as
        Rebound/Beseech the Mirror/MEC-52 already accepted.
        """
        controller = caster or self.state.player_by_id(obj.controller_id)
        if controller is None:
            return
        if caster is not None:
            # RULE 601.3e: casting a card you don't own makes you its
            # controller while it's a spell / on the battlefield.
            obj.controller_id = caster.id
        self._grant_temp_play_permission(
            obj, controller, obj.name, same_turn_only=True, mana_wildcard=None,
        )
        self.state.free_cast_instance_ids.add(obj.instance_id)
        if ignore_timing:
            self.state.free_cast_ignore_timing_instance_ids.add(obj.instance_id)
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
    def _request_cascade(self, player: Player, max_mana_value: int) -> None:
        """Cascade (RULE 702.85): exile from the top until a nonland spell
        cheaper than the cascade spell, which its controller *may* cast for
        free; the rest go to the bottom in a random order.

        Exiles eagerly, then — if a hit was found — opens a "may cast" choice
        through the ordinary immediate-play path. With no hit it bottoms
        what it exiled. The bottoming is deferred to the choice so a card that is cast
        leaves exile first (RULE 702.85a ordering).
        """
        criteria = {"max_mana_value": max_mana_value - 1}
        matched, exiled = self._exile_top_until(player, criteria, exclude_lands=True)
        if matched is None:
            self._bottom_exiled(player, exiled)
            return
        self._request_resolution_play(
            player, [matched], only_spells=True, max_mana_value=max_mana_value,
            bottom_remaining=[obj.instance_id for obj in exiled],
        )
        self.state.pending_choice["prompt"] = f"Cascade — {matched.name} kostenlos wirken?"
    @continuations.choice(
        "cascade",
        answer=continuations.ANSWER_FLAG,
        yes="cast",
        rule="702.85",
    )
    def _resume_cascade(self, choice: dict[str, Any], cast: bool = True) -> None:
        """Finish a cascade: ``cast`` the hit for free (or not), then bottom
        every still-exiled card from this cascade in a random order."""
        player = self.state.player_by_id(choice["player_id"])

        if cast:
            obj = self._exiled_by_id(player, choice["exiled"], choice["matched_id"])
            if obj is not None:
                self.cast_without_paying(player, obj)
        self._bottom_remaining(player, choice["exiled"])
    #: A mana-value bound no real card reaches, for a dig that has no cap on what it exiles ("until you exile a nonland card").
    UNBOUNDED_MANA_VALUE = 1_000_000

    def _request_discover(
        self, player: Player, max_mana_value: int, cast_limit: Optional[int] = None,
        treasures_below: Optional[int] = None, source: Optional[GameObject] = None,
    ) -> None:
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
        if cast_limit is not None and matched.mana_value > cast_limit:
            # "You may cast it without paying its mana cost if that spell's mana value is 8 or less. If you
            # don't, put that card into your hand." (Breaching Dragonstorm) — a too-big hit can only be taken.
            player.remove_from_zone(matched, Zone.EXILE)
            player.add_to_zone(matched, Zone.HAND)
            self._bottom_remaining(player, [o.instance_id for o in exiled])
            return
        self.open_choice({
            "treasures_below": treasures_below,
            "source_id": getattr(source, "instance_id", None),
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
        })
    @continuations.choice(
        "discover",
        answer=continuations.ANSWER_FLAG,
        yes="hand",
        rule="701.57",
    )
    def _resume_discover(self, choice: dict[str, Any], to_hand: bool = False) -> None:
        """Finish a discover: cast the hit for free, or (``to_hand``) put it
        into hand. Either way the card leaves exile; bottom the rest."""
        player = self.state.player_by_id(choice["player_id"])

        matched = self._exiled_by_id(player, choice["exiled"], choice["matched_id"])
        if matched is not None:
            if to_hand:
                player.remove_from_zone(matched, Zone.EXILE)
                player.add_to_zone(matched, Zone.HAND)
            else:
                self.cast_without_paying(player, matched)
            # "If the discovered card's mana value is less than 10, create a number of tapped Treasure tokens
            # equal to the difference." (Hit the Mother Lode)
            below = choice.get("treasures_below")
            if below is not None and matched.mana_value < below:
                self._apply_effect_specs([{"type": "create_token", "params": {
                    "token_name": "Treasure", "tapped": True, "count": below - matched.mana_value,
                }}], self.state.find_object(choice.get("source_id")))
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
    def _request_name_card(
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
        is only ever compared against card names (`models.cards.card_query`'s
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
        self.open_choice({
            "kind": "name_card",
            "player_id": player.id,
            "prompt": prompt,
            # Suggestions only — `_resume_name_card` takes any string.
            "free_text": True,
            "options": [{"id": name, "label": name} for name in sorted(known)],
        })
    @continuations.choice("name_card", answer=continuations.ANSWER_STR, rule="701.20")
    def _resume_name_card(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `name_card` choice with an arbitrary card name.

        A missing/declined answer names the empty string, which matches no
        card — for Demonic Consultation that means the dig finds nothing and
        exiles the library, which is the correct (if catastrophic) outcome of
        naming a card that isn't there, not an error.
        """
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
        """Replace the ``"named_card"`` sentinel anywhere in an effect's
        parameter tree with the answered name.

        The original user was a card-query criterion; later operations can
        compare a revealed card's name directly, so keeping the substitution
        generic avoids a one-off naming continuation for each such effect.
        """
        def replace(value: Any) -> Any:
            if value == "named_card":
                return name
            if isinstance(value, dict):
                return {k: replace(v) for k, v in value.items()}
            if isinstance(value, list):
                return [replace(v) for v in value]
            return value

        return replace(params)
    def _request_look_top_pay_life_loop(
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
        self.open_choice({
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
        })
    @continuations.choice("look_top_pay_life", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_look_top_pay_life(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `look_top_pay_life` choice — go again (pay the
        life, bottom what you just looked at, look at the next batch) or
        stop (shuffle, then put the last batch back on top).

        Stopping shuffles *first* and replaces the batch afterwards (RULE
        701.19e's ordering, the same one `_finish_search` uses for a
        library destination) — otherwise the shuffle would scatter the very
        cards the card promises to leave on top.
        """
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
            self._request_choose_objects(
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
        self._request_look_top_pay_life_loop(player, count, life_cost)
    def _request_reveal_top_hand_lose_life_loop(self, player: Player) -> None:
        """"Reveal the top card of your library and put that card into
        your hand. You lose life equal to its mana value. You may repeat
        this process any number of times." (Ad Nauseam, MEC-41) — the
        engine's second **open-ended**, self-re-opening loop (see
        `_request_look_top_pay_life_loop`'s own docstring for the first),
        but distinct enough not to share it: each iteration moves a card
        to hand rather than bottoming a batch, the life lost is the
        revealed card's own mana value rather than a flat cost, and —
        RULE 118.4 doesn't apply to a life-*loss* effect the way it does a
        life-*payment* cost — nothing here refuses to keep going once life
        would go to 0 or below; SBAs simply aren't checked mid-resolution
        (RULE 704.3), so the loop is only bounded by the player's own
        choice or an empty library.
        """
        if not player.library:
            return
        top = player.library[-1]
        self.open_choice({
            "kind": "reveal_top_hand_lose_life_loop",
            "player_id": player.id,
            "prompt": f"{top.name} (Manawert {top.mana_value}) "
                      "aufdecken, auf die Hand nehmen und entsprechend Leben "
                      "verlieren?",
            "looking_at": [{"instance_id": top.instance_id, "name": top.name}],
            "options": [
                {"id": "again", "label": "Fortsetzen"},
                {"id": "decline", "label": "Aufhören"},
            ],
        })
    @continuations.choice(
        "reveal_top_hand_lose_life_loop",
        answer=continuations.ANSWER_STR,
        rule="601.2b",
    )
    def _resume_reveal_top_hand_lose_life_loop(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `reveal_top_hand_lose_life_loop` choice — take
        the top card (reveal is purely informational, same idiom every
        other reveal effect in this engine uses) or stop."""
        if answer != "again":
            return
        player = self.state.player_by_id(choice["player_id"])
        if not player.library:
            return
        top = player.library.pop()
        top.zone = Zone.HAND
        player.hand.append(top)
        self.lose_life(player, top.mana_value, cause="effect")
        self._request_reveal_top_hand_lose_life_loop(player)
    def exile_until_duplicate_name(
        self, player: Player, seen_names: Optional[set[str]] = None
    ) -> None:
        """"Exile the top card of your library. You may put that card into
        your hand unless it has the same name as another card exiled this
        way. Repeat this process until you put a card into your hand or you
        exile two cards with the same name, whichever comes first." (Tainted
        Pact) — a genuinely different loop shape from `dig_until` (which
        stops on the first card matching a fixed, static `criteria`): here
        the stop condition is *cumulative* per-iteration state (a growing
        "names seen this resolution" set) with a different outcome each way
        — a name never seen before lets the player choose to *keep* it and
        end the loop, **or gamble and keep digging** (the real reason this
        card exists in cEDH: paired with Thassa's Oracle in a singleton
        deck, where no duplicate is possible, deliberately declining every
        hit exiles the whole library on purpose) — a repeat name always
        ends the loop with nothing gained. MEC-12 (sixth pass) — confirmed a
        singleton template cache-wide, built as a real primitive anyway
        since the loop itself has no card-specific data in it at all.

        A genuine ``pending_choice`` (kind ``"tainted_pact"``) whenever
        there's an actual decision to make — a freshly-exiled non-duplicate
        name with library cards still left to risk; auto-resolved (no
        prompt) the instant there's truly nothing to choose between: a
        duplicate (forced loss, nothing to decide) or an empty library
        after taking it (nothing left to keep digging for).
        """
        seen_names = set(seen_names) if seen_names else set()
        if not player.library:
            return
        obj = player.library.pop()  # top of deck is the list end
        self.exile(obj)
        if obj.name in seen_names:
            return  # a repeat: the process ends empty-handed
        seen_names.add(obj.name)
        if not player.library:
            self.return_to_hand(obj)  # nothing left to gain by asking
            return
        self._pending_tainted_pact_obj = obj
        self._pending_tainted_pact_player = player
        self._pending_tainted_pact_seen = seen_names
        self.open_choice({
            "kind": "tainted_pact",
            "player_id": player.id,
            "prompt": f"{obj.name} exiliert — auf die Hand nehmen oder weiter suchen?",
            "options": [
                {"id": "take", "label": f"{obj.name} auf die Hand nehmen"},
                {"id": "continue", "label": "Weiter exilieren"},
            ],
        })
    @continuations.choice(
        "tainted_pact",
        answer=continuations.ANSWER_STR,
        decline="take",
        rule="601.2b",
    )
    def _resume_tainted_pact(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `tainted_pact` choice (Tainted Pact) — ``"take"``
        (or any unrecognized/missing answer, the safe default) keeps the
        just-exiled card; ``"continue"`` resumes `exile_until_duplicate_name`
        with the same "names seen so far" set, risking a duplicate.
        """
        obj = self._pending_tainted_pact_obj
        player = self._pending_tainted_pact_player
        seen_names = self._pending_tainted_pact_seen
        self._pending_tainted_pact_obj = None
        self._pending_tainted_pact_player = None
        self._pending_tainted_pact_seen = None
        if answer == "continue" and player is not None:
            self.exile_until_duplicate_name(player, seen_names=seen_names)
            return
        if obj is not None:
            self.return_to_hand(obj)
    def transmute_artifact(self, player: Player) -> None:
        """"Sacrifice an artifact. If you do, search your library for an
        artifact card. If that card's mana value is less than or equal to
        the sacrificed artifact's mana value, put it onto the battlefield.
        If it's greater, you may pay {X}, where X is the difference. If you
        do, put it onto the battlefield. If you don't, put it into its
        owner's graveyard. Then shuffle." (Transmute Artifact) — MEC-12
        (sixth pass). A confirmed singleton cost-comparison-gated
        placement: every step after the sacrifice depends on a *live*
        numeric comparison against that specific sacrifice, which no other
        card's shape needs yet, so this is one self-contained bespoke
        sequence (three of its own `pending_choice` kinds — sacrifice,
        search, and an optional pay-the-difference) rather than composed
        from the general search/sacrifice/`pay_cost_then` primitives, none
        of which can express "the cost is a number computed from what a
        *different*, just-made choice turned out to be".

        RULE 608.2b: with no artifact to sacrifice, nothing happens at all
        — the "if you do" branch never triggers, matching a real "sacrifice
        an artifact" bare imperative with no legal candidate.
        """
        artifacts = [
            o for o in self.state.permanents()
            if o.card.is_artifact and o.controller_id == player.id
        ]
        if not artifacts:
            return
        if len(artifacts) == 1:
            self._transmute_artifact_sacrifice(player, artifacts[0])
            return
        self._pending_transmute_player = player
        self.open_choice({
            "kind": "transmute_sacrifice",
            "player_id": player.id,
            "prompt": "Opfere ein Artefakt (Transmute Artifact)",
            "options": [
                {"id": str(o.instance_id), "label": o.name, "instance_id": o.instance_id}
                for o in artifacts
            ],
        })
    @continuations.choice("transmute_sacrifice", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_transmute_sacrifice(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `transmute_sacrifice` choice: which of the
        player's own artifacts to sacrifice for Transmute Artifact."""
        player = self._pending_transmute_player
        self._pending_transmute_player = None
        if player is None or answer is None:
            return
        victim = self._resolve_choice_option(choice["options"], str(answer))
        if victim is not None:
            self._transmute_artifact_sacrifice(player, victim)
    def _transmute_artifact_sacrifice(self, player: Player, victim: GameObject) -> None:
        sacrificed_mv = victim.mana_value
        self.put_into_graveyard(victim)
        eligible = [
            o for o in player.library
            if o.card.is_artifact
        ]
        if not eligible:
            self.shuffle_library(player)
            return
        self._pending_transmute_player = player
        self._pending_transmute_sacrificed_mv = sacrificed_mv
        self.open_choice({
            "kind": "transmute_search",
            "player_id": player.id,
            "prompt": "Durchsuche deine Bibliothek nach einer Artefaktkarte (Transmute Artifact)",
            "options": [
                {"id": str(o.instance_id), "label": o.name, "instance_id": o.instance_id}
                for o in eligible
            ]
            + [{"id": "decline", "label": "Nichts wählen"}],
        })
    @continuations.choice("transmute_search", answer=continuations.ANSWER_STR, rule="701.23")
    def _resume_transmute_search(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `transmute_search` choice: the artifact card
        found (or a decline). A found card whose mana value is at most the
        sacrificed artifact's own goes straight to the battlefield; a
        pricier one opens the "pay the difference" choice instead."""
        player = self._pending_transmute_player
        sacrificed_mv = self._pending_transmute_sacrificed_mv
        self._pending_transmute_player = None
        self._pending_transmute_sacrificed_mv = None
        if player is None or answer is None or str(answer) == "decline":
            self.shuffle_library(player)
            return
        found = self._resolve_choice_option(choice["options"], str(answer))
        if found is None or found not in player.library:
            self.shuffle_library(player)
            return
        player.remove_from_zone(found, Zone.LIBRARY)
        self.shuffle_library(player)
        found_mv = found.mana_value
        if found_mv <= sacrificed_mv:
            self._put_searched_card(player, found, "battlefield")
            return
        difference = found_mv - sacrificed_mv
        self._pending_transmute_found_obj = found
        self._pending_transmute_player = player
        cost = ActivationCost(mana=ManaCost.parse("{" + str(difference) + "}"))
        if not self._can_pay_player_cost(player, cost):
            self.put_into_graveyard(found)
            return
        self._pending_transmute_cost = cost
        self.open_choice({
            "kind": "transmute_pay_x",
            "player_id": player.id,
            "prompt": f"{{{difference}}} bezahlen, um {found.name} ins Spiel zu bringen?",
            "options": [
                {"id": "pay", "label": f"{{{difference}}} bezahlen"},
                {"id": "decline", "label": "Nicht bezahlen"},
            ],
        })
    @continuations.choice("transmute_pay_x", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_transmute_pay_x(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `transmute_pay_x` choice: pay the mana-value
        difference to put the found artifact onto the battlefield, or let
        it go to its owner's graveyard instead."""
        player = self._pending_transmute_player
        found = self._pending_transmute_found_obj
        cost = self._pending_transmute_cost
        self._pending_transmute_player = None
        self._pending_transmute_found_obj = None
        self._pending_transmute_cost = None
        if found is None:
            return
        if answer == "pay" and player is not None and cost is not None and self._can_pay_player_cost(player, cost):
            self._pay_player_cost(player, cost)
            self._put_searched_card(player, found, "battlefield")
        else:
            self.put_into_graveyard(found)
    def dig_until(
        self,
        player: Player,
        criteria: Any,
        hit_destination: str = "hand",
        rest_destination: str = "exile",
        pre_exile: int = 0,
        caster: Optional[Player] = None,
        hit_rider: Optional[str] = None,
        uncast_hit: str = "library_bottom",
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

        ``caster`` (MEC-52 — Ensnared by the Mara's "**you** may cast that
        card") routes a ``cast_free``/``cast_free_window`` hit to a
        *different* player than the one whose library was dug — the effect's
        controller casting a card off an opponent's library. ``None`` keeps
        the digger as the caster (every other caller).

        Returns the matching object, or ``None`` if the library ran out —
        which for Demonic Consultation means the library is now empty, the
        exact state Thassa's Oracle then wins on.
        """
        for _ in range(min(pre_exile, len(player.library))):
            self.exile(player.library[-1])
        matched, revealed = self._exile_top_until(player, criteria, exclude_lands=False)
        if matched is not None and hit_destination != "exile":
            self._place_dig_hit(player, matched, hit_destination, caster=caster, hit_rider=hit_rider, uncast_hit=uncast_hit)
        rest_ids = [o.instance_id for o in revealed if o is not matched]
        if rest_destination == "library_bottom_random":
            self._bottom_remaining(player, rest_ids)
        elif rest_destination == "library_shuffled":
            # "…shuffles all other cards revealed this way into their
            # library." (Polymorph/Transmogrify-shaped) — genuinely
            # shuffled anywhere, not just the bottom; putting them at the
            # bottom (in random order among themselves, same as the
            # ``library_bottom_random`` branch) and then reshuffling the
            # whole library is observably identical to a real player (an
            # unknown order either way).
            self._bottom_remaining(player, rest_ids)
            self.shuffle_library(player)
        elif rest_destination == "graveyard":
            # "…and all other cards revealed this way into your graveyard."
            # (Hermit Druid, MEC-43) — a plain library→graveyard move for
            # cards this dig already exiled, mirroring `mill`'s own direct
            # zone move rather than `_move_to_graveyard`'s full battlefield-
            # leave machinery (which is for a permanent *dying*, not a
            # library card being discarded past by a dig).
            self._graveyard_remaining(player, rest_ids)
        return matched
    def _graveyard_remaining(self, player: Player, exiled_ids: list[int]) -> None:
        """Put every still-exiled card from this effect into the graveyard,
        in reveal order — the graveyard sibling of `_bottom_remaining`."""
        remaining = [o for o in list(player.exile) if o.instance_id in set(exiled_ids)]
        for obj in remaining:
            player.remove_from_zone(obj, Zone.EXILE)
            obj.zone = Zone.GRAVEYARD
            player.graveyard.append(obj)
    def _place_dig_hit(
        self, player: Player, obj: GameObject, destination: str,
        caster: Optional[Player] = None, hit_rider: Optional[str] = None, uncast_hit: str = "library_bottom",
    ) -> None:
        """Move a `dig_until` hit out of exile to its destination.

        ``caster`` (MEC-52) is who casts a ``cast_free``/``cast_free_window``
        hit when that is a *different* player than ``player`` (the digger) —
        Ensnared by the Mara's "**you** may cast that card" off an
        opponent's library. ``None`` keeps the digger as the caster."""
        if destination == "cast_during_resolution":
            self._request_resolution_play(caster or player, [obj], only_spells=True, cast_rider=hit_rider)
            return
        if destination == "cast_free":
            self.cast_without_paying(caster or player, obj)
            return
        if destination == "cast_free_window":
            # "That player **may** cast that card without paying its mana
            # cost." — a genuine option, not a forced free cast: the same
            # exile window Rebound and Beseech the Mirror use, so the spell
            # gets its full targeting/modal choices through the ordinary
            # action loop. The card stays in exile until cast, and the
            # delayed half below performs the printed "if they don't cast
            # it" fallback at the next end step.
            self.grant_free_cast_window_from_exile(obj, caster=caster)
            if hit_rider == "haste_sacrifice" and obj.card.is_creature:
                obj.granted_haste_sacrifice = True  # consumed when the spell enters (`_resolve_permanent_spell`)
            if uncast_hit == "library_bottom":
                self.state.delayed_triggers.append(
                    DelayedTrigger(
                        controller_id=(caster or player).id,
                        step="end",
                        scope="any",
                        effects=[ReturnUncastExiledEffect(obj, destination="library_bottom")],
                        description=f"{obj.name}: unter die Bibliothek, falls nicht gewirkt",
                    )
                )
            return
        player.remove_from_zone(obj, Zone.EXILE)
        if destination == "battlefield_attacking":
            # RULE 508.4: "put that card onto the battlefield tapped and attacking" (Raph & Mikey) — the shared
            # search-placement path taps it, fires the entry and puts it into combat.
            self._put_searched_card(player, obj, "battlefield_attacking")
            return
        if destination in ("battlefield", "battlefield_tapped"):
            obj.zone = Zone.BATTLEFIELD
            self.state.add_to_battlefield(obj)
            if destination == "battlefield_tapped":
                obj.tapped = True  # "put that card onto the battlefield tapped" (Clifftop Lookout)
            # RULE 603.6a: an entry is an event — without it "whenever a creature enters"
            # never fired for a card a dig put onto the battlefield.
            self.state.fire_event(GameEvent(
                EventType.ENTERS_BATTLEFIELD, controller_id=player.id, object=obj.name,
                from_zone=Zone.EXILE.value,
                instance_id=obj.instance_id, object_types=sorted(obj.type_words),
            ))
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
    def _bottom_remaining(self, player: Player, exiled_ids: list[int], *, zone: str = "exile") -> None:
        """Put every still-exiled card from this effect on the bottom of the
        library in a random order (RULE 702.85e). Cards already cast/taken to
        hand are no longer in exile and are skipped."""
        import random

        origin = Zone.LIBRARY if zone == "library" else Zone.EXILE
        pool = player.library if origin == Zone.LIBRARY else player.exile
        remaining = [o for o in list(pool) if o.instance_id in set(exiled_ids)]
        random.shuffle(remaining)
        for obj in remaining:
            player.remove_from_zone(obj, origin)
            obj.zone = Zone.LIBRARY
            player.library.insert(0, obj)  # bottom (index 0 — see Player.library)

    def reveal_until_creature_type(
        self,
        player: Player,
        creature_types: Union[list[str], set[str], frozenset[str]],
        count: int = 1,
        hit_destination: str = "battlefield",
        rest_destination: str = "library_bottom_random",
    ) -> list[GameObject]:
        """Reveal cards from the top of ``player``'s library until ``count``
        creature cards matching any of ``creature_types`` are revealed
        (RULE 701.19 / RULE 702.85e, MEC-72 — Descendants' Fury, Kindred Summons).

        Put those cards at ``hit_destination`` (default "battlefield") and
        the rest at ``rest_destination`` ("library_bottom_random" or
        "library_shuffled").
        """
        if count <= 0 or not player.library:
            return []
        norm_types = {t.lower() for t in creature_types}
        hits: list[GameObject] = []
        revealed: list[GameObject] = []
        while player.library and len(hits) < count:
            obj = player.library.pop()
            revealed.append(obj)
            self.state.fire_event(
                GameEvent(
                    EventType.REVEAL,
                    player_id=player.id,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    from_zone="library",
                )
            )
            if obj.card.is_creature:
                has_changeling = "changeling" in obj.card.type_line.lower() or "changeling" in obj.intrinsic_keywords
                if has_changeling:
                    hits.append(obj)
                else:
                    _, _, sub = obj.card.type_line.lower().partition("—")
                    subs = {s.strip() for s in sub.split() if s.strip()}
                    if norm_types & subs:
                        hits.append(obj)

        for obj in hits:
            if hit_destination == "battlefield":
                self._put_searched_card(player, obj, "battlefield")
            elif hit_destination == "hand":
                obj.zone = Zone.HAND
                player.add_to_zone(obj, Zone.HAND)

        rest = [o for o in revealed if o not in hits]
        if rest:
            if rest_destination == "library_bottom_random":
                import random
                random.shuffle(rest)
                for o in rest:
                    o.zone = Zone.LIBRARY
                    player.library.insert(0, o)
            elif rest_destination == "library_shuffled":
                for o in rest:
                    o.zone = Zone.LIBRARY
                    player.library.append(o)
                self.shuffle_library(player)
            elif rest_destination == "graveyard":
                for o in rest:
                    o.zone = Zone.GRAVEYARD
                    player.graveyard.append(o)
        return hits

    def reveal_until_matching(
        self,
        player: Player,
        criteria: Any,
        count: int = 1,
        hit_destination: str = "battlefield",
        rest_destination: str = "library_bottom_random",
        tapped: bool = False,
        entry_choices: bool = False,
    ) -> list[GameObject]:
        """Reveal from the top of ``player``'s library until ``count`` cards
        matching ``criteria`` (a `models.cards.card_query` dict) are revealed
        (Open the Way — "reveal cards from the top of your library until you
        reveal X land cards"), PAR-60. The generalized sibling of
        `reveal_until_creature_type` — a `card_query` predicate instead of a
        fixed creature-subtype list, plus a ``tapped`` option for "…onto the
        battlefield tapped".
        """
        from ...models.cards import card_query  # local: search_mixin already imports lazily

        if count <= 0 or not player.library:
            return []
        hits: list[GameObject] = []
        revealed: list[GameObject] = []
        for obj in list(reversed(player.library)):
            if len(hits) >= count:
                break
            if not entry_choices:
                player.library.remove(obj)
            revealed.append(obj)
            self.state.fire_event(
                GameEvent(EventType.REVEAL, player_id=player.id, object=obj.name,
                          instance_id=obj.instance_id, from_zone="library")
            )
            if card_query.matches(obj.card, criteria):
                hits.append(obj)

        for obj in ([] if entry_choices else hits):
            if hit_destination == "battlefield":
                self._put_searched_card(player, obj, "battlefield")
                if tapped:
                    self.set_tapped(obj, tapped=True)
            elif hit_destination == "hand":
                obj.zone = Zone.HAND
                player.add_to_zone(obj, Zone.HAND)
            elif hit_destination == "graveyard":
                # "…then puts those cards into their graveyard" (Consuming Aberration) — the PUT_INTO_GRAVEYARD
                # arrival event is detected by `GameState.announce_graveyard_arrivals`.
                obj.zone = Zone.GRAVEYARD
                player.graveyard.append(obj)

        rest = [o for o in revealed if o not in hits]
        if entry_choices:
            for obj in rest:
                player.library.remove(obj)
        if rest and rest_destination == "library_bottom_random":
            import random
            random.shuffle(rest)
            for o in rest:
                o.zone = Zone.LIBRARY
                player.library.insert(0, o)
        elif rest and rest_destination == "library_shuffled":
            for o in rest:
                o.zone = Zone.LIBRARY
                player.library.append(o)
            self.shuffle_library(player)
        elif rest and rest_destination == "graveyard":
            for o in rest:
                o.zone = Zone.GRAVEYARD
                player.graveyard.append(o)
        if entry_choices and hits:
            # RULE 614.12: copied characteristics and entry choices precede
            # the entry event. Keep identities in the library during prompts.
            from ..effects.battlefield_batches import start_battlefield_batch
            start_battlefield_batch(self, hits, player.id, tapped=tapped)
        return hits

    def _handle_rest_inspected(
        self, player: Player, rest_ids: list[int], destination: str
    ) -> None:
        """Handle remaining unpicked cards from a bounded top-N inspect
        (MEC-72). Move them to ``destination`` ("library_bottom_random" or
        "graveyard")."""
        objs: list[GameObject] = []
        for iid in rest_ids:
            found = self._object_by_instance_id(iid)
            if found is not None:
                objs.append(found)
        if not objs:
            return
        if destination == "library_bottom_random":
            import random
            random.shuffle(objs)
            for o in objs:
                self._remove_from_current_zone(player, o)
                o.zone = Zone.LIBRARY
                player.library.insert(0, o)
        elif destination in ("graveyard", "graveyard_with_treasures"):
            for o in objs:
                self._remove_from_current_zone(player, o)
                o.zone = Zone.GRAVEYARD
                player.graveyard.append(o)
            if destination == "graveyard_with_treasures":
                # "Create a Treasure token for each card put into your graveyard this way." (Dihada)
                from ...services.token_database import default_token_database

                treasure = default_token_database().get_token("Treasure")
                if treasure is not None:
                    self.create_token(player.id, treasure, count=len(objs))
        elif destination == "hand":
            # PAR-148: "reveal the top card … otherwise, put that card into your hand" (Hans Eriksson, Skyward Eye
            # Prophets) — the unpicked revealed card goes to its owner's hand.
            for o in objs:
                self._remove_from_current_zone(player, o)
                o.zone = Zone.HAND
                player.add_to_zone(o, Zone.HAND)
        elif destination == "library_shuffled":
            # PAR-144 (Genesis Hydra): "shuffle the rest into your library" — the
            # unpicked cards stay in the library, which is then shuffled (RULE 701.20).
            self.shuffle_library(player)

    def inspect_top_n_choose(
        self,
        player: Player,
        count: Union[int, str],
        action: str,
        filter_criteria: Optional[dict[str, Any]] = None,
        rest_destination: str = "library_bottom_random",
        optional: bool = False,
        prompt: str = "Wähle eine Karte",
        source: Optional[GameObject] = None,
        decline_leaves_untouched: bool = False,
        max_picks: Union[int, str] = 1,
        criteria: Optional[dict[str, Any]] = None,
        else_specs: Optional[list[dict]] = None,
        distinct_card_types: bool = False,
    ) -> None:
        """Inspect a bounded top-N group from ``player``'s library, offer a
        filtered choice among them, and route the rest to ``rest_destination``
        (MEC-72 — Eclipsed Flamekin, Cream of the Crop, Cavalier of Thorns).

        Preserves cards' actual zones and choices without auto-picking.

        ``max_picks`` (MEC-85, Earth's Mightiest Heroes — "You may put a
        creature card from among them onto the battlefield. If this spell
        was cast using teamwork, put any number of creature cards from
        among them onto the battlefield instead.") generalizes the single
        pick MEC-72's own cards needed to `_request_choose_objects`'s own
        ``count``: the caller resolves any cast-time-conditional cap
        (`InspectTopChooseEffect.max_picks_if_teamwork`) before this method
        ever sees it, so this stays a plain, teamwork-agnostic "how many"
        knob any future "reveal N, choose up to K" card can reuse.

        PAR-144 widened the pick vocabulary for the whole "look at the top N
        cards of your library. You may reveal a `<kind>` card from among them
        and put it into your hand/onto the battlefield. Put the rest …" family
        (~200 cards): ``criteria`` is a `models.cards.card_query` dict (types
        and subtypes, colours, mana-value bounds, "{X} in its mana cost", …)
        ANDed with the older ``filter_criteria`` keys; ``max_picks="all"`` is
        "any number"/"all" (every matching card); ``else_specs`` are the
        "if you didn't put a card into your hand this way, …" tail, run when
        nothing was picked (including when nothing matched); and a rest
        destination of ``"library_shuffled"`` shuffles the unpicked cards back
        in (Genesis Hydra). Picking nothing is only possible when ``optional``.
        """
        if isinstance(count, str) and count == "trigger_power":
            trigger_event = getattr(self.context, "trigger_event", None)
            inst_id = trigger_event.get("instance_id") if trigger_event else None
            entering = self.state.find_object(inst_id) if inst_id is not None else None
            n = max(0, int(getattr(entering, "power", 0) or 0))
        else:
            n = int(count)
        if n <= 0 or not player.library:
            return

        inspected = list(reversed(player.library[-n:]))

        def _matches(obj: GameObject) -> bool:
            if not filter_criteria:
                return True
            if filter_criteria.get("is_land"):
                if not obj.card.is_land:
                    return False
            if filter_criteria.get("is_creature"):
                if not obj.card.is_creature:
                    return False
            subtypes = filter_criteria.get("subtypes")
            if subtypes:
                norm_subtypes = {s.lower() for s in subtypes}
                has_changeling = "changeling" in obj.card.type_line.lower() or "changeling" in obj.intrinsic_keywords
                if not has_changeling:
                    _, _, sub = obj.card.type_line.lower().partition("—")
                    subs = {s.strip() for s in sub.split() if s.strip()}
                    if not (norm_subtypes & subs):
                        return False
            return True

        def _matches_all(obj: GameObject) -> bool:
            return _matches(obj) and (not criteria or card_query.matches(obj.card, criteria))

        candidates = [o for o in inspected if _matches_all(o)]
        rest_ids = [o.instance_id for o in inspected]

        if not candidates:
            if not decline_leaves_untouched:
                self._handle_rest_inspected(player, rest_ids, rest_destination)
            if else_specs:
                self._apply_effect_specs(list(else_specs), source)
            return

        pick_count = len(candidates) if max_picks == "all" else max(1, int(max_picks))
        self._request_choose_objects(
            player,
            candidates,
            action,
            count=pick_count,
            optional=optional,
            prompt=prompt,
            source=source,
            rest_ids=rest_ids,
            rest_destination=rest_destination,
            decline_leaves_untouched=decline_leaves_untouched,
            else_specs=else_specs,
            distinct_card_types=distinct_card_types,
        )
        if action == "exile_face_down_linked" and self.state.pending_choice:
            event = self.context.trigger_event or {}
            self.state.pending_choice["hideaway_incarnation"] = event.get(
                "hideaway_incarnation", getattr(source, "hideaway_incarnation", None),
            )
