"""Destruction, life, prevention, sacrifice, and player-resource effects."""
from __future__ import annotations

from .core import GameEffect
from ._runtime import install, register

install(globals())

class DestroyEffect(GameEffect):
    """Destroy a target permanent — or, with ``count`` > 1, every one of a
    fixed/"up to N" set of chosen target permanents (RULE 115.1a
    generalized to N>=2 — "destroy two target creatures"/"destroy up to two
    target artifacts and/or enchantments") — or, with ``selector`` set, a
    mass "destroy all X [with condition]" board wipe (RULE 601.2c, untargeted,
    same shape as `DealDamageEffect.selector`). ``can_be_regenerated=False``
    is Wrath of God's "They can't be regenerated." tail. ``max_mana_value``
    is Abrupt Decay-shaped "target nonland permanent with mana value 3 or
    less" — a target-offer-time cap (`targeting.TargetSpec.max_mana_value`),
    not a resolve-time check. ``creature_filter`` is the power/toughness/
    keyword quality filter (`targeting.TargetSpec.creature_filter`,
    "destroy target creature with power 4 or greater"/"…with flying"-shaped)
    — a different, orthogonal narrowing from ``filter`` above (which only
    ever applies to the untargeted ``selector`` mass-wipe path).

    ``distinct_controllers`` (Run Away Together/Protector of the Wastes-
    shaped "N target creatures/permanents controlled by **different
    players**") is `targeting.TargetSpec.distinct_controllers` — see its
    docstring; only meaningful with ``count >= 2``.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        optional: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        can_be_regenerated: bool = True,
        color: Optional[str] = None,
        colors: Optional[list[str]] = None,
        max_mana_value: Optional[int] = None,
        creature_filter: Optional[dict[str, Any]] = None,
        distinct_controllers: bool = False,
        exclude_created: bool = False,
        target_from_trigger_event: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "destroy target `<c1>` or `<c2>` creature" (Deathmark) —
        #: `TargetSpec.colors`' OR narrowing, the multi-letter sibling of
        #: ``color``'s single-letter form; checked at offer time by
        #: `targeting._color_ok`.
        self.colors = tuple(colors) if colors else None
        self.selector = selector if selector in _MASS_DESTROY_SELECTORS else None
        self.filter = filter
        self.can_be_regenerated = can_be_regenerated
        #: "Whenever a Human deals damage to you, destroy it." (Mikaeus,
        #: the Unhallowed) — "it" is the *source* of the very DAMAGE event
        #: that fired this trigger (a group-subject trigger, so there's no
        #: single chosen creature to fall back on the way a self-subject
        #: "when ~ deals damage" trigger's implicit "it" would be) — the
        #: event field name to read off `GameContext.trigger_event` (its
        #: own ``"source_id"``), resolved fresh at apply-time since the
        #: dealer varies firing to firing. Same "read this firing's own
        #: payload" idiom `DealDamageEffect.amount_from_trigger_event` uses
        #: for a magnitude instead of an object reference.
        self.target_from_trigger_event = target_from_trigger_event
        #: "Create X tokens. If X is 5 or more, destroy all **other**
        #: creatures." (Martial Coup) — RULE 608.2's "the tokens" referent
        #: excluded from a mass wipe in the *same* resolution
        #: (`GameContext.created_objects`), the mirror image of
        #: `AttachEffect`'s ``target_kind="created"`` reading the same list.
        self.exclude_created = exclude_created
        if self.selector is None and target_from_trigger_event is None:
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max, color=color,
                colors=self.colors,
                max_mana_value=max_mana_value, creature_filter=creature_filter,
                distinct_controllers=distinct_controllers,
            )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_from_trigger_event:
            event = context.trigger_event or {}
            source_id = event.get(self.target_from_trigger_event)
            target = context.state.find_object(source_id) if source_id is not None else None
            if target is not None:
                context.destroy(target, can_be_regenerated=self.can_be_regenerated)
            return
        if self.selector is not None:
            excluded = set(context.created_objects) if self.exclude_created else ()
            for obj in _mass_selector_objects(context, self.selector, self.filter, source=self.source):
                if obj in excluded:
                    continue
                context.destroy(obj, can_be_regenerated=self.can_be_regenerated)
            return
        chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
        for target in chosen:
            context.destroy(target, can_be_regenerated=self.can_be_regenerated)


class RegenerateEffect(GameEffect):
    """Give a target permanent a regeneration shield (RULE 701.16).

    ``target_kind=None`` (unlike the default ``"creature"``) makes it act on
    the effect's own source with no player choice involved — "Regenerate
    ~."/"Regenerate this creature.", mirroring `TapEffect`'s self mode.
    ``target_kind="attached_permanent"`` regenerates whatever this Aura/
    Equipment is attached to ("{G}: Regenerate enchanted creature." —
    Nurturing Licid), read live off ``source.attached_to``.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        creature_filter: Optional[dict] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self._attached_mode = target_kind == "attached_permanent"
        self.target_spec = (
            TargetSpec(kind=target_kind, creature_filter=creature_filter)
            if target_kind is not None and not self._attached_mode else None
        )

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._attached_mode:
            host_id = getattr(self.source, "attached_to", None)
            host = context.state.find_object(host_id) if host_id is not None else None
            if host is not None:
                context.regenerate(host)
            return
        target = (targets[0] if targets else None) or self.target
        if target is None and self.target_spec is None:
            target = self.source
        if target is not None:
            context.regenerate(target)


class GainLifeEffect(GameEffect):
    """The effect's controller (or an explicitly given ``player``) gains
    ``amount`` life — untargeted by default.

    ``target_kind="player"`` (Abuna's Chant-shaped "target player gains N
    life") opts into a real RULE 115 target, mirroring `LoseLifeEffect`'s
    own ``target_kind``. Without it, this effect declares no `target_spec`
    of its own, so any ``targets`` passed to `apply` belong to a *different*
    effect on the same ability/spell (e.g. Deathrite Shaman's "Exile target
    creature card from a graveyard. You gain 2 life." — the exiled card,
    not a player) — reading `targets[0]` unconditionally would silently hand
    `RulesEngine.gain_life` a `GameObject` instead of a `Player`.
    """

    def __init__(
        self,
        amount: int = 0,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        creature_filter: Optional[dict] = None,
        count_selector: Optional[str] = None,
        amount_from_target_power: bool = False,
        recipient: Optional[str] = None,
        amount_from_trigger_source_toughness: bool = False,
        amount_from_subject: Optional[str] = None,
        amount_from_trigger_event: Optional[str] = None,
        count_selector_multiplier: int = 1,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        self.count_selector = count_selector
        #: "…you gain 2 life for each creature in your party." (Shepherd of
        #: Heroes, PAR-72) — ``count_selector``'s per-unit amount is always
        #: implicitly 1 elsewhere on this effect (the count *is* the life
        #: total); this multiplies it, the `PumpEffect.x_multiplier`
        #: sibling for a fixed count-selector scale rather than {X}.
        self.count_selector_multiplier = count_selector_multiplier
        #: "Whenever ~ deals damage, you gain **that much** life." (El-Hajjâj
        #: / Exalted Angel / Whip of Erebos-shaped, PAR-36) — the event
        #: field name (``"amount"``) to read off `GameContext.trigger_event`
        #: at resolution, the same "read this firing's own payload" idiom
        #: `LoseLifeEffect.amount_from_trigger_event` (Sanguine Bond) and
        #: `DealDamageEffect.amount_from_trigger_event` already use.
        #: Overrides ``amount`` when set.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "You gain life equal to `<its / that creature's>` `<power /
        #: toughness>`" where the creature isn't a RULE 115 target of *this*
        #: effect (PAR-30, ~36 SOLO). A ``"<who>_<char>"`` string:
        #: ``self_power``/``self_toughness`` ("When ~ dies, you gain life
        #: equal to its power" — Bottle Golems), ``previous_subject_power``/
        #: ``previous_subject_toughness`` ("Destroy target creature. …you
        #: gain life equal to that creature's toughness" — Weed Strangle, a
        #: clash card; RULE 608.2h last-known info, since the creature is
        #: usually gone), ``trigger_subject_power``/``trigger_subject_
        #: toughness`` ("Whenever a creature you control enters, you gain
        #: life equal to its toughness" — Angelic Chorus; reads the firing
        #: event's own ``instance_id``).
        self.amount_from_subject = amount_from_subject
        #: "Whenever a creature you control deals combat damage to a
        #: player, you gain life equal to that creature's toughness." (Ikra
        #: Shidiqi, the Usurper, MEC-43) — "that creature" is the *source*
        #: of the very DAMAGE event that fired this group-subject trigger
        #: (Bident of Thassa's own trigger shape), not a chosen target at
        #: all, so it's read off `GameContext.trigger_event`'s
        #: ``source_id`` (`DestroyEffect.target_from_trigger_event`'s same
        #: "read this firing's own payload" idiom, applied to a magnitude
        #: rather than a destroy target) and the creature's *current* live
        #: toughness (layer-engine derived, matching RULE 613's "as the
        #: event is processed" reading every other toughness-scaled effect
        #: uses), not the damage amount itself.
        self.amount_from_trigger_source_toughness = amount_from_trigger_source_toughness
        #: "You gain life equal to target creature's power." (Dazzling
        #: Reflection, MEC-30) — reads a *shared* target this effect never
        #: declares itself (no `target_spec` of its own here; a sibling
        #: clause in the same ability — its own `prevent_damage_from_target`
        #: — is what actually requests the "target creature," and
        #: `_apply_effects_partitioned` hands the same resolved `targets`
        #: list to every effect in the ability when there's only one real
        #: targeting requirement to gather, RULE 608.2). The life-gain
        #: sibling of `DealDamageEffect.amount_from_target_count_selector`.
        self.amount_from_target_power = amount_from_target_power
        #: "**That creature's controller** gains life equal to its power."
        #: (MEC-12, Solitude) — ``"target_controller"`` reads the *same*
        #: shared target `amount_from_target_power` already reads (a
        #: sibling exile clause's own target, not this effect's own), but
        #: for *who receives* the life rather than how much: without this,
        #: an effect with no `target_kind` of its own falls back to
        #: `_controller_of(self.source, ...)` — this ability's own
        #: controller, which is wrong whenever the recipient is the
        #: target's controller instead.
        self.recipient = recipient

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        subject = targets[0] if targets else None
        player = self.player
        if player is None and self.recipient == "target_controller" and subject is not None:
            controller_id = getattr(subject, "controller_id", None)
            if controller_id is not None:
                try:
                    player = context.state.player_by_id(controller_id)
                except (KeyError, ValueError):
                    player = None
        # Tail of the chain — this effect's own chosen target (if any), else
        # its controller — is the same "explicit -> target -> controller"
        # fallback `_resolve_target_or_controller` already implements; the
        # ``recipient == "target_controller"`` branch above is this class's
        # own extra step ahead of it (see the field's docstring), so it's
        # threaded in as ``explicit`` rather than folded into the helper.
        player = self._resolve_target_or_controller(context, targets, explicit=player)

        def _from_trigger_source_toughness() -> int:
            event = context.trigger_event or {}
            source_obj = context.state.find_object(event.get("source_id"))
            return int(source_obj.toughness or 0) if source_obj is not None else 0

        def _from_subject() -> int:
            return _characteristic_of_subject(
                context, self.source, self.amount_from_subject or ""
            )

        def _from_count_selector() -> int:
            from .. import continuous  # avoid the continuous↔effects import cycle

            return self.count_selector_multiplier * continuous.count_selector(
                context.state, player.id, self.count_selector, source=self.source
            )

        amount = self._resolve_amount_override(
            self.amount,
            [
                (
                    bool(self.amount_from_trigger_event),
                    lambda: int(
                        (context.trigger_event or {}).get(self.amount_from_trigger_event) or 0
                    ),
                ),
                (
                    self.amount_from_target_power,
                    lambda: int(subject.power or 0) if subject is not None else 0,
                ),
                (self.amount_from_trigger_source_toughness, _from_trigger_source_toughness),
                (bool(self.amount_from_subject), _from_subject),
                (
                    # "You gain life equal to the life lost this way." (Gray
                    # Merchant of Asphodel-shaped RULE 119 drain) — a
                    # per-resolution accumulator (`GameContext.
                    # life_lost_this_way`), not a board count, so it's read
                    # directly rather than through `continuous.
                    # count_selector`'s vocabulary.
                    self.count_selector == "life_lost_this_way",
                    lambda: context.life_lost_this_way,
                ),
                (
                    # "…gain 1 life for each `<kind>` counter removed this
                    # way." (Lily Bowen/Essence Bottle, PAR-66) —
                    # `GameContext.counters_removed_this_way`'s own
                    # per-resolution accumulator, the counter-removal
                    # sibling of ``life_lost_this_way`` just above.
                    self.count_selector == "counters_removed_this_way",
                    lambda: context.counters_removed_this_way,
                ),
                (bool(self.count_selector) and player is not None, _from_count_selector),
            ],
            stop_at_first=True,
        )
        context.gain_life(player, amount)


class SetLifeEffect(GameEffect):
    """RULE 118.5 / 119.6: "`<player>`'s life total becomes N." (Sorin
    Markov's −3, Magister Sphinx, Repay in Kind-adjacent) — modelled purely
    as the resulting gain or loss: current > N loses ``current - N``,
    current < N gains ``N - current`` (RULE 118.4 — "becomes" is a one-shot
    set, not a lock). ``target_kind`` picks the player the same way
    `GainLifeEffect` does; default targets a player.
    """

    def __init__(
        self,
        amount: int = 0,
        target_kind: Optional[str] = "player",
        source: Optional["GameObject"] = None,
        only_reduce: bool = False,
    ) -> None:
        super().__init__(source)
        self.amount = int(amount)
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        #: "If your life total is greater than N, it becomes N." (You
        #: Compleat Me, MEC-54) — the conditional half-set: never raises a
        #: lower total, only clamps a higher one down.
        self.only_reduce = bool(only_reduce)

    def target_polarity(self) -> Optional[str]:
        return None  # can help or hurt depending on the target's current life

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self._resolve_target_or_controller(context, targets)
        if player is None:
            return
        current = int(getattr(player, "life", 0))
        if current > self.amount:
            context.lose_life(player, current - self.amount)
        elif current < self.amount and not self.only_reduce:
            context.gain_life(player, self.amount - current)


class SetMaxLifeTotalEffect(GameEffect):
    """MEC-54: "For the rest of the game, your maximum life total is N."
    (You Compleat Me) — installs a permanent `RulesEngine.set_max_life_total`
    cap on the effect's controller. Untargeted (always "your")."""

    def __init__(self, amount: int = 0, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = int(amount)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.engine.set_max_life_total(player, self.amount)


class PreventDamageEffect(GameEffect):
    """RULE 615: "Prevent all/the next N damage that would be dealt to you
    this turn" (Riot Control's spell-level "all"; Thought Lash's own
    repeatable "the next 1") — a one-shot effect that grants its own
    controller a turn-scoped damage-prevention shield, Regenerate-shaped:
    this class just triggers `RulesEngine.prevent_damage_to_player`, which
    builds+attaches the actual `ReplacementEffect` shield (unlike
    `RegenerateEffect`'s shield, this one lives on `Player.player_effects`,
    not a permanent's `replacement_effects` — nothing is being regenerated,
    the target is always the caster/activator, never chosen).

    ``amount="all"`` prevents every point of damage the player would take
    for the rest of the turn; an int prevents a cumulative bank of that
    many points total (Thought Lash's activated ability can be paid
    multiple times, each adding to the same turn's bank).

    PAR-15's targeted sibling ("prevent the next N damage that would be
    dealt this turn to any number of targets, divided as you choose" —
    Embolden/Remedy/Angel of Salvation) sets ``target_kind`` — the pool is
    then divided (RULE 601.2d-shaped, `DealDamageEffect(divided=True)`'s
    same as-evenly-as-possible split) among whichever targets were chosen
    and each gets its own `RulesEngine.prevent_damage_to_target` shield,
    rather than the single fixed "you" shield the untargeted shape above
    grants. ``amount_if_kicked`` is Pollen Remedy's own trailing "if this
    spell was kicked, prevent the next N damage this way instead" —
    an *override*, not an addition, so it's a param on this effect rather
    than a generic kicked-conditional wrapper (RULE 702.33b already covers
    the additive "if kicked, `<effect>`" shape via `ConditionalEffect`;
    this is the narrower override some cards use instead).
    """

    def __init__(
        self,
        amount: Union[int, str] = "all",
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        target: Any = None,
        count: int = 1,
        optional: bool = False,
        creature_filter: Optional[dict] = None,
        divided: bool = False,
        amount_if_kicked: Optional[Union[int, str]] = None,
        self_only: bool = False,
        watched_source_is_self: bool = False,
        recipient_is_activator: bool = False,
        combat_only: bool = False,
        rider: Optional[dict] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.amount_if_kicked = amount_if_kicked
        self.divided = divided
        self.target = target
        #: Inkshield — "Prevent all **combat** damage that would be dealt to
        #: you this turn. For each 1 damage prevented this way, create a …
        #: token." ``combat_only`` narrows the untargeted "…to you" shield to
        #: RULE 510 combat damage; ``rider`` is the "for each 1 prevented"
        #: follow-up, a `RulesEngine.apply_prevent_rider` payload (here a
        #: ``create_tokens_scaled`` rider).
        self.combat_only = combat_only
        self.rider = rider
        #: "Prevent the next N damage that would be dealt to `<this
        #: permanent>` this turn." (Opal-Eye, Konda's Yojimbo, MEC-30) — the
        #: object-recipient sibling of the untargeted "…to you" default:
        #: shields this effect's own source, not its controller.
        self.self_only = self_only
        #: "The next time **this creature** would deal damage to you this
        #: turn, prevent that damage." (Mercenaries, MEC-30) — narrows the
        #: untargeted "…to you" shield to one fixed, already-known source
        #: (this effect's own source), the no-chooser-needed sibling of
        #: `RequestPreventDamageSourceEffect`'s "a source of your choice".
        self.watched_source_is_self = watched_source_is_self
        #: RULE 602.2b: "you" resolves to whoever *activated* this ability,
        #: not this permanent's own printed controller — only ever diverges
        #: from `_controller_of` under a standing `ActivationCost.any_
        #: player_may_activate` exception (Mercenaries is the only card so
        #: far). Read via `GameContext.resolving_controller_id`, falling
        #: back to `_controller_of` when unset (a direct `effect.apply()`
        #: call outside real stack resolution — tests, a fixture).
        self.recipient_is_activator = recipient_is_activator
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional, count=count, creature_filter=creature_filter)
            if target_kind is not None
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        kicker_count = getattr(self.source, "kicker_count", 0) or 0
        amount = self._resolve_amount_override(
            self.amount,
            [(self.amount_if_kicked is not None and kicker_count > 0, lambda: self.amount_if_kicked)],
            stop_at_first=True,
        )
        if self.self_only:
            if self.source is not None:
                context.prevent_damage_to_target(self.source, amount)
            return
        if self.target_spec is None:
            player = None
            if self.recipient_is_activator and context.resolving_controller_id is not None:
                try:
                    player = context.state.player_by_id(context.resolving_controller_id)
                except (KeyError, ValueError):
                    player = None
            if player is None:
                player = _controller_of(self.source, context)
            if player is not None:
                watched_source_id = self.source.instance_id if self.watched_source_is_self and self.source is not None else None
                context.prevent_damage_to_player(
                    player, amount, watched_source_id=watched_source_id,
                    rider=self.rider, combat_only=self.combat_only,
                )
            return
        chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
        if not chosen:
            return
        if self.divided:
            total = amount if isinstance(amount, int) else 0
            base, extra = divmod(total, len(chosen))
            shares = [base + (1 if i < extra else 0) for i in range(len(chosen))]
        else:
            shares = [amount] * len(chosen)
        for target, share in zip(chosen, shares):
            if share == "all" or (isinstance(share, int) and share > 0):
                context.prevent_damage_to_target(target, share)


class GrantCantLoseThisTurnEffect(GameEffect):
    """"You can't lose the game this turn." (RULE 104.3a — Angel's Grace,
    MEC-43 round 4E) — installs the existing `WinConditionEffect`/
    `_loss_prevented` machinery directly onto this effect's own
    controller's `Player.player_effects`, turn-scoped instead of standing.
    See `RulesEngine.grant_cant_lose_this_turn`.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.grant_cant_lose_this_turn(player)


class DamageLifeFloorEffect(GameEffect):
    """"Until end of turn, damage that would reduce your life total to
    less than `floor` reduces it to `floor` instead." (RULE 104.3a-
    adjacent, Angel's Grace, MEC-43 round 4E) — see `RulesEngine.
    cap_damage_life_floor`.
    """

    def __init__(self, floor: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.floor = int(floor)
        self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.cap_damage_life_floor(player, self.floor)


class PreventLifeGainEffect(GameEffect):
    """RULE 119.3/616.1: "Your opponents can't gain life this turn."
    (Roiling Vortex's activated-ability rider). ``recipient`` picks who
    gets the shield — ``"opponents"`` (this effect's own controller's
    opponents, the only printed phrasing so far) — via `RulesEngine.
    prevent_life_gain_this_turn`, the absolute-cancel sibling of
    `PreventDamageEffect`'s numeric shield.
    """

    def __init__(self, recipient: str = "opponents", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.recipient = recipient

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if self.recipient == "all":
            # "Players can't gain life this turn." (Skullcrack / Erebos's
            # Intervention / Rain of Gore) — every living player, no
            # controller needed.
            players = list(context.state.living_players())
        elif controller is None:
            return
        elif self.recipient == "opponents":
            players = [p for p in context.state.living_players() if p.id != controller.id]
        else:
            players = [controller]
        if players:
            context.prevent_life_gain_this_turn(players)


class DisableDamagePreventionEffect(GameEffect):
    """RULE 615: "Damage can't be prevented this turn." (Insult //
    Injury/Isengard Unleashed, MEC-30) — untargeted, no recipient at all;
    just flips `GameState.damage_prevention_disabled` via `RulesEngine.
    disable_damage_prevention_this_turn`.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        context.disable_damage_prevention_this_turn()


class GrantDamageMultiplierThisTurnEffect(GameEffect):
    """RULE 616: "If a source you control would deal damage this turn, it
    deals double/triple that damage instead." (Insult // Injury/Isengard
    Unleashed, MEC-30) — the spell-cast sibling of `_double_damage_
    replacement`'s permanent-attached shape; see `RulesEngine.grant_damage_
    multiplier_this_turn`'s own docstring for why a separate method exists
    rather than reusing that factory directly from here.
    """

    def __init__(
        self, multiplier: int = 2, to_opponent_only: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.multiplier = multiplier
        self.to_opponent_only = to_opponent_only

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None or self.source is None:
            return
        context.grant_damage_multiplier_this_turn(
            controller, self.source, multiplier=self.multiplier,
            to_opponent_only=self.to_opponent_only,
        )


class PreventAllCombatDamageEffect(GameEffect):
    """RULE 615: "Prevent all combat damage that would be dealt this turn."
    (Fog) — deliberately a separate class from `PreventDamageEffect`
    rather than a third mode on it: that class's two modes both shield one
    resolved *recipient* (the caster, or a chosen target); this one has no
    recipient at all — every attacker's and every blocker's combat damage
    to *anyone* is prevented, for the rest of the turn, which is why it
    calls `RulesEngine.prevent_all_combat_damage_this_turn` instead of
    either of that class's per-recipient shield builders.

    ``exclude_subtype`` (Galadhrim Ambush) threads straight through to
    that method's own qualifier — see its docstring.
    """

    def __init__(
        self, source: Optional["GameObject"] = None, exclude_subtype: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.exclude_subtype = exclude_subtype

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.prevent_all_combat_damage_this_turn(player, exclude_subtype=self.exclude_subtype)


class RequestPreventDamageSourceEffect(GameEffect):
    """RULE 615/616.1d: "The next time a source of your choice [matching
    ``source_filter``] would deal damage to `<recipient>` this turn, prevent
    [half] that damage[, rounded up/down]." — the Circle of Protection/Rune
    of Protection family. Opens `RulesEngine._request_choose_objects`'s
    general chooser (a ``"remember_source"`` action) over every battlefield
    permanent matching ``source_filter`` (a `combat.matches_object_filter`-
    shaped dict — a colour, "an artifact source", a creature of an
    ETB-chosen type…), then grants a `RulesEngine.prevent_damage_to_player`/
    `_to_target`-shaped shield scoped to whichever one gets picked (RULE
    615's "next time" — self-expiring even if that source never actually
    deals damage this turn).

    Scoped to battlefield permanents only — RULE 609.7a's other two source
    kinds (a spell or an ability still on the stack) aren't offered, since
    `_request_choose_objects` only ever candidates `GameObject`s already on
    the battlefield. No card in this family's real pool needs to name an
    unresolved spell/ability, so this is a deliberate, documented
    simplification rather than a silent gap.

    ``target_kind``/``target`` (Circle of Despair/Martyr's Cause/Sanctum
    Guardian's "…would deal damage to **any target** this turn") route the
    *recipient* through ordinary RULE 115 targeting instead of this effect's
    own controller — the overwhelming majority of real cards ("…would deal
    damage to **you** this turn") leave both unset, so the shield simply
    protects the caster. ``amount``/``rider`` mirror
    `_prevent_damage_replacement`'s own vocabulary (an ``int``, ``"all"``, or
    ``{"half": "up"|"down"}``; `RulesEngine.apply_prevent_rider`'s follow-up
    shape) — Deflecting Palm/Reverse Damage-shaped.
    """

    def __init__(
        self,
        source_filter: Optional[dict] = None,
        target_kind: Optional[str] = None,
        target: Any = None,
        amount: Any = "all",
        rider: Any = None,
        optional: bool = False,
        recipient: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.source_filter = dict(source_filter or {})
        self.amount = amount
        self.rider = list(rider) if isinstance(rider, list) else (dict(rider) if rider else None)
        self.optional = optional
        self.target = target
        #: "…would deal damage to **enchanted creature** this turn" (Kithkin
        #: Armor, MEC-30) — the chosen-source family's own sibling of Family
        #: A's ``to="attached_permanent"``: reads ``self.source.attached_to``
        #: instead of the caster/an RULE 115 target. Mutually exclusive with
        #: ``target_kind`` (no real card needs both).
        self.recipient = recipient
        self.target_spec = (
            TargetSpec(kind=target_kind, count=1) if target_kind is not None else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None:
            return
        player = _controller_of(src, context)
        if player is None:
            return
        # "…would deal damage to you and/or creatures you control this
        # turn" (Shadowbane, MEC-30) — a dynamic recipient *set*, not one
        # resolved object, so it skips the single-``recipient_obj``
        # resolution below entirely; `_apply_chosen_object` reads this
        # scope key straight off ``prevent_shield`` instead of a fixed id.
        # ``"any"`` (Penance, MEC-30 — "…would deal damage this turn,
        # prevent that damage.", no "to you" at all) is the same idea taken
        # further: no recipient qualifier whatsoever, so `recipient_obj`
        # legitimately stays unresolved — `RulesEngine.prevent_damage_from_
        # source`'s own unscoped shape, reached via `_apply_chosen_object`'s
        # matching branch below.
        if self.recipient == "any":
            recipient_obj = None
        elif self.recipient == "you_and_creatures_you_control":
            recipient_obj = player
        elif self.recipient == "attached_permanent":
            host_id = getattr(src, "attached_to", None)
            recipient_obj = context.state.find_object(host_id) if host_id is not None else None
        elif self.target_spec is not None:
            chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
            recipient_obj = chosen[0] if chosen else None
        else:
            recipient_obj = player
        if recipient_obj is None and self.recipient != "any":
            return
        from .. import combat  # local: avoid the combat<->effects import cycle

        candidates = [
            obj for obj in context.state.battlefield
            if combat.matches_object_filter(obj, self.source_filter, reference=src)
        ]
        recipient_is_player = recipient_obj is not None and not hasattr(recipient_obj, "instance_id")
        context.engine._request_choose_objects(
            player, candidates, "remember_source", count=1, optional=self.optional,
            prompt=f"{src.name}: Quelle wählen",
            source=src,
            prevent_shield={
                "recipient_id": (
                    (recipient_obj.id if recipient_is_player else recipient_obj.instance_id)
                    if recipient_obj is not None else None
                ),
                "recipient_is_player": recipient_is_player,
                "recipient_scope": (
                    self.recipient
                    if self.recipient in ("you_and_creatures_you_control", "any")
                    else None
                ),
                "amount": self.amount,
                "rider": self.rider,
            },
        )


class RequestRedirectDamageSourceEffect(GameEffect):
    """RULE 616.1c "the next time a source of your choice would deal damage
    this turn, that damage is dealt to `<X>` instead" (Opal-Eye, Konda's
    Yojimbo, MEC-30) — `RequestPreventDamageSourceEffect`'s redirect
    sibling: opens the exact same chooser (a ``"remember_source_redirect"``
    action this time) over every battlefield permanent matching
    ``source_filter``, then grants a `RulesEngine.redirect_damage_from_
    source` shield instead of a prevention one. ``recipient="self"`` (the
    only real printed shape — "dealt to `<this permanent>` instead") reads
    this effect's own source as the new recipient.
    """

    def __init__(
        self,
        source_filter: Optional[dict] = None,
        amount: Any = "all",
        recipient: str = "self",
        optional: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.source_filter = dict(source_filter or {})
        self.amount = amount
        self.recipient = recipient
        self.optional = optional

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None:
            return
        player = _controller_of(src, context)
        if player is None:
            return
        recipient_obj: Any = src if self.recipient == "self" else None
        if recipient_obj is None:
            return
        from .. import combat  # local: avoid the combat<->effects import cycle

        candidates = [
            obj for obj in context.state.battlefield
            if combat.matches_object_filter(obj, self.source_filter, reference=src)
        ]
        context.engine._request_choose_objects(
            player, candidates, "remember_source_redirect", count=1, optional=self.optional,
            prompt=f"{src.name}: Quelle wählen",
            source=src,
            redirect_shield={
                "recipient_id": recipient_obj.instance_id,
                "recipient_is_player": False,
                "amount": self.amount,
            },
        )


class ChooseSourceCoinFlipEffect(GameEffect):
    """"Choose a source you control and flip a coin. If you win the flip,
    the next time that source would deal damage this turn, it deals
    double that damage instead. If you lose the flip, the next time it
    would deal damage this turn, prevent that damage." (Desperate Gambit,
    MEC-30 — the last card of the family, closing it out.)

    Structurally the chosen-source chooser family's third member: unlike
    `RequestPreventDamageSourceEffect`/`RequestRedirectDamageSourceEffect`,
    the candidate pool is narrowed to **battlefield permanents this
    effect's own controller controls** ("a source **you control**", RULE
    609.7a — not "of your choice" over anyone's permanents), and nothing
    is decided about win/lose until the pick actually resolves — the
    ``"remember_source_coinflip"`` action flips the coin (`RulesEngine.
    coin_flip`, RULE 705.1) *at that point* and branches into `RulesEngine.
    grant_damage_multiplier_from_source` (win) or the already-shipped
    `prevent_damage_from_source` (lose), both scoped to the one chosen
    permanent. No shield payload needed on the choice itself, since the
    chosen object already carries everything both branches need.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None:
            return
        player = _controller_of(src, context)
        if player is None:
            return
        candidates = list(context.state.permanents_controlled_by(player.id))
        context.engine._request_choose_objects(
            player, candidates, "remember_source_coinflip", count=1,
            prompt=f"{src.name}: Quelle für den Münzwurf wählen",
            source=src,
        )


class PreventDamageFromTargetEffect(GameEffect):
    """RULE 615/616.1d: "The next time target creature would deal damage
    this turn, prevent that damage." (Awe Strike/Dazzling Reflection) — the
    targeted, no-chooser-needed sibling of `RequestPreventDamageSourceEffect`:
    the source is already pinned by ordinary RULE 115 targeting, so this just
    opens `RulesEngine.prevent_damage_from_source`'s unscoped-recipient
    shield directly (protects *whoever* the target would have hit, not one
    fixed recipient) — no interactive "choose a source" step needed.
    """

    def __init__(
        self,
        target_kind: str = "creature",
        target: Any = None,
        count: int = 1,
        amount: Any = "all",
        rider: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.amount = amount
        self.rider = list(rider) if isinstance(rider, list) else (dict(rider) if rider else None)
        self.target_spec = TargetSpec(kind=target_kind, count=count)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
        for obj in chosen:
            context.engine.prevent_damage_from_source(obj, self.amount, rider=self.rider)


class ExtraLandPlayEffect(GameEffect):
    """A one-shot "you may play N additional land(s) this turn" grant
    (Explore/Escape to the Wilds/Kiora's -1-shaped, RULE 305.2) — the
    resolve-time, single-turn sibling of the standing `"extra_land_drop"`
    `StaticAbility` a permanent like Exploration grants continuously
    (`game/continuous.py`'s `extra_land_plays_for`).

    Bumps the controller's `Player.extra_land_plays_this_turn` counter,
    which `GameEngine.can_play_land` adds to the per-turn cap alongside the
    standing static grant; `GameEngine.begin_turn` resets it to 0 each turn
    the same way `lands_played_this_turn` resets.
    """

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            player.extra_land_plays_this_turn += self.count


class GraveyardPlayPermissionThisTurnEffect(GameEffect):
    """"Until end of turn, you may play lands and cast spells from your
    graveyard." (Yawgmoth's Will-shaped, MEC-12) — a *player*-scoped
    standing permission, unlike `GraveyardCastPermissionEffect` (Lurrus-
    shaped), which lives on a permanent's own `static_effects` and vanishes
    the instant that permanent leaves the battlefield. The sorcery granting
    this one is already gone (to the graveyard, or — thanks to Yawgmoth's
    Will's own second clause below — exile) long before end of turn, so the
    permission is tracked on the player directly rather than scanned off a
    permanent. Stamps `Player.graveyard_play_permission_until_turn` to the
    current turn number; `game/graveyard_cast.py`'s `has_temporary_
    graveyard_play_permission` reads it back — a stamped turn number
    naturally "expires" the moment `GameState.internal_turn.number` advances, so
    nothing needs a separate sweep. Unlike every existing graveyard-cast
    permission source, this one covers lands too.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            player.graveyard_play_permission_until_turn = context.state.internal_turn.number


class GraveyardRedirectToExileEffect(GameEffect):
    """"If a card would be put into your graveyard from anywhere this
    turn, exile that card instead." (Yawgmoth's Will's own second clause,
    MEC-12) — the player-scoped, turn-limited sibling of
    `GraveyardCastPermissionEffect.exile_if_would_be_put_into_graveyard`'s
    per-*object* redirect (which only ever catches the one spell cast via
    its own permission): this one catches every card this player *owns*,
    from any zone, for any reason, for the rest of the turn. Stamps
    `Player.graveyard_redirect_to_exile_until_turn`, checked directly in
    `RulesEngine._move_to_graveyard` — the one choke point every
    graveyard-bound move funnels through — against whichever player owns
    the moving card, since a card only ever enters its own owner's
    graveyard (RULE 404.4/700.4), which is exactly what "your graveyard"
    means here.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            player.graveyard_redirect_to_exile_until_turn = context.state.internal_turn.number


class ExileTriggeringDiscardMayPlayThisTurnEffect(GameEffect):
    """"Whenever you discard a card, you may exile that card from your
    graveyard. If you do, you may play that card this turn." (Containment
    Construct; Conspiracy Theorist's "…cast it this turn"; Currency
    Converter's exile-only first half, PAR-60).

    Reads the firing `DISCARD_CARD` event's ``instance_id``, moves that
    object graveyard -> exile, and — unless ``play_permission`` is False —
    stamps `GameState.temp_play_permissions[iid]` to the current turn
    (the same turn-scoped play window `impulsive_draw`/Lukka use, read back
    by `GameEngine.can_play_land`/`can_cast`). Documented simplification:
    the printed "you may" is modeled as always doing it — exiling a
    just-discarded card to enable playing it is essentially always what the
    controller wants for these cards.
    """

    def __init__(self, play_permission: bool = True,
                 track_exiled_with: bool = False,
                 source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.play_permission = bool(play_permission)
        #: Currency Converter (PAR-60) — "you may exile that card from your
        #: graveyard" with **no** play window: instead the exiled card's
        #: instance id is appended to this ability's own source
        #: `GameObject.exiled_with_ids` (MEC-21's accumulating tracker), so
        #: its separate ``{T}`` ability can cash one back out later.
        self.track_exiled_with = bool(track_exiled_with)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event or {}
        iid = event.get("instance_id")
        if iid is None:
            return
        obj = context.state.find_object(iid)
        if obj is None or obj.zone != Zone.GRAVEYARD:
            return
        owner = None
        try:
            owner = context.state.player_by_id(obj.owner_id)
        except (KeyError, ValueError):
            return
        if obj in owner.graveyard:
            owner.graveyard.remove(obj)
        obj.zone = Zone.EXILE
        owner.exile.append(obj)
        if self.play_permission:
            context.state.temp_play_permissions[obj.instance_id] = (
                context.state.internal_turn.number
            )
        if self.track_exiled_with and self.source is not None:
            self.source.exiled_with_ids.append(obj.instance_id)


class CurrencyConverterCashOutEffect(GameEffect):
    """"{T}: Put a card exiled with this artifact into its owner's graveyard.
    If it's a land card, create a Treasure token. If it's a nonland card,
    create a 2/2 black Rogue creature token." (Currency Converter, PAR-60.)

    Reads this ability's own source `GameObject.exiled_with_ids` (the
    accumulating MEC-21 tracker `ExileTriggeringDiscardMayPlayThisTurnEffect`
    with ``track_exiled_with=True`` fills from the discard trigger). With one
    candidate it acts directly; with several it opens the general
    `_request_choose_objects` chooser (``"choose_permanent"`` action — a bare
    "stamp the pick, act in ``then_specs``" idiom, no zone concept of its
    own), running `currency_converter_resolve` once answered.
    """

    def _cash_out(self, context: GameContext, obj: "GameObject") -> None:
        from ...services.token_database import synthesize_token_card

        try:
            owner = context.state.player_by_id(obj.owner_id)
        except (KeyError, ValueError):
            return
        if obj in owner.exile:
            owner.exile.remove(obj)
        obj.zone = Zone.GRAVEYARD
        owner.graveyard.append(obj)
        if self.source is not None and obj.instance_id in self.source.exiled_with_ids:
            self.source.exiled_with_ids.remove(obj.instance_id)
        controller_id = getattr(self.source, "controller_id", None) or owner.id
        if "land" in (obj.card.type_line or "").lower():
            card = synthesize_token_card("Treasure")
        else:
            card = synthesize_token_card(
                "Rogue", power=2, toughness=2, colors=["B"], subtypes=["Rogue"],
            )
        context.create_token(controller_id, card, 1)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        player = _controller_of(self.source, context)
        if player is None:
            return
        ids = list(getattr(self.source, "exiled_with_ids", None) or [])
        cands = [
            o for o in (context.state.find_object(i) for i in ids)
            if o is not None and o.zone == Zone.EXILE
        ]
        if not cands:
            return
        if len(cands) == 1:
            self._cash_out(context, cands[0])
            return
        context.engine._request_choose_objects(
            player, cands, "choose_permanent", count=1, optional=False,
            prompt="Currency Converter: verbannte Karte in den Friedhof legen",
            source=self.source,
            then_specs=[{"type": "currency_converter_resolve", "params": {}}],
        )


class CurrencyConverterResolveEffect(CurrencyConverterCashOutEffect):
    """``then_specs`` tail of `CurrencyConverterCashOutEffect`'s multi-card
    branch: reads the pick back off ``source.chosen_permanent_id`` (stamped
    by the ``"choose_permanent"`` action) and cashes just that one out."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        iid = getattr(self.source, "chosen_permanent_id", None)
        self.source.chosen_permanent_id = None
        if iid is None:
            return
        obj = context.state.find_object(iid)
        if obj is not None and obj.zone == Zone.EXILE:
            self._cash_out(context, obj)


class ExchangeLifeTotalsEffect(GameEffect):
    """"Two target players exchange life totals." (Soul Conduit, MEC-43
    round 2; PAR-29) — a genuine simultaneous swap, distinct from every
    other life effect in this file (`GainLifeEffect`/`LoseLifeEffect`, both
    single-player deltas): neither player's life total is set *to* a
    number, each just receives the *other's* current one, in one atomic
    step so a same-resolution "then" clause reading either player's life
    sees the post-swap value.

    RULE 701.10's other printed shape — "`<source's controller>` exchange[s]
    life totals with target opponent/player." (Magus of the Mirror/Mister
    Negative) — is this effect's own controller plus one `TargetSpec`
    rather than two, the same self+target/two-target split
    `ExchangeControlEffect` uses: ``target_kind=None`` (the default) keeps
    the original two-target mode, a real ``target_kind`` switches to it.

    Not modeled as a gain/loss for either player (no `GAIN_LIFE`/
    `LOSE_LIFE` event fires) — an exchange is its own RULE 119 category,
    and every real card of this shape prints no "you gain/lose life"
    follow-up that would depend on one firing.
    """

    def __init__(
        self, source: Optional["GameObject"] = None, target_kind: Optional[str] = None,
        life_difference_at_most: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self._two_target_mode = target_kind is None
        self.target_spec = (
            TargetSpec(kind="player", count=2) if self._two_target_mode
            else TargetSpec(kind=target_kind)
        )
        #: PAR-30 (RULE 701.10 residue, Psychic Transfer) — "if the
        #: difference between your life total and target player's life
        #: total is N or less, exchange life totals with that player." A
        #: pre-effect numeric gate RULE 115 has no vocabulary for (the
        #: comparison is between two *life totals*, not a static creature
        #: characteristic `ConditionalEffect` could read off a target) —
        #: checked here at resolution instead, the same "no `legal_targets`/
        #: client change" idiom `ExchangeControlEffect._cross_target_ok`
        #: uses: the swap just doesn't happen if the gap is too wide.
        self.life_difference_at_most = life_difference_at_most

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = list(targets or [])
        if self._two_target_mode:
            if len(chosen) != 2:
                return
            a, b = chosen
        else:
            a = _controller_of(self.source, context)
            b = chosen[0] if chosen else None
            if a is None or b is None:
                return
        if self.life_difference_at_most is not None and abs(
            (a.life or 0) - (b.life or 0)
        ) > self.life_difference_at_most:
            return
        a.life, b.life = b.life, a.life


class ExchangeLifeTotalWithToughnessEffect(GameEffect):
    """"Exchange target opponent's life total with this creature's toughness."
    (Tree of Perdition — RULE 701.12; rulings 2016-07-13.)

    Not a player↔player swap like `ExchangeLifeTotalsEffect`. On resolution:

    * the opponent's life total becomes ~'s *former* (derived) toughness,
      reached by an ordinary life gain/loss so replacement/"whenever you
      gain/lose life" effects interact (ruling 1);
    * ~'s **base** toughness is set to the opponent's former life total — a
      permanent layer-7b `pt_set` (``power=None``, toughness only) parked in
      `GameState.floating_statics`, so Auras/Equipment/counters still stack
      on top afterward (ruling 2);
    * if ~ has left the battlefield by the time this resolves, nothing
      happens at all (ruling 3).
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="opponent")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        player = picks[0] if picks else None
        src = self.source
        if player is None or src is None:
            return
        # ruling 3 — ~ must still be on the battlefield to make the exchange.
        if src not in context.state.battlefield:
            return
        former_toughness = int(getattr(src, "toughness", 0) or 0)
        former_life = int(getattr(player, "life", 0) or 0)
        delta = former_toughness - former_life
        if delta > 0:
            context.gain_life(player, delta)
        elif delta < 0:
            context.lose_life(player, -delta)
        # ~'s base toughness becomes the opponent's former life total,
        # permanently (no duration) — later P/T layers still apply.
        ability = EffectRegistry.create("pt_set", {"power": None, "toughness": former_life})
        if isinstance(ability, StaticAbility):
            ability.source = src
            ability.timestamp = context.state.next_timestamp()
            ability.affects = "objects"
            ability.object_ids = [src.instance_id]
            context.state.floating_statics.append(ability)
        context.recompute()


class TripleExchangeEffect(GameEffect):
    """"Exchange life totals with that player, exchange control of all
    permanents you and that player control, and exchange cards in your
    hands, cards in your libraries, and cards in your graveyards." (Mirror
    Mirror, delayed to "the beginning of the next end step" — see
    `CreateDelayedTriggerEffect`'s ``capture="target_player"``, which
    stamps ``player`` here with the player chosen when the ability first
    resolved, since the delayed firing itself carries no target of its own).

    RULE 701.10's three swaps, all at once. Not modeled as three separate
    registered effects composed in the delayed trigger's own ``effects``
    list: `ExchangeControlEffect`'s battlefield swap only ever handles ONE
    RULE 115-targeted pair, never "every permanent both players control" —
    an untargeted mass form this card is the only one to want — so the
    whole thing is one bespoke effect instead of three ordinary ones.

    Hand/library/graveyard are all owner-scoped zones (RULE 400.3 — each
    player has their own), so "exchanging" their contents genuinely swaps
    **ownership** of every card in them (RULE 701.10h), unlike the
    battlefield swap (control only, ownership never moves for a permanent
    exchange). Exile/command/the stack are untouched — not part of the
    printed effect.
    """

    def __init__(self, source: Optional["GameObject"] = None, player: Optional["Player"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        you = _controller_of(self.source, context)
        them = self.player
        if you is None or them is None or you is them:
            return
        you.life, them.life = them.life, you.life
        for obj in context.state.permanents():
            if obj.controller_id == you.id:
                obj.controller_id = them.id
                obj.summoning_sick = True
            elif obj.controller_id == them.id:
                obj.controller_id = you.id
                obj.summoning_sick = True
        context.recompute()
        for zone in (Zone.HAND, Zone.LIBRARY, Zone.GRAVEYARD):
            you_cards = list(you.zones.get(zone, []))
            them_cards = list(them.zones.get(zone, []))
            for obj in you_cards:
                obj.owner_id = them.id
                obj.controller_id = them.id
            for obj in them_cards:
                obj.owner_id = you.id
                obj.controller_id = you.id
            you.zones[zone], them.zones[zone] = them_cards, you_cards


class JuxtaposeEffect(GameEffect):
    """"You and target player exchange control of the creature you each
    control with the greatest mana value. Then exchange control of
    artifacts the same way." (Juxtapose) — RULE 701.10's own "the X with
    the greatest mana value" dynamic selection, run twice (creatures, then
    artifacts) against the same pair of players.

    **Documented simplification**: "If two or more permanents a player
    controls are tied for greatest, their controller chooses one of them."
    is read as the lowest ``instance_id`` among the tied permanents (the
    one that entered the battlefield first) rather than an interactive
    choice — a real board tie has no gameplay-relevant difference between
    the tied permanents' mana values, so this one card doesn't justify a
    new interactive-choice type of its own.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="player")

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    @staticmethod
    def _greatest(state: "GameState", player_id: str, want_creature: bool) -> Optional["GameObject"]:
        candidates = [
            o for o in state.permanents()
            if o.controller_id == player_id
            and (o.is_creature if want_creature else bool(o.card.is_artifact))
        ]
        if not candidates:
            return None
        best_mv = max(o.card.converted_mana_cost or 0 for o in candidates)
        tied = [o for o in candidates if (o.card.converted_mana_cost or 0) == best_mv]
        return min(tied, key=lambda o: o.instance_id)

    def _swap_round(self, context: GameContext, you: "Player", them: "Player", want_creature: bool) -> None:
        mine = self._greatest(context.state, you.id, want_creature)
        theirs = self._greatest(context.state, them.id, want_creature)
        if mine is None or theirs is None:
            return
        mine.controller_id, theirs.controller_id = theirs.controller_id, mine.controller_id
        mine.summoning_sick = True
        theirs.summoning_sick = True

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        you = _controller_of(self.source, context)
        them = targets[0] if targets else None
        if you is None or them is None or you is them:
            return
        self._swap_round(context, you, them, want_creature=True)
        self._swap_round(context, you, them, want_creature=False)
        context.recompute()


class CulturalExchangeRound2Effect(GameEffect):
    """`CulturalExchangeEffect`'s own second interactive round — see its
    docstring. Threaded through as a plain `EffectSpec` payload (``from_
    player_id``/``to_player_id``, both resolved player ids from the first
    round's own two RULE 115 targets, not card text) rather than a second
    `GameContext.previous_targets`-style referent, since the first round's
    ``_request_choose_objects`` needs a concrete `EffectSpec` to hand its own
    ``then_specs``/``else_specs`` — the "run round 2 regardless of round 1's
    outcome" combination `CulturalExchangeEffect.apply` sets both to.
    """

    def __init__(
        self, source: Optional["GameObject"] = None,
        from_player_id: Optional[str] = None, to_player_id: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.from_player_id = from_player_id
        self.to_player_id = to_player_id

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from_player = context.state.player_by_id(self.from_player_id) if self.from_player_id else None
        caster = _controller_of(self.source, context)
        if from_player is None or self.to_player_id is None or caster is None:
            return
        candidates = [
            o for o in context.state.permanents()
            if o.controller_id == from_player.id and o.is_creature
        ]
        if not candidates:
            return
        context.engine._request_choose_objects(
            caster, candidates, "gain_control_for", count=len(candidates), optional=True,
            source=self.source, control_recipient_id=self.to_player_id,
            prompt="Kreatur an den anderen Spieler abgeben?",
        )


class CulturalExchangeEffect(GameEffect):
    """"Choose any number of creatures target player controls. Choose the
    same number of creatures another target player controls. Those players
    exchange control of those creatures. (This effect lasts indefinitely.)"
    (Cultural Exchange) — two independent RULE 115 player targets, then two
    chained interactive rounds: this ability's own controller picks any
    number of the *first* target's creatures to hand to the *second*
    (`RulesEngine._request_choose_objects`, action ``"gain_control_for"``),
    then — via `CulturalExchangeRound2Effect`, run through the first
    round's own ``then_specs``/``else_specs`` so it fires either way — the
    same from the second target's creatures back to the first.

    **Documented simplification**: the printed "choose the **same**
    number" — the second round's count matching however many the first
    round picked exactly — isn't modeled; both rounds are independently
    "any number of" instead (`_request_choose_objects` has no "count =
    however many a separate, already-finished choice ended up with"
    primitive, and this is the only card that would ever need one). The
    actual control transfer — every creature picked from the first target
    moves to the second and vice versa — is otherwise exact, including
    "lasts indefinitely" (a bare `controller_id` reassignment, permanent
    like every other exchange-control effect, never a duration-bounded
    grab).
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="player")
        self.extra_target_specs = (TargetSpec(kind="player"),)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        a = targets[0] if targets and len(targets) > 0 else None
        b = targets[1] if targets and len(targets) > 1 else None
        caster = _controller_of(self.source, context)
        if a is None or b is None or a is b or caster is None:
            return
        round2 = [{
            "type": "cultural_exchange_round2",
            "params": {"from_player_id": b.id, "to_player_id": a.id},
        }]
        a_creatures = [
            o for o in context.state.permanents() if o.controller_id == a.id and o.is_creature
        ]
        if not a_creatures:
            context.apply_effect_specs(round2, self.source)
            return
        context.engine._request_choose_objects(
            caster, a_creatures, "gain_control_for", count=len(a_creatures), optional=True,
            source=self.source, control_recipient_id=b.id,
            prompt="Kreatur an den anderen Spieler abgeben?",
            then_specs=round2, else_specs=round2,
        )


#: `LoseLifeEffect`'s mass-selector vocabulary ("each opponent loses N
#: life"/"each player loses N life", RULE 601.2c) — the same closed,
#: untargeted-group shape `DealDamageEffect`'s `_DAMAGE_SELECTORS` uses (no
#: "each_creature" here — life loss never targets a creature).
_LOSE_LIFE_SELECTORS: frozenset[str] = frozenset({"each_player", "each_opponent"})


class LoseLifeEffect(GameEffect):
    """A player loses ``amount`` life (RULE 118/119) — untargeted.

    ``selector="defending_player"`` (afflict, RULE 702.130) resolves the
    player dynamically at apply-time via `_defending_player_of`, since the
    same bound ability fires against a different defender each combat;
    a plain ``player``/target keeps the shape every other simple player
    effect (`GainLifeEffect`, `DiscardEffect`) already uses.
    ``selector="each_opponent"``/``"each_player"`` (RULE 601.2c) instead
    hits every matching player, the same mass-effect shape
    `DealDamageEffect.selector` uses for "~ deals N damage to each player".
    ``selector="event_player"`` (Sheoldred, the Apocalypse's "whenever an
    opponent draws a card, **they** lose 2 life.") resolves against
    whoever the *firing event itself* names (`_event_player`, the same
    "that player" idiom `DealDamageEffect.selector` already uses for a
    damage trigger) rather than this ability's controller.

    Like `GainLifeEffect`, the plain (no-selector) path never falls back to
    a shared ``targets`` list — this effect declares no `target_spec` of
    its own, so any ``targets`` passed to `apply` belong to a *different*
    effect in the same chain (Infernal Grasp's "Destroy target creature.
    You lose 2 life.", Deathrite Shaman's exile-then-drain ability, …).
    """

    def __init__(
        self,
        amount: int = 0,
        player: Any = None,
        selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        player_id: Optional[str] = None,
        amount_from_trigger_event: Optional[str] = None,
        amount_from_life_gained_this_turn: bool = False,
        amount_from_burden_counters_on_self: bool = False,
        amount_from_count_selector: Optional[str] = None,
        amount_from_spells_cast_this_turn: bool = False,
        amount_from_half_own_life: bool = False,
        amount_from_half_target_life: bool = False,
        amount_from_damage_dealt_this_turn: bool = False,
        previous_subject: bool = False,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        #: "Target player loses life equal to the damage already dealt to
        #: that player this turn." (Final Punishment, MEC-43) — reads
        #: `GameState.damage_dealt_to_players_this_turn` for whichever
        #: player this effect resolves against, the exact same "resolve
        #: the target first, then read state off it" shape
        #: ``amount_from_half_target_life`` uses just below.
        self.amount_from_damage_dealt_this_turn = amount_from_damage_dealt_this_turn
        #: "Target player draws cards… **and loses** half their life."
        #: (MEC-43 round 2, Peer into the Abyss) — the same player
        #: `DrawCardEffect`'s own target requirement already picked
        #: (`GameContext.previous_targets`, the "It fights…"/"Tap target
        #: land. It doesn't untap…" pronoun idiom `FightEffect`/
        #: `GrantUntilEffect` already use), not a second RULE 115 target of
        #: this effect's own — the real card only ever targets once.
        self.previous_subject = previous_subject
        #: "You lose half your life, rounded up." (MEC-37, Doomsday) —
        #: reads this effect's own controller's *current* life total at
        #: resolution (RULE 107.3 rounds up), independently of the
        #: selector/target resolution below since the real card never
        #: prints one — always the caster themself.
        self.amount_from_half_own_life = amount_from_half_own_life
        #: "Target player… loses half their life. Round up." (MEC-43
        #: round 2, Peer into the Abyss) — the *targeted* sibling of
        #: ``amount_from_half_own_life`` above: reads whichever player the
        #: ordinary target/``player``/controller resolution below picks,
        #: not always the caster.
        self.amount_from_half_target_life = amount_from_half_target_life
        #: "…each opponent loses life equal to the number of tapped
        #: creatures you control." (Throne of the God-Pharaoh) — a live
        #: `continuous.count_selector` read, scoped to this effect's own
        #: controller regardless of which player ends up losing the life
        #: (unlike `PumpEffect.amount_from_count_selector`'s board-wide
        #: reads, this one is always "you", matching every printed card
        #: of this shape).
        self.amount_from_count_selector = amount_from_count_selector
        #: "Whenever a player casts a spell, they lose 1 life for each
        #: spell they've cast this turn." (Rug of Smothering) — unlike
        #: ``amount_from_count_selector`` above (always "you", the
        #: ability's own controller), this reads `GameState.
        #: spells_cast_this_turn` for the *casting* player named by the
        #: firing `SPELL_CAST` event (``selector="event_player"``'s own
        #: ``_event_player`` lookup), including the cast that triggered
        #: this ability — `RulesEngine._track_spell_cast` increments the
        #: counter before triggers are collected off the same event.
        self.amount_from_spells_cast_this_turn = amount_from_spells_cast_this_turn
        self.player = player
        #: "…you lose 1 life for each burden counter on The One Ring."
        #: Reads `GameObject.counters["burden"]` on this effect's own
        #: source, the `LoseLifeEffect` sibling of `DrawCardEffect`'s
        #: ``"burden_counters_on_self"`` count selector.
        self.amount_from_burden_counters_on_self = amount_from_burden_counters_on_self
        #: A specific player named by *id* rather than by object — the only
        #: form a serialized `EffectSpec` can carry (Professor Onyx's
        #: per-opponent "if you don't, they lose 3 life" branch, built fresh
        #: at answer time from spec data).
        self.player_id = player_id
        self.selector = selector
        # "Target player … loses 2 life" (Sign in Blood-shaped, sharing its
        # target with a sibling `DrawCardEffect` on the same spell) — opt-in
        # only, so every existing untargeted/selector caller keeps reading
        # no shared ``targets`` list at all (see the class docstring).
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        #: "Whenever you gain life, target opponent loses that much life."
        #: (Sanguine Bond-shaped) — the event field name (``"amount"``) to
        #: read off `GameContext.trigger_event` at resolution, the same
        #: "read this firing's own payload" idiom `AddManaEffect.
        #: amount_from_trigger_event` uses. Overrides ``amount`` when set.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "…loses life equal to the amount of life you gained this turn."
        #: (Gollum, Obsessed Stalker) — `GameState.life_gained_this_turn`,
        #: a *cumulative-this-turn* total rather than one firing's payload,
        #: so unlike `amount_from_trigger_event` this reads state, not the
        #: triggering event.
        self.amount_from_life_gained_this_turn = amount_from_life_gained_this_turn

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def _resolve_pre_selector_player(
        self, context: GameContext, targets: Optional[list[Any]] = None,
    ) -> Any:
        """The ``self.player -> player_id -> previous_subject ->
        target_spec -> controller`` prefix shared by
        ``amount_from_half_target_life``/``amount_from_damage_dealt_this_
        turn`` below (each needs to know *whose* life to read before
        `context.lose_life` itself is ever called) — identical to, but a
        strict prefix of, this `apply`'s own final player resolution just
        below, which layers three more selector-based fallbacks (``"defending_
        player"``/``"event_player"``/``"active_player"``) onto the same
        chain before its own controller fallback. Not folded into that
        richer chain, or into `GameEffect._resolve_target_or_controller`
        (a plainer 3-step chain neither of this class's own chains matches)
        — this is `LoseLifeEffect`'s own shape.
        """
        player = self._operand_player(context, targets, self.player) or (
            None if isinstance(self.player, (str, dict)) else self.player
        )
        if player is None and self.player_id is not None:
            player = context.state.player_by_id(self.player_id)
        if player is None and self.previous_subject and context.previous_targets:
            player = context.previous_targets[0]
        if player is None and self.target_spec is not None and targets:
            player = targets[0]
        if player is None:
            player = _controller_of(self.source, context)
        return player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        def _from_life_gained_this_turn() -> int:
            player = _controller_of(self.source, context)
            return context.state.life_gained_this_turn.get(getattr(player, "id", None), 0)

        def _from_count_selector() -> int:
            from .. import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            return continuous.count_selector(
                context.state, controller_id, self.amount_from_count_selector, source=self.source,
            )

        def _from_spells_cast_this_turn() -> int:
            caster = _event_player(context, key="player_id")
            count = context.state.spells_cast_this_turn.get(getattr(caster, "id", None), 0)
            return self.amount * count

        def _from_half_own_life() -> int:
            controller = _controller_of(self.source, context)
            life = getattr(controller, "life", 0)
            return -(-life // 2)  # ceiling division (RULE 107.3 rounds up)

        def _from_half_target_life() -> int:
            # Resolved the same way the ordinary (no-amount-selector) path
            # below picks its player — this just needs to know *before*
            # `context.lose_life` which player's life to read.
            target_player = self._resolve_pre_selector_player(context, targets)
            life = getattr(target_player, "life", 0)
            return -(-life // 2)  # ceiling division (RULE 107.3 rounds up)

        def _from_damage_dealt_this_turn() -> int:
            # Same "resolve the target first" shape as
            # ``amount_from_half_target_life`` just above.
            target_player = self._resolve_pre_selector_player(context, targets)
            return context.state.damage_dealt_to_players_this_turn.get(
                getattr(target_player, "id", None), 0
            )

        amount = self._resolve_amount_override(
            self.amount,
            [
                (
                    bool(self.amount_from_trigger_event),
                    lambda: int((context.trigger_event or {}).get(self.amount_from_trigger_event) or 0),
                ),
                (self.amount_from_life_gained_this_turn, _from_life_gained_this_turn),
                (
                    self.amount_from_burden_counters_on_self,
                    lambda: int((getattr(self.source, "counters", None) or {}).get("burden", 0)),
                ),
                (bool(self.amount_from_count_selector), _from_count_selector),
                (self.amount_from_spells_cast_this_turn, _from_spells_cast_this_turn),
                (self.amount_from_half_own_life, _from_half_own_life),
                (self.amount_from_half_target_life, _from_half_target_life),
                (self.amount_from_damage_dealt_this_turn, _from_damage_dealt_this_turn),
            ],
        )
        if amount <= 0:
            return
        if self.selector in _LOSE_LIFE_SELECTORS:
            controller_id = getattr(self.source, "controller_id", None)
            for p in context.state.living_players():
                if self.selector == "each_opponent" and p.id == controller_id:
                    continue
                context.lose_life(p, amount)
            return
        player = self._operand_player(context, targets, self.player) or (
            None if isinstance(self.player, (str, dict)) else self.player
        )
        if player is None and self.player_id is not None:
            player = context.state.player_by_id(self.player_id)
        if player is None and self.previous_subject and context.previous_targets:
            player = context.previous_targets[0]
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None and self.selector == "defending_player":
            player = _defending_player_of(self.source, context)
        if player is None and self.selector == "event_player":
            player = _event_player(context, key="player_id")
        if player is None and self.selector == "counter_recipient_controller":
            # "…its controller loses 1 life." (Auntie Ool) — the player
            # controlling the creature the firing `EventType.COUNTER`'s
            # counters went on.
            player = _event_player(context, key="recipient_controller_id")
        if player is None and self.selector == "attached_permanent_controller":
            # "Whenever enchanted creature attacks, its controller loses N
            # life." (Parasitic Impetus / Sinister Possession) — "its" is
            # the enchanted creature (RULE 303.4c); read the host live off
            # this Aura's own `attached_to`, then its current controller.
            host_id = getattr(self.source, "attached_to", None)
            host = context.state.find_object(host_id) if host_id is not None else None
            host_controller = getattr(host, "controller_id", None)
            if host_controller is not None:
                try:
                    player = context.state.player_by_id(host_controller)
                except (KeyError, ValueError):
                    player = None
        if player is None and self.selector == "active_player":
            # "At the beginning of each player's draw step, that player
            # loses 3 life…" (MEC-43 round 4F — Maralen of the Mornsong) —
            # the unscoped-trigger idiom `ExileTopOfLibraryEffect`'s own
            # ``player_selector="active_player"`` already uses (only the
            # active player ever has a draw step, so an unnarrowed "at the
            # beginning of the draw step" trigger fires once per turn, for
            # whoever that is); same sentinel `DealDamageEffect.selector`
            # already recognizes.
            player = context.state.active_player
        if player is None:
            player = _controller_of(self.source, context)
        context.lose_life(player, amount)


class AddPlayerCountersEffect(GameEffect):
    """"[Player] get[s] N [kind] counters." (RULE 122 — only "rad", RULE
    728, in practice today) — the oracle-text-facing sibling of
    `RulesEngine.add_player_counters`. Same target_kind/selector split as
    `GainLifeEffect`/`LoseLifeEffect`: untargeted (the effect's controller)
    by default, ``target_kind="player"`` for a real RULE 115 target, or
    ``selector="each_player"``/``"each_opponent"``/``"defending_player"``
    for a mass/combat-relative recipient.

    ``selector="defending_player"`` resolves against the *attacking*
    object, which for an Aura/Equipment-hosted "whenever enchanted/equipped
    creature attacks, defending player gets ~" ability (Acquired Mutation)
    is ``self.source``'s *host*, not the Aura/Equipment itself — only the
    actual attacker gets `combat_defender` stamped on it by
    `declare_attackers` (RULE 506.4). Resolved here rather than widening
    the shared `_defending_player_of` helper, since every existing caller
    (afflict) is already the attacking creature itself.
    """

    def __init__(
        self,
        amount: Any = 0,
        kind: str = "rad",
        player: Any = None,
        selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.kind = kind
        self.player = player
        self.selector = selector
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector in ("each_player", "each_opponent"):
            controller_id = getattr(self.source, "controller_id", None)
            for p in context.state.living_players():
                if self.selector == "each_opponent" and p.id == controller_id:
                    continue
                context.add_player_counters(p, self.amount, self.kind, source=self.source)
            return
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None and self.selector == "defending_player":
            host = self.source
            attached_to = getattr(host, "attached_to", None)
            if attached_to is not None:
                resolved = context.state.find_object(attached_to)
                if resolved is not None:
                    host = resolved
            player = _defending_player_of(host, context)
        if player is None:
            player = _controller_of(self.source, context)
        if player is not None:
            context.add_player_counters(player, self.amount, self.kind, source=self.source)


class LoseAllPlayerCountersEffect(GameEffect):
    """"[Player] loses all [kind] counters." (RULE 122's removal sibling —
    Survivor's Med Kit's "Target player loses all rad counters.") Reads the
    live count at apply time and removes exactly that many via
    `RulesEngine.add_player_counters`'s existing non-positive-amount path
    (bypasses RULE 616.1 replacements, same as any other counter removal).
    """

    def __init__(
        self,
        kind: str = "rad",
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        if player is None:
            return
        current = player.counters.get(self.kind, 0)
        if current > 0:
            context.add_player_counters(player, -current, self.kind, source=self.source)


class SacrificeEffect(GameEffect):
    """A player sacrifices up to ``count`` permanents matching ``what``
    (RULE 701.17) — untargeted; a real RULE 601.2c-style choice via
    `RulesEngine.sacrifice`/`_request_choose_objects`, not an auto-pick
    (`GameEngine._sacrifice_candidate`'s non-interactive convention is a
    *cost*-payment concern, a synchronous call that can't pause for a
    chooser — this is an effect resolving, which can).

    ``selector="defending_player"`` (annihilator, RULE 702.86) resolves the
    player dynamically at apply-time, the same way `LoseLifeEffect` does;
    ``selector="each_opponent"`` runs the sacrifice once per opponent
    (Professor Onyx's −3).

    ``greatest_power`` narrows the choice to "a creature with the greatest
    power among creatures that player controls" (Professor Onyx again) —
    still an auto-pick (`max()`) among the tied leaders rather than routed
    through the chooser, since only a tie among several actually leaves
    anything to decide and no shipped card sacrifices more than one this
    way (recomputing "greatest" between interactive picks isn't modeled).
    """

    def __init__(
        self,
        count: "int | str" = 1,
        what: str = "permanent",
        player: Any = None,
        selector: Optional[str] = None,
        greatest_power: bool = False,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        #: An int, or the ``"all_but_one"`` sentinel (`RulesEngine.sacrifice`
        #: resolves it against the live candidate count at apply-time).
        self.count = count
        self.what = what
        self.player = player
        self.selector = selector
        self.greatest_power = greatest_power
        #: ``target_kind="player"`` ("target player sacrifices a creature of
        #: their choice" — Diabolic Edict, and villainous/vote option bodies,
        #: ENG-33) opts into a real RULE 115 player target, exactly as
        #: `DiscardEffect`/`GainLifeEffect` do. Without a declared
        #: `target_spec` this effect keeps its untargeted `targets[0]`-when-
        #: present convention (villainous choice passes `targets=[facing]`).
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    #: A resumed continuation's own remaining-players list (see
    #: `_sacrifice_each_in_order`) — never set by a parsed `EffectSpec`
    #: (outside the whitelisted-param security boundary on purpose: this is
    #: pure runtime state, constructed only by this class itself), only by
    #: this class re-scheduling its own remainder.
    _remaining_players: Optional[list["Player"]] = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._remaining_players is not None:
            self._sacrifice_each_in_order(context, self._remaining_players)
            return
        if self.selector == "each_opponent":
            controller_id = getattr(self.source, "controller_id", None)
            players = [p for p in context.state.living_players() if p.id != controller_id]
            self._sacrifice_each_in_order(context, players)
            return
        if self.selector == "each_player":
            # RULE 601.2c mass edict — "each player sacrifices <what> of
            # their choice" (Accursed Marauder/Liliana, Dreadhorde General's
            # -4) — the `each_opponent` sibling that also includes the
            # ability's own controller.
            self._sacrifice_each_in_order(context, list(context.state.living_players()))
            return
        player = self.player or (targets[0] if targets else None)
        if player is None and self.selector == "controller":
            controller_id = getattr(self.source, "controller_id", None)
            player = context.state.player_by_id(controller_id) if controller_id is not None else None
        if player is None and self.selector == "defending_player":
            player = _defending_player_of(self.source, context)
        if player is None:
            return
        self._sacrifice_one(context, player)

    def _sacrifice_each_in_order(self, context: GameContext, players: list["Player"]) -> None:
        """`each_opponent`/`each_player` — one player's choice at a time.

        `context.sacrifice` opens a real `pending_choice` (RULE 601.2c)
        whenever a player has more matching permanents than ``count``.
        Looping every player synchronously in one `apply()` would silently
        overwrite an earlier player's still-unanswered prompt with a later
        one's — the game state holds exactly one `pending_choice` at a time
        (RULE 608.2, the same reason `_apply_effects_partitioned` parks a
        resolution's remaining *effects*; this is that same idiom one level
        down, for remaining *players* within a single effect). If a choice
        actually opened for this player and others remain, the rest are
        parked on `GameState.deferred_effects` as a fresh `SacrificeEffect`
        carrying just its own remaining-players list, resumed by
        `RulesEngine.resume_deferred_effects` once this one is answered.
        """
        state = context.state
        for i, player in enumerate(players):
            before = getattr(state, "pending_choice", None)
            self._sacrifice_one(context, player)
            opened = getattr(state, "pending_choice", None)
            if opened is not None and opened is not before and i + 1 < len(players):
                remainder = SacrificeEffect(
                    count=self.count, what=self.what, greatest_power=self.greatest_power,
                    source=self.source,
                )
                remainder._remaining_players = players[i + 1:]
                state.deferred_effects.append(
                    {
                        "effects": [remainder],
                        "targets": None,
                        "target_groups": None,
                        "group_index": 0,
                        "source": self.source,
                        "previous_targets": list(getattr(context, "previous_targets", [])),
                        "created_objects": list(getattr(context, "created_objects", [])),
                    }
                )
                return

    def _sacrifice_one(self, context: GameContext, player: "Player") -> None:
        if not self.greatest_power:
            context.sacrifice(player, self.what, self.count)
            return
        creatures = [
            o for o in context.state.permanents_controlled_by(player.id) if o.is_creature
        ]
        for _ in range(self.count):
            if not creatures:
                return
            victim = max(creatures, key=lambda o: o.power or 0)
            creatures.remove(victim)
            context.put_into_graveyard(victim)  # RULE 701.16c: sacrifice


class SacrificeSelfEffect(GameEffect):
    """"Sacrifice ~."/"Sacrifice this enchantment." (Dress Down/Underworld
    Breach-shaped standing end-step self-sac) — the effect's own source
    sacrifices itself, no player choice or RULE 115 target involved (RULE
    701.17). Uses `RulesEngine.put_into_graveyard` rather than `destroy`
    (RULE 701.16c: sacrifice isn't destruction, so it can't be regenerated),
    the same distinction `GameEngine._pay_activation_cost`'s own sacrifice
    cost-payment already makes.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.put_into_graveyard(self.source)


class SacrificeUnlessAttackedEffect(GameEffect):
    """"Sacrifice ~ unless it attacked this turn." (Instill Furor).

    This is an objective conditional consequence, not a payment choice:
    RULE 508's declaration path already records ``attacked_this_turn`` on
    the permanent, and that marker survives combat until cleanup.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None and not getattr(self.source, "attacked_this_turn", False):
            context.put_into_graveyard(self.source)


class HofriGhostforgeDiesEffect(GameEffect):
    """"Whenever another nontoken creature you control dies, exile it. If you
    do, create a token that's a copy of that creature, except it's a Spirit
    in addition to its other types and it has 'When this token leaves the
    battlefield, return the exiled card to its owner's graveyard.'" (Hofri
    Ghostforge, PAR-60.)

    Reads the firing DIES event's ``instance_id`` (the dead creature, now in
    its owner's graveyard), exiles it, and makes a token copy with Spirit
    added to its types (`RulesEngine.copy_permanent`'s ``add_subtypes``).
    Documented simplification: the "when this token leaves … return the
    exiled card to its owner's graveyard" rider is dropped — the reanimated
    Spirit copy is the effect's payoff.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        cid = getattr(self.source, "controller_id", None)
        iid = (context.trigger_event or {}).get("instance_id")
        if cid is None or iid is None:
            return
        dead = context.state.find_object(iid)
        if dead is None or dead.zone != Zone.GRAVEYARD:
            return
        context.exile(dead)
        context.engine.copy_permanent(cid, dead, 1, add_subtypes=["Spirit"])
        context.recompute()


class BrudicladCombatEffect(GameEffect):
    """"At the beginning of combat on your turn, create a 2/1 blue Phyrexian
    Myr artifact creature token. Then you may choose a token you control. If
    you do, each other token you control becomes a copy of that token."
    (Brudiclad, Telchor Engineer, PAR-60.)

    Makes the Myr, then opens an optional pick among the tokens this
    ability's controller controls; `brudiclad_become_copies` (its
    ``then_specs`` tail) turns every *other* token into a copy of the pick
    (RULE 707.2 permanent mutation via `RulesEngine.become_copy`).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import synthesize_token_card

        cid = getattr(self.source, "controller_id", None)
        if cid is None:
            return
        card = synthesize_token_card(
            "Myr", power=2, toughness=1, colors=["U"], subtypes=["Phyrexian", "Myr"],
        )
        card.type_line = "Artifact Creature — Phyrexian Myr"
        context.create_token(cid, card, 1)
        try:
            player = context.state.player_by_id(cid)
        except (KeyError, ValueError):
            return
        tokens = [
            o for o in context.state.permanents_controlled_by(cid)
            if getattr(o, "is_token", False)
        ]
        if len(tokens) < 2:
            return
        context.engine._request_choose_objects(
            player, tokens, "choose_permanent", count=1, optional=True,
            prompt="Brudiclad: einen Spielstein waehlen (andere werden zu Kopien)",
            source=self.source,
            then_specs=[{"type": "brudiclad_become_copies", "params": {}}],
        )


class BrudicladBecomeCopiesEffect(GameEffect):
    """``then_specs`` tail of `BrudicladCombatEffect`: every other token this
    ability's controller controls becomes a copy of ``source.chosen_
    permanent_id``."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        iid = getattr(self.source, "chosen_permanent_id", None)
        self.source.chosen_permanent_id = None
        chosen = context.state.find_object(iid) if iid is not None else None
        if chosen is None:
            return
        cid = getattr(self.source, "controller_id", None)
        for o in list(context.state.permanents_controlled_by(cid)):
            if getattr(o, "is_token", False) and o is not chosen:
                context.become_copy(o, chosen)
        context.recompute()


class SurgeToVictoryEffect(GameEffect):
    """"Exile target instant or sorcery card from your graveyard. Creatures
    you control get +X/+0 until end of turn, where X is that card's mana
    value. Whenever a creature you control deals combat damage to a player
    this turn, copy the exiled card. You may cast the copy without paying
    its mana cost." (Surge to Victory, PAR-60.)

    Documented simplification: the "copy the exiled card on combat damage"
    rider is dropped (no per-firing "copy a remembered exiled card" delayed
    trigger primitive) — the anthem (+X/+0 for the alpha strike) is the
    card's dominant effect and is kept.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="graveyard_instant_or_sorcery")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        card_obj = targets[0] if targets else None
        if card_obj is None:
            return
        mv = int(getattr(card_obj.card, "converted_mana_cost", 0) or 0)
        context.exile(card_obj)
        if mv > 0:
            context.engine._apply_effect_specs(
                [{"type": "pump", "params": {
                    "power": mv, "toughness": 0, "selector": "creatures_you_control",
                }}],
                self.source,
            )


class RedoubledStormsingerCopiesEffect(GameEffect):
    """"Whenever this creature attacks, for each creature token you control
    that entered this turn, create a tapped and attacking token that's a
    copy of that token." (Redoubled Stormsinger, PAR-60.)

    Each copy is appended to `GameContext.created_objects` so a following
    ``create_delayed_trigger`` with ``capture="created_objects"`` +
    ``sacrifice_specific`` picks them up for the "sacrifice those tokens at
    the beginning of the next end step" clause.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        cid = getattr(self.source, "controller_id", None)
        if cid is None:
            return
        turn = context.state.internal_turn.number
        originals = [
            o for o in context.state.permanents_controlled_by(cid)
            if o.is_creature and getattr(o, "is_token", False) and o is not self.source
            and getattr(o, "turn_entered", None) == turn
        ]
        for tok in originals:
            for copy in context.engine.copy_permanent(cid, tok, 1) or []:
                context.set_tapped(copy, tapped=True)
                context.engine.put_onto_battlefield_attacking(copy)
                context.created_objects.append(copy)
        context.recompute()


class OversimplifyEffect(GameEffect):
    """"Exile all creatures. Each player creates a 0/0 green and blue Fractal
    creature token and puts a number of +1/+1 counters on it equal to the
    total power of creatures they controlled that were exiled this way."
    (Oversimplify, PAR-60.)

    Per-player power totals are snapshotted before the exile (RULE 400.7),
    then one Fractal token per player gets that many +1/+1 counters.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import synthesize_token_card

        totals: dict[str, int] = {}
        creatures = [o for o in list(context.state.battlefield) if o.is_creature]
        for o in creatures:
            pid = o.controller_id
            if pid is not None:
                totals[pid] = totals.get(pid, 0) + max(0, int(o.power or 0))
        for o in creatures:
            context.exile(o)
        for player in list(context.state.players):
            card = synthesize_token_card(
                "Fractal", power=0, toughness=0, colors=["G", "U"], subtypes=["Fractal"],
            )
            made = context.create_token(player.id, card, 1)
            n = totals.get(player.id, 0)
            for tok in made or []:
                if n > 0:
                    context.add_counters(tok, n, "+1/+1", source=self.source)
        context.recompute()


class TragicArroganceEffect(GameEffect):
    """"For each player, you choose from among the permanents that player
    controls an artifact, a creature, an enchantment, and a planeswalker.
    Then each player sacrifices all other nonland permanents they control."
    (Tragic Arrogance, PAR-60.)

    Documented simplification: the caster's per-(player, type) choice is
    auto-resolved rather than interactive — keep the **highest** mana value
    of each type among the caster's own permanents, and the **lowest** of
    each type among every opponent's (the strategic intent: keep your best,
    leave them their worst). Every other nonland permanent is sacrificed.
    """

    _TYPE_WORDS = ("artifact", "creature", "enchantment", "planeswalker")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        caster_id = getattr(self.source, "controller_id", None)
        for player in list(context.state.players):
            perms = [
                o for o in context.state.permanents_controlled_by(player.id)
                if not o.is_land
            ]
            keep: set[int] = set()
            want_high = player.id == caster_id
            for word in self._TYPE_WORDS:
                of_type = [
                    o for o in perms
                    if word in (o.card.type_line or "").lower()
                ]
                if not of_type:
                    continue
                pick = (max if want_high else min)(
                    of_type,
                    key=lambda o: int(getattr(o.card, "converted_mana_cost", 0) or 0),
                )
                keep.add(pick.instance_id)
            for o in perms:
                if o.instance_id not in keep:
                    context.put_into_graveyard(o)


class SacrificeUnlessPayEffect(GameEffect):
    """"Sacrifice ~ unless you pay `<cost>`." (RULE 701.17 + an "unless"
    payment) — the single most common upkeep-trigger body on old cards
    (Arcades Sabboth, Breeding Pit, Child of Gaea, Kuro; Aura Flux/Coral Net
    grant it onto another permanent).

    ``cost`` is the printed cost *text* ("{G}{G}", "1 life", "a card"),
    parsed by `costs.parse_activation_cost` at resolution into the same
    `ActivationCost` an activated ability's cost uses — that's what makes
    the whole real vocabulary these cards print (mana / pay N life /
    discard a card / sacrifice another permanent) work without a bespoke
    cost model. Resolution itself is `RulesEngine.request_sacrifice_unless_
    pay`, which reuses ward's pay-or-lose-it choice machinery.
    """

    def __init__(
        self, cost: str = "", source: Optional["GameObject"] = None,
        target: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")
        #: "…sacrifice **it** unless you pay `<cost>`." naming a *different*
        #: permanent than this ability's own source (Ashling, the
        #: Limitless, MEC-42 — the token its own sacrifice trigger just
        #: made, not Ashling itself) — filled in by `CreateDelayedTrigger
        #: Effect`'s ``capture="created_objects"`` the same way it already
        #: fills `SacrificeSpecificEffect.target`-shaped effects; falls
        #: back to ``source`` (every existing caller's own shape) when unset.
        self.target = target

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        subject = self.target or self.source
        if subject is None:
            return
        player = _controller_of(subject, context)
        if player is None:
            return
        # "Sacrifice this creature unless you pay its mana cost" (Pendrell
        # Flux) prices the payment from the permanent currently bearing the
        # ability, not the Aura that granted it.  The source is exactly that
        # grantee after layer-6 regranting; `target` remains the explicit
        # delayed-trigger override, so prefer it when present.
        cost_text = self.cost_text
        if cost_text == "source_mana_cost":
            cost_text = getattr(subject.card, "mana_cost_string", "")
        cost = parse_activation_cost(cost_text)
        if cost.is_free:
            # `parse_activation_cost` returns a *free* cost for text it
            # doesn't recognize rather than raising. Honouring that here
            # would silently mean "pay nothing to keep it" — do nothing at
            # all instead. (The parser front end only claims cost shapes it
            # can express, so this is a belt-and-braces guard for a
            # hand-authored entry, not a path real oracle text reaches.)
            return
        context.engine._request_sacrifice_unless_pay(player, cost, subject)


class DestroyUnlessPayEffect(GameEffect):
    """"Destroy ~ unless you pay `<cost>`." (RULE 701.16 + an "unless"
    payment) — the real-destruction sibling of `SacrificeUnlessPayEffect`
    above (The Tabernacle at Pendrell Vale's mass granted upkeep trigger,
    "All creatures have 'At the beginning of your upkeep, destroy this
    creature unless you pay {1}.'"). Kept a distinct effect/verb rather than
    a shared "unless pay" flag: RULE 701.16c means destruction (unlike
    sacrifice) still runs through the replacement-effect pass, so a
    regeneration shield can save the permanent — `RulesEngine.request_
    destroy_unless_pay` calls `destroy`, not `put_into_graveyard`.

    ``cost`` is the printed cost text, resolved the same way as
    `SacrificeUnlessPayEffect`.
    """

    def __init__(
        self, cost: str = "", source: Optional["GameObject"] = None,
        target: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")
        #: See `SacrificeUnlessPayEffect.target` — falls back to ``source``.
        self.target = target

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        subject = self.target or self.source
        if subject is None:
            return
        player = _controller_of(subject, context)
        if player is None:
            return
        cost = parse_activation_cost(self.cost_text)
        if cost.is_free:
            # See `SacrificeUnlessPayEffect.apply`'s matching guard.
            return
        context.engine._request_destroy_unless_pay(player, cost, subject)


class TaxedDrawEffect(GameEffect):
    """"Whenever an opponent casts a spell, you may draw a card unless that
    player pays `<cost>`." (RULE 118.3's "unless" idiom applied to a draw
    rather than a sacrifice/counter — Rhystic Study/Mystic Remora/Esper
    Sentinel-shaped taxes).

    The *payer* is the triggering spell's own caster — read off the firing
    event's ``player_id`` (`GameContext.trigger_event`), not this ability's
    controller — so this only makes sense on a trigger whose condition
    already scopes the firing event to an opponent (``"controller":
    "not_you"``). Reuses `_request_pay_cost_then`'s pay-or-lose-it machinery
    exactly like `SacrificeUnlessPayEffect` does: paying does nothing,
    declining (or being unable to pay) draws a card for this ability's own
    controller (`DrawCardEffect`'s untargeted default).

    ``amount_from_source_power`` (Esper Sentinel: "unless that player pays
    {X}, where X is this creature's power") reads the cost's amount off the
    source's own live power instead of a fixed printed value.
    """

    def __init__(
        self,
        cost: str = "",
        amount_from_source_power: bool = False,
        count: int = 1,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")
        self.amount_from_source_power = amount_from_source_power
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        source = self.source
        if source is None:
            return
        event = context.trigger_event or {}
        payer_id = event.get("player_id")
        payer = None
        for p in context.state.players:
            if p.id == payer_id:
                payer = p
                break
        if payer is None:
            return
        cost_text = self.cost_text
        if self.amount_from_source_power:
            power = getattr(source, "power", 0) or 0
            cost_text = "{" + str(power) + "}"
        cost = parse_activation_cost(cost_text)
        if cost.is_free:
            return
        context.engine._request_pay_cost_then(
            payer, cost, [], source,
            else_effect_specs=[{"type": "draw", "params": {"count": self.count}}],
        )


class EachPlayerPayOrEffect(GameEffect):
    """RULE 101.4's APNAP mass "unless" (PAR-13 — "Each player loses N life
    unless they discard a card."/"...unless they sacrifice a creature,
    artifact, or land of their choice." — Bellowing Mauler/Lim-Dûl's Hex/
    Tomb of Annihilation's own two dungeon rooms), the *mass* sibling of
    `SacrificeUnlessPayEffect`: every living player is asked in turn order,
    and ``effects`` lands on whoever doesn't (or can't) pay — never the
    ability's own controller, unlike that class's single fixed subject.

    ``cost`` is printed cost text exactly like `SacrificeUnlessPayEffect`'s
    own; ``effects`` are serialized `EffectSpec` dicts applied with the
    declining player as the sole target (`RulesEngine.
    _request_each_player_pay_or` passes ``targets=[player]`` through to
    `_request_pay_cost_then`), so a spec here should carry a matching
    ``target_kind`` (``"player"`` for `lose_life`/`discard`/etc.) rather
    than relying on an untargeted default.
    """

    def __init__(
        self,
        cost: str = "",
        effects: Optional[list[dict[str, Any]]] = None,
        scope: str = "each_player",
        effect_targets: str = "decliner",
        sacrifice_or_discard: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")
        self.inner_specs = list(effects or [])
        #: "…unless they discard a card **or** sacrifice a creature."
        #: (Polygraph Orb) — the OR form of the mass cost, ORed onto the
        #: parsed `ActivationCost` at resolve time (`sacrifice_or_discard`),
        #: same as `PayCostThenEffect`'s own knob, since the plain regex
        #: cost parser AND-combines its fragments.
        self.sacrifice_or_discard = bool(sacrifice_or_discard)
        #: "…**for each opponent**, `<effect>` unless that player
        #: `<pays>`." (MEC-43, Acererak the Archlich) — ``"each_player"``
        #: (default, every existing caller's shape) asks every living
        #: player including this ability's own controller; ``"each_
        #: opponent"`` excludes the controller from the sweep entirely.
        self.scope = scope
        #: Who ``effects`` targets when a player doesn't (or can't) pay:
        #: ``"decliner"`` (default) is every existing caller's shape — the
        #: player who declined. ``"controller"`` is Acererak's own "**you**
        #: create a token" — the effect lands on this ability's controller
        #: regardless of which opponent declined, so no ``targets`` are
        #: threaded through and each inner spec resolves against its own
        #: untargeted controller default instead.
        self.effect_targets = effect_targets

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        cost = parse_activation_cost(self.cost_text)
        if self.sacrifice_or_discard:
            cost.sacrifice_or_discard = True
        if cost.is_free:
            return  # see SacrificeUnlessPayEffect's identical guard
        context.engine._request_each_player_pay_or(
            cost, self.inner_specs, self.source,
            scope=self.scope, effect_targets=self.effect_targets,
        )



register(globals())
