"""Bind `AbilitySpec` data into live `GameEffect` objects (docs/09 back-end).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("RUNTIME LINKING: parse-on-load,
bind-per-game" and the two-stage compiler).

This is the parser *back-end*: it takes the pure `AbilitySpec` IR the
front-end produced and turns it into the engine's `GameEffect` objects,
using only the whitelisted `EffectRegistry`. It is the one place allowed to
bridge `parser.oracle` (pure data) and `game.effects` (behaviour).

Binding is **per game instance** (each `GameEffect` carries its own
`source`), so it runs when a `GameObject` is created — never persisted.
Unknown effect types are refused here (`BindError`) rather than executing
anything derived from card text: the security boundary from docs/09.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

from ..models.events import EventType
from ..parser.oracle.catalogue.handlers import ONCE_PER_TURN_MARKER, SORCERY_SPEED_MARKER
from ..parser.oracle.spec import AbilitySpec, EffectSpec
from .costs import parse_activation_cost
from .effects import (
    ActivatedAbility,
    AttachEffect,
    RemoveCounterOrSacrificeEffect,
    SoulbondPairEffect,
    ChooseColorReplacement,
    ChooseCreatureTypeReplacement,
    ChooseNamedModeReplacement,
    ConditionalEffect,
    EffectRegistry,
    GameEffect,
    LivingWeaponEffect,
    LoseLifeEffect,
    PumpEffect,
    RenownEffect,
    ReplacementEffect,
    ReplacementRegistry,
    SacrificeEffect,
    StaticAbility,
    TriggeredAbility,
)

#: Ability kinds `bind_ability` realizes into `GameEffect` objects. Keyword
#: abilities don't produce effects — flag keywords dock onto the object's
#: `intrinsic_keywords` in `attach_to_object` instead — so they're handled
#: there, not here.
_SUPPORTED_KINDS: frozenset[str] = frozenset(
    {"spell_effect", "triggered", "activated", "static", "replacement", "enter_replacement"}
)

#: Params that make a keyword *parametric* (kicker cost, annihilator N,
#: protection quality). Every parametric keyword's parameter is carried onto
#: `GameObject.parametric_keywords`; landwalk, annihilator/afflict/bushido
#: (`_keyword_triggered_abilities`) and equip/fortify/reconfigure
#: (`_keyword_activated_ability`) also get real behaviour wired in at bind
#: time. The rest (kicker/ward/rampage/protection quality/…) are still
#: carried-but-inert — see `ToDo_Backend.md` "Rules Engine … M2".
_PARAMETRIC_KEYWORD_KEYS: frozenset[str] = frozenset({"n", "cost", "quality"})


class BindError(ValueError):
    """A spec could not be bound to a `GameEffect` (e.g. unknown effect type)."""


def build_effects(effects: list[EffectSpec], source: Optional[Any] = None) -> list[GameEffect]:
    """Instantiate one-shot `GameEffect`s from their specs via the registry.

    Refuses any effect ``type`` the `EffectRegistry` doesn't know — nothing
    from card text ever becomes behaviour outside the whitelist.
    """
    built: list[GameEffect] = []
    for spec in effects:
        if not EffectRegistry.is_registered(spec.type):
            raise BindError(f"no registered effect for type {spec.type!r}")
        effect = EffectRegistry.create(spec.type, dict(spec.params))
        effect.source = source
        if spec.condition is not None:
            effect = ConditionalEffect(spec.condition, effect, source=source)
        built.append(effect)
    return built


def build_replacements(
    effects: list[EffectSpec], source: Optional[Any] = None
) -> list[ReplacementEffect]:
    """Instantiate `ReplacementEffect`s from their specs via the whitelist.

    A ``replacement`` `AbilitySpec` carries its family in each `EffectSpec`'s
    ``type`` (e.g. ``"prevent_damage"``) — only names in the
    `ReplacementRegistry` bind, so nothing from card text becomes an arbitrary
    callable (docs/09 security boundary)."""
    built: list[ReplacementEffect] = []
    for spec in effects:
        if not ReplacementRegistry.is_registered(spec.type):
            raise BindError(f"no registered replacement for type {spec.type!r}")
        effect = ReplacementRegistry.create(spec.type, dict(spec.params))
        effect.source = source
        built.append(effect)
    return built


#: RULE 603.1's "you control" scoping reads a different event-data key
#: depending on the event: `ENTERS_BATTLEFIELD`/`DIES` carry `controller_id`,
#: while `ATTACKS`/`BLOCKS` carry `player_id` — always that permanent's
#: controller (RULE 508.1a/509.1b — you can only attack/block with creatures
#: you control) — instead; see the firing sites in `game/game_engine.py`.
_GROUP_CONTROLLER_EVENT_KEYS: dict[str, str] = {
    "ATTACKS": "player_id",
    "BLOCKS": "player_id",
    "SPELL_CAST": "player_id",
    # "When you play another land, …" (City of Traitors) / "Untap all
    # permanents you control during each other player's untap step."
    # (Seedborn Muse) — both fire per-player events keyed by ``player_id``
    # rather than ``controller_id``.
    "LAND_PLAYED": "player_id",
    "UNTAP": "player_id",
    # "Whenever an opponent searches their library, …" (Archivist of Oghma)
    # — `RulesEngine.request_search` fires this keyed by ``player_id`` too.
    "LIBRARY_SEARCHED": "player_id",
    # "Whenever a player/an opponent mills a nonland card, …" (RULE 728's
    # Glowing One/Infesting Radroach, The Wise Mothman) — `RulesEngine.mill`
    # fires this per nonland card, keyed by whose library it came from.
    "MILL_CARD": "player_id",
    # "Whenever a creature you control deals combat damage to a player, …"
    # (RULE 120.3, Bident of Thassa/Deepfathom Skulker) — a DAMAGE event
    # names the damage's *source*, so "you control" is that source's
    # controller (`RulesEngine.deal_damage`'s ``source_controller_id``), not
    # a bare ``controller_id`` the event doesn't carry at all.
    "DAMAGE": "source_controller_id",
}

#: Which event-data key identifies *which object* an event is about — RULE
#: 603.1's "self"/"attached_permanent" subject scoping (below) matches this
#: key against an instance id. Every event `ENTERS_BATTLEFIELD`/`DIES`/
#: `ATTACKS`/`BLOCKS` fires carries ``instance_id`` (the default); `DAMAGE`
#: is the one exception — its subject (who *dealt* the damage) is
#: ``source_id`` (`RulesEngine.deal_damage`), since ``instance_id`` isn't
#: even a key that event carries.
_SUBJECT_EVENT_KEYS: dict[str, str] = {"DAMAGE": "source_id"}


def _subject_event_key(trigger: dict[str, Any]) -> str:
    return _SUBJECT_EVENT_KEYS.get(trigger.get("event"), "instance_id")


def _subject_condition(
    trigger: dict[str, Any], source: Optional[Any]
) -> Optional[Callable[[Any, Any], bool]]:
    """RULE 603.1's trigger *subject* → its predicate, from the ``condition``
    dict the oracle-text segmenter emits (`parser/oracle/segmenter.py`'s
    `_trigger_condition`) — ``None`` when the spec carries no such dict (a
    hand-authored `ability_catalogue.py` entry, or an older/synthetic spec),
    so those keep their pre-existing unscoped behaviour.

    ``{"subject": "self"}`` — the event must be about this ability's own
    source, matched by ``instance_id``. Missing ``instance_id`` on the event
    → fail-closed ``False``, never "fires for everything" (the over-firing
    bug this grammar exists to close: "when ~ enters the battlefield, draw a
    card" must not fire when *some other* permanent enters).

    ``{"subject": "group", "type", "controller", "other"}`` — the event must
    be about *some* battlefield object matching the filter: ``type`` checks
    `GameObject.type_words`, preferring the event's own ``object_types`` the
    firing site stamped at fire time (a `DIES` object has already left the
    battlefield by the time this runs, so a live lookup wouldn't see it),
    falling back to `GameState.find_object` when the event predates that
    payload (e.g. a hand-built test event); ``controller`` ``"you"`` checks
    the event's controller against the source's; ``other`` excludes the
    source's own instance (fail-closed ``False`` if the event carries no
    ``instance_id`` to check against).

    ``{"subject": "attached_permanent"}`` — RULE 303.4/301.5's "equipped/
    enchanted creature" trigger subject (Argentum Armor's "whenever
    equipped creature attacks", a Sword's "whenever equipped creature deals
    combat damage to a player"): the event must be about whatever the
    ability's own source (the Aura/Equipment) is *currently* `attached_to`
    — re-read live every check (an Equipment can move), so this naturally
    stops firing the instant it's unattached, no separate teardown needed.
    ``{"subject": "self_or_attached_permanent"}`` is the same, but also
    matches the source's own instance (Simian Sling's "whenever this
    creature or equipped creature becomes blocked" — Simian Sling is both a
    creature and, via Reconfigure, sometimes an Equipment attached to
    something else). Both read `_subject_event_key` for *which* event key
    identifies the acting object (``instance_id`` by default, ``source_id``
    for `DAMAGE`).
    """
    condition = trigger.get("condition")
    if not condition:
        return None
    subject = condition.get("subject")
    instance_id = getattr(source, "instance_id", None)
    event_key = _subject_event_key(trigger)

    if subject == "self":

        def _self_ok(event: Any, context: Any, iid=instance_id, key=event_key) -> bool:
            event_instance = event.get(key)
            return event_instance is not None and event_instance == iid

        return _self_ok

    if subject == "attached_permanent":

        def _attached_ok(event: Any, context: Any, src=source, key=event_key) -> bool:
            host_id = getattr(src, "attached_to", None)
            if host_id is None:
                return False
            event_instance = event.get(key)
            return event_instance is not None and event_instance == host_id

        return _attached_ok

    if subject == "self_or_attached_permanent":

        def _self_or_attached_ok(event: Any, context: Any, src=source, iid=instance_id, key=event_key) -> bool:
            event_instance = event.get(key)
            if event_instance is None:
                return False
            if event_instance == iid:
                return True
            return event_instance == getattr(src, "attached_to", None)

        return _self_or_attached_ok

    if subject in ("group", "self_or_group"):
        group_ok = _build_group_ok(condition, source, trigger, instance_id)
        if subject == "group":
            return group_ok

        # "self_or_group": RULE 603.1's "~ or another <group> ..." union —
        # either this ability's own source, or a matching battlefield
        # object (The Ghoul, Gunslinger). A real OR, not the usual AND-
        # composition `_trigger_condition` builds every other predicate
        # from, since RULE 603.1 wants *either* firing condition to place
        # the trigger, not both simultaneously.
        self_ok = _subject_condition({"condition": {"subject": "self"}}, source)

        def _self_or_group_ok(event: Any, context: Any, self_check=self_ok, group_check=group_ok) -> bool:
            return self_check(event, context) or group_check(event, context)

        return _self_or_group_ok

    return None


def _build_group_ok(
    condition: dict[str, Any], source: Optional[Any], trigger: dict[str, Any], instance_id: Optional[int]
) -> Callable[[Any, Any], bool]:
    """The predicate a ``{"subject": "group"}``/``"self_or_group"`` condition
    needs to check *some* matching battlefield object — shared by both
    subject kinds (`_subject_condition`), since "self_or_group" is just this
    same filter OR-ed with the self check.

    ``type`` (`_GROUP_TYPE_WORDS`, a main card type) and ``subtypes``/
    ``nontoken`` (a creature-subtype tribal filter, The Ghoul Gunslinger's
    "another nontoken Zombie or Mutant you control dies") are mutually
    exclusive per condition dict (the segmenter only ever emits one or the
    other) but both read the event's own stamped payload rather than a live
    board lookup: a DIES event's object has already left the battlefield by
    the time a trigger check runs (RULE 400.7), so `object_types`/
    ``subtypes``/``is_token`` are snapshotted onto the event at fire time
    (`RulesEngine.destroy`/`put_into_graveyard`'s DIES firing) exactly like
    ``object_types`` already was for the plain ``type`` filter.

    *Which* event key names the acting object is `_subject_event_key`'s
    call, the same one the "self"/"attached_permanent" subjects use —
    ``instance_id`` for the RULE 603.1 object-subject events, ``source_id``
    for `DAMAGE` ("whenever a creature you control deals combat damage to a
    player", RULE 120.3: the damage event names its source rather than
    stamping an ``instance_id``).
    """
    controller_id = getattr(source, "controller_id", None)
    subject_key = _subject_event_key(trigger)
    type_word = condition.get("type")
    subtypes = condition.get("subtypes")
    nontoken = bool(condition.get("nontoken"))
    wants_you = condition.get("controller") == "you"
    # "during each OTHER player's untap step" (Seedborn Muse) — the
    # mirror image of ``"you"``: the event's player must be someone
    # *besides* this ability's own controller.
    wants_not_you = condition.get("controller") == "not_you"
    other_only = bool(condition.get("other"))
    controller_key = _GROUP_CONTROLLER_EVENT_KEYS.get(trigger.get("event"), "controller_id")

    def _group_ok(
        event: Any,
        context: Any,
        iid=instance_id,
        cid=controller_id,
        tword=type_word,
        stypes=subtypes,
        want_nontoken=nontoken,
        you=wants_you,
        not_you=wants_not_you,
        other=other_only,
        ckey=controller_key,
        skey=subject_key,
    ) -> bool:
        event_instance = event.get(skey)
        if other and (event_instance is None or event_instance == iid):
            return False
        if you and event.get(ckey) != cid:
            return False
        if not_you and event.get(ckey) == cid:
            return False
        if tword and tword != "permanent":
            types = event.get("object_types")
            if types is None and event_instance is not None:
                state = getattr(context, "state", None)
                obj = state.find_object(event_instance) if state is not None else None
                types = sorted(obj.type_words) if obj is not None else None
            if not types:
                return False
            if tword.startswith("non"):
                # "whenever you tap a **nonland** permanent for mana"
                # (Kinnan) — a negated main type, the only shape the
                # positive `tword in types` test can't express.
                if tword[3:] in types:
                    return False
            elif tword not in types:
                return False
        if stypes:
            if want_nontoken and event.get("is_token"):
                return False
            event_subtypes = event.get("subtypes")
            if event_subtypes is None and event_instance is not None:
                state = getattr(context, "state", None)
                obj = state.find_object(event_instance) if state is not None else None
                event_subtypes = _card_subtypes(obj.card) if obj is not None else None
            if not event_subtypes or not any(s in event_subtypes for s in stypes):
                return False
        return True

    return _group_ok


def _card_subtypes(card: Any) -> list[str]:
    """Lowercase subtype words after a printed type line's em dash."""
    type_line = str(getattr(card, "type_line", "") or "")
    return type_line.partition("—")[2].strip().lower().split()


def _trigger_condition(
    trigger: dict[str, Any], source: Optional[Any]
) -> Optional[Callable[[Any, Any], bool]]:
    """The extra `TriggeredAbility.check_trigger` predicate a trigger spec needs.

    Composes independent predicates so a trigger can be scoped by any
    combination the spec sets:

    * ``"condition"`` — RULE 603.1's trigger subject ("self" or a "group"
      filter), the oracle-text segmenter's own scoping — see
      `_subject_condition`.
    * ``"chapter"`` — a Saga (or Class) chapter/level ability must fire only
      for *its own* source (scoped by the event's ``instance_id``, the same
      convention `continuous._granted_trigger_condition` uses) and only at
      the specific counter number(s) its chapter/level line names — a single
      ``SAGA_CHAPTER``/``CLASS_LEVEL`` event otherwise looks identical for
      every instance on the battlefield and every chapter/level on the card.
    * ``"min_level"``/``"max_level"``/``"level_counter"`` — a Leveler tier's
      own triggered ability (RULE 711, e.g. "whenever ~ attacks, it gets
      +1/+0" restricted to ``LEVEL 2-6``) must fire only while the source's
      own counter (``level`` by default) is currently in that tier's range —
      unlike ``chapter``, this checks the source's *current* state, not the
      triggering event's payload.
    * ``"filter"`` — a small exact-match dict AND-ed onto the event's own
      payload (``{k: v}`` means ``event.get(k) == v``). Exists so a single
      broad `EventType` can drive several genuinely different triggers: RULE
      120.3's "deals combat damage to a player" (Sword-cycle/Bloodforged
      Battle-Axe/Rogue's Gloves-shaped) is just `EventType.DAMAGE` filtered
      to ``{"combat": True, "is_player": True}`` — Kaldra Compleat's "deals
      combat damage to a *creature*" is the same event with ``{"combat":
      True, "is_player": False}`` instead. Both fields are only reliably
      present on the event `RulesEngine.deal_damage` broadcasts (see its
      ``copy_with`` comment) — a hand-built/older event missing a filtered
      key fails closed (``None != True``), never over-fires.
    """
    predicates: list[Callable[[Any, Any], bool]] = []

    subject_ok = _subject_condition(trigger, source)
    if subject_ok is not None:
        predicates.append(subject_ok)

    filt = trigger.get("filter")
    if filt:
        def _filter_ok(event: Any, context: Any, f=dict(filt)) -> bool:
            return all(event.get(k) == v for k, v in f.items())

        predicates.append(_filter_ok)

    # "Whenever an equipped creature you control attacks …" (Akiri, Fearless
    # Voyager, simplified — see its catalogue entry) — the ability's own
    # source must itself have an Equipment currently attached to it. Reads
    # the board fresh every check (like `attached_permanent` does the other
    # direction), so it naturally stops applying the instant nothing's
    # attached anymore.
    if trigger.get("requires_equipped"):
        instance_id = getattr(source, "instance_id", None)

        def _equipped_ok(event: Any, context: Any, iid=instance_id) -> bool:
            state = getattr(context, "state", None)
            if state is None or iid is None:
                return False
            return any(
                o.attached_to == iid and "equipment" in o.card.type_line.lower()
                for o in state.battlefield
            )

        predicates.append(_equipped_ok)

    # "Whenever you cast an Aura, Equipment, or Vehicle spell, …" (Sram,
    # Senior Edificer) — a card-*subtype* filter, unlike `"filter"`'s exact
    # key/value match: subtypes ("Equipment"/"Aura"/"Vehicle") live after the
    # type line's em dash, so they're never in a `"group"` condition's
    # `object_types` (main types only) — this reads the live object's
    # printed type line directly instead.
    # "Whenever an opponent casts an **instant or sorcery** spell, …"
    # (Wandering Archaic) — a main-card-type filter on a `SPELL_CAST` event.
    # The `"group"` condition's own ``type`` key takes a single type word;
    # this is the OR-of-several form, read off the event's stamped
    # ``object_types`` exactly the same way.
    spell_card_types = trigger.get("spell_card_types")
    if spell_card_types:
        wanted_types = tuple(str(t).lower() for t in spell_card_types)

        def _spell_type_ok(event: Any, context: Any, words=wanted_types) -> bool:
            types = event.get("object_types") or ()
            return any(w in types for w in words)

        predicates.append(_spell_type_ok)

    subtype_any = trigger.get("spell_subtype_any")
    if subtype_any:
        wanted = tuple(str(s).lower() for s in subtype_any)

        def _subtype_ok(event: Any, context: Any, words=wanted) -> bool:
            state = getattr(context, "state", None)
            instance_id = event.get("instance_id")
            if state is None or instance_id is None:
                return False
            obj = state.find_object(instance_id)
            if obj is None:
                return False
            type_line = (obj.card.type_line or "").lower()
            return any(w in type_line for w in words)

        predicates.append(_subtype_ok)

    # "… if it's not that player's turn, …" (Price of Glory) — the player the
    # event is about (its ``controller_id``, the one who tapped the land) must
    # not be the active player. A RULE 603.4 intervening-if scoped to the
    # triggering player rather than the ability's own controller, so it reads
    # the event's controller key (the same one `"group"` scoping uses) against
    # the live active player each check.
    # "At the beginning of your/each opponent's <step>, …" (RULE 500.7,
    # `segmenter._PHASE_TRIGGER_RE`) — unlike RULE 603.1's object-subject
    # events, a `STEP_BEGIN` event carries no controller of its own to key
    # off, so this checks whose turn it currently is against the ability's
    # own source's controller instead of an event field.
    phase_relation = trigger.get("phase_relation")
    if phase_relation in ("you", "not_you"):
        controller_id = getattr(source, "controller_id", None)

        def _phase_relation_ok(event: Any, context: Any, cid=controller_id, rel=phase_relation) -> bool:
            state = getattr(context, "state", None)
            active = getattr(state, "active_player", None) if state is not None else None
            if active is None:
                return False
            is_yours = active.id == cid
            return is_yours if rel == "you" else not is_yours

        predicates.append(_phase_relation_ok)

    # "… if this artifact is tapped, …" (Mana Vault's draw-step ping) — a
    # RULE 603.4 intervening-if about the ability's **own source's** current
    # state, rather than the event or whose turn it is. Checked live at
    # trigger time (and again at resolution by the rules' own intervening-if
    # re-check, if a card ever needs that); a source that has left the
    # battlefield fails closed.
    source_state = trigger.get("source_state")
    if source_state in ("tapped", "untapped"):
        instance_id = getattr(source, "instance_id", None)

        def _source_state_ok(event: Any, context: Any, iid=instance_id, want=source_state) -> bool:
            state = getattr(context, "state", None)
            obj = state.find_object(iid) if state is not None and iid is not None else None
            if obj is None:
                return False
            return bool(obj.tapped) == (want == "tapped")

        predicates.append(_source_state_ok)

    if trigger.get("not_controllers_turn"):
        controller_key = _GROUP_CONTROLLER_EVENT_KEYS.get(trigger.get("event"), "controller_id")

        def _not_their_turn(event: Any, context: Any, ckey=controller_key) -> bool:
            state = getattr(context, "state", None)
            if state is None:
                return False
            actor = event.get(ckey)
            return actor is not None and actor != state.active_player.id

        predicates.append(_not_their_turn)

    chapters = trigger.get("chapter")
    if chapters:
        chapter_set = frozenset(chapters)
        instance_id = getattr(source, "instance_id", None)

        def _chapter_ok(event: Any, context: Any, iid=instance_id, cs=chapter_set) -> bool:
            return event.get("instance_id") == iid and event.get("chapter") in cs

        predicates.append(_chapter_ok)

    min_level = trigger.get("min_level")
    max_level = trigger.get("max_level")
    if min_level is not None or max_level is not None:
        counter_kind = trigger.get("level_counter") or "level"

        def _level_ok(event: Any, context: Any, kind=counter_kind, lo=min_level, hi=max_level) -> bool:
            n = getattr(source, "counters", {}).get(kind, 0)
            return (lo is None or n >= lo) and (hi is None or n <= hi)

        predicates.append(_level_ok)

    # "Brotherhood — ..."/"Enclave — ..." (Struggle for Project Purity's
    # own "as this enters, choose Brotherhood or Enclave" — `ChooseNamedModeReplacement`)
    # — this ability only actually fires once its source's own chosen mode
    # (a lowercase slug of the printed label, `RulesEngine.resolve_enter_
    # choice`) matches. Checked live off the source each firing (like every
    # other predicate here), never baked in at bind time, since the choice
    # happens at ETB — after bind-on-load already built this ability.
    named_mode = trigger.get("named_mode")
    if named_mode:

        def _named_mode_ok(event: Any, context: Any, src=source, mode=named_mode) -> bool:
            return getattr(src, "chosen_mode", None) == mode

        predicates.append(_named_mode_ok)

    if not predicates:
        return None
    if len(predicates) == 1:
        return predicates[0]

    def _all(event: Any, context: Any) -> bool:
        return all(p(event, context) for p in predicates)

    return _all


def bind_ability(
    spec: AbilitySpec, source: Optional[Any] = None
) -> Union[list[GameEffect], list[ReplacementEffect], TriggeredAbility, list[TriggeredAbility], ActivatedAbility]:
    """Bind one validated `AbilitySpec` into its engine representation.

    Returns:
      * ``spell_effect`` → the list of one-shot effects (goes on a spell's
        ``spell_effects`` / a stack item),
      * ``triggered``    → a `TriggeredAbility`, or a *list* of them for a
        compound multi-event trigger ("~ enters or attacks" — see
        `_SELF_MULTI_EVENT_RE`'s docstring in the segmenter),
      * ``static``       → the list of `StaticAbility` effects,
      * ``replacement``  → the list of `ReplacementEffect`s,
      * ``enter_replacement`` → the list of `EnterAsCopyReplacement`/
        `ChooseCreatureTypeReplacement`/`ChooseColorReplacement`-style
        effects (RULE 614.1c/614.12/601.2b "as ~ enters" — a different family
        from ``replacement``'s event-transform `ReplacementEffect`s, bound
        through `EffectRegistry` instead of `ReplacementRegistry`; routed
        onto `GameObject.enter_as_copy_effects`/``enter_choice_effects`` by
        `attach_to_object`, see its ``enter_replacement`` branch),
      * ``activated``    → an `ActivatedAbility`.

    ``source`` is the `GameObject` the ability belongs to (used as each
    effect's source and to default a trigger's controller).
    """
    spec.validate()
    if spec.ability_kind not in _SUPPORTED_KINDS:
        raise BindError(f"binder does not support ability_kind {spec.ability_kind!r} yet")

    if spec.ability_kind == "replacement":
        # A different whitelist (ReplacementRegistry, not EffectRegistry) —
        # each `EffectSpec.type` here names a replacement family (e.g.
        # "prevent_damage"), not a one-shot effect.
        replacements = build_replacements(spec.effects, source)
        for effect in replacements:
            if not effect.description:
                effect.description = spec.raw_text
        return replacements

    if spec.ability_kind == "enter_replacement":
        # RULE 614.1c/614.12: bound through `EffectRegistry` (unlike
        # "replacement"'s `ReplacementRegistry`) since these aren't pure
        # event-transform `ReplacementEffect`s.
        effects = build_effects(spec.effects, source)
        for effect in effects:
            if not effect.description:
                effect.description = spec.raw_text
        return effects

    # "Activate only once each turn." (Quirion Ranger/Scryb Ranger-shaped) —
    # `catalogue.handlers`'s once-per-turn handler claims the clause as a
    # marker `EffectSpec` (`ONCE_PER_TURN_MARKER`) rather than a real
    # one-shot effect, since it isn't one; strip it here before building real
    # effects and fold it into `ActivatedAbility.once_per_turn` instead
    # (mirroring `TriggeredAbility.once_per_turn`'s RULE 603.2 stamp).
    once_per_turn = False
    sorcery_speed_only = False
    effect_specs = spec.effects
    if spec.ability_kind == "activated":
        if any(e.type == ONCE_PER_TURN_MARKER for e in effect_specs):
            once_per_turn = True
        if any(e.type == SORCERY_SPEED_MARKER for e in effect_specs):
            sorcery_speed_only = True
        # Strip both timing/cap markers before building real effects (RULE
        # 602.5d / 603.2) — each is folded into the ActivatedAbility/cost, not
        # a GameEffect.
        effect_specs = [
            e for e in effect_specs
            if e.type not in (ONCE_PER_TURN_MARKER, SORCERY_SPEED_MARKER)
        ]

    effects = build_effects(effect_specs, source)

    if spec.ability_kind == "spell_effect":
        return effects

    if spec.ability_kind == "triggered":
        assert spec.trigger is not None  # validate() guarantees this
        modes = _build_mode_entries(spec.modes, source) if spec.modes else None
        trigger_event = spec.trigger["event"]

        def _one(event: str, own_effects: list[GameEffect]) -> TriggeredAbility:
            # `_trigger_condition`/`_subject_event_key` key off *this
            # specific* event (e.g. DAMAGE's subject key differs from every
            # other event's) — computed per-event via a single-event trigger
            # dict, never off the original (possibly list-valued) ``event``
            # key, which `_SUBJECT_EVENT_KEYS.get(...)` can't hash anyway.
            single_trigger = {**spec.trigger, "event": event}
            return TriggeredAbility(
                trigger_event=event,
                effects=own_effects,
                modes=modes,
                modes_or_both=bool(spec.modes.get("or_both", False)) if spec.modes else False,
                modes_choose=int(spec.modes.get("choose", 1)) if spec.modes else 1,
                modes_at_least=bool(spec.modes.get("at_least", False)) if spec.modes else False,
                condition=_trigger_condition(single_trigger, source),
                optional=spec.optional,
                controller_id=getattr(source, "controller_id", None),
                source=source,
                description=spec.raw_text,
                reflexive=bool(spec.trigger.get("reflexive", False)),
                # RULE 605.1b/605.4: a triggered *mana* ability resolves
                # immediately instead of using the stack (Wild Growth,
                # Kinnan) — see `TriggeredAbility.mana_ability`.
                mana_ability=bool(spec.trigger.get("mana_ability", False)),
            )

        if isinstance(trigger_event, list):
            # RULE 603.1's compound "~ enters or attacks" (The Wise Mothman,
            # `parser.oracle.segmenter._SELF_MULTI_EVENT_RE`) — one
            # `TriggeredAbility` per listed event, each with its own freshly
            # bound effects (never sharing effect instances/state across
            # the two abilities). `attach_to_object` extends
            # `triggered_abilities` with this list instead of appending a
            # single ability.
            return [_one(evt, build_effects(effect_specs, source)) for evt in trigger_event]
        return _one(trigger_event, effects)

    if spec.ability_kind == "static":
        # Each effect is a `StaticAbility` (from the anthem/grant_keyword/…
        # registry factories); the continuous-effects engine reads them off
        # the battlefield. Label any that arrived without their own text.
        for effect in effects:
            if isinstance(effect, StaticAbility) and not effect.description:
                effect.description = spec.raw_text
        return effects

    # activated: recognize the full cost (mana, {T}/{Q}, sacrifice, pay life,
    # discard, remove counters) from the spec's cost dict / text.
    cost = parse_activation_cost(spec.cost)
    if sorcery_speed_only:
        # RULE 602.5d — the "Activate only as a sorcery" body marker folds into
        # the cost's timing flag (`can_activate` already enforces it).
        cost.sorcery_speed_only = True
    return ActivatedAbility(
        effects=effects,
        cost=cost,
        source=source,
        description=spec.raw_text,
        once_per_turn=once_per_turn,
    )


def attach_keyword(obj: Any, spec: AbilitySpec) -> bool:
    """Dock a ``keyword`` spec onto the object (RULE 702).

    Returns ``True`` if the keyword was docked. Flag (parameterless) keywords —
    ``flying``, ``deathtouch``, … — join ``obj.intrinsic_keywords``, where the
    combat engine reads them. Parametric keywords are also docked now, each in
    the form the engine that consumes it expects:

    * **landwalk** (``{"name": "landwalk", "quality": "island"}``) → the
      specific variant slug ``"islandwalk"`` joins ``intrinsic_keywords``,
      which `combat.landwalk_subtypes` reads (RULE 702.14);
    * every parametric keyword's full parameter is also kept on
      ``obj.parametric_keywords`` (``name`` → ``{n|cost|quality}``) so the
      cost/combat-math consumers (kicker, annihilator, ward, protection
      quality) can read it — a carried record, behaviour where wired.
    """
    spec.validate()
    keyword = spec.keyword or {}
    name = keyword.get("name")
    if not name:
        return False
    if not hasattr(obj, "intrinsic_keywords"):
        obj.intrinsic_keywords = set()

    is_parametric = bool(_PARAMETRIC_KEYWORD_KEYS & keyword.keys())
    if not is_parametric:
        obj.intrinsic_keywords.add(str(name))
        return True

    # Parametric: keep the parameter, and dock the shape combat/cost expects.
    params = {k: v for k, v in keyword.items() if k != "name"}
    if not hasattr(obj, "parametric_keywords"):
        obj.parametric_keywords = {}
    obj.parametric_keywords[str(name)] = params
    if name == "landwalk" and keyword.get("quality"):
        # e.g. "island" → the "islandwalk" slug the combat engine recognizes.
        variant = str(keyword["quality"]).strip().lower().split()[0]
        obj.intrinsic_keywords.add(f"{variant}walk")
    return True


def _keyword_activated_ability(obj: Any, spec: AbilitySpec) -> Optional[ActivatedAbility]:
    """Create a live activated ability for attach-style keywords like Equip."""
    keyword = spec.keyword or {}
    name = str(keyword.get("name") or "")
    if name not in {"equip", "fortify", "reconfigure"}:
        return None

    cost_text = keyword.get("cost") or "{0}"
    target_kind = "permanent"
    # RULE 301.5c/306.2/702.151b: none of Equip/Fortify/Reconfigure tap the
    # source as part of their cost — it's exactly the printed cost, payable
    # (and re-payable) any number of times at sorcery speed. Don't graft a
    # {T} onto it: that would tap the permanent and block re-activation.
    cost = parse_activation_cost(cost_text)
    return ActivatedAbility(
        effects=[AttachEffect(target_kind=target_kind)],
        cost=cost,
        source=obj,
        description=spec.raw_text or f"{name}"
    )


def _self_only_condition(instance_id: Optional[int]) -> Callable[[Any, Any], bool]:
    """A trigger condition matching only events about ``instance_id`` itself —
    the same "self" scoping `_subject_condition` gives an oracle-parsed
    trigger, for the hand-synthesized combat-math keyword abilities below
    (which carry no oracle-text ``condition`` dict to read one from)."""

    def _check(event: Any, context: Any, iid=instance_id) -> bool:
        return event.get("instance_id") == iid

    return _check


def _other_creature_you_control_condition(obj: Any) -> Callable[[Any, Any], bool]:
    """RULE 702.94a's other half: an event about some *other* creature this
    object's controller controls — what makes Soulbond fire "when **either**
    enters", not just when the Soulbond creature itself does."""
    instance_id = getattr(obj, "instance_id", None)
    controller_id = getattr(obj, "controller_id", None)

    def _check(event: Any, context: Any, iid=instance_id, cid=controller_id) -> bool:
        event_instance = event.get("instance_id")
        if event_instance is None or event_instance == iid:
            return False
        if event.get("controller_id") != cid:
            return False
        state = getattr(context, "state", None)
        other = state.find_object(event_instance) if state is not None else None
        return other is not None and other.is_creature

    return _check


def _keyword_triggered_abilities(obj: Any, spec: AbilitySpec) -> list[TriggeredAbility]:
    """Synthesize real triggered abilities for combat-math keywords whose
    RULE 702 text *is* a triggered ability — annihilator (702.86), afflict
    (702.130), bushido (702.45) — mirroring `_keyword_activated_ability`'s
    Equip/Fortify/Reconfigure treatment: these route through the ordinary
    stack/priority/response pipeline like any parsed "when ~ attacks..."
    trigger, rather than being special-cased procedurally in `game/combat.py`
    alongside the purely-static evasion keywords (flying, trample, ...),
    since a player can actually respond to any of the three.

    Rampage (702.23) is deliberately *not* built here: its pump amount
    scales with the *specific* block's final blocker count, which a
    bind-on-load `TriggeredAbility` (one fixed `effects` list, reused for
    every firing) can't carry. It's built directly instead — the identical
    "per-firing dynamic amount" problem Ward solves the same way — by
    `RulesEngine.check_rampage`, called from `GameEngine.declare_blockers`
    right where `BECOMES_BLOCKED` fires (which already carries a
    `blocker_count` payload for exactly this).

    Living Weapon (702.92, a flag keyword — no ``n``) and Renown (702.112,
    parametric) are also synthesized here rather than left to the oracle-text
    front-end: both need real behaviour beyond what a plain `AbilitySpec`
    trigger can express (Living Weapon's "attach to the token *this same
    ability* just created"; Renown's "if it isn't renowned" one-time guard),
    the same category of "needs an actual Python condition/atomic effect"
    case docs/11 §8 calls out.
    """
    keyword = spec.keyword or {}
    name = str(keyword.get("name") or "")

    if name == "soulbond":
        # RULE 702.94a: "You may pair this creature with another unpaired
        # creature when *either* enters." Two abilities, not one — the pair
        # can form when this creature arrives *or* when a later unpaired
        # creature joins it — but both do the same thing, so the second is
        # just the same effect with a group subject instead of a self one.
        return [
            TriggeredAbility(
                trigger_event=EventType.ENTERS_BATTLEFIELD,
                effects=[SoulbondPairEffect(source=obj)],
                condition=_self_only_condition(getattr(obj, "instance_id", None)),
                optional=True,
                controller_id=getattr(obj, "controller_id", None),
                source=obj,
                description=spec.raw_text or "Soulbond",
            ),
            TriggeredAbility(
                trigger_event=EventType.ENTERS_BATTLEFIELD,
                effects=[SoulbondPairEffect(source=obj)],
                condition=_other_creature_you_control_condition(obj),
                optional=True,
                controller_id=getattr(obj, "controller_id", None),
                source=obj,
                description=spec.raw_text or "Soulbond",
            ),
        ]

    if name == "living_weapon":
        return [
            TriggeredAbility(
                trigger_event=EventType.ENTERS_BATTLEFIELD,
                effects=[LivingWeaponEffect(source=obj)],
                condition=_self_only_condition(getattr(obj, "instance_id", None)),
                source=obj,
                description=spec.raw_text or "Living weapon",
            )
        ]

    n = keyword.get("n")
    if name == "fading" and n is not None:
        # RULE 702.32b: "At the beginning of your upkeep, remove a fade
        # counter from this permanent. If you can't, sacrifice it." The
        # entry counters themselves (RULE 702.32a) are placed by
        # `RulesEngine._apply_entry_counters`, alongside every other
        # enters-with-counters clause.
        controller_id = getattr(obj, "controller_id", None)

        def _your_upkeep(event: Any, context: Any, cid=controller_id) -> bool:
            if event.get("step") != "upkeep":
                return False
            state = getattr(context, "state", None)
            active = getattr(state, "active_player", None) if state is not None else None
            return active is not None and active.id == cid

        return [
            TriggeredAbility(
                trigger_event=EventType.STEP_BEGIN,
                effects=[RemoveCounterOrSacrificeEffect(kind="fade", source=obj)],
                condition=_your_upkeep,
                controller_id=controller_id,
                source=obj,
                description=spec.raw_text or f"Fading {n}",
            )
        ]

    if name == "renown" and n is not None:
        instance_id = getattr(obj, "instance_id", None)

        def _renown_ok(event: Any, context: Any, obj=obj, iid=instance_id) -> bool:
            if event.get("source_id") != iid:
                return False
            if not event.get("combat") or not event.get("is_player"):
                return False
            return not getattr(obj, "renowned", False)

        return [
            TriggeredAbility(
                trigger_event=EventType.DAMAGE,
                effects=[RenownEffect(amount=int(n), source=obj)],
                condition=_renown_ok,
                source=obj,
                description=spec.raw_text or f"Renown {n}",
            )
        ]

    if n is None:
        return []
    n = int(n)
    condition = _self_only_condition(getattr(obj, "instance_id", None))

    if name == "annihilator":
        return [
            TriggeredAbility(
                trigger_event=EventType.ATTACKS,
                effects=[SacrificeEffect(count=n, selector="defending_player")],
                condition=condition,
                source=obj,
                description=spec.raw_text or f"Annihilator {n}",
            )
        ]
    if name == "afflict":
        return [
            TriggeredAbility(
                trigger_event=EventType.BECOMES_BLOCKED,
                effects=[LoseLifeEffect(amount=n, selector="defending_player")],
                condition=condition,
                source=obj,
                description=spec.raw_text or f"Afflict {n}",
            )
        ]
    if name == "bushido":
        # RULE 702.45a: bushido triggers both when this creature blocks
        # (BLOCKS, this object as the blocker) and when it becomes blocked
        # (BECOMES_BLOCKED, this object as the attacker) — two abilities,
        # each pumping only in the combat where its own event fired.
        return [
            TriggeredAbility(
                trigger_event=EventType.BLOCKS,
                effects=[PumpEffect(power=n, toughness=n)],
                condition=condition,
                source=obj,
                description=spec.raw_text or f"Bushido {n}",
            ),
            TriggeredAbility(
                trigger_event=EventType.BECOMES_BLOCKED,
                effects=[PumpEffect(power=n, toughness=n)],
                condition=condition,
                source=obj,
                description=spec.raw_text or f"Bushido {n}",
            ),
        ]
    return []


def _build_mode_entries(modes: dict[str, Any], source: Any) -> list[dict[str, Any]]:
    """Bind each mode's effects (RULE 700.2) into ``{"effects": [GameEffect,
    ...], "description": str}`` entries, one per printed mode — shared by a
    modal spell's ``obj.spell_modes`` (`_attach_modes`) and a modal
    triggered ability's own ``TriggeredAbility.modes``
    (`bind_ability`'s ``triggered`` branch)."""
    return [
        {"effects": build_effects(option, source), "description": description}
        for option, description in zip(
            modes.get("options", []), modes.get("descriptions") or []
        )
    ]


def _attach_modes(obj: Any, modes: dict[str, Any]) -> None:
    """Bind a modal spell's "Choose one —" options onto ``obj`` (RULE 700.2).

    Each option becomes its own entry in ``obj.spell_modes`` — a flat list
    of ``{"effects": [GameEffect, ...], "description": str}`` dicts, one
    per printed mode — plus ``obj.spell_modes_or_both`` (RULE 700.2e) and
    ``obj.spell_modes_choose`` (RULE 700.2's "choose *N* —", ``1`` for the
    ordinary case). ``obj.spell_modes_at_least`` (RULE 700.2's "choose *N*
    or more —", Farewell-shaped) makes ``spell_modes_choose`` a minimum
    rather than an exact count. The engine (`game/game_engine.py`) offers
    one cast action per *legal combination* of ``spell_modes_choose`` modes
    (every size from ``spell_modes_choose`` to all modes when
    ``spell_modes_at_least``; plus a combined "both" action when ``or_both``
    is set, for the ``choose == 1`` binary case, or when ``entwine`` (RULE
    702.42) prices one) — the same per-face-offer
    treatment MDFC/Adventure casting already uses; casting temporarily swaps
    `obj.spell_effects` to the chosen mode(s) so the existing targeting/
    resolution machinery (which reads that attribute) needs no change to be
    modal-aware.
    """
    entries = _build_mode_entries(modes, obj)
    existing = list(getattr(obj, "spell_modes", None) or [])
    obj.spell_modes = existing + entries
    obj.spell_modes_or_both = bool(modes.get("or_both", False))
    obj.spell_modes_choose = int(modes.get("choose", 1))
    obj.spell_modes_at_least = bool(modes.get("at_least", False))
    # RULE 702.42a Entwine: the raw mana cost that upgrades "choose one" to
    # "choose all". Read by `GameEngine._entwine_cost` — the "both" offer it
    # unlocks is priced (and lockable), unlike ``spell_modes_or_both``'s.
    entwine = modes.get("entwine")
    obj.spell_modes_entwine = str(entwine) if entwine else None


def attach_to_object(obj: Any, specs: list[AbilitySpec]) -> None:
    """Bind each spec and attach it to the `GameObject`'s effect lists.

    ``spell_effect`` specs populate ``obj.spell_effects`` (the hook
    `RulesEngine._effects_for_spell` reads when the spell resolves) — or,
    for a modal spell (RULE 700.2, a ``modes`` block), ``obj.spell_modes``
    instead/as well (see `_attach_modes`); ``triggered``/``activated`` go on
    the matching `GameObject` ability list; ``static``/``replacement``
    extend the matching effect list; ``keyword`` specs dock onto
    ``obj.intrinsic_keywords`` (flag keywords).

    RULE 601.2b/604.3's "as an additional cost to cast this spell, <cost>."
    is its own oracle-text line — the parser emits it as a standalone spec
    carrying no effects of its own (`parser/oracle/segmenter.py`), so it's
    picked up here by scanning every spec for ``additional_cost`` rather than
    by whichever spec happens to carry the spell's "real" effects, keeping
    the parser/binder split simple regardless of line order on the card.

    ``impulsive_draw_on_combat_damage``/``rebound``/``counter_death_return``/
    ``rad_counters_on_combat_damage``/``mill_return_from_graveyard`` are the
    same "scan every spec" idiom, for hand-authored markers with no effects
    of their own (RULE 603.4-style per-firing data — see `AbilitySpec`'s
    docstring for each field, and `RulesEngine._collect_impulsive_draw_
    triggers`/`_collect_counter_death_return_triggers`/`_collect_rad_
    counter_damage_triggers`/`_collect_mill_return_from_graveyard_triggers`,
    `cast_spell`/`resolve_top_of_stack` for ``rebound``).
    """
    for spec in specs:
        if spec.additional_cost:
            spec.validate()
            obj.additional_cast_cost = parse_activation_cost(spec.additional_cost)
        if spec.conditional_flash:
            spec.validate()
            obj.conditional_flash = spec.conditional_flash
        if spec.free_cast_condition:
            spec.validate()
            obj.free_cast_condition = spec.free_cast_condition
        if spec.impulsive_draw_on_combat_damage:
            spec.validate()
            obj.impulsive_draw_on_combat_damage = dict(spec.impulsive_draw_on_combat_damage)
        if spec.rebound:
            spec.validate()
            obj.has_rebound = True
        if spec.counter_death_return:
            spec.validate()
            obj.counter_death_return = dict(spec.counter_death_return)
        if spec.rad_counters_on_combat_damage:
            spec.validate()
            obj.rad_counters_on_combat_damage = dict(spec.rad_counters_on_combat_damage)
        if spec.rad_counters_on_attacked:
            spec.validate()
            obj.rad_counters_on_attacked = dict(spec.rad_counters_on_attacked)
        if spec.mill_return_from_graveyard:
            spec.validate()
            obj.mill_return_from_graveyard = True
        if spec.ability_kind == "keyword":
            attach_keyword(obj, spec)
            keyword_ability = _keyword_activated_ability(obj, spec)
            if keyword_ability is not None:
                obj.activated_abilities.append(keyword_ability)
            obj.triggered_abilities.extend(_keyword_triggered_abilities(obj, spec))
            continue
        bound = bind_ability(spec, source=obj)
        if spec.ability_kind == "spell_effect":
            existing = list(getattr(obj, "spell_effects", []))
            obj.spell_effects = existing + bound  # type: ignore[union-attr]
            if spec.modes:
                _attach_modes(obj, spec.modes)
        elif spec.ability_kind == "triggered":
            # A compound multi-event trigger ("~ enters or attacks") binds
            # to a *list* of `TriggeredAbility` (one per event) instead of
            # one (`bind_ability`'s ``triggered`` branch) — extend rather
            # than append in that case.
            if isinstance(bound, list):
                obj.triggered_abilities.extend(bound)
            else:
                obj.triggered_abilities.append(bound)
        elif spec.ability_kind == "activated":
            obj.activated_abilities.append(bound)
        elif spec.ability_kind == "static":
            obj.static_effects.extend(bound)
        elif spec.ability_kind == "replacement":
            obj.replacement_effects.extend(bound)
        elif spec.ability_kind == "enter_replacement":
            # Two different families share this ability_kind (docs/09):
            # `EnterAsCopyReplacement` (RULE 614.1c/614.12, target-choosing)
            # goes on `enter_as_copy_effects`; the "as ~ enters, choose a
            # creature type/color" pair (RULE 601.2b, no target at all) goes
            # on `enter_choice_effects` instead — `RulesEngine._resolve_
            # permanent_spell` offers both in turn before battlefield entry.
            for effect in bound:
                if isinstance(
                    effect, (ChooseCreatureTypeReplacement, ChooseColorReplacement, ChooseNamedModeReplacement)
                ):
                    obj.enter_choice_effects.append(effect)
                else:
                    obj.enter_as_copy_effects.append(effect)
        else:  # pragma: no cover - bind_ability already refused it
            raise BindError(f"cannot attach ability_kind {spec.ability_kind!r}")


def bind_from_catalogue(obj: Any) -> None:
    """Bind a `GameObject`'s abilities from the catalogue (bind-on-load).

    The single hook the game builder calls for every object it creates, so a
    card's activated/triggered/static abilities are live the moment it exists —
    the "binding on load" that connects card text to behaviour. A no-op for a
    card with no known specs. Import is function-local to avoid an import cycle
    (`ability_catalogue` builds specs, this module binds them)."""
    from .ability_catalogue import specs_for

    specs = specs_for(getattr(obj, "card", None))
    if specs:
        attach_to_object(obj, specs)
