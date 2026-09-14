"""Counters, continuous modifications, token creation, copying, and copying choices."""
from __future__ import annotations

from .core import GameEffect
from ._runtime import install, register

install(globals())

class BecomePreparedEffect(GameEffect):
    """A preparation card's own permanent becomes prepared (RULE 722.3a).

    Always self-only, unlike `TransformEffect` — RULE 722.3a's "~ becomes
    prepared" has no targeted form on any real card. Delegates to
    `RulesEngine.make_prepared`, which creates the exiled prepare-spell
    copy (RULE 722.3c) and is itself a no-op if the source is already
    prepared or has no prepare spell.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.make_prepared(self.source)


#: `AddCountersEffect.selector`'s closed vocabulary — a mass, untargeted
#: "put a counter on each …" (RULE 601.2c), the group `continuous.
#: group_selector_objects` already resolves for pump/anthem clauses.
#: ``each_other_creature_you_control`` (MEC-11's Bellowing Aegisaur — "put a
#: +1/+1 counter on each **other** creature you control") is the RULE 109.5
#: "another" exclusion of the ability's own source, `group_selector_objects`'s
#: existing ``"other_creatures_you_control"`` affects value.
#: ``each_other_planeswalker_you_control`` (Ajani Steadfast's own "-2",
#: MEC-30) — the planeswalker-scoped sibling of ``each_other_creature_you_
#: control`` just above, `group_selector_objects`'s own ``"other_
#: planeswalkers_you_control"`` affects value.
_ADD_COUNTERS_SELECTORS: frozenset[str] = frozenset(
    {
        "each_creature_you_control", "each_other_creature_you_control",
        "each_other_planeswalker_you_control",
        # RULE 122.1a — -1/-1-counter decks commonly affect every creature,
        # every other creature, or the creatures an opponent controls.
        "each_creature", "each_other_creature", "each_creature_opponents_control",
    }
)
#: Maps each `_ADD_COUNTERS_SELECTORS` member to the `continuous.
#: group_selector_objects` ``affects`` value it resolves against.
_ADD_COUNTERS_SELECTOR_AFFECTS: dict[str, str] = {
    "each_creature_you_control": "creatures_you_control",
    "each_other_creature_you_control": "other_creatures_you_control",
    "each_other_planeswalker_you_control": "other_planeswalkers_you_control",
    "each_creature": "all_creatures",
    "each_other_creature": "all_other_creatures",
    "each_creature_opponents_control": "creatures_opponents_control",
}


class AddCountersEffect(GameEffect):
    """Put ``amount`` +1/+1 counters on a target creature — or on the source.

    Untargeted, it buffs the effect's own source (an activated "put a +1/+1
    counter on this creature"); with a ``target_kind`` it targets (RULE 122),
    optionally as an RULE 115.1a "up to one" pick, or ``count`` > 1 several
    independent targets at once (the same shape `DestroyEffect.count` uses —
    "put a +1/+1 counter on each of up to two target creatures", the
    Support-keyword-shaped family; note ``count`` here is the *target*
    count, distinct from ``amount``, the number of counters placed on each).
    ``selector`` (`_ADD_COUNTERS_SELECTORS` — RULE 601.2c, Vastwood Surge's
    "put two +1/+1 counters on each creature you control") is instead a
    mass, untargeted effect over the group `continuous.
    group_selector_objects` already resolves for pump/anthem clauses —
    mirrors `DealDamageEffect.selector`'s "no `target_spec` at all" shape.
    ``subtypes`` (Vault 12: The Necropolis's own chapter III — "each
    creature you control that's a Zombie or Mutant") further narrows that
    same mass group to an OR-combined creature-subtype filter, checked
    against the *live* object (unlike a DIES trigger's own subtype filter,
    every affected creature here is still on the battlefield) — a real,
    broader gap beyond this one card (tribal mass-counter effects are common).
    """

    def __init__(
        self,
        amount: int = 1,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
        kind: str = "+1/+1",
        optional: bool = False,
        selector: Optional[str] = None,
        count: int = 1,
        count_max: Optional[int] = None,
        subtypes: Optional[list[str]] = None,
        trigger_subject_key: Optional[str] = None,
        divided: bool = False,
        amount_from_trigger_event: Optional[str] = None,
        x_multiplier: Optional[int] = None,
        amount_from_count_selector: Optional[str] = None,
        amount_if_trigger_subject_subtype: Optional[list[str]] = None,
        amount_if_trigger_subject_subtype_value: Optional[int] = None,
        creature_filter: Optional[dict] = None,
        count_selector: Optional[str] = None,
        ring_bearer: bool = False,
        previous_subject: bool = False,
        distinct_from_others: bool = False,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        #: RULE 109.5 — "put N -1/-1 counters on **another** target creature"
        #: / "a **third** target creature" (Incremental Blight / Incremental
        #: Growth). Each escalating clause is its own `AddCountersEffect`
        #: with its own RULE 115 target; this flag forbids re-picking a
        #: creature an earlier clause already chose
        #: (`TargetSpec.distinct_from_others`, enforced across requirements).
        self.distinct_from_others = bool(distinct_from_others)
        #: "tap [up to one] target creature and put a stun counter on **it**."
        #: (Champions of the Shoal &c., PAR-30) — "it" is the creature the
        #: *preceding* clause of this same body just tapped/targeted
        #: (`GameContext.previous_targets`), the pronoun idiom `TapEffect`/
        #: `FightEffect`/`GoadEffect` already use. Distinct from
        #: `trigger_subject_key` (a RULE 603.1 group-subject read).
        self.previous_subject = previous_subject
        #: MEC-46 (Galadriel, Elven-Queen): "put a +1/+1 counter on your
        #: Ring-bearer" — no RULE 115 target, resolved fresh against
        #: `continuous.ring_bearer_of` for this effect's controller.
        self.ring_bearer = ring_bearer
        #: MEC-27: "put X +1/+1 counters on ~, where X is the number of
        #: `<noun phrase>` you control." — `subgrammars.DEVOTION`'s wider
        #: RULE 613.7c reading, previously wired into damage/lose_life only.
        #: Same `continuous.count_selector` lookup, resolved live at
        #: resolution the same way `DealDamageEffect.amount_from_count_
        #: selector` already does; deliberately only wired into the plain
        #: self/single-target branch below, mirroring `amount_from_trigger_
        #: event`'s own single-recipient scope just above.
        self.amount_from_count_selector = amount_from_count_selector
        #: "Whenever you gain life, put that many +1/+1 counters on ~/target
        #: X." (Ageless Entity/Treebeard-shaped) — the event field name
        #: (``"amount"``) to read off `GameContext.trigger_event` at
        #: resolution, overriding ``amount`` when set. Same idiom as
        #: `LoseLifeEffect.amount_from_trigger_event`; deliberately only
        #: wired into the plain self/single-target branches below, since
        #: "that many" is inherently a single recipient, never a mass
        #: selector or an N>=2 multi-target pick.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "~ enters with twice X +1/+1 counters on it." (Banquet Guests) —
        #: a self-only ETB trigger reading the *source's own* announced
        #: {X} (`GameObject.x_paid`, RULE 107.3c — set at cast time,
        #: already present by the time this same object's own ENTERS_
        #: BATTLEFIELD trigger resolves) times this multiplier. Distinct
        #: from `_substitute_x`'s ``"x"`` sentinel, which only rewrites a
        #: *spell's own* resolution effects — a separately-fired triggered
        #: ability has no `StackItem.x` of its own to substitute against.
        self.x_multiplier = x_multiplier
        # PAR-15: "distribute N +1/+1 counters among any number of target
        # creatures" (Blessings of Nature/Jugan, the Rising Star/Verdurous
        # Gearhulk) — ``amount`` is then a *pool* split across whichever
        # targets were chosen (as evenly as possible, no explicit
        # ``division`` list — same documented simplification
        # `DealDamageEffect.divided`/`_apply_divided` uses for "damage
        # divided as you choose"), unlike the plain ``count`` > 1 shape
        # above where every target gets the *full* ``amount`` independently.
        self.divided = divided
        # The counter type: "+1/+1" (default) or "-1/-1" (RULE 122). Both shift
        # net P/T the same machinery, just with opposite sign.
        self.kind = kind
        self.selector = selector if selector in _ADD_COUNTERS_SELECTORS else None
        self.subtypes = [s.lower() for s in subtypes] if subtypes else None
        #: "Whenever a creature you control is dealt damage, put a +1/+1
        #: counter on **it**." (MEC-11's Rite of Passage) — an untargeted
        #: "it" here is *not* the ability's own source (Rite of Passage
        #: itself, an Enchantment) the way ``target_kind=None`` everywhere
        #: else in this class means, but whichever *group member* the
        #: RULE 603.1 trigger actually fired for. `parser/oracle/
        #: segmenter.py`'s group-subject damage-recipient handler sets this
        #: to the same event key (``"target_id"``) `effect_binder.
        #: _subject_event_key` resolves the trigger's own condition
        #: against, so the two always agree on which object "it" is.
        self.trigger_subject_key = trigger_subject_key
        #: "…put a +1/+1 counter on it. If it's a Unicorn, put 2 +1/+1
        #: counters on it instead." (Emiel the Blessed) — an "instead"
        #: override on the *trigger subject*'s own subtype, checked only
        #: alongside ``trigger_subject_key`` (the "it" both clauses share).
        #: Not a general "if X, do A instead of B" primitive (that stays a
        #: real open gap — see `BACKLOG.md`'s kicker "instead" note) — just
        #: this one recurring "bonus for a named creature type" shape.
        self.amount_if_trigger_subject_subtype = (
            [s.lower() for s in amount_if_trigger_subject_subtype]
            if amount_if_trigger_subject_subtype else None
        )
        self.amount_if_trigger_subject_subtype_value = amount_if_trigger_subject_subtype_value
        #: RULE 702.134a Mentor — "put a +1/+1 counter on target attacking
        #: creature with lesser power": a `matches_object_filter` dict
        #: (``{"attacking": True, "power_vs_reference": "less"}``) narrowing
        #: the RULE 115 target, evaluated against the ability's own source as
        #: the ``reference`` (`targeting._creature_matches_filter`). PAR-24.
        self.creature_filter = creature_filter
        if self.selector is None and target_kind is not None:
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max,
                creature_filter=creature_filter,
                distinct_from_others=self.distinct_from_others,
                # "Support X." (RULE 702.163, PAR-29 — Blitzball Stadium/The
                # Crowd Goes Wild) — "up to X target creatures" where X is
                # this spell/ability's own announced {X}, the identical
                # `TargetSpec.count_selector="source_x_paid"` reading "up
                # to X target creatures phase out" (March of Swirling
                # Mist)/"each of X target creatures connive" (Change of
                # Plans) already use — resolved at announce time off
                # `GameObject.x_paid`, not this class's own ``count``.
                count_selector=count_selector,
            )

    def target_polarity(self) -> Optional[str]:
        # "-1/-1"/"stun" counters are a downgrade for whoever's stuck with
        # them; every other kind this class ever places (+1/+1 chief among
        # them) is a buff.
        return "harmful" if self.kind in ("-1/-1", "stun") else "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        self._place_counters(context, targets)
        # RULE 613.1: derived P/T updates continuously, so a *later* clause of
        # the same resolution ("Put a +1/+1 counter on target creature you
        # control. It deals damage equal to its power …" — Archdruid's Charm)
        # must read the boosted value now, not at the next SBA. Every other
        # P/T-modifying one-shot (`PumpEffect`, `GrantUntilEffect`) already
        # recomputes at the end of its own `apply` for the same reason;
        # `AddCountersEffect` was the gap that kept `counter_then_fightlike_
        # damage` a fused type (ENG-37 B4).
        context.recompute()

    def _place_counters(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.x_multiplier is not None:
            x_paid = getattr(self.source, "x_paid", 0) or 0
            self.amount = self.x_multiplier * x_paid
        if self.ring_bearer:
            from ..continuous import ring_bearer_of  # avoid the continuous↔effects cycle

            controller = _controller_of(self.source, context)
            bearer = ring_bearer_of(context.state, controller) if controller is not None else None
            if bearer is not None:
                context.add_counters(bearer, self.amount, self.kind, source=self.source)
            return
        if self.trigger_subject_key:
            if self.trigger_subject_key == "remembered":
                # The deferred sibling of the live-event read below — see
                # `PayCostThenEffect.remember_trigger_subject`.
                obj_id = getattr(self.source, "remembered_instance_id", None)
            else:
                event = context.trigger_event
                obj_id = (event or {}).get(self.trigger_subject_key)
            target = context.state.find_object(obj_id) if obj_id is not None else None
            if target is not None:
                amount = self.amount
                if self.amount_if_trigger_subject_subtype and self.amount_if_trigger_subject_subtype_value is not None:
                    sub = target.card.type_line.partition("—")[2].strip().lower().split()
                    if any(s in sub for s in self.amount_if_trigger_subject_subtype):
                        amount = self.amount_if_trigger_subject_subtype_value
                context.add_counters(target, amount, self.kind, source=self.source)
            return
        if self.selector in _ADD_COUNTERS_SELECTORS:
            from ..continuous import group_selector_objects  # avoid the continuous↔effects cycle
            from .. import combat  # local: combat↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            affects = _ADD_COUNTERS_SELECTOR_AFFECTS.get(self.selector, "creatures_you_control")
            for obj in group_selector_objects(context.state, controller_id, affects, src=self.source):
                if self.subtypes is not None:
                    sub = obj.card.type_line.partition("—")[2].strip().lower().split()
                    if not any(s in sub for s in self.subtypes):
                        continue
                # "put a -1/-1 counter on each **nonblack** creature."
                # (Midnight Banshee) — a `matches_object_filter` dict
                # (``{"without_color": "B"}``) narrowing the mass group,
                # the same key the single-target branch already honours.
                if self.creature_filter and not combat.matches_object_filter(
                    obj, self.creature_filter, state=context.state
                ):
                    continue
                context.add_counters(obj, self.amount, self.kind, source=self.source)
            return
        if self.target_spec is not None and (
            self.target_spec.count_selector or self.target_spec.effective_count != 1
        ):
            # `effective_count` is a static field on a frozen dataclass —
            # it has no live board access, so a `count_selector`-sized spec
            # ("Support X.") always reads back as its printed ``count``
            # (1), never the real live value. `targets` was already
            # gathered by the *real*, state-aware `targeting.resolved_
            # count`, so take it whole rather than re-slicing to that
            # wrong static cap (the same `count_selector or …` guard
            # `GoadEffect.apply` already uses for the identical reason).
            chosen = (
                list(targets or [])
                if self.target_spec.count_selector
                else _chosen_targets(targets, self.target_spec.effective_count)
            )
            if not chosen:
                return
            if self.divided:
                total = self.amount if isinstance(self.amount, int) else 0
                base, extra = divmod(total, len(chosen))
                shares = [base + (1 if i < extra else 0) for i in range(len(chosen))]
            else:
                shares = [self.amount] * len(chosen)
            for target, share in zip(chosen, shares):
                if share > 0:
                    context.add_counters(target, share, self.kind, source=self.source)
            return
        if self.previous_subject and self.divided:
            # "…then distribute three stun counters among any number of
            # `<the creatures a previous clause just tapped>`" (Crashing
            # Wave, PAR-30) — a ``divided`` pool split across every object
            # `GameContext.previous_targets` carries, no fresh RULE 115
            # target. **Documented simplification:** "…your opponents
            # control" is dropped (a caster taps opponents' creatures to
            # stun them; stun on your own is strictly a downside), and the
            # split is auto-even rather than an interactive "any number of"
            # choice — the same call `divided`'s own targeted branch makes.
            prev = [t for t in context.previous_targets if t is not None]
            if not prev:
                return
            total = self.amount if isinstance(self.amount, int) else 0
            base, extra = divmod(total, len(prev))
            for i, one in enumerate(prev):
                share = base + (1 if i < extra else 0)
                if share > 0:
                    context.add_counters(one, share, self.kind, source=self.source)
            return
        if self.target_spec is not None:
            target = targets[0] if targets else None
        elif self.previous_subject:
            prev = list(context.previous_targets)
            target = prev[0] if prev else None
            if target is None:
                return
        else:
            target = self.source

        def _from_count_selector() -> int:
            from .. import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            return continuous.count_selector(
                context.state, controller_id, self.amount_from_count_selector, source=self.source,
            )

        # Same override as the `trigger_subject_key` branch above, for a
        # target reached the ordinary way instead — e.g. `targets` threaded
        # in from a deferred `pay_cost_then` "if you do" branch (Emiel the
        # Blessed), where `context.trigger_event`'s window has already
        # closed by the time this resolves.
        subtype_matches = False
        if (
            target is not None and self.amount_if_trigger_subject_subtype
            and self.amount_if_trigger_subject_subtype_value is not None
        ):
            sub = target.card.type_line.partition("—")[2].strip().lower().split()
            subtype_matches = any(s in sub for s in self.amount_if_trigger_subject_subtype)

        amount = self._resolve_amount_override(
            self.amount,
            [
                (
                    bool(self.amount_from_trigger_event),
                    lambda: int((context.trigger_event or {}).get(self.amount_from_trigger_event) or 0),
                ),
                (bool(self.amount_from_count_selector), _from_count_selector),
                (subtype_matches, lambda: self.amount_if_trigger_subject_subtype_value),
            ],
        )
        if target is not None and amount > 0:
            context.add_counters(target, amount, self.kind, source=self.source)


class RenownEffect(GameEffect):
    """RULE 702.112b: Renown N's own triggered-ability body — put ``amount``
    +1/+1 counters on this creature and it becomes renowned. A single
    atomic effect (not `AddCountersEffect` alone) since the "becomes
    renowned" flag has to flip together with the counters — it's what the
    keyword's own "if it isn't renowned" guard (`effect_binder.
    _keyword_triggered_abilities`) checks to fire only once per creature.
    """

    def __init__(self, amount: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        context.add_counters(self.source, self.amount, "+1/+1", source=self.source)
        self.source.renowned = True
        context.fire_event(GameEvent(EventType.RENOWNED, instance_id=self.source.instance_id))


class AmassEffect(GameEffect):
    """RULE 701.48 Amass `<Type>` N: "If you don't control an Army creature,
    create a 0/0 black Army `<Type>` creature token first. Put N +1/+1
    counters on an Army you control." (Orcish Bowmasters, MEC-42) —
    auto-picks the first Army you control when one already exists and
    there's more than one to choose from (RULE 701.48b does let the
    amassing player choose), the same "no chooser for an equally-valid
    pick" idiom this engine's other untargeted picks already use, since
    nothing here differentiates otherwise-identical Army tokens.
    """

    def __init__(self, subtype: str = "Zombies", count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.subtype = str(subtype)
        self.count = max(0, int(count))

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import synthesize_token_card  # avoid a services↔effects cycle

        player = _controller_of(self.source, context)
        if player is None or self.count <= 0:
            return
        army = next(
            (
                o for o in context.state.battlefield
                if o.controller_id == player.id and o.is_creature
                and "army" in o.card.type_line.partition("—")[2].strip().lower().split()
            ),
            None,
        )
        if army is None:
            card = synthesize_token_card(
                self.subtype, power=0, toughness=0, colors=["B"],
                subtypes=["Army", self.subtype],
            )
            made = context.create_token(player.id, card, 1) or []
            context.created_objects.extend(made)
            army = made[0] if made else None
        if army is not None:
            context.add_counters(army, self.count, "+1/+1", source=self.source)


class PayLifeEqualToOpponentsCombatDamagedDrawThatManyEffect(GameEffect):
    """"You may pay X life, where X is the number of opponents that were
    dealt combat damage this turn. If you do, draw X cards." (Tymna the
    Weaver, MEC-42) — computes X once (`continuous.count_selector`'s new
    ``"opponents_dealt_combat_damage_this_turn"``), then opens the
    general `RulesEngine._request_pay_cost_then` choice with a
    *dynamically built* ``ActivationCost(pay_life=X)`` and a matching
    draw-X-cards follow-up, rather than `PayCostThenEffect`'s own fixed
    cost-text shape (which has no way to plug in a live board count).
    X=0 skips the choice outright — there's nothing to gain from paying
    0 life to draw 0 cards, the same "don't stall on a choice nobody can
    meaningfully act on" idiom `_request_pay_cost_then` already applies
    to an unpayable cost.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .. import continuous  # function-scoped: avoid the continuous<->effects import cycle
        from ..costs import ActivationCost  # function-scoped: costs<->effects import cycle

        player = _controller_of(self.source, context)
        if player is None:
            return
        x = continuous.count_selector(context.state, player.id, "opponents_dealt_combat_damage_this_turn")
        if x <= 0:
            return
        context.engine._request_pay_cost_then(
            player, ActivationCost(pay_life=x), [{"type": "draw", "params": {"count": x}}], self.source,
        )


class GrantUntilEffect(GameEffect):
    """RULE 611: create a continuous effect that lasts for a stated duration.

    The resolve-time counterpart of a permanent's printed static ability, and
    the general form of every "…until end of turn"-shaped grant: it builds a
    `StaticAbility` (so the grant goes through the RULE 613 layer engine like
    any other, rather than being a special case read by whoever happens to
    look) and parks it in `GameState.floating_statics`, where
    `game/durations.py` sweeps it at the window its ``duration`` names.

    Why this exists next to the ``temp_power``/``temp_keywords`` fields the
    shipped pump/grant effects use: those fields *are* "until end of turn" —
    they're cleared wholesale at cleanup (RULE 514.2) and have nowhere to
    record any other ending. "Until your next turn", "until end of combat"
    and RULE 611.2b's "for as long as `<condition>`" are unreachable that
    way. Existing effects are deliberately left on the old path; anything
    needing a *different* duration comes here.

    ``static`` is the `EffectSpec`-shaped payload for the underlying static
    (``{"type": "grant_keyword", "params": {...}}``), built by the binder
    from the same whitelisted registry every printed static goes through —
    card text never reaches the layer engine except as a registered type.
    """

    def __init__(
        self,
        static: Optional[dict[str, Any]] = None,
        duration: str = "end_of_turn",
        target_kind: Optional[str] = "creature",
        optional: bool = False,
        count: int = 1,
        condition: Optional[dict[str, Any]] = None,
        previous_subject: bool = False,
        self_subject: bool = False,
        extra_statics: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.static = dict(static or {})
        #: Additional `EffectSpec`-shaped static payloads applied to the
        #: **same** chosen targets under the same duration/condition as
        #: ``static`` — "target land … becomes a 5/5 green Plant Boar
        #: creature **with haste** …" (Hedge Whisperer) is a layer-4
        #: `type_change` plus a layer-6 `grant_keyword`, and the target is
        #: picked once. Each is built and parked exactly like ``static``.
        self.extra_statics = [dict(s) for s in (extra_statics or [])]
        self.duration = duration
        self.condition = dict(condition) if condition else None
        #: Apply to whatever the *previous clause* of this ability targeted
        #: ("Tap target land. It doesn't untap … for as long as ~ remains
        #: tapped.") instead of declaring a target of this effect's own.
        self.previous_subject = previous_subject
        #: MEC-46: apply to this effect's own source, no RULE 115 target
        #: ("~ gains protection from each color …" — Council Guardian,
        #: resolved through the vote's `winner_specs` with no duration).
        self.self_subject = self_subject
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional, count=count)
            if target_kind is not None and not previous_subject and not self_subject
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .. import durations  # local: durations imports effects' siblings

        payloads = [self.static, *self.extra_statics]
        if not any(
            p.get("type") and EffectRegistry.is_registered(str(p.get("type")))
            for p in payloads
        ):
            return  # fail closed — nothing registered to grant

        controller_id = getattr(self.source, "controller_id", None)
        # Chosen targets are resolved once and shared by every payload.
        chosen_ids: Optional[list[int]] = None
        if self.target_spec is not None or self.previous_subject or self.self_subject:
            if self.self_subject:
                chosen = [self.source] if self.source is not None else []
            elif self.previous_subject:
                chosen = list(context.previous_targets)
            else:
                chosen = list(targets or [])[: self.target_spec.effective_count]
            chosen_ids = [
                t.instance_id for t in chosen if getattr(t, "instance_id", None) is not None
            ]
            if not chosen_ids:
                return

        for payload in payloads:
            self._park_static(context, durations, payload, controller_id, chosen_ids)
        # A new continuous effect changes derived characteristics immediately
        # (RULE 613.1) — the caller's SBA pass would get there anyway, but a
        # grant whose effect isn't visible until then reads as a bug.
        context.recompute()

    def _park_static(
        self, context: GameContext, durations: Any, static_payload: dict[str, Any],
        controller_id: Optional[str], chosen_ids: Optional[list[int]],
    ) -> None:
        spec_type = static_payload.get("type")
        if not spec_type or not EffectRegistry.is_registered(str(spec_type)):
            return  # fail closed — an unregistered static grants nothing
        params = dict(static_payload.get("params") or {})
        # `RulesEngine._substitute_x` walks a one-shot effect's own
        # magnitude fields, not a nested `static.params` dict — so an
        # X-scaled grant ("Creatures you control have base power and
        # toughness X/X until end of turn" — Biomass Mutation / Katara,
        # Water Tribe's Hope) still carries the ``"x"`` sentinel here.
        # Resolve it against the spell/ability's announced X (RULE 107.3c),
        # stamped on the source at cast/activate time.
        x_paid = getattr(self.source, "x_paid", 0) or 0
        for k in ("power", "toughness", "count", "amount"):
            if params.get(k) == "x":
                params[k] = x_paid
            elif params.get(k) == "-x":
                params[k] = -x_paid
        ability = EffectRegistry.create(str(spec_type), params)
        if not isinstance(ability, StaticAbility):
            return
        ability.source = self.source
        # RULE 613.7b (MEC-43 round 4E): this continuous effect's own
        # ordering key is *when it was created*, not whatever timestamp
        # `self.source` (the affected permanent, in a self-targeted grant
        # like Crew's "becomes a creature") happens to carry from its own
        # battlefield entry -- see `game/continuous.py`'s `_in_layer` and
        # `GameState.next_timestamp`'s own docstring for why that distinction
        # matters (Swift Reconfiguration's granted Crew ability, activated
        # long after the Aura already attached, must apply *after* the
        # Aura's own "loses all other card types" layer-4 static).
        ability.timestamp = context.state.next_timestamp()
        ability.duration = durations.normalize_duration(self.duration)
        ability.duration_data = {"player_id": controller_id}
        if self.condition is not None:
            # RULE 611.2b's condition-bounded duration: the effect *ends*
            # when this stops holding, unlike an ``active_if`` gate, which
            # merely lies dormant and can come back on.
            ability.duration = "for_as_long_as"
            ability.duration_data["condition"] = dict(self.condition)
        if chosen_ids is not None:
            # A targeted grant applies to exactly the permanents chosen once
            # in `apply` (`affects="objects"` reads the ids off the ability),
            # whether via a RULE 115 target, ``previous_subject`` ("Tap
            # target land. **It** doesn't untap … for as long as ~ remains
            # tapped."), or ``self_subject`` (MEC-46, this ability's source).
            ability.affects = "objects"
            ability.object_ids = list(chosen_ids)
        context.state.floating_statics.append(ability)


class EndTheTurnEffect(GameEffect):
    """"End the turn." (Day's Undoing/Time Stop-shaped reminder text) —
    untargeted, no RULE 115 target at all. See `RulesEngine.end_the_turn`'s
    own docstring for what this actually does (exiles the stack now;
    queues `GameState.end_turn_requested` for `GameEngine.advance_step` to
    drain, since a plain `RulesEngine` effect has no reach into the turn
    loop's own `_turn_steps`/`_cursor`).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        context.end_the_turn()


class GrantConditionalCastFromExileEffect(GameEffect):
    """"Creature cards exiled this way gain 'You may cast this card from
    exile as long as `<condition>`.'" (Lukka, Coppercoat Outcast's +1) —
    reads the batch a preceding `exile_top_of_library` clause surfaced onto
    `GameContext.created_objects` and, for each creature card among them,
    registers a **standing** (never turn-swept) `GameState.exile_cast_
    condition` entry gated on ``condition`` (a `static_conditions` check
    that can also start holding *again* later if the board state returns).
    Unlike every other exile-then-maybe-cast grant in this engine
    (`temp_play_permissions`, all turn-windowed), this one never expires on
    a clock. No player choice — every creature card exiled this way gets it.

    ENG-37 B6 split the fused `exile_top_then_grant_conditional_cast` into
    this + `exile_top_of_library` under a `seq`: the exile is a plain
    positional library move, and "exiled **this way**" is exactly the
    `created_objects` referent the exile clause already populates.
    """

    def __init__(
        self, condition: Optional[dict[str, Any]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.condition = dict(condition or {})

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in list(getattr(context, "created_objects", []) or []):
            card = getattr(obj, "card", None)
            if getattr(card, "is_creature", False):
                context.state.exile_cast_condition[obj.instance_id] = (
                    player.id, dict(self.condition)
                )


class MutualRevealCompareManaValueEffect(GameEffect):
    """"You and target opponent each reveal the top card of your library.
    You each lose life equal to the mana value of the card revealed by the
    other player. You each put the card you revealed into your hand."
    (MEC-43 round 4F — Keen Duelist) — a genuinely new *simultaneous,
    two-player* reveal-and-compare, unlike this file's several existing
    single-player "reveal your own top card, then act on it" effects
    (`RevealTopThenTakeAndLoseLifeEffect` just above): each player's life
    loss here reads the *other* player's reveal, so both cards must be
    known before either life total changes — the whole reason this is one
    atomic effect rather than two effects trying to share a resolve-time
    referent (`GameContext.previous_targets` names an *object* a previous
    clause targeted/created, not "whichever card the other player just
    revealed", so it doesn't fit this shape). Fully deterministic — the
    only player choice at all is RULE 115's own opponent target — so no
    interactive `pending_choice` is needed. If either library is empty,
    that player simply reveals nothing (RULE 701.20a's "you may reveal a
    card only if you have one"-adjacent default): the other player's life
    loss from it is 0, and nothing is added to that player's hand.
    """

    def __init__(
        self, target: Any = None, source: Optional["GameObject"] = None, target_kind: str = "opponent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        opponent = (targets[0] if targets else None) or self.target
        if opponent is None:
            return
        player = _controller_of(self.source, context)
        if player is None:
            return

        def _reveal(p: Any) -> Optional[Any]:
            if not p.library:
                return None
            obj = p.library.pop()
            obj.zone = Zone.HAND
            p.hand.append(obj)
            return obj

        # Both reveals happen before either life total changes — the
        # loss amount for one player depends on what the *other* one just
        # revealed, so neither `lose_life` call can run first.
        player_card = _reveal(player)
        opponent_card = _reveal(opponent)
        player_loss = int(getattr(opponent_card.card, "converted_mana_cost", 0) or 0) if opponent_card else 0
        opponent_loss = int(getattr(player_card.card, "converted_mana_cost", 0) or 0) if player_card else 0
        if player_loss:
            context.lose_life(player, player_loss)
        if opponent_loss:
            context.lose_life(opponent, opponent_loss)


class EachCreatureYouControlDamageEachOpponentEffect(GameEffect):
    """"Each creature you control deals damage equal to its power to each
    opponent." (Lukka, Coppercoat Outcast's own −7 ultimate) — a double
    mass effect (every creature the controller has × every opponent),
    each creature's own amount being its own current power; no existing
    `DealDamageEffect` selector composes two independent mass groups like
    this (``each_creature_controller`` is the single-recipient mirror —
    one hit per creature, to *its own* controller, not every opponent).
    """

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        creatures = [
            o for o in list(context.state.battlefield)
            if o.is_creature and o.controller_id == player.id
        ]
        opponents = [p for p in context.state.living_players() if p.id != player.id]
        for creature in creatures:
            power = creature.power or 0
            if power <= 0:
                continue
            for opponent in opponents:
                context.deal_damage(opponent, power, creature)


class SubjectDamagesEachOpponentEqualToPowerEffect(GameEffect):
    """"<subject> deals damage equal to its power to each opponent." — a
    triggered-ability body where the damage *source* and its *amount* are
    one object: the trigger's own subject when the firing event names one
    (``instance_id``: Champion of the Path's just-entered Elemental,
    Pyrotechnic Performer's turned-face-up creature), else the ability's
    own source (Gau, Feral Youth / Giggling Skitterspike, whose "it" is
    "~" itself). PAR-30 — a 6-card SOLO cluster the plain `DealDamageEffect`
    can't express: it sources damage from ``self.source`` and reads a flat
    or event-payload amount, never "this other object's current power".

    "Each opponent" is every living player other than the ability's
    controller (RULE 102.1). Power ≤ 0 deals nothing (RULE 119.8).
    """

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        event = context.trigger_event or {}
        subject = context.state.find_object(event.get("instance_id"))
        if subject is None:
            subject = self.source
        if subject is None:
            return
        power = subject.power or 0
        if power <= 0:
            return
        for opponent in context.state.living_players():
            if opponent.id != controller.id:
                context.deal_damage(opponent, power, subject)


class DiesReturnAsEnchantmentEffect(GameEffect):
    """"When ~ dies, if it was a creature, return it to the battlefield
    under its owner's control. It's an enchantment." (Enduring Vitality)
    — untargeted, self-only (the just-died source, a fresh RULE 400.7
    object in the graveyard by the time this trigger resolves). "If it
    was a creature" reads the firing DIES event's own ``object_types``
    snapshot (RULE 400.7 — the object has already left, so a live
    re-lookup would see nothing). "It's an enchantment" is RULE 613.4b's
    permanent characteristic-setting effect: a fresh ``type``
    `StaticAbility` (``remove_types=["creature"]``) appended straight
    onto the *returned* object's own `static_effects` — the same list a
    permanent's printed statics live in, so it's re-derived every
    `continuous.recompute` pass exactly like a real one, rather than a
    one-time field set the next `reset_derived` would silently wipe.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        event = context.trigger_event or {}
        if "creature" not in (event.get("object_types") or ()):
            return
        context.return_from_graveyard(self.source, "battlefield", controller_id=None)
        context.created_objects.append(self.source)
        self.source.static_effects.append(
            StaticAbility(
                "type", affects="self", params={"remove_types": ["creature"]},
                source=self.source,
            )
        )


class ReturnSelfToBattlefieldEffect(GameEffect):
    """"Return it to the battlefield [tapped] under its owner's control."
    (Nezahal, Primal Tide's own delayed-trigger half — "Discard three
    cards: Exile ~. Return it to the battlefield tapped under its owner's
    control at the beginning of the next end step.") — untargeted,
    self-only. Meant to run as a `CreateDelayedTriggerEffect` inner
    effect: that effect rebuilds against the *same* `GameObject` every
    time (RULE 400.7's `instance_id`/Python identity both survive
    `reset_as_new_object`, which mutates in place rather than replacing
    the reference), so `self.source` is still the right object once the
    delayed step arrives, however many zone changes it's been through
    since.
    """

    def __init__(
        self, tapped: bool = False, source: Optional["GameObject"] = None,
        under_your_control: bool = False, extra_counters: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.tapped = tapped
        #: "...under **your** control." (Ashcloud Phoenix-adjacent) — the
        #: rarer sibling of RULE 400.7's own default "under its owner's
        #: control."
        self.under_your_control = under_your_control
        #: "...with a +1/+1 counter on it." (Feign Death) — the same
        #: ``{"kind", "count"}`` shape `_request_search`'s own
        #: ``extra_counters`` uses, put on the object right after it lands.
        self.extra_counters = dict(extra_counters) if extra_counters else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        controller_id = None
        if self.under_your_control:
            player = _controller_of(self.source, context)
            controller_id = player.id if player is not None else None
        context.return_from_graveyard(
            self.source, "battlefield_tapped" if self.tapped else "battlefield",
            controller_id=controller_id,
        )
        if self.extra_counters:
            kind = str(self.extra_counters.get("kind", "+1/+1"))
            count = int(self.extra_counters.get("count", 1) or 1)
            context.add_counters(self.source, count, kind, source=self.source)


class RevealTopThenCreatureAndOrLandBattlefieldEffect(GameEffect):
    """"Reveal that many cards from the top of your library. You may put a
    creature card and/or a land card from among them onto the battlefield.
    Put the rest on the bottom in a random order." (Ojer Kaslem, Deepest
    Growth's combat-damage trigger) — ``amount_from_trigger_event`` reads
    "that many" off the firing DAMAGE event's own ``amount`` (`DealDamage
    Effect`'s established idiom).

    Only one `GameState.pending_choice` can be open at a time (see its own
    docstring), so the "up to one creature *and* up to one land" pair can't
    both be offered in this same `apply()` call — they're two independent
    optional picks over the same revealed batch, chained the way `Scroll
    RackEffect`/`ScrollRackFinishEffect` chain theirs: the revealed cards
    are bottomed in random order *immediately* (their final resting place
    unless a following pick lifts one back out — `LookTopKeepOneOnTopEffect`'s
    own "commit first, relocate on pick" trick, since `request_choose_
    objects`'s ``"library_to_battlefield"`` action already finds an object
    wherever it currently sits in the library), the land candidates' ids are
    stashed on this ability's own source via `GameObject.exiled_with_ids`
    (a generic scratch list already reused this way by other single-use
    continuations), and the creature choice is opened with a `then_specs`/
    `else_specs` pair that both point at ``ojer_kaslem_land_pick`` — so the
    land choice opens next regardless of whether a creature was taken
    (`else_specs` also covers "no creature was even offered").
    """

    def __init__(
        self,
        amount: int = 0,
        amount_from_trigger_event: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.amount_from_trigger_event = amount_from_trigger_event

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        amount = self.amount
        if self.amount_from_trigger_event:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
        if amount <= 0 or not player.library:
            return
        revealed = [player.library.pop() for _ in range(min(amount, len(player.library)))]
        if not revealed:
            return
        random.shuffle(revealed)
        for obj in revealed:
            player.library.insert(0, obj)  # bottom of library, per the card
        self.source.exiled_with_ids = [
            obj.instance_id for obj in revealed if obj.card.is_land
        ]
        creature_candidates = [obj for obj in revealed if obj.card.is_creature]
        land_pick = [{"type": "ojer_kaslem_land_pick", "params": {}}]
        context.engine._request_choose_objects(
            player, creature_candidates, "library_to_battlefield", count=1, optional=True,
            prompt="Lege bis zu eine der aufgedeckten Kreaturenkarten auf das Schlachtfeld",
            source=self.source, then_specs=land_pick, else_specs=land_pick,
        )


class OjerKaslemLandPickEffect(GameEffect):
    """The land half of `RevealTopThenCreatureAndOrLandBattlefieldEffect`,
    run as that effect's own `then_specs`/`else_specs` continuation once the
    creature pick resolves (see that class's docstring for why this can't
    just be the second half of one `apply()` call). Reads the land
    candidates' ids back off `GameObject.exiled_with_ids` and re-resolves
    them (`GameState.find_object`, still ``Zone.LIBRARY`` — nothing but this
    same continuation ever moves them) rather than trusting stale object
    references, the same caution `ScrollRackFinishEffect` takes with its own
    stashed ids.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        player = _controller_of(self.source, context)
        if player is None:
            return
        land_ids = list(getattr(self.source, "exiled_with_ids", None) or [])
        self.source.exiled_with_ids = []
        if not land_ids:
            return
        land_candidates = [
            obj for obj in (context.state.find_object(iid) for iid in land_ids)
            if obj is not None and obj.zone == Zone.LIBRARY
        ]
        context.engine._request_choose_objects(
            player, land_candidates, "library_to_battlefield", count=1, optional=True,
            prompt="Lege bis zu eine der aufgedeckten Landkarten auf das Schlachtfeld",
            source=self.source,
        )


class MonstrosityEffect(GameEffect):
    """RULE 701.37a: "Monstrosity N" — the body of ``<cost>: Monstrosity N``.

    Untargeted and always about the ability's own source (701.37b: only
    permanents become monstrous, and every printed monstrosity ability is the
    permanent's own), so there is no `TargetSpec` here at all — the
    `RenownEffect` shape rather than the `TapEffect` one.

    ``amount`` accepts the ``"x"`` sentinel `RulesEngine._substitute_x`
    rewrites with the announced {X} ("{X}{X}{R}: Monstrosity X", Fanatic of
    Xenagos-shaped), which is also what makes RULE 701.37c's "other abilities
    may refer to that X" work: `RulesEngine.monstrosity` records the
    substituted value on the permanent.
    """

    def __init__(self, amount: Any = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        # A still-unsubstituted "x" means no {X} was announced (a fixture, or
        # an ability reached outside the stack) — 0 is the honest reading.
        amount = self.amount if isinstance(self.amount, int) else 0
        context.monstrosity(self.source, amount)


class HarnessEffect(GameEffect):
    """MEC-79 / RULE 701.64a: "Harness [this permanent]" — the body of the
    Marvel Infinity Stones' ``{cost}, {T}: Harness ~`` ability.

    701.64a only ever defines the self form ("[this permanent]"), so this is
    the `MonstrosityEffect` shape (no `TargetSpec`, always the source) minus
    the counters. An explicit ``targets`` list is still honoured for the
    hypothetical "harness that permanent" a future card might print; absent
    one it harnesses `self.source`.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        objs = [
            t for t in (targets or [])
            if getattr(t, "instance_id", None) is not None
        ] or ([self.source] if self.source is not None else [])
        for obj in objs:
            context.harness(obj)


class SpecializeEffect(GameEffect):
    """MEC-48: the body of "Specialize {cost}" — "{cost}, Discard a card:
    this permanent specializes." Specialize is an Arena-only digital keyword
    (no paper CR); its five per-colour specialized faces live in Arena's own
    card data, which this repo's Scryfall ``oracle_cards`` seed does not
    carry. So this models the *designation* only: set the persistent
    ``is_specialized`` flag (read by a "when ~ specializes" self-subject
    trigger / an "as long as ~ is specialized" static — the `MonstrosityEffect`
    shape: untargeted, self-scoped) and fire `EventType.SPECIALIZED`. The
    permanent's characteristics are deliberately left unchanged (documented
    simplification — there is no face to become).

    ``color`` is a colour of the discarded card when the pay-cost step could
    determine one (single-coloured discard); otherwise ``None``. It is
    carried on the event and stamped on the object, not acted on further.
    """

    def __init__(self, color: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.color = color

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None or getattr(src, "is_specialized", False):
            return
        src.is_specialized = True
        if self.color is not None:
            src.specialized_color = self.color
        state = getattr(context, "state", None)
        if state is not None:
            state.fire_event(
                GameEvent(
                    EventType.SPECIALIZED,
                    instance_id=src.instance_id,
                    controller_id=getattr(src, "controller_id", None),
                    color=self.color,
                )
            )


class AdaptEffect(GameEffect):
    """RULE 701.46a: "Adapt N" — "if this permanent has no +1/+1 counters on
    it, put N +1/+1 counters on it".

    Deliberately its own effect rather than a conditional `AddCountersEffect`:
    the "has no +1/+1 counters" gate is part of the keyword action itself, and
    every real adapt card is an activated ability on the creature, so like
    `MonstrosityEffect` this is untargeted and self-scoped.
    """

    def __init__(self, amount: Any = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        amount = self.amount if isinstance(self.amount, int) else 0
        context.adapt(self.source, amount)


class GoadEffect(GameEffect):
    """RULE 701.15a: "Goad target creature" — and its "up to N target
    creatures" (RULE 115.1a) and pronoun forms.

    The goader is the effect's *controller* (701.15b: "a player other than
    the controller of the permanent, spell, or ability that caused it to be
    goaded"), read off the source at resolution rather than baked in at bind
    time, so a stolen/copied source goads for whoever controls it now.

    ``target_kind=None`` is the pronoun form — "…deals 2 damage to target
    creature. Goad that creature." (`GameContext.previous_targets`, the same
    referent `FightEffect` uses), or with ``referent="created"`` the tokens an
    earlier clause of this same resolution just made ("…each player creates a
    tapped 2/2 Bird. **The tokens** are goaded for the rest of the game.",
    `GameContext.created_objects`). ``selector`` is the untargeted mass form
    ("Goad all creatures your opponents control").

    ``permanent`` is the "…for the rest of the game" duration: the same
    designation with no expiry (`RulesEngine.goad`), rather than 701.15a's
    printed default of "until your next turn".
    """

    _SELECTORS = frozenset({"creatures_opponents_control"})
    _REFERENTS = frozenset({"previous", "created"})

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        optional: bool = False,
        count: Any = 1,
        selector: Optional[str] = None,
        count_selector: Optional[str] = None,
        referent: str = "previous",
        permanent: bool = False,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.selector = selector if selector in self._SELECTORS else None
        self.referent = referent if referent in self._REFERENTS else "previous"
        self.permanent = bool(permanent)
        self.target_spec = (
            TargetSpec(
                kind=target_kind,
                optional=optional,
                count=count if isinstance(count, int) else 1,
                count_selector=count_selector,
                # "For each opponent, goad up to one target creature **that
                # player** controls" — one requirement of "as many as there
                # are opponents", with the per-opponent half being exactly
                # RULE 115's already-modeled "controlled by different
                # players" constraint.
                distinct_controllers=count_selector == "opponents",
            )
            if target_kind is not None and self.selector is None
            else None
        )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        goader_id = getattr(self.source, "controller_id", None)
        if goader_id is None:
            return
        if self.selector is not None:
            from ..continuous import group_selector_objects  # avoid the continuous↔effects cycle

            for obj in group_selector_objects(context.state, goader_id, self.selector):
                context.goad(obj, goader_id, permanent=self.permanent)
            return
        if self.target_spec is None:
            # A pronoun: whatever the previous clause of this same ability
            # targeted, or created (RULE 608.2 resolution order — either way
            # it has already resolved by the time this effect runs).
            chosen = list(
                context.created_objects if self.referent == "created"
                else context.previous_targets
            )
        elif self.target_spec.count_selector or self.target_spec.effective_count != 1:
            # A dynamic count is only known at announce time, so take
            # everything that was actually chosen rather than re-deriving it.
            chosen = list(targets or [])
        else:
            chosen = [targets[0]] if targets else []
        for obj in chosen:
            # A permanent, not a player: `previous_targets` and a shared
            # targets list can both hold either, and only a creature can be
            # goaded (RULE 701.15b). Duck-typed rather than `isinstance` —
            # `game/` must not import `models/` at runtime (the module
            # boundary; `GameObject` here is a TYPE_CHECKING name only).
            if getattr(obj, "instance_id", None) is not None:
                context.goad(obj, goader_id, permanent=self.permanent)


class SuspectEffect(GameEffect):
    """RULE 701.60a: "Suspect `<creature>`." — the creature gains the
    **suspected** designation (menace + can't block, RULE 701.60b). Subject
    shapes, like `GoadEffect` / `ExploreEffect`:

      * bare self (``target_kind=None``, not a pronoun) — "when ~ enters,
        suspect it", suspecting `self.source`;
      * ``previous_subject`` — "gain control of target creature … suspect
        it", the creature an earlier clause chose (`previous_targets`);
      * ``attached`` — "suspect enchanted creature", this Aura's host;
      * a `TargetSpec` — "suspect [up to N] target creature[ an opponent
        controls]".
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        previous_subject: bool = False,
        attached: bool = False,
        optional: bool = False,
        count: Any = 1,
    ) -> None:
        super().__init__(source)
        self.previous_subject = bool(previous_subject)
        self.attached = bool(attached)
        self.target_spec = (
            TargetSpec(
                kind=target_kind,
                optional=optional,
                count=count if isinstance(count, int) else 1,
            )
            if target_kind is not None
            else None
        )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            chosen = list(targets or [])
        elif self.attached:
            host_id = getattr(self.source, "attached_to", None)
            host = context.state.find_object(host_id) if host_id is not None else None
            chosen = [host] if host is not None else []
        elif self.previous_subject:
            chosen = [
                o for o in context.previous_targets
                if getattr(o, "instance_id", None) is not None
            ]
        else:
            chosen = [self.source] if self.source is not None else []
        for obj in chosen:
            if getattr(obj, "instance_id", None) is not None:
                context.engine.suspect(obj)


class DetainEffect(GameEffect):
    """RULE 701.35a: "Detain [up to N] target `<permanent>` an opponent
    controls." — until the detainer's next turn, each target can't attack or
    block and its activated abilities can't be activated (RULE 701.35b,
    enforced by `_can_attack` / `can_block` / `can_activate` reading
    `combat.is_detained`).

    The detainer is this effect's *controller* (701.35a — "the controller of
    the spell or ability"), read off the source at resolution like
    `GoadEffect`. Always targeted (no self/pronoun form on any real card);
    ``count``/``optional`` cover the "up to two target …" cycle.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature_you_dont_control",
        optional: bool = False,
        count: int = 1,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(
            kind=target_kind,
            optional=optional,
            count=count if isinstance(count, int) else 1,
        )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        detainer_id = getattr(self.source, "controller_id", None)
        if detainer_id is None:
            return
        for obj in list(targets or []):
            if getattr(obj, "instance_id", None) is not None:
                context.engine.detain(obj, detainer_id)


class RemoveSuspectedEffect(GameEffect):
    """"... is/are no longer suspected." (RULE 701.60a's reverse). Subject
    shapes:

      * ``scope="all"`` (default) — the mass "all suspected creatures are no
        longer suspected." standalone clause (Absolving Lammasu's ETB);
      * ``previous_subject`` — the creature an earlier clause of the same
        resolution chose (`GameContext.previous_targets`): "put a +1/+1
        counter on target suspected creature you control. **You may have it
        become no longer suspected.**" (Deadly Complication, ``optional``),
        and Airtight Alibi's conditional tail "if it's suspected, it's no
        longer suspected." (wrapped in a `ConditionalEffect`, not optional);
      * ``attached`` — this Aura's host.

    ``optional`` (the "you may have it …" rider) routes through
    `_request_choose_objects` so declining is a real board choice, not an
    auto-take — a suspected creature has menace, which its controller may
    want to keep.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        scope: str = "all",
        previous_subject: bool = False,
        attached: bool = False,
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.scope = scope
        self.previous_subject = bool(previous_subject)
        self.attached = bool(attached)
        self.optional = bool(optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.attached:
            host_id = getattr(self.source, "attached_to", None)
            host = context.state.find_object(host_id) if host_id is not None else None
            objs = [host] if host is not None else []
        elif self.previous_subject:
            objs = [
                o for o in context.previous_targets
                if getattr(o, "instance_id", None) is not None
            ]
        else:
            objs = list(context.state.battlefield)
        objs = [o for o in objs if getattr(o, "is_suspected", False)]
        if not objs:
            return
        if self.optional:
            controller = _controller_of(self.source, context)
            if controller is None:
                return
            context.engine._request_choose_objects(
                controller, objs, "remove_suspected", count=len(objs),
                optional=True, source=self.source,
                prompt="Have it become no longer suspected?",
            )
            return
        context.engine.remove_suspected(objs)


class LivingWeaponEffect(GameEffect):
    """RULE 702.92: "When this Equipment enters, create a 0/0 black
    Phyrexian Germ creature token, then attach this Equipment to it."

    A single atomic effect rather than `CreateTokenEffect` + `AttachEffect`:
    the attach target is the *specific* token this same effect just
    created, not a RULE 115 target or an entry off a shared targets list —
    there's no vocabulary for "whatever the previous effect just made" in
    the ordinary effects-list composition.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        from ...services.token_database import synthesize_token_card

        card = synthesize_token_card(
            "Phyrexian Germ", power=0, toughness=0, colors=["B"], subtypes=["Phyrexian", "Germ"]
        )
        tokens = context.engine.create_token(self.source.controller_id, card)
        if tokens:
            context.engine.attach_to_target(self.source, tokens[0])


class CreateAttachedAuraTokenEffect(GameEffect):
    """"Create a `<colors>` Aura enchantment token named `<name>` attached to
    target creature `<...>`. The token has enchant creature and
    `<quoted ability>`." (Scriv, the Obligator's "Contract"; a reusable
    "make an Aura token, attach it to a RULE 115 target" shape, PAR-60.)

    The token's own quoted ability is authored under its token name in the
    ability catalogue (`register("Contract", …)`, picked up by the
    `bind_from_catalogue` `RulesEngine.create_token` already runs on every
    token) rather than passed through here — keeping this effect a plain
    create-then-attach. A no-op with no legal target (RULE 608.2b).
    """

    def __init__(
        self,
        token_name: str = "Aura",
        colors: Optional[list[str]] = None,
        target_kind: str = "creature_you_dont_control",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.token_name = token_name
        self.colors = colors or []
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import synthesize_token_card

        target = targets[0] if targets else None
        if target is None or self.source is None:
            return
        card = synthesize_token_card(
            self.token_name, colors=self.colors, subtypes=["Aura"],
            oracle_text="Enchant creature",
        )
        made = context.create_token(self.source.controller_id, card, 1)
        for tok in made or []:
            context.engine.attach_to_target(tok, target)


class ClassLevelEffect(GameEffect):
    """Set a Class's class level (RULE 716.2c) — the effect of activating one
    of its "Level N: <cost>" abilities, not the cost itself (mirrors how
    Saga's chapter advance is a dedicated step, not a generic counter add).

    Sets the source's ``class_level`` counter directly to ``level`` (never
    incremented — a Class's level-up abilities are only ever legal one level
    at a time, `GameEngine._can_activate_class_level`) and fires
    `EventType.CLASS_LEVEL` so a rare "when this Class becomes level N"
    trigger can scope to it via the same ``chapter`` trigger key Saga's
    chapter triggers already use (`effect_binder._trigger_condition`).
    """

    def __init__(self, level: int, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.level = level

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = self.source
        if target is None:
            return
        target.counters["class_level"] = self.level
        context.state.fire_event(
            GameEvent(
                EventType.CLASS_LEVEL,
                object=target.name,
                instance_id=target.instance_id,
                controller_id=target.controller_id,
                chapter=self.level,
            )
        )


class ProliferateEffect(GameEffect):
    """RULE 701.30: give an additional counter of each kind already there to
    any number of permanents and/or players.

    RULE 701.30a's per-permanent/per-player "choose any number" is a real
    interactive choice this MVP doesn't offer (no counter-proliferation
    picker exists yet) — auto-applies to *every* permanent/player that
    already carries at least one counter, the same "auto-choose, no chooser
    in MVP" simplification `SacrificeEffect`/`GameEngine._sacrifice_
    candidate` use elsewhere. Player-level counters (poison via `Player.
    poison`, everything else — rad/energy/experience — via `Player.
    counters`) proliferate the same way (Vexing Radgull's own "otherwise,
    proliferate" branch needs exactly this: a player who already has rad
    counters gets another).

    ``times`` > 1 repeats the whole pass that many times (Contagion Engine's
    "Proliferate twice."/War of the Spark's "Proliferate three times.") —
    mirrors `ScryEffect.count`'s param shape.
    """

    def __init__(self, times: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.times = times

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for _ in range(self.times):
            for obj in list(context.state.battlefield):
                for kind in list(obj.counters.keys()):
                    if obj.counters.get(kind, 0) > 0:
                        context.add_counters(obj, 1, kind, source=self.source)
            for player in list(context.state.players):
                if player.poison > 0:
                    context.add_player_counters(player, 1, "poison", source=self.source)
                for kind in list(player.counters.keys()):
                    if player.counters.get(kind, 0) > 0:
                        context.add_player_counters(player, 1, kind, source=self.source)


class RemoveCountersEffect(GameEffect):
    """Strip counters from a target permanent (Vampire Hexmage-shaped:
    "Remove all counters from target permanent") or from every permanent on
    the battlefield (Oblivion Stone/Aether Snap/Thief of Blood-shaped:
    "Remove all counters from all permanents") — the unconditional "all"
    shape, ``max_count=None``. Goes through `context.add_counters` with a
    negative amount per kind (not a raw dict mutation), the same idiom
    `ProliferateEffect` uses, so a counter-removed trigger still fires
    correctly (RULE 122's `add_counters` already treats a non-positive
    amount as removal, bypassing replacement effects, which only ever apply
    to counters being *added*).

    ``max_count`` (Glissa Sunslayer/Heartless Act/Render Inert-shaped
    "remove up to N counters from target permanent/creature") switches to a
    genuinely different, interactive **chosen**-quantity shape instead:
    resolution opens a `pending_choice` (`RulesEngine.
    _request_remove_counters_choice`) asking how many (0..min(max_count,
    counters present)), then — only if the target carries 2+ counter kinds —
    which kind to remove one at a time, mirroring `_request_search`'s
    "open a choice, the engine's `resolve_*_choice` finishes it" shape
    rather than doing anything synchronously here.
    """

    def __init__(
        self,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
        max_count: Optional[int] = None,
        draw_per_removed: bool = False,
        self_only: bool = False,
        kind: Optional[str] = None,
        keep: int = 0,
    ) -> None:
        super().__init__(source)
        self.max_count = max_count
        #: "Remove all counters from target … . Draw a card for each counter
        #: removed this way." (Nexus Mentality, PAR-60) — the controller
        #: draws N, where N is the positive-counter total actually stripped.
        self.draw_per_removed = bool(draw_per_removed)
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        #: "Remove all charge counters from ~." (Coalition Relic/Ventifact
        #: Bottle, PAR-66) — untargeted (RULE 115 never applies to an
        #: ability naming its own source), unlike ``target_spec`` above.
        self.self_only = bool(self_only)
        #: Restrict the strip to one named counter kind (RULE 122.1a) rather
        #: than every kind the object happens to carry — without this, a
        #: permanent that also carries an unrelated counter type would lose
        #: those too. ``None`` keeps every other mode's original "strip
        #: everything" behaviour unchanged.
        self.kind = kind
        #: "Remove all but one +1/+1 counter from it." (Lily Bowen, Raging
        #: Grandma, PAR-67) — a *partial*-removal count, unlike this
        #: effect's other "strip everything of the kind" modes. Only
        #: meaningful alongside ``kind`` (which counter type to leave a
        #: remainder of); ``0`` keeps every other mode's original
        #: "strip everything" behaviour unchanged.
        self.keep = max(0, int(keep))

    def _strip(self, context: GameContext, obj: "GameObject") -> int:
        removed = 0
        for kind in list(obj.counters.keys()):
            if self.kind is not None and kind != self.kind:
                continue
            amount = obj.counters.get(kind, 0)
            if not amount:
                continue
            to_remove = amount
            if self.keep and amount > 0:
                to_remove = amount - self.keep
                if to_remove <= 0:
                    continue
            if to_remove > 0:
                removed += to_remove
            context.add_counters(obj, -to_remove, kind)
        return removed

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.max_count is not None:
            target = targets[0] if targets else None
            if target is not None:
                context.engine._request_remove_counters_choice(
                    target, self.max_count, _controller_of(self.source, context)
                )
            return
        if self.self_only:
            if self.source is not None:
                context.counters_removed_this_way += self._strip(context, self.source)
            return
        if self.target_spec is not None:
            target = targets[0] if targets else None
            if target is not None:
                removed = self._strip(context, target)
                # PAR-66: `GameContext.counters_removed_this_way` — a
                # following effect's own "for each counter removed this
                # way" (Coalition Relic/Ventifact Bottle/Lily Bowen/Garnet).
                context.counters_removed_this_way += removed
                if self.draw_per_removed and removed > 0:
                    caster = _controller_of(self.source, context)
                    if caster is not None:
                        context.draw(caster, removed)
            return
        for obj in list(context.state.battlefield):
            context.counters_removed_this_way += self._strip(context, obj)


def _battlefield_counter_total(state: Any) -> int:
    """Every positive counter of every kind on every battlefield permanent —
    the tally "…equal to the number of counters removed this way." reads as a
    before/after delta (Eventide's Shadow)."""
    return sum(
        sum(v for v in (getattr(o, "counters", None) or {}).values() if v and v > 0)
        for o in state.battlefield
    )


class RemoveCountersFromAmongThenDrawLoseLifeEffect(GameEffect):
    """"Remove any number of counters from among permanents on the
    battlefield. You draw cards and lose life equal to the number of
    counters removed this way." (Eventide's Shadow.)

    The controller picks counter-bearing permanents through an ``optional``
    `_request_choose_objects` (action ``strip_all_counters`` — each pick
    loses *all* its counters, a documented permanent-granularity
    simplification of "any number of counters", the same RULE 122 precision
    `MoveCountersEffect` already accepts). This effect's controller then
    draws, and loses that much life, equal to the total removed — computed
    as a battlefield counter-total delta in the queued ``then_specs``.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        candidates = [
            o for o in context.state.battlefield
            if any(v for v in (getattr(o, "counters", None) or {}).values() if v and v > 0)
        ]
        if not candidates:
            return
        before = _battlefield_counter_total(context.state)
        context.engine._request_choose_objects(
            controller, candidates, "strip_all_counters",
            count=len(candidates), optional=True, source=self.source,
            prompt="Entferne Marken von bleibenden Karten",
            then_specs=[{
                "type": "draw_lose_life_counter_removed_delta",
                "params": {"player_id": controller.id, "before": before},
            }],
        )


class DrawLoseLifeCounterRemovedDeltaEffect(GameEffect):
    """The "you draw cards and lose life equal to the number of counters
    removed this way" tail of `RemoveCountersFromAmongThenDrawLoseLifeEffect`
    — queued as ``then_specs``, reads the battlefield counter-total delta
    against a snapshot. Not for direct card use.
    """

    def __init__(
        self, player_id: Optional[str] = None, before: int = 0,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.player_id = player_id
        self.before = int(before)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        try:
            player = context.state.player_by_id(self.player_id)
        except (KeyError, ValueError):
            return
        n = self.before - _battlefield_counter_total(context.state)
        if n > 0:
            context.draw(player, n)
            context.lose_life(player, n)


def _your_saga_lore_total(state: Any, player_id: Optional[str]) -> int:
    """Total RULE 714.2b lore counters on Sagas ``player_id`` controls —
    Garnet, Princess of Alexandria's own before/after scope, the delta
    idiom `RemoveCountersFromAmongThenDrawLoseLifeEffect` uses over the
    whole battlefield, narrowed to one player's Sagas."""
    from .. import continuous  # avoid the continuous<->effects import cycle

    return sum(
        (o.counters.get("lore", 0) or 0)
        for o in state.battlefield
        if o.controller_id == player_id and continuous.has_subtype(o, "saga")
    )


class RemoveLoreCounterFromChosenSagasThenAddCountersEffect(GameEffect):
    """"You may remove a lore counter from each of any number of Sagas you
    control. Put a +1/+1 counter on Garnet for each lore counter removed
    this way." (Garnet, Princess of Alexandria, PAR-67.)

    Reuses the ``strip_all_counters`` `_request_choose_objects` action —
    every printed Saga carries only lore counters (RULE 714.2b), so
    stripping "all" of a chosen Saga's counters is the same as removing
    its lore counter(s), the same RULE 122 precision simplification
    `RemoveCountersFromAmongThenDrawLoseLifeEffect` (Eventide's Shadow)
    already accepts — just scoped to the controller's own Sagas instead of
    the whole battlefield. The +1/+1 payoff reads a before/after lore-
    counter total over that same scope, queued as ``then_specs`` exactly
    like Eventide's Shadow's own draw/life-loss tail.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .. import continuous  # avoid the continuous<->effects import cycle

        controller = _controller_of(self.source, context)
        if controller is None or self.source is None:
            return
        candidates = [
            o for o in context.state.battlefield
            if o.controller_id == controller.id
            and continuous.has_subtype(o, "saga")
            and (o.counters.get("lore", 0) or 0) > 0
        ]
        if not candidates:
            return
        before = _your_saga_lore_total(context.state, controller.id)
        context.engine._request_choose_objects(
            controller, candidates, "strip_all_counters",
            count=len(candidates), optional=True, source=self.source,
            prompt="Entferne einen Kapitelmarker von ausgewählten Sagas",
            then_specs=[{
                "type": "add_counters_from_saga_lore_removed_delta",
                "params": {
                    "source_id": self.source.instance_id,
                    "player_id": controller.id, "before": before,
                },
            }],
        )


class AddCountersFromSagaLoreRemovedDeltaEffect(GameEffect):
    """Garnet, Princess of Alexandria's own +1/+1 payoff tail — see
    `RemoveLoreCounterFromChosenSagasThenAddCountersEffect`. Not for direct
    card use."""

    def __init__(
        self, source_id: Optional[int] = None, player_id: Optional[str] = None,
        before: int = 0, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.source_id = source_id
        self.player_id = player_id
        self.before = int(before)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = context.state.find_object(self.source_id)
        if obj is None:
            return
        n = self.before - _your_saga_lore_total(context.state, self.player_id)
        if n > 0:
            context.add_counters(obj, n, "+1/+1")


class MoveCountersEffect(GameEffect):
    """"Move a counter from target permanent you control onto a second
    target permanent." (Nesting Grounds, Fractal Harness, Ozolith-adjacent)
    — RULE 122.3: one counter is removed from the first target and put on
    the second (the placement fires "whenever a counter is put on" triggers
    normally; the removal, being a non-positive `add_counters`, does not).

    ``count`` counters are moved (always 1 on real cards so far). Which kind
    when the source carries several: **documented simplification** — the
    first kind by iteration order rather than an interactive prompt, the
    same RULE 122 precision this file already accepts for "+2/+2 counter"
    &c. Extend to a `pending_choice` (like `RemoveCountersEffect.max_count`)
    if a card ever makes the kind matter.
    """

    def __init__(
        self,
        source_target_kind: str = "permanent_you_control",
        dest_target_kind: str = "permanent",
        count: int = 1,
        source: Optional["GameObject"] = None,
        move_all_kinds: bool = False,
    ) -> None:
        super().__init__(source)
        self.count = int(count)
        #: "Move **all** counters from target … onto another target …."
        #: (Nexus Mentality, PAR-60) — every counter of every kind, not just
        #: ``count`` of the first kind.
        self.move_all_kinds = bool(move_all_kinds)
        self.target_spec = TargetSpec(kind=source_target_kind)
        self.extra_target_specs = (TargetSpec(kind=dest_target_kind, distinct_from_others=True),)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        src = picks[0] if picks else None
        dst = picks[1] if len(picks) > 1 else None
        if src is None or dst is None or src is dst:
            return
        if self.move_all_kinds:
            for kind, n in list((src.counters or {}).items()):
                if n and n > 0:
                    context.add_counters(src, -n, kind, source=self.source)
                    context.add_counters(dst, n, kind, source=self.source)
            return
        kind = next((k for k, n in (src.counters or {}).items() if n > 0), None)
        if kind is None:
            return
        moved = min(self.count, int(src.counters.get(kind, 0)))
        if moved <= 0:
            return
        context.add_counters(src, -moved, kind, source=self.source)
        context.add_counters(dst, moved, kind, source=self.source)


class MoveAllPlusOneCountersFromSelfEffect(GameEffect):
    """"…move any number of +1/+1 counters from this creature onto other
    creatures." (Forgotten Ancient's upkeep ability, PAR-60.)

    Documented simplification: "any number … onto **other creatures**"
    (RULE 122's per-counter distribution across several targets) is modeled
    as moving *all* of this creature's +1/+1 counters onto a single
    up-to-one target creature — the same "no interactive any-number/divide
    prompt" simplification `AddCountersEffect._apply_divided` and
    `MoveCountersEffect`'s own kind-pick already document.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature", optional=True)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        tgt = targets[0] if targets else None
        if self.source is None or tgt is None or tgt is self.source:
            return
        n = int((self.source.counters or {}).get("+1/+1", 0))
        if n <= 0:
            return
        context.add_counters(self.source, -n, "+1/+1", source=self.source)
        context.add_counters(tgt, n, "+1/+1", source=self.source)
        context.recompute()


class DoubleCountersOnTargetEffect(GameEffect):
    """"Double the number of [each kind of / +1/+1] counter(s) on <object>."
    (Ferrafor, Young Yew; Vorel of the Hull Clade; Gilder Bairn; Primordial
    Hydra; Tanazir Quandrix; Kalonian Hydra; Growth Curve.) RULE 701.19: for
    each doubled kind currently on the object, put that many *more* of that
    kind on it — a positive `context.add_counters` per kind, so "whenever a
    counter is put on" triggers fire for the new counters.

    Counts are snapshotted before any placement so a kind processed later
    doubles its *original* amount, not one already grown by an earlier
    kind's placement. When a creature carries both ``+1/+1`` and ``-1/-1``
    counters the net is preserved (RULE 704.5q would annihilate the pair on
    the next SBA regardless); every real single-kind case is exact.

    ``mode`` picks what to double: ``"target"`` (a real RULE 115 target,
    the default), ``"self"`` (the effect's own source — Primordial Hydra's
    upkeep / Dragonsguard Elite), ``"each_you_control"`` (every creature the
    controller has — Kalonian Hydra / Bristly Bill), or ``"previous_
    subject"`` (a creature an earlier clause of the same body picked —
    Growth Curve / Invigorating Surge's "…then double … on that creature").
    ``kind`` limits the doubling to one counter kind (``"+1/+1"`` on all of
    the modern cards); ``None`` doubles every kind (Vorel).
    """

    def __init__(
        self,
        target_kind: str = "creature",
        mode: str = "target",
        kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.mode = mode
        self.kind = kind
        self.target_spec = TargetSpec(kind=target_kind) if mode == "target" else None

    def _double_on(self, context: GameContext, obj: Any) -> None:
        counters = {k: v for k, v in (getattr(obj, "counters", None) or {}).items() if v and v > 0}
        if self.kind is not None:
            counters = {self.kind: counters.get(self.kind, 0)} if counters.get(self.kind, 0) else {}
        for kind, amount in counters.items():
            context.add_counters(obj, amount, kind, source=self.source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.mode == "self":
            if self.source is not None:
                self._double_on(context, self.source)
            return
        if self.mode == "each_you_control":
            controller_id = getattr(self.source, "controller_id", None)
            for o in list(context.state.battlefield):
                if o.is_creature and o.controller_id == controller_id:
                    self._double_on(context, o)
            return
        if self.mode == "previous_subject":
            for o in list(getattr(context, "previous_targets", []) or []):
                self._double_on(context, o)
            return
        target = targets[0] if targets else None
        if target is not None:
            self._double_on(context, target)


class CreateTokensPerCounterAmongTargetPlayerCreaturesEffect(GameEffect):
    """"Create a number of 1/1 green Saproling creature tokens equal to the
    number of counters among creatures target player controls." (Ferrafor,
    Young Yew's ETB.) ``N`` is every counter of every kind on every creature
    the chosen player controls (RULE 122 — any counter kind counts). The
    tokens are created under *this effect's* controller.
    """

    def __init__(
        self,
        power: int = 1,
        toughness: int = 1,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        token_name: str = "Saproling",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="player")
        self.power = power
        self.toughness = toughness
        self.colors = colors or ["G"]
        self.subtypes = subtypes or ["Saproling"]
        self.token_name = token_name

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import synthesize_token_card

        player = targets[0] if targets else None
        creator_id = getattr(self.source, "controller_id", None)
        if player is None or creator_id is None:
            return
        pid = getattr(player, "id", None)
        n = sum(
            sum(v for v in (getattr(o, "counters", None) or {}).values() if v and v > 0)
            for o in context.state.battlefield
            if getattr(o, "is_creature", False) and o.controller_id == pid
        )
        if n <= 0:
            return
        card = synthesize_token_card(
            self.token_name, power=self.power, toughness=self.toughness,
            colors=self.colors, subtypes=self.subtypes,
        )
        context.create_token(creator_id, card, n)


class PumpEffect(GameEffect):
    """Give a target creature a temporary P/T boost and/or keywords "until end
    of turn" (Giant Growth; RULE 613.4d layer 7d + layer 6 for keywords).

    ``power``/``toughness`` may be negative (a "-N/-N" debuff). The change is
    an *effect* with a duration, not counters — it lives on the object's
    ``temp_*`` fields, which `continuous.recompute` folds in and the cleanup
    step (RULE 514.2) clears. Untargeted (no ``target_kind``) it pumps its own
    source, e.g. an activated "~ gets +1/+0 until end of turn". ``selector``
    (e.g. ``"creatures_you_control"``) pumps a whole *group* instead — an
    untargeted resolve-time selection (RULE 601.2c — not a target at all), the
    common Saga-chapter/anthem-spell shape "Creatures you control get +N/+N
    until end of turn" (e.g. History of Benalia's chapter III).

    ``unblockable=True`` additionally sets the target's ``temp_unblockable``
    flag (the same one `UnblockableEffect` sets) — "target creature gets
    +1/+0 until end of turn and can't be blocked this turn" (You Come to a
    River-shaped) is one *ability* with one target, not two independent
    targeting effects, so it's folded into this single effect (mirroring how
    a granted keyword already rides along in ``keywords``) rather than paired
    with a second `UnblockableEffect` that would ask for its own target.

    ``target_kind="attached_permanent"`` is a fourth mode — "{U}: Enchanted
    creature gains flying until end of turn." (Pemmin's Aura-shaped Aura
    activated ability): acts on whatever the effect's own source is
    currently `attached_to`, re-read live at resolution, no RULE 115 target
    at all — the same concept `TapEffect`'s own ``"attached_permanent"``
    mode uses, see its docstring.
    """

    def __init__(
        self,
        power: int = 0,
        toughness: int = 0,
        keywords: Optional[list[str]] = None,
        target_kind: Optional[str] = None,
        selector: Optional[str] = None,
        unblockable: bool = False,
        source: Optional["GameObject"] = None,
        count: int = 1,
        count_max: Optional[int] = None,
        optional: bool = False,
        amount_from_trigger_event: Optional[str] = None,
        per_recipient_controller_counter: Optional[str] = None,
        amount_from_count_selector: Optional[str] = None,
        amount_from_count_selector_negative: bool = False,
        amount_from_count_selector_axis: str = "both",
        amount_from_created_object_mana_value: bool = False,
        creature_filter: Optional[dict] = None,
        previous_subject: bool = False,
        subtypes: Optional[list[str]] = None,
        trigger_subject: bool = False,
        self_multiplier: Optional[int] = None,
        parametric_keywords: Optional[list[dict[str, Any]]] = None,
        colors: Optional[list[str]] = None,
        power_if_kicked: Optional[int] = None,
        toughness_if_kicked: Optional[int] = None,
        power_if_bargained: Optional[int] = None,
        toughness_if_bargained: Optional[int] = None,
        target_operand: Any = None,
    ) -> None:
        super().__init__(source)
        #: "target `<c1>` or `<c2>` creature gets/gains … until end of
        #: turn" (the Weaver cycle) — `TargetSpec.colors`' OR narrowing,
        #: checked at offer time by `targeting._color_ok`. WUBRG letters.
        self.colors = tuple(colors) if colors else None
        self.power = power
        self.toughness = toughness
        self.keywords = list(keywords or [])
        #: ENG-31: "gains firebending N until end of turn" — a keyword with a
        #: number, which the flat `keywords` slug list can't carry. Written
        #: to the recipient's `temp_parametric_keywords`, the parametric
        #: sibling of `temp_keywords`. ``[{"name": str, "n": int}, ...]``.
        self.parametric_keywords = [dict(pk) for pk in (parametric_keywords or [])]
        self.selector = selector
        #: The power/toughness/keyword quality filter — kept as an attribute
        #: (not only folded into ``target_spec``) so the ``selector``-group
        #: branch of `apply` can narrow its group too ("each creature you
        #: control **with power N or less** gains `<kw>`", Earthshape).
        self.creature_filter = creature_filter
        #: RULE 702.83a Exalted — "*that* creature gets +1/+1 until end of
        #: turn": pump whichever object the firing trigger event names
        #: (`GameContext.trigger_event["instance_id"]`), not the source and
        #: not a RULE 115 target. The pump-family analogue of
        #: `AddCountersEffect.trigger_subject_key` / `GrantKeywordTo
        #: TriggerSubjectEffect` (PAR-24).
        self.trigger_subject = trigger_subject
        #: "Birds, Frogs, Otters, and Rats you control get +1/+1 until end
        #: of turn." (Valley Floodcaller, MEC-41) — the ``selector``-group
        #: sibling of `AddCountersEffect.subtypes` (same "any of these
        #: subtypes" membership check against the object's own printed
        #: type line), which this effect never had despite sharing the
        #: exact same `group_selector_objects` base.
        self.subtypes = [s.lower() for s in subtypes] if subtypes else None
        self.unblockable = unblockable
        #: ENG-30: "1 or 2 target creatures … . They gain vigilance and
        #: lifelink until end of turn." (A-Bretagard Stronghold-shaped) — the
        #: pump-family sibling of `TapEffect`/`ReturnToHandEffect`'s own
        #: ``previous_subject`` pronoun mode: no target of its own, acting on
        #: whatever group the *preceding* multi-target clause chose
        #: (`GameContext.previous_targets`), which may be a variable-size
        #: range rather than a fixed count — exactly the shape a target-count
        #: *range* creates and the reason no card needed this before.
        self.previous_subject = previous_subject
        #: "Each creature your opponents control gets -1/-1 until end of
        #: turn for each poison counter its controller has." (Phyresis
        #: Outbreak-shaped) — unlike `amount_from_trigger_event` (one
        #: shared magnitude for the whole group), each recipient's own
        #: boost scales independently by *its own controller's* count of
        #: this player-counter kind; ``power``/``toughness`` become the
        #: per-counter multiplier (``-1``) rather than a flat delta.
        #: ``selector``-only (no real card needs this on a single target).
        self.per_recipient_controller_counter = per_recipient_controller_counter
        #: "Whenever you gain life, ~ gets +X/+X until end of turn, where X
        #: is the amount of life you gained." (Field-Tested Frying Pan's
        #: granted ability) — the event field name (``"amount"``) to read
        #: off `GameContext.trigger_event` at resolution, overriding both
        #: ``power`` and ``toughness`` with the same value (always a
        #: symmetric "+X/+X" in practice). Same idiom as `LoseLifeEffect.
        #: amount_from_trigger_event`.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "Creatures you control gain trample and get +X/+X until end of
        #: turn, where X is the number of creatures you control."
        #: (Craterhoof Behemoth-shaped) — one shared magnitude for the
        #: whole group (unlike `per_recipient_controller_counter`'s
        #: per-object scaling), computed live via `continuous.
        #: count_selector` at resolve time rather than read off a firing
        #: event (`amount_from_trigger_event`'s job) — there's no trigger
        #: event to read here, this is the board state itself.
        self.amount_from_count_selector = amount_from_count_selector
        #: "…gets -X/-X until end of turn, where X is your devotion to
        #: black." (Blight-Breath Catoblepas) — `amount_from_count_selector`
        #: always reads a non-negative board count; this flips the sign
        #: after reading it, the "-X/-X" sibling of that always-positive
        #: "+X/+X" default rather than a second, duplicated param.
        self.amount_from_count_selector_negative = amount_from_count_selector_negative
        #: "…gets +X/+0 until end of turn, where X is …" (Dina, Soul Steeper;
        #: Renegade Bull; Surge to Victory) — a dynamic count that lands on
        #: only one axis. ``"power"`` / ``"toughness"`` / ``"both"`` (default,
        #: the pre-existing Giant-Growth-shaped symmetric pump).
        self.amount_from_count_selector_axis = (
            amount_from_count_selector_axis
            if amount_from_count_selector_axis in ("both", "power", "toughness")
            else "both"
        )
        #: MEC-58: "This creature gets +X/+0 until end of turn, where X is
        #: that card's mana value." (Tavern Brawler, PAR-32) — "that card"
        #: is whatever the resolution's own preceding clause just exiled
        #: (`ImpulsiveDrawEffect` appends it to `GameContext.created_
        #: objects`, the same "read what a previous clause made available"
        #: idiom `LandOrFreeCastEffect`/`previous_subject` above already
        #: use). Unlike `amount_from_trigger_event`/`amount_from_count_
        #: selector` (which set *both* `power` and `toughness` to the same
        #: magnitude), this only ever sets `power` — every printed instance
        #: of this shape is "+X/+0", never symmetric, so `toughness` stays
        #: whatever was passed in (0 by default).
        self.amount_from_created_object_mana_value = bool(amount_from_created_object_mana_value)
        #: RULE 701.10/11 "double"/"triple target creature's power and
        #: toughness" (Dragonclaw Strike/Tifa's Limit Break) — a per-object
        #: amount unlike every ``amount_from_*`` above (each recipient's own
        #: *current* power/toughness, not one shared magnitude), so it's
        #: read fresh at `_pump_one` time rather than folded into a single
        #: `apply()`-wide ``self.power``/``self.toughness`` set once. ``2``
        #: doubles (a "+1x/+1x" delta on top of the base), ``3`` triples
        #: (+2x/+2x); ``None`` leaves ``power``/``toughness`` as printed.
        self.self_multiplier = self_multiplier
        #: MEC-82 / RULE 614: the "if this spell was kicked/bargained, that
        #: creature gets `<P2>`/`<T2>` **instead**" magnitude override — a
        #: *replacement* of this pump's own printed P/T, not a second additive
        #: effect (Final Flourish / Vayne's Treachery / Explosive Growth /
        #: Candy Grapple). The `DealDamageEffect.amount_if_kicked` shape for
        #: the pump axis; resolved once per recipient in `_pump_one` via the
        #: shared `_resolve_amount_override` chain, off the source's
        #: `kicker_count`/`bargained` flags.
        self.power_if_kicked = power_if_kicked
        self.toughness_if_kicked = toughness_if_kicked
        self.power_if_bargained = power_if_bargained
        self.toughness_if_bargained = toughness_if_bargained
        self._attached_mode = target_kind == "attached_permanent"
        self.target_operand = target_operand
        if target_kind is not None and not self._attached_mode and not previous_subject and target_operand is None:
            # PAR-15: "any number of target creatures each get +N/+N [and
            # gain `<keyword>`] until end of turn" (Aerial Formation/Ajani's
            # Presence/Colossal Heroics-shaped) — ``count`` > 1 is the same
            # "each of N gets the *full* amount" shape `AddCountersEffect`'s
            # own N>=2 mode uses (as opposed to a *divided* pool), since a
            # pump spell's whole point is every chosen creature getting the
            # stated boost independently.
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max,
                creature_filter=creature_filter, colors=self.colors,
            )

    def target_polarity(self) -> Optional[str]:
        # RULE 115.1c-adjacent (MEC-43, Grim Hireling): targets are gathered
        # *before* an activated ability's own {X} is announced/resolved
        # (`GameEngine.activate_ability`'s `effects_target_specs` call
        # happens ahead of `RulesEngine._substitute_x`, which only runs at
        # resolution), so an X-scaled "-x"/"x" `power`/`toughness` sentinel
        # can still be a bare string here — comparing it against ``0``
        # would raise. A "-"-prefixed sentinel reads as a debuff (harmful),
        # any other (a bare "x", or an int) as beneficial/neutral, matching
        # what the resolved value would report either way.
        def _is_negative(value: Any) -> bool:
            if isinstance(value, str):
                return value.startswith("-")
            return value < 0

        return "harmful" if (_is_negative(self.power) or _is_negative(self.toughness)) else "beneficial"

    def _kicked_magnitude(
        self, base: Any, if_kicked: Optional[int], if_bargained: Optional[int]
    ) -> Any:
        # MEC-82 / RULE 614: swap ``base`` for the kicked/bargained value when
        # the source spell was cast that way — the same override-not-additive
        # priority chain `DealDamageEffect.amount` uses.
        return self._resolve_amount_override(
            base,
            [
                (
                    if_kicked is not None
                    and (getattr(self.source, "kicker_count", 0) or 0) > 0,
                    lambda: if_kicked,
                ),
                (
                    if_bargained is not None
                    and bool(getattr(self.source, "bargained", False)),
                    lambda: if_bargained,
                ),
            ],
            stop_at_first=True,
        )

    def _pump_one(self, obj: "GameObject") -> None:
        if self.self_multiplier:
            # RULE 701.10/11: each recipient's own *current* power/toughness
            # (post-layer-engine, so an earlier anthem in the same resolution
            # is already reflected) sets its own delta — a group-selector
            # "double each creature you control" scales every creature by
            # its own stats, not by one shared amount.
            delta = self.self_multiplier - 1
            power, toughness = delta * obj.power, delta * obj.toughness
        else:
            power = self._kicked_magnitude(
                self.power, self.power_if_kicked, self.power_if_bargained
            )
            toughness = self._kicked_magnitude(
                self.toughness, self.toughness_if_kicked, self.toughness_if_bargained
            )
        obj.temp_power += power
        obj.temp_toughness += toughness
        obj.temp_keywords.update(self.keywords)
        for pk in self.parametric_keywords:
            name, n = pk.get("name"), pk.get("n")
            if name and n is not None:
                obj.temp_parametric_keywords[str(name)] = int(n)
        if self.unblockable:
            obj.temp_unblockable = True
        # Record a per-source breakdown for the board's per-card effect
        # summary (display-only — the aggregate ints above drive the math).
        if power or toughness or self.keywords or self.parametric_keywords:
            obj.temp_effects.append(
                {
                    "source": self.source.name if self.source is not None else "Effekt",
                    "power": power,
                    "toughness": toughness,
                    "keywords": list(self.keywords),
                }
            )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_operand is not None:
            from ..effect_operands import object_for

            target = object_for(self.target_operand, context, self.source, targets)
            if target is not None:
                self._pump_one(target)
                context.recompute()
            return
        if self.previous_subject:
            # "it gains haste until end of turn" (PAR-30) — "it" is whatever
            # the *preceding* clause of this resolution chose (RULE 601.2c,
            # `previous_targets`) or, when that clause created rather than
            # targeted something ("create a token …. It gains haste …" —
            # God-Pharaoh's Gift, Harried Dronesmith, Mordor on the March),
            # what it *made* (`created_objects`).
            chosen = list(context.previous_targets) or list(
                getattr(context, "created_objects", [])
            )
            for obj in chosen:
                self._pump_one(obj)
            if chosen:
                context.recompute()
            return
        if self.trigger_subject:
            # RULE 702.83a Exalted: pump the object the firing event names.
            event = context.trigger_event or {}
            obj = context.state.find_object(event.get("instance_id"))
            if obj is not None:
                self._pump_one(obj)
                context.recompute()
            return
        if self.amount_from_trigger_event:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
            if self.amount_from_count_selector_axis in ("both", "power"):
                self.power = amount
            if self.amount_from_count_selector_axis in ("both", "toughness"):
                self.toughness = amount
            if amount <= 0:
                return
        if self.amount_from_count_selector:
            from .. import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            # PAR-32: pass ``source`` so a source-relative selector
            # ("where X is ~'s power" — Hardy Outlander's `source_power`)
            # resolves; board-count selectors ignore it, unchanged.
            amount = continuous.count_selector(
                context.state, controller_id, self.amount_from_count_selector, self.source
            )
            if amount is None:
                return
            if self.amount_from_count_selector_negative:
                amount = -amount
            if self.amount_from_count_selector_axis in ("both", "power"):
                self.power = amount
            if self.amount_from_count_selector_axis in ("both", "toughness"):
                self.toughness = amount
            if amount == 0:
                return
        if self.amount_from_created_object_mana_value:
            created = list(getattr(context, "created_objects", []))
            amount = int(getattr(created[-1].card, "converted_mana_cost", 0) or 0) if created else 0
            self.power = amount
            if amount <= 0:
                return
        if self.selector is not None:
            from ..continuous import group_selector_objects  # avoid the continuous↔effects cycle

            selector = self.selector
            if selector == "previous_selector":
                # MEC-28: "They gain first strike until end of turn."
                # (Karlach, Fury of Avernus) — "they" is whichever group the
                # *preceding clause's own mass selector* acted on, read off
                # `GameContext.previous_selector` (`_apply_effects_
                # partitioned`) rather than a selector name baked in at
                # parse time. No preceding selector clause this resolution
                # (the sentinel is unreachable any other way) → no-op.
                selector = context.previous_selector
                if not selector:
                    return
            if selector == "self_and_shared_creature_type_you_control":
                # MEC-59: RULE 205.3g "shares a creature type with ~" —
                # "it and other creatures you control that share a
                # creature type with it" (Haunted One) is self **plus**
                # every *other* creature this source's controller controls
                # whose printed subtypes overlap the source's own — read
                # directly off the source's *live* subtypes rather than a
                # fixed list, unlike every other selector here (which all
                # take their subtype filter from `self.subtypes`, a param
                # baked in at parse time).
                src = self.source
                if src is None:
                    return
                own_subtypes = set(
                    src.card.type_line.partition("—")[2].strip().lower().split()
                )
                group = [src] + [
                    obj for obj in context.state.battlefield
                    if obj is not src
                    and obj.controller_id == src.controller_id
                    and obj.is_creature
                    and own_subtypes & set(
                        obj.card.type_line.partition("—")[2].strip().lower().split()
                    )
                ]
            else:
                controller_id = getattr(self.source, "controller_id", None)
                group = group_selector_objects(context.state, controller_id, selector, src=self.source)
            if self.subtypes is not None:
                group = [
                    obj for obj in group
                    if any(
                        s in obj.card.type_line.partition("—")[2].strip().lower().split()
                        for s in self.subtypes
                    )
                ]
            if self.creature_filter:
                # "each creature you control **with power N or less** gains
                # `<kw>` until end of turn" (Earthshape, PAR-30) — the
                # power/toughness/keyword quality filter this effect already
                # accepts for its *targeted* branch, applied to a
                # selector-gathered group too. `combat.matches_object_filter`
                # is the same predicate `TargetSpec.creature_filter` uses.
                from ..combat import matches_object_filter  # avoid the import cycle

                group = [o for o in group if matches_object_filter(o, self.creature_filter)]
            if self.per_recipient_controller_counter:
                base_power, base_toughness = self.power, self.toughness
                for obj in group:
                    owner = context.state.player_by_id(obj.controller_id)
                    n = getattr(owner, self.per_recipient_controller_counter, 0) if owner else 0
                    self.power, self.toughness = base_power * n, base_toughness * n
                    self._pump_one(obj)
                self.power, self.toughness = base_power, base_toughness
                context.recompute()
                return
            for obj in group:
                self._pump_one(obj)
            context.recompute()
            return
        if self._attached_mode:
            host_id = getattr(self.source, "attached_to", None)
            target = context.state.find_object(host_id) if host_id is not None else None
        elif self.target_spec is not None:
            if self.target_spec.effective_count != 1:
                chosen = _chosen_targets(targets, self.target_spec.effective_count)
                for obj in chosen:
                    self._pump_one(obj)
                if chosen:
                    # Re-derive P/T now so a lethal -X/-X is caught by the
                    # SBA pass the caller runs right after this resolution.
                    context.recompute()
                return
            target = targets[0] if targets else None
        else:
            target = self.source
        if target is None:
            return
        self._pump_one(target)
        # Re-derive P/T now so a lethal -X/-X (toughness → 0) is caught by the
        # SBA pass the caller runs right after this resolution.
        context.recompute()


class ScryEffect(GameEffect):
    """Scry ``count`` for the effect's controller (RULE 701.18)."""

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.scry(player, self.count, source=self.source)


class SurveilEffect(GameEffect):
    """Surveil ``count`` for the effect's controller (RULE 701.31)."""

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.surveil(player, self.count, source=self.source)


class HealEffect(GameEffect):
    """RULE 701.69a: "heal all damage from `<permanent>`" / "damage … is
    healed" — remove all marked damage (`RulesEngine.heal`) from the chosen
    permanent(s).

    ``selector`` (a `continuous.group_selector_objects` name — "all_
    creatures", "creatures_you_control", …) heals a group; otherwise the
    RULE 115 ``targets``; otherwise, with neither, ``self.source`` (a bare
    "heal all damage from ~"). No amount — see `RulesEngine.heal`.
    """

    def __init__(
        self, selector: Optional[str] = None, source: Optional["GameObject"] = None
    ) -> None:
        super().__init__(source)
        self.selector = selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            from ..continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            group = group_selector_objects(
                context.state, controller_id, self.selector, src=self.source
            )
        elif targets:
            # a permanent target has an `instance_id`; a player target doesn't
            group = [t for t in targets if getattr(t, "instance_id", None) is not None]
        elif self.source is not None:
            group = [self.source]
        else:
            group = []
        for obj in group:
            context.engine.heal(obj)


class FateSealEffect(GameEffect):
    """Fateseal ``count`` (RULE 701.29a): the effect's controller looks at
    the top ``count`` cards of an opponent's library and puts any number on
    the bottom, the rest back on top in any order — scry aimed at someone
    else's deck. The opponent is auto-picked (first living opponent) —
    `RulesEngine.fateseal`'s documented simplification, same as `ClashEffect`
    / `GainControlBySourceEffect`. No target."""

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.fateseal(player, self.count, source=self.source)


class LookTopSelectEffect(GameEffect):
    """"Look at the top N cards of your library. Put M of them into your
    hand and the rest `<destination>`." (RULE 701.19-adjacent — Anticipate/
    Dig Through Time/Diabolic Vision/Ancestral Memories-shaped) — the
    fixed-selection-count sibling of scry/surveil, see
    `RulesEngine.look_top_select`."""

    def __init__(
        self,
        count: int = 1,
        select_count: int = 1,
        rest_destination: str = "library_bottom",
        rest_order: Optional[str] = None,
        select_optional: bool = False,
        select_filter: Optional[dict[str, Any]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.select_count = select_count
        self.rest_destination = rest_destination
        self.rest_order = rest_order
        #: "You **may** reveal a **creature card with power 3 or less**…"
        #: (Water Tribe Rallier) — see `RulesEngine.look_top_select`.
        self.select_optional = select_optional
        self.select_filter = select_filter

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.look_top_select(
                player, self.count, self.select_count, self.rest_destination,
                self.rest_order, select_optional=self.select_optional,
                select_filter=self.select_filter,
            )


class ManifestEffect(GameEffect):
    """Manifest (RULE 701.40a) or cloak (RULE 701.58a) the top ``count``
    cards of the effect controller's library.

    One effect for both keyword actions because they *are* the same action
    bar one characteristic — a cloaked permanent has ward {2} (701.58a) —
    which `RulesEngine.manifest` takes as its ``kind``, exactly the way the
    engine already parameterizes morph vs. disguise."""

    def __init__(
        self, count: int = 1, kind: str = "manifest", player: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.kind = kind
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if self.player == "previous_target_controller" and context.previous_targets:
            controller_id = getattr(context.previous_targets[0], "controller_id", None)
            if controller_id is not None:
                player = context.state.player_by_id(controller_id)
        if player is not None:
            context.manifest(player, self.count, kind=self.kind)


class ManifestDreadEffect(GameEffect):
    """"Manifest dread": look at the top two cards of your library, put one
    onto the battlefield face down and the other into your graveyard (RULE
    701.40a plus a look-and-choose wrapper).

    The choice is a real interactive one (`RulesEngine._request_manifest_dread`)
    rather than "take the top card", since which of the two is worth
    manifesting — and which is worth *binning*, for a graveyard deck — is
    the whole decision the mechanic exists for."""

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context._request_manifest_dread(player)


class CreateNamedCardTokenEffect(GameEffect):
    """"Create a token that's a copy of `<a specific named real card>`" (RULE
    111.5 / 707.2 — The Joiner of Cats' "a … copy of **Lurrus of the
    Dream-Den**"). Unlike `CopyPermanentEffect` (copies a permanent already
    on the battlefield) or `CreateTokenEffect` (synthesises a vanilla token
    from inline stats / the token catalogue), the copiable values come from
    a real card resolved by name out of the card cache
    (`services.card_database.default_card_database`), so the token has that
    card's actual abilities.

    ``card_name`` is clamped parser data (a string, never code). If the name
    doesn't resolve — an offline/empty cache — the effect is a no-op rather
    than raising: the token simply isn't created (RULE 608.2b, "as much as
    possible")."""

    def __init__(
        self,
        card_name: str = "",
        count: int = 1,
        tapped: bool = False,
        attacking: bool = False,
        not_legendary: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.card_name = card_name
        # clamped like any effect magnitude (`spec._clamp_params` doesn't
        # reach a nested `miss_effect_specs` entry's own params).
        self.count = max(1, min(int(count), 100))
        self.enter_tapped = bool(tapped)
        self.enter_attacking = bool(attacking)
        self.not_legendary = bool(not_legendary)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if not self.card_name:
            return
        from ...services.card_lookup import card_by_name

        card = card_by_name(self.card_name)
        if card is None:
            return
        if self.not_legendary:
            card = card.as_copy(not_legendary=True)
        controller_id = (
            self.source.controller_id if self.source is not None
            else context.active_player.id
        )
        made = context.create_token(controller_id, card, self.count) or []
        if self.enter_tapped:
            for token in made:
                token.tapped = True
        if self.enter_attacking:
            for token in made:
                context.engine.put_onto_battlefield_attacking(token)
        context.created_objects.extend(made)


#: The `GameContext` same-resolution accumulator names `CreateTokenEffect.
#: count_from_context` will read — a closed whitelist so parser-derived text
#: can never name an arbitrary `GameContext` attribute (mirrors the intent of
#: `_resolve_extra_counter_amount`'s own ``count_from_context`` key, which
#: today also only ever carries this one name).
_TOKEN_COUNT_CONTEXT_ACCUMULATORS: frozenset[str] = frozenset({
    "objects_exiled_this_way",
    # "…create a token for each nontoken creature you controlled that was
    # destroyed this way." (Ceaseless Conflict, PAR-60) — bumped by
    # `DestroyEffect` in the same resolution. Documented simplification:
    # it counts *every* permanent destroyed this way, not just your
    # nontoken creatures.
    "permanents_destroyed_this_way",
})


class CreateTokenEffect(GameEffect):
    """Create one or more token permanents (RULE 111.5 / 701.6).

    A **named** token (``token_name`` with no inline stats) is looked up in the
    curated `TokenDatabase` so it keeps its real abilities (a Treasure's mana
    ability, a Clue's sacrifice-to-draw); an **inline** token (power/toughness
    + colours + subtypes from the oracle clause) is synthesized. Either way the
    created objects are flagged tokens, so RULE 704.5d removes them the instant
    they leave the battlefield. The tokens are created under the effect's
    controller (its source's controller, else the active player).

    ``count_selector``, when given, overrides ``count`` with a live
    `continuous.count_selector` evaluation at resolve time — "create X
    Treasure tokens, where X is the number of artifacts and enchantments
    your opponents control" (Dockside Extortionist-shaped), scoped to the
    effect's own controller the same way a per-count anthem's ``power_
    count`` is.

    ``creators`` is who does the creating: the effect's own controller by
    default, or **every** player / every opponent ("Each player creates three
    tapped 1/1 white Warrior creature tokens." — The War Games), each getting
    their own ``count`` tokens under their own control. ``tapped`` is the
    "creates a **tapped** …" wording (RULE 110.5a — a permanent enters
    untapped unless an effect says otherwise), applied as the token enters
    rather than as a separate tap, so nothing sees it untapped in between.

    Whatever it creates is appended to `GameContext.created_objects`, which
    is how a following clause says "**the tokens** are goaded".
    """

    _CREATORS = frozenset(
        {"you", "each_player", "each_opponent", "previous_target_controller", "target"}
    )

    def __init__(
        self,
        count: int = 1,
        token_name: Optional[str] = None,
        target_kind: Optional[str] = None,
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
        count_selector: Optional[str] = None,
        creators: str = "you",
        tapped: bool = False,
        attacking: bool = False,
        legendary: bool = False,
        pt_from_trigger_event: Optional[str] = None,
        pt_from_count_selector: Optional[str] = None,
        count_from_trigger_event: Optional[str] = None,
        count_from_trigger_event_counter: Optional[str] = None,
        count_from_context: Optional[str] = None,
        count_from_subject: Optional[str] = None,
        extra_counters: Optional[dict[str, Any]] = None,
        grant_self_anthem: Optional[dict[str, Any]] = None,
        is_artifact: bool = False,
        parametric_keywords: Optional[list[dict[str, Any]]] = None,
        per_opponent: bool = False,
        token_dies_gain_life: Optional[int] = None,
        x_multiplier: Optional[int] = None,
        oracle_text: str = "",
    ) -> None:
        super().__init__(source)
        #: "Create **twice X** … tokens" (Pest Infestation, PAR-60) — the
        #: token-count sibling of `DealDamageEffect.x_multiplier`: the
        #: spell's own announced {X} (`GameObject.x_paid`) times this
        #: factor. Overrides ``count`` when set.
        self.x_multiplier = int(x_multiplier) if x_multiplier is not None else None
        #: "…creature token with \"when ~ dies, you gain N life.\"" — the
        #: STX Pest token's own printed death trigger (Blight Mound, Feral
        #: Appetite, Pest Rescuer, Hunt for Specimens, …). A `dies` →
        #: `gain_life` `TriggeredAbility` bound onto each created token right
        #: after it enters (RULE 603.6d — the token's own ability, so its
        #: controller is the token's controller), the triggered-ability
        #: sibling of ``grant_self_anthem``'s baked-on static.
        self.token_dies_gain_life = (
            int(token_dies_gain_life) if token_dies_gain_life is not None else None
        )
        #: "…colorless Construct **artifact** creature token…" — see
        #: `synthesize_token_card`'s own ``is_artifact`` docstring for why
        #: this can't just be inferred from ``colors=[]``: plenty of
        #: legitimately colorless non-artifact tokens exist too.
        self.is_artifact = is_artifact
        #: "…create a 0/0 … Construct … token with '~ gets +1/+1 for each
        #: artifact you control.'" (Urza's Saga's own chapter II) — a
        #: self-scaling P/T static baked *onto the created token itself*,
        #: not the effect's source. Built via the same ``anthem`` factory
        #: an oracle-parsed "creatures you control get +N/+N" static uses
        #: (``power``/``toughness``/``power_count``/``toughness_count``,
        #: `continuous._pt_mod_count`'s selector vocabulary), appended to
        #: each created token's own `GameObject.static_effects` right after
        #: it enters — the same "append a static at resolve time" idiom
        #: `GrantGraveyardCastPermissionThisTurnEffect` already uses, just
        #: permanent (no ``expires_turn``) since a token's granted ability
        #: is part of its own definition, not a turn-scoped grant.
        self.grant_self_anthem = dict(grant_self_anthem) if grant_self_anthem else None
        self.count = count
        self.token_name = token_name
        #: Inline rules text makes this a specifically-authored token rather
        #: than a lookup of a same-named curated token.  In particular, an
        #: Aura token needs its printed "Enchant creature" text to bind its
        #: attachment keyword before a following `attach` clause resolves.
        self.oracle_text = oracle_text
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.keywords = keywords or []
        #: ENG-31: "create a 2/2 red Soldier creature token with firebending
        #: N" (Fire Nation Attacks/Occupation) — a keyword with a number the
        #: flat `keywords` list can't hold. Docked onto each created token's
        #: own `parametric_keywords` + its ATTACKS mana ability synthesized,
        #: right after it enters — a *printed* part of the token's
        #: definition, not a layer-6 grant. ``[{"name": str, "n": int}, ...]``.
        self.parametric_keywords = [dict(pk) for pk in (parametric_keywords or [])]
        self.count_selector = count_selector
        self.creators = creators if creators in self._CREATORS else "you"
        #: "**Target player** creates a Treasure token." (Prismari Command)
        #: — a real RULE 115 player target whose chosen player does the
        #: creating (``creators="target"``).
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        #: "**For each opponent**, [you] create a … token[ that's tapped and
        #: attacking that opponent]." (Endless Foot Assault, Stampede Surfer)
        #: — the effect's own controller makes one token *per opponent*, and
        #: when ``attacking`` each token is put into combat attacking a
        #: *distinct* opponent (RULE 508.4a's defender choice made per token
        #: rather than by the shared auto-pick). Distinct from
        #: ``creators="each_opponent"`` (there each opponent makes their own).
        self.per_opponent = bool(per_opponent)
        self.tapped = bool(tapped)
        #: "…create a … token that's **tapped and attacking**." (RULE 508.4 —
        #: Captain's Claws, Basri Ket, Anim Pakal, the "whenever ~ attacks,
        #: make a token" family). ``tapped`` above handles the tap; this puts
        #: the fresh token into the current combat via `RulesEngine.put_onto_
        #: battlefield_attacking` right after it enters.
        self.attacking = bool(attacking)
        self.legendary = bool(legendary)
        #: "…create an Incubator token with two +1/+1 counters on it…"
        #: (Glissa, Herald of Predation's Incubate) — ``{"kind": "+1/+1",
        #: "count": 2}``, put on each created token right after it enters,
        #: the same shape `_request_search`'s own ``extra_counters`` uses
        #: for a found card reaching the battlefield.
        self.extra_counters = dict(extra_counters) if extra_counters else None
        # "…create an X/X blue Shark creature token with flying, where X is
        # that spell's mana value." (Shark Typhoon-shaped) — an X/X token
        # sized off the firing `SPELL_CAST` event's own field, read fresh at
        # resolve time (same idiom as `PumpEffect.amount_from_trigger_event`)
        # rather than a fixed ``power``/``toughness``. Always symmetric X/X
        # in practice, so one field sets both.
        self.pt_from_trigger_event = pt_from_trigger_event
        #: "…an X/X black Horror creature token, where X is the number of
        #: creatures that died this turn." (MEC-43 round 4C, Spoils of
        #: Blood) — the board-count sibling of ``pt_from_trigger_event``:
        #: reads a `continuous.count_selector` fresh at resolve time instead
        #: of a firing event's own field, the same "X/X sized off a live
        #: board count" idiom a characteristic-defining P/T static already
        #: uses for a permanent (RULE 613.7c), applied here to a token being
        #: created instead. Always symmetric X/X, same as ``pt_from_trigger_
        #: event`` above.
        self.pt_from_count_selector = pt_from_count_selector
        #: "…create **that many** 1/1 green Elf Warrior creature tokens."
        #: (Lathril, Blade of the Elves-shaped "whenever ~ deals combat
        #: damage to a player" payoff — "that many" always refers back to
        #: the firing event's own ``amount``, RULE 603.1) — the *count*
        #: sibling of ``pt_from_trigger_event`` (a token's stats, not how
        #: many get made). Overrides ``count``/``count_selector`` when set.
        self.count_from_trigger_event = count_from_trigger_event
        #: "When ~ dies, create a … token for each +1/+1 counter on it."
        #: (Hangarback Walker, Pentavus-shaped) — a named counter kind on
        #: the firing DIES event's snapshotted ``counters`` dict (RULE
        #: 603.6d — the object is gone), the `DrawCardEffect.
        #: count_from_trigger_event_counter` sibling. Overrides ``count``.
        self.count_from_trigger_event_counter = count_from_trigger_event_counter
        #: "When ~ dies, create a number of tapped Treasure tokens equal to
        #: its power." (Goldvein Hydra) — a ``"<who>_<char>"`` reading
        #: (`_characteristic_of_subject`), the DIES-snapshot-aware sibling
        #: of ``count_from_trigger_event``; ``trigger_subject_power``.
        self.count_from_subject = count_from_subject
        #: "Exile X target creature cards from your graveyard. **For each
        #: creature card exiled this way**, create a 2/2 black Zombie
        #: creature token." (Midnight Ritual / Necromancer's Covenant /
        #: Release to Memory — PAR-30 reanimator-token residue): the count is
        #: a `GameContext` same-resolution accumulator, read fresh at resolve
        #: time. Only ``"objects_exiled_this_way"`` today, the same
        #: accumulator `_resolve_extra_counter_amount`'s own ``count_from_
        #: context`` key reads (Sunfall's Incubate). Overrides ``count``.
        self.count_from_context = count_from_context

    def _resolve_extra_counter_amount(self, context: GameContext) -> int:
        """How many ``extra_counters`` to place on each created token.

        A plain ``count`` is a literal; the dynamic PAR-30 forms, all read
        fresh at resolve time and clamped to `spec.MAX_EFFECT_MAGNITUDE` (a
        hostile board count can't wedge the session):

        - ``count_from_count_selector`` — a `continuous.count_selector`
          ("Incubate X, where X is the number of lands you control" —
          Glistening Dawn).
        - ``count_from_trigger_event`` — the firing event's own field
          ("…where X is that spell's mana value" — Chrome Host Seedshark;
          "…where X is its power" off a DIES event — Bloated Processor).
        - ``count_from_context`` — a `GameContext` same-resolution
          accumulator name; only ``"objects_exiled_this_way"`` today
          ("Exile all creatures. Incubate X, where X is the number of
          creatures exiled this way." — Sunfall).
        - ``count_from_subject`` — a ``"<who>_<char>"`` string reading a
          characteristic off an object this effect never targets itself
          (`GainLifeEffect.amount_from_subject`'s idiom): ``who`` is
          ``self`` / ``previous_subject`` / ``trigger_subject``, ``char``
          is ``power`` / ``toughness`` / ``mana_value``. "Exile target
          nonland permanent. Its controller incubates X, where X is its
          mana value." — Excise the Imperfect (``previous_subject_mana_
          value``; RULE 608.2h last-known info, the permanent is gone)."""
        ec = self.extra_counters or {}
        from ...parser.oracle.spec import MAX_EFFECT_MAGNITUDE

        if ec.get("count_from_trigger_event"):
            event = context.trigger_event
            raw = int((event or {}).get(str(ec["count_from_trigger_event"])) or 0)
        elif ec.get("count_from_context"):
            raw = int(getattr(context, str(ec["count_from_context"]), 0) or 0)
        elif ec.get("count_from_subject"):
            raw = _characteristic_of_subject(context, self.source, str(ec["count_from_subject"]))
        elif ec.get("count_from_count_selector"):
            from .. import continuous  # function-scoped: avoid an import cycle

            controller_id = getattr(self.source, "controller_id", None)
            raw = continuous.count_selector(
                context.state, controller_id, str(ec["count_from_count_selector"]),
                source=self.source,
            )
        else:
            raw = int(ec.get("count", 1) or 0)
        return max(0, min(int(raw), MAX_EFFECT_MAGNITUDE))

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import default_token_database, synthesize_token_card

        power, toughness = self.power, self.toughness
        if self.pt_from_trigger_event:
            event = context.trigger_event
            x = int((event or {}).get(self.pt_from_trigger_event) or 0)
            power, toughness = x, x
        elif self.pt_from_count_selector:
            from .. import continuous  # function-scoped: avoid an import cycle

            controller_id = getattr(self.source, "controller_id", None)
            x = continuous.count_selector(
                context.state, controller_id, self.pt_from_count_selector, source=self.source
            )
            power, toughness = x, x
        card = None
        # A bare named token (no inline stats) → the curated catalogue, so it
        # keeps its printed abilities. Inline stats always synthesize.
        if self.token_name and power is None and toughness is None and not self.oracle_text:
            card = default_token_database().get_token(self.token_name)
        if card is None:
            card = synthesize_token_card(
                self.token_name or (self.subtypes[0] if self.subtypes else "Token"),
                power=power,
                toughness=toughness,
                colors=self.colors,
                subtypes=self.subtypes,
                keywords=self.keywords,
                oracle_text=self.oracle_text,
                legendary=self.legendary,
                is_artifact=self.is_artifact,
            )
        controller_id = (
            self.source.controller_id if self.source is not None
            else context.active_player.id
        )
        count = self.count
        if self.count_selector:
            from .. import continuous  # avoid the continuous↔effects import cycle

            count = continuous.count_selector(
                context.state, controller_id, self.count_selector, source=self.source
            )
        if self.count_from_trigger_event:
            event = context.trigger_event
            count = int((event or {}).get(self.count_from_trigger_event) or 0)
        if self.count_from_trigger_event_counter:
            count = int(
                ((context.trigger_event or {}).get("counters") or {})
                .get(self.count_from_trigger_event_counter, 0)
            )
        if self.x_multiplier is not None:
            count = self.x_multiplier * int(getattr(self.source, "x_paid", 0) or 0)
        if self.count_from_subject:
            count = _characteristic_of_subject(context, self.source, self.count_from_subject)
        if self.count_from_context in _TOKEN_COUNT_CONTEXT_ACCUMULATORS:
            from ...parser.oracle.spec import MAX_EFFECT_MAGNITUDE

            count = max(0, min(
                int(getattr(context, str(self.count_from_context), 0) or 0),
                MAX_EFFECT_MAGNITUDE,
            ))
        # "For each opponent, [you] create …" — one token apiece, all under
        # this effect's controller; when ``attacking`` each is paired with a
        # distinct opponent as its defender below.
        per_opp_defenders: list[str] = []
        if self.per_opponent:
            opponents = [
                p.id for p in context.state.living_players() if p.id != controller_id
            ]
            if not opponents:
                return
            # ``self.count`` tokens *per* opponent (usually 1); the defender
            # list repeats each opponent that many times so token i still
            # lines up with an opponent in the ``attacking`` zip below.
            per_opp_defenders = [o for o in opponents for _ in range(max(1, self.count))]
            count = len(per_opp_defenders)
        if count <= 0:
            return
        if self.per_opponent:
            creator_ids = [controller_id]
        elif self.creators == "each_player":
            creator_ids = [p.id for p in context.state.living_players()]
        elif self.creators == "each_opponent":
            creator_ids = [p.id for p in context.state.living_players() if p.id != controller_id]
        elif self.creators == "previous_target_controller":
            # "Exile target nonland permanent. **Its controller** incubates
            # X…" (Excise the Imperfect) — the token's creator is whoever
            # controlled the just-exiled permanent (its last-known
            # controller, RULE 608.2h — it is already gone), not this
            # spell's own controller. No previous target → nobody incubates.
            prev = list(getattr(context, "previous_targets", []) or [])
            owner = getattr(prev[0], "controller_id", None) if prev else None
            creator_ids = [owner] if owner is not None else []
        elif self.creators == "target":
            # "Target player creates a Treasure token." (Prismari Command) —
            # the chosen player, from this effect's own RULE 115 target.
            tgt = targets[0] if targets else None
            pid = getattr(tgt, "id", None)
            creator_ids = [pid] if pid is not None else []
        else:
            creator_ids = [controller_id]
        for creator_id in creator_ids:
            made = context.create_token(creator_id, card, count) or []
            if self.tapped:
                for token in made:
                    token.tapped = True
            if self.attacking and self.per_opponent:
                # RULE 508.4a per token: token i attacks opponent i.
                for token, opp_id in zip(made, per_opp_defenders):
                    opp = context.state.player_by_id(opp_id)
                    context.engine.put_onto_battlefield_attacking(
                        token,
                        defender={"kind": "player", "id": opp_id,
                                  "label": getattr(opp, "name", opp_id)},
                    )
            elif self.attacking:
                for token in made:
                    context.engine.put_onto_battlefield_attacking(token)
            if self.extra_counters:
                kind = str(self.extra_counters.get("kind", "+1/+1"))
                amount = self._resolve_extra_counter_amount(context)
                if amount:
                    for token in made:
                        context.add_counters(token, amount, kind, source=self.source)
            if self.grant_self_anthem:
                from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
                from ...parser.oracle.spec import EffectSpec

                for token in made:
                    anthem = build_effects(
                        [EffectSpec("anthem", {**self.grant_self_anthem, "affects": "self"})],
                        token,
                    )
                    token.static_effects.extend(anthem)
            if self.token_dies_gain_life is not None:
                # STX Pest: bind the token's own "when ~ dies, you gain N
                # life." — a `dies` (subject self) → `gain_life` trigger,
                # bound onto each token exactly as a printed ability would
                # be at bind-on-load.
                from ..binding.core import bind_ability  # effects↔binder cycle
                from ...parser.oracle.spec import AbilitySpec, EffectSpec

                for token in made:
                    spec = AbilitySpec(
                        "triggered",
                        [EffectSpec("gain_life", {"amount": self.token_dies_gain_life})],
                        trigger={"event": "DIES", "condition": {"subject": "self"}},
                        raw_text=f"when this creature dies, you gain {self.token_dies_gain_life} life.",
                    )
                    bound = bind_ability(spec, token)
                    if isinstance(bound, list):
                        token.triggered_abilities.extend(bound)
                    else:
                        token.triggered_abilities.append(bound)
            if self.parametric_keywords:
                # ENG-31: dock each numbered keyword onto the token itself and
                # synthesize its RULE 702-text triggered ability, the same
                # `attach_keyword` + `_keyword_triggered_abilities` pair a
                # printed keyword line goes through at bind-on-load.
                from ..binding.core import parametric_keyword_triggered_abilities  # effects↔binder cycle

                for pk in self.parametric_keywords:
                    name, n = str(pk.get("name") or ""), pk.get("n")
                    if not name or n is None:
                        continue
                    for token in made:
                        token.parametric_keywords[name] = {"n": int(n)}
                        token.triggered_abilities.extend(
                            parametric_keyword_triggered_abilities(token, name, int(n))
                        )
            # The referent for a following "the tokens are …" clause.
            context.created_objects.extend(made)


class CopyPermanentEffect(GameEffect):
    """Create a token that's a copy of a target permanent (RULE 707 / 707.2)
    — or, with ``target_kind=None``, of the effect's own source, untargeted
    (Bloodforged Battle-Axe's "create a token that's a copy of this
    Equipment" — no player choice involved, mirroring `TapEffect`'s/
    `AddCountersEffect`'s same ``target_kind=None`` self-acting mode).

    Targets a permanent (a creature by default — "create a token that's a copy
    of target creature") and makes ``count`` token copies under the effect's
    controller (its source's controller, else the active player). The basic
    version copies the printed card; layered/copy-of-copy nuances (RULE 707.2
    copiable values, other copy effects) are not modeled."""

    def __init__(
        self,
        count: int = 1,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        count_if_kicked: Optional[int] = None,
        count_from_trigger_event: Optional[str] = None,
        count_selector: Optional[str] = None,
        haste: bool = False,
        tapped: bool = False,
        attacking: bool = False,
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        not_legendary: bool = False,
        referent: str = "source",
        target_count: int = 1,
        target_count_max: Optional[int] = None,
        target_optional: bool = False,
        set_power: Optional[int] = None,
        set_toughness: Optional[int] = None,
        set_colors: Optional[list[str]] = None,
        extra_temp_keywords: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        #: PAR-18's own pronoun antecedent — "exile up to 1 target creature
        #: card from a graveyard. Create a token that's a copy of **that
        #: card**." (Ardyn/Anikthea-shaped): the copied object is neither a
        #: fresh RULE 115 target nor this effect's own source, but whatever
        #: an *earlier clause of the same ability* just targeted (RULE
        #: 608.2 resolution order — it has already resolved, in whatever
        #: zone it left the card in). ``target_kind=None`` keeps its
        #: existing "copy the source" default (``referent="source"``);
        #: ``referent="previous"`` is the new pronoun mode, the same
        #: `GameContext.previous_targets` `GoadEffect`/`FightEffect` already
        #: read for "goad it"/pronoun fights.
        #: ``referent="trigger_event"`` (Ashling, the Limitless, MEC-42 —
        #: "Whenever you sacrifice a nontoken Elemental, create a token
        #: that's a copy of **it**.") reads the firing event's own
        #: ``instance_id`` and resolves it via `GameState.find_object`,
        #: which searches every zone, not just the battlefield — unlike
        #: ``"previous"``'s RULE 608.2 pronoun (an earlier clause's own
        #: target), this is the trigger's *subject itself*, already gone
        #: from the battlefield by the time a SACRIFICE/DIES trigger
        #: resolves.
        self.referent = (
            referent
            if referent in (
                "source", "previous", "previous_each", "trigger_event", "linked_exile",
                "attachments_each",
            )
            else "source"
        )
        #: "…except it has haste." (Kiki-Jiki, Mirror Breaker-shaped) — a
        #: temp keyword grant on the freshly-made token(s), the same
        #: `temp_keywords` set every other resolve-time haste grant uses.
        self.haste = haste
        #: "…except it's a(n) X in addition to its other types" (the
        #: Cackling Counterpart/artifact-token-cycle "except it's an
        #: artifact…" shape) / "…except it isn't legendary." (Multiversal
        #: Recruitment-shaped) — `Card.as_copy`'s own modifiers, threaded
        #: through `RulesEngine.copy_permanent` rather than applied here, so
        #: the token's bound abilities are derived from the *modified* card
        #: from the start (`create_token` binds off whatever card it's given).
        self.add_types = add_types
        self.add_subtypes = add_subtypes
        self.not_legendary = not_legendary
        #: "…except it's a 1/1 red Balloon creature…" (The Jolly Balloon
        #: Man, MEC-40) — `Card.as_copy`'s own P/T-override params, threaded
        #: through the same way ``add_types``/``add_subtypes`` are.
        self.set_power = set_power
        self.set_toughness = set_toughness
        #: "…except it's a 4/4 **black** zombie" (PAR-18 residue — the
        #: Anikthea/Ardyn/God-Pharaoh's Gift/Hour of Eternity reanimator-
        #: token cycle): replace the copied card's colour identity outright
        #: with these WUBRG letters (`Card.as_copy`'s ``set_colors``).
        self.set_colors = list(set_colors) if set_colors is not None else None
        #: "…and it has flying and haste." (The Jolly Balloon Man, MEC-40)
        #: — ``haste`` above stays its own bool for backward compatibility
        #: (every existing caller already sets it that way); any *other*
        #: keyword granted alongside a copy goes here instead, applied the
        #: same ``temp_keywords`` way.
        self.extra_temp_keywords = list(extra_temp_keywords or [])
        #: "…create a **tapped and attacking** token that's a copy of …" /
        #: "…the token enters tapped and attacking." (RULE 508.4 — Calamity,
        #: Ghired, Stangg). ``tapped`` is applied to each made token; when
        #: ``attacking``, each is then put into combat via `RulesEngine.
        #: put_onto_battlefield_attacking`.
        self.enter_tapped = bool(tapped)
        self.enter_attacking = bool(attacking)
        # RULE 702.33b's *override* kicked-conditional ("Create a token
        # that's a copy of target creature. If this spell was kicked,
        # create five of those tokens instead." — Rite of Replication) —
        # same shape as `DealDamageEffect.amount_if_kicked`, just overriding
        # ``count`` instead of ``amount``.
        self.count_if_kicked = count_if_kicked
        #: "…create that many tokens that are copies of equipped
        #: creature." (Mirrormind Crown) — "that many" reads the firing
        #: `CREATE_TOKENS` event's own ``amount``, the same "read this
        #: firing's own payload" idiom `CreateTokenEffect.count_from_
        #: trigger_event` uses. Overrides ``count`` when set.
        self.count_from_trigger_event = count_from_trigger_event
        #: "…create a token that's a copy of ~ **for each card you've
        #: discarded this turn**." (Living Laser) — a `continuous.count_
        #: selector` name resolved at `apply`, overriding ``count`` (like
        #: ``count_from_trigger_event``, but off live state not the event).
        self.count_selector = count_selector
        self.target = target
        #: ``target_kind="attached_permanent"`` (Mirrormind Crown-shaped
        #: "…copies of **equipped** creature") is a third self-acting mode
        #: alongside the plain-target and ``None``-copies-the-source ones:
        #: whatever this Equipment/Aura is currently attached to, re-read
        #: live at resolution, the same concept `TapEffect`'s own
        #: ``"attached_permanent"`` mode uses.
        self._attached_mode = target_kind == "attached_permanent"
        #: "Choose any number of target creatures you control. For each of
        #: them, create a token that's a copy of that creature…" (Twinflame-
        #: shaped, MEC-12) — a genuine *per-target* multi-copy, unlike
        #: ``count``'s existing "N copies of the (one) target" meaning
        #: (Rite of Replication-shaped); named distinctly so both can
        #: combine on some future card without colliding.
        self.target_count = target_count
        self.target_spec = (
            TargetSpec(kind=target_kind, count=target_count, count_max=target_count_max, optional=target_optional)
            if target_kind is not None and not self._attached_mode else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if (
            self.target_spec is not None and not self._attached_mode
            and self.target_spec.effective_count != 1
        ):
            controller_id = (
                self.source.controller_id if self.source is not None
                else context.active_player.id
            )
            for one in _chosen_targets(targets, self.target_spec.effective_count):
                made = context.copy_permanent(
                    controller_id, one, 1,
                    add_types=self.add_types, add_subtypes=self.add_subtypes,
                    not_legendary=self.not_legendary,
                    set_power=self.set_power, set_toughness=self.set_toughness,
                    set_colors=self.set_colors,
                )
                context.created_objects.extend(made)
                if self.haste:
                    for obj in made:
                        obj.temp_keywords.add("haste")
                for kw in self.extra_temp_keywords:
                    for obj in made:
                        obj.temp_keywords.add(kw)
                self._apply_enter_state(context, made)
            return
        if self.referent == "previous_each" and self.target_spec is None:
            # "For **each** creature card exiled this way, create a token
            # that's a copy of **it**." (Foggy Swamp Visions) — one copy
            # per object an earlier clause of this same resolution acted on
            # (`GameContext.previous_targets`, RULE 608.2 order), each a
            # copy of *that* object. `self.count` copies of each.
            controller_id = (
                self.source.controller_id if self.source is not None
                else context.active_player.id
            )
            n = max(1, int(self.count) if isinstance(self.count, int) else 1)
            for one in list(context.previous_targets):
                if one is None:
                    continue
                made = context.copy_permanent(
                    controller_id, one, n,
                    add_types=self.add_types, add_subtypes=self.add_subtypes,
                    not_legendary=self.not_legendary,
                    set_power=self.set_power, set_toughness=self.set_toughness,
                    set_colors=self.set_colors,
                )
                context.created_objects.extend(made)
                if self.haste:
                    for obj in made:
                        obj.temp_keywords.add("haste")
                for kw in self.extra_temp_keywords:
                    for obj in made:
                        obj.temp_keywords.add(kw)
                self._apply_enter_state(context, made)
            return
        if self.referent == "attachments_each" and self.target_spec is None:
            # "For each Aura and Equipment attached to ~, create a token
            # that's a copy of it…" (Stangg, Echo Warrior).  This is the
            # live attachment-list sibling of ``previous_each``: all copies
            # remain in `created_objects` for a following `attach` node.
            controller_id = (
                self.source.controller_id if self.source is not None
                else context.active_player.id
            )
            count = self.count
            if self.count_selector:
                from .. import continuous

                count = continuous.count_selector(
                    context.state, controller_id, self.count_selector, source=self.source
                )
            for one in [
                obj for obj in context.state.permanents()
                if getattr(obj, "attached_to", None) == getattr(self.source, "instance_id", None)
                and ("aura" in str(getattr(obj.card, "type_line", "")).lower()
                     or "equipment" in str(getattr(obj.card, "type_line", "")).lower())
            ]:
                made = context.copy_permanent(
                    controller_id, one, count,
                    add_types=self.add_types, add_subtypes=self.add_subtypes,
                    not_legendary=self.not_legendary,
                    set_power=self.set_power, set_toughness=self.set_toughness,
                    set_colors=self.set_colors,
                )
                context.created_objects.extend(made)
                if self.haste:
                    for obj in made:
                        obj.temp_keywords.add("haste")
                for kw in self.extra_temp_keywords:
                    for obj in made:
                        obj.temp_keywords.add(kw)
                self._apply_enter_state(context, made)
            return
        # A referent/self mode (``target_spec is None``) must not grab a
        # stray ``targets[0]`` left over from a *different* effect in the
        # same resolution — the same gotcha `ExileEffect`'s self mode
        # documents (Mizzix's Mastery). It bites here for a `copy_permanent`
        # inside a villainous-choice option, applied with
        # ``targets=[the facing player]`` (The Master, Gallifrey's End).
        target = (
            self.target if self.target_spec is None
            else ((targets[0] if targets else None) or self.target)
        )
        if self._attached_mode:
            attached_to = getattr(self.source, "attached_to", None)
            target = context.state.find_object(attached_to) if attached_to is not None else None
        elif target is None and self.target_spec is None:
            if self.referent == "previous":
                prev = list(context.previous_targets)
                target = prev[0] if prev else None
            elif self.referent == "trigger_event":
                event = context.trigger_event
                iid = (event or {}).get("instance_id")
                target = context.state.find_object(iid) if iid is not None else None
            elif self.referent == "linked_exile":
                iid = getattr(self.source, "linked_exile_id", None)
                if self.source is not None:
                    self.source.linked_exile_id = None
                target = context.state.find_object(iid) if iid is not None else None
            else:
                target = self.source
        if target is None:
            return
        controller_id = (
            self.source.controller_id if self.source is not None
            else context.active_player.id
        )
        kicker_count = getattr(self.source, "kicker_count", 0) or 0
        count = self.count_if_kicked if (self.count_if_kicked is not None and kicker_count > 0) else self.count
        if self.count_from_trigger_event:
            event = context.trigger_event
            count = int((event or {}).get(self.count_from_trigger_event) or 0)
        if self.count_selector:
            from .. import continuous  # function-scoped: avoid an import cycle

            count = continuous.count_selector(
                context.state, controller_id, self.count_selector, source=self.source
            )
        if count > 0:
            made = context.copy_permanent(
                controller_id, target, count,
                add_types=self.add_types, add_subtypes=self.add_subtypes,
                not_legendary=self.not_legendary,
                set_power=self.set_power, set_toughness=self.set_toughness,
                set_colors=self.set_colors,
            )
            # RULE 608.2's "the tokens"/"it" referent for a following
            # clause — `create_token`'s own effect already does this; this
            # class just hadn't needed it until a delayed-sacrifice tail
            # (Kiki-Jiki) had to name what got made.
            context.created_objects.extend(made)
            if self.haste:
                for obj in made:
                    obj.temp_keywords.add("haste")
            for kw in self.extra_temp_keywords:
                for obj in made:
                    obj.temp_keywords.add(kw)
            self._apply_enter_state(context, made)

    def _apply_enter_state(self, context: GameContext, made: list[Any]) -> None:
        """RULE 508.4: a "tapped and attacking" token copy — tap it as it's
        made, then put it into the current combat."""
        if self.enter_tapped:
            for obj in made:
                obj.tapped = True
        if self.enter_attacking:
            for obj in made:
                context.engine.put_onto_battlefield_attacking(obj)


class EnterAsCopyReplacement(GameEffect):
    """"You may have this permanent enter the battlefield as a copy of
    target X" (RULE 614.1c/614.12, Clever Impersonator/Phantasmal Image/Copy
    Artifact/Vesuvan Shapeshifter-style) — a pure data holder, never applied
    imperatively (``apply`` returns ``None``, same "consulted elsewhere"
    idiom as `StaticAbility`/`ReplacementEffect`).

    `RulesEngine._offer_enter_as_copy` reads this off `GameObject.
    enter_as_copy_effects` at the one choke point where the permanent is
    about to be added to the battlefield (`resolve_top_of_stack`/
    `create_token`), *before* `add_to_battlefield`/`ENTERS_BATTLEFIELD` — so
    the object is never observably "itself" first, unlike the previous
    ENTERS_BATTLEFIELD-trigger modeling this replaces. A legal-target check
    there resolves the choice (interactively, if 2+ options) and calls
    `copy_mechanics.become_copy` before finishing battlefield entry.

    ``add_types``/``add_subtypes`` cover a card's own "except it's a(n) X in
    addition to its other types" clause (`Card.as_copy`).
    """

    def __init__(
        self,
        target_kind: str = "permanent",
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        optional: bool = True,
        description: str = "",
        extra_counter_if_creature: Optional[str] = None,
        extra_counter_if_planeswalker: Optional[str] = None,
        extra_counters_from_x: bool = False,
        grant_mana_option: Optional[dict[str, int]] = None,
        only_types: Optional[list[str]] = None,
        add_keywords: Optional[list[str]] = None,
        add_keywords_if_target_lacks: Optional[list[str]] = None,
        keep_own_abilities: bool = False,
        max_mana_value_from_mana_spent: bool = False,
    ) -> None:
        super().__init__(None)
        self.target_kind = target_kind
        #: "…of any creature on the battlefield with mana value less than
        #: or equal to the amount of mana spent to cast ~." (Mockingbird) —
        #: `GameObject.mana_spent_to_cast`, read live when the choice is
        #: offered (`RulesEngine._offer_enter_as_copy`).
        self.max_mana_value_from_mana_spent = max_mana_value_from_mana_spent
        self.add_types = list(add_types or [])
        self.add_subtypes = list(add_subtypes or [])
        self.optional = optional
        self.description = description
        #: "…except it loses all other card types" (Imposter Mech) — see
        #: `Card.as_copy`'s own ``only_types`` param.
        self.only_types = list(only_types) if only_types is not None else None
        #: "…except it has [keyword]" (Imposter Mech's granted Crew 3) —
        #: unconditional; see `Card.as_copy`'s ``add_keywords``.
        self.add_keywords = list(add_keywords or [])
        #: "…except it has [keyword] if [the copied creature] doesn't have
        #: [keyword]" (Flesh Duplicate's conditional Vanishing 3) — each
        #: entry granted only when the *target*'s own printed keywords
        #: don't already include it, checked in `resolve_enter_as_copy_
        #: choice` before `become_copy` runs.
        self.add_keywords_if_target_lacks = list(add_keywords_if_target_lacks or [])
        #: "…except it has ~'s other abilities" (Sakashima of a Thousand
        #: Faces) — RULE 707.2 would otherwise erase ~'s own printed
        #: abilities entirely; see `_resume_enter_as_copy`.
        self.keep_own_abilities = keep_own_abilities
        #: "…except it's an artifact and it has '{T}: Add {U}.'" (Machine
        #: God's Effigy) — a plain ``{T}``-only mana ability granted
        #: *onto the copy itself*, since RULE 707.2's copy replaces the
        #: original card's own printed text (including its own real
        #: "{T}: Add {U}." line) with the copied creature's, so that
        #: ability has to be re-added as part of this same "except" clause
        #: rather than assumed to survive. `GameObject.granted_mana_
        #: options` is the same plain-option list a layer-6 "Elves you
        #: control have '{T}: Add {B}.'" grant already appends to.
        self.grant_mana_option = dict(grant_mana_option) if grant_mana_option else None
        #: "…except it enters with an additional +1/+1 counter on it if
        #: it's a creature[, or a loyalty counter if it's a planeswalker]."
        #: (Spark Double) — a counter *kind* name (`RulesEngine.
        #: add_counters`'s vocabulary), applied once the copy is made and
        #: only when the resulting permanent is that type — a creature
        #: copy of a planeswalker (or vice versa) never happens, but the
        #: two are independent fields since either alone is a real printed
        #: shape elsewhere.
        self.extra_counter_if_creature = extra_counter_if_creature
        self.extra_counter_if_planeswalker = extra_counter_if_planeswalker
        #: "…except it enters with **X** additional +1/+1 counters on it."
        #: (Altered Ego, PAR-60) — the count is the copy spell's own
        #: announced {X} (`GameObject.x_paid`, RULE 107.3c), resolved when
        #: the copy is made rather than a fixed 1.
        self.extra_counters_from_x = bool(extra_counters_from_x)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_as_copy, not applied


class ChooseCreatureTypeReplacement(GameEffect):
    """"As ~ enters, choose a creature type." (RULE 601.2b-style
    characteristic-defining choice made as part of entering — not a
    triggered ability, so it's an ``enter_replacement`` like
    `EnterAsCopyReplacement`, just without a target — a pure data holder
    (``apply`` is never called).

    `RulesEngine._offer_enter_choices` reads this off `GameObject.
    enter_choice_effects` at the same battlefield-entry choke point
    `_offer_enter_as_copy` reads `enter_as_copy_effects` from, and stamps the
    answer onto `GameObject.chosen_type` — read back by `game/continuous.py`'s
    ``subtype_from_source`` selector param (Adaptive Automaton/Arcane
    Adaptation-shaped "creatures you control of the chosen type …"/"~ is the
    chosen type in addition to its other types" lords).
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseOpponentReplacement(GameEffect):
    """"As ~ enters, choose an opponent." (RULE 601.2b / PAR-45).

    A pre-entry choice holder, parallel to the colour/type choices.  The
    engine stamps the selected opponent id on ``chosen_player_id`` before
    the permanent enters, so a later ability can safely refer to it.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class ChooseBasicLandTypeReplacement(GameEffect):
    """"As ~ enters, choose a basic land type." (RULE 601.2b, PAR-4 —
    Realmwright/A-Thran Portal-shaped) — the basic-land-type sibling of
    `ChooseCreatureTypeReplacement`; see its docstring. Deliberately its own
    class (rather than a flag on `ChooseCreatureTypeReplacement`) so
    `RulesEngine._offer_enter_choices` can tell which fixed option list to
    offer, but it stamps the very same `GameObject.chosen_type` field —
    "the chosen type" grant clause (`continuous.py`'s ``subtype_from_source``
    selector, already shipped for the creature-type family) reads a bare
    subtype string either way and doesn't care which family produced it.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseColorReplacement(GameEffect):
    """"As ~ enters, choose a color." — the colour sibling of
    `ChooseCreatureTypeReplacement`; see its docstring. Stamps
    `GameObject.chosen_color`, read by `continuous.py`'s
    ``color_from_source`` selector param.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseNamedModeReplacement(GameEffect):
    """"As this enters, choose <Label1> or <Label2>." (Struggle for Project
    Purity: "choose Brotherhood or Enclave") — a third `enter_choice_effects`
    sibling of `ChooseCreatureTypeReplacement`/`ChooseColorReplacement`,
    for a small closed set of *named* flavour modes rather than a creature
    type/colour. Each subsequent named-bullet ability ("Brotherhood — ...",
    "Enclave — ...") stays a normal, always-bound ability, just gated by
    `effect_binder._trigger_condition`'s ``"named_mode"`` predicate
    checking the answer this stamps onto `GameObject.chosen_mode` — so the
    "wrong" mode's ability simply never fires, rather than never being
    bound at all.

    ``options`` is the card's own printed label list (``["Brotherhood",
    "Enclave"]``); `RulesEngine._offer_enter_choices` offers them as a
    lowercase-slug choice and stamps the answer onto `chosen_mode`.
    """

    def __init__(self, options: Optional[list[str]] = None, description: str = "") -> None:
        super().__init__(None)
        self.options = list(options or [])
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseCardNameReplacement(GameEffect):
    """"As ~ enters the battlefield, choose a card name." (MEC-12, Pithing
    Needle/Phyrexian Revoker-shaped) — a fourth `enter_choice_effects`
    sibling of `ChooseCreatureTypeReplacement`/`ChooseColorReplacement`/
    `ChooseNamedModeReplacement`, but naming any Magic card rather than
    picking from a small enumerable set: `RulesEngine._offer_enter_choices`
    offers a free-text choice (suggestions only, like `_request_name_card`'s
    own "name any card" idiom) and stamps the answer verbatim onto
    `GameObject.chosen_card_name` — read back by `continuous.
    group_selector_objects`'s ``card_name_from_source`` selector param.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseNumberReplacement(GameEffect):
    """"As this creature enters, choose a number." (RULE 601.2b, Sanctum
    Prelate — MEC-43) — a fifth `enter_choice_effects` sibling of
    `ChooseCreatureTypeReplacement`/`ChooseColorReplacement`/
    `ChooseNamedModeReplacement`/`ChooseCardNameReplacement`, the
    free-text-numeric case: `RulesEngine._offer_enter_choices` offers a
    free-text choice (same idiom `ChooseCardNameReplacement` uses for an
    unenumerable answer space) and stamps the parsed integer onto
    `GameObject.chosen_number` — read back by `continuous.cast_prohibited`'s
    ``max_mana_value="chosen_number"`` sentinel.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class BecomeCopyUntilEndOfTurnEffect(GameEffect):
    """*This* permanent becomes a copy of a target creature until end of
    turn (Cursed Mirror-style: "{T}: ~ becomes a copy of target creature
    until end of turn.").

    Unlike `RulesEngine.become_copy` (a permanent mutation, RULE 707.2), this
    reverts automatically at cleanup (RULE 514.2) — see `RulesEngine.
    become_copy_until_end_of_turn` and `GameEngine._step_cleanup`.
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
        if target is None or self.source is None or target is self.source:
            return
        context.become_copy_until_end_of_turn(self.source, target)


class BecomeCopyPermanentEffect(GameEffect):
    """*This* permanent permanently becomes a copy of a target creature
    (RULE 707.2 — Shameless Charlatan's "{2}{U}: ~ becomes a copy of
    another target creature."). Unlike `BecomeCopyUntilEndOfTurnEffect`
    this does *not* revert at cleanup — `RulesEngine.become_copy`."""

    def __init__(self, target: Any = None, source: Optional["GameObject"] = None,
                 target_kind: str = "creature") -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None or self.source is None or target is self.source:
            return
        context.engine.become_copy(self.source, target)


class SetCopyTargetEffect(GameEffect):
    """Choose/change the target a layer-1 conditional-copy static ability
    copies (Vesuvan Shapeshifter's "you may have it be a copy of another
    target creature") — sets `GameObject.copy_target_id`, which
    `continuous.recompute`'s layer-1 pass (`_apply_copy_layer`) reads fresh
    every pass. A simplified stand-in for RULE 707.9's "special action"
    timing (the same simplification tier `EnterAsCopyReplacement` uses
    elsewhere) — modeled as a costless activated ability instead.
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
        if target is None or self.source is None or target is self.source:
            return
        context.set_copy_target(self.source, target)



register(globals())
