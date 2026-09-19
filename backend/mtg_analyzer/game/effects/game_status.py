"""Game status, permissions, and resolution-flow effects."""
from __future__ import annotations

from .core import GameEffect
from ._runtime import install, register

install(globals())


# ---------------------------------------------------------------------------
# SPECIAL: Win/loss overrides (docs/07 PART 9)
# ---------------------------------------------------------------------------


class WinGameEffect(GameEffect):
    """"You win the game." (RULE 104.2) — Jace, Wielder of Mysteries' "-8:
    Draw seven cards. Then if your library has no cards in it, you win the
    game." tail (``if_empty_library=True`` gates it on the caster's current
    library being empty; unconditional win-the-game clauses would pass
    ``False``, though no card in the pool needs that shape yet). Calls
    `RulesEngine.player_wins` — the ability's own controller wins outright.
    """

    def __init__(self, if_empty_library: bool = False, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.if_empty_library = if_empty_library

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except Exception:
            return
        if self.if_empty_library and player.library:
            return
        context.engine.player_wins(player)


class BecomeMonarchEffect(GameEffect):
    """"[Player] become[s] the monarch." (RULE 725.1) — untargeted ("you
    become the monarch", Palace Jailer-shaped) by default; ``target_kind="player"``
    opts into a real RULE 115 target ("target player becomes the monarch",
    the Throne of the Damned-adjacent phrasing), mirroring `GainLifeEffect`.
    """

    def __init__(
        self,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self._resolve_target_or_controller(context, targets, explicit=self.player)
        if player is not None:
            context.become_monarch(player)


class TakeInitiativeEffect(GameEffect):
    """"[Player] take[s] the initiative." (RULE 726.1) — same untargeted/
    targeted split as `BecomeMonarchEffect`.

    All three of RULE 726.2's inherent abilities are live: the combat-damage
    steal, the upkeep venture, and "whenever a player takes the initiative,
    that player ventures into Undercity" — the last one fired off the
    `EventType.TOOK_INITIATIVE` `RulesEngine.take_initiative` announces, which
    is also why RULE 726.5's "taking the initiative while you already have
    it" still ventures.
    """

    def __init__(
        self,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self._resolve_target_or_controller(context, targets, explicit=self.player)
        if player is not None:
            context.take_initiative(player)


class IncreaseSpeedEffect(GameEffect):
    """PAR-28 / RULE 702.179d: the sourceless inherent ability "Whenever one
    or more opponents lose life during your turn, if your speed is less than
    4, your speed increases by 1. This ability triggers only once each
    turn." — resolves by raising ``player``'s speed (capped at 4). Built
    fresh per firing by `RulesEngine._collect_inherent_triggers`, never bound
    to a permanent."""

    def __init__(self, player: Any = None, amount: int = 1,
                 source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player
        self.amount = amount

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.player is not None:
            context.increase_speed(self.player, self.amount)


class BecomeSolvedEffect(GameEffect):
    """PAR-28 / RULE 719.3a/702.169: "this Case becomes solved." The
    resolution of the "To solve — [Condition]" end-step trigger, whose
    ``[condition]`` was checked as an intervening-if at trigger time
    (`effect_binder._trigger_condition`'s ``active_if`` predicate). Sets the
    persistent ``is_solved`` designation on the trigger's own source (RULE
    719.3b — kept until the Case leaves the battlefield), which every
    ``Solved —`` ability's ``source_solved`` gate then reads. The RULE 719.3a
    "and this Case is not solved" clause is the ``is_solved`` guard here;
    re-checking ``[condition]`` a second time at resolution (RULE 603.4) is
    left as a simplification — a Case's solve condition changing between its
    own end-step trigger and that trigger's resolution needs an empty stack
    plus another end-step effect, which no cached card sets up."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is not None and not getattr(src, "is_solved", False):
            src.is_solved = True
            state = getattr(context, "state", None)
            if state is not None:
                state.fire_event(
                    GameEvent(EventType.SOLVED, instance_id=src.instance_id,
                              controller_id=getattr(src, "controller_id", None))
                )


class GetCityBlessingEffect(GameEffect):
    """RULE 702.131a: Ascend's spell-ability form — "If you control ten or
    more permanents and you don't have the city's blessing, you get the
    city's blessing for the rest of the game." (the resolving instant/
    sorcery's own one-shot check).

    Ascend on a *permanent* (702.131b — "any time you control ten or more
    permanents…") is a continuous check instead, since the permanent must
    keep watching the board for as long as it's out there rather than
    checking once at resolution — see `RulesEngine._sba_check_ascend`, swept
    at SBA cadence like the day/night and Ring-bearer checks. This effect is
    only the spell form; both share `RulesEngine.get_city_blessing`'s
    idempotent flag-set (RULE 702.131c/d).
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .. import continuous  # avoid the continuous<->effects import cycle

        player = self.player or _controller_of(self.source, context)
        if player is None or player.has_city_blessing:
            return
        if continuous.count_selector(context.state, player.id, "permanents_you_control") >= 10:
            context.get_city_blessing(player)


class VentureIntoTheDungeonEffect(GameEffect):
    """"Venture into the dungeon." (RULE 701.49) — enter a dungeon, or move
    the venture marker one room down the one you're in.

    ``dungeon`` names RULE 701.49d's "venture into [quality]" variant
    ("venture into Undercity", RULE 726.2's own wording); ``None`` is the
    plain keyword action, which lets the player choose."""

    def __init__(
        self,
        dungeon: Optional[str] = None,
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.dungeon = dungeon
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or _controller_of(self.source, context)
        if player is not None:
            context.venture_into_the_dungeon(player, self.dungeon)


class CompleteDungeonEffect(GameEffect):
    """RULE 309.6/309.7: remove the completed dungeon card from the game.

    Appended by `RulesEngine._collect_dungeon_room_triggers` to a *bottommost*
    room's own ability, so it runs exactly when 309.6's condition first holds
    — "the venture marker is on the bottommost room and that dungeon isn't the
    source of a room ability that has triggered but not yet left the stack".
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.complete_dungeon(player)


class RadiationMillEffect(GameEffect):
    """RULE 728.1's rad-counter inherent ability: "that player mills a
    number of cards equal to the number of rad counters they have. For
    each nonland card milled this way, that player loses 1 life and
    removes one rad counter from themselves." Built fresh by
    `RulesEngine._collect_inherent_triggers` for whichever player's
    precombat main phase is beginning — no permanent hosts this ability,
    same shape as `BecomeMonarchEffect`/`TakeInitiativeEffect`. The count
    is read live at resolution time (not frozen at trigger time), matching
    the rule's present-tense "have".
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None:
            return
        count = player.counters.get("rad", 0)
        if count <= 0:
            return
        before = len(player.graveyard)
        context.mill(player, count)
        milled = player.graveyard[before:]
        nonland = sum(1 for obj in milled if not obj.is_land)
        if nonland:
            # RULE 728.1a: life lost "from radiation" refers to exactly this.
            context.lose_life(player, nonland, cause="radiation")
            context.add_player_counters(player, -nonland, "rad")


class CreateEmblemEffect(GameEffect):
    """"[Player] get[s] an emblem with '[ability]'." (RULE 114.2) — the
    quoted ability was already recursively parsed into a full nested
    `AbilitySpec` at parse time (`parser/oracle/catalogue/handlers.py`'s
    `_emblem_ability_spec`, the same recursive-`segment_line` idiom
    `static_handlers._quoted_ability_grant_effects` uses for an Aura/
    Equipment's quoted grant) and carried here as a plain JSON dict
    (``self.ability``) — still pure IR, nothing derived from card text has
    executed yet.

    Binding it into a live `TriggeredAbility`/`StaticAbility` happens once,
    at resolve time (`RulesEngine.create_emblem`), against a synthetic
    `Emblem` "source" rather than a real permanent (`models/emblem.py`) —
    an emblem has no permanent to attach to, so this can't happen at
    bind-on-load like every other ability.
    """

    def __init__(
        self,
        ability: Optional[dict] = None,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        abilities: Optional[list] = None,
    ) -> None:
        super().__init__(source)
        #: A single ability dict, or (You Compleat Me — "an emblem with 'A'
        #: and 'B'") ``abilities`` a list of them for one emblem.
        self.ability = ability
        self.abilities = list(abilities) if abilities else None
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        payload = self.abilities or self.ability
        if player is None or not payload:
            return
        context.create_emblem(player, payload)


class RequestChoosePlayerEffect(GameEffect):
    """"As this creature enters, choose a player." (Stuffy Doll) — opens
    `RulesEngine._request_choose_player`.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        context.engine._request_choose_player(player, self.source)


class SlithermuseEffect(GameEffect):
    """Slithermuse's non-targeting leaves trigger and live hand delta."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None and self.source is not None:
            context.engine._request_slithermuse_opponent(player, self.source)


class HauntEffect(GameEffect):
    """RULE 702.55a: exile this card haunting the chosen creature."""

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets or [None])[0]
        if self.source is None or target is None or target.zone != Zone.BATTLEFIELD:
            return
        if self.source.zone not in (Zone.GRAVEYARD, Zone.BATTLEFIELD):
            return
        context.exile(self.source)
        self.source.haunting_instance_id = target.instance_id


class HauntLinkedDeathEffect(GameEffect):
    """The body of ``when the creature this card haunts dies``."""

    def __init__(self, effects: Optional[list[dict[str, Any]]] = None,
                 source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.effects = [dict(effect) for effect in (effects or [])]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event or {}
        if (
            self.source is not None
            and self.source.zone == Zone.EXILE
            and getattr(self.source, "haunting_instance_id", None) == event.get("instance_id")
        ):
            context.engine._apply_effect_specs(self.effects, self.source)


class CastGraveyardInstantSorceryFreeExileEffect(GameEffect):
    """Impulsivity's targeted free-cast window plus exile rider."""

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="any_graveyard_instant_or_sorcery")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets or [None])[0]
        player = _controller_of(self.source, context)
        if player is None or target is None or target.zone != Zone.GRAVEYARD:
            return
        # The player, not the engine, chooses whether to cast and supplies
        # every RULE 115 target through the ordinary cast flow. Moving the
        # card to exile first makes the existing per-card free-cast window
        # available without inventing an off-stack target-selection shortcut.
        target.exile_after_free_cast = True
        context.exile(target)
        context.engine.grant_free_cast_window_from_exile(target, caster=player)


class DealDamageToChosenPlayerEffect(GameEffect):
    """"…it deals that much damage to the chosen player." (Stuffy Doll) —
    reads the firing `DAMAGE` event's own ``amount`` (the "that much" it
    was just dealt) against `GameObject.chosen_player_id`.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        player_id = getattr(self.source, "chosen_player_id", None)
        event = context.trigger_event
        if player_id is None or not event:
            return
        amount = int(event.get("amount") or 0)
        if amount <= 0:
            return
        try:
            player = context.state.player_by_id(player_id)
        except (KeyError, ValueError):
            return
        context.deal_damage(player, amount, self.source)


class RequestChooseCreatureTypeGrantEffect(GameEffect):
    """"When this creature enters, choose a creature type. <effect naming
    the chosen type>." (Selfless Safewright) — opens `RulesEngine.
    _request_choose_creature_type_grant`'s resolve-time type choice; see its
    docstring for why this needs its own primitive rather than RULE
    601.2b's as-it-enters `choose_creature_type_on_enter`.
    """

    def __init__(
        self,
        then_specs: Optional[list[dict]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.then_specs = list(then_specs or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        context.engine._request_choose_creature_type_grant(player, self.source, self.then_specs)


class GrantKeywordsToChosenTypeUntilEotEffect(GameEffect):
    """"Other permanents you control of that type gain hexproof and
    indestructible until end of turn." (Selfless Safewright) — "that type"
    is this effect's own source's `GameObject.chosen_type`, read live
    (set moments earlier in the same resolution by `RequestChooseCreature
    TypeGrantEffect`'s choice) rather than captured at bind time.
    """

    def __init__(
        self,
        keywords: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.keywords = list(keywords or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        wanted = getattr(self.source, "chosen_type", None)
        if not wanted or self.source is None or not self.keywords:
            return
        controller_id = self.source.controller_id
        for obj in context.state.battlefield:
            if obj is self.source or obj.controller_id != controller_id:
                continue
            if wanted.lower() not in (obj.card.type_line or "").lower():
                continue
            for kw in self.keywords:
                obj.temp_keywords.add(kw)
        context.recompute()


class GrantKeywordToTriggerSubjectEffect(GameEffect):
    """"…it gains haste until end of turn…" (Tyvar Kell's emblem, RULE
    603.1 "it" = the spell that triggered this ability) — grants a temporary
    keyword to whatever object `GameContext.trigger_event` named, rather
    than a targeted or self object. The cast spell's own `GameObject`
    persists by identity from the stack onto the battlefield (RULE 400.7's
    "new object" rule doesn't apply mid-cast), so a keyword stamped here
    while it's still a `SPELL_CAST` stack item is still present once it
    resolves.
    """

    def __init__(
        self,
        keyword: str = "haste",
        source: Optional["GameObject"] = None,
        event_key: str = "instance_id",
    ) -> None:
        super().__init__(source)
        self.keyword = keyword
        self.event_key = event_key

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if not event:
            return
        instance_id = event.get(self.event_key)
        if instance_id is None:
            return
        obj = context.state.find_object(instance_id)
        if obj is not None:
            obj.temp_keywords.add(self.keyword)


class WinConditionEffect(GameEffect):
    """Overrides a win/loss check, e.g. "you can't lose the game"."""

    def __init__(
        self,
        condition_type: str = "prevent_loss",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.condition_type = condition_type

    def prevents_loss(self) -> bool:
        return self.condition_type == "prevent_loss"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class TopLibraryPermissionEffect(GameEffect):
    """Standing permission to look at / play lands from / cast spells from
    the top of the controller's library (Oracle of Mul Daya/Glarb, Calamity's
    Augur/Future Sight-shaped) — RULE 701 has no native "play from the top"
    provision, so each real card grants it as its own static ability.

    Bound like any other ``static`` ability (`game/binding/core.py`'s
    ordinary dispatch), so it lands in ``obj.static_effects`` alongside
    `StaticAbility` — but it carries no layer/characteristic behaviour of its
    own: `continuous.recompute` only ever reads `StaticAbility` instances off
    that list (this isn't one, the same precedent as `CantBeCounteredEffect`
    above), so it's inert there. The only consumer is
    `game/top_library.py`, which scans every battlefield permanent a player
    controls for one of these (honouring ``requires_attached`` — an
    Equipment/Reconfigure-shaped grant that only counts while actually
    attached to something) and merges the results: multiple simultaneous
    grants OR together (a spell is castable if *any* active grant's
    ``min_mana_value`` gate — or lack of one — allows it), never AND.

    ``noncreature_only`` narrows ``cast_spells`` to noncreature spells only
    (Elsha of the Infinite's own restriction — a closed vocabulary of one,
    not a general subtype filter, since no other real card needs a different
    restriction here today). ``grants_flash``/``life_payment`` are each
    card's own conditional tail on top of the base permission: Elsha's "you
    may cast it as though it had flash" (consulted by `game/top_library.py`'s
    `may_cast_flash_from_top_of_library`, `GameEngine.can_cast`'s flash
    union) and Bolas's Citadel's "pay life equal to its mana value rather
    than pay its mana cost" (`top_library.top_library_life_payment_required`,
    `GameEngine._top_library_life_payment`) — both apply automatically
    whenever a spell is actually cast via *this* grant, never as a separate
    opt-in choice, matching the printed wording ("If you cast a spell this
    way, ...").
    """

    def __init__(
        self,
        look: bool = False,
        play_lands: bool = False,
        cast_spells: bool = False,
        min_mana_value: Optional[int] = None,
        requires_attached: bool = False,
        noncreature_only: bool = False,
        grants_flash: bool = False,
        life_payment: bool = False,
        chosen_type_creature_only: bool = False,
        creature_only: bool = False,
        subtypes: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.look = look
        self.play_lands = play_lands
        self.cast_spells = cast_spells
        self.min_mana_value = min_mana_value
        self.requires_attached = requires_attached
        self.noncreature_only = noncreature_only
        self.grants_flash = grants_flash
        self.life_payment = life_payment
        #: "You may cast **creature spells of the chosen type** from the top
        #: of your library." (Realmwalker) — narrows `cast_spells` to
        #: creature spells matching this grant's own source's `GameObject.
        #: chosen_type` (RULE 601.2b), read live off ``self.source`` rather
        #: than captured at bind time so a Replay/Puzzle-mode change to the
        #: choice is honoured immediately, the same live-read idiom
        #: `continuous.recompute`'s `subtype_from_source` selectors use.
        self.chosen_type_creature_only = chosen_type_creature_only
        #: "You may cast **creature** spells from the top of your library."
        #: (Eladamri, Korvecdal, MEC-40) — a plain, printed creature-only
        #: restriction (unlike ``chosen_type_creature_only``'s RULE 601.2b
        #: ETB-choice narrowing), the direct mirror of ``noncreature_only``.
        self.creature_only = creature_only
        #: "You may cast **Angel spells and Human spells** from the top of
        #: your library." (Sigarda, Font of Blessings, MEC-40) — a closed
        #: list of printed subtype words; the card qualifies if its type
        #: line contains *any* of them (union, not intersection — matching
        #: how "Angel spells and Human spells" reads as "either").
        self.subtypes = [str(s).lower() for s in subtypes] if subtypes else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # continuous marker — consulted by top_library.py, not applied


class GraveyardCastPermissionEffect(GameEffect):
    """Standing permission to cast [permanent] spells from the controller's
    own graveyard (Lurrus of the Dream-Den-shaped) — the graveyard sibling of
    `TopLibraryPermissionEffect` above, consulted the same "scan on demand"
    way by `game/graveyard_cast.py` rather than a closed keyword vocabulary
    like Flashback/Escape (`GameEngine._graveyard_cast_keyword`): those are
    an alternative *cost* printed on the card itself, this is a *permission*
    granted by some other permanent, paid at the card's own normal mana cost.

    ``permanent_only`` is Lurrus's own "a permanent spell" restriction
    (creature/artifact/enchantment/land/planeswalker); ``max_mana_value`` is
    its "with mana value 2 or less" gate (``None`` = unrestricted).
    ``once_per_turn`` (RULE 500.4-adjacent "once during each of your turns")
    is tracked per *granting object* (`GameObject.graveyard_casts_this_turn`,
    reset every untap step alongside `activated_loyalty_this_turn` — the same
    per-object, not per-player, precedent: two copies of the granting
    permanent each grant their own use).

    Bound like `TopLibraryPermissionEffect` (an ordinary ``static`` ability,
    inert to `continuous.recompute` — the only consumer is
    `game/graveyard_cast.py`).

    ``exile_if_would_be_put_into_graveyard`` is Lurrus's own trailing "if a
    spell cast this way would be put into a graveyard this turn, exile it
    instead" clause (RULE 616, ``False`` by default — a different card
    reusing this same base permission need not carry it). It isn't checked
    here: `GameEngine.cast_spell`'s dispatch stamps `GameObject.
    cast_via_graveyard_cast_permission_until_turn` with the casting turn
    only when the grant it used has this flag set, and `RulesEngine.
    _move_to_graveyard` (the one choke point every graveyard-bound move —
    destroy, sacrifice, or SBA "dies" — funnels through) redirects to exile
    while that still matches the current turn number. A per-cast turn
    number rather than a per-object bool so a later *normal* recast this
    same turn (no permission involved) correctly clears it, mirroring
    `GameObject.cast_via_flashback`'s own unconditional-reassignment
    pattern.
    """

    def __init__(
        self,
        max_mana_value: Optional[int] = None,
        permanent_only: bool = True,
        once_per_turn: bool = True,
        exile_if_would_be_put_into_graveyard: bool = False,
        source: Optional["GameObject"] = None,
        instant_sorcery_only: bool = False,
        expires_turn: Optional[int] = None,
        per_permanent_type: bool = False,
    ) -> None:
        super().__init__(source)
        self.max_mana_value = max_mana_value
        self.permanent_only = permanent_only
        self.once_per_turn = once_per_turn
        self.exile_if_would_be_put_into_graveyard = exile_if_would_be_put_into_graveyard
        #: "Each instant and sorcery card in your graveyard gains flashback
        #: until end of turn." (Backdraft Hellkite) — the mirror image of
        #: ``permanent_only``: only instant/sorcery cards, never a
        #: permanent. Mutually meaningful with ``permanent_only`` off.
        self.instant_sorcery_only = instant_sorcery_only
        #: A one-shot, turn-scoped grant (as opposed to the ordinary
        #: standing-while-attached shape every other consumer uses) —
        #: the internal turn this expires after, appended directly
        #: onto a still-on-the-battlefield permanent's own
        #: `GameObject.static_effects` (`GrantGraveyardCastPermissionThis
        #: TurnEffect`) rather than tied to a printed static ability's own
        #: continuous binding. ``None`` (every existing consumer) means
        #: "as long as the granting permanent is on the battlefield", same
        #: as before this field existed.
        self.expires_turn = expires_turn
        #: Muldrotha: one permanent spell of *each* permanent type, rather
        #: than this grant's ordinary single use per turn.
        self.per_permanent_type = per_permanent_type

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # continuous marker — consulted by graveyard_cast.py, not applied


class SelfGraveyardOrExileCastPermissionEffect(GameEffect):
    """"You may cast this card from your graveyard or from exile." (Squee,
    the Immortal-shaped) — the card's own standing self-permission, unlike
    `GraveyardCastPermissionEffect` (granted by some *other* permanent,
    scanned off the battlefield by `game/graveyard_cast.py`). Read
    directly off this object's own ``static_effects`` by `GameEngine.
    can_cast`'s ``in_castable_zone`` check (`_self_graveyard_or_exile_
    cast_permission`) regardless of which of the two zones it's currently
    sitting in — no board scan needed since the source *is* the card being
    cast, and bind-on-load already binds every object at every zone (not
    just the battlefield), so the marker survives the card's own trip
    through hand → battlefield → graveyard/exile.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class GrantGraveyardCastPermissionThisTurnEffect(GameEffect):
    """"Each instant and sorcery card in your graveyard gains flashback
    until end of turn. The flashback cost is equal to its mana cost."
    (Backdraft Hellkite) — "flashback at the printed mana cost" is exactly
    `GraveyardCastPermissionEffect`'s own shape, just turn-scoped and
    instant/sorcery-only rather than a standing permanent-only grant. Appends
    a fresh permission straight onto this effect's own source's
    `GameObject.static_effects` — the source (the attacking creature) is
    already on the battlefield and stays there, so `graveyard_cast.py`'s
    existing per-permanent scan finds it with no new consumer-side code,
    only the expiry check `expires_turn` adds.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        self.source.static_effects.append(
            GraveyardCastPermissionEffect(
                permanent_only=False,
                instant_sorcery_only=True,
                once_per_turn=False,
                expires_turn=context.state.internal_turn.number,
                source=self.source,
            )
        )


class GrantFlashbackToTargetEffect(GameEffect):
    """"Target instant or sorcery card in your graveyard gains flashback
    until end of turn. The flashback cost is equal to its mana cost."
    (MEC-24 — Recoup/Snapcaster Mage/Slickshot Lockpicker/Sphinx of
    Forgotten Lore/Katilda and Lier/The Fugitive Doctor-shaped) — the
    targeted, single-card sibling of `GrantGraveyardCastPermissionThisTurn
    Effect`'s untargeted "each instant and sorcery card in your graveyard"
    grant (Backdraft Hellkite). That one appends a marker onto the
    *granting permanent's own* `GameObject.static_effects`, discoverable by
    `game/graveyard_cast.py`'s battlefield scan; this one instead marks the
    *targeted graveyard card itself* (`GameState.temp_flashback_grants`),
    since the grant must survive independently of whatever granted it (the
    creature that triggered this may attack into removal, or simply leave
    the battlefield, before the graveyard card is ever cast) and must apply
    to exactly the one chosen card, not every instant/sorcery in the
    graveyard.

    ``cost=None`` (every real card but The Fugitive Doctor) means "equal to
    its mana cost" — read off the target's own `Card.mana_cost_string` at
    the moment this effect resolves, matching *that* card's cost rather
    than a fixed one; a literal ``cost`` string (The Fugitive Doctor's flat
    ``"{2}{R}{G}"``) overrides it. Consulted by `game/engine/casting_mixin.
    py`'s `_graveyard_cast_keyword`/`_flashback_cost`, the same choke point
    a printed Flashback keyword goes through — the exile-after-cast (RULE
    702.34a) and cost-computation machinery need no changes at all.
    """

    def __init__(
        self,
        cost: Optional[str] = None,
        target_kind: str = "graveyard_instant_or_sorcery",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost = cost
        self.target_spec = TargetSpec(kind=target_kind, count=1)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None:
            return
        cost = self.cost or getattr(target.card, "mana_cost_string", None) or "{0}"
        context.state.temp_flashback_grants[target.instance_id] = str(cost)


class GrantSelfActivatedAbilityEffect(GameEffect):
    """"This [permanent] gains '`<cost>`: `<effect>`.'" (Urza's Saga's own
    Saga-chapter shape, RULE 714.2c — a chapter's *lasting* self-grant, not
    a turn-scoped one). Appends a real `grant_activated_ability`-shaped
    `StaticAbility` (``affects="self"``) straight onto this effect's own
    source's `GameObject.static_effects`, the same "append a static at
    resolve time" idiom `GrantGraveyardCastPermissionThisTurnEffect` uses —
    permanent (no expiry) rather than turn-scoped, since a Saga chapter's
    grant lasts for as long as the Saga itself does.
    """

    def __init__(
        self,
        cost: Optional[dict[str, Any]] = None,
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.granted_cost = dict(cost or {})
        self.granted_effects = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
        from ...parser.oracle.spec import EffectSpec

        granted = build_effects(
            [EffectSpec("grant_activated_ability", {
                "affects": "self", "cost": self.granted_cost, "grant_effects": self.granted_effects,
            })],
            self.source,
        )
        self.source.static_effects.extend(granted)


class GainActivatedAbilitiesOfTargetEffect(GameEffect):
    """"~ gains all activated abilities of target creature until end of
    turn." (MEC-23, Quicksilver Elemental) — the resolve-time, single-target
    sibling of `grant_borrowed_activated_ability`'s standing layer-6 grant
    (`continuous._apply_borrowed_activated_abilities`, MEC-21, Agatha's Soul
    Cauldron): that one re-derives its granted set live off a permanent's
    own `GameObject.exiled_with_ids` every `continuous.recompute` pass, so a
    later change to an exiled card's own abilities is picked straight back
    up. This effect instead **snapshots** ``target``'s `activated_abilities`
    once, at resolution, onto a turn-scoped field
    (`GameObject.temp_granted_activated_abilities`, cleared at cleanup
    alongside `temp_keywords` — RULE 514.2) — a later change to the
    target's own ability set doesn't retroactively change what was copied,
    matching Quicksilver Elemental's own ruling that this is a one-time
    copy, not a continuous link to the target.

    Reuses `continuous._retarget_effect_source` (RULE 113.7c: "Any ability
    that a permanent gains by another spell/ability applies to that
    permanent, not to the object that granted it") rather than a second
    implementation — the same shallow-copy-per-effect approach the layer-6
    grant already uses.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature", count=1)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or not targets:
            return
        target = targets[0]
        if target is None:
            return
        from .. import continuous  # local: avoid the continuous<->effects import cycle

        for base in list(getattr(target, "activated_abilities", None) or []):
            self.source.temp_granted_activated_abilities.append(
                ActivatedAbility(
                    effects=[continuous._retarget_effect_source(e, self.source) for e in base.effects],
                    cost=base.cost,
                    source=self.source,
                    description=base.description,
                    once_per_turn=base.once_per_turn,
                )
            )


# ---------------------------------------------------------------------------
# SPECIAL: Conditional effect wrapper (parser/oracle/spec.py's EffectSpec.condition)
# ---------------------------------------------------------------------------


class ConditionalEffect(GameEffect):
    """Gates ``inner`` so it only applies when ``condition`` holds (RULE
    702.33b's "if this spell was kicked, <effect>." — a *second, additional*
    effect on the same spell/ability, not a replacement of an earlier one;
    see `parser.oracle.spec.EffectSpec.condition`'s docstring for why "if
    kicked, ... instead" — overriding an *existing* effect's own amount —
    is a different, unmodeled shape). ``{"target_is_controller": True}``
    (The Ghoul, Gunslinger: "target player gets two rad counters. If that
    player is you, create a Treasure token.") is the RULE 603.4-style
    sibling gated on the ability's own *resolved target* instead of an
    announced-cost flag — checked against ``targets`` at apply time, which
    only works because this effect carries no `target_spec` of its own: a
    `target_groups=None` ability (the overwhelming common case) passes its
    *whole* targets list to every sub-effect (`_apply_effects_partitioned`),
    so this effect transparently sees the target chosen for whichever
    *other* effect in the same ability actually declared it.

    Built only by `game/binding/core.py`'s `build_effects`, never directly
    by `EffectRegistry` (``condition`` lives on the `EffectSpec`, not inside
    ``params``, so there's no ``"conditional"`` registry entry to construct
    one from card-text-derived data — keeps the whitelist's shape/behaviour
    split from docs/09 intact).
    """

    def __init__(
        self,
        condition: dict[str, Any],
        inner: GameEffect,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.condition = condition
        self.inner = inner
        self.target_spec = inner.target_spec

    def _condition_holds(
        self, context: GameContext, targets: Optional[list[Any]] = None
    ) -> bool:
        """Whether ``condition`` gates this effect on (RULE 603.4/702.33b).

        One delegation, where this was 554 lines of flat ``if`` chains — one
        per whitelisted condition key. `game/effect_conditions.py` holds the
        structured vocabulary those keys translate into and the single
        evaluator behind it; see that module for why 44 keys were only ever a
        handful of predicates written out once per referent, threshold and
        attribute. Both spellings still work, so every shipped `AbilitySpec`
        and catalogue entry is untouched.
        """
        return effect_conditions.condition_holds(
            self.condition, context, self.source, targets
        )


    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.inner.source is None:
            self.inner.source = self.source
        if self._condition_holds(context, targets):
            self.inner.apply(context, targets)


# ---------------------------------------------------------------------------
# Concrete one-shot effects (RULE 608 resolution bodies)
# ---------------------------------------------------------------------------


#: `DealDamageEffect`'s closed selector vocabulary for a mass, untargeted hit
#: (RULE 601.2c — not RULE 115 targeting at all, e.g. Pyroclasm's "~ deals 2
#: damage to each creature"). Kept small and explicit rather than reusing
#: `continuous.group_selector_objects`'s full vocabulary, since only these
#: phrasings appear on real damage-dealing cards. ``each_creature_and_player``
#: is the compound "~ deals N damage to each creature and each player"
#: shape (Volcanic Fallout) — a single amount hitting both groups at once,
#: not two separate effects (so a doubling replacement like Furnace of Rath
#: sees — and can double — each hit individually, exactly as printed).
_DAMAGE_SELECTORS: frozenset[str] = frozenset(
    {"each_creature", "each_player", "each_opponent", "each_creature_and_player",
     # "~ deals N damage to each creature **your opponents control**."
     # (Village Pillagers) — opponents' creatures only, no players (unlike
     # ``each_opponent_and_their_creatures``).
     "each_creature_opponents_control",
     # "~ deals X damage to each creature **and planeswalker your opponents
     # control**." (Volcanic Torrent, PAR-60) — the planeswalker-inclusive
     # sibling of ``each_creature_opponents_control``.
     "each_creature_and_planeswalker_opponents_control",
     # "~ deals 1 damage to each creature and each planeswalker." (MEC-11's
     # Stalwart Speartail) — the compound-selector sibling of
     # ``each_creature_and_player``, a creature-or-planeswalker union rather
     # than creature-or-player.
     "each_creature_and_planeswalker",
     # "it deals 1 damage to **you**" (Mana Vault's draw-step ping) — the
     # source's own controller, untargeted (RULE 115: "you" is never a
     # target). The single-player counterpart of "each_player" above.
     "controller",
     # "~ deals 1 damage to itself." (Stuffy Doll) — the source's own
     # permanent, unlike "controller" (that permanent's *player*).
     "self",
     "defending_player",
     # "~ deals N damage to that player." (Spellshock/Eidolon of the Great
     # Revel-shaped cast-trigger punishers) — the player named by the
     # currently-resolving trigger's own event (`_event_player`, the same
     # helper `PayCostThenEffect`'s ``payer="event_player"`` already reads),
     # not a RULE 115 target: the ability names its own firing condition's
     # actor, the caster never chooses who gets hit.
     "event_player",
     # "Whenever a land enters, ~ deals N damage to that land's
     # controller." (Zo-Zu the Punisher) — unlike ``event_player`` (reads
     # the firing event's own ``player_id``, the *acting* player of a
     # cast/draw/tap-for-mana-shaped event), this reads its
     # ``controller_id`` — the *entering permanent's* controller
     # (`AddManaEffect.recipient`'s existing ``"event_controller"`` idiom,
     # `_event_player`'s own default key).
     "event_controller",
     # "Each creature deals 1 damage to its controller." (Rakdos Charm's
     # own third mode) — unlike every other row here, the *recipient*
     # varies per creature (that creature's own controller), so this is N
     # independent single-recipient hits (all sharing the same flat
     # ``amount``) rather than one amount fanned out to a fixed group.
     "each_creature_controller",
     # "…it deals that much damage to each **other** opponent." (Kediss,
     # Emberclaw Familiar) — `each_opponent` minus whichever opponent the
     # *firing* DAMAGE event already hit (`GameContext.trigger_event`'s own
     # ``target_id``), so the original recipient isn't hit a second time.
     "each_other_opponent",
     # "~ deals N damage to each opponent and each creature [and
     # planeswalker] they control." (Tectonic Hazard/End the Festivities/
     # Spiteful Banditry/Delayed Blast Fireball-shaped board wipes) — unlike
     # ``each_creature_and_player`` (every creature globally + every
     # player), this is scoped to *opponents only* and *their own*
     # permanents, so an ally's board is untouched.
     "each_opponent_and_their_creatures",
     "each_opponent_and_their_creatures_and_planeswalkers",
     # "At the beginning of each player's upkeep, ~ deals 1 damage to
     # them." (Roiling Vortex-shaped) — unlike ``event_player`` (a value
     # snapshotted on the firing event), `STEP_BEGIN` carries no player at
     # all, since it fires once per step globally; "them" is whoever's
     # step it is, read live off `GameState.active_player` at resolution
     # time (unchanged since the trigger fired moments earlier).
     "active_player",
     # "Whenever ~ becomes blocked, … ~ deals N damage to each creature
     # blocking it." (Fire Juggler-shaped) — every battlefield creature
     # whose `GameObject.blocking` names this effect's own source (the
     # attacker). Read live at resolution (combat is still in progress).
     "each_creature_blocking_source"}
)


class CoinFlipEffect(GameEffect):
    """RULE 705.1 "flip a coin. If you lose the flip, `<effect>`. If you win
    the flip, `<effect>`." (Ral, Monsoon Mage-shaped) — branches into
    ``win_effects``/``lose_effects`` (serialized ``{"type","params"}``
    dicts, the same shape `CreateDelayedTriggerEffect.effects` takes), off
    `RulesEngine.coin_flip`'s existing reproducible RNG. **Documented
    simplification**: a "you may" on the winning branch is modeled as
    unconditional (always taken) — the same accepted simplification every
    other undecided "may" in this codebase uses (Arcane Denial's "may draw
    up to two") when declining a beneficial option is a real but
    vanishingly rare choice.
    """

    def __init__(
        self,
        win_effects: Optional[list[dict[str, Any]]] = None,
        lose_effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.win_specs = list(win_effects or [])
        self.lose_specs = list(lose_effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
        from ...parser.oracle.spec import EffectSpec

        specs = self.win_specs if context.engine.coin_flip() else self.lose_specs
        if not specs:
            return
        inner = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in specs],
            self.source,
        )
        for effect in inner:
            effect.apply(context, targets)


class ClashEffect(GameEffect):
    """RULE 701.30: "Clash with an opponent." — this effect's controller
    clashes (`RulesEngine.clash`), stashing the RULE 701.30d outcome on
    `GameContext.clash_won` for a following `ConditionalEffect(condition=
    {"clash_won": True/False})` — the "if you win, `<effect>`. otherwise,
    `<effect>`." branch the parser emits as sibling specs in printed order.

    ``with_opponent`` is RULE 701.30b's "with an opponent" / "with defending
    player" phrasing (an opponent reveals their top card too); a bare "clash"
    with no such phrasing has no cache card and is treated identically. The
    optional 701.30a bottoming and the win/lose branch effects both live
    elsewhere (`RulesEngine.clash`'s docstring / the sibling `ConditionalEffect`s).
    """

    def __init__(
        self, with_opponent: bool = True, source: Optional["GameObject"] = None
    ) -> None:
        super().__init__(source)
        self.with_opponent = bool(with_opponent)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        context.clash_won = context.engine.clash(
            player, with_opponent=self.with_opponent, source=self.source,
        )
        # RULE 701.30b's "that player" referent — the opponent this clash
        # was with (`RulesEngine.clash` recorded its id).
        opp_id = getattr(context.engine, "_last_clash_opponent_id", None)
        context.clashed_opponent = (
            context.state.player_by_id(opp_id) if opp_id is not None else None
        )


class RollDieEffect(GameEffect):
    """RULE 706: "Roll a d20." / "Roll a six-sided die." / "Roll two d6." —
    this effect's controller rolls (`RulesEngine.roll_die`), stashing the
    kept results on `GameContext.die_results`, their sum on ``die_result``
    and RULE 706.5's ``rolled_doubles`` for a following clause ("if any of
    those results was 10 or higher, …", "where X is the result").

    ``outcomes`` is RULE 706.3a's results table: a list of
    ``{"min": int, "max": int | None, "effects": [{"type","params"}, ...]}``
    rows (``max`` ``None`` is the ``N+`` open-ended endpoint). After the
    roll, every row whose range contains the *total* fires, its inner
    effects built through the ordinary `build_effects` whitelist and applied
    in printed order — the same serialized-spec branch idiom `CoinFlipEffect`
    uses for its win/lose bodies. No matching row is legal (RULE 706.3a: "if
    any") and simply does nothing.

    ``ignore_lowest``/``ignore_highest`` are RULE 706.3's ignore rider,
    passed straight through; an advantage/disadvantage replacement (Pixie
    Guide, Barbarian Class) usually sets them on the `ROLL_DICE` event
    instead, so a bare "roll a d20." spec carries 0/0 and still gets the
    rider when one is on the battlefield.
    """

    def __init__(
        self,
        sides: int = 20,
        count: int = 1,
        ignore_lowest: int = 0,
        ignore_highest: int = 0,
        outcomes: Optional[list[dict[str, Any]]] = None,
        then_trigger: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.sides = int(sides)
        self.count = int(count)
        self.ignore_lowest = int(ignore_lowest)
        self.ignore_highest = int(ignore_highest)
        self.outcomes = list(outcomes or [])
        # RULE 603.11: a mandatory roll can still have a separate "When you
        # do" ability. Keep its serialized body until the roll succeeds, so
        # targets are chosen for the reflexive trigger, not before it.
        self.then_trigger = list(then_trigger or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
        from ...parser.oracle.spec import EffectSpec

        player = _controller_of(self.source, context)
        results = context.engine.roll_die(
            player,
            sides=self.sides,
            count=self.count,
            ignore_lowest=self.ignore_lowest,
            ignore_highest=self.ignore_highest,
        )
        context.die_results = list(results)
        context.die_result = sum(results)
        context.rolled_doubles = len(results) > 1 and len(set(results)) == 1
        if self.then_trigger:
            # A reflexive trigger resolves in a fresh context, so carry the
            # just-rolled result on its triggering event as well.
            context.enqueue_reflexive_trigger(
                self.then_trigger, self.source,
                GameEvent(EventType.DICE_ROLLED, die_result=context.die_result),
            )
        if not self.outcomes:
            return
        total = context.die_result
        for row in self.outcomes:
            lo = row.get("min")
            hi = row.get("max")
            if lo is not None and total < int(lo):
                continue
            if hi is not None and total > int(hi):
                continue
            specs = row.get("effects") or []
            inner = build_effects(
                [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in specs],
                self.source,
            )
            for effect in inner:
                effect.apply(context, targets)


class RandomNumberEffect(GameEffect):
    """RULE 706's other randomization — "a number from ``min_value`` to
    ``max_value`` chosen at random" (Hapato's Might, PAR-80). Deliberately
    **not** `RollDieEffect`: RULE 706.11 only treats literal "roll a die"
    text as a die roll subject to dice-replacement effects (Yenna-shaped
    doublers, Barbarian Class' advantage), so this fires no `ROLL_DICE`
    event at all and stashes its result on the separate `GameContext.
    random_result` rather than `die_result` — a following clause reads it
    via the ``"random_result"`` `effect_amounts` kind.

    Uses `RulesEngine.random_int` — the same game-state-seeded RNG
    `roll_die`/`coin_flip` use — so the result is reproducible across a
    `GameState.clone()` undo, unlike a fresh `random.Random()` each call.
    """

    def __init__(
        self, min_value: int = 0, max_value: int = 6, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.min_value = int(min_value)
        self.max_value = int(max_value)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        span = self.max_value - self.min_value + 1
        context.random_result = self.min_value + context.engine.random_int(max(span, 0))


#: Termination cap for `RepeatProcessEffect` (Hoarder's Greed): a chain of
#: clash wins is unbounded in principle (the same top-of-library card can
#: keep winning), and each iteration also *loses life* — so the loop would
#: usually self-terminate on death, but a defensive ceiling keeps a
#: pathological board (empty opponent library, or life-gain in the mix)
#: from wedging the resolution. 20 iterations is well past any realistic
#: run and past `MAX_EFFECT_MAGNITUDE`'s own spirit for a repeat count.
_MAX_CLASH_REPEAT_ITERATIONS = 20


class RepeatProcessEffect(GameEffect):
    """"`<process>`, then clash with an opponent. If you win, **repeat this
    process**." (Hoarder's Greed — the process is "you lose 2 life and draw
    two cards, then clash with an opponent").

    ``effects`` is the serialized process (`EffectSpec`-shaped dicts, built
    through the ordinary `effect_binder.build_effects` whitelist). It runs
    once, then — while ``repeat_while`` holds (only ``"clash_won"`` today,
    read off `GameContext.clash_won`, which the process's own trailing
    `ClashEffect` sets each pass) — runs again, up to
    `_MAX_CLASH_REPEAT_ITERATIONS`. The inner effects apply directly on
    ``context`` (not a nested `_apply_effects_partitioned`) so the clash
    outcome each pass is visible to the loop test.
    """

    def __init__(
        self,
        effects: Optional[list[dict[str, Any]]] = None,
        repeat_while: str = "clash_won",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.inner_specs = list(effects or [])
        self.repeat_while = repeat_while

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
        from ...parser.oracle.spec import EffectSpec

        if not self.inner_specs:
            return
        for _ in range(_MAX_CLASH_REPEAT_ITERATIONS):
            built = build_effects(
                [EffectSpec(type=d["type"], params=dict(d.get("params") or {}))
                 for d in self.inner_specs],
                self.source,
            )
            for effect in built:
                effect.apply(context, None)
            if self.repeat_while == "clash_won" and not getattr(context, "clash_won", None):
                return


class PlaneswalkEffect(GameEffect):
    """"Planeswalk." (RULE 901.10) — this effect's controller planeswalks
    (`RulesEngine.planeswalk`): the face-up plane goes to the bottom of the
    planar deck and the next turns face up. The plain outcome body of Path
    of the Animist / Path of the Enigma's "planeswalk or chaos" vote, and a
    standalone body (Plain Walker). A no-op outside a Planechase game
    (`planeswalk` returns ``None``)."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.engine.planeswalk(player)


class ChaosEnsuesEffect(GameEffect):
    """"Chaos ensues." (RULE 901.13) — fire `CHAOS_ENSUED` for the face-up
    plane so its chaos-triggered ability goes on the stack
    (`RulesEngine.trigger_chaos`). The tie / minority outcome body of the
    same "planeswalk or chaos" vote. A no-op with no active plane."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.engine.trigger_chaos(player)



register(globals())
