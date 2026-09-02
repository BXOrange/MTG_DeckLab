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
    def _look_at_top(
        self, player: Player, count: int, kind: str, source: Optional["GameObject"] = None
    ) -> None:
        """The shared body of `scry`/`surveil`: fire the keyword's event, then
        open its decision.

        The event fires *before* the decision, so "whenever you scry/surveil"
        triggers see it at the moment the player looks — the same point the
        old non-interactive stubs fired it, and the point RULE 603.2 means.
        An empty library is still a scry/surveil of 0: the event fires (with
        ``count`` 0) and nothing is asked.
        """
        looked = player.library[-count:] if count > 0 else []
        self.state.fire_event(
            GameEvent(
                self._LOOK_TOP_KINDS[kind]["event"], player_id=player.id, count=len(looked)
            )
        )
        if not looked:
            return
        # Top card first, which is the order a player reads them in.
        remaining = [obj.instance_id for obj in reversed(looked)]
        source_name = source.name if source is not None else None
        self.state.pending_choice = self._look_top_choice(
            player, kind, "away", remaining, [], [], source_name
        )
    def explore(self, permanent: GameObject, player: Optional[Player] = None) -> None:
        """RULE 701.44a: ``permanent``'s controller reveals the top card of
        their library. If a land is revealed, it goes to that player's hand;
        otherwise a +1/+1 counter is put on ``permanent`` and the player may
        put the revealed card into their graveyard (an interactive
        ``explore_bin`` choice — the only branch that pauses).

        RULE 701.44b: the `EventType.EXPLORED` event fires once the whole
        process is complete — inline here when nothing was revealed or a land
        went to hand, and from `resolve_explore_bin_choice` otherwise — even
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
        self.state.pending_choice = {
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
        }
    def _fire_explored(
        self, inst: Optional[str], controller_id: Optional[str], *, found_land: bool
    ) -> None:
        self.state.fire_event(GameEvent(
            EventType.EXPLORED, instance_id=inst,
            controller_id=controller_id, found_land=found_land,
        ))
    def resolve_explore_bin_choice(self, to_graveyard: bool = False) -> None:
        """Finish an explore (RULE 701.44a): ``to_graveyard`` puts the
        revealed nonland card into its owner's graveyard; otherwise it stays
        on top of the library. Fires `EventType.EXPLORED` afterward (701.44b).
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "explore_bin":
            raise ValueError("no pending explore to resolve")
        player = self.state.player_by_id(choice["player_id"])
        self.state.pending_choice = None

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
    def _look_top_choice(
        self,
        player: Player,
        kind: str,
        phase: str,
        remaining: list[int],
        away: list[int],
        top: list[int],
        source_name: Optional[str] = None,
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
        return {
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
    def resolve_scry_choice(self, instance_id: Optional[int]) -> None:
        """Answer a pending `scry` decision (RULE 701.18)."""
        self._resolve_look_top_choice("scry", instance_id)
    def resolve_surveil_choice(self, instance_id: Optional[int]) -> None:
        """Answer a pending `surveil` decision (RULE 701.31)."""
        self._resolve_look_top_choice("surveil", instance_id)
    def resolve_scroll_rack_choice(self, instance_id: Optional[int]) -> None:
        """Answer a pending Scroll Rack ordering decision (MEC-43 round 4F)."""
        self._resolve_look_top_choice("scroll_rack", instance_id)
    def _resolve_look_top_choice(self, kind: str, instance_id: Optional[int]) -> None:
        """Answer one step of a `scry`/`surveil` decision.

        In the ``away`` phase a card id sends that card to the bottom (scry)
        or the graveyard (surveil) and re-asks; declining ends that phase and
        moves on to ordering whatever is left. In the ``order`` phase a card
        id places that card next from the top; declining there keeps the rest
        in the order they already were and finishes. Either phase also
        finishes on its own as soon as there is nothing left to decide.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != kind:
            raise ValueError(f"no pending {kind} choice to resolve")
        player = self.state.player_by_id(choice["player_id"])
        remaining: list[int] = list(choice["remaining"])
        away: list[int] = list(choice["away"])
        top: list[int] = list(choice["top"])
        phase = choice["phase"]
        source_name = choice.get("source_name")

        if instance_id is None:
            if phase == "order":
                self._finish_look_top(player, kind, away, top + remaining)
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
            self._finish_look_top(player, kind, away, top + remaining)
            return
        self.state.pending_choice = self._look_top_choice(
            player, kind, phase, remaining, away, top, source_name
        )
    def _finish_look_top(
        self, player: Player, kind: str, away: list[int], top: list[int]
    ) -> None:
        """Put the looked-at cards where they were sent.

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
        self.state.pending_choice = self._look_top_choice(
            player, "scroll_rack", "order", list(instance_ids), [], [], source_name
        )

    def look_top_select(
        self,
        player: Player,
        count: int,
        select_count: int,
        rest_destination: str,
        rest_order: Optional[str] = None,
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
        """
        looked = player.library[-count:] if count > 0 else []
        if not looked:
            return
        remaining = [obj.instance_id for obj in reversed(looked)]  # top of library first
        select_count = max(0, min(select_count, len(remaining)))
        if select_count <= 0:
            self._advance_look_top_select(player, remaining, [], rest_destination, rest_order)
            return
        self.state.pending_choice = self._look_top_select_choice(
            player, "select", remaining, [], select_count, [], rest_destination, rest_order,
        )

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
    ) -> dict[str, Any]:
        """Build one step of the serializable `look_top_select` decision —
        ``phase`` is ``"select"`` (choosing the hand cards, no decline: RULE
        701.19's "put M of them" is mandatory, not "up to") or ``"order"``
        (placing what's left one at a time, decline keeps the rest in
        their looked-at order, same convention as `_look_top_choice`)."""
        looked = [(iid, self._object_by_instance_id(iid)) for iid in remaining]
        options = [
            {"id": str(iid), "label": obj.name, "instance_id": iid}
            for iid, obj in looked
            if obj is not None
        ]
        if phase == "order":
            options.append({"id": "decline", "label": "Reihenfolge behalten"})
            prompt = "Wähle die nächste Karte für die Bibliothek"
        else:
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
            "prompt": prompt,
            "options": options,
        }

    def resolve_look_top_select_choice(self, instance_id: Optional[int]) -> None:
        """Answer one step of a `look_top_select` decision — see
        `_look_top_select_choice` for the two phases."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "look_top_select":
            raise ValueError("no pending look_top_select choice to resolve")
        player = self.state.player_by_id(choice["player_id"])
        remaining: list[int] = list(choice["remaining"])
        selected: list[int] = list(choice["selected"])
        select_count: int = choice["select_count"]
        ordered: list[int] = list(choice["ordered"])
        rest_destination: str = choice["rest_destination"]
        rest_order: Optional[str] = choice["rest_order"]
        phase = choice["phase"]

        if phase == "select":
            if instance_id is None or instance_id not in remaining:
                raise ValueError(f"{instance_id} is not a legal choice")
            remaining.remove(instance_id)
            selected.append(instance_id)
            if len(selected) < select_count and remaining:
                self.state.pending_choice = self._look_top_select_choice(
                    player, "select", remaining, selected, select_count, ordered,
                    rest_destination, rest_order,
                )
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
        self.state.pending_choice = self._look_top_select_choice(
            player, "order", remaining, selected, select_count, ordered,
            rest_destination, rest_order,
        )

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
            self.state.pending_choice = self._look_top_select_choice(
                player, "order", remaining, selected, len(selected), [],
                rest_destination, rest_order,
            )
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
        else:  # "library_bottom"
            for iid in rest:
                obj = objects.get(iid)
                if obj is not None:
                    player.library.insert(0, obj)

    def _has_search_exemption(self, player: Player) -> bool:
        """RULE 116.2a (MEC-35, Leonin Arbiter): has ``player`` paid {2}
        this turn to ignore a search prohibition? See `GameState.
        search_exempt_until_turn`'s own docstring."""
        return self.state.search_exempt_until_turn.get(player.id) == self.state.turn_number

    def is_search_prohibited_for(self, player: Player) -> bool:
        """Whether ``player`` is currently barred from searching at all
        (RULE 701.19a — Stranglehold's ``scope="opponents"``/Leonin
        Arbiter's ``scope="all"``), accounting for this turn's RULE 116.2a
        exemption if any. The same check `request_search`'s own guard
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
        attach_to_creature_you_control: bool = False,
        remember_source_id: Optional[int] = None,
        total_mana_value_budget: Optional[int] = None,
        chooser: Optional[Player] = None,
        share_land_type: bool = False,
        then_specs_if_none: Optional[list[dict]] = None,
        source: Optional[GameObject] = None,
        track_exiled_with: bool = False,
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
        session surfaces it, and `resolve_search_choice` finishes the search
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
                or obj.card.converted_mana_cost <= total_mana_value_budget
            )
        ]
        if not eligible or count <= 0:
            if "library" in zones and not exile_rest:
                self.shuffle_library(player)
            # "…if you don't put a card … this way, <body>." (The Vast
            # Scrier) — nothing eligible counts as "didn't".
            self._apply_effect_specs(list(then_specs_if_none or []), source)
            return
        self.state.pending_choice = self._search_choice(
            player, criteria, destination, count, optional, found=[],
            zones=zones, destinations=destinations, exile_rest=exile_rest,
            extra_counters=extra_counters, destination_if=destination_if,
            attach_to_creature_you_control=attach_to_creature_you_control,
            remember_source_id=remember_source_id,
            total_mana_value_budget=total_mana_value_budget,
            chooser=chooser,
            share_land_type=share_land_type,
            then_specs_if_none=then_specs_if_none,
            then_source_id=getattr(source, "instance_id", None),
            track_exiled_with=track_exiled_with,
        )

    def request_intuition(
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
        `request_search`, whose single ``destination`` has no way to
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
        self.state.pending_choice = self._intuition_search_choice(
            searcher, chooser_id, count, [], source, search_optional, distinct_names,
            chosen_count, chosen_destination, rest_destination,
        )

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

    def resolve_intuition_search_choice(self, instance_id: Optional[int]) -> None:
        """Answer one pick of the search phase — ``None`` (only legal when
        ``search_optional``, RULE 701.19's "up to") stops early; otherwise
        mandatory (Intuition's own plain "search for `<count>` cards")."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "intuition_search":
            raise ValueError("no pending intuition search to resolve")
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
                self.state.pending_choice = self._intuition_search_choice(
                    searcher, choice["chooser_id"], choice["count"], found,
                    self._object_by_instance_id(choice["source_id"]),
                    choice.get("search_optional", False), choice.get("distinct_names", False),
                    choice["chosen_count"], choice["chosen_destination"], choice["rest_destination"],
                )
                return
        chooser = self.state.player_by_id(choice["chooser_id"])
        self.state.pending_choice = self._intuition_choose_choice(
            searcher, chooser, found, [], choice["chosen_count"],
            choice["chosen_destination"], choice["rest_destination"],
        )

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

    def resolve_intuition_choose_choice(self, instance_id: int) -> None:
        """The opponent's mandatory pick (RULE 601.2c — "chooses `<N>`" has
        no decline): re-opens until ``chosen_count`` are picked, the same
        "one at a time" shape `request_choose_objects` uses. Once done, the
        picked cards go to ``chosen_destination``, the rest to
        ``rest_destination``, then the library is shuffled."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "intuition_choose":
            raise ValueError("no pending intuition choice to resolve")
        found = list(choice["found"])
        if instance_id not in found or instance_id in choice["picked"]:
            raise ValueError(f"{instance_id} is not a legal choice")
        picked = list(choice["picked"]) + [instance_id]
        searcher = self.state.player_by_id(choice["searcher_id"])
        chooser = self.state.player_by_id(choice["player_id"])
        if len(picked) < choice["chosen_count"] and len(picked) < len(found):
            self.state.pending_choice = self._intuition_choose_choice(
                searcher, chooser, found, picked, choice["chosen_count"],
                choice["chosen_destination"], choice["rest_destination"],
            )
            return
        self.state.pending_choice = None
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
        other, but `request_search` never shuffles for it and never fires
        `LIBRARY_SEARCHED`, both of which are keyed to ``"library"``."""
        objs: list[GameObject] = []
        if "library" in zones:
            # RULE 701.19a-adjacent narrowing: "If an opponent would search
            # a library, that player searches the top N cards of that
            # library instead." (Aven Mindcensor) — take the smallest N
            # among every such grant that isn't ``player``'s own, mirroring
            # `GrantSearchProhibitedEffect`'s own scan just above in
            # `request_search`. `player.library[-n:]` since the list end is
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
                spent_mana_value += picked.card.converted_mana_cost

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
            and (remaining_budget is None or obj.card.converted_mana_cost <= remaining_budget)
            and _shares_land_type(obj, found_objs, share_land_type)
        ]
        if not declined and remaining > 0 and still_eligible:
            self.state.pending_choice = self._search_choice(
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
                then_specs_if_none=choice.get("then_specs_if_none"),
                then_source_id=choice.get("then_source_id"),
                track_exiled_with=choice.get("track_exiled_with", False),
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
            attach_to_creature_you_control=choice.get("attach_to_creature_you_control", False),
            remember_source_id=choice.get("remember_source_id"),
            chooser_id=chooser_id,
            track_exiled_with=choice.get("track_exiled_with", False),
            track_source_id=choice.get("then_source_id"),
        )
        # "…if you don't put a card … this way, <body>." (The Vast Scrier) —
        # the search finished and nothing was picked.
        if not found and choice.get("then_specs_if_none"):
            self._apply_effect_specs(
                list(choice["then_specs_if_none"]),
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
        then_specs_if_none: Optional[list[dict]] = None,
        then_source_id: Optional[int] = None,
        track_exiled_with: bool = False,
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
            and (remaining_budget is None or obj.card.converted_mana_cost <= remaining_budget)
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
            "player_id": (chooser or player).id,
            "library_owner_id": player.id,
            "destination": destination,
            "destinations": list(destinations) if destinations else None,
            "zones": zones,
            "exile_rest": exile_rest,
            "extra_counters": dict(extra_counters) if extra_counters else None,
            "destination_if": [dict(rule) for rule in destination_if] if destination_if else None,
            "attach_to_creature_you_control": bool(attach_to_creature_you_control),
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
        to_library = any(d in ("library_top", "library_bottom") for d in effective_destinations)
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
                # `request_search`'s docstring for why); silently stays
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
        if destination in ("battlefield", "battlefield_tapped", "battlefield_attacking"):
            obj.summoning_sick = True
            obj.tapped = destination != "battlefield"
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
            if destination == "battlefield_attacking":
                # RULE 508.4: "…onto the battlefield tapped **and attacking**"
                # (Preeminent Captain, Kaalia of the Vast). The tap is set
                # above; this puts it into the current combat.
                self.put_onto_battlefield_attacking(obj)
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
    def request_impulsive_look(
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
        }
        self.state.pending_choice = {
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
            self._apply_impulsive_look_miss_branch(chosen_id, pending_else)
            return
        for obj in exiled:
            is_hit = obj.instance_id == chosen_id
            destination = choice["hit_destination"] if is_hit else choice["miss_destination"]
            player.remove_from_zone(obj, Zone.EXILE)
            self._put_searched_card(player, obj, destination)
            if is_hit:
                self._apply_impulsive_look_hit_grants(obj, choice.get("hit_grant_keywords"))
        self._apply_impulsive_look_miss_branch(chosen_id, pending_else)

    def _apply_impulsive_look_miss_branch(
        self, chosen_id: Optional[int], pending_else: Optional[dict]
    ) -> None:
        """"If you don't put a card onto the battlefield this way, <body>."
        (The Joiner of Cats) — run the else-branch specs when the look placed
        nothing (the player declined; the nothing-eligible case is handled
        inline in `request_impulsive_look`)."""
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
        self.state.temp_play_permissions[obj.instance_id] = self.state.turn_number
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
    def request_reveal_top_hand_lose_life_loop(self, player: Player) -> None:
        """"Reveal the top card of your library and put that card into
        your hand. You lose life equal to its mana value. You may repeat
        this process any number of times." (Ad Nauseam, MEC-41) — the
        engine's second **open-ended**, self-re-opening loop (see
        `request_look_top_pay_life_loop`'s own docstring for the first),
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
        self.state.pending_choice = {
            "kind": "reveal_top_hand_lose_life_loop",
            "player_id": player.id,
            "prompt": f"{top.name} (Manawert {top.card.converted_mana_cost}) "
                      "aufdecken, auf die Hand nehmen und entsprechend Leben "
                      "verlieren?",
            "looking_at": [{"instance_id": top.instance_id, "name": top.name}],
            "options": [
                {"id": "again", "label": "Fortsetzen"},
                {"id": "decline", "label": "Aufhören"},
            ],
        }
    def resolve_reveal_top_hand_lose_life_loop_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `reveal_top_hand_lose_life_loop` choice — take
        the top card (reveal is purely informational, same idiom every
        other reveal effect in this engine uses) or stop."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "reveal_top_hand_lose_life_loop":
            raise ValueError("no pending reveal-top-hand-lose-life choice to resolve")
        self.state.pending_choice = None
        if answer != "again":
            return
        player = self.state.player_by_id(choice["player_id"])
        if not player.library:
            return
        top = player.library.pop()
        top.zone = Zone.HAND
        player.hand.append(top)
        self.lose_life(player, top.card.converted_mana_cost, cause="effect")
        self.request_reveal_top_hand_lose_life_loop(player)
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
        self.state.pending_choice = {
            "kind": "tainted_pact",
            "player_id": player.id,
            "prompt": f"{obj.name} exiliert — auf die Hand nehmen oder weiter suchen?",
            "options": [
                {"id": "take", "label": f"{obj.name} auf die Hand nehmen"},
                {"id": "continue", "label": "Weiter exilieren"},
            ],
        }
    def resolve_tainted_pact_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `tainted_pact` choice (Tainted Pact) — ``"take"``
        (or any unrecognized/missing answer, the safe default) keeps the
        just-exiled card; ``"continue"`` resumes `exile_until_duplicate_name`
        with the same "names seen so far" set, risking a duplicate.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "tainted_pact":
            raise ValueError("no pending tainted-pact choice to resolve")
        self.state.pending_choice = None
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
        self.state.pending_choice = {
            "kind": "transmute_sacrifice",
            "player_id": player.id,
            "prompt": "Opfere ein Artefakt (Transmute Artifact)",
            "options": [
                {"id": str(o.instance_id), "label": o.name, "instance_id": o.instance_id}
                for o in artifacts
            ],
        }
    def resolve_transmute_sacrifice_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `transmute_sacrifice` choice: which of the
        player's own artifacts to sacrifice for Transmute Artifact."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "transmute_sacrifice":
            raise ValueError("no pending transmute-sacrifice choice to resolve")
        self.state.pending_choice = None
        player = self._pending_transmute_player
        self._pending_transmute_player = None
        if player is None or answer is None:
            return
        victim = self._resolve_choice_option(choice["options"], str(answer))
        if victim is not None:
            self._transmute_artifact_sacrifice(player, victim)
    def _transmute_artifact_sacrifice(self, player: Player, victim: GameObject) -> None:
        sacrificed_mv = victim.card.converted_mana_cost
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
        self.state.pending_choice = {
            "kind": "transmute_search",
            "player_id": player.id,
            "prompt": "Durchsuche deine Bibliothek nach einer Artefaktkarte (Transmute Artifact)",
            "options": [
                {"id": str(o.instance_id), "label": o.name, "instance_id": o.instance_id}
                for o in eligible
            ]
            + [{"id": "decline", "label": "Nichts wählen"}],
        }
    def resolve_transmute_search_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `transmute_search` choice: the artifact card
        found (or a decline). A found card whose mana value is at most the
        sacrificed artifact's own goes straight to the battlefield; a
        pricier one opens the "pay the difference" choice instead."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "transmute_search":
            raise ValueError("no pending transmute-search choice to resolve")
        self.state.pending_choice = None
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
        found_mv = found.card.converted_mana_cost
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
        self.state.pending_choice = {
            "kind": "transmute_pay_x",
            "player_id": player.id,
            "prompt": f"{{{difference}}} bezahlen, um {found.name} ins Spiel zu bringen?",
            "options": [
                {"id": "pay", "label": f"{{{difference}}} bezahlen"},
                {"id": "decline", "label": "Nicht bezahlen"},
            ],
        }
    def resolve_transmute_pay_x_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `transmute_pay_x` choice: pay the mana-value
        difference to put the found artifact onto the battlefield, or let
        it go to its owner's graveyard instead."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "transmute_pay_x":
            raise ValueError("no pending transmute-pay-x choice to resolve")
        self.state.pending_choice = None
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
