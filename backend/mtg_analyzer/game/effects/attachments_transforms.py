"""Tapping, combat restrictions, attachments, transformations, and phasing."""
from __future__ import annotations

from .core import GameEffect
from .counters_tokens import GrantUntilEffect, PumpEffect
from ._runtime import install, register

install(globals())

#: Selectors accepted by ``TapEffect`` for untargeted mass tap/untap actions.
#: Kept next to the effect rather than the facade so its implementation owns
#: both the validation vocabulary and the operation it validates.
_TAP_SELECTORS: frozenset[str] = frozenset(
    {
        "creatures_you_control",
        "permanents_you_control",
        "nonland_permanents_you_control",
        "other_creatures_you_control",
        "attacking_creatures",
        "lands_you_control",
    }
)

def _is_valid_tap_selector(selector: "Optional[str | dict]") -> bool:
    if isinstance(selector, dict):
        # PAR-128: a structured battlefield selector (`{"zone","of","filter"}`,
        # PARSER_VERSION 473) — "tap all creatures your opponents control".
        return selector.get("zone", "battlefield") == "battlefield"
    if selector in _TAP_SELECTORS or selector == "previous_selector":
        return True
    # "…untap it and all Samurai you control." (Godo, Bandit Warlord) /
    # "Untap all Forests you control." (Woodland Guidance) —
    # `continuous.group_selector_objects`'s own subtype-scoped branches
    # already handle any such name; this just widens the whitelist to admit
    # them rather than growing `_TAP_SELECTORS` one subtype at a time.
    return bool(selector) and selector.startswith(
        ("creatures_you_control_of_type_", "lands_you_control_of_type_",
         "creatures_you_control_of_color_")
    )


#: `GameContext.previous_selector` value naming "the creatures the previous
#: mass-damage clause hit" (`GameContext.damaged_this_way`) rather than a
#: `continuous.group_selector_objects` selector.
DAMAGED_GROUP_SENTINEL = "damaged_this_way"
#: `GameContext.previous_selector` value for a mass effect scoped to a chosen player
#: (`TapEffect.selector_player`): ``{PLAYER_SCOPED_GROUP_KEY: <selector>, "controller_id": <player>}``.
PLAYER_SCOPED_GROUP_KEY = "scoped_selector"
#: The creature-only mass damage selectors a following "those creatures" may
#: replay (`DealDamageEffect.selector`); player-inclusive ones stay out.
PREVIOUS_GROUP_DAMAGE_SELECTORS: frozenset[str] = frozenset(
    {"each_creature", "each_other_creature", "each_creature_opponents_control"}
)


def previous_group_objects(context: GameContext, source: Optional["GameObject"], selector: str) -> list[Any]:
    """The battlefield objects ``selector`` (a `GameContext.previous_selector`
    value) names — the damaged set for `DAMAGED_GROUP_SENTINEL`, else
    `continuous.group_selector_objects`."""
    if selector == DAMAGED_GROUP_SENTINEL:
        return [o for o in context.damaged_this_way if o in context.state.battlefield]
    from ..continuous import group_selector_objects  # avoid the continuous↔effects cycle

    if isinstance(selector, dict) and PLAYER_SCOPED_GROUP_KEY in selector:
        # "Tap all creatures target player controls. Those creatures …" — the group is that
        # selector *for the player the clause chose*, not for the ability's controller.
        return group_selector_objects(
            context.state, selector.get("controller_id"), selector[PLAYER_SCOPED_GROUP_KEY],
            src=source,
        )

    return group_selector_objects(
        context.state, getattr(context, "acting_player_id", None) or getattr(source, "controller_id", None),
        selector, src=source,
    )


class TapEffect(GameEffect):
    """Tap (or untap) a target permanent — or the source itself (RULE 701.21/22).

    ``target_kind=None`` (unlike the default ``"permanent"``) makes it act on
    the effect's own source with no player choice involved — "untap it" in a
    "whenever this creature becomes tapped, untap it" trigger (Dionus, Elvish
    Archdruid), mirroring `AddCountersEffect`'s untargeted mode.

    ``target_kind="source"`` means the *same thing* — the effect's own source
    — but says so explicitly, which matters only because `effect_binder.
    _retarget_implicit_subject_effects` rewrites a bare ``None`` into
    ``"trigger_subject"`` under a RULE 603.1 ``{"subject": "group"}``
    trigger. That rewrite is right for the parser's "untap **it**" (Raiyuu,
    Storm's Edge — "whenever a Samurai or Warrior you control attacks alone,
    untap it", where "it" is whichever creature attacked) and wrong for a
    card whose group trigger unambiguously names *itself* (Grinding
    Station — "whenever an artifact enters, you may untap **this
    artifact**", RULE 109.2). Both spell an untargeted untap as a bare
    ``None``, so the difference has to be written down rather than inferred:
    an entry that means its own source says ``"source"``, and the rewrite
    leaves it alone.

    ``target_kind="attached_permanent"`` is a third, similarly targetless
    mode — "{U}: Tap enchanted creature."/"{U}: Untap enchanted creature."
    (Freed from the Real/Pemmin's Aura-shaped Aura activated abilities):
    acts on whatever the effect's own source (the Aura) is *currently*
    `attached_to`, re-read live at resolution (an Aura can move via
    Reconfigure-adjacent effects), mirroring `effect_binder._subject_
    condition`'s `"attached_permanent"` *trigger*-subject concept — this is
    the same idea applied to an effect's *target* instead.

    ``selector`` (see `_TAP_SELECTORS`) is a fourth mode — "untap all
    creatures you control" (Village Bell-Ringer's ETB) — untargeted, acting
    on every object `continuous.group_selector_objects` picks out for the
    effect's own controller, rather than a single target/self/attached host.

    ``count`` > 1 targets several independent objects (RULE 115.1a
    generalized to N>=2, the same shape `DestroyEffect.count` uses) — "untap
    up to two target lands" (Snap-shaped).

    ``previous_subject=True`` (PAR-15's "Untap those creatures." — Colossal
    Heroics' own trailing sentence, following "Any number of target
    creatures each get +2/+2 until end of turn.") is `ReturnToHandEffect`'s
    same pronoun shape: no target of its own, acting on whatever the
    preceding clause's own multi-target group was (`GameContext.
    previous_targets`).

    ``creature_filter`` narrows a real RULE 115 target the same way
    `DestroyEffect`/`UnblockableEffect`'s own field does — "target attacking
    creature" (`{"attacking": True}`, Raph & Leo, Sibling Rivals' own
    hand-authored simplification, MEC-28).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "permanent",
        untap: bool = False,
        optional: bool = False,
        selector: Optional[str] = None,
        count: int = 1,
        count_max: Optional[int] = None,
        previous_subject: bool = False,
        trigger_event_key: Optional[str] = None,
        creature_filter: Optional[dict] = None,
        subtypes: Optional[list[str]] = None,
        choose_tap_or_untap: bool = False,
        colors: Optional[list[str]] = None,
        count_selector: Optional[str] = None,
        target_operand: Any = None,
        selector_player: Optional[str] = None,
        remove_from_combat: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "Remove all attacking creatures from combat and untap them." (Illusionist's Gambit) — a mass
        #: ``selector`` group that is also taken out of combat (RULE 506.4): it stops attacking and the
        #: blocks around it are undone. The group is left on `GameContext.previous_targets` so a following
        #: clause can say "each of those creatures" even though they no longer match the selector.
        self.remove_from_combat = bool(remove_from_combat)
        #: PAR-128: "tap all creatures **target opponent controls**" (Tempest
        #: Caller) / "tap all lands target player controls" (Gulf Squid) — a
        #: mass ``selector`` scoped to a RULE 115 *player* target
        #: (``"player"``/``"opponent"``). The selector is written ``of: "you"``
        #: and evaluated for the chosen player rather than the controller.
        #: "tap all lands **defending player** controls" (Pretender's Claim) / "…**that player**
        #: controls" (Nature's Will) name the player off the ability's own context, the way
        #: `DealDamageEffect.group_player` does; "target player/opponent" is a RULE 115 target.
        self.selector_player = (
            selector_player if selector_player in ("player", "opponent", "defending", "event_player", "chosen") else None
        )
        #: "Tap up to **X** target creatures" (Crashing Wave) — a
        #: `TargetSpec.count_selector` (``"source_x_paid"``), resolved at
        #: announce time; see `ExileEffect._count_selector`.
        self._count_selector = count_selector
        #: "tap target `<c1>` or `<c2>` creature an opponent controls"
        #: (Tidebinder Mage) — `TargetSpec.colors`' OR narrowing.
        self.colors = tuple(colors) if colors else None
        self.untap = untap
        #: An object referent rather than a RULE 115 target.  This lets a
        #: composed rider act on a relation of an earlier choice, e.g. the
        #: host of the Equipment just unattached by Akiri.
        self.target_operand = target_operand
        #: "You may tap **or untap** target permanent." (Derevi, Empyrial
        #: Tactician, MEC-42) — a real choice at resolution, layered on top
        #: of RULE 115's own "up to one" target optionality (``optional``
        #: above only ever decides *whether there's a target at all*).
        #: Opens `RulesEngine._request_tap_or_untap_choice` instead of
        #: applying ``untap`` directly.
        self.choose_tap_or_untap = choose_tap_or_untap
        self.selector = selector if _is_valid_tap_selector(selector) else None
        #: "Untap them." (Valley Floodcaller, MEC-41), narrowing a
        #: ``selector`` group by subtype the same way `PumpEffect.subtypes`/
        #: `AddCountersEffect.subtypes` already do — Valley Floodcaller's
        #: own trigger duplicates the pump clause's ``["bird", "frog",
        #: "otter", "rat"]`` list rather than a cross-clause pronoun, since
        #: `GameContext.previous_selector` only carries the bare selector
        #: *name* (MEC-28), not any subtype narrowing layered on top of it.
        self.subtypes = [s.lower() for s in subtypes] if subtypes else None
        self._attached_mode = target_kind == "attached_permanent"
        #: ENG-29's sibling: MEC-28's RULE 603.1 "group" subject — "whenever
        #: a creature you control attacks alone, ... untap it/that creature."
        #: — where the acting object isn't a static field on the source (an
        #: Aura's ``attached_to``) but whichever object actually satisfied
        #: *this firing* of a group trigger condition, re-read off
        #: `GameContext.trigger_event` at resolution time (the same "read
        #: the current firing's own payload" idiom `GrantKeywordToTrigger
        #: SubjectEffect` already uses for Tyvar Kell's emblem — this is that
        #: idiom applied to `TapEffect` instead of a keyword grant).
        #: ``trigger_event_key`` names which event field carries the acting
        #: object's id (``instance_id`` by default, `effect_binder.
        #: _subject_event_key`'s same per-event-type lookup — e.g.
        #: ``source_id`` for a DAMAGE-sourced group condition).
        self._trigger_subject_mode = target_kind == "trigger_subject"
        #: The explicit spelling of ``target_kind=None``'s "act on my own
        #: source" — see the class docstring for why it has to be sayable.
        self._source_mode = target_kind == "source"
        self.trigger_event_key = trigger_event_key or "instance_id"
        self.previous_subject = previous_subject
        if self.selector_player in ("player", "opponent") and self.selector is not None:
            self.target_spec = TargetSpec(kind=self.selector_player)
            return
        self.target_spec = (
            TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max,
                creature_filter=creature_filter, colors=self.colors,
                count_selector=count_selector,
            )
            if target_kind is not None and not self._attached_mode
            and not self._trigger_subject_mode and not self._source_mode
            and self.selector is None and not previous_subject and target_operand is None
            else None
        )

    def target_polarity(self) -> Optional[str]:
        # Untapping is a favour (untap your own blocker/attacker); tapping
        # down is a combat trick against whoever's permanent it is (usually
        # an opponent's would-be blocker or attacker).
        return "beneficial" if self.untap else "harmful"

    @staticmethod
    def _remove_from_combat(context: GameContext, obj: "GameObject") -> None:
        """RULE 506.4: ``obj`` leaves combat — no longer attacking, nobody blocked by or blocking it."""
        for other in context.state.battlefield:
            if getattr(other, "blocking", None) == obj.instance_id:
                other.blocking = None
            if obj.instance_id in (getattr(other, "additional_blocking", None) or []):
                other.additional_blocking = [i for i in other.additional_blocking if i != obj.instance_id]
            if obj.instance_id in (getattr(other, "blocked_by", None) or []):
                other.blocked_by = [i for i in other.blocked_by if i != obj.instance_id]
        obj.attacking = False
        obj.combat_defender = None
        obj.blocking = None
        obj.additional_blocking = []
        obj.blocked_by = []

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_operand is not None:
            from ..effect_operands import object_for

            target = object_for(self.target_operand, context, self.source, targets)
            if target is not None:
                context.set_tapped(target, tapped=not self.untap)
            return
        if self.previous_subject:
            for one in list(context.previous_targets):
                context.set_tapped(one, tapped=not self.untap)
            return
        if self.selector is not None:
            from ..continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(context, "acting_player_id", None) or getattr(
                self.source, "controller_id", None)
            if self.selector_player is not None:
                if self.selector_player == "defending":
                    chosen = _defending_player_of(self.source, context)
                elif self.selector_player == "event_player":
                    chosen = _event_player(context, key="target_id")
                elif self.selector_player == "chosen":
                    # "…all nonland permanents that player controls" after "choose an opponent".
                    from .. import effect_conditions  # function-scoped: effects↔conditions cycle

                    chosen = effect_conditions.subject_of("chosen_player", context, self.source, targets)
                else:
                    chosen = targets[0] if targets else self.target
                if chosen is None or getattr(chosen, "id", None) is None:
                    return
                controller_id = chosen.id
            selector = self.selector
            if selector == "previous_selector":
                # PAR-128: "Creatures you control get +2/+1 until end of turn.
                # **Untap those creatures.**" (War Flare) — the group the
                # preceding clause's own mass selector acted on, read off
                # `GameContext.previous_selector` the same way `PumpEffect`'s
                # MEC-28 sentinel is. No such clause this resolution → no-op.
                selector = context.previous_selector
                if not selector:
                    return
            group = (
                previous_group_objects(context, self.source, selector)
                if self.selector == "previous_selector"
                else group_selector_objects(context.state, controller_id, selector, src=self.source)
            )
            if self.subtypes is not None:
                group = [
                    obj for obj in group
                    if any(
                        s in obj.card.type_line.partition("—")[2].strip().lower().split()
                        for s in self.subtypes
                    )
                ]
            for obj in group:
                if self.remove_from_combat:
                    self._remove_from_combat(context, obj)
                context.set_tapped(obj, tapped=not self.untap)
            if self.remove_from_combat:
                context.previous_targets = list(group)
            if self.selector_player is not None and self.selector != "previous_selector":
                # The core's default (the bare selector) would replay this for the ability's
                # controller; "those creatures" are the chosen player's.
                context.previous_selector = {
                    PLAYER_SCOPED_GROUP_KEY: self.selector, "controller_id": controller_id,
                }
            return
        if self._attached_mode:
            host_id = getattr(self.source, "attached_to", None)
            target = context.state.find_object(host_id) if host_id is not None else None
            if target is not None:
                context.set_tapped(target, tapped=not self.untap)
                # "Tap enchanted creature. … put three stun counters on **it**." (Kitnap, PAR-135): the
                # host is what the next clause's pronoun names, though nothing *targeted* it.
                context.previous_targets = [target]
            return
        if self._trigger_subject_mode:
            event = context.trigger_event
            obj_id = (event or {}).get(self.trigger_event_key)
            target = context.state.find_object(obj_id) if obj_id is not None else None
            if target is not None:
                context.set_tapped(target, tapped=not self.untap)
            return
        if self.target_spec is not None and (
            self.target_spec.count_selector or self.target_spec.effective_count != 1
        ):
            # A `count_selector`-sized spec ("tap up to X target creatures"
            # — Crashing Wave) took its real count at announce time; trust
            # `targets` as sized (the `AddCountersEffect`/`ExileEffect`
            # guard). Otherwise slice to this effect's own static count.
            chosen = (
                list(targets or [])
                if self.target_spec.count_selector
                else _chosen_targets(targets, self.target_spec.effective_count, self.target)
            )
            for one in chosen:
                context.set_tapped(one, tapped=not self.untap)
            return
        target = (targets[0] if targets else None) or self.target
        if self._source_mode:
            # Explicitly this effect's own source, never a passed-in target
            # and never the group trigger's acting object.
            target = self.source
        if target is None and self.target_spec is None:
            target = self.source
        if target is not None:
            if self.choose_tap_or_untap:
                context.engine._request_tap_or_untap_choice(target, source=self.source)
            else:
                context.set_tapped(target, tapped=not self.untap)


class SkipNextUntapEffect(GameEffect):
    """"[That / target] `<permanent>` doesn't untap during its controller's
    next untap step." (Barl's Cage, and the ~95-card "Tap target creature.
    It doesn't untap …" tempo family — Chillbringer, Berg Strider, the Frost
    Lynx cycle, Pollen Lullaby's clash payoff, …).

    Sets `GameObject.skip_next_untap` — the exact one-time flag RULE 702.19b
    exert already uses, consumed and cleared in `GameEngine._step_untap`.
    A pure rider: it does *not* tap anything, so "Tap X. It doesn't untap …"
    is the ordinary two-clause `[tap, skip_next_untap{previous_subject}]`
    sequence, "it" resolved off `GameContext.previous_targets`.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        previous_subject: bool = False,
        optional: bool = False,
        creature_filter: Optional[dict[str, Any]] = None,
        subject: Optional[str] = None,
        target_operand: Any = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: An event/relationship referent rather than a fresh RULE 115
        #: target. PAR-84's Kashi-Tribe family reads the creature damaged by
        #: this trigger from its firing DAMAGE event.
        self.target_operand = target_operand
        self.previous_subject = previous_subject
        #: "clash with an opponent. If you win, **creatures that player
        #: controls** don't untap during the player's next untap step."
        #: (Pollen Lullaby) — ``"clashed_opponent"`` applies the flag to
        #: every creature that player currently controls, no RULE 115
        #: target. "that player" is `GameContext.clashed_opponent`.
        self.subject = subject
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional, creature_filter=creature_filter)
            if target_kind is not None and not previous_subject and subject is None
            and target_operand is None else None
        )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_operand is not None:
            from ..effect_operands import object_for

            obj = object_for(self.target_operand, context, self.source, targets)
            objs = [obj] if obj is not None else []
        elif self.subject == "clashed_opponent":
            opp = getattr(context, "clashed_opponent", None)
            if opp is None:
                return
            objs = [
                o for o in context.state.battlefield
                if o.is_creature and o.controller_id == opp.id
            ]
        elif self.subject == "previous_selector":
            # PAR-128: "Tap all attacking creatures. **Those creatures** don't
            # untap …" (Clinging Mists) — the preceding clause's mass-selector
            # group, `GameContext.previous_selector`.
            selector = getattr(context, "previous_selector", None)
            if not selector:
                return
            objs = previous_group_objects(context, self.source, selector)
        elif self.previous_subject:
            objs = list(context.previous_targets)
        elif self.target_spec is None:
            objs = [self.target or self.source]
        else:
            objs = list(targets or ([self.target] if self.target is not None else []))
        for obj in objs:
            if obj is not None and obj in context.state.battlefield:
                obj.skip_next_untap = True


#: MEC-28: which effect types' own `selector` `_apply_effects_partitioned`
#: tracks into `GameContext.previous_selector` for a following "they" clause
#: — see that function's docstring. `TapEffect`-only today, matching
#: `effect_binder._GROUP_SUBJECT_RETARGET_FIELDS`'s identically narrow,
#: widen-only-as-a-real-card-needs-it convention.
_PREVIOUS_SELECTOR_EFFECT_TYPES: tuple[type, ...] = (TapEffect, PumpEffect, GrantUntilEffect)


class UnblockableEffect(GameEffect):
    """"Target creature can't be blocked this turn" (Rogue's Passage) — sets
    `GameObject.temp_unblockable`, read directly by `GameEngine.can_block`
    and cleared at cleanup (RULE 514.2).

    ``creature_filter`` (Access Tunnel's "target creature with power 3 or
    less") mirrors `DestroyEffect`'s own qualified-target filter.

    ``selector`` (PAR-79 — "creatures [you control] can't be blocked this
    turn", Jace/Keeper of Keys/Veiling Oddity) is `CantBlockEffect`'s own
    mass RULE 601.2c form, mirrored here: a `continuous.group_selector_
    objects` name switches from the targeted form to the untargeted one.

    ``count``/``count_max``/``optional`` (PAR-79 — "up to 2 target
    creatures can't be blocked this turn.", Ghostform) generalize the
    single-target form to RULE 115.1a's N>=2 shape, the same
    `CantBlockEffect`-shaped ``count``/``optional`` pair.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        creature_filter: Optional[dict[str, Any]] = None,
        selector: Optional[str] = None,
        count: int = 1,
        count_max: Optional[int] = None,
        count_selector: Optional[str] = None,
        optional: bool = False,
        previous_subject: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.selector = selector
        #: PAR-79 sixth increment: "put 2 +1/+1 counters on target creature
        #: you control. **That creature** can't be blocked this turn."
        #: (Stealth Mission/Trygon Prime-shaped) — the previous clause's own
        #: target, not a fresh RULE 115 target of this effect's own
        #: (`GameContext.previous_targets`, the same referent
        #: `GrantUntilEffect.previous_subject` already reads).
        self.previous_subject = previous_subject
        #: ``target_kind=None`` — "~ can't be blocked this turn" from the
        #: creature's own activated ability (Giant Koi, ENG-32): no RULE 115
        #: target, acts on this effect's own source.
        #: "Enchanted/equipped creature can't be blocked this turn": acts on the
        #: host via ``attached_to`` (RULE 301.5/303.4), no RULE 115 target.
        self._attached_mode = target_kind == "attached_permanent"
        self.target_spec = (
            None if selector or previous_subject or self._attached_mode else (
                TargetSpec(
                    kind=target_kind, creature_filter=creature_filter,
                    count=count, count_max=count_max, count_selector=count_selector, optional=optional,
                )
                if target_kind is not None else None
            )
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector:
            from ..continuous import group_selector_objects  # avoid the continuous<->effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            for obj in group_selector_objects(
                context.state, controller_id, self.selector, src=self.source
            ):
                obj.temp_unblockable = True
            return
        if self.previous_subject:
            for obj in context.previous_targets:
                if obj is not None:
                    obj.temp_unblockable = True
            return
        if self._attached_mode:
            attached_id = getattr(self.source, "attached_to", None)
            target = context.state.find_object(attached_id) if attached_id is not None else None
            if target is not None:
                target.temp_unblockable = True
            return
        if self.target_spec is not None and self.target_spec.effective_count != 1:
            for obj in (targets or []):
                if obj is not None:
                    obj.temp_unblockable = True
            return
        target = (targets[0] if targets else None) or self.target
        if target is None and self.target_spec is None:
            target = self.source
        if target is not None:
            target.temp_unblockable = True


class CantBeRegeneratedEffect(GameEffect):
    """"Target creature can't be regenerated this turn." (Gravebind, Hurr Jackal,
    Furnace Brood) / "It can't be regenerated this turn." (Engulfing Flames) /
    "A creature dealt damage this way can't be regenerated this turn."
    (Incinerate, Flamebreak) — sets `GameObject.temp_cant_be_regenerated`, which
    `RulesEngine.destroy` reads to skip the regeneration replacement pass
    (RULE 701.16), cleared at cleanup (RULE 514.2).

    Three subjects, one per way a card names it: a RULE 115 target, the
    preceding clause's target (``previous_subject``), or the creatures the
    preceding damage clause actually hit (``damaged_this_way``,
    `GameContext.damaged_this_way`, MEC-81's hit set).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        previous_subject: bool = False,
        damaged_this_way: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.previous_subject = previous_subject
        self.damaged_this_way = damaged_this_way
        self.target_spec = (
            TargetSpec(kind=target_kind)
            if target_kind is not None and not previous_subject and not damaged_this_way
            else None
        )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.damaged_this_way:
            objs = list(context.damaged_this_way)
        elif self.previous_subject:
            objs = list(context.previous_targets)
        else:
            objs = list(targets or ([self.target] if self.target is not None else []))
        for obj in objs:
            if obj is not None and getattr(obj, "is_creature", False):
                obj.temp_cant_be_regenerated = True


class CantBlockEffect(GameEffect):
    """"Target creature can't block this turn" (Falter/Abandon the Post) and
    its untargeted group form ("creatures your opponents control can't block
    this turn") — sets `GameObject.temp_cant_block`, read by
    `GameEngine.can_block` and cleared at cleanup (RULE 514.2).

    The blocker-side mirror of `UnblockableEffect` above, and shaped like it:
    ``selector`` (a `continuous.group_selector_objects` name) switches from
    RULE 115's targeted form to RULE 601.2c's mass one, ``count``
    generalizes the targeted form to N targets (RULE 115.1a — "up to two
    target creatures can't block this turn"), and ``filter`` narrows the mass
    form by characteristics `group_selector_objects`'s own selector params
    can't express ("creatures **without flying** can't block this turn" —
    `combat.matches_object_filter`'s shared vocabulary).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        count: int = 1,
        optional: bool = False,
        previous_subject: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.selector = selector
        self.filter = dict(filter or {})
        #: "…If it's a creature, **it** can't block this turn." (Searing
        #: Barb) — no RULE 115 target of its own; acts on whatever the
        #: previous clause targeted (`GameContext.previous_targets`), the
        #: same idiom `PumpEffect.previous_subject` uses.
        self.previous_subject = bool(previous_subject)
        self.target_spec = (
            None
            if (selector or previous_subject)
            else TargetSpec(kind=target_kind, count=count, optional=optional)
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.previous_subject:
            prev = context.previous_targets[0] if context.previous_targets else None
            if prev is not None and getattr(prev, "is_creature", False):
                prev.temp_cant_block = True
            return
        if self.selector:
            from .. import combat
            from ..continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            for obj in group_selector_objects(
                context.state, controller_id, self.selector, src=self.source
            ):
                if obj.is_creature and combat.matches_object_filter(obj, self.filter):
                    obj.temp_cant_block = True
            return
        count = self.target_spec.effective_count if self.target_spec is not None else 1
        # Only this effect's own ``count`` targets, off the front of a
        # possibly-shared list — see `DestroyEffect.apply`'s comment.
        chosen = (
            targets[:count] if targets else ([self.target] if self.target is not None else [])
        )
        for one in chosen:
            if one is not None:
                one.temp_cant_block = True


class GrantCombatRestrictionEffect(GameEffect):
    """""~ can't be blocked by creatures with power 2 or less **this turn**"
    (Cavern Stomper) / "target creature can't be blocked by Walls this turn"
    (Tower of Coireall) — the resolve-time sibling of the standing
    ``combat_restriction`` static.

    Grants the *same* clamped param dict onto `GameObject.
    temp_combat_restrictions`, which `combat.combat_restrictions` reads
    alongside the recompute-derived list, so no combat-time check has to know
    which of the two a restriction came from. Cleared at cleanup (RULE 514.2).

    ``restrict_to_source=True`` stamps ``self.source``'s own instance id onto
    the restriction's ``filter`` at apply time (``{"instance_id": ...}``) —
    the pairwise "target creature can't block **~** this turn"/"target
    creature blocks **~** this turn if able" shapes, where the *specific*
    attacker named is this ability's own source and so can't be baked into
    the `AbilitySpec` at parse time (it varies per game object). Combined
    with the ``cant_block_filtered``/``must_block_target`` restriction
    kinds, `combat.matches_object_filter`'s ``instance_id`` key then narrows
    the (otherwise unfiltered) restriction to that one attacker.
    """

    def __init__(
        self,
        restriction: Optional[dict[str, Any]] = None,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        restrict_to_source: bool = False,
        selector: Optional[str] = None,
        selector_params: Optional[dict[str, Any]] = None,
        creature_filter: Optional[dict[str, Any]] = None,
        count: int = 1,
        count_max: Optional[int] = None,
        count_selector: Optional[str] = None,
        optional: bool = False,
        previous_subject: bool = False,
    ) -> None:
        super().__init__(source)
        self.restriction = dict(restriction or {})
        self.target = target
        self.restrict_to_source = restrict_to_source
        self.selector = selector
        self.selector_params = dict(selector_params or {})
        #: PAR-98: "they can't be blocked this turn except by creatures with
        #: haste" (Run for Your Life) — the creatures an earlier clause of the
        #: same resolution targeted (`GameContext.previous_targets`, the same
        #: referent `UnblockableEffect.previous_subject` reads), not a fresh
        #: RULE 115 target of this effect's own.
        self.previous_subject = previous_subject
        # No ``target_kind`` at all is the self form ("~ can't be blocked
        # by … this turn"), matching `PumpEffect`'s own self/target split.
        self.target_spec = (
            TargetSpec(
                kind=target_kind, creature_filter=creature_filter, count=count,
                count_max=count_max, count_selector=count_selector, optional=optional,
            )
            if target_kind and not previous_subject else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector:
            from ..continuous import group_selector_objects
            if not self.restriction.get("kind"):
                return
            for obj in group_selector_objects(
                context.state, getattr(self.source, "controller_id", None), self.selector,
                self.selector_params, self.source,
            ):
                obj.temp_combat_restrictions.append(dict(self.restriction))
            return
        if self.previous_subject:
            recipients = [o for o in context.previous_targets if o is not None]
        elif self.target_spec is None:
            recipients = [self.source]
        else:
            # Every declared target (RULE 115.1a's "1 or 2 target creatures"),
            # not just the first; the legacy ``self.target`` is the single-
            # target fallback for a caller that pre-resolved one.
            recipients = [t for t in (targets or []) if t is not None] or [self.target]
        if not self.restriction.get("kind"):
            return
        restriction = dict(self.restriction)
        if self.restrict_to_source and self.source is not None:
            restriction["filter"] = {
                **dict(restriction.get("filter") or {}),
                "instance_id": self.source.instance_id,
            }
        for target in recipients:
            if target is not None:
                target.temp_combat_restrictions.append(dict(restriction))


class BecomeAuraEffect(GameEffect):
    """"…it becomes an Aura with '`<quoted enchant text>`.'" (RULE 305.1c/
    303.4f — Necromancy-shaped, MEC-44). Stamps `GameObject.
    parametric_keywords["enchant"]` directly onto this effect's own source
    at resolution. Every attachment-family reader (`RulesEngine.
    _attachment_kind`/`_attachment_legal`/`_detach_attachments_from`)
    already reads that dict fresh off the live object each call rather than
    a cached/load-time snapshot — the same dict `binding/core.py` writes
    exactly once, at bind time, for every ordinary Aura/Equipment/Fortify/
    Reconfigure card — so a plain runtime write here is picked up by every
    consumer for free; no threading needed, despite the field never having
    been *written* to mid-game by anything before this effect.

    ``quality`` is the enchant restriction's *type* word (``"creature"`` by
    default) — `_attachment_legal`'s own quality vocabulary (``"creature"``/
    ``"artifact"``/``"land"``/…) already falls through to permissive
    ``True`` for anything it doesn't recognize, the same simplification
    Animate Dead's own (already-an-Aura-from-load) quality string relies
    on: neither card's *exact* printed restriction ("creature card in a
    graveyard" / "creature put onto the battlefield with `<this>`") is a
    real characteristic this engine's simple word-match vocabulary can
    express, and no shipped card needs it enforced that precisely.

    Scoped to `parametric_keywords["enchant"]` specifically, not a general
    "becomes a `<type>` with `<quoted ability>`" primitive (RULE 305.1c,
    which could grant *any* ability, not just an attachment restriction) —
    that stays real, separate future work; see this card's own catalogue
    entry for why building the fully general version wasn't worth it for
    one card.
    """

    def __init__(self, quality: str = "creature", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.quality = quality

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        self.source.parametric_keywords = dict(self.source.parametric_keywords or {})
        self.source.parametric_keywords["enchant"] = {"quality": self.quality}


class LicidBecomeAuraEffect(GameEffect):
    """MEC-47 (Tempest Licid cycle): "{cost}, {T}: This creature loses this
    ability and becomes an Aura enchantment with enchant creature. Attach it
    to target creature. …"

    Attaches the Licid to the chosen creature (``attached_to``) and sets
    `GameObject.is_licid_aura`, which two things read: (1) a
    ``for_as_long_as`` floating `type_change` static parked here — strips
    the Creature type and adds Enchantment—Aura for as long as the flag
    holds (RULE 613 layer 4; `game/durations.py` sweeps it the instant
    `LicidRevertEffect` clears the flag, so nothing has to un-park it by
    hand); (2) the ``not_licid_aura`` / ``is_licid_aura`` `static_
    conditions` gating the Licid's own two activated abilities, so the
    transform is "lost" while attached and the "pay {cost} to end" only
    appears then.

    The "Enchanted creature has flying/haste/…" clause is an ordinary
    ``affects="attached_permanent"`` static bound off the card's own text —
    it does nothing while ``attached_to`` is ``None`` and starts applying
    the moment this sets it, no Aura-ness check of its own (see
    `continuous._selector_objects`'s ``attached_permanent`` branch).
    """

    def __init__(self, source: Optional["GameObject"] = None,
                 keep_creature: bool = False) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature")
        # Flanking Licid alone kept the pre-errata "becomes a creature
        # enchantment …" templating — it stays a creature and merely gains
        # the Enchantment—Aura type on top (Gatherer ruling 2004-10-04),
        # unlike every other Licid, which loses "creature".
        self._keep_creature = keep_creature

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        target = targets[0] if targets else None
        if src is None or target is None:
            return
        host_id = getattr(target, "instance_id", None)
        if host_id is None or src.zone != Zone.BATTLEFIELD:
            return
        src.attached_to = host_id
        src.is_licid_aura = True
        # "…an Aura enchantment with **enchant creature**" — the attachment
        # restriction every `_attachment_kind`/`_attachment_legal` reader
        # (and the RULE 704.5n SBA that would otherwise detach a
        # restriction-less "Aura") reads off `parametric_keywords["enchant"]`
        # live, the same field `BecomeAuraEffect` writes.
        src.parametric_keywords = dict(src.parametric_keywords or {})
        src.parametric_keywords["enchant"] = {"quality": "creature"}
        # Park the indefinite layer-4 type change (RULE 305.1c) — condition-
        # bounded so it self-ends with the flag (`GrantUntilEffect._park_
        # static`'s own idiom, inlined for the one payload).
        ability = EffectRegistry.create("type_change", {
            "add_types": ["enchantment"],
            "add_subtypes": ["aura"],
            "remove_types": [] if self._keep_creature else ["creature"],
        })
        if isinstance(ability, StaticAbility):
            ability.source = src
            ability.timestamp = context.state.next_timestamp()
            ability.duration = "for_as_long_as"
            ability.duration_data = {
                "player_id": src.controller_id,
                "condition": {"kind": "is_licid_aura"},
            }
            ability.affects = "objects"
            ability.object_ids = [src.instance_id]
            context.state.floating_statics.append(ability)
        context.recompute()


class LicidRevertEffect(GameEffect):
    """MEC-47: "You may pay {cost} to end this effect." — the Licid stops
    being an Aura and is a creature again. Clearing `is_licid_aura` is all
    that's needed: the ``for_as_long_as`` type-change static
    `LicidBecomeAuraEffect` parked expires on the next layer pass, and
    ``attached_to`` is cleared here so RULE 704.5n doesn't then bin it as an
    Aura attached to nothing."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None or not getattr(src, "is_licid_aura", False):
            return
        src.is_licid_aura = False
        src.attached_to = None
        if src.parametric_keywords:
            src.parametric_keywords = {
                k: v for k, v in src.parametric_keywords.items() if k != "enchant"
            }
        context.recompute()


class AttachEffect(GameEffect):
    """Attach a permanent to another permanent as an Aura/Equipment-style effect.

    ``target_kind="created"`` is a fourth, non-RULE-115 mode alongside the
    ordinary target/self ``TargetSpec`` shapes below — "create a 1/1 …
    creature token and attach ~ to it." (Auxiliary Boosters/Living Weapon-
    adjacent, Field-Tested Frying Pan): the host is whichever object an
    *earlier* effect in this same resolution just created
    (`GameContext.created_objects`, RULE 608.2's "the tokens/it" referent —
    see `RenownEffect`/goad's own use of the same list), not a chosen or
    printed-source permanent.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        creature_filter: Optional[dict[str, Any]] = None,
        mover: Optional[str] = None,
        mover_kind: Optional[str] = None,
        mover_optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: A following clause can attach the token it just made rather than
        #: this ability's source: "create an Aura token … attached to target
        #: creature" (Scriv, the Obligator).  This is deliberately a narrow
        #: RULE 608.2 pronoun, matching `target_kind="created"` above.
        self.mover = mover if mover in {"created", "created_after_first", "target"} else None
        self._created_mode = target_kind in {"created", "first_created"}
        self._first_created_mode = target_kind == "first_created"
        if self._created_mode and self.mover == "target" and mover_kind is not None:
            self.target_spec = TargetSpec(kind=mover_kind, optional=mover_optional)
        elif not self._created_mode:
            # "Equip commander {N}" (RULE 702.6e, Commander's Plate,
            # MEC-43) — a *second*, cheaper Equip ability restricted to
            # only ever attach to a commander (`creature_filter={
            # "is_commander": True}`), alongside the ordinary unrestricted
            # Equip cost every Equipment already gets from the keyword
            # catalogue. No prior card needed a *filtered* Equip target.
            self.target_spec = TargetSpec(kind=target_kind, creature_filter=creature_filter)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._created_mode:
            created = getattr(context, "created_objects", None)
            target = (created[0] if self._first_created_mode else created[-1]) if created else None
        else:
            target = (targets[0] if targets else None) or self.target
        mover = self.source
        if self.mover == "created":
            created = getattr(context, "created_objects", None)
            mover = created[-1] if created else None
        elif self.mover == "created_after_first":
            created = list(getattr(context, "created_objects", None) or [])
            mover = created[1:]
        elif self.mover == "target":
            mover = (targets[0] if targets else None) or self.target
        if target is None or mover is None:
            return
        if isinstance(mover, list):
            for obj in mover:
                context.engine.attach_to_target(obj, target)
        else:
            context.engine.attach_to_target(mover, target)


class AttachTriggeringPermanentEffect(GameEffect):
    """"Whenever a[n] <X> you control enters, you may attach it to target
    creature you control." (Sigarda's Aid-shaped) — RULE 603.3d's "it"
    pronoun for a **group**-subject trigger ("an Equipment you control
    enters", not "this permanent enters"), so unlike `AttachEffect` (always
    attaches the ability's own source) and `CreateTokenMayAttachEquipmentEffect`
    (a *chosen* Equipment onto a token this same resolution just created),
    the permanent being moved here is neither: it's whichever object
    actually fired the trigger this time, read off `GameContext.
    trigger_event`'s own ``instance_id`` (ENG-13's general per-firing
    dynamic reference — the same field `ReturnSharedTypePermanentEffect`
    reads for Cloudstone Curio's own "it").

    Only the destination is a real RULE 115 target (``target_kind``,
    "target creature you control" by default); the mover is never offered
    as one, so this can't be reused for a spell/ability that names the
    moving object as a *chosen* target instead of "it".
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature_you_control",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None:
            return
        mover = context.state.find_object(event.get("instance_id"))
        target = (targets[0] if targets else None) or self.target
        if mover is None or target is None:
            return
        context.engine.attach_to_target(mover, target)


class UnattachEffect(GameEffect):
    """Unattach a target Aura, Equipment, or Fortification from its host."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "attached_equipment_you_control",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        equipment = (targets[0] if targets else None) or self.target
        if equipment is None or getattr(equipment, "attached_to", None) is None:
            return
        # A following composed rider can derive the *former* host from the
        # selected attachment. The map is scoped to this resolution by
        # `_apply_effects_partitioned` just like previous_targets.
        context.attachment_hosts[equipment.instance_id] = equipment.attached_to
        equipment.attached_to = None


class TransformEffect(GameEffect):
    """Flip a double-faced permanent to its other face (RULE 712.8/712.9).

    Untargeted, it transforms its own source ("Transform ~." / "transform
    it" on a triggered/activated/loyalty ability); with a ``target_kind`` it
    targets another permanent (rare, but the same shape as `AttachEffect`).
    Delegates to `RulesEngine.transform_permanent`, which also rebinds the
    new face's catalogue-derived abilities/keywords — a bare
    `GameObject.transform()` would leave those pointing at the old face.
    """

    def __init__(
        self,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        if target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            target = targets[0] if targets else None
        else:
            target = self.source
        if target is not None:
            context.engine.transform_permanent(target)


class RevealTopThenTransformEffect(GameEffect):
    """"Look at the top card of your library. If it's a[n] <criteria> card,
    transform ~." (RULE 712.8 conditional flip — Delver of Secrets-shaped).

    Unlike the RULE 731 day/night flip (`RulesEngine.
    apply_day_night_turn_check`, spells-cast-last-turn-driven), this checks
    the top card of the *controller's* library, so it's its own one-shot
    effect rather than routed through the day/night machinery. ``criteria``
    is a `models.cards.card_query` predicate (``{"type": ["instant", "sorcery"]}``
    for Delver; a plain string/dict works the same as `SearchLibraryEffect`)
    so the same effect covers any future card sharing this template, not
    just an instant/sorcery check. The card is only looked at, never moved.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        criteria: Any = "",
    ) -> None:
        super().__init__(source)
        self.criteria = criteria

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        if card_query.matches(top.card, self.criteria):
            context.engine.transform_permanent(self.source)


class ExileReturnTransformedEffect(GameEffect):
    """"Exile ~, then return it to the battlefield transformed under its
    owner's control" (RULE 400.7 + RULE 712.8 combined). Untargeted and
    always self — a transforming Saga's own final chapter (Fable of the
    Mirror-Breaker-shaped) or a transform-flip permanent's activated
    ability phrased this way instead of a plain `TransformEffect`
    (Ayara/Clive/Jin-Gitaxias-shaped). See `RulesEngine.
    exile_return_transformed`'s docstring for why this is a genuine
    RULE 400.7 zone change rather than an in-place flip.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.exile_return_transformed(self.source)


class MeldEffect(GameEffect):
    """RULE 701.42a: "exile them, then meld them into `<result>`." — the
    body of a meld card's own trigger (Gisela, the Broken Blade / Graf Rats
    / Midnight Scavengers). Untargeted: ``self.source`` is one half of the
    pair, ``partner_name`` names the other. Resolves the partner as a
    non-token permanent the source's controller **both owns and controls**
    (RULE 701.42b) and hands both to `RulesEngine.meld`; a no-op (the
    RULE 603.4 intervening-if failed by resolution) if the partner isn't
    there — the engine also fails closed, so nothing is exiled.
    """

    def __init__(
        self, partner_name: str = "", result_name: str = "",
        source: Optional["GameObject"] = None, tapped_attacking: bool = False,
    ) -> None:
        super().__init__(source)
        self.partner_name = partner_name
        self.result_name = result_name
        self.tapped_attacking = bool(tapped_attacking)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        src = self.source
        if src is None or src.zone != Zone.BATTLEFIELD:
            return
        controller_id = src.controller_id
        # `partner_name` comes from `normalize`d oracle text (lower-cased),
        # while `GameObject.name` keeps its printed casing — compare folded.
        want = self.partner_name.strip().lower()
        partner = next(
            (
                o for o in context.state.permanents_controlled_by(controller_id)
                if o is not src
                and o.name.lower() == want
                and o.owner_id == controller_id
                and not getattr(o, "is_token", False)
            ),
            None,
        )
        if partner is None:
            return  # RULE 701.42c / 603.4 — the pair isn't both here
        result_name = self.result_name
        if result_name.startswith("~,"):
            result_name = src.name.partition(",")[0] + result_name[1:]
        else:
            result_name = result_name.replace("~", src.name)
        melded = context.engine.meld(src, partner, result_name)
        if melded is not None and self.tapped_attacking:
            melded.tapped = True
            melded.attacking = True


class SiegeDefeatedEffect(GameEffect):
    """A Siege's intrinsic defeat ability (RULE 310.11b): "exile it, then you
    may cast it transformed without paying its mana cost."

    Untargeted and always self, like `ExileReturnTransformedEffect` above —
    but the destination differs in the way that matters: the Siege goes to
    **exile and stays there**, and its back face becomes castable from
    exile for free. It does *not* come back to the battlefield on its own.

    Never bound from oracle text or the catalogue: RULE 310.11b is
    intrinsic to the Siege subtype, so `RulesEngine.check_state_based_
    actions` builds this per firing when a Siege's defense hits 0. That's
    also why it takes its source at construction rather than relying on a
    bind-time one.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.engine.exile_siege_for_transformed_cast(self.source)


class ReturnFromGraveyardTransformedEffect(GameEffect):
    """"Return this card from your graveyard to the battlefield transformed
    under its owner's control." (Bruce Banner-shaped) — the graveyard-
    sourced sibling of `ExileReturnTransformedEffect` above: a dies
    trigger's own subject is always the card that just died, so this is
    untargeted and always acts on ``self.source``, exactly like that
    sibling — never a chosen target. See `RulesEngine.return_from_graveyard`'s
    ``transformed`` param for the RULE 400.7 + RULE 712.8 mechanics (a
    genuine new-object zone change, then a forced flip onto the back face —
    not an in-place face swap). A no-op if ``self.source`` isn't actually
    sitting in a graveyard when this resolves (e.g. something else already
    moved it) or has no back face at all.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(self.source, "battlefield", transformed=True)


class ReturnSelfFromGraveyardToBattlefieldEffect(GameEffect):
    """"Return this card from your graveyard to the battlefield[, tapped]."
    (Dread Wanderer/Bloodsoaked Champion/Drownyard Temple &c) — the plain
    (non-transforming) sibling of `ReturnFromGraveyardTransformedEffect`:
    untargeted, always ``self.source``, since an activated ability's/
    triggered ability's "this card" can only ever mean the permanent whose
    text prints it. A no-op if ``self.source`` isn't actually in a
    graveyard when this resolves.

    Named distinctly from `ReturnSelfFromGraveyardEffect` above (mill's
    RULE 112.6a "return it to your hand", a *different* shape — a per-
    firing ``obj``, not always ``self.source``, and to hand rather than the
    battlefield) rather than reusing that name for an unrelated effect.
    """

    def __init__(
        self, tapped: bool = False, source: Optional["GameObject"] = None, attacking: bool = False,
        extra_counters: Optional[dict[str, Any]] = None,
        attach_to_previous: bool = False,
        face_choice: bool = False,
    ):
        super().__init__(source)
        #: "…return this card from your graveyard to the battlefield **face up or face down**." (Deathmist Raptor) —
        #: the controller picks (`RulesEngine._request_return_face_choice`); a card with no morph can only return
        #: face up, so no question is asked for it.
        self.face_choice = bool(face_choice)
        self.tapped = tapped
        self.attach_to_previous = bool(attach_to_previous)
        self.target = None
        self.attachment_incarnation = None
        self.source_incarnation = None
        #: "…with 2 +1/+1 counters on it" — ``{"kind", "count"}``, placed right after it lands
        #: (`ReturnFromGraveyardEffect.extra_counters`' own shape).
        self.extra_counters = dict(extra_counters) if extra_counters else None
        #: "…to the battlefield tapped and attacking" (Interceptor, Shadow's Hound) — RULE 508.4.
        self.attacking = attacking

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        host = None
        if self.attach_to_previous:
            host = self.target
            if (host is None or host.zone != Zone.BATTLEFIELD
                    or host.hideaway_incarnation != self.attachment_incarnation
                    or self.source.hideaway_incarnation != self.source_incarnation
                    or not context.engine._attachment_legal(self.source, host, False)):
                return  # RULE 303.4i / 603.7c: an invalid or new host prevents entry.
        destination = "battlefield_tapped" if self.tapped else "battlefield"
        controller_id = (context.resolving_controller_id or self.source.controller_id) if host is not None else None
        from .. import face_down  # function-scoped: face_down is imported by the rules mixins above this package

        if self.face_choice and face_down.cast_face_down_kind(self.source):
            context.engine._request_return_face_choice(self.source, destination)
            return
        context.return_from_graveyard(self.source, destination, attach_to=host, controller_id=controller_id)
        if self.extra_counters:
            context.add_counters(
                self.source, int(self.extra_counters.get("count", 1) or 1),
                str(self.extra_counters.get("kind", "+1/+1")), source=self.source,
            )
        if self.attacking:
            context.engine.put_onto_battlefield_attacking(self.source)


class UndyingPersistReturnEffect(GameEffect):
    """RULE 702.79b / 702.93b — the body of Persist's / Undying's own
    triggered ability: "return this card from its owner's graveyard to the
    battlefield under its owner's control with a ``counter_kind`` counter on
    it." Untargeted, always ``self.source``; a no-op unless it is actually
    in a graveyard when this resolves (it could have been exiled or
    otherwise moved in response). The RULE 702.79a/702.93a "if it had no
    such counter on it" guard lives on the trigger, not here — see
    `RulesEngine._collect_undying_persist_triggers` (PAR-25).

    `return_from_graveyard`'s own `reset_as_new_object` (RULE 400.7) drops
    whatever the creature died with *before* it lands, so placing the fresh
    counter afterwards is a clean single counter, not stacked on a stale
    one.
    """

    def __init__(self, counter_kind: str = "+1/+1", source: Optional["GameObject"] = None):
        super().__init__(source)
        self.counter_kind = counter_kind

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(self.source, "battlefield")
        context.add_counters(self.source, 1, self.counter_kind, source=self.source)


def _exile_instead_of_dying(context: GameContext, creature: "GameObject", description: str) -> None:
    """Arm ``creature`` with a RULE 614.1 "if it would leave the battlefield, exile it instead" — modeled
    as a `WOULD_DIE` replacement (the one leave-the-battlefield event this engine fires pre-emptively), so
    a bounce/blink that keeps the card is a known simplification (no general "would leave the battlefield"
    event yet). Shared by Unearth and the corpse-counter reanimation family (PAR-139)."""
    tid = creature.instance_id

    def _cond(e: GameEvent, c: GameContext, tid=tid) -> bool:
        return e.get("target_id") == tid

    def _replace(e: GameEvent, c: GameContext) -> Optional[GameEvent]:
        obj = c.state.find_object(e.get("target_id"))
        if obj is not None:
            c.engine.exile(obj)
        return None

    creature.replacement_effects.append(
        ReplacementEffect(
            event_type=EventType.WOULD_DIE, replacement_fn=_replace, condition=_cond, description=description,
        )
    )


class ExileInsteadOfLeavingEffect(GameEffect):
    """"Put target creature card from a graveyard onto the battlefield under your control with a corpse
    counter on it. … If that creature would leave the battlefield, exile it instead of putting it anywhere
    else." (From the Catacombs, Isareth the Awakener; PAR-139) — the tail sentence: arms every creature the
    earlier clause returned (`GameContext.previous_targets`, the RULE 608.2 referent) that is on the
    battlefield now. Does nothing for a card that never made it (nothing was chosen/legal)."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for creature in list(context.previous_targets or []):
            if creature.zone == Zone.BATTLEFIELD:
                _exile_instead_of_dying(context, creature, "Exilieren statt zu verlassen")


class UnearthEffect(GameEffect):
    """RULE 702.84a Unearth's own activated-ability body: "Return this card
    from your graveyard to the battlefield. It gains haste. Exile it at the
    beginning of the next end step or if it would leave the battlefield.
    Activate this ability only as a sorcery." (PAR-25 — bound via
    `effect_binder._keyword_activated_ability` with `ActivationCost.
    graveyard_zone`/`sorcery_speed_only`, so it is offered while the source
    sits in a graveyard.)

    Untargeted, always ``self.source``. The end-step exile is a
    `DelayedTrigger` (``scope="any"`` — the *next* end step whoever's turn
    it is, exactly like Corpse Dance's own trailing clause, now a
    `create_delayed_trigger` with ``capture="previous_or_self"`` in a `seq`
    after `return_from_graveyard{positional_top_creature}`). The "if it
    would leave the
    battlefield" half is modeled as a `WOULD_DIE` → exile replacement (the
    one leave-the-battlefield event this engine fires pre-emptively), so an
    unearthed creature that dies is exiled rather than left re-unearthable;
    a bounce/blink that keeps it is a known simplification (no general
    "would leave the battlefield" event yet).
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_state import DelayedTrigger

        creature = self.source
        if creature is None or creature.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(creature, "battlefield")
        creature.temp_keywords.add("haste")
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=creature.controller_id,
                step="end",
                scope="any",
                effects=[ExileEffect(target_kind=None, target=creature, source=self.source)],
                targets=[creature],
                description=f"{creature.name}: Unearth — im nächsten Endsegment exilieren",
            )
        )
        _exile_instead_of_dying(context, creature, "Unearth: exilieren statt sterben")
        context.recompute()


class MadnessToGraveyardEffect(GameEffect):
    """RULE 702.35b's "If you don't [cast it], put it into your graveyard."
    — armed as a `DelayedTrigger` for the next end step when a Madness card
    is exiled on discard (`draw_discard_mixin._maybe_madness`). A no-op
    unless ``self.source`` is still sitting in an exile zone (it was cast,
    or already moved) when this fires (PAR-26)."""

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        if obj is None or obj.zone != Zone.EXILE:
            return
        owner = context.state.player_by_id(obj.owner_id)
        if owner is None or obj not in owner.exile:
            return
        owner.exile.remove(obj)
        obj.zone = Zone.GRAVEYARD
        owner.graveyard.append(obj)
        context.state.temp_play_permissions.pop(obj.instance_id, None)


class EmbalmEternalizeEffect(GameEffect):
    """RULE 702.128a Embalm / 702.129a Eternalize's own activated-ability
    body: "Exile this card from your graveyard: Create a token that's a
    copy of it, except it's a white Zombie [Embalm] / a 4/4 black Zombie
    [Eternalize] with no mana cost." (PAR-25 — bound via `effect_binder.
    _keyword_activated_ability` with `ActivationCost.graveyard_zone`/
    `sorcery_speed_only`.)

    Reuses `RulesEngine.copy_permanent`'s ``add_subtypes``/``set_power``/
    ``set_toughness`` copy-modifier vocabulary exactly as
    `CreateTokenCopyOfLinkedExileEffect` (Lazotep Quarry) does. The colour
    override (white/black) is dropped — `Card.as_copy` has no colour
    mechanism (CLAUDE.md's documented gotcha), the same simplification that
    effect and The Jolly Balloon Man's catalogue entry accept. "With no
    mana cost" is likewise not modeled (only matters to an {X} in the
    copied card's cost).
    """

    def __init__(
        self,
        set_power: Optional[int] = None,
        set_toughness: Optional[int] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.set_power = set_power
        self.set_toughness = set_toughness

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        card_obj = self.source
        if card_obj is None or card_obj.zone != Zone.GRAVEYARD:
            return
        controller_id = card_obj.controller_id or card_obj.owner_id
        context.engine.exile(card_obj)  # RULE 702.128a/702.129a: "Exile this card…"
        made = context.engine.copy_permanent(
            controller_id, card_obj,
            add_subtypes=["Zombie"],
            set_power=self.set_power, set_toughness=self.set_toughness,
        )
        context.created_objects.extend(made or [])


class ReturnSelfFromGraveyardToHandEffect(GameEffect):
    """"Return this card from your graveyard to your hand." (PAR-16 —
    Abzan Devotee/Clay Revenant/Chandra's Phoenix/Aurora Eidolon &c) — the
    hand-destination sibling of `ReturnSelfFromGraveyardToBattlefieldEffect`
    right above: same untargeted, always-``self.source``, no-op-unless-
    still-in-the-graveyard shape, just a different destination (so no
    ``tapped`` param applies here). Two real printed shapes reach it: an
    activated ability living in the graveyard (`ActivationCost.
    graveyard_zone`, the same inference `effect_binder.bind_ability` already
    does for the battlefield sibling) and a *triggered* ability whose
    source likewise sits in the graveyard when it fires (RULE 113.6a — the
    Eidolon/Phoenix family, "Whenever `<event>`, [you may] return this card
    from your graveyard to your hand": `TriggeredAbility.
    functions_from_graveyard`, inferred the same way, and consulted by
    `RulesEngine._collect_triggers`'s graveyard scan since real printings
    carry no explicit "(this ability functions from your graveyard.)"
    reminder to key off instead).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(self.source, "hand")


class PutSelfOntoBattlefieldFromHandEffect(GameEffect):
    """"{N}: Put this card from your hand onto the battlefield." (Talon
    Gates of Madara-shaped — a land's own paid alternative to a land drop,
    RULE 305's special-action family) — untargeted, always ``self.source``;
    a no-op if it isn't actually in hand when this resolves. Doesn't count
    against the controller's land-per-turn allowance (it's an activated
    ability, not RULE 305.1's "play a land" action at all).
    `effect_binder.bind_ability` infers ``ActivationCost.hand_zone``
    whenever an ability's effects include this one, the same way
    ``graveyard_zone`` is inferred for
    `ReturnSelfFromGraveyardToBattlefieldEffect`.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.HAND:
            return
        player = context.state.player_by_id(self.source.owner_id)
        player.remove_from_zone(self.source, Zone.HAND)
        context.state.add_to_battlefield(self.source)
        context.state.fire_event(
            GameEvent(
                EventType.ENTERS_BATTLEFIELD,
                from_zone=Zone.HAND.value,
                controller_id=self.source.controller_id,
                object=self.source.name,
                instance_id=self.source.instance_id,
                object_types=sorted(self.source.type_words),
            )
        )


class ReturnDiesAsNewPermanentEffect(GameEffect):
    """"When ~ dies, return it to the battlefield. It's a[n] <type> with
    '<ability>'. ~ loses all other abilities." (Harold and Bob, First
    Numens) — a genuinely *different* card, not RULE 712.8's ordinary
    "return transformed" (`ReturnFromGraveyardTransformedEffect`, which
    needs a real printed back face): see `RulesEngine.return_dies_as_new_
    permanent`'s docstring for the mechanics (a synthetic `Card` built from
    ``new_type_line``/``new_oracle_text``, same name/owner/set).

    ``target_kind``, when given, is a real RULE 115 target this dies
    trigger resolves before returning (RULE 303.4a's "enchant Forest you
    control" — the specific permanent the new Aura form attaches to);
    mandatory (no ``target_spec.optional``), so a dying object with no
    legal target at all simply fizzles like any other single-target
    triggered ability, rather than returning unattached.
    """

    def __init__(
        self,
        new_type_line: str,
        new_oracle_text: str,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.new_type_line = new_type_line
        self.new_oracle_text = new_oracle_text
        self.target_spec = TargetSpec(kind=target_kind) if target_kind else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        attach_to = None
        if self.target_spec is not None:
            attach_to = targets[0] if targets else None
            if attach_to is None:
                return  # no legal target — the ability fizzles (RULE 608.2b)
        context.return_dies_as_new_permanent(
            self.source, self.new_type_line, self.new_oracle_text, attach_to=attach_to
        )


class PhaseOutEffect(GameEffect):
    """Phase a permanent out (RULE 702.26) — treated as though it doesn't
    exist until it phases back in at its controller's next untap step
    (`GameEngine._step_untap`'s RULE 702.26a sweep).

    Untargeted with ``target_kind=None`` (the default): phases out whatever
    is currently attached to this effect's own source ("Equipped creature
    phases out" — Robe of Stars' Astral Projection — no RULE 115 target,
    the same "defaults to its own source/host, no targeting" shape
    `TransformEffect`'s "transform ~" uses). ``target_kind="creature"``
    (etc.) targets some other permanent instead, same alternative
    `TransformEffect` offers.

    Any Aura/Equipment attached to the phasing-out permanent becomes
    unattached rather than phasing out together with it (RULE 702.26e-
    family simplification — no card needing a multi-permanent phase chain
    yet, see docs/implementation-state/BACKLOG.md).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        optional: bool = False,
        previous_subject: bool = False,
        self_target: bool = False,
        count: int = 1,
        count_selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "Put a +1/+1 counter on target creature. **It** phases out."
        #: (Slip Out the Back) — the same `GameContext.previous_targets`
        #: pronoun `FightEffect`/`GrantUntilEffect.previous_subject` already
        #: use, rather than a second independent RULE 115 target.
        self.previous_subject = previous_subject
        #: "~ phases out." (Blink Dog/Vaporous Djinn/Crystal Golem-shaped —
        #: the source phasing out *itself*, no attachment involved) —
        #: distinct from the plain untargeted default below, which is
        #: Robe of Stars' Equipment-hosted "**equipped creature** phases
        #: out" instead (`TransformEffect`'s own "self vs. attached host"
        #: split has the identical shape).
        self.self_target = self_target
        if target_kind is not None and not previous_subject:
            #: "Up to X target creatures phase out." (March of Swirling
            #: Mist, MEC-42) — ``count_selector="source_x_paid"`` reads the
            #: spell's own announced {X} fresh at target-gathering time
            #: (`targeting.resolved_count`), the same shape Goad's own
            #: "up to X target creatures" already established (ENG-30-
            #: adjacent, just a different count source).
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_selector=count_selector,
            )

    def _phase_out_one(self, context: GameContext, target: Any) -> None:
        target.phased_out = True
        for obj in context.state.battlefield:
            if obj.attached_to == target.instance_id:
                obj.attached_to = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.previous_subject:
            prev = list(context.previous_targets)
            target = prev[0] if prev else None
            if target is not None:
                self._phase_out_one(context, target)
            return
        if self.target_spec is not None and self.target_spec.count_selector:
            # A dynamic (e.g. X-sized) multi-target count, resolved once at
            # target-gathering time (`targeting.resolved_count`) — every
            # target actually gathered phases out, not just the first.
            # ``effective_count`` can't be used to slice here (it reads
            # only ``count``/``count_max``, not a live ``count_selector``),
            # so every entry the caller already gathered for this one
            # targeting effect is used as-is.
            for one in (targets or []):
                self._phase_out_one(context, one)
            return
        if self.target_spec is not None:
            target = (targets[0] if targets else None) or self.target
        elif self.self_target:
            target = self.source
        elif self.target is not None:
            # A delayed trigger's captured object ("it phases out at end of combat", Teferi's Veil).
            target = self.target
        elif self.source is not None:
            host_id = getattr(self.source, "attached_to", None)
            target = context.state.find_object(host_id) if host_id is not None else None
        else:
            target = None
        if target is None:
            return
        self._phase_out_one(context, target)



register(globals())
