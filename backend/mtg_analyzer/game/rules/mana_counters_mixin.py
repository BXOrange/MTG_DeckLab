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


def _counter_totals(target: Union[GameObject, Player]) -> dict[str, int]:
    """The ``{kind: amount}`` counters ``target`` currently carries.

    A `GameObject`'s own `counters` dict, or (PAR-2 — Price of Betrayal's
    "target artifact, creature, planeswalker, or **opponent**") a `Player`'s
    poison folded in alongside their generic `counters` dict: RULE 122.5
    lets "remove counters" name a player's poison/energy/experience just as
    freely as a permanent's +1/+1s, but `Player.poison` is its own attribute
    (`Player.add_counters`), not part of `Player.counters`.
    """
    if isinstance(target, Player):
        totals = dict(target.counters)
        if target.poison:
            totals["poison"] = target.poison
        return totals
    return dict(target.counters)



class ManaCountersMixin:
    """Resolve-time mana production, +1/+1-family counters, randomness (RULE 106.4/122/613)."""

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
    #: Labels for a narrowed mana-*type* offer. RULE 106.1b: colorless isn't
    #: a colour, so a plain "add one mana of any color" never offers {C} —
    #: but "any type that permanent produced" (Kinnan) can, since a Basalt
    #: Monolith produces exactly that.
    _MANA_TYPE_LABELS: dict[str, str] = {**_ANY_COLOR_LABELS, "C": "Farblos"}
    def add_mana_any_color(
        self, player: Player, colors: Optional[list[str]] = None, amount: int = 1
    ) -> None:
        """Open the interactive colour choice for a resolve-time "add one
        mana of any color" effect (RULE 106.4) — e.g. Deathrite Shaman's
        graveyard-exile ability, which targets and so can never be a
        `mana_abilities.py` mana ability at all (RULE 605.1a excludes any
        ability that requires a target), unlike an ordinary dual land's
        pre-declared tap-for-mana choice.

        ``colors`` narrows the offer to a specific set — Kinnan's "one mana
        of any type **that permanent produced**", where the menu is whatever
        the land or rock actually just made rather than all five colours.
        With a single option there is nothing to decide, so the mana is
        added outright; with none, nothing happens at all.

        ``amount`` (ENG-27, Carpet of Flowers' "add **X** mana of any one
        color") is how many of the *one* chosen colour to add — still a
        single colour decision, just not always a single mana of it.
        ``amount <= 0`` adds nothing and never opens a choice (an "any one
        color" ability whose count comes off the board, like Carpet of
        Flowers' target-dependent X, can resolve to zero real targets/count).

        Opens an `add_mana_any_color` `pending_choice`;
        `resolve_add_mana_any_color_choice` finishes it by adding
        ``amount`` mana of the chosen colour to ``player``'s pool.
        """
        offered = list(colors) if colors is not None else list(self._ANY_COLOR_LABELS)
        if not offered or amount <= 0:
            return
        if len(offered) == 1:
            self.add_mana(player, offered[0], amount)
            return
        self.state.pending_choice = {
            "kind": "add_mana_any_color",
            "player_id": player.id,
            "amount": amount,
            "prompt": "Farbe für die Manaerzeugung wählen",
            "options": [
                {"id": color, "label": self._MANA_TYPE_LABELS.get(color, color)}
                for color in offered
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
        offered = [o["id"] for o in choice.get("options") or []]
        color = answer if answer in offered else (offered[0] if offered else "W")
        self.add_mana(player, color, int(choice.get("amount", 1) or 1))
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

        The untap direction mirrors this exactly (`EventType.UNTAPPED`, MEC-
        43 round 4E, Mesmeric Orb): every genuine untap route — the untap
        step's own per-permanent loop, an ability's own ``{Q}``/"Untap ~"
        cost or effect, `TapEffect`'s ``untap=True`` mode — was widened to
        call this method instead of setting `GameObject.tapped` directly,
        precisely so this is the one place both transitions are observable.
        A zone-change reset (a fresh battlefield arrival, `reset_as_new_
        object`) still sets `tapped` directly and correctly fires neither
        event — RULE 400.7's new object was never tapped/untapped "before".
        """
        was_tapped = obj.tapped
        # RULE 122.1c: "If a permanent with a stun counter on it would become
        # untapped, instead remove a stun counter from it." A replacement on
        # every genuine untap route (this is the choke point) — the untap
        # step's per-permanent loop, a {Q}/"Untap ~" cost or effect,
        # `TapEffect(untap=True)`. The permanent stays tapped and no
        # `UNTAPPED` event fires, exactly as if the untap never happened.
        if (
            not tapped
            and was_tapped
            and obj.counters.get("stun", 0) > 0
        ):
            self.add_counters(obj, -1, "stun")
            return
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
        elif not tapped and was_tapped:
            self.state.fire_event(
                GameEvent(
                    EventType.UNTAPPED,
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
            # Recipient scoping for a "on a creature/permanent **you control**"
            # replacement (Hardened Scales/Branching Evolution/Kami of
            # Whispered Hopes) — the counters' *recipient*'s controller and
            # whether it's a creature, a different axis from the causer-scoped
            # ``source_controller_id`` above (Innkeeper's Talent).
            recipient_controller_id=obj.controller_id,
            recipient_is_creature=bool(getattr(obj, "is_creature", False)),
        )

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is None:
                return
            _place(resolved.get("amount", amount))
            # "if you put a counter on a creature this turn" (Lasting Tarfire)
            # — a per-turn history question no board scan can answer; record
            # the causer here, keyed by the same causer-scoped
            # ``source_controller_id`` the event already carries.
            if resolved.get("recipient_is_creature") and resolved.get("amount", 0) > 0:
                _scid = resolved.get("source_controller_id")
                if _scid is not None:
                    self.state.counter_placed_on_creature_this_turn.add(_scid)
            # "Whenever a -1/-1 counter is put on a creature, …" (Flourishing
            # Defenses) / "…on a permanent you control, …" (Hardened Scales-
            # adjacent triggered, not just replacement, consumers) — RULE
            # 122.5's own trigger family. `apply_replacements` only ever used
            # this event to compute the final amount; nothing broadcast it,
            # so `_collect_triggers` (a `state.fire_event` subscriber) could
            # never see a counter placement at all until now.
            self.state.fire_event(resolved)

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
            # A player recipient is never a creature; scoped-"you control"
            # counter replacements (Hardened Scales et al.) never apply to a
            # player anyway, but carry the fields for shape-consistency with
            # `add_counters`'s own COUNTER event.
            recipient_controller_id=player.id,
            recipient_is_creature=False,
        )

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is None:
                return
            _place(resolved.get("amount", amount))
            # See `add_counters`'s matching fix: broadcast so a "whenever a
            # player gets a poison/energy counter" trigger can actually fire.
            self.state.fire_event(resolved)

        self.apply_replacements(event, on_resolved=_finish)
    def bolster(
        self, player: Player, amount: int, source: Optional[GameObject] = None
    ) -> None:
        """"Bolster N" (RULE 701.39a): choose a creature with the least
        toughness among creatures ``player`` controls, then put N +1/+1
        counters on it. RULE 701.39a's tie clause — if two or more creatures
        tie for least toughness, ``player`` chooses one; if they control no
        creatures, bolster does nothing.

        Degenerate cases resolve without asking (the `RulesEngine.populate`
        idiom): no creatures, or a single least-toughness creature → place
        the counters straight away; a genuine tie → a `bolster`
        `pending_choice` (`resolve_bolster_choice`). The counters go on
        through `add_counters`, so RULE 616.1 doublers (Doubling Season) and
        RULE 122.5 "whenever a +1/+1 counter is put on ~" triggers apply.
        """
        if amount <= 0:
            return
        creatures = [
            obj
            for obj in self.state.battlefield
            if obj.controller_id == player.id and getattr(obj, "is_creature", False)
        ]
        if not creatures:
            return
        least = min(obj.toughness for obj in creatures)
        tied = [obj for obj in creatures if obj.toughness == least]
        if len(tied) == 1:
            self.add_counters(tied[0], amount, "+1/+1", source=source)
            return
        self.state.pending_choice = {
            "kind": "bolster",
            "player_id": player.id,
            "amount": amount,
            "source_id": source.instance_id if source is not None else None,
            "prompt": f"Verstärken {amount}: welche Kreatur mit der geringsten Widerstandskraft?",
            "options": [
                {"id": str(o.instance_id), "label": o.name, "instance_id": o.instance_id}
                for o in tied
            ],
        }
    def resolve_bolster_choice(self, instance_id: Optional[int]) -> None:
        """Answer a pending `bolster` tie-break: put the parked +1/+1
        counters on the chosen least-toughness creature. A missing/unknown
        answer defaults to the first tied creature — RULE 701.39a is
        mandatory once you control a creature (no "you may")."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "bolster":
            raise ValueError("no pending bolster choice to resolve")
        self.state.pending_choice = None
        offered = [opt["instance_id"] for opt in choice["options"]]
        chosen_id = instance_id if instance_id in offered else (offered[0] if offered else None)
        chosen = self._object_by_instance_id(chosen_id) if chosen_id is not None else None
        source_id = choice.get("source_id")
        source = self._object_by_instance_id(source_id) if source_id is not None else None
        if chosen is not None:
            self.add_counters(chosen, int(choice["amount"]), "+1/+1", source=source)
        self.check_state_based_actions()
    def blight(
        self, player: Player, amount: int, source: Optional[GameObject] = None,
        interactive: bool = True,
    ) -> None:
        """"Blight N" (Bloomburrow's reminder text: "put N -1/-1 counters on
        a creature you control"). The negative sibling of `bolster` — but the
        creature is ``player``'s free choice (not least-toughness), so it
        opens a `blight` `pending_choice` whenever they control 2+ creatures.

        Degenerate cases resolve without asking (the `bolster`/`populate`
        idiom): no creatures → nothing (like a cost that can't be paid);
        exactly one → the counters go straight on it. Placed through
        `add_counters` (kind ``"-1/-1"``), so RULE 122.5 "whenever a -1/-1
        counter is put on ~" triggers and the RULE 704.5q +1/-1 annihilation
        SBA all apply.

        ``interactive=False`` (PAR-29 — "Blight N" paid as a *cost*, where
        payment is synchronous and can't pause for a chooser): auto-pick the
        creature with the highest toughness, then highest power — the
        least-self-harm pick, the same "auto-pick to minimise loss"
        documented simplification `collect_evidence` uses.
        """
        if amount <= 0:
            return
        creatures = [
            obj
            for obj in self.state.battlefield
            if obj.controller_id == player.id and getattr(obj, "is_creature", False)
        ]
        if not creatures:
            return
        if len(creatures) == 1:
            self.add_counters(creatures[0], amount, "-1/-1", source=source)
            return
        if not interactive:
            victim = max(
                creatures,
                key=lambda o: (getattr(o, "toughness", 0) or 0, getattr(o, "power", 0) or 0),
            )
            self.add_counters(victim, amount, "-1/-1", source=source)
            return
        self.state.pending_choice = {
            "kind": "blight",
            "player_id": player.id,
            "amount": amount,
            "source_id": source.instance_id if source is not None else None,
            "prompt": f"Verkümmern {amount}: auf welche Kreatur (−1/−1-Marken)?",
            "options": [
                {"id": str(o.instance_id), "label": o.name, "instance_id": o.instance_id}
                for o in creatures
            ],
        }
    def resolve_blight_choice(self, instance_id: Optional[int]) -> None:
        """Answer a pending `blight` choice: put the parked -1/-1 counters on
        the chosen creature you control. A missing/unknown answer defaults to
        the first offered creature (blight has no "you may" once you control
        one — its optionality lives in the "you may blight N" wrapper, not
        here)."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "blight":
            raise ValueError("no pending blight choice to resolve")
        self.state.pending_choice = None
        offered = [opt["instance_id"] for opt in choice["options"]]
        chosen_id = instance_id if instance_id in offered else (offered[0] if offered else None)
        chosen = self._object_by_instance_id(chosen_id) if chosen_id is not None else None
        source_id = choice.get("source_id")
        source = self._object_by_instance_id(source_id) if source_id is not None else None
        if chosen is not None:
            self.add_counters(chosen, int(choice["amount"]), "-1/-1", source=source)
        self.check_state_based_actions()
    def blight_possible(self, player: Player) -> bool:
        """Whether ``player`` could pay a "Blight N" cost right now (PAR-29) —
        i.e. controls at least one creature to put the -1/-1 counters on."""
        return any(
            obj.controller_id == player.id and getattr(obj, "is_creature", False)
            for obj in self.state.battlefield
        )
    def earthbend(
        self, land: Optional[GameObject], amount: int, source: Optional[GameObject] = None
    ) -> None:
        """"Earthbend N" (RULE 701.66 — Avatar: The Last Airbender): the
        target land ``land`` you control **becomes a 0/0 creature with haste
        that's still a land**, then gets N +1/+1 counters.

        The animation is two `rest_of_game` floating statics scoped to this
        one object (`type_change` add-Creature-0/0 in layer 4/7b, plus a
        layer-6 `grant_keyword` haste) — a genuine RULE 611 continuous
        effect, so RULE 611.2c ends it automatically if the land leaves (the
        layer engine only visits battlefield permanents, and a land that
        returns is a new object the `object_ids` list no longer names).
        The +1/+1 counters go on through `add_counters` (RULE 122.5 triggers,
        RULE 704.5f/q SBAs apply).

        **Documented simplification:** the reminder text's third sentence —
        "When it dies or is exiled, return it to the battlefield tapped." —
        is not modeled (an edge case for solo practice; the land just goes
        to the graveyard/exile like any other permanent).
        """
        from ..effects import EffectRegistry  # function-scoped: effects↔rules cycle

        if land is None or land not in self.state.battlefield:
            return
        for spec_type, params in (
            # `_added_types`/keyword sets are lowercase (`GameObject.
            # is_creature`, `combat.keywords_of`).
            ("type_change", {"add_types": ["creature"], "power": 0, "toughness": 0}),
            ("grant_keyword", {"keywords": ["haste"]}),
        ):
            ability = EffectRegistry.create(spec_type, dict(params))
            if not isinstance(ability, StaticAbility):
                continue
            ability.source = source
            ability.timestamp = self.state.next_timestamp()
            ability.duration = "rest_of_game"
            ability.duration_data = {"player_id": getattr(source, "controller_id", None)}
            ability.affects = "objects"
            ability.object_ids = [land.instance_id]
            self.state.floating_statics.append(ability)
        if amount > 0:
            self.add_counters(land, amount, "+1/+1", source=source)
        self.check_state_based_actions()
        # RULE 701.6x: the earthbend is complete — fire EventType.BENT so a
        # "whenever you earthbend" trigger (Avatar Aang) sees it.
        bender_id = getattr(source, "controller_id", None)
        bender = self.state.player_by_id(bender_id) if bender_id else None
        if bender is not None:
            self.record_bend(bender, "earthbend", amount, source=source)
    def request_remove_counters_choice(
        self, target: Union[GameObject, Player], max_count: int, chooser: Player
    ) -> None:
        """Open the "how many counters to remove" choice for ``target``.

        A no-op if ``target`` carries no counters at all — nothing to
        choose, same as an empty-eligible `request_search`. ``target`` may
        be a `Player` (PAR-2's "…or opponent" compound target) as freely as
        a permanent — see `_counter_totals`.
        """
        total = sum(v for v in _counter_totals(target).values() if v > 0)
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
    def _remove_target_counters(self, target: Union[GameObject, Player], amount: int, kind: str) -> None:
        """Remove ``-amount`` counters of ``kind`` from ``target`` — routes a
        `Player` target (PAR-2) through `add_player_counters` instead of the
        permanent-only `add_counters`."""
        if isinstance(target, Player):
            self.add_player_counters(target, amount, kind)
        else:
            self.add_counters(target, amount, kind)

    def _continue_remove_counters(self, target: Union[GameObject, Player], remaining: int) -> None:
        totals = _counter_totals(target)
        kinds = sorted(k for k, v in totals.items() if v > 0)
        if not kinds or remaining <= 0:
            return
        if len(kinds) == 1:
            take = min(remaining, totals.get(kinds[0], 0))
            self._remove_target_counters(target, -take, kinds[0])
            return
        self._pending_remove_counters_target = target
        self._pending_remove_counters_remaining = remaining
        self.state.pending_choice = {
            "kind": "remove_counters_kind",
            # RULE 101.4c: with no instruction otherwise, the choice is made
            # by whoever controls the target — a player controls themselves.
            "player_id": target.controller_id if isinstance(target, GameObject) else target.id,
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
        self._remove_target_counters(target, -1, kind)
        if remaining > 1:
            self._continue_remove_counters(target, remaining - 1)
