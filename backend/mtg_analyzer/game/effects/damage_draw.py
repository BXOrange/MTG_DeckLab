"""Damage, card draw, reveal, discard, and shared target helpers."""
from __future__ import annotations

import random

from .core import GameEffect
from ._runtime import install, register

install(globals())


class PreventCombatDamageDealtEffect(GameEffect):
    """Prevent all combat damage the named creature would deal this turn
    (RULE 615) — Loafing Giant's own "prevent all combat damage ~ would
    deal this turn", and RULE 510.1e's "assigns no combat damage this turn"
    is a rules-distinct but observably identical shape (Gaze of Pain,
    MEC-99), since `deal_damage`'s own check for this flag returns before
    any `DAMAGE` event fires either way.

    ``subject`` is `effect_conditions`'s referent vocabulary, defaulting to
    ``None`` (the effect's own source, Loafing Giant's printed "~"); MEC-99
    adds the group-subject reading — "**it** assigns no combat damage this
    turn." where "it" is whichever creature matched this ability's own
    RULE 603.1 group trigger, not the ability's source (a temporary
    triggered ability granted by a sorcery has no combat-relevant source of
    its own to flag).
    """

    def __init__(
        self, subject: Optional[str] = None, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.subject = subject

    def apply(self, context, targets=None) -> None:
        obj = self.source
        if self.subject:
            from .. import effect_conditions  # avoid the effect_conditions↔effects import cycle

            obj = effect_conditions.subject_of(self.subject, context, self.source, targets)
        if obj is not None:
            obj.temp_prevent_combat_damage_dealt = True

#: PAR-128: RULE 109.5's "each other creature" — every creature but this
#: effect's own source. Kept off `_DAMAGE_SELECTORS`, which `library.py`'s
#: power-damage effect shares and does not iterate.
_DAMAGE_OTHER_SELECTORS: frozenset[str] = frozenset({"each_other_creature", "attacked_object"})


class DealDamageEffect(GameEffect):
    """Deal ``amount`` damage to a target player or creature — or, with
    ``selector`` set, to *every* object/player a closed vocabulary names
    (RULE 601.2c "each creature"/"each player"/"each opponent" — a mass
    effect, not a RULE 115 target, so it carries no ``target_spec`` at all,
    the same untargeted-group shape `PumpEffect.selector` uses).
    """

    def __init__(
        self,
        amount: int,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "any",
        selector: Optional[str] = None,
        optional: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
        colors: Optional[list[str]] = None,
        creature_filter: Optional[dict[str, Any]] = None,
        selector_filter: Optional[dict[str, Any]] = None,
        group: Optional[dict[str, Any]] = None,
        group_player: Optional[str] = None,
        group_and_players: Optional[str] = None,
        divided: bool = False,
        distinct_from_others: bool = False,
        double_at: Optional[int] = None,
        amount_if_kicked: Optional[int] = None,
        amount_if_teamwork: Optional[int] = None,
        amount_if_raid: Optional[int] = None,
        amount_if_mana_color_spent: Optional[dict[str, Any]] = None,
        each_target_if_mana_color_spent: Optional[dict[str, Any]] = None,
        amount_if_full_party: Optional[int] = None,
        amount_if_bargained: Optional[Union[int, str]] = None,
        double_if_bargained: bool = False,
        amount_if_target_color: Optional[tuple[Union[int, str], list[str]]] = None,
        amount_if_cast_from_exile: Optional[int] = None,
        amount_if_source_subtype: Optional[tuple[str, int]] = None,
        tap_target_if_colorless: bool = False,
        x_multiplier: Optional[int] = None,
        amount_from_noncreature_spells_cast_this_turn: bool = False,
        amount_from_count_selector: Optional[str] = None,
        amount_plus_count_selector: int = 0,
        amount_multiplier: int = 1,
        amount_from_trigger_event: Optional[str] = None,
        amount_from_defending_player_hand_size: bool = False,
        recipient_subject: Optional[str] = None,
        unpreventable: bool = False,
        dealer_event_key: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self._base_amount = amount
        #: "The damage can't be prevented." (Combust, RULE 615.6) — this one
        #: instance ignores prevention shields. Implemented by flipping the
        #: same turn-scoped `GameState.damage_prevention_disabled` flag
        #: `disable_damage_prevention_this_turn` sets (`_run_replacement_
        #: loop` reads it to drop every ``prevents_damage`` effect), but only
        #: for the span of this `apply()` so it doesn't leak to unrelated
        #: later damage.
        self.unpreventable = unpreventable
        #: The event field naming the damage's dealer when it is the group trigger's firing
        #: object rather than the source (resolved from the parser's sentinel by the binder).
        self.dealer_event_key = dealer_event_key
        #: "~ deals N damage to **that creature's controller**" where "that
        #: creature" is a creature an *earlier clause* targeted (PAR-30 —
        #: "Destroy target creature. ~ deals 2 damage to that creature's
        #: controller." — Consign to the Pit / Blur of Blades) or the one a
        #: *group/trigger* subject names ("Whenever a creature blocks/dies,
        #: ~ deals N damage to that creature's controller." — Battle Strain /
        #: Dingus Staff). A ``"<who>_controller"`` string: ``previous_
        #: subject_controller`` (`GameContext.previous_targets` — RULE
        #: 608.2h last-known controller, since the creature is usually gone)
        #: or ``trigger_subject_controller`` (the firing event's own
        #: ``instance_id`` / ``controller_id`` payload). No RULE 115 target
        #: of this effect's own.
        self.recipient_subject = recipient_subject
        #: "Imodane deals that much damage to each opponent." — the event
        #: field name to read off `GameContext.trigger_event` at
        #: resolution, the same idiom `LoseLifeEffect.amount_from_trigger_
        #: event` already uses. Overrides everything else when set.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "…deals X damage to defending player, where X is the number of
        #: cards in their hand." (Unquenchable Fury) — read the combat
        #: defender's live hand at resolution.
        self.amount_from_defending_player_hand_size = bool(amount_from_defending_player_hand_size)
        #: "X is 2 plus the number of cards in your graveyard that are
        #: instant cards, sorcery cards, and/or have an Adventure."
        #: (Frantic Firebolt) — a live `continuous.count_selector` read,
        #: scoped to this effect's own controller, resolved once at
        #: `apply()` time (there's no announced ``{X}`` to substitute —
        #: this card's mana cost carries no X at all, so the value is
        #: purely a resolve-time computation, not RULE 107.3c's X).
        #: ``amount_plus_count_selector`` is the flat addend ("2 plus …").
        self.amount_from_count_selector = amount_from_count_selector
        self.amount_plus_count_selector = amount_plus_count_selector
        #: "~ deals 2 damage to you for each Treasure you control."
        #: (Black Market Tycoon) — unlike the existing ``plus`` form, the
        #: printed numeral multiplies the live count.
        self.amount_multiplier = max(0, int(amount_multiplier))
        #: "If this spell was bargained, it deals twice X damage to that
        #: permanent instead." (Stonesplitter Bolt) / "…instead it deals 3
        #: damage…" (Torch the Tower) — RULE 702.157's own `GameObject.
        #: bargained` flag (already stamped at cast time for any spell
        #: printing the Bargain keyword), the same *override*-not-additive
        #: shape `amount_if_kicked` uses. ``double_if_bargained`` is the
        #: "twice X" phrasing specifically (X isn't known until resolution,
        #: so a fixed override number can't express it); a plain
        #: ``amount_if_bargained`` int/``"x"`` covers every other phrasing.
        self.amount_if_bargained = amount_if_bargained
        self.double_if_bargained = double_if_bargained
        #: "It deals 5 damage instead if that target is white and/or
        #: blue." (Lithomantic Barrage) — ``(override_amount, [colors])``;
        #: checked per resolved target against `GameObject.colors`, since
        #: (unlike every other conditional here) this one can vary target
        #: to target rather than being a single flat override.
        self.amount_if_target_color = amount_if_target_color
        # RULE 702.33b's *override* kicked-conditional ("~ deals 2 damage to
        # any target. If this spell was kicked, it deals 4 damage instead." —
        # Burst Lightning-shaped), distinct from the *additive* "if kicked,
        # <effect>" shape `ConditionalEffect`/`EffectSpec.condition` already
        # cover — mirrors `PreventDamageEffect.amount_if_kicked` exactly, a
        # param on the effect rather than a generic wrapper since it's the
        # specific numeric param being overridden that differs per effect
        # type (amount here, a token count for `CreateTokenCopyEffect`, …).
        # A property (below) rather than resolving once in `__init__` since
        # `kicker_count` is only known once ``source`` is fully bound onto
        # the battlefield object, not necessarily yet at construction time.
        self.amount_if_kicked = amount_if_kicked
        #: RULE 702.194b (PAR-68): "~ deals 2 damage to target attacking or
        #: blocking creature. If this spell was cast using teamwork, it
        #: deals 4 damage to that creature instead." (Helicarrier Strike) —
        #: `GameObject.teamwork_paid`, the same override-not-additive shape
        #: `amount_if_kicked`/`amount_if_bargained` use; same "recipient
        #: unchanged, only the magnitude does" scope (unlike Cruel Alliance/
        #: Too Evil to Stay Dead/Earth's Mightiest Heroes' own teamwork
        #: "instead" clauses, which change *target legality* or *selection
        #: count* rather than a flat magnitude — a still-open engine gap,
        #: `MEC-85`).
        self.amount_if_teamwork = amount_if_teamwork
        #: PAR-64: Raid's two-line "deals N damage instead if you attacked
        #: this turn" replacement. Like Kicker, this replaces this damage
        #: event's magnitude rather than adding a second damage effect.
        self.amount_if_raid = amount_if_raid
        #: PAR-95 / Adamant's amount-replacement form (Slaying Fire): unlike
        #: an additive rider, this replaces the preceding damage amount.
        self.amount_if_mana_color_spent = amount_if_mana_color_spent
        self.each_target_if_mana_color_spent = each_target_if_mana_color_spent
        #: "…it deals 3 damage to each opponent instead." (PAR-76, The
        #: Destined Black Mage) — RULE 700.8's already-shipped
        #: `"creatures_in_your_party"` count selector read as a live
        #: threshold (>= 4, the cap that count can ever reach), the same
        #: override shape Kicker/Raid establish above.
        self.amount_if_full_party = amount_if_full_party
        #: "If this spell was cast from exile, it deals 5 damage … instead."
        #: (Delayed Blast Fireball) — `GameObject.cast_from_exile`, the
        #: same override-not-additive shape `amount_if_kicked`/
        #: `amount_if_bargained` use.
        self.amount_if_cast_from_exile = amount_if_cast_from_exile
        #: "If this creature is a Wizard, it deals 2 damage instead."
        #: (Sorcerer's Wand) — an activated ability's source can change type
        #: between activation and resolution, so inspect its live type line
        #: when resolving the override.
        self.amount_if_source_subtype = amount_if_source_subtype
        #: "If a colorless creature is dealt damage this way, tap it."
        #: (Pathway Arrows) — a rider on this damage event's chosen target.
        self.tap_target_if_colorless = bool(tap_target_if_colorless)
        #: "When ~ enters, it deals X damage to each creature." (Spiteful
        #: Banditry-shaped ETB) — `AddCountersEffect.x_multiplier`'s own
        #: sibling: a self-only ETB trigger reading the source's own
        #: announced {X} (`GameObject.x_paid`), unlike `_substitute_x`'s
        #: ``"x"`` sentinel (spell-resolution-only, no `StackItem.x` exists
        #: for a separately-fired triggered ability to read).
        self.x_multiplier = x_multiplier
        #: "~ deals damage to that player equal to the number of
        #: noncreature spells they've cast this turn." (Magebane Lizard) —
        #: `LoseLifeEffect.amount_from_spells_cast_this_turn`'s own
        #: sibling, reading `GameState.noncreature_spells_cast_this_turn`
        #: for the event's own caster instead of a flat multiplier.
        self.amount_from_noncreature_spells_cast_this_turn = amount_from_noncreature_spells_cast_this_turn
        self.target = target
        self.selector = selector if selector in _DAMAGE_SELECTORS | _DAMAGE_OTHER_SELECTORS else None
        #: PAR-128: "~ deals N damage to each creature you don't control" / "…to each other
        #: creature without flying" — a structured battlefield selector (`{"zone","of",
        #: "filter"}`) for the mass groups the closed `_DAMAGE_SELECTORS` vocabulary has no
        #: name for, resolved through `continuous.group_selector_objects`.
        self.group = dict(group) if isinstance(group, dict) and group.get("zone", "battlefield") == "battlefield" else None
        if self.group is not None:
            self.selector = "group"
        #: "…to each other creature without flying **and each player**" (Themberchaud, Conductor
        #: of Cacophony) — the group's damage also goes to every player (``"each_player"``) or
        #: every opponent (``"each_opponent"``); players are never filtered by ``group``.
        self.group_and_players = group_and_players if group_and_players in ("each_player", "each_opponent") else None
        #: "…to each creature **defending player controls**" / "…**that player** controls" /
        #: "…**target opponent** controls" (PAR-128) — whose creatures ``group`` (written
        #: ``of: "you"``) names: ``"defending"`` (RULE 506.4), ``"event_player"`` (the trigger's
        #: damaged player), ``"previous_controller"`` (the controller of the preceding clause's
        #: target), or ``"player"``/``"opponent"`` (a RULE 115 player target).
        self.group_player = (
            group_player if group_player in ("defending", "event_player", "previous_controller", "player", "opponent")
            else None
        )
        #: "~ deals N damage to each creature **without flying**." (RULE
        #: 601.2c — Earthquake / Fault Line / Pyroclasm-with-a-filter) — a
        #: `combat.matches_object_filter`-shaped narrowing applied to the
        #: `each_creature`/`each_creature_and_player` iteration only (players
        #: in a union selector are never filtered).
        self.selector_filter = selector_filter
        # RULE 601.2d: a *divided* damage spell splits its total ``amount``
        # (typically {X}) among the chosen targets — "N damage divided as you
        # choose among …" (Fire Covenant, Shatterskull Smashing) — rather than
        # dealing the full amount to each (``count`` > 1's default). The "as
        # you choose" split is UI-less here: the total is distributed as
        # evenly as possible across whatever targets were chosen (an explicit
        # ``division`` list, if a caller sets one, wins) — a documented
        # simplification (the total dealt, and which permanents take damage,
        # are exactly right; only the player's freedom to lump it unevenly is
        # auto-made). ``double_at`` is Shatterskull's "if X is 6 or more,
        # deals twice X … instead" (RULE 107.3) — the pool doubles once the
        # resolved amount reaches that threshold.
        self.divided = divided
        self.double_at = double_at
        self.division: Optional[list[int]] = None
        self.target_spec = None
        if self.group is not None and self.group_player in ("player", "opponent"):
            self.target_spec = TargetSpec(kind=self.group_player)
        if self.selector is None and self.recipient_subject is None:
            # Damage targets "any target" by default (RULE 115.4); a card
            # that only hits creatures can narrow this to "creature".
            # ``optional`` is RULE 115.1a "up to one/N target(s)" — fewer
            # than ``count`` (including zero) is then a legal choice, so
            # casting is never locked on it. ``count`` > 1 is "to each of
            # up to N target X" (Volcanic Salvo-shaped) — the full amount
            # applies to *every* chosen target, not divided among them.
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max,
                colors=tuple(colors) if colors else None,
                # RULE 115/601.2c power/toughness/keyword quality filter —
                # "target creature with flying"/"…with power 4 or greater"
                # (PAR-40), the same `TargetSpec.creature_filter` narrowing
                # `destroy`/`exile` already carry.
                creature_filter=creature_filter,
                # "…and 3 damage to each of up to two **other** targets." (Drakuseth) — RULE 109.5: never a
                # target an earlier requirement of the same ability already chose.
                distinct_from_others=bool(distinct_from_others),
            )

    @property
    def amount(self) -> Union[int, str]:
        kicker_count = getattr(self.source, "kicker_count", 0) or 0
        raid = bool(
            self.source is not None
            and getattr(self.source, "controller_id", None)
            in (getattr(getattr(self, "_state", None), "players_attacked_this_turn", None) or set())
        )
        bargained = getattr(self.source, "bargained", False)
        source_subtype_match = False
        if self.amount_if_source_subtype is not None and self.source is not None:
            subtype, _ = self.amount_if_source_subtype
            words = self.source.card.type_line.partition("—")[2].strip().lower().split()
            source_subtype_match = subtype.lower() in words

        full_party = False
        state = getattr(self, "_state", None)
        if self.amount_if_full_party is not None and self.source is not None and state is not None:
            from .. import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            full_party = continuous.count_selector(
                state, controller_id, "creatures_in_your_party", source=self.source,
            ) >= 4

        def _bargained_amount() -> Union[int, str]:
            if self.double_if_bargained:
                base = self._base_amount
                return base * 2 if isinstance(base, int) else base
            return self.amount_if_bargained

        return self._resolve_amount_override(
            self._base_amount,
            [
                (
                    self.x_multiplier is not None,
                    lambda: self.x_multiplier * (getattr(self.source, "x_paid", 0) or 0),
                ),
                (self.amount_if_kicked is not None and kicker_count > 0, lambda: self.amount_if_kicked),
                (
                    self.amount_if_teamwork is not None and bool(getattr(self.source, "teamwork_paid", False)),
                    lambda: self.amount_if_teamwork,
                ),
                (self.amount_if_raid is not None and raid, lambda: self.amount_if_raid),
                (
                    self.amount_if_mana_color_spent is not None
                    and self.source is not None
                    and int((getattr(self.source, "mana_by_color_spent_to_cast", None) or {}).get(
                        str(self.amount_if_mana_color_spent.get("color", "")).upper(), 0
                    )) >= int(self.amount_if_mana_color_spent.get("threshold", 1)),
                    lambda: self.amount_if_mana_color_spent["amount"],
                ),
                (full_party, lambda: self.amount_if_full_party),
                (
                    self.amount_if_cast_from_exile is not None and getattr(self.source, "cast_from_exile", False),
                    lambda: self.amount_if_cast_from_exile,
                ),
                (
                    bargained and (self.double_if_bargained or self.amount_if_bargained is not None),
                    _bargained_amount,
                ),
                (
                    source_subtype_match,
                    lambda: self.amount_if_source_subtype[1],
                ),
            ],
            stop_at_first=True,
        )

    def _amount_for(self, target: Any, context: Optional["GameContext"] = None) -> Union[int, str]:
        """``self.amount``, further narrowed by ``amount_if_target_event``/
        ``amount_from_count_selector``/``amount_if_target_color`` for this
        specific ``target`` (see each field's own docstring)."""

        def _from_count_selector() -> int:
            from .. import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            return self.amount_plus_count_selector + self.amount_multiplier * continuous.count_selector(
                context.state, controller_id, self.amount_from_count_selector, source=self.source,
            )

        def _from_target_color() -> Union[int, str]:
            override, _ = self.amount_if_target_color
            return override

        target_color_match = False
        if self.amount_if_target_color is not None:
            _, colors = self.amount_if_target_color
            target_colors = {str(c).upper() for c in (getattr(target, "colors", None) or set())}
            target_color_match = bool(target_colors & {str(c).upper() for c in colors})

        return self._resolve_amount_override(
            self.amount,
            [
                (
                    bool(self.amount_from_trigger_event) and context is not None,
                    lambda: int((context.trigger_event or {}).get(self.amount_from_trigger_event) or 0),
                ),
                (bool(self.amount_from_count_selector) and context is not None, _from_count_selector),
                (target_color_match, _from_target_color),
            ],
        )

    @amount.setter
    def amount(self, value: Union[int, str]) -> None:
        # `RulesEngine.resolve_top_of_stack`'s `_substitute_x` rewrites a
        # spell's own "x" sentinel to the announced X in place via plain
        # `setattr` — kept writable (onto `_base_amount`, not a fixed value)
        # so that substitution still composes with `amount_if_kicked`
        # exactly as an X-kicker spell's base amount would.
        self._base_amount = value

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.dealer_event_key is None:
            self._apply_from(context, targets)
            return
        # PAR-123: under a group trigger "it deals N damage" names the object that fired the
        # trigger, not this ability's source (Dragon Tempest) — deal from it for this resolution
        # only, since one effect instance serves every future firing of the ability.
        dealer = context.state.find_object((context.trigger_event or {}).get(self.dealer_event_key))
        if dealer is None:
            return
        original = self.source
        self.source = dealer
        try:
            self._apply_from(context, targets)
        finally:
            self.source = original

    def _apply_from(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        # Amount overrides are resolve-time questions; Raid reads the same
        # player declaration history as every other controller-scoped gate.
        self._state = context.state
        if not self.unpreventable:
            self._apply_impl(context, targets)
            return
        # RULE 615.6: for the span of this one effect, no prevention shield
        # applies — flip the flag `_run_replacement_loop` checks, then
        # restore it so unrelated later damage this turn is unaffected.
        prior = context.state.damage_prevention_disabled
        context.state.damage_prevention_disabled = True
        try:
            self._apply_impl(context, targets)
        finally:
            context.state.damage_prevention_disabled = prior

    def _apply_impl(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            self._apply_selector(context, targets)
            return
        if self.recipient_subject == "trigger_subject_defender":
            # "~ deals 1 damage to the player or planeswalker **it's attacking**" (PAR-123, Hellrider):
            # what the attacker that fired the trigger was declared against (`combat_defender` — a
            # player, or a planeswalker/battle), read live off that attacker.
            attacker = context.state.find_object((context.trigger_event or {}).get("instance_id"))
            defender = getattr(attacker, "combat_defender", None) or {}
            if defender.get("kind") == "player":
                try:
                    recipient = context.state.player_by_id(defender.get("id"))
                except (KeyError, ValueError):
                    recipient = None
            else:
                recipient = context.state.find_object(defender.get("instance_id"))
            if recipient is not None:
                context.deal_damage(recipient, self._amount_for(recipient, context), self.source)
            return
        if self.recipient_subject is not None:
            who = self.recipient_subject.rpartition("_")[0]  # strip trailing "_controller"
            obj = None
            if who == "attached_permanent":
                # MEC-47 (Leeching Licid): "…deals 1 damage to that player."
                # where "that player" is the enchanted creature's
                # controller — read live off the Aura's own `attached_to`.
                host_id = getattr(self.source, "attached_to", None)
                obj = context.state.find_object(host_id) if host_id is not None else None
            elif who == "previous_subject":
                prev = list(context.previous_targets)
                obj = prev[0] if prev else None
            elif who == "damage_recipient":
                # "…that archer deals that much damage to **that creature's** controller" (Greatbow
                # Doyen): the creature the firing DAMAGE event's damage was dealt to.
                obj = context.state.find_object((context.trigger_event or {}).get("target_id"))
            elif who == "trigger_subject":
                ev = context.trigger_event or {}
                obj = context.state.find_object(ev.get("instance_id"))
                # RULE 400.7: a dies/blocks event's object may already be
                # gone — fall back to the controller id the event stamped.
                if obj is None and ev.get("controller_id") is not None:
                    try:
                        player = context.state.player_by_id(ev["controller_id"])
                    except (KeyError, ValueError):
                        player = None
                    if player is not None:
                        context.deal_damage(player, self._amount_for(None, context), self.source)
                    return
            controller_id = getattr(obj, "controller_id", None)
            if controller_id is not None:
                try:
                    player = context.state.player_by_id(controller_id)
                except (KeyError, ValueError):
                    player = None
                if player is not None:
                    context.deal_damage(player, self._amount_for(obj, context), self.source)
            return
        chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
        if self.divided:
            override = self.each_target_if_mana_color_spent or {}
            paid = getattr(self.source, "mana_by_color_spent_to_cast", None) or {}
            if override and int(paid.get(str(override.get("color", "")).upper(), 0)) >= int(override.get("threshold", 1)):
                # Sundering Stroke's Adamant branch replaces the divided pool
                # with the full printed amount to every already chosen target.
                for target in chosen:
                    context.deal_damage(target, self._amount_for(target, context), self.source)
                return
            self._apply_divided(context, chosen)
            return
        # "targets only a single creature" (Imodane, the Pyrohammer) is a
        # property of *this effect's own* target_spec, not of the damage in
        # general — computed here, where that shape is known, and carried
        # onto the DAMAGE event by `RulesEngine.deal_damage`.
        single_target_hint = (
            self.selector is None and self.target_spec is not None
            and self.target_spec.count == 1 and not self.target_spec.optional
        )
        for target in chosen:
            context.deal_damage(
                target, self._amount_for(target, context), self.source,
                single_target_hint=single_target_hint,
            )
            if self.tap_target_if_colorless and getattr(target, "is_creature", False):
                colors = {str(c).upper() for c in (getattr(target, "colors", None) or set())}
                if not colors.intersection({"W", "U", "B", "R", "G"}):
                    # Reuse TapEffect so the normal TAPPED event and trigger
                    # path are preserved rather than directly flipping a flag.
                    from .attachments_transforms import TapEffect
                    TapEffect(source=self.source, target_kind="creature").apply(context, [target])

    def _apply_divided(self, context: GameContext, targets: list[Any]) -> None:
        """Split the pool across ``targets`` (RULE 601.2d) — see ``divided``."""
        if not targets:
            return
        # The pool is the resolved amount, so a computed X (Monstrous Onslaught's greatest power) divides too.
        total = self._amount_for(targets[0], context)
        total = total if isinstance(total, int) else 0
        if self.double_at is not None and total >= self.double_at:
            total *= 2  # RULE 107.3: "deals twice X … instead"
        if self.division is not None and len(self.division) == len(targets):
            amounts = [int(a) for a in self.division]
        else:
            base, extra = divmod(total, len(targets))
            amounts = [base + (1 if i < extra else 0) for i in range(len(targets))]
        for target, amount in zip(targets, amounts):
            if amount > 0:
                context.deal_damage(target, amount, self.source)

    def _apply_selector(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        # "Imodane deals that much damage to each opponent." — the mass-
        # selector sibling of `_amount_for`'s single-target read: `self.
        # amount` (the property below) takes no `context`, so the
        # trigger-event override is resolved into a local here instead,
        # once, and threaded through every `context.deal_damage` call this
        # method makes below (shadowing `self.amount` reads inline rather
        # than mutating shared state, since this effect instance is reused
        # across every future firing of the same permanent's ability).
        amount = self.amount
        if self.amount_from_trigger_event:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
        if self.amount_from_count_selector:
            # "it deals damage to each opponent equal to your devotion to
            # red." (Fanatic of Mogis) — `_amount_for`'s own read, needed
            # here too since the mass-selector path never calls that method.
            from .. import continuous  # avoid the continuous↔effects import cycle

            controller_id_for_amount = getattr(self.source, "controller_id", None)
            amount = self.amount_plus_count_selector + self.amount_multiplier * continuous.count_selector(
                context.state, controller_id_for_amount, self.amount_from_count_selector, source=self.source,
            )
        if self.amount_from_noncreature_spells_cast_this_turn:
            caster = _event_player(context, key="player_id")
            amount = context.state.noncreature_spells_cast_this_turn.get(getattr(caster, "id", None), 0)
        if self.selector == "group":
            from ..continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            if self.group_player is not None:
                if self.group_player == "defending":
                    scoped = _defending_player_of(self.source, context)
                elif self.group_player == "event_player":
                    scoped = _event_player(context, key="target_id")
                elif self.group_player == "previous_controller":
                    # "…deals 4 damage to target creature an opponent controls. Then ~ deals
                    # 2 damage to each other creature **that player** controls." — the
                    # earlier clause's target's controller (last-known, so it may have died).
                    prev = context.previous_targets[0] if context.previous_targets else None
                    owner_id = getattr(prev, "controller_id", None)
                    scoped = context.state.player_by_id(owner_id) if owner_id is not None else None
                else:
                    scoped = (targets or [self.target])[0] if (targets or self.target is not None) else None
                if scoped is None or getattr(scoped, "id", None) is None or not hasattr(scoped, "life"):
                    return
                controller_id = scoped.id
            # Snapshot first: an early death must not skip a still-owed hit.
            for obj in list(group_selector_objects(context.state, controller_id, self.group, src=self.source)):
                context.deal_damage(obj, amount, self.source)
            if self.group_and_players is not None:
                for player in list(context.state.living_players()):
                    if self.group_and_players == "each_opponent" and player.id == getattr(self.source, "controller_id", None):
                        continue
                    context.deal_damage(player, amount, self.source)
            return
        if self.selector == "attacked_object":
            # "…deals X damage to the player or planeswalker it's attacking." (Myr Battlesphere) — the
            # thing this attacker was declared against (`combat_defender`), a player or a permanent.
            spec = getattr(self.source, "combat_defender", None) or {}
            if spec.get("kind") == "player":
                victim = context.state.player_by_id(spec.get("id"))
            else:
                victim = context.state.find_object(spec.get("id")) if spec.get("id") is not None else None
            if victim is not None:
                context.deal_damage(victim, amount, self.source)
            return
        if self.selector == "defending_player":
            # Simian Sling's "it deals 1 damage to defending player" — the
            # same per-firing dynamic-defender resolution afflict's
            # `LoseLifeEffect` selector uses (`_defending_player_of`), just
            # dealing damage instead of a direct life loss.
            player = _defending_player_of(self.source, context)
            if player is not None:
                if self.amount_from_defending_player_hand_size:
                    amount = len(player.hand)
                context.deal_damage(player, amount, self.source)
            return
        if self.selector == "each_other_creature":
            # Snapshot first: an early death must not skip a still-owed hit.
            for obj in list(context.state.permanents()):
                if obj.is_creature and obj is not self.source:
                    context.deal_damage(obj, amount, self.source)
            return
        if self.selector in ("each_creature", "each_creature_and_player", "each_creature_and_planeswalker"):
            from ..continuous import group_selector_objects  # avoid the continuous↔effects cycle
            from .. import combat  # local: combat↔effects cycle

            for obj in group_selector_objects(context.state, None, "all_creatures"):
                if self.selector_filter and not combat.matches_object_filter(obj, self.selector_filter):
                    continue
                context.deal_damage(obj, amount, self.source)
            if self.selector == "each_creature_and_planeswalker":
                # A creature that's *also* a planeswalker (rare, but real —
                # RULE 205.2 multi-type permanents) was already hit above;
                # excluding ``is_creature`` here is what keeps it a single
                # hit, not two.
                for obj in context.state.permanents():
                    if obj.is_planeswalker and not obj.is_creature:
                        context.deal_damage(obj, amount, self.source)
                return
            if self.selector == "each_creature":
                return
        controller_id = getattr(self.source, "controller_id", None)
        if self.selector == "controller":
            # "it deals 1 damage to **you**" (Mana Vault) — the source's own
            # controller, and only them.
            player = _controller_of(self.source, context)
            if player is not None:
                context.deal_damage(player, amount, self.source)
            return
        if self.selector == "self":
            # "~ deals 1 damage to itself." (Stuffy Doll)
            if self.source is not None:
                context.deal_damage(self.source, amount, self.source)
            return
        if self.selector == "active_player":
            player = context.state.active_player
            if player is not None:
                context.deal_damage(player, amount, self.source)
            return
        if self.selector == "each_creature_blocking_source":
            src_id = getattr(self.source, "instance_id", None)
            if src_id is None:
                return
            for obj in list(context.state.battlefield):
                if obj.is_creature and getattr(obj, "blocking", None) == src_id:
                    context.deal_damage(obj, amount, self.source)
            return
        if self.selector == "event_player":
            # "whenever a player casts a spell, ~ deals 2 damage to that
            # player." (Spellshock) — the caster named by the SPELL_CAST
            # event that fired this trigger, read via the same
            # `_event_player` helper `PayCostThenEffect` uses.
            player = _event_player(context, key="player_id")
            if player is not None:
                context.deal_damage(player, amount, self.source)
            return
        if self.selector == "event_controller":
            # "Whenever a land enters, ~ deals N damage to that land's
            # controller." (Zo-Zu the Punisher) — see `_DAMAGE_SELECTORS`'
            # own docstring for why this differs from ``event_player``.
            player = _event_player(context)
            if player is not None:
                context.deal_damage(player, amount, self.source)
            return
        if self.selector == "each_creature_controller":
            # "Each creature deals 1 damage to its controller." (Rakdos
            # Charm) — snapshot the list first: a creature's own damage can
            # kill its controller's other creatures via state-based actions
            # mid-loop, which must not skip or reorder anyone still owed a
            # hit.
            for obj in list(context.state.battlefield):
                if not obj.is_creature:
                    continue
                owner = context.state.player_by_id(obj.controller_id)
                if owner is not None:
                    context.deal_damage(owner, amount, obj)
            return
        if self.selector in (
            "each_creature_opponents_control",
            "each_creature_and_planeswalker_opponents_control",
        ):
            # "~ deals N damage to each creature [and planeswalker] your
            # opponents control." (Village Pillagers / Volcanic Torrent) —
            # opponents' permanents only, no players. Snapshot first (an
            # early death must not skip a still-owed hit).
            include_pw = self.selector == "each_creature_and_planeswalker_opponents_control"
            from .. import combat  # local: combat↔effects cycle

            for obj in list(context.state.battlefield):
                if (
                    (obj.is_creature or (include_pw and obj.is_planeswalker))
                    and obj.controller_id is not None
                    and obj.controller_id != controller_id
                    # PAR-128: "each creature with flying your opponents control".
                    and not (self.selector_filter
                             and not combat.matches_object_filter(obj, self.selector_filter))
                ):
                    context.deal_damage(obj, amount, self.source)
            return
        if self.selector in (
            "each_opponent_and_their_creatures", "each_opponent_and_their_creatures_and_planeswalkers",
        ):
            # Snapshot first (same reasoning as `each_creature_controller`
            # above): an opponent's own creature dying to this damage must
            # not skip a later opponent's still-owed hit.
            for obj in list(context.state.battlefield):
                if obj.controller_id == controller_id or obj.controller_id is None:
                    continue
                if obj.is_creature or (
                    self.selector == "each_opponent_and_their_creatures_and_planeswalkers"
                    and obj.is_planeswalker
                ):
                    context.deal_damage(obj, amount, self.source)
            for player in context.state.living_players():
                if player.id != controller_id:
                    context.deal_damage(player, amount, self.source)
            return
        excluded_recipient = None
        if self.selector == "each_other_opponent":
            event = context.trigger_event or {}
            excluded_recipient = event.get("target_id")
        for player in context.state.living_players():
            if self.selector in ("each_opponent", "each_other_opponent") and player.id == controller_id:
                continue
            if player.id == excluded_recipient:
                continue
            context.deal_damage(player, amount, self.source)


#: `DrawCardEffect`'s ``count_selector`` vocabulary — a per-object dynamic
#: draw count (RULE 601.2c-style variable amount), the same "count instead
#: of a flat number" shape `continuous._pt_mod_count` uses for a per-count
#: anthem. Wyleth, Soul of Steel's "draw a card for each Aura and Equipment
#: attached to it"; ``"opponents_you_have"`` (Struggle for Project Purity's
#: Brotherhood mode: "each opponent draws a card. You draw a card for each
#: card drawn this way.") approximates "cards drawn this way" as the
#: opponent count — exact whenever nothing prevented an opponent's draw,
#: the same "auto-resolve the common case" simplification `ProliferateEffect`/
#: `SacrificeEffect` already use elsewhere in this engine.
_DRAW_COUNT_SELECTORS: frozenset[str] = frozenset(
    {
        "auras_and_equipment_attached_to_self", "opponents_you_have", "burden_counters_on_self",
        # "Target player draws cards equal to half the number of cards in
        # their library… Round up." (MEC-43 round 2, Peer into the Abyss)
        # — read off the *resolved drawing player's own* library, not the
        # ability's controller (`amount_from_half_own_life`'s sibling for
        # "half your life" is always the caster; this one is always
        # whoever the target/`player` param resolves to).
        "half_target_library_round_up",
    }
)


def _attached_auras_and_equipment_count(context: GameContext, source: Optional["GameObject"]) -> int:
    if source is None:
        return 0
    return sum(
        1 for o in context.state.battlefield
        if o.attached_to == source.instance_id
        and ("aura" in o.card.type_line.lower() or "equipment" in o.card.type_line.lower())
    )


class DrawIfTriggerObjectGreatestPowerEffect(GameEffect):
    """"…its controller may draw a card if its power is greater than each
    other creature's power." (Selvala, Heart of the Wilds, MEC-43) — "its"
    (RULE 603.1) is the firing `EventType.ENTERS_BATTLEFIELD` event's own
    object, not a fixed subject; the comparison is a strict "greater than
    **each** other creature" (a tie with even one other creature
    disqualifies it), re-evaluated live off the board at resolution rather
    than snapshotted at trigger time.

    **Documented simplification**: "may" is read as unconditional, the same
    accepted convention every other untargeted "you may" trigger with no
    real downside to declining already gets in this engine.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event or {}
        instance_id = event.get("instance_id")
        obj = context.state.find_object(instance_id) if instance_id is not None else None
        if obj is None or not obj.is_creature:
            return
        power = obj.power or 0
        others = [o for o in context.state.permanents() if o.is_creature and o is not obj]
        if any((o.power or 0) >= power for o in others):
            return
        if not obj.controller_id:
            return
        try:
            player = context.state.player_by_id(obj.controller_id)
        except (KeyError, ValueError):
            return
        context.draw(player, 1)


class DrawCardEffect(GameEffect):
    """Draw ``count`` cards for the effect's controller (or a target player)
    — or, with ``count_selector`` set, a per-object dynamic count instead of
    a flat number (Wyleth, Soul of Steel's "draw a card for each Aura and
    Equipment attached to it"). ``selector="each_player"``/``"each_opponent"``
    (Struggle for Project Purity's Brotherhood mode: "each opponent draws a
    card") is instead a mass, untargeted draw for every matching living
    player — mirrors `AddPlayerCountersEffect.selector`'s shape.
    """

    def __init__(
        self,
        count: int = 1,
        player: Any = None,
        source: Optional["GameObject"] = None,
        count_selector: Optional[str] = None,
        target_kind: Optional[str] = None,
        selector: Optional[str] = None,
        target_count: int = 1,
        target_optional: bool = False,
    ) -> None:
        super().__init__(source)
        #: How many cards: a number, or an `effect_amounts` operand measured at resolution
        #: ("draw cards equal to its power", "that many", "a card for each -1/-1 counter on it").
        self.count = count
        self.player = player
        self.count_selector = count_selector if count_selector in _DRAW_COUNT_SELECTORS else None
        self.selector = (
            selector
            if selector in ("each_player", "each_opponent", "attacking_player", "event_player")
            else None
        )
        # "Target player draws N cards" (Sign in Blood-shaped) — a genuine
        # RULE 115 target, unlike the untargeted default (most draw effects
        # just draw for their own controller).
        # ``target_count``/``target_optional`` widen it to "any number of target opponents each draw a card"
        # (Communal Brewing — RULE 115.1a's "up to N"): every chosen player draws.
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=bool(target_optional), count=max(1, int(target_count)))
            if target_kind is not None else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        count = self._measured(self.count, context, targets)
        if self.target_spec is not None and (self.target_spec.count > 1 or self.target_spec.optional):
            for chosen in list(targets or [])[: self.target_spec.count]:
                if getattr(chosen, "instance_id", None) is None and getattr(chosen, "id", None) is not None:
                    context.draw(chosen, count)
            return
        if self.selector == "event_player":
            # "…you and the controller of those creatures each draw a card." (Nelly Borca,
            # MEC-104) — the player the firing event names (``player_id``: the combat-damage
            # aggregate's contributing creatures' controller).
            eid = (context.trigger_event or {}).get("player_id")
            try:
                drawer = context.state.player_by_id(eid) if eid is not None else None
            except (KeyError, ValueError):
                drawer = None
            if drawer is not None:
                context.draw(drawer, count)
            return
        if self.selector == "attacking_player":
            # "…that attacking player draws a card…" (Breena, the Demagogue)
            # — whoever the firing `PLAYER_ATTACKED` aggregate names as the
            # attacker, not this ability's controller.
            aid = (context.trigger_event or {}).get("attacking_player_id")
            try:
                drawer = context.state.player_by_id(aid) if aid is not None else None
            except (KeyError, ValueError):
                drawer = None
            if drawer is not None:
                context.draw(drawer, count)
            return
        if self.selector in ("each_player", "each_opponent"):
            controller_id = getattr(self.source, "controller_id", None)
            for p in context.state.living_players():
                if self.selector == "each_opponent" and p.id == controller_id:
                    continue
                context.draw(p, count)
            return
        # Like `GainLifeEffect`/`LoseLifeEffect`: only consume the shared
        # `targets` list when this effect actually declared a target_spec
        # of its own (`target_kind` set) — otherwise a `targets[0]` left
        # over from a *different* targeting effect in the same resolution
        # (Deathrite Shaman-shaped "Exile target creature card... Draw a
        # card.", or a delayed trigger that inherited its arming
        # resolution's own targets) would silently get handed to
        # `RulesEngine.draw` as if it were a chosen player.
        explicit = self.player
        if isinstance(explicit, int) and not isinstance(explicit, bool):
            # A granted trigger's body naming its grantor (`continuous.GRANTOR_SENTINEL`, resolved to an object id):
            # "…whenever either of those creatures deals combat damage, **you** draw a card" (Tamiyo, Field
            # Researcher) — the grantor's controller, not the creature's.
            grantor = context.state.find_object(explicit)
            try:
                explicit = context.state.player_by_id(getattr(grantor, "controller_id", None))
            except (KeyError, ValueError):
                return
        player = self._resolve_target_or_controller(context, targets, explicit=explicit)

        count = self._resolve_amount_override(
            count,
            [
                (
                    self.count_selector == "auras_and_equipment_attached_to_self",
                    lambda: _attached_auras_and_equipment_count(context, self.source),
                ),
                (
                    self.count_selector == "opponents_you_have",
                    lambda: sum(
                        1 for p in context.state.living_players()
                        if p.id != getattr(self.source, "controller_id", None)
                    ),
                ),
                (
                    # "…draw a card for each burden counter on The One Ring." — read *after*
                    # this same activation's own ``add_counters`` effect has already placed this
                    # turn's counter (RULE 608.2b, effects in printed order), so the count
                    # includes it.
                    self.count_selector == "burden_counters_on_self",
                    lambda: int((getattr(self.source, "counters", None) or {}).get("burden", 0)),
                ),
                (
                    self.count_selector == "half_target_library_round_up",
                    # ceiling division (RULE 107.3 rounds up)
                    lambda: -(-len(getattr(player, "library", None) or []) // 2),
                ),
            ],
            stop_at_first=True,
        )
        context.draw(player, count)


class DrawPerAttachedAuraControllerEffect(GameEffect):
    """"Whenever an enchanted creature dies, draw a card for each Aura you
    controlled that was attached to it." (Hateful Eidolon, PAR-60.)

    Reads the firing DIES event's ``attached_aura_controller_ids`` snapshot
    (`RulesEngine._move_to_graveyard` records it while the dying creature —
    and its Auras — are still on the battlefield, RULE 603.6a) and draws one
    card per entry equal to this ability's own controller id. Zero matching
    Auras draws nothing.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        cid = getattr(self.source, "controller_id", None)
        if cid is None:
            return
        ids = list((context.trigger_event or {}).get("attached_aura_controller_ids") or [])
        n = sum(1 for c in ids if c == cid)
        if n <= 0:
            return
        try:
            player = context.state.player_by_id(cid)
        except (KeyError, ValueError):
            return
        context.draw(player, n)


def _is_prime(n: int) -> bool:
    """RULE-neutral helper — Zimone's own reminder text enumerates 2, 3, 5,
    7, 11, 13, 17, 19, 23, 29, 31; 1 and 0 are not prime."""
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


class ZimoneAllQuestioningEndStepEffect(GameEffect):
    """"At the beginning of your end step, if a land entered the battlefield
    under your control this turn and you control a prime number of lands,
    create Primo, the Indivisible, a legendary 0/0 green and blue Fractal
    creature token, then put that many +1/+1 counters on it." (Zimone,
    All-Questioning, PAR-60.)

    Self-gating: the "a land entered … this turn" + "prime number of lands"
    intervening-if is checked here at resolution rather than via new
    condition-key plumbing (`GameState.lands_entered_this_turn`, added
    alongside its creature sibling).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import synthesize_token_card

        cid = getattr(self.source, "controller_id", None)
        if cid is None:
            return
        if int(context.state.lands_entered_this_turn.get(cid, 0)) <= 0:
            return
        land_count = sum(
            1 for o in context.state.permanents_controlled_by(cid) if o.is_land
        )
        if not _is_prime(land_count):
            return
        card = synthesize_token_card(
            "Primo, the Indivisible", power=0, toughness=0,
            colors=["G", "U"], subtypes=["Fractal"],
        )
        card.type_line = "Legendary Creature — Fractal"
        made = context.create_token(cid, card, 1)
        for tok in made or []:
            context.add_counters(tok, land_count, "+1/+1", source=self.source)
        context.recompute()


class DrawEachPlayerWithCreaturePowerEffect(GameEffect):
    """Each player controlling a creature with power at least ``min_power`` draws.

    This is a simultaneous-condition sweep: eligibility is checked before a
    following board wipe changes the battlefield (Shatter the Sky).
    """
    def __init__(self, min_power: int = 4, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.min_power = min_power

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for player in context.state.living_players():
            if any(
                obj.is_creature and obj.power >= self.min_power
                for obj in context.state.permanents_controlled_by(player.id)
            ):
                context.draw(player, 1)


class DrawControlledChosenCreatureTypeEffect(GameEffect):
    """Draw for each creature of this spell's resolve-time chosen type."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .. import continuous
        player = _controller_of(self.source, context)
        chosen = getattr(self.source, "chosen_type", None)
        if player is None or not chosen:
            return
        count = sum(
            1 for obj in context.state.permanents_controlled_by(player.id)
            if obj.is_creature and continuous.has_subtype(obj, chosen)
        )
        context.draw(player, count)


class SylvanLibraryEffect(GameEffect):
    """"At the beginning of your draw step, you may draw two additional
    cards. If you do, choose two cards in your hand drawn this turn. For
    each of those cards, pay 4 life or put the card on top of your
    library." (Sylvan Library, MEC-40)

    The whole ability's own `TriggeredAbility.optional=True` already models
    the "you may draw" gate (declining draws nothing, so there's nothing
    left to choose from afterward) — this effect is the "if you do"
    continuation: draw ``count`` more, then hand the *specific just-drawn
    objects* to `RulesEngine._request_pay_life_or_return_to_library`'s own
    sequential per-card chooser.

    **Documented simplification**: doesn't offer a genuine "choose which
    two" decision when more than ``count`` cards were drawn this turn (a
    second simultaneous draw effect, rare) — always processes the most
    recently drawn ``count`` (`GameState.cards_drawn_this_turn_ids`), which
    is always exactly this ability's own two in the overwhelming common
    case (nothing else draws in the same window).
    """

    def __init__(
        self, life: int = 4, count: int = 2, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.life = life
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.draw(player, self.count)
        drawn_ids = set(
            context.state.cards_drawn_this_turn_ids.get(player.id, [])[-self.count:]
        )
        objs = [o for o in player.hand if o.instance_id in drawn_ids]
        context.engine._request_pay_life_or_return_to_library(player, objs, amount=self.life)


def _reveal_whose_player(
    whose: str, source: Optional["GameObject"], context: GameContext,
    targets: Optional[list[Any]] = None,
) -> Optional["Player"]:
    """The player a `reveal_top` / `put_revealed_card` clause acts on."""
    if whose == "defending_player":
        return _defending_player_of(source, context)
    if whose == "target":
        # "Each player reveals the top card of **their** library" (Selvala) — the `for_each` item handed to the
        # body as its target, whoever it is (not the ability's controller).
        item = targets[0] if targets else None
        return item if item is not None and getattr(item, "instance_id", None) is None else None
    return _controller_of(source, context)


class RevealTopEffect(GameEffect):
    """RULE 701.20 — reveal the top card of a library, and stash it as
    `GameContext.revealed_card` so a following `if_else`/`bind` clause can
    ask about it (``of: "revealed"``) — "reveal the top card of your
    library. If it's a land card, …" (Goblin Guide, Dark Confidant,
    Thrasios). ENG-37 B5: the referent half of retiring the `reveal_top_*`
    fusion family.

    Records the card and emits a public REVEAL event. Acting on it
    (move to hand/battlefield, lose life, …) is a separate body clause. An empty library reveals nothing
    and leaves `revealed_card` as it was reset to (``None``).
    """

    def __init__(self, whose: str = "you", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.whose = str(whose or "you")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        context.revealed_card = None
        player = _reveal_whose_player(self.whose, self.source, context, targets)
        if player is None or not player.library:
            return
        context.revealed_card = player.library[-1]
        context.state.fire_event(GameEvent(
            EventType.REVEAL, player_id=player.id, object=context.revealed_card.name,
            instance_id=context.revealed_card.instance_id, from_zone=Zone.LIBRARY.value,
        ))


class PutRevealedCardEffect(GameEffect):
    """Move `GameContext.revealed_card` (a `RevealTopEffect` clause set it,
    RULE 701.20) from the top of its owner's library to ``destination``:
    ``"hand"`` (RULE 121.4 — *not* a draw, so no draw replacement /
    "whenever you draw" trigger fires), ``"battlefield"`` or
    ``"battlefield_tapped"``.

    A no-op if nothing was revealed, or if the card is no longer on top of
    that library (an intervening clause moved it). ENG-37 B5.
    """

    def __init__(
        self, destination: str = "hand", whose: str = "you",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.destination = str(destination or "hand")
        self.whose = str(whose or "you")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        card = getattr(context, "revealed_card", None)
        if card is None:
            return
        player = _reveal_whose_player(self.whose, self.source, context)
        if player is None or not player.library or player.library[-1] is not card:
            return
        if self.destination == "exile":
            context.exile(card)
            return
        player.library.pop()
        if self.destination in ("battlefield", "battlefield_tapped"):
            card.zone = Zone.BATTLEFIELD
            card.tapped = self.destination == "battlefield_tapped"
            context.state.add_to_battlefield(card)
            context.state.fire_event(GameEvent(
                EventType.ENTERS_BATTLEFIELD, controller_id=player.id, object=card.name,
                from_zone=Zone.LIBRARY.value,
                instance_id=card.instance_id, object_types=sorted(card.type_words),
            ))
        else:
            player.add_to_zone(card, Zone.HAND)


class CastRevealedCardFreeEffect(GameEffect):
    """"You may cast that card without paying its mana cost." acting on
    `GameContext.revealed_card` (a `RevealTopEffect` clause set it) —
    Powerbalance's own "if you do, you may cast that card … if the two
    spells have the same mana value" (the mana-value gate is a sibling
    `if_else` clause). Opens `_request_choose_objects`' existing
    ``"cast_free"`` action over the one revealed card, ``optional`` so the
    player may decline (RULE 601.2b). A no-op if nothing was revealed.
    ENG-37 B5.
    """

    def __init__(self, whose: str = "you", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.whose = str(whose or "you")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        card = getattr(context, "revealed_card", None)
        if card is None:
            return
        player = _reveal_whose_player(self.whose, self.source, context)
        if player is None:
            return
        context.choose_objects(
            player, [card], "cast_free", count=1, optional=True, source=self.source,
        )


class DiscardEffect(GameEffect):
    """Make a player discard ``count`` cards — an interactive choice (RULE
    701.8: the discarding player, not this effect's controller, picks which
    cards), the looting-shaped template ("draw a card, then discard a
    card") shares with a directly-targeted forced discard (Mind Rot).

    ``target_kind="player"`` ("target player/opponent discards N cards")
    opts into a real RULE 115 target, exactly as `GainLifeEffect`'s own
    ``target_kind`` does — and for the same reason: without a declared
    `target_spec` this effect must *not* read ``targets[0]``, since any
    targets present would belong to a different effect on the same
    ability. ``scope`` ("each_player"/"each_opponent") is the untargeted
    mass form (RULE 601.2c), which hits everyone rather than one pick.

    ``draw_per_discard`` (MEC-43 round 4C, Syphon Mind — "Each other player
    discards a card. You draw a card for each card discarded this way.")
    queues a ``draw`` `EffectSpec` as `discard_choice`'s own ``then_specs``
    for every player asked to discard, so this effect's own controller
    draws ``count`` cards *per player who actually discarded* — not a flat
    amount, and not double-counted for a player whose hand was already
    empty (`_request_choose_objects` only ever runs its "if you do" tail
    when at least one card was actually picked). Deliberately built on the
    discard's own resolution rather than a `GameContext` same-resolution
    accumulator (`life_lost_this_way`'s idiom): unlike a destroy/life-loss,
    a non-forced discard is *interactive* (RULE 701.8 — the discarding
    player picks which card), so the true count isn't known until each
    `pending_choice` actually resolves, possibly turns of real time later
    in a multiplayer game; threading it through as a follow-up effect
    keeps the draw honest no matter how long that takes.

    ``player`` also accepts a ``{"of": …, "as": "controller"|"owner"}``
    referent (PAR-115, "destroy target creature. **its controller**
    discards a card.") — resolved the same way `GainLifeEffect`/
    `LoseLifeEffect`/`DrawCardEffect` already read one, through
    `GameEffect._operand_player`.
    """

    def __init__(
        self,
        count: int = 1,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        scope: Optional[str] = None,
        player_from_trigger_event: bool = False,
        draw_per_discard: bool = False,
        previous_subject: bool = False,
        random: bool = False,
        whole_hand: bool = False,
        count_max: Optional[int] = None,
        then_draw_discarded: bool = False,
        filter: Optional[dict[str, Any]] = None,
        unless_discard: Optional[dict[str, Any]] = None,
        player_id: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.player = player
        #: "Discard N cards **unless** you discard a `<quality>` card." (Thirst for Knowledge, Compulsive
        #: Research, Alpharael) — the discarding player may instead discard one hand card matching this
        #: filter (``{"card_type": "land"}`` / ``{"nonland": True}`` / ``{"subtype": "pirate"}``); declining —
        #: or holding no such card — discards ``count`` cards as usual (RULE 608.2, the choice is theirs).
        self.unless_discard = dict(unless_discard) if unless_discard else None
        #: An explicit discarding player by id — what the "declined, so discard N" branch of
        #: ``unless_discard`` carries across the choice (serialized specs hold no `Player`).
        self.player_id = player_id
        #: "…discards all cards with that spell's mana value." (PAR-74,
        #: Infernal Kirin) — RULE 601.2c's non-interactive "all `<filter>`"
        #: mass discard, unlike every other mode above (all RULE 701.8
        #: player choices over a *count*). Only ``mana_value_from_trigger_
        #: event`` is recognized so far (`DestroyEffect.filter`'s identical
        #: key, same PAR-71 "that spell's mana value" referent) — a closed,
        #: fail-closed vocabulary the same way `DestroyEffect.filter` is.
        self.filter = dict(filter) if filter else None
        #: "Discard **up to** N cards[, then draw that many]." (Cathartic
        #: Pyre mode 2, Kinetic Augur, Daretti +2 — ENG-37 B7 retired the
        #: fused `discard_up_to_then_draw_that_many` type here.) ``count_max``
        #: makes the interactive discard a ceiling, not a quota (RULE 601.2b
        #: over each pick); ``then_draw_discarded`` queues
        #: `draw_cards_discarded_delta` as the choice's own ``then_specs``,
        #: so the draw is exactly the number *actually* discarded (the
        #: `GameState.cards_discarded_this_turn` delta, which survives the
        #: `pending_choice` pause because it lives on the state).
        self.count_max = int(count_max) if count_max is not None else None
        self.then_draw_discarded = bool(then_draw_discarded)
        #: "…discards their hand…" (RULE 701.8f — the wheel family: Wheel of
        #: Fortune, Windfall, Timetwister). ``count`` is then whatever that
        #: player is holding when this effect reaches them, so a `scope`
        #: sweep discards each player's own hand size rather than one shared
        #: number. Non-interactive (there is nothing to pick), matching the
        #: `context.discard(player, len(hand))` the fused `wheel`/`windfall`
        #: classes used before ENG-37 decomposed them.
        self.whole_hand = bool(whole_hand)
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        self.scope = scope
        #: "…discards a card **at random**." (RULE 701.8d — Black Cat /
        #: Bottomless Pit / Hypnotic Specter). Routes to
        #: `RulesEngine.discard_random` (uniform pick, no chooser) instead
        #: of the interactive `discard_choice`, in every player-resolution
        #: branch below.
        self.random = bool(random)
        #: "**That player** discards a card." — the same `Player` an earlier
        #: clause of this resolution RULE 115-targeted (Pulling Teeth's
        #: "…target player discards two cards. Otherwise, that player…"),
        #: OR, when nothing was targeted, whichever player the firing
        #: trigger's own event names: a DAMAGE event's recipient (Abyssal
        #: Specter — "whenever ~ deals damage to a player, that player
        #: discards a card") or a SPELL_CAST's caster (Oppression). One
        #: param covering both "that player" idioms, resolved in priority
        #: order at apply time.
        self.previous_subject = bool(previous_subject)
        #: "Whenever equipped creature deals combat damage to a player,
        #: **that player** discards a card…" (Sword of Feast and Famine,
        #: MEC-43) — "that player" is the DAMAGE event's own recipient
        #: (``target_id``, ``is_player``), not a chosen target at all — the
        #: `GainLifeEffect.amount_from_trigger_source_toughness` idiom
        #: applied to *who* rather than *how much*, mirroring the bespoke
        #: `LoseGameTriggerDamagedPlayerEffect`'s own read of the same
        #: event field but as a reusable param instead of a one-card class.
        self.player_from_trigger_event = player_from_trigger_event
        self.draw_per_discard = draw_per_discard

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def _then_specs(self) -> Optional[list[dict]]:
        if not self.draw_per_discard:
            return None
        return [{"type": "draw", "params": {"count": self.count}}]

    def _matches_unless_discard(self, obj: Any) -> bool:
        """Whether ``obj`` is the kind of card ``unless_discard`` accepts in place of ``count`` discards."""
        spec = self.unless_discard or {}
        type_line = str(getattr(obj.card, "type_line", "") or "").lower()
        types, _, subtypes = type_line.partition("—")
        if spec.get("nonland"):
            return "land" not in types.split()
        if spec.get("subtype"):
            return str(spec["subtype"]).lower() in subtypes.split()
        return str(spec.get("card_type", "")).lower() in types.split()

    def _discard_from(self, context: GameContext, player: Any) -> None:
        if self.filter is not None:
            if self.filter.get("mana_value_from_trigger_event"):
                mv = (context.trigger_event or {}).get("mana_value")
                context.discard_matching(player, mana_value=mv, cause=self.source)
            return
        count = self._measured(self.count, context)
        if count <= 0:
            return
        if self.unless_discard:
            context.engine._request_choose_objects(
                player,
                [o for o in player.hand if self._matches_unless_discard(o)],
                "discard", count=1, optional=True,
                prompt="Wähle die Karte, die du stattdessen abwirfst (oder lehne ab)", source=self.source,
                else_specs=[{"type": "discard", "params": {"count": count, "player_id": player.id}}],
            )
            return
        if self.whole_hand:
            context.discard(player, len(player.hand), cause=self.source)
            return
        if self.count_max is not None:
            if not player.hand:
                return  # nothing to discard, so nothing to draw
            then = list(self._then_specs() or [])
            if self.then_draw_discarded:
                before = int(
                    (context.state.cards_discarded_this_turn or {}).get(player.id, 0) or 0
                )
                then.append({
                    "type": "draw_cards_discarded_delta",
                    "params": {"player_id": player.id, "before": before},
                })
            context.discard_choice(
                player, self.count_max, source=self.source,
                then_specs=then or None, optional=True,
            )
            return
        if self.random:
            context.discard_random(player, count, cause=self.source)
        else:
            context.discard_choice(
                player, count, source=self.source, then_specs=self._then_specs()
            )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.scope:
            controller = _controller_of(self.source, context)
            for other in context.state.living_players():
                if self.scope == "each_opponent" and other is controller:
                    continue
                self._discard_from(context, other)
            return
        # A ``{"of": …, "as": "controller"}`` referent ("destroy target
        # creature. its controller discards a card." — PAR-115) resolves
        # through the same shared vocabulary `LoseLifeEffect`/`GainLifeEffect`/
        # `DrawCardEffect` already read via `_operand_player`; an
        # already-resolved `Player` (or ``None``) passes straight through
        # unchanged, so every existing caller of this field keeps working.
        player = self._operand_player(context, targets, self.player) or (
            None if isinstance(self.player, (str, dict)) else self.player
        )
        if player is None and self.previous_subject:
            prev = list(context.previous_targets)
            player = prev[0] if prev else None
            if player is None:
                # No RULE 115 target in this resolution — "that player" is
                # the firing trigger's own event player (Abyssal Specter's
                # damaged player, Oppression's caster).
                event = context.trigger_event or {}
                if event.get("is_player"):
                    try:
                        player = context.state.player_by_id(event.get("target_id"))
                    except (KeyError, ValueError):
                        player = None
                if player is None:
                    player = (
                        _event_player(context, key="player_id")
                        or _event_player(context)
                    )
        if player is None and self.player_from_trigger_event:
            event = context.trigger_event or {}
            if event.get("is_player"):
                try:
                    player = context.state.player_by_id(event.get("target_id"))
                except (KeyError, ValueError):
                    player = None
        if player is None and self.target_spec is not None and targets:
            player = targets[0]
        if player is None and self.player_id is not None:
            try:
                player = context.state.player_by_id(self.player_id)
            except (KeyError, ValueError):
                player = None
        if player is None:
            player = _controller_of(self.source, context)
        self._discard_from(context, player)


class ExileHandCardEffect(GameEffect):
    """Make a player exile ``count`` cards from their own hand (PAR-74 —
    Kyoki, Sanity's Eclipse: "target opponent exiles a card from their
    hand."). The exile-zone sibling of `DiscardEffect` above, trimmed to the
    one shape a real card has needed so far: a RULE 115 ``target_kind=
    "player"`` pick (mirroring `DiscardEffect`'s own), resolved through
    `GameContext.exile_hand_choice` — RULE 701.5a's interactive "that player
    chooses" (not this effect's controller), same `_request_choose_objects`
    chooser `discard_choice` uses, just with its ``"exile"`` action instead
    of ``"discard"``.
    """

    def __init__(
        self,
        count: int = 1,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        previous_subject: bool = False,
        zone: str = "hand",
    ) -> None:
        super().__init__(source)
        self.count = count
        #: ``"graveyard"`` — "target player exiles a card from their graveyard" (Merrow Bonegnawer).
        self.zone = zone if zone in ("hand", "graveyard") else "hand"
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        #: "**That player** exiles a card from their hand." — the `Player`
        #: an earlier clause of this resolution RULE 115-targeted, the same
        #: `DiscardEffect.previous_subject` idiom.
        self.previous_subject = bool(previous_subject)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = None
        if self.previous_subject:
            prev = list(context.previous_targets)
            player = prev[0] if prev else None
        if player is None and self.target_spec is not None and targets:
            player = targets[0]
        if player is None:
            player = _controller_of(self.source, context)
        if player is None or self.count <= 0:
            return
        context.exile_hand_choice(player, self.count, source=self.source, zone=self.zone)


class LookAtHandEffect(GameEffect):
    """"Look at target player's hand." (Clairvoyance, Peek, Glasses of Urza, Ingenious Thief) — the
    effect's controller is shown that player's hand (`RulesEngine.look_at_hand`); nothing changes."""

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "player",
        previous_subject: bool = False,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        #: "…look at **that player's** hand" after an earlier clause aimed at a player.
        self.previous_subject = bool(previous_subject)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        looker = _controller_of(self.source, context)
        owner = None
        if self.previous_subject:
            prev = list(context.previous_targets)
            owner = prev[0] if prev else None
        if owner is None and self.target_spec is not None and targets:
            owner = targets[0]
        if looker is not None and owner is not None:
            context.look_at_hand(looker, owner, source=self.source)


class DiscardCardsDiscardedDeltaDrawEffect(GameEffect):
    """Draw for a player the number of cards they've discarded *since a
    snapshot* — the "then draw that many cards" tail of "discard up to N
    cards, then draw that many cards" (Cathartic Pyre / Kinetic Augur /
    Daretti). Queued as the discard choice's ``then_specs`` by
    `DiscardEffect` when ``count_max`` + ``then_draw_discarded`` are set
    (ENG-37 B7), which records ``before`` (the player's
    `GameState.cards_discarded_this_turn` count) right before opening the
    interactive discard; the delta is exactly how many were actually
    discarded this way.
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
        after = int((context.state.cards_discarded_this_turn or {}).get(self.player_id, 0) or 0)
        n = after - self.before
        if n > 0:
            context.draw(player, n)


class MayDiscardThenDrawMillEffect(GameEffect):
    """"You may discard a card. If you do, draw N cards, then mill M."
    (Quintorius, History Chaser's +1, PAR-60.) A loot with a *fixed* upside
    — the sibling of `discard` with ``count_max`` + ``then_draw_discarded``
    (there the payoff equals the number discarded); here the discard is a
    single optional
    card and the payoff (``draw``/``mill``) is constant, but only if the
    player actually discarded. Snapshots `GameState.cards_discarded_this_
    turn` before opening the chooser so the tail (`DrawMillIfDiscardedEffect`)
    can tell whether a discard happened.
    """

    def __init__(
        self, draw: int = 2, mill: int = 1, source: Optional["GameObject"] = None
    ) -> None:
        super().__init__(source)
        self.draw = int(draw)
        self.mill = int(mill)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or not player.hand:
            return
        before = int((context.state.cards_discarded_this_turn or {}).get(player.id, 0) or 0)
        context.engine._request_choose_objects(
            player, list(player.hand), "discard", count=1, optional=True,
            source=self.source, prompt="Wirf eine Karte ab",
            then_specs=[{
                "type": "draw_mill_if_discarded",
                "params": {"player_id": player.id, "before": before,
                           "draw": self.draw, "mill": self.mill},
            }],
        )


class DrawMillIfDiscardedEffect(GameEffect):
    """The "if you do, draw N then mill M" tail of `MayDiscardThenDrawMill
    Effect` — fires only when the interactive discard actually removed a
    card (``cards_discarded_this_turn`` delta > 0). Draw precedes mill, as
    printed."""

    def __init__(
        self, player_id: Optional[str] = None, before: int = 0,
        draw: int = 2, mill: int = 1, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.player_id = player_id
        self.before = int(before)
        self.draw = int(draw)
        self.mill = int(mill)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        try:
            player = context.state.player_by_id(self.player_id)
        except (KeyError, ValueError):
            return
        after = int((context.state.cards_discarded_this_turn or {}).get(self.player_id, 0) or 0)
        if after - self.before <= 0:
            return
        if self.draw > 0:
            context.draw(player, self.draw)
        if self.mill > 0:
            context.mill(player, self.mill)


#: `RevealHandChooseDiscardEffect.destination` → the `choose_objects` action that moves each pick.
_HAND_PICK_ACTIONS: dict[str, str] = {
    "discard": "discard", "library_top": "hand_to_library_top", "library_third": "hand_to_library_third",
}


class RevealHandChooseDiscardEffect(GameEffect):
    """RULE 119/701.8's iconic hand-disruption template — "Target opponent
    reveals their hand. You choose a `<filter>` card from it. That player
    discards that card." (Duress/Thoughtseize/Coercion/Distress-shaped,
    one of the most repeated templates in the cache).

    "Reveals their hand" isn't a separate step to model (RULE 701.13's
    reveal is a zero-effect visibility action, and this engine has no
    client-visibility layer to update mid-resolution anyway) — the real
    behaviour is that the *chooser* is this effect's controller (the
    caster), not the revealed hand's owner, over that owner's *actual*
    cards. That's exactly `RulesEngine._request_choose_objects`'s shape
    (Tevesh Szat's sacrifice, Cloudstone Curio's bounce, …), just sourced
    from a hand instead of the battlefield, with its pre-existing
    ``action="discard"`` (`_apply_chosen_object` already resolves that
    against the *object's own owner*, regardless of who's choosing).

    ``exclude_land``/``exclude_creature`` are RULE 601.2c "non-X" card-type
    exclusions (composing — Duress's "noncreature, nonland" sets both);
    ``card_types`` is the inclusive opposite ("a creature or planeswalker
    card" — Despise-shaped). No filter at all (Coercion's bare "a card")
    leaves both unset and ``card_types`` `None`.

    ``max_mana_value`` (MEC-43 round 2, Inquisition of Kozilek — "…a
    nonland card from it with mana value 3 or less…") narrows the
    candidate pool further, same "card's own printed `converted_mana_cost`"
    read every other mana-value filter in this file uses.
    """

    def __init__(
        self,
        target_kind: str = "player",
        target: Any = None,
        source: Optional["GameObject"] = None,
        exclude_land: bool = False,
        exclude_creature: bool = False,
        card_types: Optional[list[str]] = None,
        max_mana_value: Optional[int] = None,
        optional: bool = False,
        else_specs: Optional[list[dict[str, Any]]] = None,
        count: Any = 1,
        up_to: bool = False,
        destination: str = "discard",
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind)
        self.target = target
        #: "Look at target player's hand and choose X cards from it" (Mind Warp, Extortion's "up to 2", Agonizing
        #: Memories' 2): how many the chooser takes. ``"x"`` is the spell's announced X (`_substitute_x`); ``up_to``
        #: lets the chooser stop early. Looking at a hand is a zero-effect visibility action here, as "reveals".
        self.count = count
        self.up_to = bool(up_to)
        #: What happens to each pick: ``"discard"`` (the owner discards it), ``"library_top"`` (Painful/Agonizing
        #: Memories — "put on top of that player's library", later picks end up higher: the caster's order) or
        #: ``"library_third"`` (Lost Hours — third from the top, RULE 401.7).
        self.destination = str(destination)
        self.exclude_land = exclude_land
        self.exclude_creature = exclude_creature
        self.card_types = card_types
        self.max_mana_value = max_mana_value
        #: "You **may** choose a creature or battle card from it. … If you
        #: don't, incubate 3." (Traumatic Revelation) — the chooser may
        #: decline, and ``else_specs`` (serialized `EffectSpec` dicts) then
        #: resolve instead of the discard.
        self.optional = bool(optional)
        self.else_specs = list(else_specs or [])

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def _matches(self, obj: "GameObject") -> bool:
        card = obj.card
        if self.exclude_land and obj.is_land:
            return False
        if self.exclude_creature and obj.is_creature:
            return False
        if self.card_types:
            checks = {
                "creature": obj.is_creature,
                "planeswalker": bool(getattr(obj, "is_planeswalker", False)),
                "artifact": bool(card.is_artifact),
                "instant": bool(card.is_instant),
                "sorcery": bool(card.is_sorcery),
                "enchantment": bool(card.is_enchantment),
                # "a creature or battle card" (Traumatic Revelation).
                "battle": bool(getattr(card, "is_battle", False)),
            }
            if not any(checks.get(t, False) for t in self.card_types):
                return False
        if self.max_mana_value is not None and (card.converted_mana_cost or 0) > self.max_mana_value:
            return False
        return True

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = _chosen_targets(targets, 1, self.target)
        if not chosen:
            return
        revealed_player = chosen[0]
        caster = _controller_of(self.source, context)
        if caster is None:
            return
        candidates = [obj for obj in revealed_player.hand if self._matches(obj)]
        count = max(0, int(self.count)) if not isinstance(self.count, str) else 0
        if count == 0:
            return  # "choose X cards" with X = 0
        # An empty pool still opens the (empty) choice: its "if you don't" else-branch (Traumatic Revelation) runs.
        count = max(1, min(count, len(candidates)))
        context.choose_objects(
            caster, candidates, _HAND_PICK_ACTIONS[self.destination], count=count, source=self.source,
            optional=self.optional or self.up_to,
            else_specs=self.else_specs or None,
        )


class RevealAnyNumberHandCardsEffect(GameEffect):
    """RULE 701.20's "any number" reveal — "Reveal any number of green
    cards in your hand." (Ivy Seer, Scent of Ivy, PAR-80): the reveal-from-
    hand sibling of `discard_choice`/`exile_hand_choice`
    (`RulesEngine._request_choose_objects`'s own ``"reveal"`` action), but
    the pick changes nothing (RULE 701.20 has no mechanical weight of its
    own — `RevealTopEffect`'s own docstring); only the *count* chosen
    matters, accumulated onto `GameObject.revealed_with_ids` (mirroring
    MEC-21's ``exiled_with_ids``/``"exiled_with_count"``) and read back by a
    following clause via the `continuous.count_selector`
    ``"revealed_with_count"``.

    ``count=len(candidates), optional=True`` is this codebase's established
    "any number, 0 or more" idiom (`ImprintTrackedExileEffect`'s own
    identical call). `revealed_with_ids` is cleared first so a repeatable
    ability starts fresh each activation rather than accumulating across
    uses — unlike Imprint's own accumulating list, this one is a per-use
    count with nothing else consuming it between activations.
    """

    def __init__(self, colors: Optional[list[str]] = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.colors = [str(c).upper() for c in (colors or [])]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if player is None:
            return
        source.revealed_with_ids = []
        candidates = [
            obj for obj in player.hand
            if not self.colors or any(c in obj.colors for c in self.colors)
        ]
        context.choose_objects(
            player, candidates, "reveal", count=len(candidates), optional=True,
            source=source,
        )


class RevealRandomHandCardIfNamedEffect(GameEffect):
    """Reveal one random card from an opponent's hand and discard it iff
    its name equals an earlier card-name choice.

    This is a standalone RULE 701.14/701.8 operation: ``named_card`` is a
    plain comparison value supplied by any naming effect, rather than a
    reference to one particular card or a tribal ability.  Revealing itself
    has no mutable state in this engine's non-hidden-information model.
    """

    def __init__(
        self, named_card: str = "", target_kind: str = "opponent",
        target: Any = None, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.named_card = str(named_card)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = _chosen_targets(targets, 1, self.target)
        if not chosen:
            return
        player = chosen[0]
        if not player.hand:
            return
        revealed = random.choice(player.hand)
        if revealed.name.casefold() == self.named_card.casefold():
            context.discard_specific(revealed, cause=self.source)


class RevealRandomHandCardEffect(GameEffect):
    """RULE 701.20/701.14: "Target opponent reveals a card at random from
    their hand." (Planeswalker's Favor, PAR-80) — unlike `RevealRandomHand
    CardIfNamedEffect` above, nothing happens to the pick (no discard); it
    is stashed as `GameContext.revealed_card` (the same referent
    `RevealTopEffect` sets, ``of: "revealed"``) so a following clause can
    read its mana value. Reveal has no mechanical weight of its own in this
    engine — see `RevealTopEffect`'s own docstring. Uses the game-state-
    seeded `RulesEngine.random_choice` (reproducible across a `clone()`
    undo), unlike this file's own plain ``random.choice`` above.
    """

    def __init__(
        self, target_kind: str = "opponent", target: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind)
        self.target = target

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = _chosen_targets(targets, 1, self.target)
        if not chosen:
            return
        player = chosen[0]
        context.revealed_card = context.engine.random_choice(list(player.hand))


class PutHandCardsOnTopEffect(GameEffect):
    """"Put N cards from your hand on top of your library in any order"
    (Brainstorm's back half — the same loot-shaped template other
    draw-then-filter cards this pool doesn't need yet would share). See
    `RulesEngine.put_hand_cards_on_top` for why the missing "any order"
    choice is inert at this engine's fidelity.
    """

    def __init__(self, count: int = 1, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.put_hand_cards_on_top(player, self.count)


class PutHandCardOnBottomThenDrawEffect(GameEffect):
    """"You may put a card from your hand on the bottom of your library. If
    you do, draw a card." (Volcanic Spite) — see `RulesEngine.put_hand_card_
    on_bottom_then_draw` for why the "may" is auto-taken.
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.put_hand_card_on_bottom_then_draw(player)


#: RULE 601.2c mass "destroy/exile all X" selectors (Wrath of God/Citywide
#: Bust/Farewell-shaped board wipes) — untargeted, unlike every RULE 115
#: target form above, so `DestroyEffect`/`ExileEffect` skip `target_spec`
#: entirely when one of these is set, mirroring `DealDamageEffect.selector`.
_MASS_DESTROY_SELECTORS: frozenset[str] = frozenset(
    {
        "all_creatures", "all_artifacts", "all_enchantments", "all_artifacts_and_enchantments", "all_permanents",
        "all_planeswalkers", "all_lands",
        # "destroy all Equipment attached to that creature." (Awaken the
        # Sleeper's after-tail — "that creature" is the threaten clause's
        # chosen target, `GameContext.previous_targets`). The printed "you
        # may" isn't offered as an interactive choice (documented
        # simplification — it's the opponent's Equipment about to help a
        # creature leaving your control; a `previous_target_is_equipped`
        # `ConditionalEffect` gate already skips the clause when empty).
        "equipment_attached_to_previous",
        # "return all nonland permanents with mana value X or less to their
        # owners' hands." (Displacement Wave) — `ReturnToHandEffect`'s own
        # mass-bounce sibling of the destroy/exile board wipes above.
        "all_nonland_permanents",
        # "return all blue creatures your opponents control to their
        # owners' hands." (Llawan, Cephalid Empress, MEC-43) — the
        # opponent-scoped sibling of ``all_creatures``, combined with the
        # new ``color`` ``filt`` key below rather than a wider single-word
        # scope, since no other card here needs "opponents' creatures"
        # alone yet.
        "opponents_creatures",
        # "Destroy all enchantments your opponents control." (Spring
        # Cleaning — a clash win-branch) and the artifact sibling. The
        # opponent-scoped versions of ``all_enchantments``/``all_artifacts``,
        # keyed the same "opponents_<type>" way as ``opponents_creatures``.
        "opponents_enchantments", "opponents_artifacts",
        # "exile all other permanents you control." (MEC-43 round 4D,
        # Worldgorger Dragon) — mandatory and unqualified by type, unlike
        # `ExileAnyNumberYouControlEffect`'s own "any number" *choice* among
        # the controller's other permanents (Abdel Adrian, Gorion's Ward):
        # there's no decision here at all, so it belongs with the plain
        # `_MASS_DESTROY_SELECTORS` board-wipe family instead.
        "other_permanents_you_control",
        # "Destroy all other creatures." / "…all creatures other than ~" /
        # "…all creatures except for ~" (Novablast Wurm, Magister of Worth's
        # vote branch, Mageta the Lion) — RULE 400's "other" = every
        # creature except this effect's own source, whoever controls it;
        # and the controller-scoped sibling "destroy all other creatures
        # you control" (Desolation Giant).
        "all_other_creatures", "other_creatures_you_control",
        # "Return all other nonland permanents to their owners' hands." (PAR-128,
        # Kederekt Leviathan) — `all_nonland_permanents` minus the source.
        "all_other_nonland_permanents",
    }
)


def _mass_selector_objects(
    context: GameContext, selector: str, filt: Optional[dict[str, Any]] = None,
    source: Optional["GameObject"] = None,
) -> list[Any]:
    """The battlefield objects a mass "all X [with condition]" selector
    picks — a snapshot list (the caller destroys/exiles each in turn, which
    mutates ``state.battlefield`` as it goes; iterating this separate list
    keeps that safe). ``filt`` is a small closed vocabulary of optional
    numeric conditions, all AND-combined: ``min_toughness``/``max_mana_
    value``/``min_mana_value`` (Citywide Bust/Austere Command-shaped), plus
    ``color`` (MEC-43, Llawan — a single WUBRG letter, checked against each
    candidate's `GameObject.colors`). ``source`` is only needed by the
    ``"opponents_creatures"`` selector, to know whose opponents.
    """
    # RULE 702.26c: a phased-out permanent is treated as though it doesn't
    # exist — a board wipe leaves it untouched.
    battlefield = context.state.permanents()
    if selector == "all_creatures":
        result = [o for o in battlefield if o.is_creature]
    elif selector == "all_artifacts":
        result = [o for o in battlefield if o.card.is_artifact]
    elif selector == "all_enchantments":
        result = [o for o in battlefield if o.card.is_enchantment]
    elif selector == "all_artifacts_and_enchantments":
        result = [o for o in battlefield if o.card.is_artifact or o.card.is_enchantment]
    elif selector == "all_planeswalkers":
        result = [o for o in battlefield if getattr(o, "is_planeswalker", False)]
    elif selector == "all_permanents":
        result = list(battlefield)
    elif selector == "all_lands":
        result = [o for o in battlefield if o.card.is_land]
    elif selector == "all_nonland_permanents":
        result = [o for o in battlefield if not o.card.is_land]
    elif selector == "equipment_attached_to_previous":
        # "destroy all Equipment attached to that creature." (Awaken the
        # Sleeper's own after-tail) — "that creature" is the threaten
        # clause's chosen target (`GameContext.previous_targets`).
        prev = context.previous_targets[0] if context.previous_targets else None
        pid = getattr(prev, "instance_id", None)
        result = [
            o for o in battlefield
            if pid is not None and o.attached_to == pid
            and "equipment" in (o.card.type_line or "").lower()
        ]
    elif selector == "opponents_creatures":
        controller_id = getattr(source, "controller_id", None)
        result = [
            o for o in battlefield
            if o.is_creature and controller_id is not None and o.controller_id != controller_id
        ]
    elif selector in ("opponents_enchantments", "opponents_artifacts"):
        controller_id = getattr(source, "controller_id", None)
        want = "is_enchantment" if selector.endswith("enchantments") else "is_artifact"
        result = [
            o for o in battlefield
            if getattr(o.card, want, False)
            and controller_id is not None and o.controller_id != controller_id
        ]
    elif selector == "other_permanents_you_control":
        # "exile all other permanents you control." (MEC-43 round 4D,
        # Worldgorger Dragon) — every battlefield permanent this source's
        # own controller has, minus the source itself (the printed
        # "other").
        controller_id = getattr(source, "controller_id", None)
        result = [
            o for o in battlefield
            if o is not source and controller_id is not None and o.controller_id == controller_id
        ]
    elif selector == "all_other_nonland_permanents":
        result = [o for o in battlefield if not o.card.is_land and o is not source]
    elif selector == "all_other_creatures":
        # RULE 400: "other" excludes this effect's own source, regardless
        # of who controls it (Novablast Wurm, Mageta the Lion).
        result = [o for o in battlefield if o.is_creature and o is not source]
    elif selector == "other_creatures_you_control":
        # "destroy all other creatures you control." (Desolation Giant) —
        # ``all_other_creatures`` narrowed to the source's own controller.
        controller_id = getattr(source, "controller_id", None)
        result = [
            o for o in battlefield
            if o.is_creature and o is not source
            and controller_id is not None and o.controller_id == controller_id
        ]
    else:
        result = []
    if filt:
        color = filt.get("color")
        if color:
            result = [o for o in result if str(color).upper() in (o.colors or set())]
        min_toughness = filt.get("min_toughness")
        if min_toughness is not None:
            result = [o for o in result if (o.toughness or 0) >= min_toughness]
        max_mv = filt.get("max_mana_value")
        if max_mv is not None:
            result = [o for o in result if o.card.converted_mana_cost <= max_mv]
        min_mv = filt.get("min_mana_value")
        if min_mv is not None:
            result = [o for o in result if o.card.converted_mana_cost >= min_mv]
        # "destroy all permanents with that spell's mana value." (PAR-74,
        # Celestial Kirin) — the exact-match sibling of ``max_mana_value``/
        # ``min_mana_value`` above, reading the firing SPELL_CAST event's
        # own ``mana_value`` field (PAR-71's established "that spell's mana
        # value" referent, `amount_from_trigger_event="mana_value"`'s
        # magnitude idiom applied to a mass-wipe filter instead).
        if filt.get("mana_value_from_trigger_event"):
            mv = (context.trigger_event or {}).get("mana_value")
            result = [o for o in result if mv is not None and o.card.converted_mana_cost == mv]
        # "destroy all creatures with power 3 or greater" (Dusk // Dawn/The
        # Battle of Bywater-shaped) — the power-threshold sibling of
        # ``min_toughness`` above.
        min_power = filt.get("min_power")
        if min_power is not None:
            result = [o for o in result if (o.power or 0) >= min_power]
        max_power = filt.get("max_power")
        if max_power is not None:
            result = [o for o in result if (o.power or 0) <= max_power]
        # "destroy all nonbasic lands." (Ruination-shaped) — paired with
        # ``selector="all_lands"`` rather than its own selector, the same
        # "selector picks the zone/type, filter narrows it" split every
        # other mass-wipe qualifier here uses.
        if filt.get("nonbasic"):
            result = [o for o in result if "basic" not in (o.card.type_line or "").lower()]
        # "Return all creature **tokens** / all **nontoken** creatures to
        # their owners' hands." (Perplexing Test, PAR-60) — RULE 111.9.
        if filt.get("token") is not None:
            want = bool(filt["token"])
            result = [o for o in result if bool(getattr(o, "is_token", False)) == want]
        # "Destroy all creatures that aren't enchanted." (Winds of Rath,
        # PAR-60) — an Aura attached to it makes a creature enchanted;
        # ``enchanted`` is tri-state (True keeps only enchanted, False only
        # the rest), read off the live attachment graph.
        if filt.get("enchanted") is not None:
            want = bool(filt["enchanted"])
            aura_hosts = {
                o.attached_to for o in battlefield
                if "aura" in (o.card.type_line or "").lower() and o.attached_to is not None
            }
            result = [o for o in result if (o.instance_id in aura_hosts) == want]
        # "…each nonland permanent with mana value X whose controller was dealt combat damage by this creature
        # this turn." (Steel Hellkite) — the event-derived per-source victim set
        # (`GameState.combat_damage_to_players_this_turn`), keyed by this effect's own source.
        if filt.get("controller_dealt_combat_damage_by_source"):
            victims = context.state.combat_damage_to_players_this_turn.get(getattr(source, "instance_id", None), set())
            result = [o for o in result if o.controller_id in victims]
        # "Return all attacking creatures to their owner's hand." (Aetherize) — RULE 508.1k's attacking status.
        if filt.get("attacking") is not None:
            want = bool(filt["attacking"])
            result = [o for o in result if bool(getattr(o, "attacking", False)) == want]
        subtype = filt.get("subtype")
        if subtype:
            # "exile all Nightmares." (MEC-43 round 2, Chainer, Dementia
            # Master) — delegates to `combat.matches_object_filter`'s own
            # subtype check rather than a bare type-line read, since the
            # subtype here is often *granted* (Chainer's own reanimated
            # creatures), not printed.
            from .. import combat  # local: avoid the combat<->effects import cycle

            result = [o for o in result if combat.matches_object_filter(o, {"subtype": subtype})]
    return result


def _chosen_targets(targets: Optional[list[Any]], count: int, target: Any = None) -> list[Any]:
    """RULE 115.1a "up to N target(s)" resolution: only this effect's own
    ``count`` targets, off the front of a possibly-shared list — a stack
    item's ``targets`` list is shared by every effect on it, so a
    single-target effect (``count=1``, the default) must not swallow entries
    meant for something else sharing the same cast. Falls back to an
    explicit single ``target`` (a resolve-time pronoun/self reference) only
    when no shared list was supplied at all. Shared by `DestroyEffect`,
    `ExileEffect`, `ReturnToHandEffect`, `ReturnFromGraveyardEffect`,
    `TapEffect`, `AddCountersEffect` and `DealDamageEffect`, which otherwise
    each reimplemented this identically.
    """
    if targets:
        return targets[:count]
    return [target] if target is not None else []



register(globals())
