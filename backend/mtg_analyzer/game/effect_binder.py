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
from ..models.mana_cost import ManaCost
from ..parser.oracle.catalogue.handlers import (
    ACTIVATION_CONDITION_MARKER,
    ONCE_PER_TURN_MARKER,
    ONLY_DURING_YOUR_TURN_MARKER,
    SORCERY_SPEED_MARKER,
)
from ..parser.oracle.spec import AbilitySpec, EffectSpec
from .costs import parse_activation_cost
from .effects import (
    ActivatedAbility,
    AttachEffect,
    CumulativeUpkeepEffect,
    RemoveCounterOrSacrificeEffect,
    SoulbondPairEffect,
    ChooseBasicLandTypeReplacement,
    ChooseColorReplacement,
    ChooseCreatureTypeReplacement,
    ChooseNamedModeReplacement,
    ConditionalEffect,
    EffectRegistry,
    GameEffect,
    GetCityBlessingEffect,
    LivingWeaponEffect,
    LoseLifeEffect,
    PumpEffect,
    RenownEffect,
    ReplacementEffect,
    ReplacementRegistry,
    ReturnSelfFromGraveyardToBattlefieldEffect,
    ReturnSelfFromGraveyardToHandEffect,
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
#: carried-but-inert — see `docs/implementation-state/BACKLOG.md` (PAR/MEC
#: tickets) for which of them are still open.
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
    # RULE 506.5's "whenever a Samurai or Warrior you control attacks alone"
    # — same payload shape as `ATTACKS`, just fired once per combat rather
    # than once per attacker (`GameEngine._fire_attacks_alone_event`).
    "ATTACKS_ALONE": "player_id",
    "BLOCKS": "player_id",
    # RULE 509.5: "whenever a creature you control becomes blocked" — the
    # attacker-side event names its controller as ``player_id`` (the same
    # convention `ATTACKS`/`BLOCKS` use), not ``controller_id``.
    "BECOMES_BLOCKED": "player_id",
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
    # "Whenever you scry/surveil, …" (Chance-Met Elves, Dimir Spybug) — both
    # keyword actions fire a per-player event naming who looked
    # (`RulesEngine._look_at_top`), the same ``player_id`` convention as
    # every other player-subject event above.
    "SCRY": "player_id",
    "SURVEIL": "player_id",
    # "Whenever you gain life, …" (RULE 119.3, Ajani's Pridemate-shaped) —
    # `RulesEngine.gain_life` fires `LIFE_GAINED` per-player, same
    # convention as every other player-subject event above.
    "LIFE_GAINED": "player_id",
    # "Whenever the Ring tempts you, …" (RULE 701.51a, Tales of Middle-
    # earth) — `RulesEngine.the_ring_tempts_you` fires this per-player, same
    # convention as SCRY/SURVEIL/LIFE_GAINED above.
    "RING_TEMPTED": "player_id",
    # "Whenever an opponent draws a card, …" (Smothering Tithe-shaped,
    # MEC-12) — `RulesEngine.draw` already fires this per-player
    # (`draw_discard_mixin.py`), same ``player_id`` convention as every
    # other player-subject event above; only this table entry was missing.
    "DRAW": "player_id",
}

#: Which event-data key identifies *which object* an event is about — RULE
#: 603.1's "self"/"attached_permanent" subject scoping (below) matches this
#: key against an instance id. Every event `ENTERS_BATTLEFIELD`/`DIES`/
#: `ATTACKS`/`BLOCKS` fires carries ``instance_id`` (the default); `DAMAGE`
#: is the one exception — its subject (who *dealt* the damage) is
#: ``source_id`` (`RulesEngine.deal_damage`), since ``instance_id`` isn't
#: even a key that event carries. `COUNTER` (RULE 122, `RulesEngine.
#: add_counters`) names the permanent counters were put *on* as
#: ``target_id`` — a self-subject "whenever counters are put on ~" grant
#: (Danny Pink) needs that key, not the default.
_SUBJECT_EVENT_KEYS: dict[str, str] = {"DAMAGE": "source_id", "COUNTER": "target_id"}


def _subject_event_key(trigger: dict[str, Any]) -> str:
    # RULE 603.1's *recipient*-side damage trigger (MEC-11, Enrage-shaped
    # "whenever ~ is dealt damage" — `parser/oracle/segmenter.py`'s
    # `_DAMAGE_RECIPIENT_TRIGGER_RE`) needs the *other* end of the same
    # `DAMAGE` event: who was hit, not who hit them. The segmenter marks
    # this with ``condition["recipient"] = True`` rather than a second
    # `EventType`, since it's still the same event, just read from the
    # other side.
    if trigger.get("event") == "DAMAGE" and (trigger.get("condition") or {}).get("recipient"):
        return "target_id"
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

    ``{"subject": "you"}`` — the odd one out, and deliberately so: RULE
    603.1 conditions whose subject is a **player** rather than an object
    ("whenever **you** scry", "whenever **you** surveil"). There is no
    acting object to match at all, so this compares the event's *player*
    key (`_GROUP_CONTROLLER_EVENT_KEYS`, ``player_id`` for these) against
    the source's controller — the same key the "group … you control"
    subjects use for their controller half, just used on its own. Missing
    that key on the event → fail-closed ``False``, exactly like the
    object subjects.
    """
    condition = trigger.get("condition")
    if not condition:
        return None
    subject = condition.get("subject")
    instance_id = getattr(source, "instance_id", None)
    event_key = _subject_event_key(trigger)

    if subject == "you":
        controller_key = _GROUP_CONTROLLER_EVENT_KEYS.get(
            trigger.get("event"), "controller_id"
        )

        def _you_ok(event: Any, context: Any, src=source, key=controller_key) -> bool:
            actor = event.get(key)
            return actor is not None and actor == getattr(src, "controller_id", None)

        return _you_ok

    if subject == "self":

        def _self_ok(event: Any, context: Any, iid=instance_id, key=event_key) -> bool:
            event_instance = event.get(key)
            return event_instance is not None and event_instance == iid

        return _self_ok

    if subject == "self_as_recipient":
        # "Whenever ~ is dealt damage, …" (Stuffy Doll) — unlike plain
        # "self" (keyed to `_subject_event_key`'s per-event *actor* field,
        # ``source_id`` for DAMAGE), this checks the *recipient* instead
        # — always ``target_id`` regardless of event type, since a
        # "dealt damage" subject only ever makes sense for DAMAGE.
        def _self_recipient_ok(event: Any, context: Any, iid=instance_id) -> bool:
            target_id = event.get("target_id")
            return target_id is not None and target_id == iid

        return _self_recipient_ok

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
    # RULE 701.15b: a *designation* filter on the acting object rather than a
    # characteristic — "whenever a **goaded** creature attacks" (Vengeful
    # Ancestor), "whenever a **goaded attacking or blocking** creature dies"
    # (Baeloth Barrityl). Read live off the board where it can be, and off the
    # event where it can't (a DIES event's object has already left, RULE
    # 400.7, so `RulesEngine`'s DIES firing snapshots both keys).
    goaded = bool(condition.get("goaded"))
    in_combat = bool(condition.get("in_combat"))
    wants_you = condition.get("controller") == "you"
    # "during each OTHER player's untap step" (Seedborn Muse) — the
    # mirror image of ``"you"``: the event's player must be someone
    # *besides* this ability's own controller.
    wants_not_you = condition.get("controller") == "not_you"
    other_only = bool(condition.get("other"))
    # RULE 603.1 recipient-scoped "you control" (Rite of Passage's "a
    # creature you control is dealt damage") needs `target_controller_id`
    # (`RulesEngine.deal_damage`), the recipient's own controller, not
    # `source_controller_id`'s — same ``condition["recipient"]`` marker
    # `_subject_event_key` reads.
    if trigger.get("event") == "DAMAGE" and condition.get("recipient"):
        controller_key = "target_controller_id"
    else:
        controller_key = _GROUP_CONTROLLER_EVENT_KEYS.get(trigger.get("event"), "controller_id")
    # "Whenever a Human deals damage to **you**, …" (Mikaeus, the
    # Unhallowed) — unlike ``condition["recipient"]``/``target_controller_
    # id`` above (a *permanent* recipient's controller — "a creature you
    # control is dealt damage"), the recipient here is the player
    # directly: `RulesEngine.deal_damage`'s DAMAGE event stamps
    # ``target_id`` as the player's own id and ``target_controller_id`` as
    # `None` for a player target (a player has no controller), so that key
    # can never match a player recipient. Checked separately rather than
    # folded into ``controller_key`` so a permanent-recipient condition and
    # a player-recipient one never get confused for each other.
    wants_recipient_you = bool(condition.get("recipient_is_you"))

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
        want_goaded=goaded,
        want_in_combat=in_combat,
        want_recipient_you=wants_recipient_you,
    ) -> bool:
        event_instance = event.get(skey)
        if other and (event_instance is None or event_instance == iid):
            return False
        if you and event.get(ckey) != cid:
            return False
        if not_you and event.get(ckey) == cid:
            return False
        if want_recipient_you and not (event.get("is_player") and event.get("target_id") == cid):
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
        if want_goaded or want_in_combat:
            snapshot_goaded = event.get("goaded")
            snapshot_combat = event.get("in_combat")
            if snapshot_goaded is None or snapshot_combat is None:
                state = getattr(context, "state", None)
                obj = (
                    state.find_object(event_instance)
                    if state is not None and event_instance is not None else None
                )
                if obj is None:
                    return False
                from .combat import is_goaded  # local: combat imports models lazily too

                if snapshot_goaded is None:
                    snapshot_goaded = is_goaded(obj)
                if snapshot_combat is None:
                    snapshot_combat = bool(
                        getattr(obj, "attacking", False)
                    ) or getattr(obj, "blocking", None) is not None
            if want_goaded and not snapshot_goaded:
                return False
            if want_in_combat and not snapshot_combat:
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

    # "As long as this Equipment is attached to a creature, …" (Mirrormind
    # Crown) — the mirror image of `requires_equipped` above: the ability's
    # own source (the Equipment/Aura itself) must currently *be* attached to
    # something, not have something attached to it. Reads `GameObject.
    # attached_to` fresh every check, same live-board idiom.
    if trigger.get("requires_attached"):
        def _attached_gate_ok(event: Any, context: Any, src=source) -> bool:
            return getattr(src, "attached_to", None) is not None

        predicates.append(_attached_gate_ok)

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

    # "Whenever you cast a **noncreature** spell, …" (Young Pyromancer/
    # Shark Typhoon-shaped) — the negated sibling of `spell_card_types`
    # just above: RULE 603.1 excludes one main type rather than naming
    # several to include, so this is a separate key/predicate rather than
    # a "negate" flag on the existing one.
    spell_exclude_card_types = trigger.get("spell_exclude_card_types")
    if spell_exclude_card_types:
        excluded_types = tuple(str(t).lower() for t in spell_exclude_card_types)

        def _spell_type_excluded_ok(event: Any, context: Any, words=excluded_types) -> bool:
            types = event.get("object_types") or ()
            return not any(w in types for w in words)

        predicates.append(_spell_type_excluded_ok)

    # "Whenever a player casts a spell with mana value 3 or less, …"
    # (Eidolon of the Great Revel/Pyrostatic Pillar-shaped) — `SPELL_CAST`
    # already stamps ``mana_value`` (`RulesEngine`'s own cast-tracking, used
    # by `_track_spell_cast`'s "spells cast this turn" tally), so this is
    # purely a missing predicate, not a missing event field.
    spell_mv_at_most = trigger.get("spell_mana_value_at_most")
    if spell_mv_at_most is not None:
        threshold = int(spell_mv_at_most)

        def _spell_mv_ok(event: Any, context: Any, n=threshold) -> bool:
            mv = event.get("mana_value")
            return mv is not None and mv <= n

        predicates.append(_spell_mv_ok)

    # "Whenever an instant or sorcery spell you control that targets only a
    # single creature deals damage to that creature, …" (Imodane, the
    # Pyrohammer) — two flags `RulesEngine.deal_damage`/`DealDamageEffect`
    # stamp onto the DAMAGE event at the point where both the source's own
    # card type and its target_spec's shape are known; "you control" is
    # already the ordinary `"subject": "group", "controller": "you"`
    # `_build_group_ok` check (DAMAGE's group-controller key is
    # ``source_controller_id``), so these only need to add the two things
    # that check doesn't cover.
    if trigger.get("requires_source_instant_or_sorcery"):
        def _instant_sorcery_source_ok(event: Any, context: Any) -> bool:
            return bool(event.get("source_is_instant_or_sorcery"))

        predicates.append(_instant_sorcery_source_ok)

    if trigger.get("requires_single_creature_target"):
        def _single_creature_target_ok(event: Any, context: Any) -> bool:
            return bool(event.get("source_targets_only_single_creature"))

        predicates.append(_single_creature_target_ok)

    # "Whenever you cast a creature spell of the chosen type, draw a card."
    # (Vanquisher's Banner) — unlike `spell_card_types`'s fixed-at-bind-time
    # word list, the wanted subtype is only known once RULE 601.2b's "as
    # this enters, choose a creature type" choice has been made
    # (`GameObject.chosen_type`), so this reads it live off ``source`` at
    # check time rather than capturing it as a closure default. The event
    # itself carries no ``subtypes`` payload (unlike e.g. `SACRIFICE`), so
    # the cast spell is looked up live by its stamped ``instance_id`` —
    # still on the stack, since a trigger checks before it resolves.
    if trigger.get("cast_of_chosen_type"):
        def _chosen_type_cast_ok(event: Any, context: Any, src=source) -> bool:
            wanted = getattr(src, "chosen_type", None)
            if not wanted:
                return False
            state = getattr(context, "state", None)
            instance_id = event.get("instance_id")
            if state is None or instance_id is None:
                return False
            obj = state.find_object(instance_id)
            if obj is None:
                return False
            return wanted.lower() in _card_subtypes(obj.card)

        predicates.append(_chosen_type_cast_ok)

    # "Whenever you cast a red spell, …" (Runaway Steam-Kin) — a colour
    # filter on the cast card, unlike `spell_card_types`'s card-type-word
    # filter; the event carries no colour of its own, so the cast object is
    # looked up live by its stamped ``instance_id``, the same fallback
    # `cast_of_chosen_type` uses.
    cast_of_color = trigger.get("cast_of_color")
    if cast_of_color:
        wanted_color = str(cast_of_color).upper()

        def _cast_of_color_ok(event: Any, context: Any, color=wanted_color) -> bool:
            state = getattr(context, "state", None)
            instance_id = event.get("instance_id")
            if state is None or instance_id is None:
                return False
            obj = state.find_object(instance_id)
            return obj is not None and color in (getattr(obj, "colors", None) or set())

        predicates.append(_cast_of_color_ok)

    # "Whenever you sacrifice a Food, …" (RULE 122.1a/701.17 — Experimental
    # Confectioner/Trail of Crumbs-shaped) — `EventType.SACRIFICE`'s own
    # `subtypes` payload (`RulesEngine.put_into_graveyard`, the sacrificed
    # card's printed subtype half — "Food"/"Clue"/"Treasure" are subtypes,
    # not main types, so this reads `subtypes` rather than `object_types`
    # the way `spell_card_types` above does for a cast spell's main types).
    sacrifice_type = trigger.get("sacrifice_type")
    if sacrifice_type:
        word = str(sacrifice_type).lower()

        def _sacrifice_type_ok(event: Any, context: Any, w=word) -> bool:
            return w in (event.get("subtypes") or ())

        predicates.append(_sacrifice_type_ok)

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

    # "…if this creature has fewer than three +1/+1 counters on it, …"
    # (Runaway Steam-Kin) — the counter-count sibling of `source_state`
    # above, same RULE 603.4 intervening-if-about-the-source shape, just
    # a threshold instead of a tapped/untapped flag.
    source_counters_below = trigger.get("source_counters_below")
    if source_counters_below is not None:
        instance_id = getattr(source, "instance_id", None)
        threshold = int(source_counters_below.get("count", 0))
        kind = str(source_counters_below.get("kind", "+1/+1"))

        def _source_counters_below_ok(
            event: Any, context: Any, iid=instance_id, want=threshold, k=kind,
        ) -> bool:
            state = getattr(context, "state", None)
            obj = state.find_object(iid) if state is not None and iid is not None else None
            if obj is None:
                return False
            return int((obj.counters or {}).get(k, 0)) < want

        predicates.append(_source_counters_below_ok)

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
    only_during_your_turn = False
    activation_condition: Optional[dict[str, Any]] = None
    effect_specs = spec.effects
    if spec.ability_kind == "activated":
        if any(e.type == ONCE_PER_TURN_MARKER for e in effect_specs):
            once_per_turn = True
        if any(e.type == SORCERY_SPEED_MARKER for e in effect_specs):
            sorcery_speed_only = True
        if any(e.type == ONLY_DURING_YOUR_TURN_MARKER for e in effect_specs):
            only_during_your_turn = True
        # PAR-10: "…and only if `<condition>`." — the same marker-then-strip
        # shape as the two above, folded into `ActivationCost.
        # activation_condition` instead of a flag.
        condition_marker = next(
            (e for e in effect_specs if e.type == ACTIVATION_CONDITION_MARKER), None
        )
        if condition_marker is not None:
            activation_condition = dict(condition_marker.params.get("condition") or {})
        # Strip every timing/cap/condition marker before building real
        # effects (RULE 602.5d / 603.2) — each is folded into the
        # ActivatedAbility/cost, not a GameEffect.
        effect_specs = [
            e for e in effect_specs
            if e.type not in (
                ONCE_PER_TURN_MARKER, SORCERY_SPEED_MARKER,
                ONLY_DURING_YOUR_TURN_MARKER, ACTIVATION_CONDITION_MARKER,
            )
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
                # RULE 603.2/PAR-14: "This ability triggers only once each
                # turn."/"…for the first time each turn." — both printed
                # spellings fold to the same `AbilitySpec.trigger["limit"]`
                # flag in `segmenter.segment_line`; the `once_per_turn`/
                # `_last_triggered_turn` mechanism itself already existed
                # (built for Dionus, Elvish Archdruid's granted ability),
                # this is the first oracle-text path that reaches it.
                once_per_turn=bool(spec.trigger.get("limit", False)),
                # RULE 113.6a/PAR-16: inferred straight off the effect list,
                # the same "effect and permission always travel together"
                # shape `graveyard_zone` uses below for the activated half.
                functions_from_graveyard=any(
                    isinstance(e, (ReturnSelfFromGraveyardToBattlefieldEffect, ReturnSelfFromGraveyardToHandEffect))
                    for e in own_effects
                ),
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
    if only_during_your_turn:
        # RULE 602.5d's wider sibling — see `ONLY_DURING_YOUR_TURN_MARKER`.
        cost.only_during_your_turn = True
    if activation_condition:
        cost.activation_condition = activation_condition
    if any(
        isinstance(e, (ReturnSelfFromGraveyardToBattlefieldEffect, ReturnSelfFromGraveyardToHandEffect))
        for e in effects
    ):
        # PAR-10/PAR-16: "Return this card from your graveyard to the
        # battlefield[, tapped]/to your hand." is always this ability's
        # entire body on a real card — the ability lives in the graveyard,
        # not the battlefield (`can_activate`'s `graveyard_zone` branch).
        cost.graveyard_zone = True
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
    """Create a live activated ability for attach-style keywords like Equip,
    and for a card's own bare RULE 702.28/702.29 Cycling (PAR-9)."""
    keyword = spec.keyword or {}
    name = str(keyword.get("name") or "")
    if name == "cycling":
        return _cycling_activated_ability(obj, spec, keyword)
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
        description=spec.raw_text or f"{name}",
        attach_kind=name,
    )


def _cycling_activated_ability(
    obj: Any, spec: AbilitySpec, keyword: dict[str, Any]
) -> Optional[ActivatedAbility]:
    """RULE 702.28/702.29: "Cycling `<cost>`" — "`<cost>`, Discard this
    card: Draw a card." The `discard_self` cost primitive (`game/costs.py`)
    already existed; only Dismantling Wave/Renewed Faith-shaped cards ever
    got a real activatable ability out of it, hand-authored per card
    (`game/ability_catalogue.py`) — an *unregistered* card's plain Cycling
    was recognized by the parser (satisfying the coverage gate) but bound to
    nothing, so it never became an offered action (PAR-9).

    Two guards keep this from mis-firing:

    * `keywords.keyword_slug` aliases every "`<type>`cycling" spelling
      ("Landcycling", "Typecycling", "Islandcycling", …) onto this same
      "cycling" slug, and the shared cost-extraction regex has no word
      boundary — it matches "Landcycling {1}" as a substring just as
      happily as a real "Cycling {1}" line. A type-restricted variant
      searches the library instead of drawing, a different (unmodeled)
      effect — so this only fires when the card's own *raw* Scryfall
      keyword list carries no other "…cycling" entry alongside the plain
      one.
    * A card already carrying a `discard_self`-cost activated ability
      (Dismantling Wave/Renewed Faith's own hand-authored one, bound
      earlier in this same pass — `ability_catalogue.specs_for` puts
      hand-authored specs first) defines its *own* Cycling behaviour;
      don't compete with it for the same cost.
    """
    cost_text = keyword.get("cost")
    if not cost_text:
        return None
    raw_names = [str(k).strip().lower() for k in (getattr(obj.card, "keywords", None) or [])]
    if any(n != "cycling" and "cycling" in n for n in raw_names):
        return None
    if any(getattr(a.cost, "discard_self", False) for a in obj.activated_abilities):
        return None
    cost = parse_activation_cost(f"{cost_text}, Discard this card")
    cost.is_cycling = True
    return ActivatedAbility(
        effects=build_effects([EffectSpec("draw", {"count": 1})], source=obj),
        cost=cost,
        source=obj,
        description=spec.raw_text or "Cycling",
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


def _kw_soulbond(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
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


def _kw_living_weapon(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    return [
        TriggeredAbility(
            trigger_event=EventType.ENTERS_BATTLEFIELD,
            effects=[LivingWeaponEffect(source=obj)],
            condition=_self_only_condition(getattr(obj, "instance_id", None)),
            source=obj,
            description=spec.raw_text or "Living weapon",
        )
    ]


def _kw_fading(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    if n is None:
        return []
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


def _kw_cumulative_upkeep(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    # RULE 702.24b: "At the beginning of your upkeep, put an age counter on
    # this permanent, then sacrifice it unless you pay its upkeep cost for
    # each age counter on it." Cumulative Upkeep is `KeywordShape.COST`, not
    # `NUMBER` — its parsed param lives under `spec.keyword["cost"]`, not the
    # ``n`` this dispatch table's callers all otherwise pass (see
    # `_keyword_triggered_abilities`, which always forwards `keyword.get("n")`
    # regardless of shape); ``n`` is simply unused here.
    cost = (spec.keyword or {}).get("cost")
    if not cost:
        return []
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
            effects=[CumulativeUpkeepEffect(cost=cost, source=obj)],
            condition=_your_upkeep,
            controller_id=controller_id,
            source=obj,
            description=spec.raw_text or f"Cumulative upkeep {cost}",
        )
    ]


def _kw_renown(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    if n is None:
        return []
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


def _kw_annihilator(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    if n is None:
        return []
    n = int(n)
    condition = _self_only_condition(getattr(obj, "instance_id", None))
    return [
        TriggeredAbility(
            trigger_event=EventType.ATTACKS,
            effects=[SacrificeEffect(count=n, selector="defending_player")],
            condition=condition,
            source=obj,
            description=spec.raw_text or f"Annihilator {n}",
        )
    ]


def _kw_afflict(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    if n is None:
        return []
    n = int(n)
    condition = _self_only_condition(getattr(obj, "instance_id", None))
    return [
        TriggeredAbility(
            trigger_event=EventType.BECOMES_BLOCKED,
            effects=[LoseLifeEffect(amount=n, selector="defending_player")],
            condition=condition,
            source=obj,
            description=spec.raw_text or f"Afflict {n}",
        )
    ]


def _kw_bushido(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    if n is None:
        return []
    n = int(n)
    condition = _self_only_condition(getattr(obj, "instance_id", None))
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


#: `keyword["name"]` → builder, mirroring `EffectRegistry`'s dict-over-
#: if/elif pattern. Each builder takes ``(obj, spec, n)`` and returns the
#: real triggered abilities to synthesize for that keyword (or ``[]`` if
#: its own ``n`` requirement isn't met) — see `_keyword_triggered_abilities`.
_KEYWORD_TRIGGERED_BUILDERS: dict[str, Callable[[Any, AbilitySpec, Any], list[TriggeredAbility]]] = {
    "soulbond": _kw_soulbond,
    "living_weapon": _kw_living_weapon,
    "fading": _kw_fading,
    "cumulative_upkeep": _kw_cumulative_upkeep,
    "renown": _kw_renown,
    "annihilator": _kw_annihilator,
    "afflict": _kw_afflict,
    "bushido": _kw_bushido,
}


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
    builder = _KEYWORD_TRIGGERED_BUILDERS.get(name)
    if builder is None:
        return []
    return builder(obj, spec, keyword.get("n"))


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
        if spec.alt_cost:
            # RULE 118.9 (MEC-15): the payment half reuses `additional_cost`'s
            # `parse_activation_cost` dict-to-`ActivationCost` reuse (minus
            # its own ``condition`` key, which isn't a cost component);
            # the optional gate reuses `free_cast_condition`'s own field/
            # evaluator (`condition_query.free_cast_condition_holds`).
            spec.validate()
            payment = {k: v for k, v in spec.alt_cost.items() if k != "condition"}
            obj.alt_cast_cost = parse_activation_cost(payment)
            obj.alt_cast_condition = spec.alt_cost.get("condition")
        if spec.strive_cost:
            spec.validate()
            obj.strive_cost = ManaCost.parse(spec.strive_cost)
        if spec.impulsive_draw_on_combat_damage:
            spec.validate()
            obj.impulsive_draw_on_combat_damage = dict(spec.impulsive_draw_on_combat_damage)
        if spec.rebound:
            spec.validate()
            obj.has_rebound = True
        if spec.enter_or_graveyard_discard_land:
            spec.validate()
            obj.enter_or_graveyard_discard_land = True
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
            # RULE 702.131a: Ascend on an instant/sorcery is a one-shot spell
            # ability ("you get the city's blessing"), checked once at
            # resolution — unlike Ascend on a permanent (702.131b), which
            # stays on `intrinsic_keywords` for `RulesEngine._sba_check_
            # ascend` to watch continuously instead.
            keyword = spec.keyword or {}
            if str(keyword.get("name") or "") == "ascend" and (
                getattr(obj.card, "is_instant", False) or getattr(obj.card, "is_sorcery", False)
            ):
                obj.spell_effects = list(getattr(obj, "spell_effects", [])) + [GetCityBlessingEffect(source=obj)]
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
                    effect,
                    (
                        ChooseCreatureTypeReplacement,
                        ChooseColorReplacement,
                        ChooseNamedModeReplacement,
                        ChooseBasicLandTypeReplacement,
                    ),
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
