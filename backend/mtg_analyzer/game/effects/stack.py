"""Spells and abilities on the stack: counters, copies, wards, and casting restrictions."""
from __future__ import annotations

from .core import GameEffect
from ._runtime import install, register

install(globals())

class CounterSpellEffect(GameEffect):
    """Counter a target spell on the stack (RULE 701.5).

    ``noncreature``/``card_types``/``mana_value`` narrow *which* spells are
    legal targets in the first place (RULE 601.2c/115 — "counter target
    noncreature spell", "… target instant or sorcery spell", "… target spell
    with mana value N"), folded into `target_spec.spell_filter` and enforced
    by `targeting.legal_targets`. ``unless_pays`` (RULE 601's "Mana Leak"
    template — "counter target spell unless its controller pays {N}") is a
    resolve-time condition instead: the target's controller gets an
    interactive choice, handled by `RulesEngine.counter_unless_pays`.
    """

    def __init__(
        self,
        target: Any = None,
        unless_pays: Optional[str] = None,
        noncreature: bool = False,
        card_types: Optional[list[str]] = None,
        subtype_any: Optional[list[str]] = None,
        mana_value: Optional[int] = None,
        color: Optional[str] = None,
        source: Optional["GameObject"] = None,
        target_from_trigger_event: Optional[str] = None,
        suspend_instead: Optional[int] = None,
        on_pay_effect_specs: Optional[list[dict]] = None,
        unless_pays_extra_selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.unless_pays = unless_pays
        #: "…unless its controller pays {1} plus an additional {1} for each
        #: creature in your party." (Concerted Defense, PAR-72) — a
        #: `continuous.count_selector` name, each point of which adds one
        #: more generic mana to ``unless_pays`` at resolution time (read for
        #: *this effect's own controller* — the counterspell's caster, whose
        #: party size the tax scales with, not the target's controller who
        #: actually pays it).
        self.unless_pays_extra_selector = unless_pays_extra_selector
        #: "…unless its controller pays {4}. **If they do**, you incubate 2."
        #: (Assimilate Essence) — serialized `EffectSpec` dicts applied only
        #: on the branch where the target's controller *pays* the
        #: ``unless_pays`` cost (so the spell resolves). Threaded through
        #: `RulesEngine.counter_unless_pays` and fired from
        #: `_resume_counter_unless_pays`'s "pay" answer; inert on the
        #: countered / can't-pay branches (they didn't pay).
        self.on_pay_effect_specs = list(on_pay_effect_specs or [])
        #: "…if no mana was spent to cast it, counter that spell." (Vexing
        #: Bauble) — "that spell" is the firing SPELL_CAST event's own
        #: object, not a RULE 115 target — the same "resolve off the firing
        #: event" idiom `DestroyEffect.target_from_trigger_event` already
        #: established.
        self.target_from_trigger_event = target_from_trigger_event
        #: RULE 702.62 (Delay, MEC-42): "exile it with N time counters on it
        #: instead of putting it into its owner's graveyard. If it doesn't
        #: have suspend, it gains suspend." Threaded straight through to
        #: `RulesEngine.counter_unless_pays`/`counter_spell`.
        self.suspend_instead = suspend_instead
        spell_filter: dict[str, Any] = {}
        if noncreature:
            spell_filter["noncreature"] = True
        if card_types:
            spell_filter["card_types"] = list(card_types)
        # "counter target **spirit or arcane** spell." (PAR-74, Hisoka's
        # Defiance) — a creature-subtype-or-"Arcane" OR filter, unlike
        # ``card_types``' fixed main-type set (`targeting._spell_matches_
        # filter`'s own ``subtype_any`` branch).
        if subtype_any:
            spell_filter["subtype_any"] = list(subtype_any)
        if mana_value is not None:
            spell_filter["mana_value"] = mana_value
        if color:
            spell_filter["color"] = color
        if target_from_trigger_event is None:
            self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def _unless_pays_cost(self, context: GameContext) -> Optional[str]:
        if not self.unless_pays_extra_selector:
            return self.unless_pays
        from .. import continuous  # function-scoped: avoid an import cycle

        controller_id = getattr(_controller_of(self.source, context), "id", None)
        extra = continuous.count_selector(
            context.state, controller_id, self.unless_pays_extra_selector, source=self.source,
        )
        base = ManaCost.parse(self.unless_pays or "").converted_mana_cost
        return f"{{{base + extra}}}"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        on_pay = self.on_pay_effect_specs or None
        unless_pays = self._unless_pays_cost(context)
        if self.target_from_trigger_event:
            event = context.trigger_event or {}
            instance_id = event.get(self.target_from_trigger_event)
            target = context.state.find_object(instance_id) if instance_id is not None else None
            if target is not None:
                context.counter(
                    target, unless_pays=unless_pays, source=self.source,
                    suspend_instead=self.suspend_instead, on_pay_effect_specs=on_pay,
                )
            return
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.counter(
                target, unless_pays=unless_pays, source=self.source,
                suspend_instead=self.suspend_instead, on_pay_effect_specs=on_pay,
            )


class CounterAbilityEffect(GameEffect):
    """Counter target activated or triggered ability (RULE 701.5b — Stifle/
    Trickbind, ENG-26).

    The stack-item-identity sibling of `CounterSpellEffect`: an ability
    `StackItem` has no `GameObject` of its own (`.obj` is `None`), so
    ``target_spec`` uses `targeting.py`'s ``"ability"`` kind
    (`StackItem.stack_id`-keyed) rather than ``"spell"``
    (`GameObject.instance_id`-keyed). No ``unless_pays``/type-filter
    params — no printed card needing either has reached this yet; add
    them the same way `CounterSpellEffect` carries its own if one does.
    """

    def __init__(self, target: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind="ability")

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.counter_ability(target)


class CopySpellEffect(GameEffect):
    """Copy a target spell on the stack (RULE 707.10 — Dualcaster Mage/Flare
    of Duplication/Reiterate "copy target instant or sorcery spell").

    ``card_types`` narrows which spells are legal targets (default instant/
    sorcery), folded into ``target_spec.spell_filter`` exactly as
    `CounterSpellEffect` does. ``count`` copies are made (Flare of
    Duplication makes one; a hypothetical "copy it twice" would set 2). The
    copy is controlled by *this effect's source's controller* (RULE 707.10c
    — the copier), created by `RulesEngine.copy_spell`. "You may choose new
    targets for the copy" is a legal-but-optional refinement (RULE 707.10c);
    this MVP keeps the original's targets (the default outcome), which every
    real card in scope allows — a genuine new-target choice would open a
    `pending_choice`, deferred until a card needs it.
    """

    def __init__(
        self,
        card_types: Optional[list[str]] = None,
        count: int = 1,
        source: Optional["GameObject"] = None,
        target_count: int = 1,
        optional: bool = False,
        target_kind: str = "spell",
        spell_from_trigger_event: Optional[str] = None,
        controller_from_trigger_event: Optional[str] = None,
        count_selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        #: "…copy it for each time you've cast your commander from the
        #: command zone this game." (Thunderclap Drake, PAR-60) — the copy
        #: count read live from a `continuous.count_selector` at resolution
        #: rather than a fixed ``count``; 0 makes no copies.
        self.count_selector = count_selector
        self.spell_from_trigger_event = spell_from_trigger_event
        self.controller_from_trigger_event = controller_from_trigger_event
        spell_filter: dict[str, Any] = {}
        if card_types:
            spell_filter["card_types"] = list(card_types)
        # "Copy any number of target instant and/or sorcery spells." (Display
        # of Power) — ``target_count`` > 1 offers several *distinct* spell
        # targets (each getting ``count`` copies), the RULE 601.2c "any
        # number" idiom Fire Covenant's own ``count=10`` UI cap already
        # established for "any number of target creatures", applied here to
        # a spell target instead of a permanent one. Untargeted when the
        # spell instead comes off the *firing trigger event*
        # (``spell_from_trigger_event`` — "whenever a player casts an
        # instant or sorcery spell, that player copies it", Bonus Round-
        # shaped: RULE 603.1's "it" is the spell that triggered this, not a
        # RULE 601.2c target choice at all) — same ``target_kind=None`` +
        # ``and … is None`` guard `DestroyEffect.target_from_trigger_event`
        # already established.
        if spell_from_trigger_event is None:
            self.target_spec = TargetSpec(
                kind=target_kind, spell_filter=spell_filter or None, count=target_count, optional=optional,
            )
        else:
            self.target_spec = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.spell_from_trigger_event is not None:
            event = context.trigger_event or {}
            instance_id = event.get(self.spell_from_trigger_event)
            target = context.state.find_object(instance_id) if instance_id is not None else None
            if target is None:
                return
            controller_id = (
                event.get(self.controller_from_trigger_event)
                if self.controller_from_trigger_event
                else getattr(self.source, "controller_id", None)
            )
            if controller_id is None:
                return
            n = self._copies(context, controller_id)
            if n > 0:
                context.copy_spell(target, controller_id, n)
            return
        if not targets:
            return
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        n = self._copies(context, controller_id)
        if n <= 0:
            return
        for target in targets:
            context.copy_spell(target, controller_id, n)

    def _copies(self, context: GameContext, controller_id: str) -> int:
        """The fixed ``count``, or the live board/history count ``count_selector`` names."""
        if self.count_selector is None:
            return self.count
        from ..continuous import count_selector as _count_selector  # avoid import cycle

        return _count_selector(context.state, controller_id, self.count_selector, source=self.source)


class ConjureDuplicateIntoHandEffect(GameEffect):
    """"Conjure a duplicate of that spell into your hand." (Spellchain
    Scatter, PAR-124) — the hand-zone sibling of `CopySpellEffect`'s
    ``spell_from_trigger_event`` mode: "that spell" is RULE 603.1's own
    firing-event referent (the spell this `create_turn_trigger` ability
    fired for), not a RULE 115 target, resolved the identical way.
    """

    def __init__(
        self,
        spell_from_trigger_event: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.spell_from_trigger_event = spell_from_trigger_event

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.spell_from_trigger_event is None:
            return
        event = context.trigger_event or {}
        instance_id = event.get(self.spell_from_trigger_event)
        target = context.state.find_object(instance_id) if instance_id is not None else None
        if target is None:
            return
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        duplicate = context.conjure_duplicate_into_hand(target, controller_id)
        if duplicate is not None:
            context.created_objects.append(duplicate)


class CopyAbilityEffect(GameEffect):
    """Copy an activated ability on the stack (RULE 707.10 — Rings of
    Brighthearth's "you may pay {2}. If you do, copy that ability. You may
    choose new targets for the copy.").

    "That ability" is a RULE 603.1 pronoun naming *the ability that fired
    this trigger*, not a RULE 601.2c target choice — the same untargeted
    shape `CopySpellEffect.spell_from_trigger_event` already reads off
    `GameContext.trigger_event`, except an ability `StackItem` has no
    `GameObject`/``instance_id`` of its own to name it by (ENG-26); it's
    identified by `StackItem.stack_id` instead, remembered onto
    `GameObject.remembered_stack_id` by the enclosing `PayCostThenEffect`'s
    ``remember_trigger_stack_id=True`` (the trigger-event window has closed
    by the time this "if you do" branch actually runs).

    **Documented simplification**, the same one `CopySpellEffect`'s own
    docstring already establishes for a spell copy: "you may choose new
    targets for the copy" keeps the original's targets rather than opening
    a fresh interactive pick — no real card in scope needs a genuinely
    different target on the copy.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        stack_id = getattr(self.source, "remembered_stack_id", None)
        if stack_id is None:
            return
        item = next((i for i in context.state.stack if i.stack_id == stack_id), None)
        if item is None:
            return
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        context.copy_ability(item, controller_id)


class CopySelfSpellEffect(GameEffect):
    """"Target player discards two cards. That player may copy this spell
    and may choose a new target for that copy." (Chain of Smog, MEC-43) —
    the copier is whoever the *preceding* clause of this same spell
    targeted (`GameContext.previous_targets`, the same pronoun idiom
    `FightEffect`/`GoadEffect` use), not this spell's own caster.

    **Documented simplification**, the same one `CopySpellEffect`'s own
    docstring and `CopySelfIfCastFromGraveyardEffect` already establish:
    "may" is read as unconditional (always copies — declining has no real
    downside worth modeling) and "may choose a new target" keeps the
    original target instead of opening a fresh interactive pick.
    """

    def __init__(self, controller: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.controller = controller

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        from ..effect_operands import player_for

        controller = player_for(self.controller, context, self.source, targets)
        controller_id = getattr(controller, "id", None)
        if controller_id is None:
            return
        context.copy_self_spell(self.source, controller_id, targets=None)


class CopySelfIfCastFromGraveyardEffect(GameEffect):
    """"If this spell was cast from a graveyard, you may copy this spell
    and may choose a new target for the copy." (Sevinne's Reclamation,
    MEC-42) — reads `GameObject.cast_via_flashback` directly off this
    effect's own source: still ``True`` at this point, since `RulesEngine.
    _finish_resolving_stack_item`'s own "exile instead of graveyard"
    branch (which clears it) only runs *after* every one of the spell's
    effects — this one included — has already resolved. Opens
    `RulesEngine.copy_self_spell` rather than `CopySpellEffect`'s ordinary
    `copy_spell` (which looks up a *live* `StackItem` — the original is
    already off the stack by now).

    **Documented simplification**: "you may" is read as unconditional
    (always copies when cast from a graveyard) — the same accepted
    simplification this engine already gives every other untargeted
    "you may" trigger with no real downside to declining.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or not getattr(self.source, "cast_via_flashback", False):
            return
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        context.copy_self_spell(self.source, controller_id, targets=targets)


class ChangeTargetEffect(GameEffect):
    """Change the target of a target spell already on the stack (RULE
    115.4/601.2c — Misdirection/Deflecting Swat).

    The *changing* player (RULE 115.4a: this effect's own controller, not
    the targeted spell's) picks a fresh legal target, recomputed against
    the current board — not whatever was legal when that spell was cast.
    ``single_target`` folds into ``target_spec.spell_filter`` as
    Misdirection's own restriction ("target spell **with a single
    target**"); Deflecting Swat has no such restriction printed, but this
    MVP still only retargets a spell with exactly one existing target —
    see `RulesEngine.change_target`'s docstring for why. ``optional`` is
    Deflecting Swat's "**you may** choose new targets"; Misdirection's own
    "Change the target" is mandatory.

    ``spell_or_ability`` (ENG-26) is Deflecting Swat's actual printed scope
    ("choose new targets for target spell **or ability**") — the union
    `targeting.py` kind covering both a spell `StackItem` (keyed by its own
    `GameObject.instance_id`, as `single_target`'s ``spell_filter`` still
    only narrows) and an ability one (keyed by `StackItem.stack_id`, which
    has no *spell*-shaped filter to narrow by). `RulesEngine.change_target`
    reads whichever one the chosen `StackItem` turns out to be.

    ``card_types`` narrows the *targeted* spell by its own printed types
    ("target **instant or sorcery** spell with a single target" — Hydroelectric
    Specimen), folded into the same ``target_spec.spell_filter`` dict
    ``single_target`` uses (`targeting._spell_matches_filter`'s
    ``card_types`` key).

    ``redirect_to_source`` is Spellskite's actual printed shape ("Change a
    target of target spell or ability **to this creature**") — not a free
    choice among every legal alternative the way Misdirection/Deflecting
    Swat's own player-facing pick is, but a forced redirect to one specific
    permanent (this effect's own source), silently declining (RULE 115.4a's
    "no legal target, doesn't change") if the source isn't itself a legal
    target of whatever's being retargeted.
    """

    def __init__(
        self,
        target: Any = None,
        single_target: bool = False,
        optional: bool = False,
        spell_or_ability: bool = False,
        card_types: Optional[list[str]] = None,
        redirect_to_source: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.optional = optional
        self.redirect_to_source = redirect_to_source
        if spell_or_ability:
            self.target_spec = TargetSpec(kind="spell_or_ability")
        else:
            spell_filter: dict[str, Any] = {}
            if single_target:
                spell_filter["single_target"] = True
            if card_types:
                spell_filter["card_types"] = list(card_types)
            self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.change_target(
                target, optional=self.optional, source=self.source,
                redirect_to_source=self.redirect_to_source,
            )


class GainControlOfSpellEffect(GameEffect):
    """"Gain control of target noncreature spell. You may choose new
    targets for it." (Commandeer) — the still-on-the-stack sibling of the
    ordinary battlefield control-change effects (`GainControlUntilEndOfTurn
    Effect`/`GainControlBySourceEffect`), which all assume the target is
    already a permanent. The retarget reuses `RulesEngine.change_target`
    outright rather than a second `TargetSpec` of its own — it's the exact
    same spell already gained, so there's nothing new to choose *which*
    stack item is affected. Run *before* the control change (not after) so
    RULE 115.4a's "you"/"your" in the target description still resolves
    against the spell's *original* controller, matching `change_target`'s
    own documented reading.
    """

    def __init__(self, target: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind="spell", spell_filter={"noncreature": True})

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        context.change_target(target, optional=True, source=self.source)
        context.gain_control_of_spell(target, controller_id)


class ExchangeControlSpellEffect(GameEffect):
    """RULE 701.10i: exchanging control of a permanent and a **spell** on
    the stack — the sibling `ExchangeControlEffect` doesn't cover (its own
    swap is a plain `GameObject.controller_id` flip, which only makes sense
    for something already on the battlefield). Two printed shapes:

      * ``reflexive_spell=True`` — "Whenever `<event>`, **you may** exchange
        control of this creature and **that spell**." (Perplexing Chimera,
        RULE 603.3d): the spell is the reflexive trigger subject, never a
        RULE 115 target of this effect's own (``target_spec=None`` — the
        "you may" pause and the target-baking both happen in
        `triggers_mixin._place_triggers`'s reflexive branch before this ever
        runs, see `RulesEngine._pending_trigger_reflexive_target`), so
        ``targets`` here is just ``[that spell]`` and the permanent side is
        always this effect's own source.
      * otherwise — "Exchange control of target noncreature spell and
        target creature." (Sudden Substitution): two independent RULE 115
        targets, the spell always first (``target_spec``) so ``targets[0]``/
        ``targets[1]`` read the same regardless of pick order, mirroring
        `ExchangeControlEffect`'s own ``first_target_kind`` two-target mode.

    Both then let "the spell's controller" (the *new* one, post-swap) choose
    new targets for it (`RulesEngine.change_target`, ``optional=True`` —
    RULE 601.2c/115.5's "may").

    The permanent's controller becomes the spell's controller and
    vice-versa, mirroring `ExchangeControlEffect.apply` exactly for the
    permanent side; the spell side reuses `RulesEngine.gain_control_of_spell`
    (Commandeer's own primitive), which mirrors `StackItem.controller_id`
    onto the underlying `GameObject` too — so a plain `spell.controller_id`
    read is always the spell's *current* controller, no separate stack-item
    lookup needed. A no-op (same controller already, or the spell already
    left the stack) leaves both untouched.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        permanent_target_kind: Optional[str] = None,
        spell_filter: Optional[dict[str, Any]] = None,
        reflexive_spell: bool = False,
    ) -> None:
        super().__init__(source)
        self._reflexive_spell = reflexive_spell
        if reflexive_spell:
            self.target_spec = None
        else:
            self.target_spec = TargetSpec(kind="spell", spell_filter=dict(spell_filter or {}))
            self.extra_target_specs = (
                TargetSpec(kind=permanent_target_kind or "creature"),
            )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._reflexive_spell:
            permanent = self.source
            spell = targets[0] if targets else None
        else:
            spell = targets[0] if targets and len(targets) > 0 else None
            permanent = targets[1] if targets and len(targets) > 1 else None
        if permanent is None or spell is None:
            return
        if permanent not in context.state.permanents():
            return
        if not any(item.obj is spell for item in context.state.stack):
            return  # the spell already resolved/was countered/left the stack
        old_permanent_controller = permanent.controller_id
        old_spell_controller = spell.controller_id
        if old_permanent_controller == old_spell_controller:
            return
        permanent.controller_id = old_spell_controller
        permanent.summoning_sick = True  # RULE 302.6, mirroring ExchangeControlEffect
        context.gain_control_of_spell(spell, old_permanent_controller)
        context.recompute()
        context.change_target(spell, optional=True, source=self.source)


class WardEffect(GameEffect):
    """A ward triggered ability's own resolution body (RULE 702.21a):
    "counter that spell or ability unless that player pays [cost]."

    Unlike `CounterSpellEffect`/`CounterSpellEffect.unless_pays` (where the
    *target's controller* decides whether to pay — RULE 601's "Mana Leak"
    template), ward's decision belongs to the *caster* of the countered
    item. ``item``/``caster_id``/``cost`` are fixed the moment the warded
    permanent became a target (RULE 603.3a's trigger-time lock-in), not
    re-derived here — so even if the caster or the item's legality changes
    before this resolves, the ability still asks the right player about the
    right item (RULE 603.6/603.10 "look back in time").

    Never built via `EffectRegistry` — always constructed directly by
    `RulesEngine.check_ward`, one instance per warded target, each wrapped
    in its own `StackItem` placed on top of the triggering spell/ability so
    normal priority-passing carries it (RULE 603.3), rather than resolved
    inline as a synchronous choice.
    """

    def __init__(
        self,
        item: Any,
        caster_id: str,
        cost: Any,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.item = item
        self.caster_id = caster_id
        self.cost = cost

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        ability_controller_id = self.source.controller_id if self.source is not None else None
        context.engine.resolve_ward_effect(
            self.item, self.caster_id, self.cost, ability_controller_id=ability_controller_id
        )


class CounterUnlessPayEffect(GameEffect):
    """MEC-19: "Counter it/that spell[or ability] unless that player/its
    controller pays `<cost>`." — a genuine printed triggered ability's own
    resolution body (RULE 603.1's "whenever ~ becomes the target of a
    spell/ability [an opponent/you control(s)], …" family), for the ~150
    real cards that spell this out as ordinary card text rather than
    printing the **Ward** keyword (RULE 702.21, already handled by
    `WardEffect`/`RulesEngine.check_ward`/`resolve_ward_effect` — this is
    the same rules outcome, just reached as an ordinary triggered ability
    that goes on the stack and gets a normal priority window, rather than
    Ward's own special-cased RULE 702.21c "push straight on top" timing).

    Deliberately a thin adapter onto `resolve_ward_effect`, not a parallel
    implementation: the targeted spell/ability and its caster are looked up
    fresh, off `GameContext.trigger_event`'s own `stack_id`/`controller_id`
    (`EventType.BECOMES_TARGET`), then handed straight to the exact same
    "can they afford it? open a real pay-or-not choice; if not, counter"
    flow ward already has — including reusing its ``"ward"`` `pending_
    choice` kind, since the two are rules-identical from that point on.
    """

    def __init__(
        self,
        cost: str = "",
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = cost
        # Usually this effect resolves off a BECOMES_TARGET event.  A small
        # direct-counter family (Perplex) instead names a spell as a normal
        # RULE 115 target, but shares the same non-mana "unless" cost path.
        if target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..costs import parse_activation_cost  # function-scoped: import cycle

        event = context.trigger_event
        if event is not None:
            stack_id = event.get("stack_id")
            item = next((i for i in context.state.stack if i.stack_id == stack_id), None)
            if item is None:
                return  # the targeting spell/ability already left the stack
            caster_id = event.get("controller_id")
            if caster_id is None:
                return
        else:
            item = (targets or [None])[0]
            if item is None or getattr(item, "obj", None) is None:
                return
            caster_id = item.obj.controller_id
        ability_controller_id = self.source.controller_id if self.source is not None else None
        context.engine.resolve_ward_effect(
            item,
            caster_id,
            parse_activation_cost(self.cost_text),
            ability_controller_id=ability_controller_id,
        )


class CantBeCounteredEffect(GameEffect):
    """Marker: "This spell can't be countered." (RULE 118-area).

    Bound like any other one-shot effect — via `spell_effect` on an instant/
    sorcery's own body, or `static` on a permanent's standing line — and so
    lands in ``obj.spell_effects``/``obj.static_effects`` respectively
    (`game/binding/core.py`'s ordinary dispatch, no special-casing needed).
    It carries no continuous behaviour: `continuous.recompute` only ever
    reads `StaticAbility` instances off `static_effects` (this isn't one), and
    a spell's own resolution just calls `apply()` like every other effect in
    its list. The only consumer is `RulesEngine._is_cant_be_countered`, which
    scans both lists for this marker *before* the object would otherwise
    leave the stack — the one moment "can't be countered" actually matters.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class LookAtCardsEffect(GameEffect):
    """"Look at the top card of target player's library."/"Look at a card at
    random in target player's hand." (Mishra's Bauble/Urza's Bauble) — a
    genuine RULE 115 target (so hexproof/protection still matters), but no
    game-state consequence: this engine has no reason to hide the peeked
    card from the querying player in the first place (a solo/goldfish board
    already shows every zone to its one real player, and a bot never reads
    hidden information regardless), so there's nothing left for "look" to
    actually *do*. Kept as its own effect rather than dropped to an empty
    ``effects`` list precisely so the target requirement survives.
    """

    def __init__(
        self, target: Any = None, source: Optional["GameObject"] = None, target_kind: str = "player",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class MarkCantBeCounteredEffect(GameEffect):
    """Marks a spell handed in via ``targets[0]`` — never a RULE 115 target
    of its own — as "can't be countered", by appending a
    `CantBeCounteredEffect` marker onto its `GameObject.spell_effects` so
    `RulesEngine._is_cant_be_countered`'s existing scan finds it with no new
    consumer-side code — the resolve-time counterpart to that class's own
    bind-time marker, for a spell that already exists (Vexing Shusher's
    "Target spell can't be countered."). The "this turn" grants that cover
    spells not yet cast are `CantBeCounteredThisTurnEffect`.

    ``target_kind`` (MEC-40, Vexing Shusher's own "{R/G}: Target spell
    can't be countered.") opts this effect into a genuine RULE 115 target
    of its own instead of relying on some other caller to hand a spell in
    via ``targets[0]`` — ``None`` (the default) leaves that to the caller.
    """

    def __init__(
        self, source: Optional["GameObject"] = None, target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None:
            return
        # `GameObject.spell_effects` is only ever populated by `effect_
        # binder.bind_from_catalogue` when the card has a genuine
        # ``"spell_effect"``-kind body (MEC-40 — found while testing Domri,
        # Anarch of Bolas's own "creature spells you cast this turn can't
        # be countered": the overwhelming majority of creature/artifact/
        # enchantment spells have *no* such body at all — only triggered/
        # static/activated abilities — so `hasattr` alone silently dropped
        # this marker for any of them, a dormant bug this ability's own
        # printed wording exercises directly, not just an edge case).
        if not hasattr(target, "spell_effects"):
            target.spell_effects = []
        target.spell_effects.append(CantBeCounteredEffect())


class GrantCantBeCounteredEffect(GameEffect):
    """A standing "Spells you control can't be countered." grant (Hexing
    Squelcher-shaped) — unlike `CantBeCounteredThisTurnEffect`
    (a *resolve-time*, "this turn" grant), this is a bind-time
    `static_effects` marker on the granting permanent itself, scanned by
    `RulesEngine._is_cant_be_countered` for every spell as it's cast
    (never expires while the permanent is in play). ``scope`` is
    ``"you"`` (every spell) or ``"creature_spells_you_control"`` (RULE
    502-area creature-only grants — Rionya/Sarkhan Unbroken-shaped).
    """

    def __init__(
        self, scope: str = "you", color: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.scope = scope
        #: "**Green** spells you control can't be countered." (Allosaurus
        #: Shepherd, MEC-40) — ``scope="color_spells_you_control"``'s own
        #: colour, checked against `GameObject.colors` at `RulesEngine.
        #: _is_cant_be_countered`'s existing scan point.
        self.color = str(color).upper() if color else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class GrantSearchProhibitedEffect(GameEffect):
    """"Your opponents can't search libraries." (Stranglehold-shaped, RULE
    701.19a: an effect that instructs a prohibited player to search simply
    doesn't — the search is skipped, not replaced). A bind-time
    `static_effects` marker, the same minimal shape
    `GrantCantBeCounteredEffect` uses; scanned by `RulesEngine.
    _request_search`'s own guard rather than the layer engine (a
    permission, not a characteristic).

    ``scope="opponents"`` (the default, Stranglehold's own shape) prohibits
    only players other than this effect's own controller; ``scope="all"``
    (MEC-35, "**Players** can't search libraries." — Leonin Arbiter) drops
    that exemption, prohibiting the controller too.
    """

    def __init__(self, scope: str = "opponents", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.scope = scope if scope in ("opponents", "all") else "opponents"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class GrantSearchLimitedToTopNEffect(GameEffect):
    """"If an opponent would search a library, that player searches the
    top N cards of that library instead." (Aven Mindcensor-shaped, RULE
    701.19a-adjacent — a *narrowing* of the search rather than
    `GrantSearchProhibitedEffect`'s outright block). A bind-time
    `static_effects` marker, scanned by `RulesEngine._search_zone_objects`
    exactly where `GrantSearchProhibitedEffect` is scanned by `request_
    search` — the library portion of the pool becomes just its top ``n``
    cards (in order) rather than the whole thing, for anyone who isn't this
    effect's own controller.
    """

    def __init__(self, n: int = 4, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.n = n

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class BecomeSaddledEffect(GameEffect):
    """RULE 702.171a: "Saddle N" — "…: This permanent becomes saddled
    until end of turn." (Guardian Sunmare, MEC-40). Not a RULE 613 layer
    effect (being saddled changes no characteristic) — a plain sticky
    `GameObject.saddled_until_turn` stamp, the same "needs no cleanup-step
    reset, just goes stale next turn" idiom `GraveyardCastPermissionEffect.
    expires_turn` uses.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            self.source.saddled_until_turn = context.state.internal_turn.number


class GrantSkipExtraTurnsEffect(GameEffect):
    """"If an opponent would begin an extra turn, that player skips that
    turn instead." (Stranglehold-shaped, RULE 500.7/700.4). A bind-time
    `static_effects` marker; `GameEngine.begin_turn`'s own extra-turn pop
    loop skips a queued taker matching this grant instead of handing them
    the turn.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class MillThenDamageEachOpponentByMvEffect(GameEffect):
    """"You mill a card[ for each past vote], then ~ deals damage to each
    opponent equal to the total mana value of cards milled this way."
    (Fateful Tempest's past-vote outcome, PAR-60.)

    A single atomic effect: mills ``count`` cards from this effect's own
    controller's library (``count`` is already vote-scaled by
    `_tally_and_apply_vote` when this rides a ``per_vote_specs`` entry),
    sums their mana values, and deals that much to each opponent. Keeping
    the mill and the MV tally in one effect sidesteps needing a
    "total-mv-milled-this-resolution" `GameContext` accumulator for the one
    card that wants it.
    """

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = int(count)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.count <= 0:
            return
        before = len(player.graveyard)
        context.mill(player, self.count)
        milled = player.graveyard[before:]
        total_mv = sum(int(getattr(o.card, "converted_mana_cost", 0) or 0) for o in milled)
        if total_mv <= 0:
            return
        for opp in context.state.players:
            if opp.id != player.id:
                context.deal_damage(opp, total_mv, self.source)


class MillEffect(GameEffect):
    """Put the top ``count`` cards of a player's library into their graveyard.

    Untargeted ("Mill three cards.") mills the effect's controller; a
    ``target_kind`` of ``"player"`` mills a chosen player (RULE 701.13).

    ``count_selector`` (MEC-43, Altar of Dementia — "target player mills
    cards equal to the sacrificed creature's power") makes ``count``
    dynamic instead of fixed: a `continuous.count_selector` name, evaluated
    for this effect's own **source's controller** (not the milled player —
    "the sacrificed creature's power" is a fact about what *this ability's
    controller* just paid, unrelated to who gets milled), overriding the
    fixed ``count`` when set.

    ``selector="event_controller"`` (Mesmeric Orb, MEC-43 round 4E —
    "whenever a permanent becomes untapped, **that permanent's
    controller** mills a card.") mills whoever the firing `EventType.
    UNTAPPED` event names as ``controller_id`` — neither this ability's
    own controller (no target at all here, unlike "target player mills…")
    nor a RULE 115 target (nothing to choose: the group condition already
    picked which permanent untapped), the same "read the firing event's
    own payload" idiom `LoseLifeEffect.selector="event_player"`/
    `DealDamageEffect.selector` already use for an analogous "that player"
    subject.

    ``selector="trigger_subject_controller"`` (PAR-117, Poisonbelly Ogre-
    shaped — "whenever another creature enters, its controller mills a
    card.") is `"event_controller"`'s RULE 603.1 group-subject sibling:
    the firing event names the acting object by ``instance_id`` (MEC-28's
    ``group_subject`` pronoun scope) rather than stamping a
    ``controller_id`` of its own directly, so this reads the object's
    controller off the live board (or its RULE 400.7 last-known one, for a
    DIES-shaped trigger) instead of a flat event field.

    ``selector="attached_permanent_controller"`` (PAR-117, Chronic Flooding
    — "whenever enchanted land becomes tapped, its controller mills three
    cards.") is RULE 303.4c's "enchanted permanent" sibling of
    ``"trigger_subject_controller"`` above: the referent is this Aura's own
    host (`effect_conditions.subject_of("attached", ...)`, its ``attached_to``
    link) rather than a RULE 603.1 group-trigger's firing object.
    `LoseLifeEffect.selector` of the same name already exists for this exact
    referent (Parasitic Impetus) — this is its `MillEffect` sibling.
    """

    def __init__(
        self,
        count: int = 1,
        target_kind: Optional[str] = None,
        count_selector: Optional[str] = None,
        selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        #: How many cards: a number or an `effect_amounts` operand ("target player mills X cards,
        #: where X is that spell's mana value" — Cloudhoof Kirin).
        self.count = count
        self.count_selector = count_selector
        self.selector = selector
        if target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector == "event_controller":
            player = _event_player(context)
        elif self.selector == "previous_subject_controller":
            # "Counter target spell … . Clash … . If you win, **that
            # spell's controller** mills four cards." (Broken Ambitions) —
            # `context.previous_targets[0]` is the countered spell, now in
            # a graveyard with no controller (RULE 608.2h last-known info),
            # so fall back to its `owner_id`. PAR-120: "that player" reaches
            # this same selector for an antecedent that already targeted a
            # *player* directly ("target player mills N cards" preceded by
            # a clause naming that player again as "that player") — a
            # referent with no `controller_id`/`owner_id` of its own, so it
            # is the mill's recipient outright rather than looked up.
            prev = list(context.previous_targets)
            obj = prev[0] if prev else None
            if obj is not None and getattr(obj, "instance_id", None) is None:
                player = obj
            else:
                who_id = getattr(obj, "controller_id", None) or getattr(obj, "owner_id", None)
                try:
                    player = context.state.player_by_id(who_id) if who_id is not None else None
                except (KeyError, ValueError):
                    player = None
        elif self.selector == "trigger_subject_controller":
            # RULE 603.1 group-subject sibling of "previous_subject_
            # controller" above — "its" is whichever object satisfied this
            # ability's own group-subject trigger condition (MEC-28), read
            # via the same referent `effect_conditions.subject_of
            # ("entering", ...)` resolves off the firing event's own
            # ``instance_id``. A DIES-shaped trigger's object is gone from
            # the battlefield but keeps its last-known `controller_id`
            # (RULE 400.7 — nothing here resets it), so no owner_id
            # fallback is needed the way the countered-spell case above does.
            from .. import effect_conditions  # function-scoped: effects↔conditions cycle

            obj = effect_conditions.subject_of("entering", context, self.source, targets)
            who_id = getattr(obj, "controller_id", None)
            try:
                player = context.state.player_by_id(who_id) if who_id is not None else None
            except (KeyError, ValueError):
                player = None
        elif self.selector == "attached_permanent_controller":
            # RULE 303.4c's "enchanted land" sibling of "trigger_subject_
            # controller" above — "its" is the Aura's own host, read via the
            # same `effect_conditions.subject_of("attached", ...)` referent
            # `LoseLifeEffect.selector` of the same name already uses
            # (PAR-117, Chronic Flooding: "whenever enchanted land becomes
            # tapped, its controller mills three cards.").
            from .. import effect_conditions  # function-scoped: effects↔conditions cycle

            obj = effect_conditions.subject_of("attached", context, self.source, targets)
            who_id = getattr(obj, "controller_id", None)
            try:
                player = context.state.player_by_id(who_id) if who_id is not None else None
            except (KeyError, ValueError):
                player = None
        elif self.target_spec is not None:
            player = targets[0] if targets else None
        else:
            player = context.active_player
        if player is None:
            return
        count = self._measured(self.count, context, targets)
        if self.count_selector:
            from .. import continuous  # function-scoped: avoid an import cycle

            controller_id = getattr(self.source, "controller_id", None)
            count = continuous.count_selector(
                context.state, controller_id, self.count_selector, source=self.source
            )
        before = len(player.graveyard)
        context.mill(player, count)
        milled = player.graveyard[before:]
        context.moved_objects.extend(milled)
        # RULE 701.13: "this way" is this one mill instruction, not every
        # card moved earlier in the resolution.
        context.milled_objects = list(milled)



register(globals())
