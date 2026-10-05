"""Library search, look/exile/cast windows, mana, exchanges, and advanced actions."""
from __future__ import annotations

from .core import GameEffect
from ._runtime import install, register

install(globals())

class IntuitionEffect(GameEffect):
    """"Search your library for `<count>` cards and reveal them. Target
    opponent chooses one. Put that card into your hand and the rest into
    your graveyard. Then shuffle." (Intuition) — see
    `RulesEngine._request_intuition` for the two-phase shape (the searcher
    picks the cards, then the *targeted opponent* — a real RULE 115 target,
    not the searcher — picks from among them).

    Generalized (MEC-41, Gifts Ungiven) via the same params `request_
    intuition` gained — ``search_optional``/``distinct_names`` shape the
    *searcher's* phase, ``chosen_count``/``chosen_destination``/
    ``rest_destination`` the *chooser's* one. All default to Intuition's
    own original fixed shape, unchanged.
    """

    def __init__(
        self, count: int = 3, source: Optional["GameObject"] = None,
        search_optional: bool = False, distinct_names: bool = False,
        chosen_count: int = 1, chosen_destination: str = "hand",
        rest_destination: str = "graveyard",
    ) -> None:
        super().__init__(source)
        self.count = count
        self.search_optional = search_optional
        self.distinct_names = distinct_names
        self.chosen_count = chosen_count
        self.chosen_destination = chosen_destination
        self.rest_destination = rest_destination
        self.target_spec = TargetSpec(kind="opponent")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        searcher = _controller_of(self.source, context)
        chooser = targets[0] if targets else None
        chooser_id = getattr(chooser, "id", None)
        if searcher is None or chooser_id is None:
            return
        context._request_intuition(
            searcher, chooser_id, self.count, self.source,
            search_optional=self.search_optional, distinct_names=self.distinct_names,
            chosen_count=self.chosen_count, chosen_destination=self.chosen_destination,
            rest_destination=self.rest_destination,
        )


class SearchLibraryEffect(GameEffect):
    """Search the controller's library for a card (RULE 701.19), tutors.

    The search is parameterized on two independent axes so one effect covers
    the whole tutor family (Demonic Tutor, Rampant Growth, Cultivate, Vampiric
    Tutor, Entomb, …):

    * ``criteria`` — *what* to look for, as pure data understood by
      `models.cards.card_query`: ``""`` for "a card", a type string like
      ``"Creature"``, or a dict like ``{"type": ["Plains", "Island"]}`` /
      ``{"basic": True}`` / ``{"type": "Creature", "max_mana_value": 3}``.
    * ``destination`` — *where* the found card goes: ``"hand"`` (default),
      ``"battlefield"``, ``"battlefield_tapped"``, ``"library_top"``,
      ``"library_bottom"``, ``"graveyard"``, ``"exile"``, ``"cast_free"``
      (casts it immediately, Sunforger-shaped), or ``"exile_free_cast"``
      (exiles it with a *standing* "you may cast it without paying its
      mana cost" permission instead — Bring to Light, MEC-41).
    * ``count`` — how many cards (search for "up to N"); the choice is
      offered one card at a time.
    * ``zones`` — *where* to look: ``["library"]`` (default, RULE 701.19)
      or ``["library", "graveyard"]``/``["graveyard"]`` for "search your
      library and/or graveyard" (backgrounds/Lurrus-shaped).
    * ``destinations`` — an optional per-found-card override list,
      positional against the picks, for a split destination ("put one onto
      the battlefield tapped and the other into your hand" —
      Cultivate/Kodama's Reach); ``destination`` remains the fallback.
    * ``destination_if`` — a *conditional* override instead of a positional
      one: ``[{"criteria": {"type": "Land"}, "destination":
      "battlefield_tapped"}]`` is Archdruid's Charm's "put it onto the
      battlefield tapped if it's a land card. Otherwise, put it into your
      hand." Which branch applies depends on the card the player actually
      found, so it can only be decided once the search is answered.
    * ``exile_rest`` — once the search finishes, exile every remaining
      criteria-matching card still in ``zones`` and skip the shuffle
      entirely (Doomsday-shaped).

    Because *which* card is a player choice, this doesn't move a card itself
    — it asks the engine to open a choice (`GameContext._request_search`); the
    chosen card(s) are moved to their destination(s) and the library
    shuffled (unless ``exile_rest``) when the player answers.

    ``mana_value_from`` makes the criteria's mana-value bound *dynamic*
    rather than printed: ``{"source": "sacrificed_cost", "plus": 2, "cmp":
    "le"}`` is Eldritch Evolution's "with mana value X or less, where X is 2
    plus the sacrificed creature's mana value"; ``"cmp": "eq"`` is Neoform's
    exact "equal to 1 plus …". The base value is read off the spell object's
    own `GameObject.sacrificed_cost_mana_value`, stamped when the RULE
    601.2b additional cost was paid — `StackItem.x` can't carry it (it only
    ever threads an *announced* {X}). ``{"source": "count_selector",
    "count_selector": "lands_you_control"}`` (MEC-43 round 3, Beseech the
    Queen's "mana value less than or equal to the number of lands you
    control") reads the base off a live board count instead
    (`continuous.count_selector`, the same whitelisted vocabulary a
    characteristic-defining P/T uses) — evaluated fresh when the search
    opens, not cached from announcement, since RULE 601.2c legality is
    checked at the *search*'s own resolution. Merged into ``criteria`` at
    resolution time as ``max_mana_value``/``mana_value``, so
    `models.cards.card_query` needs no dynamic vocabulary of its own.

    ``type_restriction`` is accepted as a deprecated alias for a string
    ``criteria`` so older fixtures keep working.
    """

    def __init__(
        self,
        criteria: Any = "",
        destination: str = "hand",
        count: int = 1,
        optional: bool = True,
        player: Any = None,
        source: Optional["GameObject"] = None,
        type_restriction: Optional[str] = None,
        zones: Optional[list[str]] = None,
        destinations: Optional[list[str]] = None,
        exile_rest: bool = False,
        mana_value_from: Optional[dict[str, Any]] = None,
        extra_counters: Optional[dict[str, Any]] = None,
        destination_if: Optional[list[dict[str, Any]]] = None,
        attach_to_creature_you_control: bool = False,
        remember: bool = False,
        total_mana_value_budget: Optional[int] = None,
        player_from_target: bool = False,
        share_land_type: bool = False,
        track_exiled_with: bool = False,
        untap_if_lands_at_least: Optional[int] = None,
        then_specs: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        super().__init__(source)
        #: "…put it onto the battlefield tapped, then shuffle. Then if you
        #: control N or more lands, untap that land." (Fabled Passage) — a
        #: conditional, applied to the just-fetched land by
        #: `RulesEngine._finish_search` right after it reaches the
        #: battlefield. Only meaningful with ``destination=
        #: "battlefield_tapped"``; the land counts itself in the total
        #: (it has already entered when the test is made).
        self.untap_if_lands_at_least = untap_if_lands_at_least
        #: "…exile them, then incubate 2 **that many times**." (Phyrexian
        #: Incubator) — with ``destination="exile"``, appends every card
        #: this search exiles to the source's `GameObject.exiled_with_ids`,
        #: so a later `create_token` with ``count_selector=
        #: "exiled_with_count"`` in the same effect list can size itself off
        #: the count *after* the search's RULE 608.2 pending-choice
        #: suspension (the list lives on the permanent, not the resolution
        #: `GameContext`). Same accumulator `ExileEffect.track_exiled_with`
        #: and `_request_choose_objects` already write.
        self.track_exiled_with = bool(track_exiled_with)
        #: "...basic land cards **that share a land type**." (Myriad
        #: Landscape, MEC-43 round 3) — a cross-pick constraint on a
        #: multi-card search; see `RulesEngine._request_search`'s own
        #: docstring for how it's enforced round by round.
        self.share_land_type = share_land_type
        #: "Search **target opponent's** library for a card…" (Praetor's
        #: Grasp, MEC-42) — ``player`` becomes whichever player this
        #: ability's own RULE 115 target resolved to (the library that gets
        #: searched/shuffled and stays the found card's owner), while the
        #: *chooser* — who actually answers the search — stays this
        #: effect's own controller, via `RulesEngine._request_search`'s
        #: ``chooser`` param. Distinct from every other ``player`` sentinel
        #: above (``"previous_target_controller"`` etc.), which all still
        #: make the target both the searcher *and* the one who answers.
        self.player_from_target = player_from_target
        if player_from_target:
            self.target_spec = TargetSpec(kind="opponent", description="Gegner")
        #: "…for any number of creature cards with **total** mana value 6
        #: or less…" (Protean Hulk, MEC-12) — a running budget shared
        #: across the *whole* multi-pick search, unlike `criteria`'s own
        #: ``max_mana_value`` (a fixed per-card cap): each round's own
        #: eligible pool additionally excludes any card whose mana value
        #: would push the sum of everything picked so far over this total.
        #: See `RulesEngine._request_search`'s own docstring for how the
        #: running total is threaded through the choice loop.
        self.total_mana_value_budget = total_mana_value_budget
        #: "Exile a card from a graveyard. [...] the exiled card." (Cemetery
        #: Gatekeeper) — `ExileEffect.remember`'s own sibling for a search-
        #: shaped exile: stamps the found card's `instance_id` onto this
        #: ability's own source (`GameObject.linked_exile_id`) once the
        #: player's pick is known (`RulesEngine._finish_search`), since
        #: unlike a RULE 115 target a search's result isn't known until the
        #: `pending_choice` round trip finishes.
        self.remember = remember
        #: A per-found-card *conditional* destination (RULE 701.19c), unlike
        #: the positional ``destinations`` above: a list of ``{"criteria":
        #: <card_query>, "destination": <str>}`` rules, first match wins,
        #: falling back to ``destinations``/``destination``. Archdruid's
        #: Charm's "put it onto the battlefield tapped **if it's a land
        #: card**. Otherwise, put it into your hand." — the branch depends
        #: on *which* card the player found, so it can't be decided when the
        #: search is opened.
        self.destination_if = destination_if
        self.criteria = type_restriction if type_restriction is not None else criteria
        self.destination = destination
        self.count = count
        self.optional = optional
        self.player = player
        self.zones = zones
        self.destinations = destinations
        self.exile_rest = exile_rest
        self.mana_value_from = mana_value_from
        #: "…put that card onto the battlefield **with an additional +1/+1
        #: counter on it**" (Neoform) — ``{"kind": "+1/+1", "count": 1}``,
        #: applied by `RulesEngine._resume_search` right after the
        #: found card reaches the battlefield.
        self.extra_counters = extra_counters
        #: "…put it onto the battlefield, **attach it to a creature you
        #: control**" (Stonehewer Giant/Quest for the Holy Relic) — see
        #: `RulesEngine._finish_search`'s own docstring for the auto-pick.
        self.attach_to_creature_you_control = attach_to_creature_you_control
        self.then_specs = list(then_specs or [])

    def _resolved_criteria(self, context: Optional[GameContext] = None) -> Any:
        """``criteria`` with any `mana_value_from` bound to a real number."""
        if not self.mana_value_from:
            return self.criteria
        if self.mana_value_from.get("source") == "count_selector" and context is not None:
            from .. import continuous  # avoid the continuous↔effects import cycle
            base = continuous.count_selector(
                context.state, getattr(self.source, "controller_id", None),
                self.mana_value_from["count_selector"], source=self.source,
            )
        else:
            base = getattr(self.source, "sacrificed_cost_mana_value", None)
            if base is None:
                # RULE 601.2b's cost was never paid (or the record is gone) —
                # fail closed to "nothing matches" rather than silently
                # searching for an unrestricted card.
                base = -1
        value = base + int(self.mana_value_from.get("plus", 0))
        criteria = dict(self.criteria) if isinstance(self.criteria, dict) else (
            {"type": self.criteria} if self.criteria else {}
        )
        criteria["max_mana_value"] = value
        if self.mana_value_from.get("cmp") == "eq":
            # `card_query` has no single "exactly N" key — an equal bound is
            # the two-sided one (Neoform's "mana value equal to 1 plus …").
            criteria["min_mana_value"] = value
        return criteria

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.player == "previous_target_controller":
            # "Its controller may search their library …" (Assassin's
            # Trophy-shaped) — the controller of whatever this same
            # resolution's *previous* clause targeted (RULE 608.2's
            # referent, `GameContext.previous_targets`), the same sentinel
            # `PayCostThenEffect`'s own ``payer`` param already uses for
            # Chain of Vapor. No previous target on record (shouldn't
            # happen for a real card printing this shape, but fails closed
            # rather than guessing) skips the search entirely.
            prev = list(context.previous_targets)
            player = (
                context.state.player_by_id(prev[0].controller_id)
                if prev and getattr(prev[0], "controller_id", None)
                else None
            )
            if player is None:
                return
        elif self.player_from_target:
            chosen = _chosen_targets(targets, 1, None)
            target = chosen[0] if chosen else None
            if target is None or hasattr(target, "instance_id"):
                # Not actually resolved to a player (missing/withered
                # target) — fail closed, same as every other targeted
                # effect with no legal target left.
                return
            player = target
        elif isinstance(self.player, (str, dict)):
            # A player operand (`effect_operands`): "each opponent may search …" run per opponent as the acting
            # player (``"controller"``), or the spell's own controller from inside such a body (Tempt with
            # Discovery's "search your library" for each opponent who did).
            player = self._operand_player(context, targets, self.player)
            if player is None:
                return
        else:
            player = self.player or context.active_player
        chooser = _controller_of(self.source, context) if self.player_from_target else None
        context._request_search(
            player, self._resolved_criteria(context), self.destination, self.count, self.optional,
            zones=self.zones, destinations=self.destinations, exile_rest=self.exile_rest,
            extra_counters=self.extra_counters, destination_if=self.destination_if,
            attach_to_creature_you_control=self.attach_to_creature_you_control,
            remember_source_id=self.source.instance_id if self.remember and self.source is not None else None,
            total_mana_value_budget=self.total_mana_value_budget,
            chooser=chooser,
            share_land_type=self.share_land_type,
            source=self.source,
            track_exiled_with=self.track_exiled_with,
            untap_if_lands_at_least=self.untap_if_lands_at_least,
            then_specs=self.then_specs or None,
        )


# ---------------------------------------------------------------------------
# Registry (docs/07 PART 4 Option C / PART 6)
# ---------------------------------------------------------------------------


class ImpulsiveLookEffect(GameEffect):
    """"Look at the top N cards, take one matching a filter, rest to Y"
    (Grisly Salvage/Commune with the Gods-shaped) — distinct from
    `SearchLibraryEffect` (searches the *whole* library, always shuffles
    afterwards) and `top_library.py`'s standing "look at/play from the top"
    permission (never moves a card). Peels exactly ``count`` cards, offers a
    choice among only the ones matching ``criteria``, routes the pick to
    ``hit_destination`` and the rest to ``miss_destination`` (see
    `GameContext.impulsive_look`/`RulesEngine._request_impulsive_look`).
    """

    def __init__(
        self,
        count: int = 1,
        criteria: Any = "",
        hit_destination: str = "hand",
        miss_destination: str = "graveyard",
        optional: bool = True,
        player: Any = None,
        source: Optional["GameObject"] = None,
        hit_grant_keywords: Optional[list[str]] = None,
        miss_effect_specs: Optional[list[dict]] = None,
        hit_effect_specs: Optional[list[dict]] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.criteria = criteria
        self.hit_destination = hit_destination
        self.miss_destination = miss_destination
        self.optional = optional
        self.player = player
        #: "It gains <keyword> until end of turn." interpose (Winota, Joiner
        #: of Forces) — temp_keywords granted to the placed card, RULE 514.2.
        self.hit_grant_keywords = list(hit_grant_keywords or [])
        #: "If you don't put a card onto the battlefield this way, <body>."
        #: (The Joiner of Cats) — serialized `EffectSpec` dicts applied when
        #: the look places nothing (declined, or nothing eligible).
        self.miss_effect_specs = list(miss_effect_specs or [])
        # Instructions about 'that card' run after the player chooses it, with
        # that exact object as their referent (PAR-119, Arthur).
        self.hit_effect_specs = list(hit_effect_specs or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.impulsive_look(
            player, self.count, self.criteria,
            self.hit_destination, self.miss_destination, self.optional,
            hit_grant_keywords=self.hit_grant_keywords or None,
            miss_effect_specs=self.miss_effect_specs or None,
            hit_effect_specs=self.hit_effect_specs or None,
            source=self.source,
        )


class ImpulsiveDrawEffect(GameEffect):
    """Exile the top ``count`` cards of the library; their controller may
    play any of them through the end of their next turn (RULE 601.3b
    analogue, Light Up the Stage-shaped "impulsive draw") — every card
    exiled becomes playable, unlike `ImpulsiveLookEffect`'s filtered
    choice-and-route shape (see `GameContext.exile_with_play_permission`/
    `RulesEngine.exile_with_play_permission`).

    ``player`` (whose library is exiled from) and ``permission_player``
    (who may play the exiled card) default to the same player — Light Up
    the Stage's own shape — but can differ (Ragavan, Nimble Pilferer-shaped:
    exile from *the player Ragavan just damaged*, permission to Ragavan's
    own controller). ``same_turn_only`` shortens the window from "until
    the end of your next turn" to "until end of turn" (Ragavan's own,
    shorter clause) — see `RulesEngine.exile_with_play_permission`.
    """

    def __init__(
        self,
        count: int = 1,
        player: Any = None,
        permission_player: Any = None,
        same_turn_only: bool = False,
        source: Optional["GameObject"] = None,
        choose_one: bool = False,
        each_player: bool = False,
        mana_wildcard: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        #: "Exile the top card of **each player's** library. You may play those cards this turn,
        #: and you may spend mana as though it were mana of any color to cast those spells."
        #: (Mezzio Mugger) — one exile per living player, all playable by this effect's controller.
        self.each_player = each_player
        #: RULE 605.1a mana-spend permission on the exiled cards (see `GameState.mana_wildcard_permission`).
        self.mana_wildcard = mana_wildcard
        #: PAR-137: "choose 1 of them. You may play that card" / "you may play 1 of those cards" —
        #: only the player's pick keeps the play permission (the other exiled cards stay exiled).
        self.choose_one = choose_one
        #: How many: a number or an `effect_amounts` operand ("…you may exile that many cards from
        #: the top of your library" — Virtue of Courage; "…three cards instead if the additional
        #: cost was paid" — Burning Curiosity).
        self.count = count
        self.player = player
        self.permission_player = permission_player
        self.same_turn_only = same_turn_only

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        # "you" is this ability's/spell's own controller, not whoever
        # happens to be on the play right now (Virtue of Courage: a source
        # its controller controls can deal damage on *any* turn, and
        # `context.active_player` is only ever correct by coincidence for
        # a resolution that happens to land on the controller's own turn —
        # off-turn it silently exiled from, and gave play permission to,
        # the wrong player). `self.source.controller_id` mirrors the
        # already-correct pattern `TargetOrDelayedDrawEffect` uses just
        # above, falling back to `context.active_player` only when no
        # source is bound at all (a bare fixture-built effect) — the same
        # "read the source's live controller, not the turn" pattern
        # `CastExiledFaceDownEffect.apply` already uses above.
        player = self.player
        if player is None and self.source is not None:
            player = context.state.player_by_id(self.source.controller_id)
        player = player or context.active_player
        permission_player = self.permission_player or player
        source_name = self.source.name if self.source is not None else None
        count = self._measured(self.count, context, targets)
        if count <= 0:
            return
        # One exile per library; every permission is held by the effect's controller.
        libraries = list(context.state.living_players()) if self.each_player else [player]
        exiled = []
        for library_owner in libraries:
            exiled.extend(context.exile_with_play_permission(
                library_owner, count, source_name=source_name,
                permission_player=permission_player, same_turn_only=self.same_turn_only,
                grant=not self.choose_one, mana_wildcard=self.mana_wildcard,
            ))
        if self.choose_one and exiled:
            context.engine._request_choose_objects(
                permission_player, exiled,
                "grant_temp_play_same_turn" if self.same_turn_only else "grant_temp_play_next_turn",
                count=1, optional=False, prompt="Wähle eine Karte", source=self.source,
            )
        # MEC-58: seed `created_objects` (the "the tokens"/"that card"
        # RULE 608.2 referent idiom this file already uses in several
        # places) so a following clause in the same ability body can act on
        # what was just exiled — Tavern Brawler's "…where X is that card's
        # mana value" (`PumpEffect.amount_from_created_object_mana_value`).
        # Purely additive: no existing card reads this after an impulsive
        # draw, so this changes nothing for them.
        context.created_objects.extend(exiled or [])


class DrawRevealCastOneFreeEffect(GameEffect):
    """"Draw N cards and reveal them. You may cast one of them without
    paying its mana cost." (RULE 121/601.3b combo — Dungeon of the Mad
    Mage's own "Mad Wizard's Lair" room, PAR-13).

    Reveal is purely informational (RULE 701.28 — no hidden-zone state to
    model, since `services/game_session.py`'s own redaction already keeps
    a hand private otherwise), so this only draws, then offers
    `RulesEngine._request_choose_objects`'s ``"cast_free"`` action over
    *exactly* the cards this draw put into hand (never the rest of the
    hand) — snapshotting the hand before/after rather than assuming a
    fixed append count, since a draw can be redirected (RULE 121.5's
    replacement family) or silently capped (a draw-limit static).
    """

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.count <= 0:
            return
        before = list(player.hand)
        context.draw(player, self.count)
        drawn = [c for c in player.hand if c not in before]
        if drawn:
            context.choose_objects(
                player, drawn, "cast_free", count=1, optional=True, source=self.source,
            )


class ReturnRemainingExiledEffect(GameEffect):
    """RULE 603.7 delayed cleanup: whichever of ``instance_ids`` are still
    sitting in exile move to their owner's graveyard — Mnemonic Betrayal's
    own "at the beginning of the next end step, if any of those cards
    remain exiled, return them to their owners' graveyards." Anything
    already cast by then is simply gone from the zone check (it resolved,
    or is on the stack/battlefield/graveyard through its own path), so this
    only ever touches leftovers. Plain data (``instance_ids`` are ints), so
    it survives `GameState.clone` like any other armed `DelayedTrigger`.
    """

    def __init__(self, instance_ids: list[int], source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.instance_ids = list(instance_ids)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for iid in self.instance_ids:
            obj = context.state.find_object(iid)
            if obj is None or obj.zone != Zone.EXILE:
                continue
            owner = context.state.player_by_id(obj.owner_id)
            owner.remove_from_zone(obj, Zone.EXILE)
            owner.add_to_zone(obj, Zone.GRAVEYARD)
            context.state.temp_play_permissions.pop(iid, None)
            context.state.temp_play_permission_player.pop(iid, None)
            context.state.temp_play_permission_source.pop(iid, None)
            context.state.mana_wildcard_permission.pop(iid, None)


class GraveyardImpulsiveCastEffect(GameEffect):
    """"Exile all opponents' graveyards. You may cast spells from among
    those cards this turn, and mana of any type can be spent to cast them.
    At the beginning of the next end step, if any of those cards remain
    exiled, return them to their owners' graveyards." (Mnemonic Betrayal) —
    the graveyard-sourced sibling of `ImpulsiveDrawEffect`'s library-top
    exile: the same dual-player permission shape (exile-owner vs.
    permission-holder can differ, `RulesEngine._grant_temp_play_permission`)
    plus RULE 605.1a's broadest "any type" mana-wildcard grant (``ManaPool``'s
    ``wildcard="type"``, see `RulesEngine.cast_spell`) and a RULE 603.7
    delayed cleanup (`ReturnRemainingExiledEffect`) for whatever's left
    unexiled at the next end step.
    """

    def __init__(
        self,
        mana_wildcard: Optional[str] = "type",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.mana_wildcard = mana_wildcard

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_state import DelayedTrigger  # avoid effects↔game_state cycle

        controller_id = getattr(self.source, "controller_id", None) or context.active_player.id
        controller = context.state.player_by_id(controller_id)
        source_name = self.source.name if self.source is not None else None
        exiled_ids: list[int] = []
        for player in context.state.living_players():
            if player.id == controller_id or not player.graveyard:
                continue
            exiled = context.engine.exile_graveyard_with_cast_permission(
                player, controller, source_name=source_name, mana_wildcard=self.mana_wildcard,
            )
            exiled_ids.extend(obj.instance_id for obj in exiled)
        if not exiled_ids:
            return
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=controller_id,
                step="end",
                scope="any",
                effects=[ReturnRemainingExiledEffect(exiled_ids, source=self.source)],
                description=f"{source_name}: restliche Karten zurückgeben" if source_name else "",
            )
        )


class ShuffleLibraryEffect(GameEffect):
    """Shuffle the controller's (or a target player's) library (RULE 701.20)."""

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or (targets[0] if targets else None) or context.active_player
        context.shuffle_library(player)


class ShuffleHandAndGraveyardIntoLibraryEffect(GameEffect):
    """"Shuffle your hand and graveyard into your library." (RULE 701.20) —
    the move underneath the wheel family (Timetwister / Time Reversal / Echo
    of Eons / Day's Undoing), whose full printed line ("…, then draws seven
    cards") is now a `seq` of this and a `draw` with ``selector`` set rather
    than a fused `wheel` type (ENG-37).

    ``scope="each_player"`` is the mass RULE 601.2c form those cards print;
    without it, just the effect's controller. Every player's shuffle only
    touches their own zones, so the sequential loop is order-independent
    (RULE 101.4's simultaneous idiom).
    """

    def __init__(self, scope: Optional[str] = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.scope = scope

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.scope == "each_player":
            players = list(context.state.living_players())
        else:
            controller = _controller_of(self.source, context)
            players = [controller] if controller is not None else []
        for player in players:
            context.shuffle_hand_and_graveyard_into_library(player)


class CascadeEffect(GameEffect):
    """Cascade (RULE 702.85): free-cast the first cheaper nonland from the top.

    Exiles from the top of the library until a nonland card with mana value
    *less than* the cascade spell's, which the controller may cast without
    paying; the rest go to the bottom in a random order. This is a cast (it
    uses the stack), not a "put onto the battlefield" — the distinction the
    event model draws.

    ``mana_value`` is the threshold; left ``None`` it is read from the
    cascade spell (``source``) at resolution, since cascade's own spell is
    what sets the ceiling.
    """

    def __init__(
        self,
        mana_value: Optional[int] = None,
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.mana_value = mana_value
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or _controller_of(self.source, context)
        mana_value = self.mana_value
        if mana_value is None:
            mana_value = (context.trigger_event or {}).get("mana_value")
        if mana_value is None and self.source is not None:
            from ...models.mana.mana_cost import ManaCost
            mana_value = ManaCost.from_card(self.source.card).with_x(getattr(self.source, "x_paid", 0)).resolved_value
        context.cascade(player, mana_value or 0)


class DiscoverEffect(GameEffect):
    """Discover N (RULE 702.164): like cascade, but the hit is a nonland with
    mana value ``N`` *or less*, and the controller casts it for free **or**
    puts it into their hand (never leaves it behind)."""

    def __init__(
        self,
        mana_value: Any = 0,
        player: Any = None,
        source: Optional["GameObject"] = None,
        cast_limit: Optional[int] = None,
        treasures_below: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        #: "…You may cast it without paying its mana cost if that spell's mana value is N or less. If you don't, put
        #: that card into your hand." (Breaching Dragonstorm): a hit above ``cast_limit`` can only go to the hand.
        self.cast_limit = cast_limit
        #: "If the discovered card's mana value is less than N, create that many tapped Treasure tokens equal to the
        #: difference." (Hit the Mother Lode)
        self.treasures_below = treasures_below
        #: The discover cap: a number or an `effect_amounts` operand ("Discover X, where X is that
        #: spell's mana value" — Monstrous Vortex's cast trigger, Hurl into History's countered spell).
        self.mana_value = mana_value
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.discover(
            player, self._measured(self.mana_value, context, targets),
            cast_limit=self.cast_limit, treasures_below=self.treasures_below, source=self.source,
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — player-scoped restrictions & history-driven effects
# ---------------------------------------------------------------------------


class PlayerCastRestrictionEffect(GameEffect):
    """"Until your next turn, target player can't cast noncreature spells."
    (Hope of Ghirapur) — a **player-scoped**, duration-bounded cast
    prohibition (RULE 601.3a), installed on `Player.player_effects` rather
    than derived by the layer engine.

    It isn't a `StaticAbility`: nothing on the battlefield keeps it alive
    (Hope of Ghirapur has *sacrificed itself* to pay for this), so there is
    no permanent for `continuous.recompute` to read it off. The parallel is
    `PreventDamageEffect`'s turn-scoped shield, which lives on
    `player_effects` for the same reason.

    ``until_next_turn_of`` is the player id whose next turn ends it (RULE
    611.2b) — `GameEngine.begin_turn` sweeps every `player_effects` list for
    entries keyed to the incoming active player. ``noncreature`` restricts
    only noncreature spells (leave ``False`` for a blanket "can't cast
    spells"). Consulted by `GameEngine.can_cast` via `_player_cast_
    restricted`.
    """

    #: Marker `GameEngine.can_cast` scans for, so it never has to import
    #: this class (the same duck-typed flag `damage_prevention_shield` uses).
    player_cast_restriction = True

    def __init__(
        self,
        noncreature: bool = True,
        until_next_turn_of: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.noncreature = noncreature
        self.until_next_turn_of = until_next_turn_of
        self.target_spec = TargetSpec(
            kind="player_dealt_combat_damage_by_source",
            description="Spieler, dem diese Kreatur in diesem Zug Kampfschaden zugefügt hat",
        )

    def restricts(self, card: Any) -> bool:
        """Whether this restriction blocks casting ``card`` (RULE 601.3a)."""
        if not self.noncreature:
            return True
        return not getattr(card, "is_creature", False)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None or not hasattr(target, "player_effects"):
            return
        controller = _controller_of(self.source, context)
        installed = PlayerCastRestrictionEffect(
            noncreature=self.noncreature,
            until_next_turn_of=controller.id if controller is not None else None,
            source=self.source,
        )
        # The installed copy is a plain marker read by `can_cast`; it must
        # not carry a `target_spec` that would make it look like a fresh
        # targeting effect if anything ever re-scanned `player_effects`.
        installed.target_spec = None
        target.player_effects.append(installed)


class LookTopKeepOneOnTopEffect(GameEffect):
    """"Look at the top X cards of your library … put up to one of them on
    top of your library and the rest on the bottom in a random order."
    (Thassa's Oracle) — a library-reordering dig with no card ever changing
    zone in the ordinary sense.

    ``count_selector`` (`continuous.count_selector`, e.g. ``"devotion_to_
    blue"``) resolves X live at resolution time rather than baking a number
    in; ``count`` is the fixed fallback when no selector is given.

    ``win_if_count_at_least_library`` is Thassa's Oracle's own alternative
    win condition (RULE 104.2a): checked *before* the reordering, against
    the library size at that moment — X >= library size wins the game
    outright, which is the whole reason the card is a cEDH staple. Routed
    through `RulesEngine.player_wins`, the same choke point Jace, Wielder of
    Mysteries uses, so "you can't win the game" effects stay in one place.

    "Put **up to one** of them on top" is a real choice, offered through
    the general `GameContext.choose_objects` chooser (optional, so declining
    bottoms all X). The rest go to the bottom in a random order, per the
    card — and they are bottomed *before* the choice rather than after, so
    the randomization can't depend on which card was kept; removing one card
    from an already-random sequence leaves the others just as random.
    """

    def __init__(
        self,
        count: int = 0,
        count_selector: Optional[str] = None,
        win_if_count_at_least_library: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.count_selector = count_selector
        self.win_if_count_at_least_library = win_if_count_at_least_library

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        amount = self.count
        if self.count_selector:
            from .. import continuous  # function-scoped: avoid an import cycle

            amount = continuous.count_selector(context.state, player.id, self.count_selector)
        library = player.zones[Zone.LIBRARY]
        # RULE 104.2a, checked before anything moves — an empty library
        # satisfies "X >= 0 cards" and wins even with X of 0.
        if self.win_if_count_at_least_library and amount >= len(library):
            context.engine.player_wins(player)
            return
        if amount <= 0:
            return
        # The library's *end* is its top (see `Player.zones`): peel the top
        # ``amount`` and bottom them all in a random order, then let the
        # player lift up to one back onto the top.
        looked = [library.pop() for _ in range(min(amount, len(library)))]
        if not looked:
            return
        random.shuffle(looked)
        for card in looked:
            library.insert(0, card)  # bottom of library
        context.choose_objects(
            player, looked, "library_top", count=1, optional=True,
            prompt="Lege bis zu eine der angesehenen Karten oben auf deine Bibliothek",
            source=self.source,
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — mana-trigger bodies (RULE 605.1b/605.4)
# ---------------------------------------------------------------------------


class MirrorProducedManaEffect(GameEffect):
    """"Add one mana of any type that permanent produced." (Kinnan, Bonder
    Prodigy) — the amount is fixed at one, but the *type* is only knowable
    from the firing itself, read off `GameContext.trigger_event`'s
    ``produced`` payload (the `TAPPED_FOR_MANA` event `GameEngine.
    tap_for_mana` stamps with what actually went into the pool).

    Distinct from `AddManaEffect`'s ``"ANY"`` sentinel, which offers every
    colour: Kinnan is restricted to what that permanent *did* produce, so a
    Basalt Monolith copies {C} and a Bloom Tender copies only the colours it
    actually made.

    When a single tap produced 2+ distinct types (an "any combination of
    colours" ability — `ManaAbility.any_combination`, or a Bloom Tender),
    *which* one to copy is a real choice, offered through the narrowed
    `RulesEngine.add_mana_any_color` menu. One type produced needs no
    prompt, which is the overwhelmingly common case.
    """

    def __init__(
        self, count: int = 1, player: Any = None, source: Optional["GameObject"] = None
    ) -> None:
        super().__init__(source)
        self.count = count
        #: Who adds it — "**that player** adds …" (Mana Flare, PAR-119) is an operand
        #: (`effect_operands`); ``None`` is the ability's controller (Kinnan).
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.player is None:
            player = _controller_of(self.source, context)
        else:
            from ..effect_operands import player_for  # function-scoped: import cycle

            player = player_for(self.player, context, self.source, targets)
        event = context.trigger_event
        if player is None or event is None:
            return
        produced = event.get("produced") or {}
        colours = [c for c, n in produced.items() if n]
        if not colours:
            return
        # RULE 605.1a: "any type **that permanent produced**" — a real
        # choice whenever one tap made 2+ types (a Bloom Tender, a dual
        # land's "any combination"), narrowed to exactly those. Safe to open
        # a `pending_choice` here even though a triggered mana ability
        # resolves off-stack (RULE 605.4): the firing action, `GameEngine.
        # tap_for_mana`, is a discrete player action, not a mid-payment step.
        for _ in range(max(self.count, 1)):
            context.engine.add_mana_any_color(player, colours)


class TapMatchingLandsEffect(GameEffect):
    """"Tap all lands that player controls that could produce any type of
    mana that land could produce." (Mana Web) — a mana-denial sweep keyed to
    the *specific* land that was just tapped.

    Both halves come from `GameContext.trigger_event` (`TAPPED_FOR_MANA`):
    which player to sweep (``controller_id``) and which land set the
    reference types (``instance_id``). The reference land's *potential*
    production is re-derived from `game/mana_abilities.py`, not from the
    event's ``produced`` payload — RULE 605.1a is explicit that this is
    about what a land *could* produce, so a dual land tapped for {U} still
    locks down every land that makes {U} **or** its other colour.

    Not itself a mana ability (it produces none), so it uses the stack like
    any ordinary triggered ability.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    @staticmethod
    def _producible(obj: Any, state: Any) -> set[str]:
        """Every mana type ``obj`` could produce right now (RULE 605.1a)."""
        from ..mana_abilities import mana_abilities_for  # function-scoped: import cycle

        types: set[str] = set()
        for ability in mana_abilities_for(obj, state=state):
            for option in ability.options:
                types.update(c for c, n in option.items() if n)
        return types

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None:
            return
        reference = context.state.find_object(event.get("instance_id"))
        player_id = event.get("controller_id")
        if reference is None or player_id is None:
            return
        wanted = self._producible(reference, context.state)
        if not wanted:
            return
        for obj in context.state.permanents():
            if obj.controller_id != player_id or not obj.is_land or obj.tapped:
                continue
            if self._producible(obj, context.state) & wanted:
                context.set_tapped(obj, True)


# ---------------------------------------------------------------------------
# cEDH staples cube — control exchange, mass phasing, copy+bounce
# ---------------------------------------------------------------------------


class ExchangeControlEffect(GameEffect):
    """"Exchange control of this creature and up to one target creature an
    opponent controls. If you don't or can't make an exchange, sacrifice
    this creature." (Gilded Drake) — RULE 108.4/701.10.

    A genuine *swap*, which neither shipped control shape could express: the
    layer-2 ``control_change`` static reassigns one permanent's controller
    for as long as its source stays around, and
    `GainControlUntilEndOfTurnEffect` is a one-way, duration-bounded grab.
    Exchange is permanent, two-way, and — crucially for Gilded Drake — has a
    failure mode with its own consequence.

    Implemented as a straight `GameObject.controller_id` swap rather than a
    pair of continuous effects, because RULE 701.10c makes an exchange a
    one-shot change of control that doesn't depend on any source remaining
    on the battlefield: Gilded Drake dying afterwards must *not* give the
    creature back, which is precisely why the card is played.

    ``sacrifice_self_if_no_exchange`` is Gilded Drake's own failure clause
    (RULE 701.10d: an exchange with only one exchangeable permanent doesn't
    happen at all). Note the drake's ability "still resolves if its target
    becomes illegal" — with `target_spec.optional` set, no legal target is
    itself a legal choice, so the ability resolves, the exchange doesn't
    happen, and the sacrifice does.
    """

    def __init__(
        self,
        target_kind: str = "creature",
        sacrifice_self_if_no_exchange: bool = False,
        source: Optional["GameObject"] = None,
        first_target_kind: Optional[str] = None,
        second_creature_filter: Optional[dict[str, Any]] = None,
        optional: bool = False,
        count: int = 1,
        distinct_controllers: bool = False,
        shares_type: Optional[str] = None,
        second_not_greater: Optional[str] = None,
        destroy_auras_if_exchanged: bool = False,
        draw_if_neither_controlled: int = 0,
    ) -> None:
        super().__init__(source)
        #: RULE 701.10c's own after-effect riders, both conditioned on the
        #: exchange *actually happening* (unlike ``shares_type``/
        #: ``second_not_greater`` above, which gate whether it happens at
        #: all): ``destroy_auras_if_exchanged`` (Gauntlets of Chaos —
        #: "if those permanents are exchanged this way, destroy all Auras
        #: attached to them") destroys every Aura attached to either
        #: permanent post-swap; ``draw_if_neither_controlled`` (Modify
        #: Memory — "if you control neither creature, draw three cards")
        #: draws that many cards for this ability's controller when, after
        #: the attempt, they end up controlling neither exchanged permanent
        #: (true both when the exchange happened and handed both away, and
        #: when it never happened at all because neither was theirs to
        #: begin with).
        self.destroy_auras_if_exchanged = destroy_auras_if_exchanged
        self.draw_if_neither_controlled = int(draw_if_neither_controlled or 0)
        #: PAR-30 (RULE 701.10 exchange-control residue) — cross-target
        #: legality predicates RULE 115 verifies at *selection*, checked here
        #: at resolution instead (the same documented simplification the
        #: ``mine.controller_id != theirs.controller_id`` no-op below already
        #: is): ``shares_type`` (``"card"``/``"permanent"`` — "…that shares a
        #: card type with it", Daring Thief / Legerdemain / Role Reversal /
        #: Shifting Loyalties) requires the two permanents to share a card
        #: type; ``second_not_greater`` (``"mana_value"``/``"power"`` — Puca's
        #: Mischief "with equal or lesser mana value", Spawnbroker "with power
        #: less than or equal to that creature's power") caps the *second*
        #: (opponent-side) permanent against the first. A pick that fails
        #: either just doesn't exchange — one more branch onto the existing
        #: ``exchangeable`` gate, no `legal_targets`/client change.
        self.shares_type = shares_type
        self.second_not_greater = second_not_greater
        # "Exchange control of target artifact or creature you control and
        # target creature an opponent controls with power 3 or less." (Oko,
        # Thief of Crowns' -5, MEC-43 round 4E) — unlike Gilded Drake's own
        # "this creature and up to one target creature" (one side is
        # always this effect's own source), both sides here are
        # independently-chosen RULE 115 targets; ``first_target_kind`` set
        # switches into this two-target mode via `GameEffect.extra_target_
        # specs` (see its own docstring — Brass Squire/Halvar's identical
        # "two independently-chosen targets of different kinds" shape),
        # rather than ``self`` + one target. Neither is ``optional`` here
        # (Oko's own text prints no "up to"/failure clause), unlike the
        # single-target mode below.
        #
        # "Exchange control of 2 target creatures controlled by different
        # players." (PAR-29 — Modify Memory/Shifting Borders/Djinn of
        # Infinite Deceits-shaped) is neither of those: both sides are the
        # *same* kind and neither is this effect's own source, but unlike
        # Oko it's one RULE 601.2c requirement of two, not two independent
        # ones — ``count=2`` on a single `TargetSpec` (the same "up to two"
        # multi-target idiom `DestroyEffect`/`ChooseTargetsEffect`'s own
        # group form already use), which is also what makes
        # ``distinct_controllers`` (an *across-rounds* offer-time
        # constraint, `targeting.TargetSpec`'s own docstring) meaningful
        # here at all — it has no cross-spec equivalent for the
        # ``first_target_kind`` two-spec mode above. `apply()` doesn't need
        # to know which of the two shapes produced its two targets; a flat
        # ``targets`` list of 2 reads the same either way.
        #: PAR-30 (Confusion in the Ranks — "whenever `<X>` enters, its
        #: controller chooses target permanent … that shares a card type
        #: with it. Exchange control of those permanents."): the *first*
        #: side is the firing event's own subject (the entering permanent),
        #: never a RULE 115 target of this effect's own — the same
        #: ``target_kind="trigger_subject"`` idiom `ExileEffect`/`TapEffect`
        #: already use, just for the ``first_target_kind`` slot instead of
        #: the only one. Only the *second* side is a real target — chosen by
        #: `TriggeredAbility.controller_from_trigger_event` (not this
        #: ability's own source's controller), so this collapses to the
        #: same single-target-mode shape the plain ``self``+target case
        #: below already has, just resolving ``mine`` from the trigger event
        #: in `apply` instead of `self.source`.
        self._first_trigger_subject = first_target_kind == "trigger_subject"
        self._two_target_mode = (
            first_target_kind is not None and not self._first_trigger_subject
        ) or count >= 2
        if self._first_trigger_subject:
            self.target_spec = TargetSpec(kind=target_kind, creature_filter=second_creature_filter)
        elif first_target_kind is not None:
            self.target_spec = TargetSpec(kind=first_target_kind)
            self.extra_target_specs = (
                TargetSpec(kind=target_kind, creature_filter=second_creature_filter),
            )
        elif count >= 2:
            # ``second_creature_filter`` doubles as the multi mode's own
            # shared filter here (Djinn of Infinite Deceits' "two target
            # **nonlegendary** creatures") — one requirement picking N
            # same-kind, same-filter targets, unlike the two-independently-
            # typed-specs mode above.
            self.target_spec = TargetSpec(
                kind=target_kind, count=count, distinct_controllers=distinct_controllers,
                creature_filter=second_creature_filter,
            )
        else:
            # ``optional`` is RULE 115.1a's "up to one" (Gilded Drake) —
            # PAR-29's plain "exchange control of ~ and target X." cards
            # (Avarice Totem/Phyrexian Infiltrator) print no "up to" and
            # need a real, mandatory target instead.
            self.target_spec = TargetSpec(kind=target_kind, optional=optional)
        self.sacrifice_self_if_no_exchange = sacrifice_self_if_no_exchange

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def _cross_target_ok(self, mine: Any, theirs: Any) -> bool:
        """RULE 115 cross-target predicates verified at resolution — see the
        ``shares_type`` / ``second_not_greater`` note in ``__init__``."""
        if self.shares_type is not None:
            # RULE 205.2: for two battlefield permanents "shares a permanent
            # type" and "shares a card type" pick out the same set, so both
            # spellings check the same intersection — narrowed to real card
            # types (``type_words`` also carries a synthetic "permanent"
            # entry every permanent has, which would make the test vacuous).
            a = {t.lower() for t in getattr(mine, "type_words", ())} & _PERMANENT_TYPE_WORDS
            b = {t.lower() for t in getattr(theirs, "type_words", ())} & _PERMANENT_TYPE_WORDS
            if not (a & b):
                return False
        if self.second_not_greater == "mana_value":
            if (getattr(theirs.card, "converted_mana_cost", 0) or 0) > (
                getattr(mine.card, "converted_mana_cost", 0) or 0
            ):
                return False
        if self.second_not_greater == "power":
            if (theirs.power or 0) > (mine.power or 0):
                return False
        return True

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._first_trigger_subject:
            ev = context.trigger_event
            mine = context.state.find_object(ev.get("instance_id")) if ev is not None else None
            theirs = targets[0] if targets else None
        elif self._two_target_mode:
            mine = targets[0] if targets and len(targets) > 0 else None
            theirs = targets[1] if targets and len(targets) > 1 else None
        else:
            mine = self.source
            theirs = targets[0] if targets else None
        battlefield = context.state.permanents()
        exchangeable = (
            mine is not None
            and theirs is not None
            and mine in battlefield
            and theirs in battlefield
            and mine.controller_id != theirs.controller_id
            and self._cross_target_ok(mine, theirs)
        )
        if exchangeable:
            mine.controller_id, theirs.controller_id = theirs.controller_id, mine.controller_id
            # RULE 302.6: each permanent is newly under its controller's
            # command, so both are summoning sick until that player's next
            # turn — the same treatment `RulesEngine` gives any other
            # battlefield arrival.
            mine.summoning_sick = True
            theirs.summoning_sick = True
            if self.destroy_auras_if_exchanged:
                # Gauntlets of Chaos — every Aura attached to either
                # now-swapped permanent, RULE 704.5m style (SBA-independent,
                # a direct destroy so a regeneration shield can't save one).
                for aura in [
                    o for o in context.state.battlefield
                    if o.attached_to in (mine.instance_id, theirs.instance_id)
                    and "aura" in (o.card.type_line or "").lower()
                ]:
                    context.destroy(aura)
            context.recompute()
        elif self.sacrifice_self_if_no_exchange and mine is not None and mine in battlefield:
            # RULE 701.10d + 701.16c: no exchange happened, so the drake
            # sacrifices itself — sacrifice, never destruction.
            context.put_into_graveyard(mine)
        if self.draw_if_neither_controlled:
            # Modify Memory — whether or not the exchange above happened,
            # this ability's controller ends up controlling neither
            # permanent, so they draw a consolation hand.
            player = _controller_of(self.source, context)
            controls_either = player is not None and player.id in (
                getattr(mine, "controller_id", None), getattr(theirs, "controller_id", None),
            )
            if player is not None and not controls_either:
                context.draw(player, self.draw_if_neither_controlled)


class ExchangeControlThenEnergySacrificeEffect(GameEffect):
    """"Exchange control of this creature and target creature an opponent
    controls. If you do, you get {E}{E}{E}{E}, then sacrifice that creature
    unless you pay an amount of {E} equal to its mana value." (Volatile
    Stormdrake) — RULE 608.2b's "if you do" here gates on whether the
    *exchange* (RULE 701.10, the same swap `ExchangeControlEffect` does)
    actually happened, a condition no generic `ConditionalEffect` key
    covers and `_apply_effects_partitioned` has no channel to signal
    between separate effect instances — the same reason a genuine "action,
    if you do, consequence" card gets one bespoke composite effect rather
    than two effects and a cross-effect flag (or, where the "if you do" is
    just "a target was chosen", an ENG-37 `seq` of an optional verb + an
    `if_else` on `previous_target`, as Temur Sabertooth now uses). "that
    creature" is the one just exchanged in — now under this
    ability's controller, who must pay {E} equal to *its* mana value
    (read live, post-exchange) or lose it.

    Like `ExchangeControlEffect`, ``target_kind="creature"`` isn't narrowed
    to "an opponent controls" at the `TargetSpec` level (Gilded Drake's own
    established simplification) — the exchange itself already no-ops if
    the chosen target shares this ability's controller.
    """

    def __init__(self, target_kind: str = "creature", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind, optional=True)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        mine = self.source
        theirs = targets[0] if targets else None
        # RULE 112.7a: this ability's controller is fixed as of when it was
        # put on the stack — captured *before* the swap below, since "you"
        # in "you get {E}{E}{E}{E}" must stay this permanent's original
        # controller even though the swap is about to hand ``mine`` to
        # ``theirs``'s former controller instead.
        player = _controller_of(mine, context)
        battlefield = context.state.permanents()
        exchangeable = (
            mine is not None
            and theirs is not None
            and player is not None
            and mine in battlefield
            and theirs in battlefield
            and mine.controller_id != theirs.controller_id
        )
        if not exchangeable:
            return
        mine.controller_id, theirs.controller_id = theirs.controller_id, mine.controller_id
        mine.summoning_sick = True
        theirs.summoning_sick = True
        context.recompute()
        context.add_player_counters(player, 4, "energy", source=mine)
        from ..costs import ActivationCost  # function-scoped: costs↔effects cycle
        mv = theirs.card.converted_mana_cost or 0
        context.engine._request_sacrifice_unless_pay(player, ActivationCost(pay_energy=mv), theirs)


class ExchangeControlThenCopyTokenEffect(GameEffect):
    """"You may exchange control of two other target artifacts. When you
    do, create a token that's a copy of target artifact you don't control,
    except it's a 1/1 green Squirrel creature token in addition to its
    other colors and types." (Arteeoh, Dread Scavenger) — RULE 608.2b's "if
    you do" gated on whether the *exchange* actually happened (same
    composite-effect reason `ExchangeControlThenEnergySacrificeEffect`'s
    own docstring gives), **and** RULE 603.11's "when you do" reflexive
    shape for the copy's own target — a fresh permanent, chosen only once
    the exchange is confirmed, never one of the two just exchanged. Queued
    via `RulesEngine.enqueue_reflexive_trigger` exactly like `pay_cost_
    then.then_trigger` (v206) rather than resolved off-stack, so the copy
    target gets real RULE 115 selection.

    **Documented simplification**: "in addition to its **other colors**" —
    the green addition — isn't modeled (`CopyPermanentEffect` has
    ``set_colors`` (replace) but no *additive* colour param, and this is
    the only card that would ever want one); the type/subtype/P/T additions
    ("1/1 … Squirrel creature … in addition to its other types") are exact.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="artifact", count=2, optional=True)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = [t for t in (targets or []) if t is not None]
        if len(chosen) < 2:
            return
        a, b = chosen[0], chosen[1]
        battlefield = context.state.permanents()
        exchangeable = a in battlefield and b in battlefield and a.controller_id != b.controller_id
        if not exchangeable:
            return
        a.controller_id, b.controller_id = b.controller_id, a.controller_id
        a.summoning_sick = True
        b.summoning_sick = True
        context.recompute()
        context.enqueue_reflexive_trigger(
            [{
                "type": "copy_permanent",
                "params": {
                    "target_kind": "artifact_you_dont_control",
                    "add_types": ["creature"], "add_subtypes": ["Squirrel"],
                    "set_power": 1, "set_toughness": 1,
                },
            }],
            self.source,
        )


class PhaseOutAllYouControlEffect(GameEffect):
    """"Until your next turn, your life total can't change and you gain
    protection from everything. All permanents you control phase out."
    (Teferi's Protection) — RULE 702.26/611.2b.

    Three separate things the card does at once, kept as one effect because
    all three share the same "until your next turn" duration and the same
    player, and because none is meaningful without the others:

    * every permanent the controller controls phases out (RULE 702.26b) —
      the mass form of the shipped, single-permanent `PhaseOutEffect`. The
      RULE 702.26a sweep in `GameEngine._step_untap` already phases them all
      back in at that player's next untap step, so the duration needs no
      separate bookkeeping.
    * their life total can't change (`PlayerLifeLockEffect`-style marker on
      `Player.player_effects`, consulted by `RulesEngine.gain_life`/
      `lose_life`).
    * they gain protection from everything, which for a *player* reduces to
      "can't be dealt damage / targeted" — modeled with the same
      `player_effects` marker so both halves lapse together in
      `GameEngine.begin_turn`.

    Unlike `PhaseOutEffect`, attached Auras/Equipment are *not* unattached:
    here their host and they themselves both phase out together, so the
    attachment stays valid throughout (RULE 702.26e) — which is the whole
    point of Teferi's Protection as a board-preserving answer.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in list(context.state.battlefield):
            if obj.controller_id == player.id:
                obj.phased_out = True
        shield = PlayerShieldEffect(
            life_locked=True,
            protection_from_everything=True,
            until_next_turn_of=player.id,
            source=self.source,
        )
        player.player_effects.append(shield)
        context.recompute()


class PlayerShieldEffect(GameEffect):
    """Teferi's Protection's player-scoped half: "your life total can't
    change and you gain protection from everything", until your next turn
    (RULE 611.2b).

    A marker on `Player.player_effects` — the same home the RULE 615 damage
    shield and `PlayerCastRestrictionEffect` use, and for the same reason:
    the spell that granted it is already in the graveyard, so there is no
    permanent for `continuous.recompute` to derive it from. Read by
    `RulesEngine.gain_life`/`lose_life` (life lock, RULE 119.6) and
    `RulesEngine.deal_damage` (protection from everything, RULE 702.16e);
    swept by `GameEngine.begin_turn` via ``until_next_turn_of``.

    ``protected_from_player_id`` (MEC-62 — Noble Heritage: "you gain
    protection from that player until your next turn") is the narrower,
    single-player sibling of ``protection_from_everything`` — only damage
    from a source *that specific player controls* is prevented
    (`RulesEngine._player_protected_from_source_controller`), rather than
    every source. Like ``protection_from_everything`` already does, this
    only ever covers the damage component (RULE 702.16e's "can't be dealt
    damage" — the only DEBT letter a player, as opposed to a permanent,
    is actually subject to in this model); "can't be targeted"/"can't be
    enchanted by that player's stuff" are the same pre-existing scope gap
    `protection_from_everything` already has (no consultation site exists
    for either anywhere in this engine), not something new here.
    """

    #: Duck-typed markers the engine scans for, so neither `RulesEngine` nor
    #: `GameEngine` needs to import this class (the same convention
    #: `damage_prevention_shield`/`player_cast_restriction` follow).
    player_life_locked = True

    def __init__(
        self,
        life_locked: bool = True,
        protection_from_everything: bool = True,
        protected_from_player_id: Optional[str] = None,
        until_next_turn_of: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.life_locked = life_locked
        self.player_life_locked = life_locked
        self.player_protected_from_everything = protection_from_everything
        self.protected_from_player_id = protected_from_player_id
        self.until_next_turn_of = until_next_turn_of

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # a marker consulted by the engine, never applied itself


class EachPlayerMayCounterThenProtectionEffect(GameEffect):
    """"Each player may put two +1/+1 counters on a creature they control.
    For each opponent who does, you gain protection from that player until
    your next turn." (Noble Heritage, MEC-62)

    MVP simplification: this engine has no genuine per-player-in-sequence
    "may" chooser yet (each of several players independently offered a real
    optional decision, in turn, before the next clause reads the results) —
    every living player who controls at least one creature is assumed to
    accept, the same "auto-chosen, no chooser in MVP" call this codebase
    already makes for an untargeted optional decision elsewhere
    (`_discard_instead_of_non_first_draw_replacement`'s own docstring, for
    Chains of Mephistopheles), and a reasonable one here specifically since
    accepting is pure upside for every player who's offered it. The
    counters land on that player's own commander if they control one, else
    the first creature on the battlefield in board order — deterministic,
    not a real choice.

    "For each opponent who does" then reads back which opponents actually
    received counters (only players who controlled a creature at all) and
    grants this effect's own controller one `PlayerShieldEffect` per such
    opponent (RULE 611.2b "until your next turn", swept in `GameEngine.
    begin_turn`) — see that class's own docstring for the damage-only scope
    "protection from a player" covers here.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        state = context.state
        accepted: list["Player"] = []
        for player in state.living_players():
            creatures = [
                o for o in state.battlefield
                if o.controller_id == player.id and o.is_creature
            ]
            if not creatures:
                continue
            chosen = next((o for o in creatures if o.is_commander), creatures[0])
            chosen.add_counters("+1/+1", 2)
            accepted.append(player)
        if accepted:
            context.recompute()
        for player in accepted:
            if player.id == controller.id:
                continue
            controller.player_effects.append(PlayerShieldEffect(
                life_locked=False, protection_from_everything=False,
                protected_from_player_id=player.id,
                until_next_turn_of=controller.id, source=self.source,
            ))


class ReturnSharedTypePermanentEffect(GameEffect):
    """"You may return another permanent you control that shares a permanent
    type with it to its owner's hand." (Cloudstone Curio) — the bounce half
    of a RULE 603.1 "whenever a permanent enters" trigger.

    "Shares a permanent type **with it**" is why this can't be an ordinary
    `ReturnToHandEffect` with a target kind: the legal set depends on the
    *entering* permanent, which is only known per firing. It is read off
    `GameContext.trigger_event`'s ``instance_id``/``object_types``, and the
    candidate list is narrowed to permanents sharing at least one of those
    main types (RULE 205.2a) excluding the trigger's own subject.

    *Which* matching permanent to return is the controller's own choice,
    offered through the general `GameContext.choose_objects` chooser — and
    optional there as well as on the trigger itself, so declining at either
    prompt leaves the board alone.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None:
            return
        entering = context.state.find_object(event.get("instance_id"))
        if entering is None:
            return
        wanted = {t for t in entering.type_words if t in _PERMANENT_TYPE_WORDS}
        candidates = [
            obj
            for obj in context.state.permanents()
            if obj is not entering
            and obj.controller_id == entering.controller_id
            and wanted & set(obj.type_words)
        ]
        controller = context.state.player_by_id(entering.controller_id)
        if candidates and controller is not None:
            context.choose_objects(
                controller, candidates, "return_to_hand", count=1, optional=True,
                prompt="Cloudstone Curio: Wähle ein bleibendes Objekt zum Zurücknehmen",
                source=self.source,
            )


class ExileTriggerDamagedCreatureEffect(GameEffect):
    """"Whenever this creature deals combat damage to a creature, exile
    that creature." (Kaldra Compleat-shaped — a Living Weapon's granted
    ability, RULE 613.7f) — RULE 603.3d's "that creature" pronoun refers to
    the `DAMAGE` event's *recipient*, not its source: `_GRANTED_EVENT_KEYS`
    scopes *which grantee* reacts off the event's ``source_id`` (the
    equipped creature that dealt the damage — "this creature"), a different
    field from who was hit. No target choice at all — `GameContext.
    trigger_event`'s own ``target_id`` (ENG-13's general per-firing dynamic
    reference) names the exact object, the granted-ability counterpart of
    what `TriggeredAbility.reflexive` does for an ordinary "that
    permanent/spell" off ``instance_id``. A damaged *player* (``is_player``)
    or a since-departed creature is simply nothing to exile.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None or event.get("is_player"):
            return
        creature = context.state.find_object(event.get("target_id"))
        if creature is None:
            return
        context.exile(creature)


class LoseGameTriggerDamagedPlayerEffect(GameEffect):
    """"…that player loses the game…" (Frodo, Sauron's Bane) — RULE 603.3d's
    "that player" pronoun refers to the `DAMAGE` event's *recipient*, the
    exact mirror of `ExileTriggerDamagedCreatureEffect` for a player instead
    of a creature: no target choice, `GameContext.trigger_event`'s own
    ``target_id`` is the damaged player's id (`is_player`). A damaged
    creature or a since-departed player is simply nothing to make lose.
    """

    def __init__(self, reason: str = "effect", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.reason = reason

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None or not event.get("is_player"):
            return
        context.lose_game(context.state.player_by_id(event.get("target_id")), self.reason)


class AddCountersToTriggerDamagedPlayerEffect(GameEffect):
    """"Whenever this creature deals combat damage to a player, they get
    that many poison counters." (Etali, Primal Sickness) — RULE 603.3d's
    "they"/"that many" pronouns both refer to the `DAMAGE` event's own
    recipient and amount: the counter-granting mirror of `LoseGameTrigger
    DamagedPlayerEffect`, sharing its "no target choice, read `GameContext.
    trigger_event` directly" shape rather than a chosen target and a fixed
    amount. A damaged creature, a since-departed player, or a zero-amount
    event (already-prevented/replaced damage) is simply nothing to counter.
    """

    def __init__(self, kind: str = "poison", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.kind = kind

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None or not event.get("is_player"):
            return
        player = context.state.player_by_id(event.get("target_id"))
        if player is None:
            return
        amount = event.get("amount") or 0
        if amount <= 0:
            return
        context.add_player_counters(player, amount, self.kind, source=self.source)


#: RULE 205.2a's permanent card types — the vocabulary "shares a permanent
#: type with it" (Cloudstone Curio) compares against, so a shared *spell*
#: type (instant/sorcery, which no permanent has anyway) can never match.
_PERMANENT_TYPE_WORDS: frozenset[str] = frozenset(
    {"artifact", "creature", "enchantment", "land", "planeswalker", "battle"}
)


def _printed_main_types(card: Any) -> set[str]:
    """The lowercased main-type words on a printed type line (before the em
    dash), for a card *not* on the battlefield (so `GameObject.type_words`'
    always-on "permanent" doesn't apply)."""
    head = str(getattr(card, "type_line", "") or "").partition("—")[0]
    return {w for w in head.strip().lower().split() if w}


class RandomGraveyardExileCopyLoopEffect(GameEffect):
    """"Exile a permanent card from your graveyard at random, then create a
    tapped token that's a copy of that card. If the exiled card is a land
    card, repeat this process." (Sin, Spira's Punishment) — RULE 706
    randomization + RULE 707.2 token copy, looped while each exiled card is
    a land (so it terminates the moment a non-land is hit, or the graveyard
    runs out of permanent cards)."""

    #: A graveyard can't realistically hold this many permanent cards; a
    #: hard stop regardless, so a modeling slip can't spin forever.
    MAX_ITER = 200

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for _ in range(self.MAX_ITER):
            pool = [
                o for o in list(player.graveyard)
                if _printed_main_types(o.card) & _PERMANENT_TYPE_WORDS
            ]
            if not pool:
                return
            chosen = context.engine.random_choice(pool)
            player.remove_from_zone(chosen, Zone.GRAVEYARD)
            player.add_to_zone(chosen, Zone.EXILE)
            context.state.fire_event(
                GameEvent(
                    EventType.EXILE, player_id=player.id, object=chosen.name,
                    from_zone="graveyard",
                )
            )
            made = context.engine.create_token(player.id, chosen.card, 1) or []
            for tok in made:
                tok.tapped = True
            context.created_objects.extend(made)
            if "land" not in _printed_main_types(chosen.card):
                return


class PutFromHandOntoBattlefieldEffect(GameEffect):
    """"Put up to two creature cards from your hand onto the battlefield."
    (Tooth and Nail's second mode) — RULE 701.19-adjacent, but from **hand**.

    Every other "put onto the battlefield" shape in the engine moves a card
    out of a library (a search) or a graveyard (reanimation); none opens an
    arbitrary pick from hand. Reuses `RulesEngine._request_search`'s
    interactive one-at-a-time choice machinery by searching the ``"hand"``
    zone, so the UI, the undo snapshots and the "up to N" semantics are
    identical to every other pick — rather than a parallel choice kind that
    would need its own wiring in the session and the frontend.

    ``tapped=True`` (Horizon of Progress's "…onto the battlefield
    **tapped**") just switches the search destination to the existing
    ``"battlefield_tapped"`` string `_put_searched_card` already handles —
    no new engine behaviour, only Tooth and Nail's own untapped default
    ever exercised the other branch before.
    """

    def __init__(
        self,
        criteria: Any = "",
        count: int = 1,
        tapped: bool = False,
        attacking: bool = False,
        trigger_attacks: bool = False,
        max_mana_value_selector: Optional[str] = None,
        power_less_than_source: bool = False,
        miss_effect_specs: Optional[list[dict]] = None,
        zones: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
        max_mana_value_from_trigger: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.criteria = criteria
        self.count = count
        self.tapped = tapped
        #: "…a permanent card with mana value less than or equal to **that damage**…" (Broodcaller Scourge) —
        #: the firing event's field (``"matching_amount"``: the combat damage its matched Dragons dealt)
        #: that caps the pick's mana value, read at `apply` time.
        self.max_mana_value_from_trigger = max_mana_value_from_trigger
        #: "…from your hand **or graveyard**…" (Dread Tiller) — the pool to
        #: pick from, defaulting to hand only (`_request_search` already
        #: takes a multi-zone list). Every other caller stays hand-only.
        self.zones = list(zones) if zones else ["hand"]
        #: "If you don't put a card onto the battlefield this way, <body>."
        #: (The Vast Scrier) — serialized `EffectSpec` dicts run when the
        #: from-hand pick places nothing (declined / nothing eligible),
        #: threaded through `_request_search`'s ``then_specs_if_none``.
        self.miss_effect_specs = list(miss_effect_specs or [])
        #: "…onto the battlefield tapped **and attacking**." (RULE 508.4 —
        #: Preeminent Captain, Kaalia of the Vast). Routes to the
        #: ``"battlefield_attacking"`` search destination, which enters the
        #: card tapped and calls `RulesEngine.put_onto_battlefield_attacking`.
        self.attacking = attacking
        #: A card can explicitly override RULE 508.3a after putting the
        #: creature into combat (The Vast Scrier: "those trigger"). This is
        #: deliberately separate from ordinary ``attacking`` entry.
        self.trigger_attacks = bool(trigger_attacks)
        #: "…creature card **with mana value X or less** … where X is the
        #: number of attacking creatures you control." (Kinscaer Sentry) —
        #: a `continuous.count_selector` name resolved at `apply` time and
        #: folded into ``criteria`` as a `max_mana_value` cap.
        self.max_mana_value_selector = max_mana_value_selector
        #: "…creature card **with lesser power** …" (Shadowfax, Lord of
        #: Horses) — strictly less printed power than this effect's source,
        #: resolved at `apply` time into a `max_power` cap.
        self.power_less_than_source = bool(power_less_than_source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        if self.attacking and self.trigger_attacks:
            destination = "battlefield_attacking_triggering"
        elif self.attacking:
            destination = "battlefield_attacking"
        elif self.tapped:
            destination = "battlefield_tapped"
        else:
            destination = "battlefield"
        criteria = self.criteria
        if self.max_mana_value_from_trigger:
            raw = (getattr(context, "trigger_event", None) or {}).get(self.max_mana_value_from_trigger)
            criteria = dict(criteria) if isinstance(criteria, dict) else {}
            # No such field on the event → nothing is affordable (fail closed), not an uncapped pick.
            criteria["max_mana_value"] = int(raw) if isinstance(raw, int) and not isinstance(raw, bool) else -1
        if self.max_mana_value_selector or self.power_less_than_source:
            from .. import continuous  # function-scoped: avoid an import cycle

            criteria = dict(criteria) if isinstance(criteria, dict) else {}
            if self.max_mana_value_selector:
                controller_id = getattr(self.source, "controller_id", None)
                criteria["max_mana_value"] = continuous.count_selector(
                    context.state, controller_id, self.max_mana_value_selector,
                    source=self.source,
                )
            if self.power_less_than_source:
                src_power = getattr(self.source, "power", None)
                # No power on the source → nothing has "lesser power" → an
                # impossible cap (fail closed) rather than an open pick.
                criteria["max_power"] = (src_power - 1) if src_power is not None else -1
        count = int(getattr(self.source, "x_paid", 0) or 0) if self.count == "x" else self.count
        context._request_search(
            player, criteria, destination, count, optional=True, zones=list(self.zones),
            then_specs_if_none=self.miss_effect_specs or None, source=self.source,
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — naming a card, and the three loop shapes
# ---------------------------------------------------------------------------


class NameCardThenEffect(GameEffect):
    """"Choose a card name. `<effect>`" (Demonic Consultation) — RULE 701's
    naming action, which no `pending_choice` could express before: every
    other choice in the engine picks from an enumerable set, and a player
    may name *any* card in Magic, including one nowhere in this game.

    `RulesEngine._request_name_card` therefore offers the names the player
    can actually see (their own hand/library/graveyard) as suggestions while
    accepting an arbitrary string, and substitutes it into the follow-up
    effects' ``"named_card"`` criteria sentinel — the naming counterpart of
    `_substitute_x`'s ``"x"``. The string is only ever *compared against*
    card names, never interpreted, so nothing derived from it becomes
    behaviour (docs/09's security boundary).
    """

    def __init__(
        self,
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.inner_specs = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine._request_name_card(player, self.inner_specs, self.source)


class ExileUntilDuplicateNameEffect(GameEffect):
    """"Exile the top card of your library. You may put that card into
    your hand unless it has the same name as another card exiled this
    way. Repeat this process until you put a card into your hand or you
    exile two cards with the same name, whichever comes first." (RULE
    701.19-adjacent — Tainted Pact) — see `RulesEngine.
    exile_until_duplicate_name`'s docstring for why this is a genuinely
    different loop shape from `DigUntilEffect`, not a special case of it.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.exile_until_duplicate_name(player)


class TransmuteArtifactEffect(GameEffect):
    """"Sacrifice an artifact. If you do, search your library for an
    artifact card. If that card's mana value is less than or equal to the
    sacrificed artifact's mana value, put it onto the battlefield. If
    it's greater, you may pay {X}, where X is the difference. If you do,
    put it onto the battlefield. If you don't, put it into its owner's
    graveyard. Then shuffle." (Transmute Artifact) — see `RulesEngine.
    transmute_artifact`'s own docstring for why this is one self-contained
    bespoke sequence rather than composed from the general search/
    sacrifice/`pay_cost_then` primitives.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.transmute_artifact(player)


class DigUntilEffect(GameEffect):
    """"Reveal/exile cards from the top of your library until `<predicate>`"
    (Demonic Consultation, Tibalt's Trickery, Possibility Storm) — the
    generalized form of the cascade/discover dig, which was hard-wired to
    "nonland cheaper than N, may cast it, rest to the bottom".

    Both the predicate (``criteria``, a `models.cards.card_query` dict — including
    the new ``not_name`` for "a different name than that spell") and both
    destinations are parameters here. ``pre_exile`` is Demonic
    Consultation's "exile the top six cards" prologue, which happens before
    the dig and is never part of it.

    ``criteria`` may carry the ``"named_card"`` sentinel — the name just
    chosen (see `NameCardThenEffect`), substituted at answer time rather
    than baked in. The *spell*-derived predicates ("a different name than
    that spell", "shares a card type with it") live on
    `ScrambleSpellEffect` instead, which has the answered spell in hand.

    ``digger`` / ``caster`` (MEC-52 — Ensnared by the Mara, villainous
    option A: "**They** exile cards from the top of **their** library until
    they exile a nonland card, then **you** may cast that card without
    paying its mana cost") split the two players a villainous-option dig
    involves: ``digger="facing"`` reads off the library of the facing
    player this option was applied against (``targets[0]``) rather than the
    effect's own controller, and ``caster="controller"`` routes the free-
    cast window / free cast to the effect's controller (RULE 601.3e — a
    player casting a card they don't own becomes its controller) rather
    than the digger. Both default to the plain "your library, you cast it"
    shape.
    """

    def __init__(
        self,
        criteria: Any = "",
        hit_destination: str = "hand",
        rest_destination: str = "exile",
        pre_exile: int = 0,
        digger: str = "controller",
        caster: str = "digger",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.criteria = criteria
        self.hit_destination = hit_destination
        self.rest_destination = rest_destination
        self.pre_exile = int(pre_exile)
        self.digger = digger
        self.caster = caster

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.digger == "facing":
            player = targets[0] if targets else None
        elif self.digger == "previous_target_controller":
            # "…its controller exiles cards from the top of their library until they exile a nonland
            # card, then they may cast it" (Transforming Flourish) — the controller of the permanent
            # an earlier clause of this resolution destroyed (last-known: it already left the board).
            previous = context.previous_targets[0] if context.previous_targets else None
            player = context.state.player_by_id(getattr(previous, "controller_id", None))
        else:
            player = _controller_of(self.source, context)
        if player is None or not hasattr(player, "library"):
            return
        caster = (
            _controller_of(self.source, context)
            if self.caster == "controller" else None
        )
        context.engine.dig_until(
            player,
            self.criteria,
            hit_destination=self.hit_destination,
            rest_destination=self.rest_destination,
            pre_exile=self.pre_exile,
            caster=caster,
        )


class MillUntilCreatureEffect(GameEffect):
    """"Target opponent mills a card, then repeats this process until a
    creature card or X cards have been put into their graveyard this way,
    whichever comes first. If one or more creature cards were put into that
    graveyard this way, sacrifice this artifact and put one of them onto the
    battlefield under your control." (Helm of Obedience)

    The engine's first **repeat-until-a-predicate-holds** loop: every other
    repetition primitive here has a count fixed before it starts (mill N,
    draw N, proliferate). Here the count is a *cap* and the real stopping
    condition is what the mill turned up, so the loop has to check after
    each iteration.

    Bounded on both sides by construction — ``X`` caps the iterations and an
    empty library ends it early — so this cannot spin, which is the property
    that makes a "repeat until" primitive safe to have at all.

    Note the reanimated creature comes back under **your** control, not its
    owner's (RULE 110.2), and the Helm sacrifices itself only when the mill
    actually hit a creature (RULE 701.16c: sacrifice, not destruction).
    """

    def __init__(
        self,
        amount: Any = 0,
        target_kind: str = "player",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        victim = targets[0] if targets else None
        cap = self.amount if isinstance(self.amount, int) else 0
        if victim is None or not hasattr(victim, "graveyard") or cap <= 0:
            return  # "X can't be 0."
        found: list[Any] = []
        for _ in range(cap):
            if not victim.library:
                break
            context.mill(victim, 1)
            milled = victim.graveyard[-1] if victim.graveyard else None
            if milled is not None and milled.is_creature:
                found.append(milled)
                break
        if not found:
            return
        controller = _controller_of(self.source, context)
        if self.source is not None and self.source in context.state.permanents():
            context.put_into_graveyard(self.source)
        context.return_from_graveyard(
            found[0], "battlefield",
            controller_id=controller.id if controller is not None else None,
        )


class LookTopPayLifeLoopEffect(GameEffect):
    """"Look at the top five cards of your library. As many times as you
    choose, you may pay 1 life, put those cards on the bottom of your
    library in any order, then look at the top five cards. Then shuffle and
    put the last cards you looked at on top in any order." (Lim-Dûl's Vault)

    The engine's first **open-ended** loop: every other repetition here has
    a fixed count or a hard cap (`MillUntilCreatureEffect`'s X, a search's
    "up to N"). Here the player decides after each iteration whether to go
    again, so it's driven by a `pending_choice` that re-opens itself —
    the same self-re-opening shape a multi-card search already uses, but
    with no counter running down.

    It is still bounded in practice by the payment: each iteration costs 1
    life, so it can run at most `Player.life` - 1 times, and the choice is
    simply not offered once the player can't pay. That is the card's own
    natural bound, not a safety cap bolted on.

    **Documented simplification**: "in any order" is not an interactive
    reorder — the five cards keep their relative order when bottomed, and
    the final five are left on top as they lie. The card is played to *find*
    a specific card, and the top card is what the next draw takes either
    way; a full five-card ordering UI is a separate feature.
    """

    def __init__(
        self,
        count: int = 5,
        life_cost: int = 1,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = int(count)
        self.life_cost = int(life_cost)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine._request_look_top_pay_life_loop(player, self.count, self.life_cost)


class RevealTopHandLoseLifeLoopEffect(GameEffect):
    """"Reveal the top card of your library and put that card into your
    hand. You lose life equal to its mana value. You may repeat this
    process any number of times." (Ad Nauseam, MEC-41) — see `RulesEngine.
    _request_reveal_top_hand_lose_life_loop`'s own docstring for why this is
    a distinct open-ended loop from `LookTopPayLifeLoopEffect` just above,
    not a parameterization of it.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine._request_reveal_top_hand_lose_life_loop(player)


class ScrambleSpellEffect(GameEffect):
    """The "answer a spell, then dig its controller's library for a
    replacement they may cast free" family — Possibility Storm and Tibalt's
    Trickery, which differ only in *how* the original spell is answered and
    what predicate the dig uses.

    One atomic effect rather than a composition, for the reason the paired-
    clause effects in this file already document: every clause acts on the
    *same* spell and on **its controller** (never the effect's own
    controller), and the dig's predicate is derived from that spell — none
    of which a separate `counter` + `mill` + `dig_until` chain could thread
    between its members.

    ``answer`` is ``"counter"`` (Tibalt's Trickery) or ``"exile"``
    (Possibility Storm, whose "that player exiles it" is a zone change, not
    a counter — which is why it also gets around "can't be countered").
    ``mill_random_max``, when set, mills the spell's controller a random
    1..N first (Tibalt's Trickery's "choose 1, 2, or 3 at random" — genuine
    randomness the card itself demands, not an engine shortcut).

    The replacement card is *offered*, never force-cast: the hit gets the
    same exile free-cast window Rebound and Beseech the Mirror use, and a
    delayed trigger performs the printed "put it on the bottom of their
    library" fallback at the next end step if they don't take it.
    ``match`` picks the dig predicate: ``"different_name"`` (a nonland card
    not named like the answered spell) or ``"shares_card_type"`` (RULE
    205.2, read off the answered spell's own main types).
    """

    def __init__(
        self,
        answer: str = "counter",
        match: str = "different_name",
        mill_random_max: int = 0,
        card_types: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.answer = answer
        self.match = match
        self.mill_random_max = int(mill_random_max)
        spell_filter: dict[str, Any] = {}
        if card_types:
            spell_filter["card_types"] = list(card_types)
        self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        item = context.engine._stack_item_for(target)
        if item is None or item.obj is None:
            return
        spell = item.obj
        try:
            caster = context.state.player_by_id(item.controller_id)
        except (KeyError, ValueError):
            return
        # Snapshot before the spell leaves the stack — both the dig
        # predicate and the mill are about *that* spell and *its* controller.
        name = spell.name
        types = [t for t in spell.type_words if t != "permanent"]

        if self.answer == "exile":
            context.engine.move_spell_off_stack(item, "exile")
        else:
            context.engine.counter_spell(item)

        if self.mill_random_max > 0:
            context.mill(caster, random.randint(1, self.mill_random_max))

        if self.match == "shares_card_type":
            criteria: dict[str, Any] = {"type": types or ["__none__"]}
        else:
            criteria = {"not_name": name}
        context.engine.dig_until(
            caster,
            criteria,
            # "That player **may** cast that card without paying its mana
            # cost" — an offer, not a forced cast (see `_place_dig_hit`).
            hit_destination="cast_free_window",
            rest_destination="library_bottom_random",
        )


class LegendarySpellFreeDigEffect(GameEffect):
    """"Whenever you cast a legendary spell from your hand, exile cards from
    the top of your library until you exile a legendary nonland card with
    lesser mana value. You may cast that card without paying its mana
    cost. Put the rest on the bottom of your library in a random order."
    (MEC-43 round 4D, Jodah, the Unifier) — the free-cast dig family's
    "legendary"-qualified member: `RulesEngine.dig_until` (the cascade/
    Possibility Storm-shaped generalized dig, criteria + both destinations
    parameterized) with a criteria dict built fresh from *this firing's
    own* `GameContext.trigger_event` (RULE 603.1 — the just-cast spell's
    own mana value, read off `EventType.SPELL_CAST`'s existing
    ``mana_value`` key) rather than a literal/selector amount the way
    every other `dig_until` caller supplies one. Unlike `ScrambleSpellEffect`
    (Possibility Storm/Tibalt's Trickery) the triggering spell is never
    answered — it resolves completely normally; only the dig for a
    *replacement* card is new behaviour here, so this needs no
    `target_spec` at all.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        event = context.trigger_event or {}
        mana_value = event.get("mana_value")
        if player is None or mana_value is None:
            return
        criteria = {
            "type": ["Legendary"],
            "without_type": ["Land"],
            "max_mana_value": mana_value - 1,
        }
        context.engine.dig_until(
            player, criteria,
            hit_destination="cast_free_window",
            rest_destination="library_bottom_random",
        )


class PutEqualOrLesserManaValueFromHandEffect(GameEffect):
    """"Whenever another permanent you control enters, if it wasn't put
    onto the battlefield with this ability, you may put a permanent card
    with equal or lesser mana value from your hand onto the battlefield."
    (MEC-43 round 4D, Kodama of the East Tree) — the dynamic-cap sibling
    of `PutFromHandOntoBattlefieldEffect` (Tooth and Nail): the ceiling
    isn't a literal baked into the spec, it's *this firing's own*
    entering permanent's mana value (RULE 603.1, read off `GameContext.
    trigger_event`'s ``instance_id``) rather than something the catalogue
    could supply ahead of time. Uses `RulesEngine._request_choose_objects`'s
    new ``"hand_to_battlefield"`` action (rather than
    `PutFromHandOntoBattlefieldEffect`'s `_request_search`) specifically so
    the new pick gets `GameObject.entered_via_ability_id` stamped — the
    printed "if it wasn't put onto the battlefield with this ability"
    guard on Kodama's own trigger (`effect_binder`'s
    ``not_entered_via_self`` condition) reads it back to avoid
    re-triggering off this ability's own puts.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        event = context.trigger_event or {}
        entering = context.state.find_object(event.get("instance_id"))
        if player is None or entering is None or self.source is None:
            return
        max_mv = entering.card.converted_mana_cost
        candidates = [
            obj for obj in player.hand
            if card_query.matches(obj.card, {
                "type": ["Creature", "Artifact", "Enchantment", "Planeswalker", "Battle", "Land"],
                "max_mana_value": max_mv,
            })
        ]
        context.engine._request_choose_objects(
            player, candidates, "hand_to_battlefield", count=1, optional=True,
            prompt="Permanentenkarte auf das Schlachtfeld legen",
            source=self.source,
        )


class ExileCastSpellIntoImprintPoolEffect(GameEffect):
    """RULE 603.3d reflexive trigger body: "Whenever a player casts a spell
    from their hand, that player exiles it. If the player does, they may
    cast a spell from among other cards exiled with this artifact without
    paying its mana cost." (Knowledge Pool, MEC-43 round 4G).

    The trigger condition/reflexive-target shape is identical to
    Possibility Storm's own "whenever a player casts a spell from their
    hand, that player exiles it" (`EventType.SPELL_CAST`, ``filter={
    "from_hand": True}``, ``reflexive=True`` — no ``condition`` at all,
    since "**a player**" is deliberately unscoped, matching every player at
    the table, not just this artifact's controller). It diverges from
    `ScrambleSpellEffect` right where Possibility Storm digs a *fresh*
    replacement from the caster's own library: Knowledge Pool's
    replacement pool is instead the *shared*, ever-growing set of cards
    already exiled with this permanent (`GameObject.exiled_with_ids`,
    MEC-21) — seeded by the ETB imprint (`ExileTopOfLibraryEffect`'s own
    ``track_exiled_with``) and grown by this effect's own exile, never dug
    fresh from anyone's library.

    "They may cast a spell from **among** other cards exiled with this
    artifact" is a genuine choice among 0+ candidates (every pool member
    except the one just added by this same resolution) —
    `RulesEngine._request_choose_objects`'s ``"grant_free_cast"`` action
    (MEC-20's Expertise-cycle primitive: arms the *one* chosen card's
    free-cast window rather than casting it immediately, so the caster
    still gets full RULE 115 targeting through the ordinary `legal_actions`
    cast option). That action already works for an exiled card exactly as
    well as a hand one — `GameEngine.can_cast`'s castable-zone check has an
    ``obj.zone == Zone.EXILE and self._has_temp_play_permission(...)``
    branch for exactly this (Rebound/Beseech the Mirror) — so arming only
    the chosen candidate (not every pool member at once) is what keeps this
    "cast **a** spell", singular, rather than silently granting a free cast
    of the *whole* remaining pool every time a spell is cast.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="spell")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        target = targets[0] if targets else None
        item = context.engine._stack_item_for(target)
        if item is None or item.obj is None:
            return
        spell = item.obj
        try:
            caster = context.state.player_by_id(item.controller_id)
        except (KeyError, ValueError):
            return
        context.engine.move_spell_off_stack(item, "exile")
        # RULE 603.3d "that player exiles **it**" — join the shared pool
        # this permanent tracks (MEC-21), the same accounting the ETB
        # imprint already used, so a later cast sees every card ever
        # exiled this way, not just the newest one.
        self.source.exiled_with_ids.append(spell.instance_id)
        candidates = [
            obj for obj in (
                context.state.find_object(iid)
                for iid in self.source.exiled_with_ids
                if iid != spell.instance_id
            )
            if obj is not None and obj.zone == Zone.EXILE
        ]
        if not candidates:
            return
        context.engine._request_choose_objects(
            caster, candidates, "grant_free_cast", count=1, optional=True,
            prompt=f"{self.source.name}: Karte ohne Bezahlen ihrer Manakosten wirken?",
            source=self.source,
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — Fading, Soulbond, Mutate (RULE 702.32/702.94/702.140)
# ---------------------------------------------------------------------------


class RemoveCounterOrSacrificeEffect(GameEffect):
    """Fading's upkeep half (RULE 702.32b): "At the beginning of your upkeep,
    remove a fade counter from this permanent. If you can't, sacrifice it."

    Note the "if you can't" is about there being **no counter left**, not
    about any choice — a permanent at 0 fade counters is sacrificed, which
    is why Fading N lasts N+1 of your upkeeps rather than N. ``sacrifice_
    on_last_removed`` switches to Vanishing's (RULE 702.61b) own phrasing —
    "remove a time counter... When the last is removed, sacrifice it" —
    which has no such off-by-one: the removal that empties the counter
    sacrifices the permanent in that same upkeep, one upkeep sooner than
    Fading's "counters already gone" check would.

    Sacrifice, never destruction (RULE 701.16c), so nothing can regenerate
    or "if it would die, exile it instead" its way out.
    """

    def __init__(
        self, kind: str = "fade", source: Optional["GameObject"] = None,
        sacrifice_on_last_removed: bool = False,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.sacrifice_on_last_removed = sacrifice_on_last_removed

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        if obj is None or obj not in context.state.permanents():
            return
        if obj.counters.get(self.kind, 0) > 0:
            obj.add_counters(self.kind, -1)
            if self.sacrifice_on_last_removed and obj.counters.get(self.kind, 0) <= 0:
                context.put_into_graveyard(obj)
            return
        context.put_into_graveyard(obj)


class SuspendUpkeepEffect(GameEffect):
    """RULE 702.62a's 2nd+3rd Suspend abilities, combined the same way
    Vanishing's own upkeep pair already is (`RemoveCounterOrSacrificeEffect`
    above): "At the beginning of your upkeep, if this card is suspended,
    remove a time counter from it," then "When the last time counter is
    removed from this card, if it's exiled, you may play it without paying
    its mana cost if able."

    Unlike Vanishing, ``source`` here is never a permanent — a suspended
    card sits in exile the whole time (RULE 702.62b), so there's nothing to
    sacrifice at zero; instead the free-cast window opens exactly the way
    Rebound's own delayed half does (`ReboundFreeCastWindowEffect` →
    `RulesEngine.grant_free_cast_window_from_exile`), including that
    primitive's documented same-turn-only simplification for the "you may"
    choice. `granted_suspend_haste` arms RULE 702.62a's trailing "if you
    cast a creature spell this way, it gains haste" clause, consumed once
    at resolution by `RulesEngine._resolve_permanent_spell` exactly like
    `cast_via_evoke`.

    Collected fresh each owner's-upkeep by `_collect_suspend_triggers`
    (`game/rules/triggers_mixin.py`) rather than bound once at load time —
    a card can become suspended mid-game with no printed Suspend at all
    (Delay's granted suspend), so there's no permanent `TriggeredAbility`
    to have pre-attached one to.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        if obj is None or obj.zone != Zone.EXILE or obj.counters.get("time", 0) <= 0:
            return
        context.engine.remove_suspend_time_counter(obj)


def _scale_cumulative_upkeep_cost(cost: "ActivationCost", n: int) -> "ActivationCost":
    """RULE 702.24b: "…unless you pay its upkeep cost **for each age
    counter** on it" — the whole printed cost, paid ``n`` times over, not a
    single payment scaled by a multiplier read elsewhere. For a mana cost
    that's the same thing either way (three payments of ``{G}`` and one
    payment of ``{G}{G}{G}`` cost identically much), so this repeats the
    parsed cost's own mana symbols/``pay_life`` ``n`` times — correct for
    the overwhelming majority of printed Cumulative Upkeep costs (plain
    mana, or "pay N life").

    **Documented simplification**: a non-numeric cost component
    (``sacrifice``/``discard``/``tap_others``/``return_to_hand``/…, "tap an
    untapped white creature you control"-shaped) is left un-scaled — paid
    once regardless of the age-counter count — since "pay this cost N
    *separate* times" (tap N different creatures, sacrifice N different
    permanents) is a distinct, more general primitive genuinely unbuilt
    both here and in `RulesEngine._request_sacrifice_unless_pay`'s existing
    RULE 701.17 machinery this reuses.
    """
    from dataclasses import replace

    from ...models.mana.mana_cost import ManaCost

    scaled_mana = ManaCost(list(cost.mana.symbols) * n, raw=cost.mana.raw)
    return replace(cost, mana=scaled_mana, pay_life=cost.pay_life * n)


class CumulativeUpkeepEffect(GameEffect):
    """RULE 702.24b: "At the beginning of your upkeep, put an age counter
    on this permanent, then sacrifice it unless you pay its upkeep cost
    for each age counter on it."

    The age counter goes on **first, unconditionally** every upkeep — the
    opposite direction from Fading's off-by-one-free "remove, then check"
    shape (`RemoveCounterOrSacrificeEffect`), since this one only ever
    adds, never runs out on its own. The scaled payment
    (`_scale_cumulative_upkeep_cost`) reuses the exact same pay-or-
    sacrifice machinery a plain "Sacrifice ~ unless you pay `<cost>`"
    already rides (RULE 701.17, `SacrificeUnlessPayEffect` →
    `RulesEngine._request_sacrifice_unless_pay`), just with the parsed cost
    multiplied by however many age counters the permanent now carries.
    """

    def __init__(self, cost: str = "", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        obj = self.source
        if obj is None or obj not in context.state.permanents():
            return
        obj.add_counters("age", 1)
        n = obj.counters.get("age", 0)
        base = parse_activation_cost(self.cost_text)
        if base.is_free or n <= 0:
            return
        player = _controller_of(obj, context)
        if player is None:
            return
        context.engine._request_sacrifice_unless_pay(
            player, _scale_cumulative_upkeep_cost(base, n), obj
        )


class TapPermanentsPerCounterEffect(GameEffect):
    """"That player taps an untapped artifact, creature, or land they control
    for each fade counter on this artifact." (Tangle Wire) — a per-player
    tax whose *magnitude* is read live off the source's own counters, so it
    shrinks each upkeep as Fading counts down.

    *Which* permanents get tapped is the taxed player's own choice (RULE
    701.21a) — and on this card it is the whole decision, since leaving the
    right permanents open is what playing against a Tangle Wire consists
    of. Offered through the general `GameContext.choose_objects` chooser,
    one at a time; with N or fewer candidates it taps them all without
    asking, because there is nothing left to decide.
    """

    def __init__(
        self,
        kind: str = "fade",
        types: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.types = [t.lower() for t in (types or ["artifact", "creature", "land"])]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        event = context.trigger_event
        if obj is None or event is None:
            return
        # "each player's upkeep" — the taxed player is whoever's turn it is,
        # since `STEP_BEGIN` carries no player of its own (see the
        # `phase_relation` predicate in `effect_binder`).
        player = context.state.active_player
        remaining = obj.counters.get(self.kind, 0)
        if remaining <= 0:
            return
        candidates = [
            candidate
            for candidate in context.state.permanents_controlled_by(player.id)
            if not candidate.tapped and (set(candidate.type_words) & set(self.types))
        ]
        context.choose_objects(
            player, candidates, "tap", count=remaining,
            prompt=f"{obj.name}: Wähle ein bleibendes Objekt zum Tappen",
            source=obj,
        )


class SacrificePermanentsPerCounterEffect(GameEffect):
    """"At the beginning of each player's upkeep, that player sacrifices a
    permanent of their choice for each soot counter on this artifact."
    (Smokestack, MEC-43 round 4E) — the sacrifice-costed sibling of
    `TapPermanentsPerCounterEffect` (Tangle Wire): same "read the count
    live off the source's own counters, offer N picks via the general
    chooser, one at a time" shape, just every permanent (no type or
    untapped-only filter, unlike Tangle Wire's own artifact/creature/land
    restriction) and ``action="sacrifice"`` instead of ``"tap"``.
    """

    def __init__(
        self,
        kind: str = "soot",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        event = context.trigger_event
        if obj is None or event is None:
            return
        # "each player's upkeep" — the taxed player is whoever's turn it
        # is, since `STEP_BEGIN` carries no player of its own (see
        # `TapPermanentsPerCounterEffect`'s identical comment).
        player = context.state.active_player
        remaining = obj.counters.get(self.kind, 0)
        if remaining <= 0:
            return
        candidates = list(context.state.permanents_controlled_by(player.id))
        context.choose_objects(
            player, candidates, "sacrifice", count=remaining,
            prompt=f"{obj.name}: Wähle eine bleibende Karte zum Opfern",
            source=obj,
        )


class SoulbondPairEffect(GameEffect):
    """Soulbond's pairing half (RULE 702.94a): "You may pair this creature
    with another unpaired creature when either enters."

    Pairing is a genuine piece of game state, not a continuous effect —
    `GameObject.paired_with` holds the partner's instance id on **both**
    objects, and RULE 702.94c breaks the pair automatically the moment
    either leaves the battlefield or changes controller
    (`RulesEngine.check_state_based_actions`).

    Fires for *either* creature entering (the Soulbond creature itself, or a
    later unpaired one joining it), which is what the printed "when either
    enters" means; a creature already paired is skipped both ways.

    *Which* creature to pair with is the controller's choice (RULE
    702.94a), offered through the general `GameContext.choose_objects`
    chooser — and on Deadeye Navigator it is the entire decision, since the
    partner is whatever you intend to blink all game. Optional there too:
    the printed "you **may** pair" means declining leaves both unpaired.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        entering = (
            context.state.find_object(event.get("instance_id")) if event else None
        )
        obj = self.source
        if obj is None or entering is None:
            return
        # RULE 702.94a: whichever of the two just entered, the pair is always
        # "this creature" + some other unpaired creature.
        if obj.paired_with is not None:
            return
        candidates = [
            o
            for o in context.state.permanents_controlled_by(obj.controller_id)
            if o is not obj and o.is_creature and o.paired_with is None
        ]
        if not candidates:
            return
        controller = context.state.player_by_id(obj.controller_id)
        if controller is None:
            return
        context.choose_objects(
            controller, candidates, "soulbond_pair", count=1, optional=True,
            prompt=f"{obj.name}: Wähle eine Kreatur zum Paaren (Seelenbund)",
            source=obj,
        )
        context.recompute()


class MutateEffect(GameEffect):
    """Mutate's merge (RULE 702.140b-d): "put this creature over or under
    target non-Human creature you own. They mutate into the creature on top
    plus all abilities from under it."

    Both directions are modeled. On top (the usual choice): the mutating
    creature's characteristics (name, P/T, types) replace the host's, and
    the host's abilities merge in underneath. Under: the host keeps its
    characteristics and gains the mutating card's abilities. Which one
    applies is chosen *as the spell is cast* (RULE 702.140a), so it rides
    `GameObject.mutate_under` rather than being decided here.

    Implemented by `RulesEngine.mutate_onto`, which keeps the *host* as the
    surviving `GameObject` either way — so its counters, damage, Auras and
    summoning-sickness state all carry over untouched (RULE 702.140c: the
    merged permanent is the same permanent, never a new object, which is
    exactly why mutate dodges "enters the battlefield" triggers).

    Fires `EventType.MUTATES` afterwards so "whenever this creature mutates"
    (Lore Drakkis) has something to trigger on.
    """

    def __init__(
        self,
        target_kind: str = "non_human_creature_you_own",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        host = targets[0] if targets else None
        if host is None or self.source is None:
            return
        context.engine.mutate_onto(
            self.source, host, under=bool(getattr(self.source, "mutate_under", False))
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — two independently-chosen targets in one clause
# ---------------------------------------------------------------------------


class AttachChosenEffect(GameEffect):
    """"Attach target Equipment you control to target creature you control."
    (Brass Squire; Halvar, God of Battle's combat trigger) — RULE 301.5c.

    The first card in this engine to need **two independently-chosen targets
    of different kinds in one clause**: the thing being attached is itself a
    target, not the ability's own source (which is what the shipped
    `AttachEffect` assumes). Expressed with `GameEffect.extra_target_specs`,
    so both requirements are gathered through the ordinary RULE 115.1
    one-at-a-time machinery and arrive here flattened in printed order:
    everything before the last pick is what moves, the last one is where it
    goes.

    ``what_kind`` widens the first requirement for Halvar, whose clause is
    "target Aura **or** Equipment attached to a creature you control".

    PAR-135 generalized the two halves independently. ``what_optional`` /
    ``what_count`` are "up to one target Equipment" / "any number of target Equipment"
    (Raubahn, Armory Automaton, Thorin); ``to_optional`` is "to up to one target creature"
    (Iron Hills Stalwart). ``to_subject`` names a destination that is **not** a target —
    the source itself (``"source"``: "attach target Equipment you control to ~", Kazuul's
    Toll Collector), the object that fired a group trigger (``"trigger_subject"``: "…to
    that creature", Sokka and Suki), the pick an earlier clause made (``"previous_target"``)
    or an Aura/Equipment's host (``"attached_permanent"``) — the same subject vocabulary
    `FightEffect` reads (`_IMPLICIT_FIGHT_SUBJECTS`), so such a clause announces only the
    Equipment requirement. The destination is the last pick, so a declined optional
    requirement can't shift which pick is which.
    """

    def __init__(
        self,
        what_kind: str = "equipment_you_control",
        to_kind: str = "creature_you_control",
        source: Optional["GameObject"] = None,
        what_optional: bool = False,
        what_count: int = 1,
        to_optional: bool = False,
        to_subject: Optional[str] = None,
        creature_filter: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.to_subject = to_subject
        self.target_spec = TargetSpec(kind=what_kind, optional=what_optional, count=what_count)
        if to_subject is None:
            # ``creature_filter`` narrows the *destination* ("…to target attacking creature", "…to target
            # Rebel you control"); the Equipment being moved has no filter of its own to carry.
            self.extra_target_specs = (
                TargetSpec(kind=to_kind, optional=to_optional, creature_filter=creature_filter),
            )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = [t for t in (targets or []) if t is not None]
        if self.to_subject is None:
            if len(picks) < 2:
                return
            *moving, host = picks
        else:
            host = _implicit_fight_subject(
                None if self.to_subject == "source" else self.to_subject, self, context
            )
            moving = picks
        if host is None:
            return
        for what in moving:
            # RULE 301.5b: a spell or ability may attach an Equipment to a creature its controller
            # doesn't control — control matters only to the equip ability itself.
            context.attach_to_target(what, host, check_control=False)


#: Subject names that are *not* a RULE 115 target choice — the five ways a
#: fight/one-sided-damage clause can name a creature without announcing a
#: requirement for it. Shared by `FightEffect` and
#: `DamageEqualToPowerEffect`, which take exactly the same subject vocabulary
#: on either side of the verb (a fight is two of these dealing damage to each
#: other; the one-sided family is one of them dealing to a target).
#:
#: * ``None`` — the effect's own source ("**it** fights …" in a trigger whose
#:   subject is that permanent, "when ~ dies, **it** deals damage equal to its
#:   power to any target");
#: * ``"attached_permanent"`` — an Aura/Equipment's current host ("when this
#:   Aura enters, **enchanted creature** fights …"), re-read live at
#:   resolution the way `TapEffect`'s attached mode does;
#: * ``"previous_target"`` / ``"previous_target_2"`` — the first/second target
#:   the *preceding* clause of this same resolution chose
#:   (`GameContext.previous_targets`): "target creature you control gets
#:   +1/+2 until end of turn. **It** fights target creature you don't
#:   control." (Epic Confrontation) and "Choose target creature you control
#:   and target creature you don't control. … Then **those creatures** fight
#:   each other." (Ancient Animus);
#: * ``"trigger_subject"`` (MEC-99) — whichever object matched this ability's
#:   own RULE 603.1 group-subject trigger condition, a different one every
#:   firing ("whenever a creature you control attacks and isn't blocked, you
#:   may have **it** deal damage equal to its power to target creature.",
#:   Gaze of Pain) — `effect_conditions.subject_of`'s own referent, shared
#:   with every other group-subject reading in this codebase rather than a
#:   bespoke lookup here.
_IMPLICIT_FIGHT_SUBJECTS: frozenset = frozenset(
    {None, "attached_permanent", "previous_target", "previous_target_2", "trigger_subject"}
)


def _implicit_fight_subject(
    kind: Optional[str], effect: "GameEffect", context: GameContext
) -> Optional[Any]:
    """Resolve one of `_IMPLICIT_FIGHT_SUBJECTS` against the live game."""
    if kind is None:
        return effect.source
    if kind == "trigger_subject":
        from .. import effect_conditions  # avoid the effect_conditions↔effects import cycle

        return effect_conditions.subject_of("trigger_subject", context, effect.source, None)
    if kind == "attached_permanent":
        host_id = getattr(effect.source, "attached_to", None)
        return context.state.find_object(host_id) if host_id is not None else None
    index = 1 if kind == "previous_target_2" else 0
    previous = getattr(context, "previous_targets", []) or []
    return previous[index] if len(previous) > index else None


class ReselectAttackEffect(GameEffect):
    """"You may reselect which player or permanent target attacking creature is attacking. (It can't
    attack its controller or their permanents.)" (Misleading Signpost) — RULE 506.3-adjacent.

    The target is any attacking creature; the ability's controller is offered every defender its own
    controller could have attacked (`GameEngine.legal_defenders_for`: opposing players, their
    planeswalkers and protected battles, `RulesEngine._attack_defender_specs`) or to keep the current one, through the `reselect_attack`
    choice. With a single possible defender there is nothing to choose and nothing is asked.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature", creature_filter={"attacking": True})

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        attacker = targets[0] if targets else None
        chooser = _controller_of(self.source, context)
        if attacker is None or chooser is None or not getattr(attacker, "attacking", False):
            return
        owner = context.state.player_by_id(attacker.controller_id)
        defenders = context.engine._attack_defender_specs(owner) if owner is not None else []
        if len(defenders) < 2:
            return
        context.engine._request_reselect_attack(chooser, attacker, defenders)


class FightEachOpposingCreatureEffect(GameEffect):
    """"For each creature your opponents control, create a 4/4 green Phyrexian Beast creature token. Each
    of those tokens fights a different one of those creatures." (Ezuri's Predation)

    The opposing creatures are snapshotted first (RULE 608.2c), one token is made per creature, and
    the *i*-th token fights the *i*-th creature. **Documented simplification:** which token fights
    which creature is fixed in battlefield order rather than chosen by the controller (every token is
    identical, so only the damage dealt to each creature is affected, and it is the same for each).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        victims = [
            o for o in context.state.permanents() if o.is_creature and o.controller_id != controller.id
        ]
        if not victims:
            return
        card = CreateTokenEffect(
            token_name="Phyrexian Beast", power=4, toughness=4, colors=["G"], subtypes=["Phyrexian", "Beast"],
            source=self.source,
        )
        before = len(context.created_objects)
        card.count = len(victims)
        card.apply(context, None)
        tokens = list(context.created_objects[before:])
        for token, victim in zip(tokens, victims):
            FightEffect._fight(context, token, victim)


class DrawPerDamageDealtToSourceEffect(GameEffect):
    """"When ~ leaves the battlefield, each player draws cards equal to the amount of damage dealt to ~
    this turn by sources they controlled." (Grothama, All-Devouring)

    Read from this turn's DAMAGE events (`EventType.DAMAGE` targeting the source's ``instance_id``,
    summed per ``source_controller_id``) rather than a mutable tally, so it still answers once the
    source has left. Damage is counted whether or not it was combat damage and whatever the source was
    (a permanent, a spell); players with nothing dealt draw nothing.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        per_player: dict[str, int] = {}
        for event in context.state.events_this_turn():
            if event.type != EventType.DAMAGE or event.get("is_player"):
                continue
            if event.get("target_id") != source.instance_id:
                continue
            controller_id = event.get("source_controller_id")
            if controller_id is not None:
                per_player[controller_id] = per_player.get(controller_id, 0) + int(event.get("amount") or 0)
        for player in context.state.living_players():
            amount = per_player.get(player.id, 0)
            if amount > 0:
                context.draw(player, amount)


class FightEffect(GameEffect):
    """RULE 701.14 — "Target creature you control fights target creature you
    don't control." (Prey Upon), "~ fights up to one target creature you don't
    control." (Kogla's ETB).

    Both creatures deal damage equal to their power to each other (701.14a),
    and it is **not** combat damage (701.14d) — so `context.deal_damage`'s
    default ``combat=False`` is exactly right, and a first-strike/deathtouch-
    style combat concept never enters into it.

    ``fighter_kind``/``other_kind`` each name either a RULE 115 target kind —
    the printed two-target form ("target creature you control fights target
    creature …"), where `extra_target_specs` carries the second requirement
    the same way `AttachChosenEffect` does — or one of the implicit
    subjects `_IMPLICIT_FIGHT_SUBJECTS` documents (the source, an Aura's host,
    a pronoun pointing back at the previous clause's target, or a RULE 603.1
    group trigger's own firing object). An implicit
    subject announces no requirement at all, so "it fights target creature you
    don't control" is a *one*-target spell and "those creatures fight each
    other" is a zero-target one.

    RULE 701.14b is the whole reason this is one atomic effect rather than two
    `DealDamageEffect`s: if *either* creature has left the battlefield or
    stopped being a creature by resolution, **neither** deals damage. Both
    powers are also snapshotted before any damage is dealt, since 701.14a's
    two damage events are simultaneous — a creature whose power changes as a
    consequence of the first half (a dies-trigger, an SBA) must still deal
    what it had. A creature fighting itself deals twice its power to itself
    (701.14c), which falls out of dealing both halves to the same object —
    *unless* ``distinct`` marks the clause's RULE 109.5 "**another** target
    creature", where picking the same creature twice was never legal to begin
    with (`TargetSpec.distinct_from_others`); this is that constraint's
    resolve-time backstop.
    """

    def __init__(
        self,
        fighter_kind: Optional[str] = None,
        other_kind: Optional[str] = "creature",
        fighter_optional: bool = False,
        optional: bool = False,
        distinct: bool = False,
        source: Optional["GameObject"] = None,
        other_exact_mana_value: Optional[Union[int, str]] = None,
        other_instance_id: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self.fighter_kind = fighter_kind
        self.other_kind = other_kind
        self.distinct = distinct
        #: A fixed opponent in the fight — "…you may have it fight Grothama" (a granted ability whose
        #: granting permanent is the other fighter): no RULE 115 target, the object is pinned by id.
        self.other_instance_id = other_instance_id if isinstance(other_instance_id, int) else None
        specs: list[TargetSpec] = []
        if fighter_kind not in _IMPLICIT_FIGHT_SUBJECTS:
            specs.append(TargetSpec(kind=fighter_kind, optional=fighter_optional))
        if other_kind not in _IMPLICIT_FIGHT_SUBJECTS and self.other_instance_id is None:
            # ``other_exact_mana_value``: "…target creature you don't control **with the same mana
            # value**" (Boxing Ring) — `TargetSpec.exact_mana_value`'s ``trigger_subject_mana_value``.
            specs.append(TargetSpec(
                kind=other_kind, optional=optional, distinct_from_others=distinct,
                exact_mana_value=other_exact_mana_value,
            ))
        if specs:
            self.target_spec = specs[0]
            self.extra_target_specs = tuple(specs[1:])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        chosen = iter(picks)
        if self.fighter_kind in _IMPLICIT_FIGHT_SUBJECTS:
            fighter = _implicit_fight_subject(self.fighter_kind, self, context)
        else:
            fighter = next(chosen, None)
        if self.other_instance_id is not None:
            other = context.state.find_object(self.other_instance_id)
        elif self.other_kind in _IMPLICIT_FIGHT_SUBJECTS:
            other = _implicit_fight_subject(self.other_kind, self, context)
        else:
            other = next(chosen, None)
        # RULE 701.14b: gone from the battlefield, or no longer a creature →
        # neither fights (an "up to one" clause with no target lands here too).
        battlefield = context.state.permanents()
        for creature in (fighter, other):
            if creature is None or creature not in battlefield or not creature.is_creature:
                return
        if fighter is other and (self.distinct or self.fighter_kind == "previous_target"):
            # RULE 109.5: "another" was never a legal pick of itself. The same
            # guard covers a pronoun fighter whose clause declined its own
            # "up to one" target — a caller that sends a *flat* list can't
            # say which requirement was skipped (`targeting.partition_targets`
            # returns None there), so this clause would otherwise read the
            # earlier clause's pick as its own and have the creature fight
            # itself. No printed card means that.
            return
        self._fight(context, fighter, other)

    @staticmethod
    def _fight(context: GameContext, fighter: Any, other: Any) -> None:
        """RULE 701.14a: both deal damage equal to their power to each other (the powers snapshotted first),
        then each fires `FIGHTS`. Shared with effects that pair creatures themselves (Ezuri's Predation)."""
        fighter_power = fighter.power or 0
        other_power = other.power or 0
        context.deal_damage(other, fighter_power, fighter)
        context.deal_damage(fighter, other_power, other)
        for creature in (fighter, other):
            context.state.fire_event(GameEvent(
                EventType.FIGHTS, instance_id=creature.instance_id,
                controller_id=creature.controller_id, object_types=sorted(creature.type_words),
            ))


class DamageEqualToPowerEffect(GameEffect):
    """"Target creature you control deals damage equal to its power to target
    creature you don't control." (Rabid Bite) — the *one-sided* fight, and
    "When ~ dies, it deals damage equal to its power to any target." /
    "… to each opponent." (Ghoulcaller's Accomplice-shaped dies triggers).

    Shares `FightEffect`'s subject vocabulary for the **dealer**
    (`_IMPLICIT_FIGHT_SUBJECTS`, or a target kind) and `DealDamageEffect`'s
    for the **recipient** (a target kind, or an untargeted ``selector`` —
    RULE 601.2c's "each opponent"/"each player"/"each creature").

    Two rules-relevant differences from a fight, both deliberate: the damage
    is one-way, and the dealer is **not** required to still be on the
    battlefield. The commonest printed form of this clause is a dies trigger,
    where the dealer is already in the graveyard as the ability resolves —
    RULE 608.2h's last known information is what its power is read from, which
    is exactly what `GameObject.power` still reports there.
    """

    def __init__(
        self,
        dealer_kind: Optional[str] = None,
        target_kind: Optional[str] = "any",
        selector: Optional[str] = None,
        dealer_optional: bool = False,
        optional: bool = False,
        to_self: bool = False,
        source: Optional["GameObject"] = None,
        dealer_group: Optional[str] = None,
        excess_to_controller_if_trample: bool = False,
    ) -> None:
        super().__init__(source)
        #: "If the creature you control has trample, excess damage is dealt to that creature's
        #: controller instead." (Ram Through) — with a trampling dealer the recipient creature
        #: takes only lethal damage (RULE 120.4a; 1 from a deathtouch dealer) and the rest goes
        #: to that creature's controller.
        self.excess_to_controller_if_trample = excess_to_controller_if_trample
        #: ``"previous_targets"`` — "**each of those creatures** deals damage equal to its power
        #: to ~" (Polukranos, World Eater; PAR-128): every object the preceding clause targeted
        #: is a dealer of its own power, and the recipient is the ability's source. No target of
        #: this clause's own.
        self.dealer_group = dealer_group if dealer_group == "previous_targets" else None
        self.dealer_kind = dealer_kind
        # "… deals damage to itself equal to its power" (Wave of Reckoning /
        # Solar Blaze / Justice Strike) — the dealer *is* the recipient, so
        # there is never a second target, and the "each creature" mass form
        # has no dealer target at all (each creature is its own dealer).
        self.to_self = to_self
        self.selector = selector if selector in _DAMAGE_SELECTORS else None
        specs: list[TargetSpec] = []
        need_dealer_target = self.dealer_group is None and dealer_kind not in _IMPLICIT_FIGHT_SUBJECTS and not (
            to_self and self.selector is not None
        )
        if need_dealer_target:
            specs.append(TargetSpec(kind=dealer_kind, optional=dealer_optional))
        if not to_self and self.selector is None and target_kind is not None and self.dealer_group is None:
            specs.append(TargetSpec(kind=target_kind, optional=optional))
        if specs:
            self.target_spec = specs[0]
            self.extra_target_specs = tuple(specs[1:])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.dealer_group is not None:
            recipient = self.source
            if recipient is None or recipient not in context.state.permanents():
                return  # RULE 608.2b: a permanent that left the battlefield takes no damage
            for dealer in list(context.previous_targets):
                # Players have no power; a creature's power is read as it last existed (RULE 608.2h).
                amount = getattr(dealer, "power", None) or 0
                if hasattr(dealer, "instance_id") and amount > 0:
                    context.deal_damage(recipient, amount, dealer)
            return
        picks = list(targets or [])
        chosen = iter(picks)
        # "each creature deals damage to itself equal to its power." — no
        # dealer target; every creature damages itself for its *own* power
        # (RULE 601.2c untargeted group; amounts differ per creature).
        if self.to_self and self.selector == "each_creature":
            for creature in [o for o in context.state.permanents() if o.is_creature]:
                amount = creature.power or 0
                if amount > 0:
                    context.deal_damage(creature, amount, creature)
            return
        if self.dealer_kind in _IMPLICIT_FIGHT_SUBJECTS:
            dealer = _implicit_fight_subject(self.dealer_kind, self, context)
        else:
            dealer = next(chosen, None)
        if dealer is None:
            return
        amount = dealer.power or 0
        if amount <= 0:
            return
        if self.to_self:
            # "target creature deals damage to itself equal to its power."
            if hasattr(dealer, "instance_id") and dealer not in context.state.permanents():
                return
            context.deal_damage(dealer, amount, dealer)
            return
        if self.selector is not None:
            for recipient in self._selected_recipients(context, dealer):
                context.deal_damage(recipient, amount, dealer)
            return
        recipient = next(chosen, None)
        if recipient is None:
            return
        if recipient is dealer and self.dealer_kind == "previous_target":
            # The same flat-list guard `FightEffect` makes: a declined "up to
            # one" would otherwise leave this clause reading the previous
            # clause's pick as its own recipient, damaging it with itself.
            return
        # A permanent that has since left the battlefield takes no damage
        # (RULE 608.2b's illegal-target check, the same guard a fight makes);
        # a player recipient (no ``instance_id``) is always still there.
        if hasattr(recipient, "instance_id") and recipient not in context.state.permanents():
            return
        if self.excess_to_controller_if_trample and hasattr(recipient, "instance_id"):
            from .. import combat  # function-scoped: combat is a leaf module, avoid load-order cycles

            if combat.has_trample(dealer):
                lethal = 1 if combat.has_deathtouch(dealer) else max(0, (recipient.toughness or 0) - (recipient.damage_marked or 0))
                to_creature = min(amount, lethal)
                excess = amount - to_creature
                if to_creature > 0:
                    context.deal_damage(recipient, to_creature, dealer)
                if excess > 0:
                    context.deal_damage(context.state.player_by_id(recipient.controller_id), excess, dealer)
                return
        context.deal_damage(recipient, amount, dealer)

    def _selected_recipients(self, context: GameContext, dealer: Any) -> list[Any]:
        """RULE 601.2c's untargeted recipient groups, scoped to the **dealer**
        (not the effect's source — "each opponent" of the creature dealing the
        damage, which for a granted/copied ability need not be the same
        player)."""
        if self.selector == "each_creature":
            return [obj for obj in context.state.permanents() if obj.is_creature]
        controller_id = getattr(dealer, "controller_id", None)
        if self.selector == "each_other_creature_and_opponent":
            return [
                *(obj for obj in context.state.permanents() if obj.is_creature and obj is not dealer),
                *(p for p in context.state.living_players() if p.id != controller_id),
            ]
        return [
            player
            for player in context.state.living_players()
            if not (self.selector == "each_opponent" and player.id == controller_id)
        ]


class DamageEqualToCountersEffect(GameEffect):
    """"~ deals damage equal to the number of +1/+1 counters on it to any
    other target." (Red Hulk-shaped) — `DamageEqualToPowerEffect`'s sibling
    for a counter-count amount rather than power (the two aren't always the
    same number: a creature's power can be modified by other statics/pumps
    independently of its counters).

    Red Hulk's own printed shape ("put a +1/+1 counter on him. **When you
    do**, he deals damage equal to the number of +1/+1 counters on him to
    any other target.") is really two abilities under RULE 603.10 — a
    reflexive trigger off the counter-placement, not a plain sequential
    resolution. This engine has no reflexive "when you do" trigger
    primitive yet, so the catalogue entry runs both as one triggered
    ability's effect list instead (RULE 608.2a resolves a list in printed
    order, and nothing has a window to intervene between them either way in
    an automated engine) — a documented simplification, not a rules
    difference a real game could ever observe.
    """

    def __init__(
        self,
        kind: str = "+1/+1",
        target: Any = None,
        target_kind: Optional[str] = "any",
        optional: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional) if target_kind else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        amount = (
            self.source.plus_one_counters if self.kind == "+1/+1"
            else int((getattr(self.source, "counters", None) or {}).get(self.kind, 0) or 0)
        )
        if amount <= 0:
            return
        context.deal_damage(target, amount, self.source)


class ChooseTargetsEffect(GameEffect):
    """"Choose target creature you control **and** target creature you don't
    control." (Ancient Animus, Coven-style fight spells) — a clause that only
    *announces* targets (RULE 601.2c), doing nothing on its own; the clauses
    after it act on them by pronoun ("Then **those creatures** fight each
    other.", `_IMPLICIT_FIGHT_SUBJECTS`' ``previous_target``/
    ``previous_target_2`` via `GameContext.previous_targets`).

    Modeling it as a real, no-op effect rather than folding the targets into
    whichever later clause uses them keeps the announcement where the card
    prints it: the targets are chosen as the spell is *cast* (RULE 601.2c),
    so they must be part of what `targeting.spell_target_specs` reports even
    when the clause consuming them is conditional and may never happen ("if
    you control three or more snow permanents, …").

    ``count``/``distinct_controllers``/``optional`` (PAR-1, only meaningful
    with a single ``kinds`` entry) are Run Away Together's own "**choose two
    target creatures** controlled by different players." shape — one
    quantified requirement picking N objects of the *same* kind, unlike the
    Ancient Animus pair above (two independent, differently-kinded single
    choices). The whole chosen group is then read back — not by a
    positional ``previous_target``/``previous_target_2`` pronoun, which only
    ever names the *first*/*second* of exactly two — by a later clause's own
    ``previous_subject`` flag (`ReturnToHandEffect`'s, for now).
    """

    def __init__(
        self,
        kinds: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
        count: Optional[int] = None,
        distinct_controllers: bool = False,
        optional: bool = False,
        per_player: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        kinds = kinds or []
        if len(kinds) == 1 and count:
            specs = [TargetSpec(
                kind=kinds[0], count=count, distinct_controllers=distinct_controllers,
                optional=optional, per_player=per_player,
            )]
        else:
            specs = [TargetSpec(kind=kind, optional=optional, per_player=per_player) for kind in kinds]
        if specs:
            self.target_spec = specs[0]
            self.extra_target_specs = tuple(specs[1:])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        # Nothing happens here; the picks reach the following clauses through
        # `_apply_effects_partitioned`'s `GameContext.previous_targets`.
        return


class DestroyEachWithManaValueEffect(GameEffect):
    """"Destroy each artifact with mana value X." (Dauntless Dismantler's
    ``{X}{X}{W}`` ability) — a mass destroy whose *filter* is the ability's
    own announced X rather than a printed constant.

    The shipped `DestroyEffect`'s ``max_mana_value`` is a printed cap; this
    is an exact match against a value only known at activation, threaded
    through the same ``"x"`` sentinel `RulesEngine._substitute_x` rewrites
    for every other X-scaled magnitude. Untargeted (RULE 601.2c), like every
    other board wipe here.
    """

    def __init__(
        self,
        amount: Any = 0,
        card_type: str = "artifact",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.card_type = card_type

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if not isinstance(self.amount, int):
            return
        doomed = [
            obj
            for obj in context.state.permanents()
            if self.card_type in obj.type_words
            and obj.card.converted_mana_cost == self.amount
        ]
        for obj in doomed:
            context.destroy(obj)


class DiscardOrLoseLifeEffect(GameEffect):
    """"Each opponent may discard a card. If they don't, they lose N life.
    Repeat this process M more times." (Professor Onyx's −8) — RULE 701.8
    plus a fixed-count repetition.

    ``times`` is the total number of rounds (7 for Onyx: the first plus "six
    more"), which makes this a *bounded* loop like `MillUntilCreatureEffect`
    rather than an open-ended one — the count is known before it starts.

    Whether to discard is each opponent's own decision (RULE 118.3-style
    optional payment), so every round is a real `pay_cost_then` prompt —
    the shipped primitive Mana Vault and Wandering Archaic already use,
    with discarding as the cost and losing the life as its "if you don't"
    branch. The loop is driven by making *both* branches carry a
    ``discard_or_lose_life`` spec for the remaining rounds/opponents, so
    resolving one prompt opens the next: `pending_choice` holds one
    decision at a time, which a Python loop here could never respect.

    ``round_index``/``player_index`` are that continuation's bookmark
    (rounds completed so far, and how far through the opponent list this
    round is) — internal, never authored on a card.
    """

    def __init__(
        self,
        count: int = 1,
        amount: int = 3,
        times: int = 1,
        selector: str = "each_opponent",
        round_index: int = 0,
        player_index: int = 0,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.amount = amount
        self.times = int(times)
        self.selector = selector
        self.round_index = int(round_index)
        self.player_index = int(player_index)

    def _continuation_spec(self, round_index: int, player_index: int) -> dict[str, Any]:
        """This same effect, bookmarked one step further on."""
        return {
            "type": "discard_or_lose_life",
            "params": {
                "count": self.count,
                "amount": self.amount,
                "times": self.times,
                "selector": self.selector,
                "round_index": round_index,
                "player_index": player_index,
            },
        }

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..costs import ActivationCost

        controller_id = getattr(self.source, "controller_id", None)
        opponents = [
            p for p in context.state.living_players()
            if not (self.selector == "each_opponent" and p.id == controller_id)
        ]
        round_index, player_index = self.round_index, self.player_index
        # Skip past anyone already handled this round, and past finished
        # rounds — the loop only ever advances, so a re-entry can't repeat.
        while round_index < max(self.times, 0):
            if player_index >= len(opponents):
                round_index += 1
                player_index = 0
                continue
            player = opponents[player_index]
            if not player.hand:
                # Nothing to discard: RULE 118.3's "a player who can't pay
                # isn't asked", so the else-branch applies straight away.
                context.lose_life(player, self.amount)
                player_index += 1
                continue
            cost = ActivationCost(discard=self.count)
            rest = [self._continuation_spec(round_index, player_index + 1)]
            context.engine._request_pay_cost_then(
                player,
                cost,
                effect_specs=rest,
                else_effect_specs=[
                    {
                        "type": "lose_life",
                        "params": {"amount": self.amount, "player_id": player.id},
                    },
                    *rest,
                ],
                source=self.source,
                prompt=f"{player.id}: Eine Karte abwerfen statt {self.amount} Leben zu verlieren?",
            )
            return


class ReturnCommandersToCommandZoneEffect(GameEffect):
    """"Target player returns each commander they control from the battlefield
    to the command zone." (Leadership Vacuum) — RULE 903.3 / 903.9.

    An instruction, not the owner's RULE 903.9a replacement choice
    (`RulesEngine._commander_zone_choice`, which only offers the *option* when a
    commander would change zone elsewhere): the target player moves every
    commander **they control** — an opponent's or their own — so there is
    nothing to decline. Fires `LEAVES_BATTLEFIELD` (RULE 603.6c, ``to_zone=
    "command"``) before the move, resets the object (RULE 400.7: a new object
    in the command zone, no counters/attachments), and puts it back with its
    owner, whoever controlled it.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="player")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = targets[0] if targets else _controller_of(self.source, context)
        if player is None:
            return
        for obj in [o for o in context.state.battlefield if o.is_commander and o.controller_id == player.id]:
            context.fire_event(
                GameEvent(
                    EventType.LEAVES_BATTLEFIELD, to_zone="command", object=obj.name,
                    owner_id=obj.owner_id, controller_id=obj.controller_id,
                    instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                    counters=dict(obj.counters), power=obj.power, toughness=obj.toughness,
                )
            )
            context.state.remove_from_battlefield(obj)
            obj.reset_as_new_object()
            context.state.player_by_id(obj.owner_id).add_to_zone(obj, Zone.COMMAND)
        context.recompute()


class GainControlOfAllCommandersEffect(GameEffect):
    """"Gain control of all commanders. Put all commanders from the command
    zone onto the battlefield under your control." (Tevesh Szat's −10) —
    RULE 903.3/110.2.

    Genuinely Commander-specific, with no near-miss anywhere in the engine:
    the layer-2 ``control_change`` static reassigns one permanent for as
    long as its source stays around, and no shipped effect moves a card out
    of the **command zone** onto the battlefield at all.

    The control change here is permanent (a one-shot RULE 110.2 change, like
    `ExchangeControlEffect`'s), not a duration-bounded grab — Tevesh Szat is
    an ultimate, and the board state it creates is meant to stick.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        for obj in list(context.state.battlefield):
            if obj.is_commander:
                obj.controller_id = controller.id
                obj.summoning_sick = True  # RULE 302.6: new controller
        for player in context.state.players:
            for obj in list(player.command):
                if not obj.is_commander:
                    continue
                player.remove_from_zone(obj, Zone.COMMAND)
                obj.controller_id = controller.id
                obj.zone = Zone.BATTLEFIELD
                obj.summoning_sick = True
                context.state.add_to_battlefield(obj)
                context.fire_event(
                    GameEvent(
                        EventType.ENTERS_BATTLEFIELD,
                        from_zone=Zone.COMMAND.value,
                        instance_id=obj.instance_id,
                        controller_id=obj.controller_id,
                        object_types=sorted(obj.type_words),
                    )
                )
        context.recompute()


class RegainControlOfOwnedCreaturesEffect(GameEffect):
    """"Each player gains control of all creatures they own." (MEC-43
    round 4D, Homeward Path) — RULE 108.4/110.2's plain one-shot control
    change (`ExchangeControlEffect`'s own docstring: a straight
    `GameObject.controller_id` write, not a duration-bounded layer-2
    grant), just applied to *every* player's own stolen creatures at once
    instead of a single chosen pair — untargeted (RULE 601.2c), unscoped
    by whose ability activated it (this hands a creature back to whoever
    already **owns** it, regardless of who currently controls Homeward
    Path).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for obj in list(context.state.permanents()):
            if obj.is_creature and obj.controller_id != obj.owner_id:
                obj.controller_id = obj.owner_id
                # RULE 302.6: newly under its owner's command again.
                obj.summoning_sick = True
        context.recompute()


class PutCommanderIntoHandEffect(GameEffect):
    """"Put your commander into your hand from the command zone." (MEC-43
    round 4D, Command Beacon) — RULE 903.7's reverse direction from the
    far more common "return to the command zone" replacement family: a
    plain zone move for every commander currently sitting in the
    ability's own controller's command zone (RULE 903.3 lets a deck have
    more than one, Partner-shaped), a no-op if there's none there right
    now (already on the battlefield, or already moved elsewhere).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in [o for o in player.command if o.is_commander]:
            player.remove_from_zone(obj, Zone.COMMAND)
            player.add_to_zone(obj, Zone.HAND)


class MultiplyDamageFromTargetEffect(GameEffect):
    """"Choose target creature. Until your next turn, if that creature would
    deal combat damage to one of your opponents, it deals triple that damage
    to that player instead." (Jeska, Thrice Reborn's 0) — RULE 616.1.

    The shipped damage-multiplying replacement family (Furnace of Rath/Fiery
    Emancipation) is standing, board-wide and sourced from a permanent whose
    presence keeps it alive. This is the same *rewrite*, scoped three ways
    that family never needed: to one specific source instance, to combat
    damage only, and to the effect's controller's opponents — and bounded by
    a duration rather than by its source sticking around.

    So it reuses the replacement machinery rather than a new one: a
    turn-scoped `ReplacementEffect` installed on the targeted creature's own
    `GameObject.replacement_effects`, exactly the per-object shield shape
    `RegenerateEffect` already uses.
    """

    def __init__(
        self,
        multiplier: int = 2,
        combat_only: bool = True,
        to: str = "opponents",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.multiplier = int(multiplier)
        self.combat_only = combat_only
        self.to = to
        self.target_spec = TargetSpec(kind="creature")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        controller = _controller_of(self.source, context)
        if target is None or controller is None:
            return
        multiplier = self.multiplier
        combat_only = self.combat_only
        wants_opponents = self.to == "opponents"
        source_id = target.instance_id
        controller_id = controller.id

        def _replace(event: GameEvent, ctx: GameContext) -> Optional[GameEvent]:
            if event.get("source_id") != source_id:
                return event
            if combat_only and not event.get("combat"):
                return event
            if not event.get("is_player"):
                return event
            if wants_opponents and event.get("target_id") == controller_id:
                return event
            return event.copy_with(amount=int(event.get("amount", 0)) * multiplier)

        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=_replace,
            source=self.source,
            description=f"{target.name}: {multiplier}× Kampfschaden",
        )
        # "Until your next turn" (RULE 611.2b) — the same duration key
        # `GameEngine.begin_turn` already sweeps for `PlayerShieldEffect`
        # and Hope of Ghirapur's lock, here on a permanent instead.
        effect.until_next_turn_of = controller_id
        target.replacement_effects.append(effect)



register(globals())
