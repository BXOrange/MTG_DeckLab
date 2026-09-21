"""Choices, voting, keyword actions, combat, and player-turn effects."""
from __future__ import annotations

from .core import GameEffect
from ._runtime import install, register

install(globals())

class AddManaEffect(GameEffect):
    """Add mana straight to the effect's controller's pool (RULE 106.4) — a
    spell's own bare "Add {B}{B}{B}." resolve-time body (Dark Ritual-shaped),
    as opposed to a permanent's mana ability (`game/mana_abilities.py`,
    tapped for mana outside the stack entirely, never a resolve-time effect).
    Also covers a *targeted* activated ability's own "Add one mana of any
    color" body (Deathrite Shaman's graveyard-exile abilities) — RULE 605.1a
    excludes anything that targets from ever being a `mana_abilities.py`
    mana ability at all, so that shape can only ever resolve here.

    ``colors`` is one WUBRGC letter per mana symbol printed, in the order
    printed, or the sentinel ``"ANY"`` for "one mana of any color" — a
    genuine player decision, opened as an interactive `add_mana_any_color`
    `pending_choice` (`RulesEngine.add_mana_any_color`/`resolve_add_mana_
    any_color_choice`) rather than guessed at. Untargeted (mana itself
    can't be targeted, RULE 106.4 — unrelated to whatever cost the
    ability/spell producing it might target).
    """

    def __init__(
        self,
        colors: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
        amount: Optional[int] = None,
        color: str = "C",
        amount_selector: Optional[str] = None,
        amount_from_trigger_event: Optional[str] = None,
        recipient: str = "controller",
        target_kind: Optional[str] = None,
        amount_from_target_hand_size: bool = False,
        amount_from_target_count_selector: Optional[str] = None,
        once_per_turn_ability: bool = False,
        color_from_source_chosen_color: bool = False,
        color_from_source_noted_color: bool = False,
        any_color_choices: Optional[list[str]] = None,
        any_amount_from_context: Optional[str] = None,
        amount_from_context: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        #: "Add X mana in any combination of {B} and/or {G}." (Culling
        #: Ritual, MEC-40) — narrows the ``colors=["ANY"]`` offer to this
        #: fixed set instead of all five WUBRG, mirroring `add_mana_any_
        #: color`'s own ``colors`` narrowing (Kinnan's "any type **that
        #: permanent produced**"). **Documented simplification**: the real
        #: card lets the caster split the total across *both* colours
        #: independently, mana by mana (RULE 106.1); this offers one colour
        #: choice for the whole amount instead — no "how many of each"
        #: interactive shape exists yet (`add_mana_any_color`'s own
        #: `pending_choice` is a single categorical pick, not a per-unit
        #: split). Still fully usable mana, just less flexible than printed.
        self.any_color_choices = list(any_color_choices) if any_color_choices else None
        #: The `GameContext` accumulator name to size the ``"ANY"`` amount
        #: from instead of `amount_from_target_count_selector` — Culling
        #: Ritual's "for each permanent destroyed this way" reads
        #: `GameContext.permanents_destroyed_this_way`, the same
        #: same-resolution-accumulator idiom `life_lost_this_way` already
        #: established.
        self.any_amount_from_context = any_amount_from_context
        #: "…adds an additional one mana of **the chosen color**." (Utopia
        #: Sprawl-shaped RULE 601.2b "as ~ enters, choose a color" Auras) —
        #: reads this effect's own source's `GameObject.chosen_color`
        #: (`RulesEngine._offer_enter_choices`'s existing ETB choice) fresh
        #: at apply time instead of a fixed `colors` list, so a later
        #: Replay/Puzzle-mode change to the choice is honoured too.
        self.color_from_source_chosen_color = color_from_source_chosen_color
        #: "Add one mana of this artifact's last noted type." (Jeweled
        #: Amulet, MEC-43) — the `noted_mana_color` sibling of
        #: `color_from_source_chosen_color` just above; reads `GameObject.
        #: noted_mana_color` fresh at apply time instead of a fixed
        #: ``colors`` list. Produces no mana at all if nothing has been
        #: noted yet (the card's own activation-order gate — "Activate
        #: only if there are no charge counters" on the noting ability —
        #: already guarantees a note exists before this one can fire).
        self.color_from_source_noted_color = color_from_source_noted_color
        #: "…add X mana of any one color, where X is the number of Islands
        #: **target opponent** controls" (ENG-27, Carpet of Flowers) — a
        #: `continuous.count_selector` evaluated for the *resolved target*
        #: (``targets[0].id``), not this effect's own controller the way
        #: ``amount_selector`` below always is. Only meaningful alongside
        #: ``colors=["ANY"]``; scales that colour's own amount instead of
        #: the fixed-``self.color`` slot.
        self.amount_from_target_count_selector = amount_from_target_count_selector
        #: "…if you haven't added mana with this ability this turn, you may
        #: add …" (Carpet of Flowers) — the effect's own source gets the
        #: `GameObject.added_mana_with_ability_this_turn` flag (reset each
        #: untap step); already-used-this-turn is a resolve-time no-op
        #: rather than a full RULE 603.4 intervening-if that keeps the
        #: trigger off the stack in the first place — the "you may" is
        #: still offered, it just does nothing if accepted anyway.
        self.once_per_turn_ability = once_per_turn_ability
        #: "Add {R} for each card in target opponent's hand." (Jeska's
        #: Will) — the one shape here that genuinely targets (RULE 601.2c
        #: opts this effect into a real `target_spec`, unlike every other
        #: untargeted form above); the produced amount is read off that
        #: resolved target's own hand size at resolution, not a board-wide
        #: `continuous.count_selector` scope.
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        self.amount_from_target_hand_size = amount_from_target_hand_size
        #: "add that much {R}" (MEC-11's Raphael, Ninja Destroyer, an
        #: Enrage sibling — "whenever ~ is dealt damage, add that much
        #: {R}") — the event field name (``"amount"``) to read off
        #: `GameContext.trigger_event` at resolution, `MirrorProducedManaEffect`'s
        #: "read this firing's own payload" idiom applied to a plain
        #: numeric amount instead of a produced-colour set. **Documented
        #: simplification**: Raphael's own trailing "until end of turn, you
        #: don't lose this mana as steps and phases end" isn't modeled —
        #: `ManaPool` has no persist-past-a-step mechanism yet — so this
        #: mana empties at the current step's end like any other (RULE
        #: 500.4), rather than lasting the rest of the turn.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: Who the mana goes to: ``"controller"`` (the effect's own source's
        #: controller — every ordinary case) or ``"event_controller"``, the
        #: player named by the triggering event (`GameContext.trigger_event`).
        #: Wild Growth needs the latter: "whenever enchanted land is tapped
        #: for mana, **its controller** adds an additional {G}" — the land's
        #: controller, who need not be the Aura's (RULE 110.2 lets those
        #: diverge under a control-change effect).
        self.recipient = recipient
        self.colors = [str(c).upper() for c in (colors or [])]
        # ``amount``/``color`` are the *variable-count* form ("add an amount of
        # {C} equal to that spell's mana value" — Mana Drain): a resolved count
        # of one colour, threaded through the same ``"x"`` sentinel
        # `RulesEngine._substitute_x` rewrites, instead of one letter per
        # printed symbol. Kept separate from ``colors`` so the fixed-symbol
        # form (Dark Ritual's "{B}{B}{B}") is unchanged.
        self.amount = amount
        self.color = str(color).upper()
        #: A `continuous.count_selector` name resolved *at resolution time*
        #: for the board-dependent form — "then add {R} for each card named ~
        #: in each graveyard" (Rite of Flame). Additive with ``colors``
        #: above, so Rite of Flame's flat "{R}{R}" and its per-copy bonus are
        #: one effect rather than two: ``colors=["R","R"]`` plus this.
        #: Distinct from ``amount`` (a value the *caller* already resolved).
        self.amount_selector = amount_selector
        #: "Add {C} for each charge counter removed this way." (Ventifact
        #: Bottle, PAR-66) — ``amount_selector``'s same-resolution-
        #: accumulator sibling: a `GameContext` attribute name
        #: (`counters_removed_this_way`) instead of a board-wide
        #: `continuous.count_selector`, the fixed-colour counterpart of
        #: ``any_amount_from_context`` (which only ever scales the
        #: ``colors=["ANY"]`` branch).
        self.amount_from_context = amount_from_context

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.recipient == "event_controller":
            player = _event_player(context)
        else:
            player = _controller_of(self.source, context)
        if player is None:
            return
        if self.once_per_turn_ability and getattr(
            self.source, "added_mana_with_ability_this_turn", False
        ):
            return
        used_this_turn = False
        colors = self.colors
        if self.color_from_source_chosen_color:
            chosen = getattr(self.source, "chosen_color", None)
            colors = [chosen] if chosen else []
        elif self.color_from_source_noted_color:
            noted = getattr(self.source, "noted_mana_color", None)
            colors = [noted] if noted else []
        for color in colors:
            if color == "ANY":
                any_amount = 1
                if self.amount_from_target_count_selector and targets:
                    from .. import continuous  # function-scoped: avoid an import cycle

                    target_player = targets[0]
                    any_amount = continuous.count_selector(
                        context.state, getattr(target_player, "id", None),
                        self.amount_from_target_count_selector, source=self.source,
                    )
                elif self.any_amount_from_context:
                    any_amount = int(getattr(context, self.any_amount_from_context, 0) or 0)
                elif self.amount_selector:
                    # "Add X mana in any combination of {B} and/or {R},
                    # where X is the sacrificed creature's mana value."
                    # (MEC-43, Burnt Offering) — the same `amount_selector`
                    # the fixed-``color`` branch below already reads,
                    # widened to also size the ``colors=["ANY"]`` amount
                    # (previously only ``amount_from_target_count_selector``/
                    # ``any_amount_from_context`` could).
                    from .. import continuous  # function-scoped: avoid an import cycle

                    any_amount = continuous.count_selector(
                        context.state, player.id, self.amount_selector, source=self.source
                    )
                if any_amount > 0:
                    context.add_mana_any_color(
                        player, colors=self.any_color_choices, amount=any_amount,
                    )
                    used_this_turn = True
            else:
                context.add_mana(player, color)
                used_this_turn = True
        if self.once_per_turn_ability and used_this_turn and self.source is not None:
            self.source.added_mana_with_ability_this_turn = True
        if isinstance(self.amount, int) and self.amount > 0:
            context.add_mana(player, self.color, self.amount)
        if self.amount_from_trigger_event:
            event = context.trigger_event
            extra = int((event or {}).get(self.amount_from_trigger_event) or 0)
            if extra > 0:
                context.add_mana(player, self.color, extra)
        if self.amount_selector:
            from .. import continuous  # function-scoped: avoid an import cycle

            extra = continuous.count_selector(
                context.state, player.id, self.amount_selector, source=self.source
            )
            if extra > 0:
                context.add_mana(player, self.color, extra)
        if self.amount_from_target_hand_size and targets:
            extra = len(getattr(targets[0], "hand", []) or [])
            if extra > 0:
                context.add_mana(player, self.color, extra)
        if self.amount_from_context:
            extra = int(getattr(context, self.amount_from_context, 0) or 0)
            if extra > 0:
                context.add_mana(player, self.color, extra)


def _mana_value_of(target: Any) -> int:
    """The mana value of a targeted spell (a `StackItem` or its `GameObject`
    or a `Card`) — for a delayed trigger capturing "that spell's mana value"
    (Mana Drain) at setup, before the spell leaves the game."""
    obj = getattr(target, "obj", None) or target
    card = getattr(obj, "card", None) or obj
    return int(getattr(card, "converted_mana_cost", 0) or 0)


class CreateDelayedTriggerEffect(GameEffect):
    """Arm a delayed triggered ability (RULE 603.7) at resolution — "at the
    beginning of your next <step>, <effect>." (Mana Drain, the Pacts, Final
    Fortune, Corpse Dance).

    ``step`` is the step-name it waits for (``"upkeep"``/``"main1"``/
    ``"end"``/…); ``scope`` is ``"controller"`` (that controller's next such
    step) or ``"any"`` (the very next one). ``effects`` is a list of
    whitelisted ``{"type", "params"}`` effect descriptors built into live
    one-shot effects here (through the same `effect_binder.build_effects`
    whitelist as any other effect — nothing from card text escapes it) and
    stashed on `GameState.delayed_triggers`; `GameEngine._fire_delayed_
    triggers` places them on the stack when the step arrives.

    ``capture`` reads a dynamic value from this effect's own resolution and
    bakes it into the delayed effects: ``"target_mana_value"`` substitutes the
    ``"x"`` amount/count sentinel with the targeted spell's mana value (Mana
    Drain's "add an amount of {C} equal to that spell's mana value") — captured
    now, since the spell is gone by the time the delayed ability fires.

    ``description`` is a human-readable label for the UI's "planned"
    delayed-trigger panel (`DelayedTrigger.to_dict()`) — e.g. "Mana Drain:
    {C} in Höhe der Manakosten hinzufügen". Optional (defaults to empty);
    hand-authored specs should still set one so the panel isn't blank.
    """

    def __init__(
        self,
        step: str,
        effects: Optional[list[dict[str, Any]]] = None,
        scope: str = "controller",
        capture: Optional[str] = None,
        min_turn_offset: int = 0,
        description: str = "",
        condition: Optional[dict[str, Any]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.step = str(step)
        self.inner_specs = list(effects or [])
        self.scope = str(scope)
        self.capture = capture
        # ``min_turn_offset`` arms the trigger to fire no earlier than
        # ``internal_turn.number + offset`` — 1 makes "at the beginning of *that*
        # (extra) turn's end step" (Final Fortune) skip the *current* turn's
        # end step, which would otherwise be the very next one.
        self.min_turn_offset = int(min_turn_offset)
        self.description = str(description)
        #: RULE 603.4 intervening-if on the *whole* delayed ability — "at the
        #: beginning of the next end step, exile that token **unless ~ is
        #: your Ring-bearer**" (Sauron, the Necromancer). A whitelisted
        #: `EffectSpec.condition`-shaped dict (`_ALLOWED_CONDITION_KEYS`),
        #: re-checked by `_fire_delayed_triggers` when the delayed ability
        #: would go on the stack; if it doesn't hold, the ability simply
        #: doesn't trigger. Distinct from a `condition` on an *inner* spec
        #: (which `build_effects` wraps in `ConditionalEffect`, checked at
        #: resolution) — this one gates the firing itself, which is what an
        #: "…unless <X>" rider on the delayed instruction wants.
        from ...parser.oracle.spec import _ALLOWED_CONDITION_KEYS

        self.condition = (
            {k: v for k, v in condition.items() if k in _ALLOWED_CONDITION_KEYS}
            if condition else None
        ) or None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
        from ...parser.oracle.spec import EffectSpec
        from ...models.game.game_state import DelayedTrigger

        inner = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in self.inner_specs],
            self.source,
        )
        if self.capture == "target_mana_value" and targets:
            captured = _mana_value_of(targets[0])
            for effect in inner:
                for attr in ("amount", "count"):
                    if getattr(effect, attr, None) == "x":
                        setattr(effect, attr, captured)
        if self.capture == "created_objects":
            # "…Sacrifice it at the beginning of the next end step."
            # (Kiki-Jiki, Mirror Breaker) / "…exile it." (Puppeteer
            # Clique) — "it" names whatever *this same resolution* just
            # created/returned (RULE 608.2's referent, `GameContext.
            # created_objects`), not a fresh RULE 115 target — baked
            # directly into the delayed effect the same way as every other
            # capture here, since the object has to survive until the
            # delayed firing without being re-chosen.
            made = list(context.created_objects)
            for effect in inner:
                if hasattr(effect, "objects"):
                    effect.objects = made
                elif hasattr(effect, "exiled_object") and made:
                    # "…Put that card into your hand at the beginning of
                    # your next end step." (MEC-38, Necropotence) —
                    # `ReturnUncastExiledEffect.exiled_object`, the same
                    # single-object capture `.target` gets just below,
                    # named differently since this effect already uses
                    # `.target`-shaped semantics for something else (RULE
                    # 608.2's referent here is specifically "the card *this
                    # same resolution* just exiled").
                    effect.exiled_object = made[0]
                elif hasattr(effect, "target") and made:
                    effect.target = made[0]
        if self.capture == "previous_or_self":
            # PAR-30: "…sacrifice/exile it at the beginning of the next end
            # step." as a *trailing split clause* — "it"/"that creature"/
            # "that token"/"them" names whatever this same resolution's
            # earlier clause chose (a RULE 115 target, `previous_targets`)
            # or created (RULE 608.2, `created_objects`), falling back to
            # this ability's own source for a bare self-subject "sacrifice
            # it" with nothing before it (Brackwater Elemental). Baked in
            # now so the object set survives to the delayed firing; an
            # empty chain with no source leaves the delayed effect a no-op.
            made = (
                list(context.previous_targets)
                or list(getattr(context, "created_objects", []))
                or ([self.source] if self.source is not None else [])
            )
            for effect in inner:
                if hasattr(effect, "objects"):
                    effect.objects = made
                elif hasattr(effect, "target") and made:
                    effect.target = made[0]
        if self.capture == "self":
            # "Sacrifice ~ at the beginning of the next end step." (Wine of
            # Blood and Iron, PAR-80) — an *explicit* self-reference, unlike
            # "it"/"that creature"'s `previous_or_self` fallback chain
            # above: "~" never means whatever an earlier clause of this same
            # resolution targeted/created (Wine of Blood and Iron's own
            # earlier clause targets the creature it *pumps*, not itself),
            # so this ignores `previous_targets` entirely rather than only
            # falling back to source when that chain is empty.
            made = [self.source] if self.source is not None else []
            for effect in inner:
                if hasattr(effect, "objects"):
                    effect.objects = made
                elif hasattr(effect, "target") and made:
                    effect.target = made[0]
        # "Its controller may draw up to two cards at the beginning of the
        # next turn's upkeep." (Arcane Denial's own first sentence) — the
        # delayed draw belongs to the countered spell's controller, not
        # this ability's caster, so both *whose* upkeep it waits for
        # (`DelayedTrigger.controller_id`, below) and *who* the inner
        # `draw` effect hands cards to need that player instead of the
        # default. Baked directly into the constructed effect objects, the
        # same "capture a resolve-time fact the delayed firing can't see
        # anymore" idiom `target_mana_value` uses just above — by the time
        # this fires, the countered spell is long gone.
        target_controller_id: Optional[str] = None
        if self.capture == "target_controller" and targets:
            target_controller_id = getattr(targets[0], "controller_id", None)
            if target_controller_id is not None:
                target_player = context.state.player_by_id(target_controller_id)
                for effect in inner:
                    if hasattr(effect, "player") and getattr(effect, "player", None) is None:
                        effect.player = target_player
        if self.capture == "target_player" and targets:
            # "Choose target player. At the beginning of the next end step,
            # `<effect against that player>`." (Mirror Mirror) — unlike
            # ``target_controller`` above, ``targets[0]`` here already *is*
            # the chosen player (RULE 115's own player target, `TargetSpec(
            # kind="player")`), not a permanent whose controller has to be
            # looked up. Baked the same way — the only settable-``player``
            # inner effect this feeds is `TripleExchangeEffect`.
            target_player = targets[0]
            target_controller_id = getattr(target_player, "id", None)
            for effect in inner:
                if hasattr(effect, "player") and getattr(effect, "player", None) is None:
                    effect.player = target_player
        controller_id = (
            target_controller_id
            or getattr(self.source, "controller_id", None)
            or context.active_player.id
        )
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=controller_id,
                step=self.step,
                effects=inner,
                scope=self.scope,
                targets=list(targets or []),
                description=self.description,
                min_turn=context.state.internal_turn.number + self.min_turn_offset,
                condition=self.condition,
            )
        )


class InstallTemporaryPlayerTriggerEffect(GameEffect):
    """Arm a `TemporaryPlayerTrigger` (RULE 603.7-adjacent, but *recurring*
    and player-scoped rather than one-shot and step-scoped) — "until the
    end of defending player's next turn, that player gets two rad counters
    whenever they cast a spell" (Nuka-Nuke Launcher).

    The recipient defaults to the defending player (RULE 506.4). Like
    `AddPlayerCountersEffect.selector="defending_player"`, an Aura/
    Equipment-hosted "whenever equipped creature attacks, ..." trigger's
    own source is the Equipment, not the attacker — `combat_defender` is
    only ever stamped onto the actual attacking creature (RULE 506.4/
    `declare_attackers`), so this resolves the source's own ``attached_to``
    host first, exactly mirroring that effect's own docstring. ``event_type``
    is the `EventType`
    the installed trigger re-fires on (``"SPELL_CAST"`` — the only shape any
    real card in this pool needs); ``effects`` are whitelisted descriptors
    built into live effects immediately (mirroring `CreateDelayedTrigger
    Effect`) and reused for every firing while the trigger stays active —
    each is baked with ``player`` as its recipient (any effect carrying a
    settable, currently-``None`` ``player`` attribute, e.g.
    `AddPlayerCountersEffect`), since the specific player is fixed at
    install time, not re-resolved per firing.
    """

    def __init__(
        self,
        event_type: str,
        effects: Optional[list[dict[str, Any]]] = None,
        description: str = "",
        source: Optional["GameObject"] = None,
        recipient: str = "defending_player",
        duration: str = "defending_next_turn",
        event_player_scope: str = "self",
    ) -> None:
        super().__init__(source)
        self.event_type = str(event_type)
        self.inner_specs = list(effects or [])
        self.description = str(description)
        #: Who the installed trigger's effects go to: ``"defending_player"``
        #: (RULE 506.4 — Nuka-Nuke Launcher) or ``"controller"`` (this
        #: effect's own source's controller — Ruinous Waterbending's "…you
        #: gain 1 life").
        self.recipient = recipient
        #: Passed straight through to `TemporaryPlayerTrigger` — see its
        #: docstring. ``"this_turn"`` + ``event_player_scope="any"`` is the
        #: Ruinous Waterbending shape ("whenever a creature dies this turn").
        self.duration = duration
        self.event_player_scope = event_player_scope

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
        from ...parser.oracle.spec import EffectSpec
        from ...models.game.game_state import TemporaryPlayerTrigger

        host = self.source
        attached_to = getattr(host, "attached_to", None)
        if attached_to is not None:
            resolved = context.state.find_object(attached_to)
            if resolved is not None:
                host = resolved
        if self.recipient == "controller":
            player = _controller_of(self.source, context)
        else:
            player = _defending_player_of(host, context)
        if player is None:
            return
        inner = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in self.inner_specs],
            self.source,
        )
        for effect in inner:
            if hasattr(effect, "player") and getattr(effect, "player", None) is None:
                effect.player = player
        context.state.temporary_player_triggers.append(
            TemporaryPlayerTrigger(
                player_id=player.id,
                event_type=self.event_type,
                effects=inner,
                install_turn=context.state.internal_turn.number,
                description=self.description,
                duration=self.duration,
                event_player_scope=self.event_player_scope,
            )
        )


class PayEnergyThenEffect(GameEffect):
    """RULE 122/601.2b resolve-time optional cost: "you may pay {E}{E}. If you
    do, `<effect>`." (Aether Chaser/Herder/Inspector/Swooper — "…create a 1/1
    colorless Servo artifact creature token"). The controller may pay
    ``amount`` energy counters; only if they do do the ``effects`` follow —
    a genuine player decision (unlike the flat "Pay {E}" *activated-ability
    cost*, `ActivationCost.pay_energy`), so it opens an interactive yes/no
    `pay_energy_then` `pending_choice` at resolution (`RulesEngine.request_
    pay_energy_then`), mirroring the shock-land pay-life choice.

    ``effects`` are whitelisted descriptor dicts, built into live effects
    lazily at resolution (mirroring `InstallTemporaryPlayerTriggerEffect`);
    only untargeted follow-ups are modeled today (every real energy card
    with this rider creates a token / gains life / draws — none needs a
    freely-chosen target here). If the controller can't afford ``amount``
    energy, the payment simply never happens (no choice offered).
    """

    def __init__(
        self,
        amount: int = 0,
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = int(amount)
        self.inner_specs = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or player.counters.get("energy", 0) < self.amount:
            return  # can't pay — the optional payment simply doesn't happen
        context.engine._request_pay_energy_then(player, self.amount, self.inner_specs, self.source)


class BackFromTheBrinkEffect(GameEffect):
    """MEC-52 — Back from the Brink: "Exile a creature card from your
    graveyard **and pay its mana cost**: Create a token that's a copy of
    that card. Activate only as a sorcery."

    The cost is a *pick-then-price* one — a variable mana cost the payer
    can't know until they've chosen the graveyard card. `game/costs.py` and
    the activation flow have no such cost, so this is modeled as the
    **resolution** of an otherwise free (sorcery-speed-only) activated
    ability: on resolution the controller picks a creature card in their
    graveyard (`_request_choose_objects` ``action="exile"``, which now also
    seeds `GameContext.previous_targets` with the exiled card), then a
    `PayCostThenPreviousMvEffect` prices the "pay its mana cost" half off
    that card and, if paid, creates the copy (`copy_permanent`
    ``referent="previous"``).

    **Documented simplification:** the exile + payment happen as the
    ability resolves rather than as an activation cost, so (a) the ability
    can be activated with no eligible creature card in the graveyard (it
    then resolves into nothing) and (b) the choice/payment can't be
    responded to between announcement and payment. No printed interaction
    depends on either in a practice game.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        candidates = [o for o in controller.graveyard if o.card.is_creature]
        if not candidates:
            return
        context.engine._request_choose_objects(
            controller,
            candidates,
            action="exile",
            count=1,
            source=self.source,
            prompt="Kreaturenkarte aus deinem Friedhof ins Exil schicken",
            then_specs=[{"type": "pay_cost_then_previous_mv", "params": {}}],
        )


class PayCostThenPreviousMvEffect(GameEffect):
    """MEC-52 — the "and pay its mana cost" half of Back from the Brink: a
    `_request_pay_cost_then` whose cost is the mana cost of whatever card the
    previous clause of this resolution exiled (`GameContext.previous_
    targets`). Paid ⇒ ``effects`` (a `copy_permanent` ``referent="previous"``
    of that same card); declined ⇒ nothing.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.mana.mana_cost import ManaCost  # function-scoped: import cycle
        from ..costs import ActivationCost  # function-scoped: import cycle

        prev = [
            o for o in context.previous_targets
            if getattr(o, "card", None) is not None
        ]
        if not prev:
            return
        card_obj = prev[0]
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        cost = ActivationCost(mana=ManaCost.from_card(card_obj.card))
        context.engine._request_pay_cost_then(
            controller,
            cost,
            effect_specs=[{
                "type": "copy_permanent",
                "params": {"target_kind": None, "referent": "previous"},
            }],
            source=self.source,
            prompt=f"Manakosten von {card_obj.name} bezahlen?",
            captured_previous=[card_obj],
        )


class MayExileSourceThenEffect(GameEffect):
    """``You may exile this card. If you do, <targeted payoff>.``

    Dies abilities need this as a resolution primitive rather than an
    activation cost: by the time the trigger resolves, its source is a card
    in a graveyard. The payoff is emitted as a reflexive trigger so ordinary
    target selection happens after the optional exile has succeeded.
    """

    def __init__(
        self, then_trigger: Optional[list[dict[str, Any]]] = None,
        prompt: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.then_trigger_specs = list(then_trigger or [])
        self.prompt = prompt

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        context.engine._request_exile_source_then(
            player, self.source, self.then_trigger_specs, prompt=self.prompt,
        )


class ReflexiveTriggerEffect(GameEffect):
    """RULE 603.12: put a "When you do, `<effect>`" reflexive triggered
    ability on the stack.

    The body of a `ChooseObjectsEffect`'s ``then`` list ("You may tap
    another untapped Merfolk you control. When you do, return target
    creature card … from your graveyard to the battlefield." — Meanders
    Guide): ``then`` only runs once a pick was actually made, so the
    reflexive trigger exists only if the antecedent happened, and its own
    RULE 115 target is chosen when it is put on the stack, not before.
    Unlike `PayCostThenEffect`'s own ``then_trigger`` this has no payment of
    its own — the antecedent is whatever effect carries this in ``then``.
    """

    def __init__(
        self, then_trigger: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.then_trigger_specs = list(then_trigger or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or not self.then_trigger_specs:
            return
        context.enqueue_reflexive_trigger(self.then_trigger_specs, self.source)


class PayCostThenEffect(GameEffect):
    """RULE 118.3-style resolve-time optional payment: "you may pay
    `<cost>`. If you do, `<effect>`." — the general form of
    `PayEnergyThenEffect` above, which only ever handled ``{E}`` pips.

    ``cost`` is free-form cost *text* parsed by `game/costs.py`'s
    `parse_activation_cost`, so mana / life / discard / sacrifice all work
    through the one `_can_pay_player_cost`/`_pay_player_cost` path ward and
    "sacrifice ~ unless you pay" already share, rather than a fourth
    parallel payment implementation.

    ``payer`` says *who* is asked: ``"controller"`` (Mana Vault's own
    upkeep untap), ``"event_controller"``/``"event_player"`` — the player
    named by the triggering event (Wandering Archaic taxes the **opponent
    who cast the spell**, not its own controller) — or
    ``"attached_permanent"`` (MEC-43 round 4F, Dance of the Dead's own
    "enchanted creature's controller may pay…") — whoever currently
    controls the host this ability's own source (an Aura/Equipment) is
    attached to, read live rather than the ability's own source's
    controller.

    ``else_effects`` is the "**If you don't**, `<effect>`." branch, which for
    Wandering Archaic is the entire point: the opponent *declining* is what
    lets you copy their spell.
    """

    def __init__(
        self,
        cost: Any = "",
        effects: Optional[list[dict[str, Any]]] = None,
        else_effects: Optional[list[dict[str, Any]]] = None,
        payer: str = "controller",
        source: Optional["GameObject"] = None,
        remember_trigger_subject: bool = False,
        target_kind: Optional[str] = None,
        sacrifice_or_discard: bool = False,
        capture_previous: bool = False,
        prompt: Optional[str] = None,
        remember_trigger_stack_id: bool = False,
        then_trigger: Optional[list[dict[str, Any]]] = None,
        then_trigger_modes: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.cost_data = cost
        self.inner_specs = list(effects or [])
        self.else_specs = list(else_effects or [])
        #: "You may `<cost>`. **When you do**, `<targeted payoff>`." (Sample
        #: Collector, Curious Forager, Warren Torchmaster) — RULE 603.11's
        #: reflexive triggered ability. Unlike ``effects`` (applied off the
        #: stack the moment the choice is answered, so a RULE 115 target
        #: could never be chosen), these serialized `EffectSpec` dicts go on
        #: the stack as their *own* triggered ability once the cost is paid,
        #: with full target selection — see `RulesEngine.
        #: _resume_pay_cost_then`. Mutually exclusive with
        #: ``effects``/``else_effects`` in practice; an "if you don't" on a
        #: reflexive card doesn't occur.
        self.then_trigger_specs = list(then_trigger or [])
        self.then_trigger_modes = dict(then_trigger_modes or {})
        self.payer = payer
        #: "…unless they sacrifice a nonland permanent of their choice or
        #: discard a card." (Tergrid's Lantern, MEC-43 round 4E) — ORed
        #: onto the parsed ``cost_text`` at resolve time (`ActivationCost.
        #: sacrifice_or_discard`) rather than folded into ``cost_text``
        #: itself, since the plain regex cost parser has no grammar for
        #: this compound "sacrifice X **or** discard a card" shape (every
        #: other field on `ActivationCost` is AND-combined).
        self.sacrifice_or_discard = sacrifice_or_discard
        # A deferred "unless" branch may still name the permanent targeted
        # by the preceding instruction (Torment of Venom).  Preserve that
        # RULE 608.2 referent across its payment choice.
        self.capture_previous = capture_previous
        #: A custom prompt (Tergrid, God of Fright, MEC-43 round 4E — "you
        #: may put that card... onto the battlefield") — the default
        #: ``f"{cost_label} bezahlen?"`` reads oddly for a genuinely free
        #: ``cost=""`` "you may `<do something>`" framing, since there's
        #: nothing to name as the cost.
        self.prompt = prompt
        #: "Whenever another creature you control enters, you may pay
        #: `<cost>`. If you do, `<effect>` **it**." (Emiel the Blessed) —
        #: ``context.trigger_event`` is only live for this, the *first*,
        #: still-synchronous `apply()` call; the "if you do" branch runs
        #: later, once the interactive choice is answered, by which point
        #: that window has closed. Stamping the subject onto `GameObject.
        #: remembered_instance_id` here lets the deferred branch's own
        #: effects (`AddCountersEffect`'s ``trigger_subject_key="remembered"``)
        #: read it back.
        self.remember_trigger_subject = remember_trigger_subject
        #: "{T}: **Target player** loses 3 life unless they sacrifice a
        #: nonland permanent of their choice or discard a card."
        #: (Tergrid's Lantern, MEC-43 round 4E) — a genuine RULE 115
        #: target, unlike every other ``payer`` mode below (each derived
        #: from a firing event or this ability's own controller);
        #: meaningful only together with ``payer="target"``.
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        #: The `StackItem.stack_id` sibling of ``remember_trigger_subject``
        #: above — "Whenever you activate an ability, ... you may pay {2}.
        #: If you do, copy **that ability**." (Rings of Brighthearth) names
        #: an ability item, which has no `instance_id` of its own. Stamps
        #: `GameObject.remembered_stack_id`; `CopyAbilityEffect` reads it
        #: back on the deferred side.
        self.remember_trigger_stack_id = remember_trigger_stack_id

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..costs import parse_activation_cost  # function-scoped: import cycle

        if self.remember_trigger_subject and self.source is not None:
            event = context.trigger_event
            self.source.remembered_instance_id = (event or {}).get("instance_id")
        if self.remember_trigger_stack_id and self.source is not None:
            event = context.trigger_event
            self.source.remembered_stack_id = (event or {}).get("stack_id")
        if self.payer == "target":
            # See ``target_kind`` above — the payer is whoever this
            # ability's own RULE 115 target resolved to.
            player = targets[0] if targets else None
        elif self.payer == "target_controller":
            subject = targets[0] if targets else None
            player = (
                context.state.player_by_id(subject.controller_id)
                if getattr(subject, "controller_id", None) is not None
                else None
            )
        elif self.payer == "event_controller":
            player = _event_player(context)
        elif self.payer == "event_player":
            player = _event_player(context, key="player_id")
        elif self.payer == "previous_target_controller":
            # "…that permanent's controller may sacrifice a land…" (Chain of
            # Vapor) — the controller of whatever this same resolution's
            # *previous* clause targeted (RULE 608.2's referent,
            # `GameContext.previous_targets`), not this spell's own caster —
            # a bounce spell almost always targets an opponent's permanent,
            # so it's *them* being asked, not the caster.
            prev = list(context.previous_targets)
            player = (
                context.state.player_by_id(prev[0].controller_id)
                if prev and getattr(prev[0], "controller_id", None)
                else None
            )
        elif self.payer == "attached_permanent":
            # "At the beginning of the upkeep of enchanted creature's
            # controller, that player may pay …" (MEC-43 round 4F — Dance
            # of the Dead) — the *current* controller of whatever this
            # Aura/Equipment is attached to, read live (not this ability's
            # own source's controller, which can differ after a
            # control-change effect on the host). `GameObject.attached_to`
            # is an instance id, not the object itself (`TapEffect`'s own
            # ``target_kind="attached_permanent"`` mode resolves it the
            # same way).
            host_id = getattr(self.source, "attached_to", None)
            host = context.state.find_object(host_id) if host_id is not None else None
            player = context.state.player_by_id(host.controller_id) if host is not None else None
        else:
            player = _controller_of(self.source, context)
        if player is None:
            return
        cost = parse_activation_cost(self.cost_data)
        from ..costs import PAY_LIFE_X
        if cost.pay_life == PAY_LIFE_X:
            cost.pay_life = int(getattr(self.source, "x_paid", 0) or 0)
        if self.sacrifice_or_discard:
            cost.sacrifice_or_discard = True
        context.engine._request_pay_cost_then(
            player,
            cost,
            self.inner_specs,
            self.source,
            else_effect_specs=self.else_specs,
            # A reflexive trigger's baked-in "that spell" (Wandering
            # Archaic) has to reach the branch effects, which are built
            # fresh when the choice is answered rather than sitting on the
            # stack item where the usual target dispatch would find them.
            targets=list(targets or []),
            prompt=self.prompt,
            then_trigger_specs=self.then_trigger_specs or None,
            then_trigger_modes=self.then_trigger_modes or None,
            # The outer trigger's own event, so a "When you do" payoff that
            # names it ("that player", "defending player's graveyard") can
            # read it back off its own `StackItem.trigger_event`.
            then_trigger_event=context.trigger_event,
            captured_previous=(list(context.previous_targets) if self.capture_previous else None),
        )


class RequestAllPlayersDeclineOrEffect(GameEffect):
    """"Any player may pay `<cost>`. If no one does, `<effect>`." (Rhystic
    Circle, MEC-30, RULE 118.3-adjacent) — the multi-player sibling of
    `PayCostThenEffect`: every living player gets an independent chance to
    pay, in turn order, and ``effects`` only resolves — once, for this
    effect's own controller — if literally every one of them declines (or
    can't pay). The first player to actually pay cancels the whole thing.
    See `RulesEngine._request_all_players_decline_or` for the turn-order
    chaining.

    ``cost`` is free-form cost text (`game/costs.py`'s
    `parse_activation_cost`), same as `PayCostThenEffect`.
    """

    def __init__(
        self,
        cost: str = "",
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost)
        self.inner_specs = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..costs import parse_activation_cost  # function-scoped: import cycle

        controller = _controller_of(self.source, context)
        if controller is None:
            return
        context.engine._request_all_players_decline_or(
            parse_activation_cost(self.cost_text), self.inner_specs, self.source, controller.id,
        )


class UntapSelfEffect(GameEffect):
    """"Untap this permanent." (Mana Vault's upkeep payoff) — the untap
    sibling of `TapEffect`'s self mode, scoped to the effect's own source.

    Deliberately bypasses `continuous.has_no_untap_static`: that gate is
    about the *untap step* (RULE 502.4), and a permanent whose whole point
    is "doesn't untap during your untap step, but here's how to untap it
    anyway" (Mana Vault, Winter Orb's cousins) must not have this blocked by
    its own restriction.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.source
        if target is not None:
            context.set_tapped(target, False)


class ReboundFreeCastWindowEffect(GameEffect):
    """RULE 702.88b Rebound's delayed half: "At the beginning of your next
    upkeep, you may cast this card from exile without paying its mana
    cost." Fires as a `DelayedTrigger`'s effect, armed by `RulesEngine.
    resolve_top_of_stack` when a `GameObject.has_rebound` card resolves
    having been cast from hand (Ephemerate-shaped).

    Modeled as a *standing* temp-cast permission (`GameState.temp_play_
    permissions`, already known to `can_cast`/`cast_spell`) plus `GameState.
    free_cast_instance_ids` to zero the mana cost, rather than a forced
    yes/no choice at this trigger's own resolution: RULE 702.88b's delayed
    ability really does ask "you may cast X" right then, but this engine has
    no synchronous mid-resolution chooser for a one-shot optional action
    (`RulesEngine.discard`'s "auto-choose, no chooser in this MVP" is the
    same fidelity level elsewhere). Same-turn-only (swept at this upkeep's
    own cleanup, `GameEngine._step_cleanup`) — "use it this turn or lose
    it", matching Rebound's real one-shot window closely enough without new
    step-scoped cleanup machinery.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        if obj is None or obj.zone != Zone.EXILE:
            return
        context.engine.grant_free_cast_window_from_exile(obj)


class TheRingTemptsYouEffect(GameEffect):
    """"The Ring tempts you." (RULE 701.51a) — untargeted; the tempted
    player is the source's controller unless ``player`` names one.

    Everything the temptation *does* lives in `RulesEngine.
    the_ring_tempts_you`: level the emblem up, then choose a Ring-bearer
    (interactively when there's a real choice to make).
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or _controller_of(self.source, context)
        if player is not None:
            context.engine.the_ring_tempts_you(player)


class ChooseObjectsEffect(GameEffect):
    """"[You] choose N <kind> you control and <do something to it>." — the
    spec-facing front for `RulesEngine._request_choose_objects`.

    The general answer to every clause that names *what kind* of permanent
    to act on but leaves *which one* to a player: Tevesh Szat's "you may
    sacrifice another creature or planeswalker", Professor Onyx's forced
    per-opponent sacrifice. Distinct from `SacrificeEffect`, which picks its
    own victim by criteria — use that where the rules pick (annihilator's
    "sacrifice N permanents" is still the defender's choice, but no shipped
    card cares which), and this where the player does.

    ``then``/``then_if_commander`` are serialized `EffectSpec` dicts applied
    once the picks are in: "**If you do**, draw two cards", and RULE 903's
    "if a commander was sacrificed this way, draw a card" on top. They can't
    be separate effects in the same list, because whether they apply is only
    known *after* the choice — which is exactly what a "you may" clause
    means.

    ``player_selector="active_player"`` (MEC-43, Sheoldred, Whispering
    One's "At the beginning of **each opponent's** upkeep, **that player**
    sacrifices a creature of their choice.") reads `GameState.active_player`
    live at resolution instead of this effect's own source's controller —
    the same "no subject of its own, read live off `GameState.
    active_player`" idiom `ExileTopOfLibraryEffect`/`LandOrFreeCastEffect`
    already established for Omen Machine's "each player's draw step, that
    player exiles…": a ``STEP_BEGIN`` trigger scoped to "not you" only ever
    fires during an *opponent's* own upkeep, which is exactly whoever is
    active at firing time.

    ``require_untapped=True`` (PAR-79 seventh increment — Gravelgill
    Scoundrel/Tidal Terror's "you may tap another untapped creature you
    control") narrows candidates to permanents that aren't already tapped;
    combined with ``exclude_self`` this is the general "choose N of your
    own untapped `<type>`s, excluding this permanent" shape "…another
    untapped `<type>` you control"/"…`<N>` other untapped `<type>`s you
    control" templates both need — no separate effect type, since
    `_request_choose_objects`'s ``action="tap"`` already does the rest.
    """

    def __init__(
        self,
        action: str = "sacrifice",
        what: str = "permanent",
        count: int = 1,
        optional: bool = False,
        exclude_self: bool = False,
        prompt: str = "",
        then: Optional[list[dict[str, Any]]] = None,
        then_if_commander: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
        player_selector: str = "controller",
        require_untapped: bool = False,
    ) -> None:
        super().__init__(source)
        self.action = action
        self.what = what
        self.count = count
        self.optional = optional
        self.exclude_self = exclude_self
        self.prompt = prompt
        self.then = then
        self.then_if_commander = then_if_commander
        self.player_selector = player_selector
        #: "…tap another untapped creature you control." (Gravelgill
        #: Scoundrel/Tidal Terror, PAR-79 seventh increment) — narrows the
        #: candidate pool to permanents that are currently untapped, the
        #: same qualifier a RULE 115 target's `creature_filter={"tapped":
        #: False}` would apply, but this chooser has no such filter param
        #: of its own since no prior card needed one.
        self.require_untapped = require_untapped

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..rules_engine import _matches_permanent_type

        if self.player_selector == "active_player":
            player = context.state.active_player
        else:
            player = _controller_of(self.source, context)
        if player is None:
            return
        candidates = [
            obj
            for obj in context.state.permanents_controlled_by(player.id)
            if _matches_permanent_type(obj, self.what)
            and not (self.exclude_self and obj is self.source)
            and not (self.require_untapped and obj.tapped)
        ]
        context.choose_objects(
            player, candidates, self.action, count=self.count,
            optional=self.optional, prompt=self.prompt, source=self.source,
            then_specs=self.then, then_specs_if_commander=self.then_if_commander,
        )


class ConniveEffect(GameEffect):
    """"`<permanent>` connives[ N]." (RULE 701.47/701.50, MEC-43 — Ledger
    Shredder; PAR-29): its controller draws a card, then discards a card; if
    a nonland card was discarded this way, put a +1/+1 counter on it.

    The draw is plain `context.draw`; the discard is the general
    interactive hand-card chooser (`RulesEngine._request_choose_objects`,
    ``action="discard"`` — already `_apply_chosen_object`'s own primitive
    for a *chosen* discard, called directly here rather than through
    `ChooseObjectsEffect`, whose own candidate gathering is battlefield-
    permanents-only and so can't reach hand cards), widened with a new
    ``connive`` flag so `_apply_chosen_object` can inspect the picked
    card's own `is_land` after the fact and place the counter — the
    "if you did X" conditional depends on *what* was picked, not just
    *whether* something was, which the existing ``then_specs_if_commander``
    boolean-tracking idiom doesn't cover.

    Same three subject shapes as `GoadEffect`/`ExploreEffect`: bare self
    (``target_kind=None``, not a pronoun — "~ connives"/"it connives" off
    ``self.source``, including a triggered ability whose own subject was
    dynamically retargeted onto e.g. the attached permanent), a `TargetSpec`
    ("target creature [you control] connives"), and ``previous_subject``
    ("that creature connives", `GameContext.previous_targets`).

    ``times``/``times_from_count_selector``/``times_from_trigger_event`` are
    RULE 701.50d's "connives N"/"connives X": the controller draws N cards,
    discards N cards (**one** N-card choice, not N separate 1-and-1
    cycles — `_request_choose_objects`'s own ``count=N`` already offers that
    as N sequential picks, same as any other multi-pick chooser), then a
    counter goes on the conniving permanent for each nonland card among
    those N discards (unbounded — RULE 701.50d, unlike 701.50a's implicit
    cap of one). ``times_from_trigger_event`` reads the firing event's own
    field (`GameContext.trigger_event`, the `DealDamageEffect.
    amount_from_trigger_event` idiom — "the amount of damage it dealt to
    that player", Mask of the Schemer); ``times_from_count_selector`` reads
    a live board count (`continuous.count_selector`, DEVOTION-derived —
    "the number of attacking creatures"/"creatures that died this turn").
    RULE 701.50e: conniving 0 is a no-op (no draw, no discard, no event).

    Every conniving creature's *own* controller draws/discards for it (RULE
    701.47), not necessarily this effect's controller — so with 2+ subjects
    (a `TargetSpec` naming several, e.g. "each of X target creatures you
    control connive") each is processed one at a time via
    `GameState.deferred_effects`, the same RULE 608.2 idiom
    `SacrificeEffect._sacrifice_each_in_order` uses: looping every subject's
    interactive discard synchronously in one `apply()` would silently
    overwrite an earlier subject's still-unanswered prompt with a later
    one's, since the game state holds exactly one `pending_choice` at a
    time.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        previous_subject: bool = False,
        optional: bool = False,
        count: Any = 1,
        count_selector: Optional[str] = None,
        times: int = 1,
        times_from_count_selector: Optional[str] = None,
        times_from_trigger_event: Optional[str] = None,
        creature_filter: Optional[dict] = None,
    ) -> None:
        super().__init__(source)
        self.previous_subject = bool(previous_subject)
        self.times = max(1, int(times))
        self.times_from_count_selector = times_from_count_selector
        self.times_from_trigger_event = times_from_trigger_event
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional,
                       count=count if isinstance(count, int) else 1,
                       count_selector=count_selector, creature_filter=creature_filter)
            if target_kind is not None
            else None
        )

    #: A resumed continuation's own remaining-subjects queue (see
    #: `_connive_queue`) — never set by a parsed `EffectSpec` (outside the
    #: whitelisted-param security boundary on purpose: pure runtime state,
    #: constructed only by this class itself), only by this class
    #: re-scheduling its own remainder. The same idiom as
    #: `SacrificeEffect._remaining_players`.
    _remaining_queue: Optional[list["GameObject"]] = None
    #: Carried onto a resumed continuation alongside ``_remaining_queue`` —
    #: every subject in one resolution connives the same N (RULE 701.50c/d
    #: never mixes a per-subject count within a single instruction).
    _resumed_times: int = 1

    def _resolve_times(self, context: GameContext) -> int:
        if self.times_from_trigger_event:
            event = context.trigger_event
            value = (event or {}).get(self.times_from_trigger_event)
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return 0
        if self.times_from_count_selector:
            from .. import continuous
            controller_id = getattr(self.source, "controller_id", None)
            return max(0, continuous.count_selector(
                context.state, controller_id, self.times_from_count_selector, source=self.source,
            ))
        return self.times

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._remaining_queue is not None:
            self._connive_queue(context, self._remaining_queue, self._resumed_times)
            return
        if self.target_spec is not None:
            subjects = list(targets or [])
        elif self.previous_subject:
            subjects = [
                obj for obj in context.previous_targets
                if getattr(obj, "instance_id", None) is not None
            ]
        else:
            subjects = [self.source] if self.source is not None else []
        times = self._resolve_times(context)
        if times <= 0:
            # RULE 701.50e: conniving 0 does nothing — no draw, no discard.
            return
        self._connive_queue(context, subjects, times)

    def _connive_queue(
        self, context: GameContext, queue: list["GameObject"], times: int,
    ) -> None:
        state = context.state
        for i, obj in enumerate(queue):
            player = _controller_of(obj, context)
            if player is None:
                continue
            before = getattr(state, "pending_choice", None)
            context.draw(player, times)
            if player.hand:
                context.engine._request_choose_objects(
                    player, list(player.hand), "discard", count=min(times, len(player.hand)),
                    source=obj, connive=True,
                )
            opened = getattr(state, "pending_choice", None)
            if opened is not None and opened is not before and i + 1 < len(queue):
                remainder = ConniveEffect(source=self.source)
                remainder._remaining_queue = queue[i + 1:]
                remainder._resumed_times = times
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


class RecruitEffect(GameEffect):
    """"Recruit." (RULE 701.70a — Tales of Middle-earth): this effect's
    controller draws a card, then discards a card; if the discarded card was
    a nonland card, they create a 1/1 white Human Soldier creature token.

    Connive's sibling (`ConniveEffect`) — same draw-then-conditional-discard
    shape, different payoff (a token, not a +1/+1 counter on a source), so
    `RulesEngine.recruit` owns it as its own small primitive rather than
    reusing the shared chooser's ``connive`` flag. Bare "you"-subject only —
    every real card says just "recruit."
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.recruit(player)


class LearnEffect(GameEffect):
    """"Learn." (RULE 701.48a — Strixhaven): this effect's controller may
    discard a card, then draw a card (the "Lesson from outside the game"
    branch is dropped — see `RulesEngine.learn`). Bare "you"-subject only —
    every real card says just "learn.".
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.learn(player, source=self.source)


class CollectEvidenceEffect(GameEffect):
    """"Collect evidence N." (RULE 701.59a — Murders at Karlov Manor) as a
    *resolving effect* rather than a cost: this effect's controller exiles
    graveyard cards totalling mana value ``amount`` or greater (auto-picked;
    see `RulesEngine.collect_evidence`) and fires
    `EventType.COLLECTED_EVIDENCE`. A no-op if their graveyard can't reach
    the threshold.

    The "you may" that precedes it on every real card is the segmenter's
    outer `_peel_optional` (`AbilitySpec.optional`) — a *non*-peeled "you
    may collect evidence N" whole clause is claimed instead by
    `handlers._collect_evidence_bare` as an interactive `pay_cost_then`.
    """

    def __init__(self, amount: int = 0, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = int(amount)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        if context.engine.collect_evidence_possible(player, self.amount):
            context.engine.collect_evidence(player, self.amount)


class ExileSelfCollectEvidenceReturnEffect(GameEffect):
    """Lamplight Phoenix's optional death-trigger sequence.

    The source has already died, so it moves from its owner's graveyard to
    exile, then the controller collects evidence.  The return is conditional
    on that collection actually completing; moving through the graveyard
    immediately before the established self-return helper preserves its
    normal entry and event path without exposing an intermediate game action.
    """

    def __init__(self, amount: int, tapped: bool = True, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = int(amount)
        self.tapped = bool(tapped)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_object import Zone

        source = self.source
        player = _controller_of(source, context)
        if source is None or player is None or not context.engine.collect_evidence_possible(player, self.amount):
            return
        context.exile(source)
        if source.zone != Zone.EXILE or not context.engine.collect_evidence(player, self.amount):
            return
        owner = context.state.player_by_id(source.owner_id)
        if owner is None:
            return
        owner.remove_from_zone(source, Zone.EXILE)
        source.zone = Zone.GRAVEYARD
        owner.add_to_zone(source, Zone.GRAVEYARD)
        context.return_from_graveyard(
            source, "battlefield_tapped" if self.tapped else "battlefield"
        )


class RecordBendEffect(GameEffect):
    """Mark that this effect's controller performed a bending keyword action
    (RULE 701.6x — ``kind`` in `RulesEngine.BEND_KINDS`) by calling
    `RulesEngine.record_bend` (stamps `GameState.bends_this_turn`, fires
    `EventType.BENT`).

    Not an instruction body of its own — used as the **Firebending** attack
    marker: `effect_binder._kw_firebending` appends it to the firebending
    mana trigger's effects, so "you firebend" is registered the moment that
    trigger resolves (the set has no other "firebend" action). Earthbend,
    the waterbend cost payment and airbend (`ExileEffect.bend_kind`) each
    call `record_bend` from their own primitive directly instead. Kept as a
    registered spec type so any future explicit "you `<bend>`" body has a
    marker to reach.
    """

    def __init__(self, kind: str = "firebend", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.kind = kind

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.engine.record_bend(player, self.kind, source=self.source)


class ForageEffect(GameEffect):
    """"Forage." (RULE 701.61a — Bloomburrow) as a *resolving effect*: this
    effect's controller exiles three cards from their graveyard or
    sacrifices a Food (auto-picked; see `RulesEngine.forage`) and fires
    `EventType.FORAGED`. A no-op if they can do neither.

    The "you may" before it is the segmenter's outer `_peel_optional`
    (`AbilitySpec.optional`); a *non*-peeled "you may forage" whole clause
    is claimed instead by `handlers._forage_bare` as an interactive
    `pay_cost_then`.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        if context.engine.forage_possible(player):
            context.engine.forage(player)


class VoteEffect(GameEffect):
    """RULE 701.38: "Starting with you, each player votes for one of
    ``options``." An APNAP sweep (`RulesEngine._request_vote`) collects one
    vote per living player, then resolves an outcome:

    * ``majority_specs`` — one serialized effect list per option (same order
      as ``options``); the strict vote leader's list is applied, or
      ``tie_index``'s if no option leads alone (RULE 701.38d, "or the vote
      is tied").
    * ``per_vote_specs`` — ``[{"option": i, "effects": [...], "scale": k}]``:
      each entry's ``count``/``amount`` params are multiplied by ``k`` ×
      option ``i``'s vote total ("… for each `<option>` vote"). MEC-46: an
      entry may instead be ``{"option": i, "per_voter_gain_control": true}``
      (Expropriate's per-money-vote gain-control).
    * ``winner_specs`` (MEC-46) — like ``majority_specs`` but applied for
      *every* option tied for most votes, not only a sole leader ("~ gains
      protection from each color with the most votes or tied for most
      votes" — Council Guardian).

    A bare "you"-subject effect — no target, no pronoun. The vote outcome
    is applied with this effect's own controller as the target ("you").
    """

    def __init__(
        self,
        options: Optional[list[str]] = None,
        majority_specs: Optional[list[list[dict[str, Any]]]] = None,
        tie_index: Optional[int] = None,
        per_vote_specs: Optional[list[dict[str, Any]]] = None,
        winner_specs: Optional[list[Optional[list[dict[str, Any]]]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.options = list(options or [])
        self.majority_specs = majority_specs
        self.tie_index = tie_index
        self.per_vote_specs = per_vote_specs
        self.winner_specs = winner_specs

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or len(self.options) < 2:
            return
        context.engine._request_vote(
            source=self.source,
            controller_id=player.id,
            options=self.options,
            majority_specs=self.majority_specs,
            tie_index=self.tie_index,
            per_vote_specs=self.per_vote_specs,
            winner_specs=self.winner_specs,
        )


class SetForcedVoterEffect(GameEffect):
    """RULE 701.38f (MEC-46): "You choose how each player votes this turn."
    (Illusion of Choice) — a bare "you"-subject effect that marks this
    effect's controller as the answerer of every `vote` / `vote_object`
    choice for the rest of the turn. `RulesEngine._advance_vote` /
    `_advance_object_vote` redirect each ballot's `pending_choice` to this
    player while `GameState.forced_vote_controller_id` is set; it clears at
    cleanup (RULE 514.2, `GameEngine._step_cleanup`) like every other "this
    turn" marker.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.state.forced_vote_controller_id = player.id


class ExpropriateGainControlEffect(GameEffect):
    """MEC-46 (Expropriate): the continuation of "for each money vote,
    choose a permanent owned by the voter and gain control of it".

    Carries the *remaining* voter ids in ``voter_ids`` and re-enters
    `RulesEngine._advance_expropriate_gain_control`, which opens one
    `choose_objects` (``action="gain_control"``) pick for the next voter
    and chains another copy of this effect for the rest — so the whole
    queue lives in serialized `pending_choice` data and survives the undo
    snapshots `GameState` takes.
    """

    def __init__(
        self, voter_ids: Optional[list[str]] = None, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.voter_ids = [str(v) for v in (voter_ids or [])]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None or not self.voter_ids:
            return
        context.engine._advance_expropriate_gain_control(
            self.source, controller.id, list(self.voter_ids)
        )


class ObjectVoteEffect(GameEffect):
    """MEC-46 (RULE 701.38): "Starting with you, each player votes for `<an
    object>`. `<verb>` each `<object>` with the most votes or tied for most
    votes." — the tally-over-objects vote (`RulesEngine.request_object_
    vote`), distinct from `VoteEffect`'s tally-over-named-options.

    ``pool`` picks the candidate set:

    * ``"nonland_permanents_opponents"`` — every nonland permanent this
      effect's controller doesn't control (Council's Judgment).
    * ``"graveyard_cards"`` — cards in this controller's graveyard whose
      type is in ``card_types`` (Custodi Squire — artifact/creature/
      enchantment).

    ``outcome`` is ``"exile"`` or ``"return_to_hand"``.
    """

    def __init__(
        self,
        pool: str = "nonland_permanents_opponents",
        outcome: str = "exile",
        card_types: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.pool = pool
        self.outcome = outcome
        self.card_types = [str(t).lower() for t in (card_types or [])]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        if self.pool == "graveyard_cards":
            candidates = [
                o for o in controller.graveyard
                if not self.card_types
                or any(t in o.type_words for t in self.card_types)
            ]
            prompt = "Abstimmung: Karte aus dem Friedhof"
        else:
            candidates = [
                o for o in context.state.permanents()
                if not o.is_land and o.controller_id != controller.id
            ]
            prompt = "Abstimmung: bleibender Nichtland-Permanent"
        if not candidates:
            return
        context.engine._request_object_vote(
            source=self.source,
            controller_id=controller.id,
            candidates=candidates,
            outcome=self.outcome,
            prompt=prompt,
        )


class TimeTravelEffect(GameEffect):
    """RULE 701.56: "Time travel." — a bare "you"-subject keyword action;
    `RulesEngine.time_travel` owns the procedure and its documented
    add-to-Vanishing / remove-from-suspended simplification. "Time travel,
    then time travel." (The Parting of the Ways) is two of these in
    sequence from `parse_effect_body`'s ", then" split.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.engine.time_travel(player)


class FaceVillainousChoiceEffect(GameEffect):
    """RULE 701.55: "`<player>` faces a villainous choice — `<A>`, or
    `<B>`." Each facing player (resolved from ``subject``) chooses one of
    the two options; that option's effects resolve **for that player**
    (`RulesEngine._request_villainous_choice`, an APNAP sweep — the
    `VoteEffect` sweep minus the tally).

    ``subject`` — who faces it:

    * ``"each_opponent"`` — every opponent of this effect's controller.
    * ``"target"`` — a single targeted player (``targets[0]``).
    * ``"trigger_target_player"`` — the player named by the triggering
      event ("Whenever ~ deals combat damage to a player, **that player**
      faces …").

    ``option_a`` / ``option_b`` are serialized `EffectSpec` lists; a
    ``sacrifice``/``discard``/``lose_life`` spec with no selector lands on
    the facing player, a "you …" spec on the controller.
    """

    def __init__(
        self,
        option_a: Optional[list[dict[str, Any]]] = None,
        option_b: Optional[list[dict[str, Any]]] = None,
        subject: str = "each_opponent",
        labels: Optional[list[str]] = None,
        subject_min_life_lost: int = 0,
        capture_previous: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.option_a = list(option_a or [])
        self.option_b = list(option_b or [])
        self.subject = subject
        self.labels = tuple(labels) if labels and len(labels) == 2 else ("A", "B")
        #: "**each opponent who lost N or more life this turn** faces a
        #: villainous choice" (Davros, Dalek Creator) — narrows an
        #: ``"each_opponent"`` sweep to the opponents at/past the threshold
        #: (`GameState.life_lost_this_turn`). 0 = no filter.
        self.subject_min_life_lost = int(subject_min_life_lost)
        #: "…choose an opponent with the most life among your opponents. That
        #: player faces a villainous choice — … or you create a token that's
        #: a copy of **that card**." (The Master, Gallifrey's End) — bake the
        #: RULE 608.2 referent (`context.previous_targets`, the card an
        #: earlier clause of this resolution just exiled) into the choice so
        #: an option body's `copy_permanent` ``referent="previous"`` still
        #: resolves against it once the choice is *answered* — by which point
        #: this resolution's own context is long gone.
        self.capture_previous = bool(capture_previous)
        if subject == "target":
            self.target_spec = TargetSpec(kind="player")
        elif subject == "previous_target_controller":
            #: "Choose up to four target creatures you don't control. For
            #: each of them, **that creature's controller** faces a
            #: villainous choice — …" (MEC-52, Hunted by The Family). The
            #: RULE 115 targets are the *creatures*; each one's controller
            #: is the facing player for its own queued choice, and every
            #: option body acts on that creature (`captured`), not on the
            #: player. "Up to four" ⇒ ``optional`` + ``count=4`` (0..4, per
            #: RULE 115.1a generalized).
            self.target_spec = TargetSpec(
                kind="creature_you_dont_control", optional=True, count=4,
            )
        else:
            self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None or not self.option_a or not self.option_b:
            return
        if self.subject == "previous_target_controller":
            self._face_per_target(context, controller, targets)
            return
        facing: list[Any] = []
        if self.subject == "each_opponent":
            start = context.state.active_player_index
            n = len(context.state.players)
            facing = [
                context.state.players[(start + i) % n]
                for i in range(n)
                if not context.state.players[(start + i) % n].has_lost
                and context.state.players[(start + i) % n].id != controller.id
            ]
        elif self.subject == "target":
            facing = [t for t in (targets or []) if getattr(t, "id", None) is not None]
        elif self.subject == "trigger_target_player":
            ev = context.trigger_event
            pid = (ev or {}).get("player_id") or (ev or {}).get("target_player_id")
            if pid is not None:
                try:
                    facing = [context.state.player_by_id(pid)]
                except (KeyError, ValueError):
                    facing = []
        elif self.subject == "opponent_with_most_life":
            # "choose an opponent with the most life among your opponents"
            # (The Master, Gallifrey's End) — RULE 701.55's pre-selection.
            # Ties: the first in APNAP order (a documented simplification of
            # the printed "your choice").
            opps = [
                p for p in context.state.living_players() if p.id != controller.id
            ]
            if opps:
                most = max(p.life for p in opps)
                start = context.state.active_player_index
                n = len(context.state.players)
                ordered = [
                    context.state.players[(start + i) % n] for i in range(n)
                ]
                facing = [p for p in ordered if p in opps and p.life == most][:1]
        if self.subject_min_life_lost > 0:
            facing = [
                p for p in facing
                if context.state.life_lost_this_turn.get(p.id, 0) >= self.subject_min_life_lost
            ]
        if not facing:
            return
        context.engine._request_villainous_choice(
            source=self.source,
            controller_id=controller.id,
            facing_ids=[p.id for p in facing],
            option_a=self.option_a,
            option_b=self.option_b,
            labels=self.labels,
            captured_previous=(
                list(context.previous_targets) if self.capture_previous else None
            ),
        )

    def _face_per_target(
        self, context: GameContext, controller: Any, targets: Optional[list[Any]],
    ) -> None:
        """MEC-52 (Hunted by The Family): one queued villainous choice per
        chosen creature, faced by *that creature's* controller, with the
        creature itself baked in as the RULE 608.2 referent (`captured`) so
        an option body's `grant_until` ``previous_subject`` / `copy_permanent`
        ``referent="previous"`` acts on the creature, not the facing
        player."""
        creatures = [
            c for c in (targets or []) if getattr(c, "instance_id", None) is not None
        ]
        rounds: list[dict[str, Any]] = []
        for creature in creatures:
            try:
                ctrl = context.state.player_by_id(creature.controller_id)
            except (KeyError, ValueError):
                continue
            if ctrl.has_lost:
                continue
            rounds.append({
                "facing_id": ctrl.id,
                "option_a": self.option_a,
                "option_b": self.option_b,
                "labels": self.labels,
                "captured": [creature],
            })
        if not rounds:
            return
        context.engine._request_villainous_choice(
            source=self.source, controller_id=controller.id, rounds=rounds,
        )


class ExploreEffect(GameEffect):
    """RULE 701.44: "`<permanent>` explores." — reveal the top card of the
    exploring permanent's controller's library; a land goes to hand,
    otherwise a +1/+1 counter goes on the permanent and its controller may
    bin the revealed card. `RulesEngine.explore` owns the whole procedure
    (and the one interactive pause, the "may put it into your graveyard"
    choice); this effect only resolves *which* permanent(s) explore.

    Like `GoadEffect`, the subject is a permanent and comes in three shapes:
    ``target_kind`` set — "target creature you control explores"; ``previous_
    subject`` — "it explores" / "that creature explores", the creature an
    earlier clause of this resolution chose (`GameContext.previous_targets`);
    and the bare self form (``target_kind=None``, not a pronoun) — "when ~
    enters, it explores", exploring `self.source`.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        previous_subject: bool = False,
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.previous_subject = bool(previous_subject)
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional)
            if target_kind is not None
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            explorers = list(targets or [])
        elif self.previous_subject:
            explorers = [
                obj for obj in context.previous_targets
                if getattr(obj, "instance_id", None) is not None
            ]
        else:
            explorers = [self.source] if self.source is not None else []
        for obj in explorers:
            context.engine.explore(obj)


class PopulateEffect(GameEffect):
    """RULE 701.36: "Populate[ X times]." — put a token onto the
    battlefield that's a copy of a creature token this effect's controller
    controls (701.36a); if they control no creature tokens, populate does
    nothing (701.36b).

    Always the resolving controller's own creature tokens — "populate" never
    takes a target or a pronoun subject (unlike `ExploreEffect`/`GoadEffect`),
    so there is only the one shape. `RulesEngine.populate` owns the whole
    procedure, including the one interactive pause (which token to copy when
    the controller has more than one).

    ``count`` (PAR-29, Full Flowering's "Populate X times.") is the plain
    ``"x"``/``"-x"`` sentinel `RulesEngine._substitute_x` already resolves
    generically on any effect's own ``count`` attribute — no bespoke
    ``count_selector``/``trigger_event`` plumbing needed, unlike
    `ConniveEffect`'s dynamic amount (connive's X can come from a board
    count or a firing trigger's own field; populate's only ever comes from
    the spell's own announced {X}). 2+ repeats are sequenced one at a time
    via `GameState.deferred_effects` — the same RULE 608.2 idiom
    `ConniveEffect`/`SacrificeEffect` use — since looping every repeat's
    interactive "which token?" choice synchronously would silently
    overwrite an earlier repeat's still-unanswered prompt with a later
    one's.
    """

    def __init__(
        self, source: Optional["GameObject"] = None, count: Any = 1,
        tapped: bool = False, attacking: bool = False,
    ) -> None:
        super().__init__(source)
        self.count = count if not isinstance(count, int) else max(1, count)
        #: "…populate. **That token enters tapped and attacking.**" (Ghired,
        #: Conclave Exile — RULE 508.4). Carried to `RulesEngine.populate` as
        #: an ``enter_state`` dict so the copy is tapped/put-into-combat the
        #: instant it enters, including on the interactive 2+-token path.
        self.enter_tapped = bool(tapped)
        self.enter_attacking = bool(attacking)

    #: A resumed continuation's own remaining-repeat count — never set by a
    #: parsed `EffectSpec`, only by this class re-scheduling its own
    #: remainder (the same idiom as `SacrificeEffect._remaining_players`).
    _remaining_count: Optional[int] = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        count = self.count if self._remaining_count is None else self._remaining_count
        count = count if isinstance(count, int) else 1
        if count <= 0:
            return
        player = _controller_of(self.source, context)
        if player is None:
            return
        state = context.state
        enter_state = (
            {"tapped": self.enter_tapped, "attacking": self.enter_attacking}
            if (self.enter_tapped or self.enter_attacking) else None
        )
        for i in range(count):
            before = getattr(state, "pending_choice", None)
            context.engine.populate(player, enter_state=enter_state)
            opened = getattr(state, "pending_choice", None)
            if opened is not None and opened is not before and i + 1 < count:
                remainder = PopulateEffect(source=self.source)
                remainder.enter_tapped = self.enter_tapped
                remainder.enter_attacking = self.enter_attacking
                remainder._remaining_count = count - i - 1
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


class BolsterEffect(GameEffect):
    """RULE 701.39: "Bolster N[/X]." — put N +1/+1 counters on a least-
    toughness creature this effect's controller controls (their own choice
    on a tie), nothing if they control no creatures. Always the resolving
    controller's own creatures — "bolster" never takes a target or a
    pronoun subject, so (like `PopulateEffect`) there is only the one
    shape. `RulesEngine.bolster` owns the whole procedure, including the
    tie-break `pending_choice`.

    ``amount_from_count_selector`` (PAR-29, Dragonscale General/Sunbringer's
    Touch) is RULE 701.39a's dynamic "bolster X, where X is `<board
    count>`" — read live via `continuous.count_selector` at resolution, the
    same idiom `PumpEffect.amount_from_count_selector` uses. RULE 701.39e's
    "bolster 0 does nothing" falls out for free: `RulesEngine.bolster`
    already treats an amount of 0 as trivially satisfied (0 counters placed).
    """

    def __init__(
        self, source: Optional["GameObject"] = None, amount: int = 1,
        amount_from_count_selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.amount = max(1, int(amount)) if amount_from_count_selector is None else int(amount)
        self.amount_from_count_selector = amount_from_count_selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        amount = self.amount
        if self.amount_from_count_selector:
            from .. import continuous
            amount = continuous.count_selector(
                context.state, player.id, self.amount_from_count_selector, source=self.source,
            )
        if amount <= 0:
            return
        context.engine.bolster(player, amount, source=self.source)


class EndureEffect(GameEffect):
    """RULE 701.63a: "`<permanent>` endures N[/X]." (Bloomburrow) — its
    controller either puts N +1/+1 counters on it or creates an N/N white
    Spirit creature token. `RulesEngine.endure` owns the procedure and the
    modal `endure` `pending_choice`; this effect only resolves *which*
    permanent endures.

    Subject shapes, like `ExploreEffect`: bare self ("when ~ enters, it
    endures 3", the bulk), ``previous_subject`` ("that creature endures N"),
    and a `TargetSpec` ("target creature you control endures N").

    ``amount`` (PAR-29, Krumar Initiate's "~ endures X") may be the plain
    ``"x"`` sentinel `RulesEngine._substitute_x` already resolves
    generically on any effect's own ``amount`` attribute — the same idiom
    `PopulateEffect.count`/`MonstrosityEffect.amount` use, so int
    conversion is deferred rather than attempted at construction time
    (``int("x")`` would raise).
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        amount: Any = 1,
        target_kind: Optional[str] = None,
        previous_subject: bool = False,
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.amount = amount if not isinstance(amount, int) else max(1, amount)
        self.previous_subject = bool(previous_subject)
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional)
            if target_kind is not None
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            endurers = list(targets or [])
        elif self.previous_subject:
            endurers = [
                o for o in context.previous_targets
                if getattr(o, "instance_id", None) is not None
            ]
        else:
            endurers = [self.source] if self.source is not None else []
        amount = self.amount if isinstance(self.amount, int) else 1
        for obj in endurers:
            context.engine.endure(obj, amount)


class BlightEffect(GameEffect):
    """"Blight N." (Bloomburrow — "put N -1/-1 counters on a creature you
    control"). `BolsterEffect`'s negative sibling: a bare "you"-subject
    effect (no target, no pronoun), `RulesEngine.blight` owns the procedure
    and its "which creature" `pending_choice`.

    ``target_kind`` (PAR-30 — Champion of the Weird's "target opponent
    blights 2.") makes *that player* the one who blights: the RULE 115
    target is read as the player, and the -1/-1 counters go on a creature
    **they** control (their own `pending_choice`), not the controller's.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        amount: int = 1,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.amount = max(1, int(amount))
        self.target_kind = target_kind
        if target_kind:
            from ..targeting import TargetSpec

            self.target_spec = TargetSpec(target_kind, count=1)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_kind:
            from ...models.game.player import Player as _Player

            player = next(
                (t for t in (targets or []) if isinstance(t, _Player)), None
            )
        else:
            player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.blight(player, self.amount, source=self.source)


class EarthbendEffect(GameEffect):
    """"Earthbend N." (RULE 701.66 — Avatar: The Last Airbender): a target
    land you control becomes a 0/0 creature with haste that's still a land,
    then gets N +1/+1 counters. `RulesEngine.earthbend` owns the procedure.

    Targets a ``land_you_control`` (the reminder text's "target land you
    control") unless ``previous_subject`` — "earthbend N, then <do something
    to> that land" names the land an earlier clause of the same ability
    already earthbended (`GameContext.previous_targets`), the pronoun idiom
    `FightEffect`/`GoadEffect` use. ``amount`` may be the literal ``"x"``
    sentinel `RulesEngine._substitute_x` resolves (int conversion deferred
    to `apply`, as `EndureEffect` does).
    """

    def __init__(
        self,
        amount: Any = 1,
        previous_subject: bool = False,
        source: Optional["GameObject"] = None,
        amount_from_count_selector: Optional[str] = None,
        amount_multiplier: int = 1,
        amount_from_trigger_event: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.previous_subject = previous_subject
        #: RULE 701.66 dynamic "earthbend X, where X is **that creature's
        #: power**" (Beifong's Bounty Hunters) — a field name read off
        #: `GameContext.trigger_event` at resolution (``"power"``, the DIES
        #: event's RULE 400.7 last-known-power snapshot), the same
        #: "amount comes from the firing event's payload" idiom
        #: `DealDamageEffect.amount_from_trigger_event` uses.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: RULE 701.66's dynamic "earthbend X, where X is `<board count>`"
        #: (Rockalanche/The Boulder, Ready to Rumble — PAR-30), read live via
        #: `continuous.count_selector` at resolution, the same idiom
        #: `BolsterEffect.amount_from_count_selector` uses. ``amount_
        #: multiplier`` folds in a "**twice** the number of …" prefix
        #: (Bumi's Feast Lecture).
        self.amount_from_count_selector = amount_from_count_selector
        self.amount_multiplier = max(1, int(amount_multiplier))
        self.target_spec = (
            None if previous_subject else TargetSpec(kind="land_you_control")
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.previous_subject:
            lands = [
                t for t in context.previous_targets
                if getattr(t, "is_land", False) or getattr(t, "was_land", False)
            ]
        else:
            lands = [t for t in (targets or []) if getattr(t, "instance_id", None) is not None]
        if not lands:
            return
        if self.amount_from_trigger_event:
            from ...parser.oracle.spec import MAX_EFFECT_MAGNITUDE

            event = context.trigger_event or {}
            raw = event.get(self.amount_from_trigger_event) or 0
            try:
                amount = max(0, min(int(raw), MAX_EFFECT_MAGNITUDE))
            except (TypeError, ValueError):
                amount = 0
        elif self.amount_from_count_selector:
            from .. import continuous  # function-scoped: avoid an import cycle
            from ...parser.oracle.spec import MAX_EFFECT_MAGNITUDE

            controller_id = getattr(self.source, "controller_id", None)
            raw = continuous.count_selector(
                context.state, controller_id, self.amount_from_count_selector, source=self.source,
            ) * self.amount_multiplier
            amount = max(0, min(int(raw), MAX_EFFECT_MAGNITUDE))
        else:
            try:
                amount = int(self.amount)
            except (TypeError, ValueError):
                amount = 0  # unresolved "x" sentinel — nothing to add
        context.engine.earthbend(lands[0], max(0, amount), source=self.source)


class SacrificeSpecificEffect(GameEffect):
    """Sacrifice the exact permanents baked into this effect (RULE 701.17).

    The named-object counterpart of `SacrificeEffect`, which picks its
    victims by criteria and selector. Used where the rules already fixed
    *which* permanents ("that creature's controller sacrifices it at end of
    combat" — RULE 701.51a's third Ring ability), so there is nothing to
    choose and nothing to target. Silently skips any that already left the
    battlefield by the time this resolves.

    ``delay_step`` defers the sacrifice to a RULE 603.7 delayed trigger at
    that step instead of doing it now — "…sacrifices it **at end of
    combat**". Armed rather than executed, so a blocker that dies in combat
    first is simply gone when the delayed half fires.
    """

    def __init__(
        self,
        objects: list["GameObject"],
        delay_step: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.objects = objects
        self.delay_step = delay_step

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.delay_step:
            from ...models.game.game_state import DelayedTrigger

            controller_id = getattr(self.source, "controller_id", None) or (
                context.active_player.id if context.active_player else ""
            )
            context.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=controller_id,
                    step=self.delay_step,
                    scope="any",
                    effects=[SacrificeSpecificEffect(list(self.objects), source=self.source)],
                    description="Opfern am Ende des Kampfes",
                )
            )
            return
        for obj in list(self.objects):
            if obj in context.state.battlefield:
                # RULE 701.17a: a sacrifice is a non-destructive move to the
                # graveyard, so it can't be stopped by a regeneration shield
                # (RULE 701.16c) — `put_into_graveyard`, not `destroy`.
                context.engine.put_into_graveyard(obj)


class SacrificeAttachedPermanentEffect(GameEffect):
    """"When this Aura leaves the battlefield, that creature's controller
    sacrifices it." (MEC-34, RULE 303.4f's reanimator-Aura template —
    Animate Dead/Necromancy) — reads `self.source.attached_to` live at
    resolution rather than baking in a fixed object the way
    `SacrificeSpecificEffect` does, since the acting object here is only
    known once this LEAVES_BATTLEFIELD trigger actually fires.
    `GameState.remove_from_battlefield` never clears `attached_to`, so the
    just-departed Aura's own field still names the creature it was
    attached to the moment it left.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        host_id = getattr(self.source, "attached_to", None)
        if host_id is None:
            return
        host = context.state.find_object(host_id)
        if host is None or host not in context.state.battlefield:
            return
        context.engine.put_into_graveyard(host)


class ExileSpecificEffect(GameEffect):
    """Exile the exact permanents baked into this effect (RULE 406/701.5a).

    The plural counterpart of `SacrificeSpecificEffect` (same "the rules
    already fixed which objects, nothing to choose or target" shape),
    needed for a *delayed* "exile them" tail whose referent is `GameContext.
    created_objects` (MEC-12, Twinflame's "…create a token that's a copy of
    that creature… Exile **those tokens** at the beginning of the next end
    step.") — `CreateDelayedTriggerEffect`'s own ``capture="created_
    objects"`` branch already special-cases any inner effect exposing an
    ``.objects`` list (as `SacrificeSpecificEffect` does for Kiki-Jiki's
    singular "sacrifice it"), but `ExileEffect` only ever carries one
    ``.target``, silently dropping every token past the first for a
    multi-target source like Twinflame. Silently skips any object that
    already left the battlefield by the time this resolves — a token that
    died some other way first has already ceased to exist (RULE 111.7),
    so there is nothing left to move.
    """

    def __init__(
        self,
        objects: list["GameObject"],
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.objects = objects

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for obj in list(self.objects):
            if obj in context.state.battlefield:
                context.engine.exile(obj)


class DestroySpecificEffect(GameEffect):
    """Destroy the exact permanents baked into this effect (RULE 701.7).

    The destroy sibling of `SacrificeSpecificEffect`/`ExileSpecificEffect`,
    for a *delayed* "destroy it at the beginning of the next end step" tail
    (Old Hob, Alleycat Blues — "create a … token. … Destroy it at the
    beginning of the next end step.") whose referent is `GameContext.
    created_objects` / `previous_targets` (baked in by `CreateDelayedTrigger
    Effect`'s ``capture`` handling, which special-cases any inner effect
    exposing an ``.objects`` list). Unlike sacrifice, this goes through
    `RulesEngine.destroy` — so a regeneration shield or indestructible could
    still save the object, which is the printed wording's actual meaning.
    Silently skips anything already gone (RULE 111.7)."""

    def __init__(
        self,
        objects: list["GameObject"],
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.objects = objects

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for obj in list(self.objects):
            if obj in context.state.battlefield:
                context.engine.destroy(obj)


class ReturnSpecificToHandEffect(GameEffect):
    """Return the exact permanents baked into this effect to their owners'
    hands (RULE 608.2 / 400.7).

    The hand-return sibling of `SacrificeSpecificEffect`/`ExileSpecificEffect`
    /`DestroySpecificEffect`, for a *delayed* "return that creature to its
    owner's hand at the beginning of the next end step" tail (Ilharg, the
    Raze-Boar; Zara, Renegade Recruiter; Alora, Merry Thief — a "put a
    creature onto the battlefield / make it unblockable, then bounce it end
    of turn" loan). Referent baked in by `CreateDelayedTriggerEffect`'s
    ``capture`` handling, which special-cases any inner effect exposing an
    ``.objects`` list. Silently skips anything that already left the
    battlefield (RULE 111.7 / a token that ceased to exist)."""

    def __init__(
        self,
        objects: list["GameObject"],
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.objects = objects

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for obj in list(self.objects):
            if obj in context.state.battlefield:
                context.engine.return_to_hand(obj)


class ReturnUncastExiledEffect(GameEffect):
    """The "…if it wasn't cast this way" tail every optional free-cast-from-
    exile window needs: Beseech the Mirror's "put the exiled card into your
    hand", Possibility Storm's and Tibalt's Trickery's "put it on the bottom
    of their library in a random order".

    Armed as a `DelayedTrigger` alongside the window itself and baked onto
    the exiled card (``exiled_object``) — "the exiled card" names one
    specific object, nothing targetable. Being still in exile when this
    fires *is* "wasn't cast this way": casting it moves the card to the
    stack, so the check is a zone read rather than a flag anything has to
    remember to clear.
    """

    def __init__(
        self,
        exiled_object: "GameObject",
        destination: str = "hand",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.exiled_object = exiled_object
        self.destination = destination

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.exiled_object
        if obj is None or obj.zone != Zone.EXILE:
            return
        obj.face_down_in_exile = False
        if self.destination == "library_bottom":
            owner = context.state.player_by_id(obj.owner_id)
            if owner is None:
                return
            owner.remove_from_zone(obj, Zone.EXILE)
            obj.zone = Zone.LIBRARY
            owner.library.insert(0, obj)
            return
        context.engine.return_to_hand(obj)


class CastExiledFaceDownEffect(GameEffect):
    """"You may cast the exiled card without paying its mana cost if that
    spell's mana value is N or less. Put the exiled card into your hand if
    it wasn't cast this way." (Beseech the Mirror.)

    Runs right after a search whose destination was ``"exile_face_down"``,
    and claims every face-down card in the controller's exile — only that
    destination ever sets `GameObject.face_down_in_exile`, and this effect
    always clears it, so the pairing is unambiguous within one resolution.

    ``require_bargained`` gates the *cast* half on the spell having been
    bargained (RULE 701.x, `GameObject.bargained`) — the "put it into your
    hand" half is unconditional, which is why this isn't the existing
    `ConditionalEffect` wrapper around a cast-only effect.

    The window itself is `RulesEngine.grant_free_cast_window_from_exile`'s
    (Rebound's), so the card is cast through the ordinary action loop with
    full targeting rather than a stripped mid-resolution cast. **Documented
    deviation**: the real card offers that cast *during its own resolution*
    and sends the card to hand immediately afterwards; here the window
    stays open until the beginning of the end step, when the delayed
    `ReturnUncastExiledEffect` performs the "if it wasn't cast this
    way" half. The engine has no synchronous mid-resolution chooser for an
    optional cast (the same fidelity limit `ReboundFreeCastWindowEffect`
    documents), and holding the window open only ever helps the caster —
    who, on this card, has already paid for it.
    """

    def __init__(
        self,
        max_mana_value: Optional[int] = None,
        require_bargained: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.max_mana_value = max_mana_value
        self.require_bargained = require_bargained

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_state import DelayedTrigger

        source = self.source
        player = None
        if source is not None:
            player = context.state.player_by_id(source.controller_id)
        player = player or context.active_player
        if player is None:
            return
        may_cast = not self.require_bargained or bool(getattr(source, "bargained", False))
        for obj in list(player.exile):
            if not getattr(obj, "face_down_in_exile", False):
                continue
            cheap_enough = (
                self.max_mana_value is None
                or obj.card.converted_mana_cost <= self.max_mana_value
            )
            if not (may_cast and cheap_enough):
                # Never eligible to be cast — the "put it into your hand"
                # half applies straight away rather than at the end step.
                obj.face_down_in_exile = False
                context.engine.return_to_hand(obj)
                continue
            context.engine.grant_free_cast_window_from_exile(obj)
            context.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=player.id,
                    step="end",
                    scope="any",
                    effects=[ReturnUncastExiledEffect(obj, source=source)],
                    description=f"{obj.name}: auf die Hand nehmen, falls nicht gewirkt",
                )
            )


class ScrollRackEffect(GameEffect):
    """"Exile any number of cards from your hand face down." (MEC-43
    round 4F — Scroll Rack, RULE 701.20a-adjacent) — the exile-any-number
    half of the ability. Candidates are the whole hand, unlike
    `ChooseObjectsEffect` (hard-coded to `permanents_controlled_by` —
    battlefield only), so this opens `RulesEngine._request_choose_objects`
    directly rather than going through that registry effect. ``track_
    exiled_with=True`` (MEC-21) accumulates every pick's instance id onto
    this ability's own source (`GameObject.exiled_with_ids`), which
    `ScrollRackFinishEffect` reads once the choice completes — wired as
    ``then_specs``, since "how many cards to draw and which cards need
    reordering" is only known *after* the player answers. Zero cards
    exiled (a legal "any number") correctly does nothing further, since
    `_request_choose_objects` only fires ``then_specs`` once at least one
    pick was made.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        context.engine._request_choose_objects(
            player, list(player.hand), "exile", count=len(player.hand), optional=True,
            prompt="Scroll Rack: Karten verdeckt aus der Hand verbannen",
            source=self.source, track_exiled_with=True,
            then_specs=[{"type": "scroll_rack_finish", "params": {}}],
        )


class ScrollRackFinishEffect(GameEffect):
    """Scroll Rack's own back half (MEC-43 round 4F), run once the
    exile-any-number choice (`ScrollRackEffect`) completes: stamp every
    just-exiled card `GameObject.face_down_in_exile` (RULE 701.20a — the
    same flag Beseech the Mirror's own face-down exile uses, set here
    rather than at the moment of exile since `RulesEngine.
    _request_choose_objects`'s own ``"exile"`` action has no face-down
    concept of its own and several *other* cards share that action
    unchanged); put that many cards from the top of the controller's
    library into their hand (a plain "put into hand", not a draw — RULE
    121.4, the same non-draw idiom `RevealTopThenTakeAndLoseLifeEffect`
    already uses); then open the "look at the exiled cards and put them
    on top of your library in any order" decision
    (`RulesEngine.open_scroll_rack_order_choice`).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        player = _controller_of(self.source, context)
        if player is None:
            return
        ids = list(getattr(self.source, "exiled_with_ids", None) or [])
        self.source.exiled_with_ids = []
        if not ids:
            return
        for instance_id in ids:
            obj = context.state.find_object(instance_id)
            if obj is not None:
                obj.face_down_in_exile = True
        for _ in range(len(ids)):
            if not player.library:
                break
            top = player.library.pop()
            top.zone = Zone.HAND
            player.hand.append(top)
        context.engine.open_scroll_rack_order_choice(player, ids, source=self.source)


class MarchesaDelayedReturnEffect(GameEffect):
    """RULE 603.7 delayed half of "return that card to the battlefield under
    your control at the beginning of the next end step" (Marchesa, the
    Black Rose-shaped: a creature you control with a counter on it dies).
    ``dying_object`` is baked in at construction — there's nothing left to
    target once the delayed trigger fires (the same RULE 603.4 per-firing
    shape `RulesEngine._collect_impulsive_draw_triggers`/`ImpulsiveDrawEffect`
    already use for Ragavan's per-firing damaged player).
    """

    def __init__(self, dying_object: "GameObject", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.dying_object = dying_object

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_state import DelayedTrigger

        controller_id = getattr(self.source, "controller_id", None) or context.active_player.id
        inner = ReturnFromGraveyardEffect(
            target=self.dying_object,
            destination="battlefield",
            under_your_control=True,
            source=self.source,
        )
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=controller_id,
                step="end",
                scope="any",
                effects=[inner],
                description=f"{self.dying_object.name}: unter Kontrolle zurück auf das Schlachtfeld",
            )
        )


class ReturnDyingSubjectToBattlefieldEffect(GameEffect):
    """"When enchanted creature dies, return that card to the battlefield
    under its owner's control." (Gift of Immortality's first clause, PAR-60.)

    Reads the firing DIES event's ``instance_id`` (the enchanted creature,
    now in its owner's graveyard) and returns it to the battlefield under
    its **owner's** control (`context.return_from_graveyard`'s default). A
    no-op if the card has since left that graveyard.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        iid = (context.trigger_event or {}).get("instance_id")
        if iid is None:
            return
        obj = context.state.find_object(iid)
        if obj is None or obj.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(obj, "battlefield")


class GiftOfImmortalityDiesEffect(GameEffect):
    """"When enchanted creature dies, return that card to the battlefield
    under its owner's control. Return this card to the battlefield attached
    to that creature at the beginning of the next end step." (Gift of
    Immortality, PAR-60.)

    One atomic effect: (1) return the dying creature (DIES event
    ``instance_id``) from its owner's graveyard, remembering the *new*
    permanent's instance id on this Aura, then (2) arm a RULE 603.7 delayed
    trigger for the next end step that returns this Aura from the graveyard
    and re-attaches it to that remembered creature (still a legal attach —
    if it has since left, the Aura's own RULE 704.5n SBA sends it back to
    the graveyard, matching the printed "that creature" wording).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_state import DelayedTrigger

        iid = (context.trigger_event or {}).get("instance_id")
        creature = context.state.find_object(iid) if iid is not None else None
        new_id: Optional[int] = None
        if creature is not None and creature.zone == Zone.GRAVEYARD:
            context.return_from_graveyard(creature, "battlefield")
            new_id = creature.instance_id  # `return_from_graveyard` reuses the object
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=getattr(self.source, "controller_id", None)
                or context.active_player.id,
                step="end",
                scope="any",
                effects=[ReturnSelfAttachedEffect(attach_to_id=new_id, source=self.source)],
                description="Gift of Immortality: Aura re-attach",
            )
        )


class ReturnSelfAttachedEffect(GameEffect):
    """Return this Aura from the graveyard to the battlefield, attached to a
    specific permanent id (Gift of Immortality's delayed re-attach). If that
    permanent is gone, the Aura still returns and its own RULE 704.5n SBA
    handles the illegal-attachment case.
    """

    def __init__(self, attach_to_id: Optional[int] = None,
                 source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.attach_to_id = attach_to_id

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        aura = self.source
        if aura is None or aura.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(aura, "battlefield")
        host = (
            context.state.find_object(self.attach_to_id)
            if self.attach_to_id is not None else None
        )
        if host is not None and host.zone == Zone.BATTLEFIELD:
            aura.attached_to = host.instance_id
        context.recompute()


class ReturnSelfFromGraveyardEffect(GameEffect):
    """"...if this creature is in your graveyard, you may return it to your
    hand." (RULE 112.6a, Infesting Radroach) — ``obj`` is baked in at
    construction (`RulesEngine._collect_mill_return_from_graveyard_
    triggers`, the same per-firing shape `MarchesaDelayedReturnEffect`
    above uses for its own dying object), deliberately with no
    `target_spec` of its own so `_place_or_pause_trigger` never opens a
    target choice for it — "it" is always this ability's own source, never
    a pick. Re-checks ``obj``'s zone at resolution time rather than
    assuming it's still in the graveyard (RULE 603.3c/608.2b: something
    else may have moved it between trigger and resolution, e.g. an
    opponent's graveyard-hate instant).

    ``obj=None`` falls back to ``self.source`` instead — the shape a
    *granted* "when this creature dies, return it to the battlefield…"
    ability needs (Malakir Rebirth-shaped): `continuous.py`'s layer-6
    `grant_triggered_ability` binds a fresh copy of the ability onto each
    affected object with that object as ``source``, so there's no specific
    firing to bake a reference in at — "it" is simply whichever object the
    granted ability ended up on, read live the same way `RegenerateEffect`'s
    self mode reads ``self.source``. ``tapped``/``under_your_control``
    (RULE 400.7's "under **its owner's** control" is the default;
    ``under_your_control`` is only for the rarer "under **your** control"
    phrasing) cover the two real variants beyond the plain Infesting
    Radroach shape.
    """

    def __init__(
        self,
        obj: Optional["GameObject"] = None,
        destination: str = "hand",
        source: Optional["GameObject"] = None,
        tapped: bool = False,
        under_your_control: bool = False,
        transformed: bool = False,
    ) -> None:
        super().__init__(source)
        self.obj = obj
        self.destination = destination
        self.tapped = tapped
        self.under_your_control = under_your_control
        #: "…return it to the battlefield tapped **and transformed** under
        #: its owner's control." (Ojer Axonil, Deepest Might) —
        #: `RulesEngine.return_from_graveyard`'s own ``transformed`` flag.
        self.transformed = transformed

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.obj or self.source
        if obj is None or obj.zone != Zone.GRAVEYARD:
            return
        controller_id = None
        if self.under_your_control and self.destination == "battlefield":
            player = _controller_of(self.source, context)
            controller_id = player.id if player is not None else None
        # `self.tapped` had been accepted (Malakir Rebirth's own granted
        # "return it to the battlefield **tapped**…") but never actually
        # applied — a dormant bug, since `RulesEngine.return_from_graveyard`
        # reads "tapped" off the ``destination`` string itself, not a
        # separate flag.
        destination = (
            "battlefield_tapped" if self.tapped and self.destination == "battlefield"
            else self.destination
        )
        context.return_from_graveyard(
            obj, destination, controller_id=controller_id, transformed=self.transformed,
        )
        if self.tapped and self.destination == "battlefield":
            obj.tapped = True


class SacrificeObjectEffect(GameEffect):
    """Sacrifice one specific, already-known permanent (RULE 701.17) — the
    delayed half of "sacrifice the creature at the beginning of the next end
    step" (Sneak Attack/Meek Attack-shaped): baked in at arm time, since
    there's no target left to choose once the delayed trigger fires.
    """

    def __init__(self, obj: "GameObject", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.obj = obj

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.obj in context.state.battlefield:
            context.engine.put_into_graveyard(self.obj)


class CheatCreatureFromHandEffect(GameEffect):
    """"You may put a creature card from your hand onto the battlefield.
    That creature gains haste. Sacrifice the creature at the beginning of
    the next end step." (Sneak Attack/Meek Attack-shaped — RULE 701 "cheat
    into play" plus a RULE 603.7 delayed sacrifice tail). ``max_total_pt``
    is Meek Attack's own "total power and toughness 5 or less" filter
    (``None`` for Sneak Attack's unrestricted version). ``subtypes`` is an
    optional OR-filter for cards such as Incandescent Soulstoke's Elemental
    restriction. The controller chooses the eligible card, including the
    option not to put one onto the battlefield; that choice has to survive
    a session snapshot, so it uses `RulesEngine._request_choose_objects`
    rather than a resolution-time callback.
    """

    def __init__(
        self,
        max_total_pt: Optional[int] = None,
        subtypes: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.max_total_pt = max_total_pt
        self.subtypes = tuple(str(subtype) for subtype in (subtypes or []) if subtype)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_state import DelayedTrigger

        player = _controller_of(self.source, context)
        if player is None:
            return
        from .. import continuous  # function-scoped: avoid the module cycle

        candidates = [
            obj for obj in player.hand
            if obj.card.is_creature
            and (self.max_total_pt is None or (
                (obj.card.power or 0) + (obj.card.toughness or 0) <= self.max_total_pt
            ))
            # RULE 702.73a: changeling is visible in every zone, including
            # the hand, through `continuous.has_subtype`.
            and (not self.subtypes or any(continuous.has_subtype(obj, subtype) for subtype in self.subtypes))
        ]
        if not candidates:
            return
        criterion = " oder ".join(self.subtypes) if self.subtypes else "Kreatur"
        context.engine._request_choose_objects(
            player,
            candidates,
            action="hand_to_battlefield_haste_sacrifice",
            count=1,
            optional=True,
            prompt=f"{criterion}-Kreaturenkarte aus deiner Hand ins Spiel bringen",
            source=self.source,
        )


class TakeExtraTurnEffect(GameEffect):
    """Take an extra turn after this one (RULE 500.7) — Final Fortune, the
    Time Warp family. Queues the effect's controller onto
    `GameState.extra_turns`; `GameEngine.begin_turn` takes it right after the
    current turn.

    ``count`` > 1 (MEC-46 — Expropriate's "for each time vote, take an
    extra turn after this one") queues that many, all for the same player:
    RULE 500.7 stacks them so they are taken back to back. The vote's own
    per-vote scaling (`_tally_and_apply_vote`) multiplies this ``count`` by
    the number of "time" votes.
    """

    def __init__(self, count: Any = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        # Not cast to ``int`` here (PAR-67, Sage of Hours): a `bind`
        # (RULE 608.2) node substitutes its sentinel only at `apply()` time,
        # so a `bind`-measured ``count`` still reads as ``"$n"`` while
        # `target_specs` builds every composed effect once, uncoerced, just
        # to enumerate targeting requirements — the same "store raw, coerce
        # lazily" idiom `AddCountersEffect.amount` and friends already use.
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        try:
            count = max(0, int(self.count))
        except (TypeError, ValueError):
            return
        for _ in range(count):
            context.take_extra_turn(player)


class ControlPlayerEffect(GameEffect):
    """MEC-51 (RULE 720): "You control target opponent during that player's
    next turn." (Mindslaver, Emrakul the Promised End's cast trigger, Sorin
    Markov's −7, Worst Fears) — and ``scope="combat"`` for "…during their
    next combat phase." (Secret of Bloodbending).

    Installs a `GameState.TurnControl` (``"waiting"``) naming the effect's
    controller and the chosen player; `RulesEngine._advance_turn_controls`
    then runs the `TURN_BEGIN` state machine. A fresh control over a player
    who already has one replaces it (last effect wins — RULE 720.6-ish),
    rather than stacking two.

    ``target_kind`` — ``"opponent"`` (the usual "target opponent") or
    ``"player"`` (Worst Fears' "target player"). A self-target does nothing.
    """

    def __init__(
        self,
        scope: str = "turn",
        target_kind: str = "opponent",
        grant_extra_turn_after: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.scope = scope if scope in ("turn", "combat") else "turn"
        self.grant_extra_turn_after = bool(grant_extra_turn_after)
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_state import TurnControl

        controller = _controller_of(self.source, context)
        target = targets[0] if targets else None
        if controller is None or target is None:
            return
        controlled_id = getattr(target, "id", None)
        if controlled_id is None or controlled_id == controller.id:
            return
        state = context.state
        state.turn_controls = [
            tc for tc in state.turn_controls if tc.controlled_id != controlled_id
        ]
        tc = TurnControl(
            controlled_id=controlled_id,
            controller_id=controller.id,
            install_turn=state.internal_turn.number,
            scope=self.scope,
            source_name=getattr(getattr(self.source, "card", None), "name", "") or "",
        )
        tc.grant_extra_turn_after = self.grant_extra_turn_after
        state.turn_controls.append(tc)


class WordOfCommandEffect(GameEffect):
    """MEC-51b (RULE 720 / Word of Command): "Look at target opponent's hand
    and choose a card from it. You control that player until ~ finishes
    resolving. The player plays that card if able."

    `RulesEngine._request_word_of_command` opens a `word_of_command`
    `pending_choice` addressed to *this effect's controller* (the hand is
    revealed to them via `game_session`), listing the target's hand;
    `_resume_word_of_command` then has the target player play the
    chosen card — `play_land` if it's a land they can play, else
    `cast_without_paying` (the same effect-driven free-cast primitive
    cascade/discover use — see that method).

    **Documented simplifications:** the card is cast *without its mana cost
    paid* (so the RULE 720 "only land mana, only for that card" restriction
    is moot) and, like every effect-driven free cast in this engine, it is
    cast without target selection (RULE 601.2c). "If able" is enforced only
    for a land (`can_play_land`).
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="opponent")

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        target = targets[0] if targets else None
        if controller is None or target is None or getattr(target, "id", None) is None:
            return
        context.engine._request_word_of_command(controller, target, source=self.source)


class ExtraCombatPhaseEffect(GameEffect):
    """"After this combat phase, there is an additional combat phase[,
    followed by an additional main phase]." (RULE 500.4-adjacent —
    Combat Celebrant/Godo/Aurelia-shaped triggered abilities; World at
    War/Aggravated Assault's own activated-ability wording sets
    ``main_phase_too``). The same "queue now, the turn loop drains it
    later" shape `TakeExtraTurnEffect`/`GameState.extra_turns` already
    use — this effect can't reach `GameEngine._turn_steps` directly (only
    `GameContext`/`RulesEngine` are visible to it), so it appends to
    `GameState.pending_extra_combats` instead and `GameEngine.
    advance_step` drains it (via `insert_additional_combat_phase`) before
    running the next step.
    """

    def __init__(self, main_phase_too: bool = False, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.main_phase_too = main_phase_too

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        context.state.pending_extra_combats.append(self.main_phase_too)


class GrantProtectionEffect(GameEffect):
    """"Target creature gains protection from the color of your choice until
    end of turn" (RULE 702.16 — Mother of Runes; Giver of Runes adds a
    "colorless" option and targets *another* creature).

    Opens an interactive `grant_protection_color` choice (`RulesEngine.
    grant_protection_choice`) for the effect's controller; the chosen quality
    lands in ``target.temp_protections`` (cleared at cleanup, RULE 514.2).
    ``allow_colorless`` is Giver of Runes' extra option.
    """

    def __init__(
        self,
        target_kind: Optional[str] = "creature_you_control",
        allow_colorless: bool = False,
        previous_subject: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.allow_colorless = allow_colorless
        #: "~ gains protection from the color of your choice until end of
        #: turn" (Jareth, Cartel Aristocrat, …) — no RULE 115 target, act on
        #: this effect's own source.
        self.previous_subject = previous_subject
        self.target_spec = (
            TargetSpec(kind=target_kind)
            if target_kind is not None and not previous_subject else None
        )

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        if self.previous_subject:
            recipients = list(context.previous_targets)
        elif self.target_spec is None:
            recipients = [self.source] if self.source is not None else []
        else:
            recipients = [targets[0]] if targets else []
        for target in recipients:
            if target is not None:
                context.engine.grant_protection_choice(target, controller, self.allow_colorless)


class GrantFixedProtectionGroupEffect(GameEffect):
    """Give each selected creature protection from one fixed colour this turn."""

    def __init__(
        self, color: str, selector: str = "creatures_you_control",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.color = str(color).upper()
        self.selector = selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..continuous import group_selector_objects

        controller_id = getattr(self.source, "controller_id", None)
        for obj in group_selector_objects(context.state, controller_id, self.selector, src=self.source):
            obj.temp_protections.add(self.color)


class GrantCantBeTargetOfSpellColorEffect(GameEffect):
    """"Creatures you control can't be the targets of blue or black spells
    this turn." (Autumn's Veil, MEC-41) — an untargeted, group-scoped RULE
    115 targeting restriction, narrower than protection/hexproof (see
    `targeting._targetable_by`'s own docstring for why those don't fit):
    only refuses a *spell* whose own color is in ``colors``, checked
    against the new turn-scoped `GameObject.temp_cant_be_target_of_spell_
    colors` (cleared at cleanup like `temp_protections`).
    """

    def __init__(
        self, colors: Optional[list[str]] = None, selector: str = "creatures_you_control",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.colors = [str(c).upper() for c in (colors or [])]
        self.selector = selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if not self.colors:
            return
        from .. import continuous  # avoid the continuous↔effects import cycle

        controller_id = getattr(self.source, "controller_id", None)
        for obj in continuous.group_selector_objects(
            context.state, controller_id, self.selector, src=self.source,
        ):
            obj.temp_cant_be_target_of_spell_colors.update(self.colors)


class LoseGameEffect(GameEffect):
    """The effect's controller loses the game (RULE 104.3a) — Final Fortune's
    "you lose the game" downside, resolved via the same `_player_loses` path
    an SBA loss uses."""

    def __init__(self, reason: str = "effect", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.reason = reason

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.lose_game(player, self.reason)

register(globals())
