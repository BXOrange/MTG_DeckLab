"""Exile, control-changing, and related battlefield-to-zone effects."""
from __future__ import annotations

from .core import GameEffect
from ._runtime import install, register

install(globals())

class ExileEffect(GameEffect):
    """Exile a target permanent (RULE 406 / 701.5a) — or, with ``count`` >
    1, every one of a fixed/"up to N" set of chosen targets (RULE 115.1a
    generalized to N>=2 — "exile up to two target creatures you control") —
    or, with ``selector`` set, a mass "exile all X" board wipe (RULE
    601.2c, untargeted — Farewell-shaped), the same shape
    `DestroyEffect.selector` uses.

    ``target_kind=None`` (unlike the default ``"permanent"``) is the *self*
    form — "Exile ~."/"Exile this spell/card." (Teferi's Protection/
    Mnemonic Betrayal-shaped trailing self-exile) — no RULE 115 target at
    all, mirroring `TapEffect`/`RegenerateEffect`'s own self mode.

    ``remember=True`` additionally stamps the exiled target's own
    ``instance_id`` onto this ability's own source (`GameObject.
    linked_exile_id`) — the O-Ring-shaped "when this leaves the
    battlefield, return the exiled card" half (`ReturnLinkedExileEffect`)
    reads it back later, arbitrarily many turns on. Only meaningful with a
    single (``count=1``) real target — a mass/selector exile has nothing
    single to remember.

    ``track_exiled_with=True`` (MEC-21, Agatha's Soul Cauldron) is the
    generalized, *accumulating* sibling of ``remember`` — "exile target
    card. [...] exiled **with** ~" (~185 cached cards print this shape,
    per this ticket's sizing) — appending the exiled target's
    ``instance_id`` onto `GameObject.exiled_with_ids` instead of
    overwriting `linked_exile_id`'s single slot, so a repeatable ability
    (Agatha's Soul Cauldron's own "{T}: Exile target card from a
    graveyard.") builds up a real list across many activations rather than
    only ever remembering its last one. The two flags are independent and
    may combine on a future card; this one is also meaningful with
    ``count > 1`` (unlike ``remember``), appending every target chosen.

    ``distinct_controllers`` (Protector of the Wastes-shaped "up to two
    target artifacts and/or enchantments controlled by **different
    players**") is `targeting.TargetSpec.distinct_controllers` — see its
    docstring; only meaningful with ``count >= 2``.

    ``target_kind="trigger_subject"`` (MEC-38, Necropotence's "whenever
    you discard a card, exile **that card** from your graveyard") is a
    fourth, non-RULE-115 mode alongside the target/self/selector shapes
    above — the acted-on object isn't chosen at all, it's whichever card
    the firing event itself names, read live off `GameContext.
    trigger_event` (``trigger_event_key``, ``"instance_id"`` by default)
    the same way `TapEffect`'s own ``target_kind="trigger_subject"``
    already does. By the time this fires the named card is already
    sitting in the graveyard (`RulesEngine.discard`/`discard_specific`
    move it there before firing), so this is a real zone change, not a
    no-op.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "permanent",
        optional: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        remember: bool = False,
        creature_filter: Optional[dict[str, Any]] = None,
        distinct_controllers: bool = False,
        track_exiled_with: bool = False,
        max_mana_value: Optional[int] = None,
        grant_owner_play_permission: bool = False,
        owner_play_permission_tax: Optional[int] = None,
        owner_play_permission_cost: Optional[str] = None,
        trigger_event_key: Optional[str] = None,
        grant_free_cast_window: bool = False,
        spell_or_permanent: bool = False,
        colors: Optional[list[str]] = None,
        bend_kind: Optional[str] = None,
        count_selector: Optional[str] = None,
        unless_flag: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "Exile **X** target creatures you control" (Waterbender's
        #: Restoration) — a `TargetSpec.count_selector` (``"source_x_paid"``,
        #: resolved at announce time off `GameObject.x_paid`), not the plain
        #: ``count``, so `has_legal_targets`/`all_requirements_satisfiable`
        #: see a real int rather than the ``"x"`` sentinel.
        self._count_selector = count_selector
        #: RULE 701.65 (Airbend) / 701.6x: when set (always ``"airbend"``,
        #: from `handlers._airbend`/`_airbend_trigger_subject`), fire
        #: `EventType.BENT` after the exile so Avatar Aang's "whenever you …
        #: airbend" trigger sees it. `RulesEngine.record_bend` owns the
        #: event + `GameState.bends_this_turn` stamp; fired once per
        #: resolution that exiled at least one object, not once per object.
        self.bend_kind = bend_kind
        #: "exile target `<c1>` or `<c2>` permanent" (Celestial Purge) —
        #: `TargetSpec.colors`' OR narrowing, offer-time (`_color_ok`).
        self.colors = tuple(colors) if colors else None
        self.selector = selector if selector in _MASS_DESTROY_SELECTORS else None
        self.filter = filter
        self.remember = remember
        self.track_exiled_with = track_exiled_with
        #: "airbend up to one other target creature **or spell**" (Aang,
        #: Swift Savior — RULE 701.65 applied to a spell). A chosen target
        #: that is currently a spell on the stack is exiled *off the stack*
        #: (RULE 400.1, `RulesEngine.move_spell_off_stack`) so it never
        #: resolves, rather than through `context.exile` (a battlefield
        #: move); the exiled card keeps its `instance_id`/`owner_id`, so the
        #: `_post_exile` recast-permission riders apply unchanged. Mirrors
        #: `ReturnToHandEffect`'s own `spell_or_permanent` (Unsubstantiate).
        self.spell_or_permanent = spell_or_permanent
        #: "…copy it, and you may cast the copy without paying its mana
        #: cost." (MEC-43 round 4C, Mizzix's Mastery) — `grant_owner_play_
        #: permission`'s free-cast sibling: once the target is exiled,
        #: opens `RulesEngine.grant_free_cast_window_from_exile` on it
        #: directly (the same primitive `ExileTopFromEachPlayerCastFree
        #: Effect`/`ReboundFreeCastWindowEffect` already use), rather than
        #: literally instantiating a second "copy" object — nothing this
        #: engine tracks distinguishes an uncast copy from the real exiled
        #: card, and RULE 707.10a means an uncast copy simply ceases to
        #: exist either way, so the two are behaviourally identical.
        self.grant_free_cast_window = grant_free_cast_window
        self._trigger_subject_mode = target_kind == "trigger_subject"
        #: "Exile enchanted creature." (Spiral into Solitude) — an Aura's
        #: own one-shot effect acting on its host, no RULE 115 target of its
        #: own (`GameObject.attached_to`), the same "attached_permanent"
        #: self-acting mode `TapEffect`/`PumpEffect`/
        #: `ShuffleSelfIntoLibraryEffect` already have.
        self._attached_mode = target_kind == "attached_permanent"
        self.trigger_event_key = trigger_event_key
        #: "For as long as that card remains exiled, its owner may play
        #: it." (MEC-12, Soul Partition/Praetor's Grasp-shaped) — the
        #: standing, unconditional sibling of Lukka's own board-gated
        #: `GameState.exile_cast_condition` grant (an empty condition dict
        #: always holds, per `static_conditions.condition_holds`'s own "no
        #: condition = always true"), keyed to the exiled card's *owner*
        #: rather than this effect's controller.
        self.grant_owner_play_permission = grant_owner_play_permission
        #: "A spell cast by an opponent this way costs {2} more to cast."
        #: (Soul Partition) — stamped directly onto the exiled card's own
        #: ``affects="self"`` static at the moment it's exiled
        #: (`except_same_controller_as` = the exiler's own id), read back
        #: by `continuous.self_cost_reduction_for`'s new ``caster_id``
        #: param whenever/if it's ever actually cast.
        self.owner_play_permission_tax = owner_play_permission_tax
        #: RULE 701.65 (Airbend, PAR-29): "…its owner may cast it for {2}
        #: rather than its mana cost." — a *fixed* alternative cast cost
        #: (a mana string) while exiled, stamped into `GameState.exile_
        #: cast_cost_override` alongside the `grant_owner_play_permission`
        #: grant. Distinct from `owner_play_permission_tax` (which *adds*
        #: to the printed cost); mutually exclusive with it in practice.
        self.owner_play_permission_cost = owner_play_permission_cost
        self.target_spec: Optional[TargetSpec] = None
        if (
            self.selector is None and target_kind is not None
            and not self._trigger_subject_mode and not self._attached_mode
        ):
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max, creature_filter=creature_filter,
                distinct_controllers=distinct_controllers, colors=self.colors,
                count_selector=count_selector,
                # "…permanent … with mana value N or less." (MEC-12, Skyclave
                # Apparition) — the same target-offer-time cap `DestroyEffect`
                # already threads (`targeting.TargetSpec.max_mana_value`).
                max_mana_value=max_mana_value,
                # "…with mana value 3 or less. If this spell was cast using
                # teamwork, instead exile target creature[.]" (MEC-85, Cruel
                # Alliance) — see `targeting.TargetSpec.unless_flag`.
                unless_flag=unless_flag,
            )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            for obj in _mass_selector_objects(context, self.selector, self.filter, source=self.source):
                if self.track_exiled_with and self.source is not None:
                    # "…exile all other permanents you control. When ~
                    # leaves the battlefield, return the exiled cards…"
                    # (MEC-43 round 4D, Worldgorger Dragon) — the mass
                    # selector's own sibling of the targeted branch's
                    # ``track_exiled_with`` handling just below, so an
                    # untargeted board-wipe-shaped exile can still feed
                    # `ReturnAllExiledWithEffect` later.
                    self.source.exiled_with_ids.append(obj.instance_id)
                context.exile(obj)
            return
        if self._attached_mode:
            # "Exile enchanted creature." — this Aura/Equipment's host.
            host_id = getattr(self.source, "attached_to", None)
            host = context.state.find_object(host_id) if host_id is not None else None
            if host is not None:
                context.exile(host)
                self._post_exile(context, host)
            return
        if self._trigger_subject_mode:
            event = context.trigger_event
            # A DAMAGE event records the dealt-to object as ``target_id``;
            # ordinary object-subject events use ``instance_id``.  The
            # parser's "exile that creature" referent is valid for both
            # forms, so an omitted explicit key chooses the former only
            # where it exists and otherwise keeps the long-standing latter.
            key = self.trigger_event_key or (
                "target_id" if (event or {}).get("target_id") is not None else "instance_id"
            )
            obj_id = (event or {}).get(key)
            target = context.state.find_object(obj_id) if obj_id is not None else None
            if target is not None:
                context.exile(target)
                # RULE 608.2's "it"/"that card" referent — a following clause
                # ("If you do, … create a token that's a copy of **that
                # card**." — The Master, Gallifrey's End) names what this
                # clause just exiled, the same way the RULE 115 targeted
                # branch below leaves its picks in `previous_targets` via
                # `_apply_effects_partitioned`.
                context.previous_targets = [target]
                # "…you may **airbend that creature**." (Monk Gyatso, PAR-30)
                # — the trigger-subject sibling still needs the airbend
                # exile-cast permission / remember / free-cast-window riders,
                # exactly as the RULE 115 targeted branch below applies them.
                self._post_exile(context, target)
                self._record_bend_if_set(context)
            return
        if self.target_spec is None:
            # Self mode ("Exile ~."/"Exile this spell/card.") — like
            # `DrawCardEffect`'s own documented gotcha, this must *not*
            # fall back to a stray `targets[0]` left over from a different
            # targeting effect earlier in the same resolution: Mizzix's
            # Mastery's "Exile target card... . [...] Exile Mizzix's
            # Mastery." (MEC-43 round 4C) is exactly that shape — the
            # first clause's own real RULE 115 target must not get handed
            # to this second, untargeted self-exile as if it were one.
            target = self.target or self.source
            if target is not None:
                context.exile(target)
                # PAR-74: "exile ~. If you do, return it to the battlefield
                # …" (Hikari, Twilight Guardian) needs `remember`'s
                # `linked_exile_id` stamp same as the RULE 115 targeted
                # branch below — this self mode silently skipped it before
                # (no real card combined ``target_kind=None`` with
                # ``remember`` until now).
                if self.remember and self.source is not None:
                    self.source.linked_exile_id = target.instance_id
                if self.track_exiled_with and self.source is not None:
                    self.source.exiled_with_ids.append(target.instance_id)
            return
        # A `count_selector`-sized spec ("exile X target …" — Waterbender's
        # Restoration / Foggy Swamp Visions) took its real count at announce
        # time; `effective_count` is a static field with no live board
        # access, so trust `targets` as already sized (the `AddCountersEffect`
        # `count_selector` guard). Otherwise slice to this effect's own count
        # off the possibly-shared list.
        chosen = (
            list(targets or [])
            if self.target_spec.count_selector
            else _chosen_targets(targets, self.target_spec.effective_count, self.target)
        )
        for target in chosen:
            if self.remember and self.source is not None:
                self.source.linked_exile_id = target.instance_id
            if self.track_exiled_with and self.source is not None:
                self.source.exiled_with_ids.append(target.instance_id)
            item = (
                context.engine._stack_item_for(target)
                if self.spell_or_permanent else None
            )
            if item is not None and item.obj is not None:
                context.engine.move_spell_off_stack(item, "exile")
            else:
                context.exile(target)
            self._post_exile(context, target)
        if chosen:
            self._record_bend_if_set(context)

    def _record_bend_if_set(self, context: GameContext) -> None:
        """Fire `EventType.BENT` for an airbend (RULE 701.65) — a no-op
        unless `bend_kind` was set (`handlers._airbend`). Called once per
        resolution that exiled at least one object; `RulesEngine.record_bend`
        is idempotent within a turn (`GameState.bends_this_turn` is a set)."""
        if not self.bend_kind:
            return
        player = _controller_of(self.source, context)
        if player is not None:
            context.engine.record_bend(player, self.bend_kind, source=self.source)

    def _post_exile(self, context: GameContext, target: "GameObject") -> None:
        """The free-cast-window / owner-play-permission / import-tax riders a
        just-exiled object may carry — shared by the RULE 115 targeted branch
        and the ``trigger_subject`` one (Monk Gyatso's "airbend that
        creature")."""
        if self.grant_free_cast_window:
            context.engine.grant_free_cast_window_from_exile(target)
        if self.grant_owner_play_permission:
            context.state.exile_cast_condition[target.instance_id] = (target.owner_id, {})
            if self.owner_play_permission_cost:
                context.state.exile_cast_cost_override[target.instance_id] = (
                    self.owner_play_permission_cost
                )
            if self.owner_play_permission_tax:
                from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
                from ...parser.oracle.spec import EffectSpec

                exiler_id = getattr(self.source, "controller_id", None)
                tax = build_effects(
                    [EffectSpec("cost_reduction", {
                        "affects": "self",
                        "generic": self.owner_play_permission_tax,
                        "increase": True,
                        "except_same_controller_as": exiler_id,
                    })],
                    target,
                )
                target.static_effects.extend(tax)


class ExileTopOfLibraryEffect(GameEffect):
    """"Exile the top card of your library[, face down]." (MEC-38,
    Necropotence-shaped) — deterministic, no chooser at all, unlike
    `SearchLibraryEffect` (which offers the *whole* zone as a real RULE
    115.1a-ish pick even with ``count=1``): always the literal top card.
    ``face_down=True`` stamps `GameObject.face_down_in_exile`, the same
    flag `RulesEngine._put_searched_card`'s own ``"exile_face_down"``
    destination uses. Appends the exiled card to `GameContext.
    created_objects` so a following clause ("Put that card into your
    hand at the beginning of your next end step.") can reach it — see
    `CreateDelayedTriggerEffect`'s ``capture="created_objects"``.

    ``player_selector="active_player"`` (MEC-33, Omen Machine — "at the
    beginning of **each player's** draw step, **that player** exiles…")
    reads `GameState.active_player` live at resolution instead of this
    effect's own source's controller — a `STEP_BEGIN` trigger with no
    ``phase_relation`` fires once per turn regardless of whose turn it is
    (RULE 500.1: a draw step only ever belongs to the turn's own active
    player, so "each player's draw step" and "the active player's draw
    step, every turn" are the same set of firings), the same "no subject
    of its own, read live off `GameState.active_player`" idiom
    `DealDamageEffect`'s own ``"active_player"`` selector already
    established (Roiling Vortex-shaped). ``player_selector="each_player"``
    (MEC-43 round 4C, Doomsday Excruciator — "**each player** exiles all
    but the bottom six cards of their library…"; also RULE 601.2c mass
    form, Knowledge Pool's own imprint ETB — "**each player** exiles the
    top three cards of their library") is the mass sibling of both: every
    living player does this to their own library, independently, in APNAP
    order (`GameState.living_players()`), the same ``each_player``
    selector `SacrificeEffect`/`LoseLifeEffect` already use.

    ``keep_bottom`` (Doomsday Excruciator's own "all **but the bottom
    six**") makes ``count`` dynamic instead of fixed — the player's own
    current library size minus this many, clamped at 0 — so a library that
    already has ``keep_bottom`` cards or fewer exiles nothing. Overrides
    ``count`` when set. Deterministic either way (no chooser): the bottom
    of the library is whatever `Player.library`'s own front already is,
    library order never having been a real chosen thing this engine
    exposes a distinction for.

    ``count`` (Demonic Bargain: 13, Knowledge Pool: 3) exiles that many
    cards per player instead of just the top one — stopping early if a
    library runs out mid-way, same as every other "exile/mill N cards"
    effect in this file. ``track_exiled_with=True`` (MEC-21) is
    `ExileEffect`'s own accumulating "exiled with ~" tracker, threaded
    here so Knowledge Pool's imprint pool (`GameObject.exiled_with_ids`)
    starts seeded with every card this ETB exiles, not just ones a later
    targeted exile adds.
    """

    def __init__(
        self, face_down: bool = False, player_selector: str = "controller",
        count: int = 1, keep_bottom: Optional[int] = None,
        track_exiled_with: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.face_down = face_down
        self.player_selector = player_selector
        #: "Exile the top **thirteen** cards of your library, …" (MEC-43
        #: round 4C, Demonic Bargain) — the flat-count sibling of the
        #: original top-**one**-card-only shape; each exiled card is still
        #: appended to `GameContext.created_objects` in library order, so a
        #: following clause reading the whole batch (not just the last one)
        #: remains possible for a future card.
        self.count = int(count)
        self.keep_bottom = keep_bottom
        self.track_exiled_with = track_exiled_with

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.player_selector == "target":
            players = [targets[0]] if targets and hasattr(targets[0], "library") else []
        elif self.player_selector == "active_player":
            players = [context.state.active_player]
        elif self.player_selector == "each_player":
            players = list(context.state.living_players())
        else:
            controller = _controller_of(self.source, context)
            players = [controller] if controller is not None else []
        for player in players:
            if player is None:
                continue
            count = self.count
            if self.keep_bottom is not None:
                count = max(0, len(player.library) - self.keep_bottom)
            for _ in range(count):
                if not player.library:
                    break
                top = player.library[-1]
                context.exile(top)
                context.moved_objects.append(top)
                if self.face_down:
                    # Set *after* the move: `RulesEngine._remove_from_
                    # current_zone` (which `exile()` calls to pull the card
                    # out of its old zone) unconditionally clears this flag
                    # as its own RULE 400.7 "a card leaving exile turns
                    # face up" behavior — harmless for that case, but it
                    # would silently undo this card *entering* exile face
                    # down if set beforehand.
                    top.face_down_in_exile = True
                if self.track_exiled_with and self.source is not None:
                    self.source.exiled_with_ids.append(top.instance_id)
                context.created_objects.append(top)


class ExileTopThenDamageByMvEffect(GameEffect):
    """MEC-52 (Ensnared by the Mara, villainous option B): "that player
    exiles the top four cards of their library and ~ deals damage equal to
    the **total mana value of those exiled cards** to that player."

    Applied inside a villainous choice with ``targets=[the facing player]``
    (`RulesEngine._request_villainous_choice` hands each option its facing
    player as the target). Exiles up to ``count`` cards off the top of that
    player's library and deals damage equal to their summed mana value back
    to them, from this effect's source — the summed-MV amount source the
    RULE 701 keyword trail's damage clauses had no primitive for.
    """

    def __init__(self, count: int = 4, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = int(count)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        victim = targets[0] if targets else None
        if victim is None or not hasattr(victim, "library"):
            return
        total = 0
        for _ in range(self.count):
            if not victim.library:
                break
            top = victim.library[-1]
            context.exile(top)
            total += int(getattr(top.card, "converted_mana_cost", 0) or 0)
        if total > 0:
            context.engine.deal_damage(victim, total, source=self.source)


class LandOrFreeCastEffect(GameEffect):
    """"If it's a land card, the player puts it onto the battlefield.
    Otherwise, the player casts it without paying its mana cost if able."
    (MEC-33 — Omen Machine's own tail; the same tail also prints on Wild
    Evocation off a different source card, "reveals a card at random from
    their hand" instead of an exiled top card, confirming this is a real
    shared template worth its own primitive rather than a one-off).

    Acts on whatever card an earlier effect in the same resolution just
    made available — `GameContext.created_objects[-1]`, the same "read
    what a previous clause created" idiom `AttachEffect(target_kind=
    "created")`/`ReturnFromGraveyardEffect(target_kind=
    "self_enchant_target")` already use, rather than a RULE 115 target of
    its own (nothing here is chosen — it's whichever card the source
    effect surfaced). ``player_selector`` matches `ExileTopOfLibraryEffect`'s
    own param exactly (``"controller"`` default, ``"active_player"`` for
    Omen Machine's "each player's draw step, that player…" scoping).

    A land goes straight to the battlefield (RULE 305.1 — no stack, no
    legality check beyond existing). Anything else is cast via
    `RulesEngine.cast_without_paying` (RULE 118.9/601.3b) — but only when
    "able": a spell requiring a target it has none of simply can't be cast,
    the same RULE 601.2c gate `GameEngine.has_legal_targets` checks before
    ever offering a real cast action, replicated here directly off
    `targeting.py` since an effect has no `GameEngine` to call through
    (`GameContext.engine` is the `RulesEngine`). "If able" names no other
    fallback in either printed card, so an uncastable nonland card is left
    exactly where the source effect left it (in exile, or wherever) —
    neither card's text says to do anything else with it.

    A nonland card opens the ordinary per-card free-cast window instead of
    being cast during this resolution. Its controller consciously decides
    whether to cast and supplies all targets through the standard cast flow.
    """

    def __init__(self, player_selector: str = "controller", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player_selector = player_selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = context.created_objects[-1] if context.created_objects else None
        if obj is None:
            return
        if self.player_selector == "active_player":
            player = context.state.active_player
        else:
            player = _controller_of(self.source, context)
        if player is None:
            return
        if obj.card.is_land:
            from_zone = obj.zone.value
            obj.summoning_sick = True
            context.engine._remove_from_current_zone(player, obj)
            context.state.add_to_battlefield(obj)
            context.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD,
                    from_zone=from_zone,
                    controller_id=player.id,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
            return
        context.engine.grant_free_cast_window_from_exile(obj, caster=player)


class ExileAnyNumberYouControlEffect(GameEffect):
    """"Exile any number of other nonland permanents you control until ~
    leaves the battlefield." (MEC-12, Abdel Adrian, Gorion's Ward) — a
    *selection* among the controller's own permanents, not a RULE 115
    target at all (the printed line has no "target" word), so it opens
    `RulesEngine._request_choose_objects`'s "choose N of these objects"
    chooser instead of `ExileEffect`'s own target-gathering, offering
    every eligible permanent at once (``count=len(candidates)``) with
    ``optional=True`` so the player may stop after any number, including
    zero. Each pick accumulates onto this ability's own source via the
    chooser's ``track_exiled_with=True`` — the same `GameObject.
    exiled_with_ids` list `ExileEffect(track_exiled_with=True)` uses — read
    back by a following ``create_token`` clause's own ``count_selector=
    "exiled_with_count"`` for "a token for each permanent exiled this way",
    and by `ReturnAllExiledWithEffect` (already shipped for Parallax Wave)
    on this permanent's own leaves-battlefield trigger.
    """

    def __init__(self, other_only: bool = True, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.other_only = other_only

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if player is None:
            return
        candidates = [
            obj for obj in context.state.battlefield
            if not obj.is_land and obj.controller_id == player.id
            and (not self.other_only or obj is not source)
        ]
        context.engine._request_choose_objects(
            player, candidates, "exile", count=len(candidates), optional=True,
            prompt=f"{source.name}: Permanente exilieren?",
            source=source, track_exiled_with=True,
        )


class ImprintEffect(GameEffect):
    """"Imprint — When ~ enters, you may exile a `<filter>` card from your
    hand." (MEC-17, Chrome Mox-shaped) — a resolve-time *choice* among the
    controller's own hand, not a RULE 115 target (the printed line carries
    no "target" word at all, matching every other "exile a card from your
    hand" cost/effect in this codebase).

    Reuses `RulesEngine._request_choose_objects`'s general "choose N of
    these objects" chooser (``action="exile"``) rather than a bespoke
    pending_choice — the same primitive Gemstone Caverns' own "exile a
    card from your hand" pregame tail already rides — with its new
    ``remember=True`` stamping the exiled card's own `instance_id` onto
    this permanent (`GameObject.linked_exile_id`, the same field
    `ExileEffect(remember=True)` uses for the unrelated O-Ring return-
    when-leaves shape) so a later mana ability/static can read back
    *which* card got imprinted — see `ManaAbility.color_selector`'s
    ``"imprinted_card_colors"`` kind (`game/mana_abilities.py`).

    ``exclude_card_types`` is Chrome Mox's own "nonartifact, nonland"
    filter — a list of `Card.is_<word>` flag names to exclude, checked
    against each hand card's printed characteristics. ``include_card_type``
    is the opposite-direction sibling (Isochron Scepter's "an **instant**
    card" — only that single type is eligible, rather than every type but
    a few); ``max_mana_value`` is Isochron's own "with mana value 2 or
    less" cap. Both default to unset (every card type, no cap), matching
    every existing caller.
    """

    def __init__(
        self,
        optional: bool = True,
        exclude_card_types: Optional[list[str]] = None,
        include_card_type: Optional[str] = None,
        max_mana_value: Optional[int] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.optional = optional
        self.exclude_card_types = [str(t).lower() for t in (exclude_card_types or [])]
        self.include_card_type = str(include_card_type).lower() if include_card_type else None
        self.max_mana_value = max_mana_value

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if player is None:
            return
        candidates = [
            obj for obj in player.hand
            if not any(getattr(obj.card, f"is_{t}", False) for t in self.exclude_card_types)
            and (self.include_card_type is None or getattr(obj.card, f"is_{self.include_card_type}", False))
            and (self.max_mana_value is None or obj.card.converted_mana_cost <= self.max_mana_value)
        ]
        context.engine._request_choose_objects(
            player, candidates, "exile", count=1, optional=self.optional,
            prompt=f"{source.name}: Karte aus der Hand exilieren?",
            source=source, remember=True,
        )


class CopyImprintedCardEffect(GameEffect):
    """"{cost}: You may copy the exiled card. If you do, you may cast the
    copy without paying its mana cost." (RULE 707.10/601 — Isochron
    Scepter's repeatable payoff for `ImprintEffect`'s exiled card,
    `GameObject.linked_exile_id`).

    The *original* imprinted card never itself gets cast — it stays exiled
    for the rest of the game — so, unlike `CopySpellEffect`/`copy_ability`
    (which put a copy directly onto the stack, keyed off a `StackItem`
    that's already there), this has to manufacture a fresh copy from
    scratch. It builds one as a token placed straight into the
    controller's own exile (`RulesEngine.create_token(..., zone=Zone.
    EXILE)` — the same "never really entered the battlefield" idiom RULE
    722.3c's `make_prepared` already uses for a Class's prepared copy),
    then opens `RulesEngine.grant_free_cast_window_from_exile` on it so it
    reaches the ordinary `legal_actions` cast option with full targeting —
    the same MEC-20/Beseech the Mirror idiom, rather than a bespoke
    mid-resolution cast that would skip target selection. Repeatable every
    activation, since the source stays exiled and gets copied fresh each
    time; a copy nobody casts is swept by `_remove_stranded_tokens`'s own
    ``free_cast_instance_ids`` exemption once its window closes at cleanup.

    **Documented simplification**: "you may copy" is read as unconditional
    (no real benefit to declining once {2}, {T} is already paid) — the
    same accepted "may" convention Runic Armasaur/Selvala's own docstrings
    establish; the genuine decision is whether to *cast* the resulting
    copy, which stays real (an offered, not forced, action).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        exiled_id = getattr(source, "linked_exile_id", None)
        if exiled_id is None:
            return
        exiled = context.state.find_object(exiled_id)
        if exiled is None or exiled.zone != Zone.EXILE:
            return
        controller_id = getattr(source, "controller_id", None)
        if controller_id is None:
            return
        copiable = getattr(exiled, "_front_card", exiled.card).as_copy()
        tokens = context.engine.create_token(controller_id, copiable, zone=Zone.EXILE)
        if not tokens:
            return
        copy_obj = tokens[0]
        copy_obj.is_copy = True
        context.engine.grant_free_cast_window_from_exile(copy_obj)


class ChoosePermanentEffect(GameEffect):
    """"As this creature enters, you may choose a nonland permanent."
    (MEC-26, Scheming Fence) — a resolve-time choice stamped onto this
    permanent's own `GameObject.chosen_permanent_id`, the object-choice
    sibling of `ImprintEffect` just above (same `_request_choose_objects`
    reuse, a different action — ``"choose_permanent"`` stamps a pointer
    rather than exiling).

    Unlike `ChooseObjectsEffect`'s candidates (always ``permanents_
    controlled_by(player.id)``), "a nonland permanent" is deliberately
    unscoped by controller — Scheming Fence borrows an *opponent's*
    abilities just as readily as its controller's own, so candidates are
    every nonland permanent on the whole battlefield. Choosing this
    permanent itself is a legal (if pointless) pick; `continuous.
    _apply_borrowed_activated_abilities`'s own donor-is-grantee guard makes
    it a no-op rather than something that needs excluding here.
    """

    def __init__(self, optional: bool = True, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.optional = optional

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if player is None:
            return
        candidates = [obj for obj in context.state.permanents() if not obj.is_land]
        context.engine._request_choose_objects(
            player, candidates, "choose_permanent", count=1, optional=self.optional,
            prompt=f"{source.name}: nichtländliches Bleibendes wählen?",
            source=source,
        )


class BounceOwnLandFromTriggerEffect(GameEffect):
    """"Whenever a player casts a spell, that player returns a land they
    control to its owner's hand." (Mana Breach, MEC-43) — "that player" is
    the firing `SPELL_CAST` event's own caster (``player_id``), not this
    ability's controller (the trigger's own subject condition is a bare
    "group", matching *any* player's cast — RULE 603.1). Not a RULE 115
    target (the printed line has no "target" word — it's the caster's own
    choice among their own lands, the same non-targeted shape `ReturnToHand
    Effect`'s ``"land_you_control"`` kind is for a fixed controller), so
    this reuses `RulesEngine._request_choose_objects`'s general chooser
    (``action="return_to_hand"``) with the *triggering* player passed in
    directly instead of this effect's own controller.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event or {}
        player_id = event.get("player_id")
        if player_id is None:
            return
        try:
            player = context.state.player_by_id(player_id)
        except (KeyError, ValueError):
            return
        candidates = [o for o in context.state.permanents_controlled_by(player.id) if o.is_land]
        if not candidates:
            return
        context.engine._request_choose_objects(
            player, candidates, "return_to_hand", count=1, optional=False,
            prompt="Land auf die Hand zurückgeben?",
        )


class FreeCastFromHandEffect(GameEffect):
    """"You may cast a spell with mana value N or less from your hand
    without paying its mana cost." (RULE 601.2f-adjacent — MEC-20, the
    "Expertise" cycle: Kari Zev's/Sram's/Yahenni's/Baral's/Rishkar's
    Expertise, Electrodominance, Epistolary Librarian.

    A resolve-time *choice* among the controller's own hand (RULE 601.3b
    analogue), not a target — none of the printed lines carry "target".
    Opens `RulesEngine._request_choose_objects`'s general chooser with a new
    ``"grant_free_cast"`` action that only *arms* the chosen card's
    `GameState.free_cast_instance_ids` entry rather than casting it
    immediately (unlike the existing ``"cast_free"`` action's
    `RulesEngine.cast_without_paying`, which puts a chosen card straight on
    the stack with no further interaction) — a hand card is already a
    legal cast zone (`can_cast`'s ``in_castable_zone``), so arming the flag
    is enough; the caster then casts it (or doesn't) through the ordinary
    `legal_actions` cast option, getting its full targeting/modal choices
    exactly like `RulesEngine.grant_free_cast_window_from_exile`'s own
    "goes through the ordinary action loop" shape for an *exiled* card.

    ``criteria={"max_mana_value": ...}`` mirrors `SearchLibraryEffect`'s own
    key so the ``"x"`` sentinel `RulesEngine._substitute_x` already walks
    (``filter``/``criteria`` dicts) resolves Electrodominance's own "mana
    value X or less" for free, no separate wiring needed. ``max_mana_value_
    selector`` (Epistolary Librarian's "where X is the number of attacking
    creatures" — a *triggered* ability, never itself cast for an {X} of its
    own) is the `continuous.count_selector` sibling for a cap read off the
    board instead.
    """

    def __init__(
        self,
        criteria: Optional[dict[str, Any]] = None,
        max_mana_value_selector: Optional[str] = None,
        noncreature_only: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.criteria = dict(criteria or {})
        self.max_mana_value_selector = max_mana_value_selector
        #: ENG-33 (Great Intelligence's Plan) / ENG-32 (Waterbend "cast a
        #: noncreature spell without paying") — an *uncapped* free cast: no
        #: ``max_mana_value``/selector at all, so every nonland hand card is
        #: offered. ``noncreature_only`` further narrows it.
        self.noncreature_only = bool(noncreature_only)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if player is None:
            return
        max_mv: Any = None
        if self.max_mana_value_selector:
            from .. import continuous  # function-scoped: avoid the continuous<->effects import cycle

            max_mv = continuous.count_selector(
                context.state, player.id, self.max_mana_value_selector, source=source
            )
        elif self.criteria.get("max_mana_value") is not None:
            max_mv = self.criteria.get("max_mana_value")
        # A cap was *asked for* (selector / literal) but didn't resolve to an
        # int → an unresolved "x" sentinel; nothing legal to offer. An
        # uncapped effect (neither given) skips the check entirely.
        capped = self.max_mana_value_selector is not None or self.criteria.get("max_mana_value") is not None
        if capped and not isinstance(max_mv, int):
            return
        candidates = [
            obj for obj in player.hand
            if not obj.card.is_land
            and (not self.noncreature_only or not obj.card.is_creature)
            and (not isinstance(max_mv, int) or (obj.card.converted_mana_cost or 0) <= max_mv)
        ]
        context.engine._request_choose_objects(
            player, candidates, "grant_free_cast", count=1, optional=True,
            prompt=f"{source.name}: Karte kostenlos zaubern?",
            source=source,
        )


class ExileAllGraveyardsEffect(GameEffect):
    """"Exile all graveyards." (RULE 406 mass exile, Farewell-shaped) —
    every card in every player's graveyard, untargeted.

    ``colors`` (MEC-43 round 2, Sanctifier en-Vec — "exile all cards that
    are **black or red** from all graveyards") narrows this to a colour
    subset, OR semantics (matching "black or red", not "black and red");
    reads `GameObject.colors` the same way every other colour filter in
    this file does.
    """

    def __init__(
        self, source: Optional["GameObject"] = None, colors: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.colors = {str(c).upper() for c in colors} if colors else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for player in context.players:
            for obj in list(player.graveyard):
                if self.colors and not ((obj.colors or set()) & self.colors):
                    continue
                context.exile(obj)


class ExileGraveyardCardCounterIfPermanentEffect(GameEffect):
    """"{W}: Exile target card from a graveyard. If it was a permanent
    card, put a +1/+1 counter on this permanent." (Lion Sash) — a single
    atomic effect since the counter is conditional on *what* was exiled,
    not a separately-modeled clause."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "any_graveyard_card",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        card = target.card
        is_permanent = bool(
            card.is_creature or card.is_artifact or card.is_enchantment
            or card.is_land or getattr(card, "is_planeswalker", False)
        )
        context.exile(target)
        if is_permanent and self.source is not None:
            context.add_counters(self.source, 1, "+1/+1", source=self.source)


class ExileTargetGraveyardEffect(GameEffect):
    """"Exile target player's graveyard." (Bojuka Bog/Tormod's Crypt-shaped)
    — every card in that one graveyard, untargeted per-card unlike
    `_exile_from_graveyard`'s single-card family; the untargeted "every
    graveyard" sibling is `ExileAllGraveyardsEffect` above.

    ``card_type`` (a `Card.is_<type>` flag name — "creature", "land", …)
    narrows it to "exile all `<type>` cards from that graveyard" (Crypt
    Incursion); ``None`` is the whole graveyard. The exiles run through
    `GameContext.exile`, so ``objects_exiled_this_way`` counts them — which
    is how Crypt Incursion's "gain 3 life for each card exiled this way"
    reads the count as an ENG-37 `bind` rather than needing a fused effect."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
        card_type: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.card_type = card_type
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        for obj in list(player.graveyard):
            if self.card_type and not getattr(obj.card, f"is_{self.card_type}", False):
                continue
            context.exile(obj)


class AttackerCreatesAttackingTokenEffect(GameEffect):
    """"Whenever a player attacks one of your opponents, that attacking
    player creates a tapped 2/1 white and black Inkling creature token with
    flying that's attacking that opponent." (Combat Calligrapher; the same
    "the *other* player makes the token" shape Scriv, Assemble the Legion's
    Inkling family reach for, PAR-60.)

    Reads the firing `PLAYER_ATTACKED` aggregate's ``attacking_player_id``
    (who makes and controls the token — never this ability's controller)
    and ``defending_player_id`` (which opponent it attacks). The token is
    tapped and put into the current combat attacking that specific defender
    via `RulesEngine.put_onto_battlefield_attacking` (RULE 508.4).
    """

    def __init__(
        self,
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        token_name: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.keywords = keywords or []
        self.token_name = token_name or (subtypes[0] if subtypes else "Token")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import synthesize_token_card

        event = context.trigger_event or {}
        attacker_id = event.get("attacking_player_id")
        defender_id = event.get("defending_player_id")
        if attacker_id is None:
            return
        try:
            defender_player = (
                context.state.player_by_id(defender_id) if defender_id is not None else None
            )
        except (KeyError, ValueError):
            defender_player = None
        card = synthesize_token_card(
            self.token_name, power=self.power, toughness=self.toughness,
            colors=self.colors, subtypes=self.subtypes, keywords=self.keywords,
        )
        made = context.create_token(attacker_id, card, 1)
        for tok in made or []:
            context.set_tapped(tok, tapped=True)
            defender = (
                {"kind": "player", "id": defender_player.id, "label": defender_player.name}
                if defender_player is not None else None
            )
            context.engine.put_onto_battlefield_attacking(tok, defender=defender)


class DestroyExileThenControllerRevealCreatureEffect(GameEffect):
    """"Destroy/Exile target creature. It can't be regenerated
    [destroy mode only]. Its controller reveals cards from the top of
    their library until they reveal a creature card. [That/The] player
    puts that card onto the battlefield, then shuffles [all other cards
    revealed this way/the rest] into their library." (Polymorph/
    Transmogrify-shaped) — one atomic effect, not a two-effect list,
    since the dig is run by the *target's own controller* (read before the
    removal — RULE 400.7's zone change would otherwise leave nothing to
    read a controller off of once it's in the graveyard/exile) rather than
    this ability's own controller, the same "read before it leaves the
    battlefield" idiom Nature's Claim's composition (`destroy` + a referent recipient, ENG-37) uses.

    ``mode`` picks destroy (``can_be_regenerated=False``, Polymorph) or
    exile (Transmogrify, which has no regeneration clause to carry since
    exile was never regenerable in the first place).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        mode: str = "destroy",
        criteria: Any = "Creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)
        self.mode = mode
        self.criteria = criteria

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        if self.mode == "exile":
            context.exile(target)
        else:
            context.destroy(target, can_be_regenerated=False)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        context.engine.dig_until(
            player, self.criteria,
            hit_destination="battlefield", rest_destination="library_shuffled",
        )


class ShuffleTargetIntoLibraryRevealTopEffect(GameEffect):
    """"The owner of target permanent shuffles it into their library, then
    reveals the top card of their library. If it's a permanent card, they
    put it onto the battlefield." (Chaos Warp — RULE 701.20 shuffle + a
    RULE 701.15-style reveal, PAR-60.)

    One atomic effect rather than composed pieces: the reveal is read off
    *the owner's* library right after their own shuffle (the same "the
    target's own controller/owner acts" shape `DestroyExileThenController
    RevealCreatureEffect` uses), and the two halves share no RULE 115
    target. The revealed card entering is not itself a target — Chaos Warp
    famously can hit an indestructible/hexproof-from-you permanent and drop
    a bomb for the opponent."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..graveyard_cast import _is_permanent_card  # local: avoid import cycle

        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        owner_id = getattr(target, "owner_id", None)
        context.shuffle_into_library(target)
        if owner_id is None:
            return
        try:
            owner = context.state.player_by_id(owner_id)
        except (KeyError, ValueError):
            return
        if not owner.library:
            return
        top = owner.library[-1]
        if _is_permanent_card(top.card):
            owner.remove_from_zone(top, Zone.LIBRARY)
            top.zone = Zone.BATTLEFIELD
            context.state.add_to_battlefield(top)
            context.state.fire_event(GameEvent(
                EventType.ENTERS_BATTLEFIELD, controller_id=owner.id, object=top.name,
                from_zone=Zone.LIBRARY.value,
                instance_id=top.instance_id, object_types=sorted(top.type_words),
            ))


class GainControlUntilEndOfTurnEffect(GameEffect):
    """"Gain control of target permanent until end of turn. Untap that
    permanent. It gains haste until end of turn." (RULE 108.4-adjacent —
    Zealous Conscripts/Coercive Recruiter-shaped) — a single atomic effect
    bundling the control change, the untap, and the haste grant (every real
    printed instance of this exact clause pairs all three on the *same*
    target), rather than composing 3 separate targeting effects that would
    each need their own copy of the shared target (the "two targeting
    effects double-prompt" reason `TargetPlayerDrawLoseLifeEffect`'s
    docstring gives — no plain `pump`/keyword-grant effect can reach the
    exact object this one just changed control of without `target_groups`
    machinery no real card here needs). Reverts control automatically at
    the next cleanup (`GameEngine._step_cleanup`, `GameObject.control_
    change_until_eot` remembers the original controller) — the haste grant
    is a `temp_keywords` entry, cleared at that same cleanup, matching
    "until end of turn" exactly. RULE 302.6's own "summoning sickness
    resets under a new controller" isn't separately modeled, since the
    haste grant makes the distinction unobservable either way. Doesn't move
    the object zones at all (unlike `blink`), so counters/attachments/
    damage marked all carry over exactly as the permanent itself would
    expect.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        haste: bool = True,
        max_mana_value: Optional[int] = None,
        exact_mana_value: Optional[Union[int, str]] = None,
        selector: Optional[str] = None,
        creature_filter: Optional[dict] = None,
        count_selector: Optional[str] = None,
        mass_of_target_player: Optional[str] = None,
        mark_no_sacrifice: bool = False,
        duration: str = "end_of_turn",
        untap: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "Gain control of target creature **with mana value X**."
        #: (Entrancing Melody, Mind Control / Control Magic / Persuasion /
        #: Corrupted Conscience family, PAR-60) — ``"permanent"`` makes the
        #: control change a RULE 611.2 no-duration continuous effect (a bare
        #: `controller_id` reassignment that cleanup never reverts), vs the
        #: default ``"end_of_turn"`` (`GameObject.control_change_until_eot`,
        #: reverted by `_step_cleanup`).
        self.duration = duration
        #: The Zealous Conscripts family untaps what it takes; the
        #: Mind-Control family does not — a toggle rather than always-on.
        self.untap = bool(untap)
        #: "You can't sacrifice those creatures this turn." (Call for Aid) —
        #: stamp `GameObject.cant_be_sacrificed_this_turn` on every creature
        #: this effect takes control of, so the anti-abuse rider needs no
        #: separate "which objects" plumbing.
        self.mark_no_sacrifice = mark_no_sacrifice
        #: "Gain control of all creatures/artifacts **target opponent**
        #: controls until end of turn." (Call for Aid, Ashiok Sculptor of
        #: Fears, Tezzeret Master of Metal) — a RULE 115 *player* target
        #: (``target_kind="opponent"``), then every permanent of the named
        #: kind that one player controls. Distinct from ``selector=
        #: "opponents_creatures"`` (Broadcast Takeover — *all* opponents, no
        #: target). Value is a bare type word: ``"creature"`` / ``"artifact"``.
        self.mass_of_target_player = mass_of_target_player
        #: "Untap **all creatures** and gain control of them until end of
        #: turn." (Insurrection) — the untargeted RULE 601.2c mass sibling
        #: of the single-target form above, same ``_mass_selector_objects``
        #: vocabulary `DestroyEffect.selector` uses. Only ``"all_creatures"``
        #: is meaningful here (no real card needs a different mass filter),
        #: but the param is named/shaped like every other mass effect's for
        #: consistency.
        self.selector = selector
        if self.selector is None:
            #: "Gain control of target creature **with mana value 3 or
            #: less**" (Claim the Firstborn) — a target-offer-time cap, the
            #: same `TargetSpec.max_mana_value` `DestroyEffect`/`destroy_mv`
            #: already use. ``creature_filter`` is the sibling power/
            #: toughness filter ("…**with power 2 or less**" — Enthralling
            #: Victor, PAR-30).
            #: "For each opponent, gain control of up to 1 target creature
            #: **that player controls** …" (Mass Mutiny/Molten Primordial,
            #: PAR-30) — one requirement whose *count* is the opponent
            #: count, RULE 601.2c, the same `count_selector`/`distinct_
            #: controllers` shape `GoadEffect` uses for "for each opponent,
            #: goad up to one target creature that player controls".
            self.target_spec = TargetSpec(
                kind=target_kind, max_mana_value=max_mana_value,
                # "…with **that spell's** mana value." (PAR-74, Skyfire
                # Kirin) — `TargetSpec.exact_mana_value`'s own sentinel-
                # string resolution (`targeting.legal_targets`), the
                # exact-match sibling of `max_mana_value` just above.
                exact_mana_value=exact_mana_value,
                creature_filter=creature_filter, count_selector=count_selector,
                optional=count_selector is not None,
            )
        self.haste = haste

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def _take(self, context: GameContext, target: "GameObject", controller: "Player") -> None:
        if target.controller_id != controller.id:
            if self.duration == "permanent":
                # RULE 611.2 no-duration continuous effect — cleanup must not
                # revert it, so don't stamp ``control_change_until_eot``.
                target.controller_id = controller.id
                target.summoning_sick = True  # RULE 302.6 under a new controller
            else:
                if target.control_change_until_eot is None:
                    target.control_change_until_eot = target.controller_id
                target.controller_id = controller.id
        if self.untap:
            context.set_tapped(target, tapped=False)
        if self.haste:
            target.temp_keywords.add("haste")
        if self.mark_no_sacrifice:
            target.cant_be_sacrificed_this_turn = True

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        if self.selector is not None:
            for obj in _mass_selector_objects(context, self.selector, None, source=self.source):
                self._take(context, obj, controller)
            context.recompute()
            return
        chosen = list(targets or ([self.target] if self.target is not None else []))
        if not chosen:
            return
        if self.mass_of_target_player:
            player = chosen[0]
            pid = getattr(player, "id", player)
            want_creature = self.mass_of_target_player == "creature"
            for obj in list(context.state.permanents()):
                if obj.controller_id != pid:
                    continue
                if want_creature and not obj.is_creature:
                    continue
                if self.mass_of_target_player == "artifact" and not obj.card.is_artifact:
                    continue
                self._take(context, obj, controller)
            context.recompute()
            return
        # RULE 601.2c: a `count_selector` requirement ("for each opponent,
        # gain control of up to 1 target creature that player controls")
        # yields a *list*; the single-target forms still pass exactly one.
        for target in chosen:
            self._take(context, target, controller)
        context.recompute()


class PreventAttackingPlayerThisTurnEffect(GameEffect):
    """"You can't attack that player this turn." (Call for Aid) — RULE
    508.1a, for the rest of the turn. "That player" is this effect's own
    shared RULE 115 target (no `target_spec` of its own — it reads the
    ability's `targets` list, which a `target_groups=None` ability passes
    whole to every sub-effect, the same idiom `ConditionalEffect` uses);
    "you" is the ability's controller. Records the ``(you, them)`` pair on
    `GameState.no_attack_pairs_this_turn`, swept at cleanup.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        target = (targets or [None])[0]
        them_id = getattr(target, "id", None)
        if controller is None or them_id is None:
            return
        context.state.no_attack_pairs_this_turn.add((controller.id, them_id))


class GainControlBySourceEffect(GameEffect):
    """"An opponent gains control of ~." (RULE 701.10-adjacent — Wishclaw
    Talisman-shaped: an activated ability that hands its own permanent away
    as a drawback, rather than the caster grabbing something). Unlike
    `GainControlUntilEndOfTurnEffect` (temporary, a chosen *target*, control
    moves *to* the ability's controller), this is indefinite, always the
    source itself, moves control *away* from the controller, and isn't a
    RULE 115 target at all — the printed line never says "target opponent".

    ``recipient="opponent"`` is the only kind today. With exactly one
    opponent (the common 1v1 goldfish/Replay case) the pick is unambiguous;
    with 2+ (multiplayer), this auto-picks the next player after the
    current controller in seating order — no "choose an opponent" chooser
    exists yet for a *player* (`_request_choose_objects` only offers
    `GameObject` candidates), the same "auto-pick, no chooser in this MVP"
    idiom `put_hand_cards_on_top` already documents for a value-neutral
    selection among equally-valid choices.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        recipient: str = "opponent",
    ) -> None:
        super().__init__(source)
        self.recipient = recipient
        self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        players = context.state.players
        if self.recipient == "activator":
            # "Gain control of ~." on an ability only an opponent may
            # activate (Oft-Nabbed Goat, RULE 602.2b) — control moves to
            # whoever activated it, read off the resolving ability.
            activator_id = getattr(context, "resolving_controller_id", None)
            if activator_id is None or activator_id == self.source.controller_id:
                return
            self.source.controller_id = activator_id
            context.recompute()
            return
        opponents = [p for p in players if p.id != controller.id]
        if not opponents:
            return
        idx = players.index(controller)
        ordered = players[idx + 1:] + players[:idx]
        recipient = next((p for p in ordered if p in opponents), opponents[0])
        self.source.controller_id = recipient.id
        context.recompute()


class OwnerDrawOthersLosePerDyingCounterEffect(GameEffect):
    """"When ~ dies, if it had one or more -1/-1 counters on it, its owner
    draws that many cards and each other player loses that much life."
    (Oft-Nabbed Goat.)

    ``N`` is the ``-1/-1`` count on the firing DIES event's RULE 400.7
    snapshot (the object is already gone). "Its owner" is ~'s owner, not its
    controller — Oft-Nabbed Goat's own ability hands control to an opponent,
    so at death the two usually differ; "each other player" is everyone
    except that owner.
    """

    def __init__(self, counter_kind: str = "-1/-1", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.counter_kind = counter_kind

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        event = context.trigger_event or {}
        n = int((event.get("counters") or {}).get(self.counter_kind, 0) or 0)
        if n <= 0:
            return
        owner = next(
            (p for p in context.state.players if p.id == getattr(self.source, "owner_id", None)),
            None,
        )
        if owner is None:
            return
        context.draw(owner, n)
        for player in context.state.players:
            if player.id != owner.id:
                context.lose_life(player, n)


class GainControlAttachedEffect(GameEffect):
    """"Gain control of enchanted creature." / "That player gains control of
    enchanted creature." (Captivating Glance's clash win / otherwise
    branches) — an indefinite control change of this Aura's *host*, moved
    to whichever player ``recipient`` names, no RULE 115 target.

    ``recipient`` ∈ ``"controller"`` (this ability's own controller — the
    "if you win" branch) or ``"clashed_opponent"`` (the opponent the
    preceding `ClashEffect` clashed with — the "otherwise" branch, read off
    `GameContext.clashed_opponent`). Applied as a direct ``controller_id``
    mutation + recompute, the same documented simplification
    `GainControlBySourceEffect` makes for a permanent (not layer-2)
    control change in this MVP.
    """

    def __init__(
        self, recipient: str = "controller", source: Optional["GameObject"] = None
    ) -> None:
        super().__init__(source)
        self.recipient = recipient

    def target_polarity(self) -> Optional[str]:
        return "beneficial" if self.recipient == "controller" else "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        host_id = getattr(self.source, "attached_to", None)
        host = context.state.find_object(host_id) if host_id is not None else None
        if host is None:
            return
        if self.recipient == "clashed_opponent":
            recipient = getattr(context, "clashed_opponent", None)
        else:
            recipient = _controller_of(self.source, context)
        if recipient is None or host.controller_id == recipient.id:
            return
        host.controller_id = recipient.id
        context.recompute()


class MayBeholdThenUntapLinkedEffect(GameEffect):
    """"You may behold a(n) `<type>`. If you do, untap that land." (Elven
    Passage — PAR-30) — the reflexive tail of a "search your library for a
    basic land, put it onto the battlefield tapped" activated ability. The
    land searched up is on this ability's own source (`GameObject.
    linked_exile_id`, stamped by the preceding `search` effect's
    ``remember=True``, the O-Ring field); this untaps it when the behold
    succeeds.

    **Documented simplification:** the "you may" is auto-taken whenever the
    controller *can* behold (controls / holds a matching card) — beholding
    reveals a card at no cost and the payoff is pure upside (a fetched land
    untapped), the same "auto-pick, no chooser in this MVP" idiom
    `collect_evidence` / `forage` / `blight` use for a value-neutral or
    strictly-beneficial choice.
    """

    def __init__(self, quality: str = "Elf", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.quality = quality

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        linked_id = getattr(self.source, "linked_exile_id", None)
        self.source.linked_exile_id = None
        if linked_id is None:
            return
        land = context.state.find_object(linked_id)
        if land is None or land.zone != Zone.BATTLEFIELD:
            return
        player = _controller_of(self.source, context)
        if player is None:
            return
        if context.engine.behold(player, self.quality, source=self.source):
            context.engine.set_tapped(land, False)


class CollectEvidenceXThenBoardDamageEffect(GameEffect):
    """Incinerator of the Guilty (PAR-30): "Whenever this creature deals
    combat damage to a player, you may collect evidence X. When you do, this
    creature deals X damage to each creature and planeswalker **that
    player** controls."

    "That player" is the combat-damage recipient, read off the firing
    `DAMAGE` event's ``target_id``.

    **Documented simplification:** X — the player's choice of how much
    evidence to collect — is taken as the maximum (every card in the
    controller's graveyard is exiled), since a larger X is strictly better
    for the payoff and costs nothing beyond those graveyard cards; the same
    "auto-pick the strongest line" idiom `RulesEngine.collect_evidence`'s
    own highest-MV-first exile already uses. The RULE 603.11 reflexive "when
    you do" is folded in here rather than fired as its own trigger, because
    the payoff takes no RULE 115 target (an untargeted mass selector).
    """

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None:
            return
        controller = _controller_of(src, context)
        event = context.trigger_event or {}
        victim = None
        vid = event.get("target_id")
        if vid is not None:
            try:
                victim = context.state.player_by_id(vid)
            except (KeyError, ValueError):
                victim = None
        if controller is None or victim is None:
            return
        x = sum(c.card.converted_mana_cost for c in controller.graveyard)
        if x <= 0:
            return
        context.engine.collect_evidence(controller, x)  # exiles all; fires COLLECTED_EVIDENCE
        for obj in list(context.state.battlefield):
            if obj.controller_id == victim.id and (
                getattr(obj, "is_creature", False) or getattr(obj, "is_planeswalker", False)
            ):
                context.deal_damage(obj, x, src)


class CelestialReunionSearchEffect(GameEffect):
    """Celestial Reunion (PAR-30): "Search your library for a creature card
    with mana value X or less, reveal it, put it into your hand, then
    shuffle. If this spell's additional cost was paid and the revealed card
    is the chosen type, put that card onto the battlefield instead of
    putting it into your hand."

    X is the spell's own announced ``{X}`` (`GameObject.x_paid`). The
    conditional destination rides `_request_search`'s ``destination_if``: a
    ``{"type": <chosen creature type>}`` criteria → ``"battlefield"``,
    active only when the optional "choose a creature type and behold two
    creatures of that type" additional cost was paid
    (`GameObject.additional_cost_paid` + `GameObject.chosen_type`, both
    stamped by `GameEngine._pay_additional_cast_cost`).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None:
            return
        player = _controller_of(src, context)
        if player is None:
            return
        x = getattr(src, "x_paid", 0) or 0
        criteria: dict[str, Any] = {"type": "Creature", "max_mana_value": x}
        destination_if = None
        chosen = getattr(src, "chosen_type", None)
        if getattr(src, "additional_cost_paid", False) and chosen:
            destination_if = [
                {"criteria": {"type": str(chosen)}, "destination": "battlefield"}
            ]
        context._request_search(
            player, criteria, "hand", 1, optional=True,
            destination_if=destination_if, source=src,
        )


class MemoryVampireCombatEffect(GameEffect):
    """Memory Vampire (PAR-30): "Whenever this creature deals combat damage
    to a player, any number of target players each mill that many cards.
    Then you may collect evidence 9. When you do, you may cast target
    nonland card from defending player's graveyard without paying its mana
    cost."

    "That many" / "defending player" are read off the firing `DAMAGE`
    event (``amount`` / ``target_id``).

    **Documented simplifications:**
    * "any number of target players" → every opponent mills ``amount``
      cards (the aggressive intent; a self-mill line isn't auto-taken).
    * "you may collect evidence 9. When you do, you may cast …" → the
      collect and the follow-up cast are auto-taken when able, and the
      RULE 115 "target nonland card" is the highest-mana-value nonland card
      in the damaged player's graveyard — the same "auto-pick the strongest
      line, no chooser in this MVP" idiom `collect_evidence` itself uses.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None:
            return
        controller = _controller_of(src, context)
        event = context.trigger_event or {}
        amount = int(event.get("amount") or 0)
        victim = None
        vid = event.get("target_id")
        if vid is not None:
            try:
                victim = context.state.player_by_id(vid)
            except (KeyError, ValueError):
                victim = None
        if controller is None or victim is None or amount <= 0:
            return
        for player in context.state.living_players():
            if player.id != controller.id:
                context.engine.mill(player, amount)
        if not context.engine.collect_evidence_possible(controller, 9):
            return
        context.engine.collect_evidence(controller, 9)
        candidates = [
            c for c in list(victim.graveyard)
            if not getattr(c.card, "is_land", False)
        ]
        if not candidates:
            return
        pick = max(candidates, key=lambda c: c.card.converted_mana_cost or 0)
        context.engine.cast_without_paying(controller, pick)


class ReturnLinkedExileEffect(GameEffect):
    """"When this leaves the battlefield, return the exiled card to the
    battlefield under its owner's control." (Leonin Relic-Warder/O-Ring-
    shaped) — the return half of an `ExileEffect(remember=True)` pair:
    reads the linked card's ``instance_id`` off this ability's own source
    (stamped by the earlier ETB exile, survives however long the card
    stays exiled) rather than a RULE 115 target — nothing was ever chosen
    here, "the exiled card" is a fixed reference. A no-op if nothing is
    currently linked (the "may exile" ETB was declined) or the linked card
    already left exile some other way (bounced back by a third effect,
    etc.).

    ``destination`` defaults to ``"battlefield"`` (O-Ring). The Lorwyn
    "Champion" cycle reflavoured (Champion of the Clachan &c. — PAR-30)
    prints "return the exiled card to its owner's **hand**" instead, paired
    with a ``behold_exile`` additional cast cost that stamps
    `linked_exile_id`; ``destination="hand"`` covers that.
    """

    def __init__(
        self, destination: str = "battlefield", source: Optional["GameObject"] = None
    ) -> None:
        super().__init__(source)
        self.destination = destination

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        linked_id = getattr(self.source, "linked_exile_id", None)
        self.source.linked_exile_id = None
        if linked_id is None:
            return
        card_obj = context.state.find_object(linked_id)
        if card_obj is None or card_obj.zone != Zone.EXILE:
            return
        context.return_from_graveyard(card_obj, self.destination)


class ReturnAllExiledWithEffect(GameEffect):
    """"When this leaves the battlefield, each player returns to the
    battlefield all cards they own exiled with it." (MEC-12, Parallax
    Wave/Abdel Adrian, Gorion's Ward-shaped) — the mass sibling of
    `ReturnLinkedExileEffect`: reads `GameObject.exiled_with_ids` (MEC-21's
    accumulating tracker, stamped by `ExileEffect(track_exiled_with=True)`)
    instead of the single-slot `linked_exile_id`, since a repeatable
    "remove a counter: exile target creature"-shaped ability can link
    arbitrarily many cards over the source's lifetime, potentially owned
    by several different players. Each returns under **its own owner's**
    control (`return_from_graveyard`'s default), not this source's
    controller — "each player" in the printed text, not "you".
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        ids = list(getattr(self.source, "exiled_with_ids", None) or [])
        self.source.exiled_with_ids = []
        for instance_id in ids:
            card_obj = context.state.find_object(instance_id)
            if card_obj is None or card_obj.zone != Zone.EXILE:
                continue
            context.return_from_graveyard(card_obj, "battlefield")


class CreateTokenForLinkedExileEffect(GameEffect):
    """"When this creature leaves the battlefield, the exiled card's owner
    creates an X/X `<colors>` `<subtypes>` creature token, where X is the
    mana value of the exiled card." (MEC-12, Skyclave Apparition) — reads
    the linked card (`GameObject.linked_exile_id`, the same O-Ring-shaped
    field `ExileEffect(remember=True)`/`ReturnLinkedExileEffect` use) one
    last time for its owner and mana value, then hands off to the ordinary
    token-creation choke point (`GameContext.create_token`) under *that*
    owner's control — unlike every `CreateTokenEffect` caller, the
    recipient here is neither "you" nor a fixed "each_player"/
    "each_opponent" but whoever happens to own the specific card that was
    exiled. A no-op if nothing is linked (the "up to one" ETB was
    declined) — matching `ReturnLinkedExileEffect`'s own treatment of that
    case — or if the linked card has since left exile some other way.
    """

    def __init__(
        self,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.keywords = keywords or []

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        linked_id = getattr(self.source, "linked_exile_id", None)
        self.source.linked_exile_id = None
        if linked_id is None:
            return
        card_obj = context.state.find_object(linked_id)
        if card_obj is None or card_obj.zone != Zone.EXILE:
            return
        from ...services.token_database import synthesize_token_card

        x = int(card_obj.card.converted_mana_cost or 0)
        token_card = synthesize_token_card(
            self.subtypes[0] if self.subtypes else "Token",
            power=x, toughness=x, colors=self.colors, subtypes=self.subtypes, keywords=self.keywords,
        )
        made = context.create_token(card_obj.owner_id, token_card) or []
        context.created_objects.extend(made)


class ExileOwnGraveyardCardManaValueXEffect(GameEffect):
    """"Exile target creature card with mana value X from your graveyard.
    ..." (Lazotep Quarry, MEC-41's own ``{X}{2}, {T}, Sacrifice a Desert:``
    activated ability) — opens a `_request_choose_objects` pick among the
    controller's own graveyard creature cards whose mana value equals the
    source's own announced ``{X}`` (`GameObject.x_paid`, now stamped for an
    ability's own source too — see `GameEngine.activate_ability`).

    **Documented simplification**: RULE 115's "target" is read as this
    resolve-time pick instead. A genuine RULE 115 target here would need X
    threaded into `legal_targets` *before* targets are gathered (RULE
    601.2b announces X ahead of RULE 602.2b's targets) — no activated
    ability in this engine does that yet (`GameEngine._ability_target_
    requirements` computes every requirement's legal options with no X
    known), and building that sequencing for one card's own graveyard-only
    pick (where hexproof/protection/an opponent's response don't apply
    regardless) is disproportionate. ``then_specs`` fires once a pick is
    made, via ``remember=True``'s `GameObject.linked_exile_id`.
    """

    def __init__(
        self,
        creature_only: bool = True,
        then_specs: Optional[list[dict]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.creature_only = creature_only
        self.then_specs = list(then_specs or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        x = getattr(self.source, "x_paid", 0) or 0
        candidates = [
            o for o in player.graveyard
            if (o.is_creature or not self.creature_only)
            and o.card.converted_mana_cost == x
        ]
        context.engine._request_choose_objects(
            player, candidates, "exile", count=1, source=self.source,
            remember=True, then_specs=self.then_specs,
        )


class CreateTokenCopyOfLinkedExileEffect(GameEffect):
    """The token-*copy* sibling of `CreateTokenForLinkedExileEffect` just
    above: makes a token that's a genuine copy of the linked exiled card's
    own printed characteristics (RULE 707.2) instead of a synthesized X/X,
    reusing the same override vocabulary `CopyPermanentEffect` already
    exposes (``set_power``/``set_toughness``/``add_subtypes``). Lazotep
    Quarry's own "... Create a token that's a copy of it, except it's a 4/4
    ... Zombie." (MEC-41), paired with `ExileOwnGraveyardCardManaValueX
    Effect`'s own ``remember=True`` pick.

    Colour ("black") is dropped, the same documented simplification The
    Jolly Balloon Man's own catalogue entry accepts — `Card.as_copy` has no
    colour-override mechanism (CLAUDE.md's own documented gotcha).
    """

    def __init__(
        self,
        set_power: Optional[int] = None,
        set_toughness: Optional[int] = None,
        add_subtypes: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.set_power = set_power
        self.set_toughness = set_toughness
        self.add_subtypes = add_subtypes

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        linked_id = getattr(self.source, "linked_exile_id", None)
        self.source.linked_exile_id = None
        if linked_id is None:
            return
        card_obj = context.state.find_object(linked_id)
        if card_obj is None or card_obj.zone != Zone.EXILE:
            return
        controller_id = self.source.controller_id
        made = context.engine.copy_permanent(
            controller_id, card_obj, set_power=self.set_power,
            set_toughness=self.set_toughness, add_subtypes=self.add_subtypes,
        )
        context.created_objects.extend(made or [])


class ChooseVoidCounterCardEffect(GameEffect):
    """"Choose an exiled card an opponent owns with a void counter on it.
    You may play it this turn without paying its mana cost." (Dauthi
    Voidwalker, MEC-42) — gathers the live candidate pool (any card in an
    *opponent's* exile zone still carrying `GameState.void_counter_
    holder`, stamped by `continuous.void_counter_redirect_controller_for`'s
    standing replacement) and opens the already-general chooser via the
    ``"grant_free_cast"`` action (MEC-20's "arm a temporary, same-turn
    free-cast window" shape) — just over a different candidate pool than
    that action's own hand-zone origin.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        candidates = [
            obj
            for other in context.state.players
            if other.id != player.id
            for obj in other.exile
            if obj.instance_id in context.state.void_counter_holder
        ]
        if not candidates:
            return
        context.engine._request_choose_objects(
            player, candidates, "grant_free_cast", count=1, optional=True, source=self.source,
        )


class ExileLibraryEffect(GameEffect):
    """"Exile all cards from your library." (Paradigm Shift-shaped) — an
    untargeted, hidden-zone-to-exile mass move: a library's contents are
    never legal RULE 115 targets, and `ExileEffect.selector`'s mass-board-
    wipe vocabulary only ever reads the *battlefield*, so this is its own
    effect rather than a reused selector.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in list(player.library):
            context.exile(obj)


class ExileOwnGraveyardCardsEffect(GameEffect):
    """Exile N cards from your graveyard (RULE 701.5a)."""

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = max(1, int(count))

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        candidates = list(controller.graveyard)
        if not candidates:
            return
        context.engine._request_choose_objects(
            controller, candidates, action="exile", count=self.count,
            source=self.source,
            prompt=f"{self.count} Karten aus deinem Friedhof ins Exil schicken",
        )


class ShuffleGraveyardIntoLibraryEffect(GameEffect):
    """"Shuffle your graveyard into your library." (RULE 701.20) — the
    graveyard-only sibling of `RulesEngine.shuffle_hand_and_graveyard_
    into_library`'s "hand AND graveyard" wheel template; reused wherever
    only the graveyard moves (Paradigm Shift).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in list(player.graveyard):
            player.remove_from_zone(obj, Zone.GRAVEYARD)
            player.add_to_zone(obj, Zone.LIBRARY)
        context.shuffle_library(player)


class ShuffleTargetGraveyardCardsIntoLibraryEffect(GameEffect):
    """"Target player shuffles up to three target cards from their graveyard
    into their library." (Quandrix Command's fourth mode) — RULE 701.20 over
    a chosen subset rather than the whole graveyard.

    The picks are the spell's controller's to make (RULE 601.2c), out of the
    *targeted* player's graveyard, and each returns to that player's own
    library (RULE 404 "their"). Modeled as a resolve-time
    `_request_choose_objects` (action ``graveyard_to_library``, which also
    shuffles) rather than three separate card `TargetSpec`s — an accepted
    RULE 115 precision loss in line with this module's norms.
    """

    #: Quandrix Command's own "up to three".
    DEFAULT_CARD_CAP = 3

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        count_max: int = DEFAULT_CARD_CAP,
    ) -> None:
        super().__init__(source)
        self.count_max = int(count_max)
        self.target_spec = TargetSpec(kind="player")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target_player = (targets[0] if targets else None) or getattr(self, "target", None)
        chooser = _controller_of(self.source, context)
        if target_player is None or chooser is None:
            return
        pool = list(target_player.graveyard)
        if not pool:
            return
        context.engine._request_choose_objects(
            chooser,
            pool,
            "graveyard_to_library",
            count=self.count_max,
            optional=True,
            prompt="Bis zu drei Karten aus dem Friedhof in die Bibliothek mischen",
            source=self.source,
        )


class NoMaxHandSizeRestOfGameEffect(GameEffect):
    """"You have no maximum hand size for the rest of the game." (Spirit
    Water Revival) — a resolve-time grant, so it lives as a player-id flag
    on `GameState.no_max_hand_size_player_ids` (consulted by `continuous.
    has_no_maximum_hand_size`) rather than a battlefield-static
    `no_max_hand_size` layer. Never expires (rest of the game) and is RULE
    400.7-safe (keyed by the player, not an object)."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.state.no_max_hand_size_player_ids.add(player.id)


class GraveyardToLibraryBottomRandomEffect(GameEffect):
    """"Up to one target player puts all the cards from their graveyard on
    the bottom of their library in a random order." (Endurance-shaped) —
    RULE 701.20-adjacent; unlike a plain `shuffle_library` call (which
    randomizes the *whole* library), this only randomizes the moved batch's
    own relative order among themselves before appending it to the bottom,
    leaving the existing library order above them untouched.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        moved = list(player.graveyard)
        if not moved:
            return
        random.shuffle(moved)
        for obj in moved:
            player.remove_from_zone(obj, Zone.GRAVEYARD)
        for obj in moved:
            player.library.insert(0, obj)
            obj.zone = Zone.LIBRARY


class TopUpPlayerCounterToThresholdEffect(GameEffect):
    """"If target player has fewer than N [kind] counters, they get a
    number of [kind] counters equal to the difference." (Vraska,
    Betrayal's Sting's -9) — a threshold top-up rather than a flat amount;
    a player already at or past the threshold gets none.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
        kind: str = "poison",
        threshold: int = 9,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.kind = kind
        self.threshold = threshold
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        current = getattr(player, self.kind, None)
        if current is None:
            current = player.counters.get(self.kind, 0)
        diff = self.threshold - int(current or 0)
        if diff > 0:
            context.add_player_counters(player, diff, self.kind, source=self.source)


class TransformNamedTokensEffect(GameEffect):
    """"Transform all Incubator tokens you control." (Glissa, Herald of
    Predation) — applies the same permanent creature-animation every
    Incubator token's own "{2}: Transform this token" ability does
    (`type_change`'s existing power/toughness-animation static, granted
    at ``duration="rest_of_game"``) to every matching token at once, for
    free, rather than one at a time through its own activated ability.
    An already-transformed (already-creature) token is skipped — nothing
    left to transform.
    """

    def __init__(
        self,
        token_name: str = "Incubator",
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        power: int = 0,
        toughness: int = 0,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.token_name = token_name
        self.add_types = list(add_types or ["creature"])
        self.add_subtypes = list(add_subtypes or [])
        self.power = power
        self.toughness = toughness

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        for obj in list(context.state.battlefield):
            if not (
                obj.controller_id == controller_id
                and obj.card.is_token
                and obj.card.name == self.token_name
                and not obj.is_creature
            ):
                continue
            GrantUntilEffect(
                static={
                    "type": "type_change",
                    "params": {
                        "add_types": self.add_types, "add_subtypes": self.add_subtypes,
                        "power": self.power, "toughness": self.toughness,
                    },
                },
                duration="rest_of_game",
                target_kind=None,
                source=obj,
            ).apply(context)


class EachOpponentCounterOwnCreatureEffect(GameEffect):
    """"Each opponent blights N. (They each put N -1/-1 counters on a
    creature they control.)" (High Perfect Morcant) — RULE 122's per-
    opponent fan-out: each opponent independently puts the counters on a
    creature they control. **Documented simplification**: auto-picked (the
    first creature found) rather than routed through a real per-opponent
    chooser — the same "not worth a chooser for a single pick" convention
    `SacrificeEffect.greatest_power` already uses; an opponent with no
    creature simply gets nothing.
    """

    def __init__(
        self, amount: int = 1, kind: str = "-1/-1", source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.kind = kind

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller_id = getattr(self.source, "controller_id", None)
        for player in context.state.living_players():
            if player.id == controller_id:
                continue
            creatures = [o for o in context.state.permanents_controlled_by(player.id) if o.is_creature]
            if creatures:
                context.add_counters(creatures[0], self.amount, self.kind, source=self.source)


class DamageThenInvestigateIfExcessEffect(GameEffect):
    """"~ deals twice X damage to target creature. If excess damage was
    dealt to that creature this way, investigate." (Torch the Witness) —
    RULE 120.9's "excess damage" (more than needed to be lethal): the
    dealt amount compared against the target's toughness net of damage
    already marked, read *before* this damage lands — a single atomic
    effect since the check needs that pre-damage snapshot, not the
    post-damage `GameObject.damage_marked` total (which could already
    include unrelated damage from earlier this turn).
    """

    def __init__(
        self, target: Any = None, source: Optional["GameObject"] = None, target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        x_paid = getattr(self.source, "x_paid", 0) or 0
        amount = x_paid * 2
        remaining = (target.toughness or 0) - target.damage_marked
        context.deal_damage(target, amount, self.source)
        if amount > max(remaining, 0):
            player = _controller_of(self.source, context)
            if player is not None:
                from ...services.token_database import default_token_database

                clue = default_token_database().get_token("Clue")
                if clue is not None:
                    context.create_token(player.id, clue, 1)


class CantBeCounteredThisTurnEffect(GameEffect):
    """"Spells you control can't be countered this turn." (Veil of Summer) / "Creature
    spells you cast this turn can't be countered." (Domri, Anarch of Bolas) / "The next
    spell you cast this turn can't be countered." (Mistrise Village) — records an
    `UncounterableGrant`, which `RulesEngine._is_cant_be_countered` reads. A continuous
    effect, not a trigger: it also covers a spell already on the stack."""

    def __init__(
        self,
        card_types: Optional[list[str]] = None,
        next_only: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.card_types = card_types
        self.next_only = next_only

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine._grant_uncounterable(player, self.card_types, self.next_only)


class ExileHandEffect(GameEffect):
    """"Exile all the cards from your hand." — an untargeted, hidden-zone
    mass move (a hand's contents are never legal RULE 115 targets), the
    exact sibling of `ExileLibraryEffect`. The "…, then draw that many
    cards" tail (Invasion of Kaldheim) is a `bind` over ``resource:
    hand_size`` around this + a `draw` (ENG-37 B7 retired the fused
    `exile_hand_then_draw_that_many` type).

    **Documented simplification** (carried over from the fused class): the
    trailing "until the end of your next turn, you may play cards exiled
    this way" isn't modeled — no primitive grants a *set* of specific
    exiled cards a multi-turn play window the way `ImpulsiveDrawEffect`
    does for a *library* exile; the cards are simply gone.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for card in list(player.hand):
            context.exile(card)


class ExileTopFromEachPlayerCastFreeEffect(GameEffect):
    """"Exile the top card of each player's library, then you may cast any
    number of spells from among those cards without paying their mana
    costs." (Etali, Primal Storm) — reuses `RulesEngine.grant_free_cast_
    window_from_exile` (Rebound/Beseech the Mirror's own "cast from exile
    free" window) per exiled *nonland* card, one per player, all opened
    for *this* effect's own controller (RAW: "**you** may cast any number
    of spells from among those cards" — not each card's owner) rather
    than the method's own default of the card's ``controller_id``, so a
    control reassignment happens first. A land card is still exiled
    unconditionally (that part of the ability has no filter), but never
    gets a free-cast window — Scryfall's own ruling is explicit that "any
    cards not cast, including land cards, remain in exile," and since this
    ability only ever offers to *cast* what it finds (never "play"), a
    land here must not become playable either; `grant_free_cast_window_
    from_exile`'s permission is generic enough to also satisfy
    `GameEngine.can_play_land` (it backs cards like Ragavan/Light Up the
    Stage that *do* let a found land be played), so leaving lands
    unfiltered here would have wrongly let Etali play them.

    ``until_nonland`` (Etali, Primal Conqueror's ETB trigger — "each
    player exiles cards from the top of their library until they exile a
    nonland card") widens the per-player dig from a fixed single card to
    `RulesEngine._exile_top_until`'s existing "keep exiling past lands
    until a nonland hit, or the library empties" shape — the same
    primitive cascade/discover already use. Every card exiled along the
    way (lands included) stays in exile; only the nonland hit, if any,
    opens a free-cast window.
    """

    def __init__(self, source: Optional["GameObject"] = None, until_nonland: bool = False) -> None:
        super().__init__(source)
        self.until_nonland = bool(until_nonland)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for p in context.state.living_players():
            if self.until_nonland:
                card, _exiled = context.engine._exile_top_until(p, {}, exclude_lands=True)
            else:
                if not p.library:
                    continue
                card = p.library[-1]
                context.exile(card)
            if card is None or card.card.is_land:
                continue
            card.controller_id = player.id
            context.engine.grant_free_cast_window_from_exile(card, ignore_timing=True)


class GrantDieToExileThisTurnEffect(GameEffect):
    """"If that creature would die this turn, exile it instead." (Lava
    Coil/Smite the Deathless/Torch the Tower-shaped) — the resolve-time,
    single-target, single-turn sibling of `ReplacementRegistry`'s standing
    ``"die_to_exile"`` (a *permanent*'s own printed ability, scoped by
    ``subject`` off ``effect.source``). This instead appends a fresh
    `ReplacementEffect` straight onto the target's own `GameObject.
    replacement_effects` — the same "just add to the list" idiom a bind-
    on-load ability normally arrives by — with the turn number baked into
    its condition at grant time so it expires on its own once the turn
    moves on, no `GameState.floating_statics`/duration-sweep machinery
    needed for a grant this narrow.
    """

    def __init__(
        self, target: Any = None, source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None, previous_subject: bool = False,
        damaged_this_way: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "~ deals N damage to target creature. **If that creature would
        #: die this turn, exile it instead.**" (PAR-40 — Magma Spray / Feed
        #: the Flames / Bleed Dry) — the trailing sentence has no RULE 115
        #: target of its own; it arms the replacement on whatever creature
        #: the *preceding* clause targeted (`GameContext.previous_targets`),
        #: the same shape `PumpEffect.previous_subject` uses. No
        #: `target_spec` in that mode, so `RulesEngine._trigger_target_specs`
        #: doesn't open a spurious RULE 115 choice for it.
        self.previous_subject = bool(previous_subject)
        #: MEC-81: "~ deals N damage to **each creature**. **If a creature
        #: dealt damage this way would die this turn, exile it instead.**"
        #: (Anger of the Gods / Crush the Weak / Serpentine Spike / Demonfire).
        #: Mass and multi-target damage never populate `previous_targets` with
        #: the hit set, so this arm reads `GameContext.damaged_this_way` —
        #: every permanent an earlier `deal_damage` clause of this same
        #: resolution actually hit — and arms the replacement on exactly that
        #: set. Supersedes `previous_subject` whenever the "before" clause
        #: dealt damage (it's the same set for a single target, and correct
        #: for the mass case where `previous_subject` armed on nobody).
        self.damaged_this_way = bool(damaged_this_way)
        self.target_spec = (
            TargetSpec(kind=target_kind)
            if target_kind is not None
            and not self.previous_subject
            and not self.damaged_this_way
            else None
        )

    def _arm(self, target: Any, context: GameContext) -> None:
        armed_turn = context.state.internal_turn.number
        target_id = target.instance_id

        def _condition(e: GameEvent, c: GameContext, turn=armed_turn, tid=target_id) -> bool:
            return c.state.internal_turn.number == turn and e.get("target_id") == tid

        def _replace(e: GameEvent, c: GameContext) -> Optional[GameEvent]:
            obj = c.state.find_object(e.get("target_id"))
            if obj is not None:
                c.engine.exile(obj)
            return None

        target.replacement_effects.append(
            ReplacementEffect(
                event_type=EventType.WOULD_DIE,
                replacement_fn=_replace,
                condition=_condition,
                description="exile instead of dying this turn",
            )
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.damaged_this_way:  # MEC-81 — the actual hit set
            for hit in list(getattr(context, "damaged_this_way", [])):
                if hasattr(hit, "instance_id"):
                    self._arm(hit, context)
            return
        if self.previous_subject:
            for prev in list(context.previous_targets):
                if hasattr(prev, "instance_id"):
                    self._arm(prev, context)
            return
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        self._arm(target, context)


class TriggerDoublerEffect(GameEffect):
    """"If `<cause>` causes a triggered ability of a permanent you control to
    trigger, that ability triggers an additional time." / "If a triggered ability
    of `<subject>` triggers, …" (RULE 603.2d — Roaming Throne, Panharmonicon,
    Elesh Norn, Teysa Karlov, Delney …) — a continuous marker like
    `TopLibraryPermissionEffect`/`CantBeCounteredEffect`: no layer behaviour of
    its own (``apply()`` is a no-op), just something `game/rules/triggers_mixin.py`'s
    `_collect_triggers` scans (`continuous.trigger_doubler_bonus`) when deciding how
    many times to place a permanent's triggered ability on the stack.

    Two independent, optional halves (PAR-122 — they replaced seven flat flags,
    one per printed variation):

    ``cause`` is a trigger-shaped dict — the same ``event`` / ``condition`` /
    ``filter`` / ``phase_relation`` / ``spell_filter`` keys an `AbilitySpec.trigger`
    carries — answered by the binder's own `_trigger_condition` predicate against the
    firing event, so "a creature you control attacking" means exactly what "whenever
    a creature you control attacks" means. Absent = any cause.

    ``subject`` scopes the *doubled* permanent: ``filter`` (a
    `combat.matches_object_filter` dict — a creature type, a power bound, "of the
    chosen type" via ``subtype_from_source``, "you control but don't own"),
    ``other`` ("another": not this doubler itself) and ``attached`` ("equipped
    creature"). Absent = any permanent its controller controls.

    ``active_if`` is a RULE 613.6 "as long as …" gate on the whole doubler.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        cause: Optional[dict[str, Any]] = None,
        subject: Optional[dict[str, Any]] = None,
        active_if: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.cause = dict(cause) if cause else None
        self.subject = dict(subject) if subject else None
        self.active_if = dict(active_if) if active_if else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class GrantFlashUntilEndOfTurnEffect(GameEffect):
    """"You may cast spells this turn as though they had flash." (Borne
    Upon a Wind-shaped) — stamps `GameState.temp_flash_until_turn` for the
    effect's controller, consulted by `GameEngine.can_cast`'s sorcery-speed
    timing gate; naturally expires once the turn number advances, no
    cleanup-step bookkeeping needed (unlike the `temp_*` `GameObject`
    fields `_step_cleanup` clears).

    ``card_types`` (PAR-124, Complete the Circuit's "cast **sorcery**
    spells this turn as though they had flash") narrows the grant to a
    printed type word, stamped onto the sibling `GameState.
    temp_flash_until_turn_types` field instead — kept apart from the
    unrestricted grant above so a type-scoped instance is never mistaken
    for a blanket one.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        card_types: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.card_types = list(card_types) if card_types else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        turn = context.state.internal_turn.number
        if self.card_types:
            context.state.temp_flash_until_turn_types[player.id] = (turn, tuple(self.card_types))
        else:
            context.state.temp_flash_until_turn[player.id] = turn


class ExileControllerSearchesBasicLandEffect(GameEffect):
    """"Exile target creature you don't control. For each creature exiled
    this way, its controller searches their library for a basic land
    card. Those players put those cards onto the battlefield tapped, then
    shuffle." (Winds of Abandon, single-target cast — Overload's "each
    opponent" rewrite isn't modeled, see the catalogue entry) — the search
    is offered to the *exiled creature's own controller*, not the caster,
    the same "read the target's last-known controller off the object after
    the zone change" resolution `create_token` with ``creators="previous_
    target_controller"`` uses.
    ``target_kind="creature"`` (broader than "you don't control" — no
    target kind carries an ownership exclusion yet) is a documented
    simplification, mirroring `ExileControllerSearchesBasicLandEffect`'s
    siblings elsewhere in this file.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.exile(target)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        context._request_search(player, {"basic": True}, "battlefield_tapped", 1, False)


class DestroyControllerMaySearchBasicLandEffect(GameEffect):
    """"Destroy target artifact, enchantment, or nonbasic land an opponent
    controls. That player may search their library for a land card with a
    basic land type, put it onto the battlefield, then shuffle." (Boseiju,
    Who Endures's Channel ability) — `ExileControllerSearchesBasicLandEffect`'s
    destroy-shaped sibling: destroy (so RULE 616 indestructible/regeneration
    still applies, unlike exile) rather than exile, the search is *optional*
    and untapped rather than Winds of Abandon's mandatory tapped one, and
    "a land card with a basic land type" (any land carrying a basic land
    type, not only a true basic) is `_request_search`'s own criteria dict.
    ``target_kind`` drops the "an opponent controls" restriction — no target
    kind carries an ownership exclusion yet, the same documented
    simplification `ExileControllerSearchesBasicLandEffect` uses.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "artifact_enchantment_or_nonbasic_land",
        can_be_regenerated: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.can_be_regenerated = can_be_regenerated
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.destroy(target, can_be_regenerated=self.can_be_regenerated)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        context._request_search(
            # "a land card with a basic land type" — `card_query`'s "basic"
            # criterion (RULE 205.4h supertype) rather than a stricter
            # basic-land-*type* check; the two coincide for every real card
            # in this cache, the same simplification precedent Winds of
            # Abandon's own basic-land search uses.
            player, {"basic": True}, "battlefield", 1, True,
        )


class TargetPlayerCounterEachCreatureEffect(GameEffect):
    """"Target player puts a `<kind>` counter on each creature they control."
    (Shadrix Silverquill's third mode, PAR-60.) A real RULE 115 player
    target whose creatures — not this ability's controller's — get the
    counters: "one shared player target, mass-counter body". (The
    Sign-in-Blood-shaped "target player draws N and loses M" sibling this
    used to cite is now an ENG-37 B4 `seq` of `draw` + `lose_life`
    (``previous_subject``), not a fused type.)
    """

    def __init__(
        self, amount: int = 1, kind: str = "+1/+1", target: Any = None,
        source: Optional["GameObject"] = None, target_kind: str = "player",
    ) -> None:
        super().__init__(source)
        self.amount = int(amount)
        self.kind = kind
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        for obj in list(context.state.permanents_controlled_by(player.id)):
            if obj.is_creature:
                context.add_counters(obj, self.amount, self.kind, source=self.source)
        context.recompute()


class EachPlayerExileFromGraveyardThenCountersEffect(GameEffect):
    """"Whenever Augusta attacks, each player exiles a card from their
    graveyard. When one or more nonland cards are exiled this way, put that
    many +1/+1 counters on target attacking creature." (Augusta, Order
    Returned, PAR-60.)

    A single atomic effect over one shared RULE 115 target (``creature`` +
    ``{"attacking": True}``), the same "two targeting effects would
    double-prompt" reason `CounterUntapGrantKeywordEffect` is one effect.
    Documented simplification: "each player exiles a card **of their
    choice**" is modeled as auto-exiling each player's oldest graveyard card
    — the interactive per-player pick would need the `SacrificeEffect.
    _sacrifice_each_in_order` deferred-choice chain threaded through the
    counter payoff, disproportionate for one card; the payoff (growth
    scaled by how many nonland cards were dredged up) is preserved.
    """

    def __init__(
        self, target: Any = None, source: Optional["GameObject"] = None,
        target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(
            kind=target_kind, creature_filter={"attacking": True},
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        nonland = 0
        for player in context.state.players:
            if not player.graveyard:
                continue
            card_obj = player.graveyard[0]  # oldest — see class docstring
            was_land = bool(getattr(card_obj, "is_land", False))
            context.exile(card_obj)
            if not was_land:
                nonland += 1
        if nonland > 0 and target is not None:
            context.add_counters(target, nonland, "+1/+1", source=self.source)
            context.recompute()


class PeekTopLandBattlefieldTappedEffect(GameEffect):
    """"Look at the top card of your library. If it's a land card, you may
    put it onto the battlefield tapped." (Explorer's Scope) — an "impulse
    peek", distinct from Sword of the Animist's own unconditional library
    *search* for a basic land.

    Bug report, 2026-09-04: the actual interactive "you may", plus the
    library-removal `_put_searched_card` needs before it moves anything
    onto the battlefield (omitting it used to leave the same `GameObject`
    sitting in both the library and the battlefield at once — a later draw
    would then hand that same still-in-library object into hand too), both
    live in `RulesEngine.peek_top_land_battlefield_tapped`/`resolve_peek_
    top_land_choice` now — this just opens that choice.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.peek_top_land_battlefield_tapped(player, source=self.source)


class PeekTopLandOrHandEffect(GameEffect):
    """Look at the top card; optionally put a land from it onto the
    battlefield tapped, otherwise put that card into hand (Risen Reef)."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.engine.peek_top_land_battlefield_tapped(
                player, source=self.source, otherwise_hand=True,
            )


class ReturnCreaturesByPowerParityEffect(GameEffect):
    """"Return each creature with power of the chosen quality to its owner's
    hand. (Zero is even.)" (Zimone's Hypothesis, PAR-60.)

    Untargeted mass bounce filtered by power parity — ``parity`` is fixed at
    "odd"/"even" (the caller's "choose odd or even" is a `modes` choice of
    two of these). RULE 107.3 — power can be negative; Python's ``%`` on a
    negative int already yields the mathematically-correct 0/1 here.
    """

    def __init__(self, parity: str = "even", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.parity = "odd" if str(parity).lower() == "odd" else "even"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        want_odd = self.parity == "odd"
        for obj in list(context.state.battlefield):
            if not obj.is_creature:
                continue
            if (int(obj.power or 0) % 2 == 1) == want_odd:
                context.return_to_hand(obj)



register(globals())
