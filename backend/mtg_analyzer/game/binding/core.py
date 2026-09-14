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

from ...models.game.events import EventType
from ...models.mana.mana_cost import ManaCost
from ...parser.oracle.catalogue.handlers import (
    ACTIVATE_ONLY_ONCE_MARKER,
    ACTIVATION_CONDITION_MARKER,
    FROM_HAND_MARKER,
    ONCE_PER_TURN_MARKER,
    ONLY_DURING_YOUR_TURN_MARKER,
    POWERUP_COST_REDUCTION_MARKER,
    SORCERY_SPEED_MARKER,
)
from ...parser.oracle.spec import AbilitySpec, EffectSpec
from ..costs import ActivationCost, parse_activation_cost
from ..static_conditions import condition_holds
from ..effects.core import (
    ActivatedAbility,
    AddCountersEffect,
    AddManaEffect,
    RecordBendEffect,
    AttachEffect,
    BecomeSaddledEffect,
    CumulativeUpkeepEffect,
    RemoveCounterOrSacrificeEffect,
    SoulbondPairEffect,
    ChooseBasicLandTypeReplacement,
    ChooseCardNameReplacement,
    ChooseColorReplacement,
    ChooseCreatureTypeReplacement,
    ChooseNamedModeReplacement,
    ChooseNumberReplacement,
    ChooseOpponentReplacement,
    ConditionalEffect,
    EffectRegistry,
    EmbalmEternalizeEffect,
    GameEffect,
    GetCityBlessingEffect,
    GrantUntilEffect,
    HauntEffect,
    LivingWeaponEffect,
    LoseLifeEffect,
    PumpEffect,
    RenownEffect,
    ReplacementEffect,
    ReplacementRegistry,
    PutSelfOntoBattlefieldFromHandEffect,
    ReturnSelfFromGraveyardToBattlefieldEffect,
    ReturnSelfFromGraveyardToHandEffect,
    SacrificeEffect,
    SpecializeEffect,
    UnearthEffect,
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
_PARAMETRIC_KEYWORD_KEYS: frozenset[str] = frozenset(
    {"n", "cost", "quality", "exile_hand_card_color"}
)


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
    callable (docs/09 security boundary).

    ``spec.params["active_if"]`` (RULE 613.6's "as long as `<condition>`, …"
    vocabulary, `static_conditions.py`) gates *any* replacement generically —
    wrapping whatever `condition` the factory itself set, rather than each
    replacement factory reimplementing its own level/turn/board gate. This is
    what lets a Leveler's per-band amount (Hedron-Field Purists — MEC-30)
    ship as two plain `EffectSpec("prevent_damage", {..., "active_if": {...}})`
    entries instead of new bespoke code, reusing `condition_from_legacy_
    params`'s existing ``source_counters`` min/max translation of
    ``min_level``/``max_level``.
    """
    built: list[ReplacementEffect] = []
    for spec in effects:
        if not ReplacementRegistry.is_registered(spec.type):
            raise BindError(f"no registered replacement for type {spec.type!r}")
        params = dict(spec.params)
        active_if = params.pop("active_if", None)
        effect = ReplacementRegistry.create(spec.type, params)
        effect.source = source
        if active_if is not None:
            inner_condition = effect.condition
            controller_id = getattr(source, "controller_id", None)

            def _gated(
                event: Any, context: Any,
                _active_if: dict = active_if, _inner: Any = inner_condition,
                _source: Any = source, _controller_id: Any = controller_id,
            ) -> bool:
                if not condition_holds(_active_if, context.state, _source, _controller_id):
                    return False
                return _inner is None or _inner(event, context)

            effect.condition = _gated
        built.append(effect)
    return built


#: RULE 603.1's "you control" scoping reads a different event-data key
#: depending on the event: `ENTERS_BATTLEFIELD`/`DIES` carry `controller_id`,
#: while `ATTACKS`/`BLOCKS` carry `player_id` — always that permanent's
#: controller (RULE 508.1a/509.1b — you can only attack/block with creatures
#: you control) — instead; see the firing sites in `game/game_engine.py`.
_GROUP_CONTROLLER_EVENT_KEYS: dict[str, str] = {
    "ATTACKS": "player_id",
    # "Whenever you lose life for the first time each turn, …" (Intermediate
    # Chirography level 2, PAR-60) — `RulesEngine.lose_life` fires
    # `LIFE_LOST` per player, keyed by ``player_id``.
    "LIFE_LOST": "player_id",
    # RULE 702.19b's "whenever you exert a creature, …" (Ahn-Crop
    # Champion-cycle payoffs) — `GameEngine.declare_attackers` fires this
    # per-exert, same ``player_id`` convention as `ATTACKS` above.
    "EXERTED": "player_id",
    # RULE 506.5's "whenever a Samurai or Warrior you control attacks alone"
    # — same payload shape as `ATTACKS`, just fired once per combat rather
    # than once per attacker (`GameEngine._fire_attacks_alone_event`).
    "ATTACKS_ALONE": "player_id",
    # RULE 506.4's "whenever you attack, …" (MEC-28, Karlach, Fury of
    # Avernus-shaped) — `GameEngine._fire_player_attacked_events`' own
    # aggregate event names the attacker as ``attacking_player_id`` (it also
    # carries a ``defending_player_id``, unlike every other player-subject
    # event above), fired once per combat rather than once per attacker.
    "PLAYER_ATTACKED": "attacking_player_id",
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
    # — `RulesEngine._request_search` fires this keyed by ``player_id`` too.
    "LIBRARY_SEARCHED": "player_id",
    # "Whenever a player/an opponent mills a nonland card, …" (RULE 728's
    # Glowing One/Infesting Radroach, The Wise Mothman) — `RulesEngine.mill`
    # fires this per nonland card, keyed by whose library it came from.
    "MILL_CARD": "player_id",
    # "Whenever you discard a card, …" (MEC-38, Necropotence) — same
    # per-card-sibling-of-an-aggregate shape as `MILL_CARD` above.
    "DISCARD_CARD": "player_id",
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
    # "Whenever you lose life, …" (RULE 118/119, Vilis Broker of Blood-
    # shaped, MEC-43) — `RulesEngine.lose_life` fires `LIFE_LOST` per-player
    # (the single choke point for every cause of life loss, including
    # combat/noncombat damage — see its own docstring), same ``player_id``
    # convention as `LIFE_GAINED` just above.
    "LIFE_LOST": "player_id",
    # "Whenever the Ring tempts you, …" (RULE 701.51a, Tales of Middle-
    # earth) — `RulesEngine.the_ring_tempts_you` fires this per-player, same
    # convention as SCRY/SURVEIL/LIFE_GAINED above.
    "RING_TEMPTED": "player_id",
    # "Whenever an opponent draws a card, …" (Smothering Tithe-shaped,
    # MEC-12) — `RulesEngine.draw` already fires this per-player
    # (`draw_discard_mixin.py`), same ``player_id`` convention as every
    # other player-subject event above; only this table entry was missing.
    "DRAW": "player_id",
    # "Whenever you discard a card, …" (Glint-Horn Buccaneer) — `RulesEngine.
    # discard`/`discard_specific` fire `DISCARD` per-player, same
    # ``player_id`` convention as every other player-subject event above.
    "DISCARD": "player_id",
    # "Whenever a creature/permanent **you control** becomes the target of a
    # spell or ability, …" (MEC-19, Battle Mammoth/Shapers' Sanctuary-
    # shaped) — `BECOMES_TARGET` names the *targeted* object's own
    # controller as ``target_controller_id`` (not a bare ``controller_id``,
    # which this event uses for the unrelated *caster* — see its own
    # docstring), so "you control" scopes to the target, not whoever cast
    # the targeting spell.
    "BECOMES_TARGET": "target_controller_id",
    # "Whenever one or more creatures you control … deal combat damage to a
    # player, …" (MEC-29) — the aggregate event already names the
    # contributing creatures' controller as ``player_id``, the same
    # convention every other player-subject aggregate event above uses.
    "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER": "player_id",
    # "Whenever you clash, …" / "Whenever you win a clash, …" (RULE 701.30,
    # PAR-29) — `RulesEngine.clash` fires `CLASHED`/`WON_CLASH` per-player,
    # the same ``player_id`` convention as SCRY/SURVEIL/LIFE_GAINED above.
    "CLASHED": "player_id",
    "WON_CLASH": "player_id",
    # "Whenever you collect evidence, …" (RULE 701.59b, PAR-29) —
    # `RulesEngine.collect_evidence` fires `COLLECTED_EVIDENCE` per-player.
    "COLLECTED_EVIDENCE": "player_id",
    # "Whenever you forage, …" (RULE 701.61b, PAR-29) — `RulesEngine.forage`
    # fires `FORAGED` per-player.
    "FORAGED": "player_id",
    # "Whenever you behold …" (RULE 701.4b, PAR-29) — `RulesEngine.behold`
    # fires `BEHELD` per-player.
    "BEHELD": "player_id",
    # "Whenever you waterbend, earthbend, firebend, or airbend, …" (RULE
    # 701.6x, Avatar Aang) — `RulesEngine.record_bend` fires `BENT`
    # per-player, same ``player_id`` convention as every player-subject
    # event above.
    "BENT": "player_id",
    # "Whenever you roll one or more dice, …" (RULE 706, Farideh, Devil's
    # Chosen / Vrondiss, Rage of Ancients / Barbarian Class) —
    # `RulesEngine.roll_die` fires `DICE_ROLLED` per roll instruction,
    # keyed by ``player_id``, same convention as CLASHED/SCRY above.
    "DICE_ROLLED": "player_id",
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


def attacked_player_lowest_life_predicate(controller_id: Optional[str]) -> Callable[[Any, Any], bool]:
    """"if no opponent has more life than that player" (PAR-32, Guild
    Artisan cycle) — a RULE 603.4 gate on an "~ attacks a player" trigger:
    the attacked player (the ATTACKS event's ``defending_player_id``) has
    life ≤ every non-eliminated opponent of ``controller_id``. Shared by
    `_trigger_condition` (printed form) and
    `continuous._apply_layer_6_ability` (the "Commander creatures you own
    have '…'" re-granted form)."""

    def _ok(event: Any, context: Any, me=controller_id) -> bool:
        state = getattr(context, "state", None)
        did = (event or {}).get("defending_player_id")
        if state is None or did is None:
            return False
        try:
            defender = state.player_by_id(did)
        except (KeyError, ValueError):
            return False
        opponents = [
            p for p in state.players
            if p.id != me and not getattr(p, "has_lost", False)
        ]
        return bool(opponents) and all(defender.life <= p.life for p in opponents)

    return _ok


def regrant_trigger_gate_predicate(
    key: str, controller_id: Optional[str], source: Any = None
) -> Optional[Callable[[Any, Any], bool]]:
    """A firing-event gate for a *re-granted* trigger (PAR-32 — "Commander
    creatures you own have 'Whenever …'"), by the trigger-dict key that
    carried it. `continuous._apply_layer_6_ability` ANDs the result onto the
    granted `TriggeredAbility.condition`; each gate is the same event-field
    read the printed-trigger path uses in `_trigger_condition`. ``source``
    is the granted-to permanent, for the source-relative keys."""
    if key == "attacked_player_has_lowest_life":
        return attacked_player_lowest_life_predicate(controller_id)
    if key == "spell_from_exile":
        return lambda event, context: bool((event or {}).get("from_exile"))
    if key == "spell_exclude_card_types":
        def _not_creature_spell(event: Any, context: Any) -> bool:
            state = getattr(context, "state", None)
            spell = state.find_object((event or {}).get("instance_id")) if state is not None else None
            return spell is not None and not bool(getattr(spell, "is_creature", False))
        return _not_creature_spell
    if key == "spell_shares_creature_type_with_source":
        def _shares(event: Any, context: Any, src=source) -> bool:
            state = getattr(context, "state", None)
            spell = state.find_object((event or {}).get("instance_id")) if state is not None else None
            if spell is None or src is None:
                return False

            def _subs(o: Any) -> set[str]:
                tl = getattr(getattr(o, "card", None), "type_line", "") or ""
                return {w.lower() for w in tl.partition("—")[2].split()}

            return bool(_subs(spell) & _subs(src))

        return _shares
    return None


def regrant_active_if_predicate(active_if: dict[str, Any], source: Any) -> Callable[[Any, Any], bool]:
    """PAR-32: a re-granted phase trigger's RULE 603.4 intervening-if
    (`static_conditions` `active_if` dict — Cloakwood Hermit / Dragon
    Cultist), evaluated against the *granted-to* permanent and its
    controller. `continuous._apply_layer_6_ability` ANDs it."""
    cid = getattr(source, "controller_id", None)

    def _ok(event: Any, context: Any, cond=dict(active_if), src=source, c=cid) -> bool:
        state = getattr(context, "state", None)
        return state is not None and condition_holds(cond, state, src, c)

    return _ok


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
        # RULE 508.3a batch attack: "one or more <filter> creatures you
        # control attack" — the `PLAYER_ATTACKED` aggregate carries only the
        # attacking player, so the ``<filter>`` (a negated creature subtype
        # or a main type, `segmenter._batch_attack_group_filter`) is checked
        # against the live attacking group, which is still on the battlefield
        # when triggers are put on the stack (RULE 508.3).
        group_filter = condition.get("group_filter") or None

        def _you_ok(
            event: Any, context: Any, src=source, key=controller_key, gf=group_filter
        ) -> bool:
            actor = event.get(key)
            if actor is None or actor != getattr(src, "controller_id", None):
                return False
            if gf is None:
                return True
            return _any_attacking_matches(context, actor, gf)

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

    ``crewed_by_self`` (MEC-29, RULE 702.122c) — the acting object's own
    live `GameObject.crewed_by_ids` must contain this ability's own source
    ("whenever a Vehicle crewed by ~ this turn attacks", Balthier and Fran).
    Read off the board (never snapshotted onto the event) since the acting
    object is always still on the battlefield for every event kind this key
    is meaningful for (ATTACKS).
    """
    controller_id = getattr(source, "controller_id", None)
    subject_key = _subject_event_key(trigger)
    type_word = condition.get("type")
    subtypes = condition.get("subtypes")
    nontoken = bool(condition.get("nontoken"))
    # "a creature **token** you control deals combat damage to a player"
    # (Curiosity Crafter) — the positive mirror of ``nontoken`` (RULE 111.9).
    want_token = bool(condition.get("is_token"))
    # "a **non-Human** creature you control attacks" (Winota) — the negated
    # mirror of ``subtypes``: the acting object must NOT have any of these
    # creature subtypes. Read off the event's live subtypes (ATTACKS keeps
    # the object on the battlefield, RULE 508.3), fail-closed if unknowable.
    excluded_subtypes = [s.lower() for s in condition.get("excluded_subtypes") or []]
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
    wants_owner_you = condition.get("owner") == "you"
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
    # RULE 702.122c: "whenever a Vehicle crewed by ~ this turn attacks"
    # (Balthier and Fran) — a filter on the acting object's own state
    # (`GameObject.crewed_by_ids`, stamped when a creature is tapped to pay
    # a Crew cost), the same "read the board, not the event" idiom the
    # goaded/in-combat filters below already use, just keyed on this
    # ability's own source rather than a designation.
    want_crewed_by_self = bool(condition.get("crewed_by_self"))
    # "Whenever a player taps a **nonbasic** land for mana, …" (Burning
    # Earth) — a supertype, not a main type (`object_types`) or a subtype
    # (after the printed em dash), so it needs its own live board check
    # rather than either existing filter above.
    want_nonbasic = bool(condition.get("nonbasic"))
    # "Whenever a **nonland** creature/permanent you control dies, …"
    # (Beifong's Bounty Hunters) — a negated main type on the acting object.
    # Checked against the DIES event's snapshotted ``object_types`` (the
    # object has left the battlefield by the time this runs, RULE 400.7),
    # with the same live-lookup fallback the ``type`` filter uses.
    want_nonland = bool(condition.get("nonland"))
    # RULE 603.1 Panharmonicon-shaped self-recursion guard (MEC-43 round
    # 4D, Kodama of the East Tree — "if it wasn't put onto the
    # battlefield with this ability"): the acting object's own live
    # `GameObject.entered_via_ability_id` (stamped by `RulesEngine.
    # _apply_chosen_object`'s ``"hand_to_battlefield"`` action) must not
    # equal this ability's own source — the same "read the board, keyed
    # on this ability's own source" idiom `crewed_by_self` uses above.
    # Fails *open* (doesn't reject) when the guard can't be confirmed —
    # the printed default is "wasn't put here", so an inconclusive lookup
    # shouldn't silently suppress an otherwise-legal trigger.
    want_not_entered_via_self = bool(condition.get("not_entered_via_self"))
    # MEC-49: "whenever a creature **dealt damage by ~ this turn** dies, …"
    # (Baron Sengir, Abattoir Ghoul) — the acting object's `instance_id`
    # must be in `GameState.creatures_damaged_by_source_this_turn` keyed
    # under this ability's own source. A pure history lookup (the object is
    # gone by DIES), keyed on this ability's source like `crewed_by_self`.
    want_damaged_by_self = bool(condition.get("damaged_by_source_this_turn"))
    # "…by **enchanted creature**" (Vampiric Embrace) — the damage source is
    # this Aura's host, not the Aura itself.
    damaged_by_via_attached = bool(condition.get("via_attached"))
    # "whenever a creature [you control / an opponent controls] **with a
    # -1/-1 counter on it** dies" (the -1/-1 & +1/+1 aristocrats archetype
    # — Necroskitter, Skyclave Shadowcat, The Scorpion God, …). Read off
    # the DIES event's snapshotted ``counters`` (RULE 400.7 — the object is
    # gone), with a live-board fallback for verbs that keep the object
    # around (ATTACKS &c.). ``has_counter_kind`` names the counter kind;
    # ``has_counter`` is the kindless "with a counter on it".
    want_has_counter = bool(condition.get("has_counter"))
    want_has_counter_kind = condition.get("has_counter_kind")
    #: "creatures that are enchanted by an Aura you control" (Killian,
    #: Decisive Mentor, PAR-60).
    want_enchanted_by_your_aura = bool(condition.get("enchanted_by_your_aura"))

    def _group_ok(
        event: Any,
        context: Any,
        iid=instance_id,
        cid=controller_id,
        tword=type_word,
        stypes=subtypes,
        excl_stypes=excluded_subtypes,
        want_nontoken=nontoken,
        want_token=want_token,
        you=wants_you,
        not_you=wants_not_you,
        owner_you=wants_owner_you,
        other=other_only,
        ckey=controller_key,
        skey=subject_key,
        want_goaded=goaded,
        want_in_combat=in_combat,
        want_recipient_you=wants_recipient_you,
        want_crewed_by_self=want_crewed_by_self,
        want_nonbasic=want_nonbasic,
        want_nonland=want_nonland,
        want_not_entered_via_self=want_not_entered_via_self,
        want_damaged_by_self=want_damaged_by_self,
        damaged_by_via_attached=damaged_by_via_attached,
        want_has_counter=want_has_counter,
        want_has_counter_kind=want_has_counter_kind,
        want_enchanted_by_your_aura=want_enchanted_by_your_aura,
    ) -> bool:
        event_instance = event.get(skey)
        if other and (event_instance is None or event_instance == iid):
            return False
        if you and event.get(ckey) != cid:
            return False
        if not_you and event.get(ckey) == cid:
            return False
        if owner_you and event.get("owner_id") != cid:
            return False
        if want_recipient_you and not (event.get("is_player") and event.get("target_id") == cid):
            return False
        # "An opponent sacrifices a nontoken permanent…" (Tergrid, God of
        # Fright, MEC-43 round 4E) — unlike every prior caller, this is a
        # bare "nontoken `<any permanent>`" qualifier with *no* accompanying
        # subtype list, so it must be checked on its own rather than nested
        # inside the ``if stypes:`` block below (which only ever ran when a
        # subtype filter was *also* present, e.g. "another nontoken Zombie
        # or Mutant" — The Ghoul, Gunslinger).
        if want_nontoken and event.get("is_token"):
            return False
        if want_token:
            # The DAMAGE event carries no `is_token` for its *source*, so
            # re-derive it from the still-live acting object (a creature that
            # just dealt combat damage is on the battlefield, RULE 510.2).
            tok = event.get("is_token")
            if tok is None and event_instance is not None:
                state = getattr(context, "state", None)
                obj = state.find_object(event_instance) if state is not None else None
                tok = bool(getattr(obj, "is_token", False)) if obj is not None else None
            if not tok:
                return False
        if tword and tword != "permanent":
            types = event.get("object_types")
            if types is None and event_instance is not None:
                state = getattr(context, "state", None)
                obj = state.find_object(event_instance) if state is not None else None
                types = sorted(obj.type_words) if obj is not None else None
            if not types:
                return False
            # "an ability of a **creature or land**…" (MEC-43 round 2,
            # Runic Armasaur, hand-authored) — `tword` a list means "any of
            # these", the OR sibling of the single-string check below;
            # every parser-emitted condition still passes a bare string.
            words = tword if isinstance(tword, (list, tuple)) else (tword,)
            matched = False
            for word in words:
                if word.startswith("non"):
                    # "whenever you tap a **nonland** permanent for mana"
                    # (Kinnan) — a negated main type, the only shape the
                    # positive `word in types` test can't express.
                    if word[3:] not in types:
                        matched = True
                        break
                elif word in types:
                    matched = True
                    break
            if not matched:
                return False
        if stypes:
            event_subtypes = event.get("subtypes")
            if event_subtypes is None and event_instance is not None:
                state = getattr(context, "state", None)
                obj = state.find_object(event_instance) if state is not None else None
                event_subtypes = _card_subtypes(obj.card) if obj is not None else None
            if not event_subtypes or not any(s in event_subtypes for s in stypes):
                return False
        if excl_stypes:
            event_subtypes = event.get("subtypes")
            if event_subtypes is None and event_instance is not None:
                state = getattr(context, "state", None)
                obj = state.find_object(event_instance) if state is not None else None
                event_subtypes = _card_subtypes(obj.card) if obj is not None else None
            if event_subtypes is None:
                return False  # can't confirm the negation — fail closed
            lowered = {str(s).lower() for s in event_subtypes}
            if any(e in lowered for e in excl_stypes):
                return False
        if want_nonbasic:
            if event_instance is None:
                return False
            state = getattr(context, "state", None)
            obj = state.find_object(event_instance) if state is not None else None
            if obj is None or "basic" in str(getattr(obj.card, "type_line", "") or "").lower():
                return False
        if want_nonland:
            types = event.get("object_types")
            if types is None and event_instance is not None:
                state = getattr(context, "state", None)
                obj = state.find_object(event_instance) if state is not None else None
                types = sorted(obj.type_words) if obj is not None else None
            if types is None or "land" in types:
                return False
        if want_crewed_by_self:
            if iid is None or event_instance is None:
                return False
            state = getattr(context, "state", None)
            obj = state.find_object(event_instance) if state is not None else None
            if obj is None or iid not in (getattr(obj, "crewed_by_ids", None) or []):
                return False
        if want_not_entered_via_self and iid is not None and event_instance is not None:
            state = getattr(context, "state", None)
            obj = state.find_object(event_instance) if state is not None else None
            if obj is not None and getattr(obj, "entered_via_ability_id", None) == iid:
                return False
        if want_damaged_by_self:
            if iid is None or event_instance is None:
                return False
            state = getattr(context, "state", None)
            source_id = iid
            if damaged_by_via_attached:
                aura = state.find_object(iid) if state is not None else None
                source_id = getattr(aura, "attached_to", None)
                if source_id is None:
                    return False
            hit_by = (
                getattr(state, "creatures_damaged_by_source_this_turn", {}).get(event_instance, ())
                if state is not None else ()
            )
            if source_id not in hit_by:
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
                from ..combat import is_goaded  # local: combat imports models lazily too

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
        if want_has_counter or want_has_counter_kind:
            ctrs = event.get("counters")
            if ctrs is None and event_instance is not None:
                state = getattr(context, "state", None)
                obj = state.find_object(event_instance) if state is not None else None
                ctrs = dict(getattr(obj, "counters", {}) or {}) if obj is not None else None
            if not ctrs:
                return False
            if want_has_counter_kind and int(ctrs.get(want_has_counter_kind, 0)) <= 0:
                return False
            if want_has_counter and not any(int(v) > 0 for v in ctrs.values()):
                return False
        # "whenever one or more creatures that are enchanted by an Aura you
        # control attack, …" (Killian, Decisive Mentor, PAR-60) — the acting
        # object (still on the battlefield for ATTACKS, RULE 508.3) must have
        # at least one Aura attached whose controller is this ability's
        # controller.
        if want_enchanted_by_your_aura:
            state = getattr(context, "state", None)
            if state is None or event_instance is None:
                return False
            if not any(
                getattr(o, "attached_to", None) == event_instance
                and "aura" in (o.card.type_line or "").lower()
                and o.controller_id == cid
                for o in state.battlefield
            ):
                return False
        return True

    return _group_ok


def _card_subtypes(card: Any) -> list[str]:
    """Lowercase subtype words after a printed type line's em dash."""
    type_line = str(getattr(card, "type_line", "") or "")
    return type_line.partition("—")[2].strip().lower().split()


def _any_attacking_matches(
    context: Any, controller_id: Any, group_filter: dict[str, Any]
) -> bool:
    """RULE 508.3a: does ``controller_id`` have at least one *currently
    attacking* creature matching ``group_filter`` (`segmenter.
    _batch_attack_group_filter`'s ``{"excluded_subtypes": [...]}`` /
    ``{"type": ...}`` shape)? — the live check for a batch attack trigger
    whose `PLAYER_ATTACKED` aggregate names only the attacking player."""
    state = getattr(context, "state", None)
    if state is None:
        return False
    excluded = [s.lower() for s in group_filter.get("excluded_subtypes") or []]
    want_type = group_filter.get("type")
    want_suspected = bool(group_filter.get("is_suspected"))
    for obj in state.battlefield:
        if not getattr(obj, "attacking", False):
            continue
        if getattr(obj, "controller_id", None) != controller_id:
            continue
        if want_type and want_type not in {t.lower() for t in getattr(obj, "type_words", ())}:
            continue
        # RULE 508.3a / 701.60 (Clandestine Meddler): "whenever one or more
        # **suspected** creatures you control attack, …".
        if want_suspected and not getattr(obj, "is_suspected", False):
            continue
        if excluded:
            obj_subs = {s.lower() for s in _card_subtypes(getattr(obj, "card", None))}
            if any(e in obj_subs for e in excluded):
                continue
        return True
    return False


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

    if trigger.get("graveyard_owner") == "you":
        def _your_graveyard_exit_ok(event: Any, context: Any, src=source) -> bool:
            controller_id = getattr(src, "controller_id", None)
            return controller_id is not None and any(
                card.get("graveyard_owner_id") == controller_id
                for card in (event.get("cards") or [])
            )

        predicates.append(_your_graveyard_exit_ok)

    # "Whenever one or more cards are put into exile from your library and/or
    # your graveyard, …" (Laelia, the Blade Reforged, PAR-60) — an
    # `EventType.EXILE` predicate keyed on the event's own ``from_zone``
    # (stamped by `RulesEngine.exile`) and the card's owner. Documented
    # simplification: `EXILE` fires per card, so this fires once per card
    # exiled from those zones rather than once per "one or more" batch —
    # exact for the single-card exiles that dominate (Laelia's own attack
    # trigger, impulse draws), an over-count only on a true mass exile.
    if trigger.get("exiled_from_your_library_or_graveyard"):
        def _exiled_from_your_lib_or_gy_ok(event: Any, context: Any, src=source) -> bool:
            controller_id = getattr(src, "controller_id", None)
            if controller_id is None:
                return False
            owner = event.get("owner_id")
            if owner is None:
                owner = event.get("player_id")
            return (
                owner == controller_id
                and event.get("from_zone") in ("library", "graveyard")
            )

        predicates.append(_exiled_from_your_lib_or_gy_ok)

    if trigger.get("during_your_turn"):
        def _during_your_turn_ok(event: Any, context: Any, src=source) -> bool:
            state = getattr(context, "state", None)
            return getattr(getattr(state, "active_player", None), "id", None) == getattr(src, "controller_id", None)

        predicates.append(_during_your_turn_ok)

    filt = trigger.get("filter")
    if filt:
        # ``by_you`` (Hapatra, Vizier of Poisons — "whenever **you** put one
        # or more -1/-1 counters on a creature") is causer-scoped rather
        # than an exact-match payload key: the counters' source must be this
        # ability's own controller (`EventType.COUNTER`'s
        # ``source_controller_id``). Popped out so it isn't fed to the
        # exact-match loop below.
        by_you = bool(filt.get("by_you"))
        player_or_planeswalker = bool(filt.get("player_or_planeswalker"))
        exact = {
            k: v for k, v in dict(filt).items()
            if k not in ("by_you", "player_or_planeswalker")
        }

        def _filter_ok(
            event: Any, context: Any, f=exact, want_by_you=by_you,
            want_player_or_planeswalker=player_or_planeswalker,
        ) -> bool:
            if not all(event.get(k) == v for k, v in f.items()):
                return False
            if want_player_or_planeswalker and not event.get("is_player"):
                target_id = event.get("target_id")
                target = context.state.find_object(target_id) if target_id is not None else None
                if target is None or not getattr(target, "is_planeswalker", False):
                    return False
            if want_by_you and event.get("source_controller_id") != getattr(source, "controller_id", None):
                return False
            return True

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

    # "Whenever ~ attacks while saddled, …" (Guardian Sunmare, MEC-40,
    # RULE 702.171c) — the ability's own source must currently carry a
    # live "becomes saddled until end of turn" stamp
    # (`GameObject.saddled_until_turn`, set by `effects.BecomeSaddledEffect`
    # — `_saddle_activated_ability`), the same "checks the source's own
    # live state, not the event's payload" idiom `requires_equipped` uses.
    if trigger.get("requires_saddled"):
        def _saddled_ok(event: Any, context: Any, src=source) -> bool:
            state = getattr(context, "state", None)
            turn = getattr(state.internal_turn, "number", None)
            return turn is not None and getattr(src, "saddled_until_turn", None) == turn

        predicates.append(_saddled_ok)

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

    # "Whenever you cast a spell with {X} in its mana cost, …"
    # (Elementalist's Palette, the Quandrix {X}-first-spell cluster, PAR-60)
    # — reads `SPELL_CAST`'s own ``has_x`` bool.
    if trigger.get("spell_has_x"):
        def _spell_has_x_ok(event: Any, context: Any) -> bool:
            return bool(event.get("has_x"))

        predicates.append(_spell_has_x_ok)

    # "Whenever you cast a **historic** spell, …" (Teshar, Ancestor's
    # Apostle, PAR-60) — RULE 700.13: an artifact, legendary, or Saga
    # spell. The `SPELL_CAST` event carries ``object_types`` (main types);
    # legendary/Saga need the live object.
    if trigger.get("spell_is_historic"):
        def _spell_is_historic_ok(event: Any, context: Any) -> bool:
            if "artifact" in (event.get("object_types") or ()):
                return True
            state = getattr(context, "state", None)
            iid = event.get("instance_id")
            obj = state.find_object(iid) if state is not None and iid is not None else None
            if obj is None:
                return False
            tl = (obj.card.type_line or "").lower()
            return bool(getattr(obj.card, "is_legendary", False)) or "saga" in tl

        predicates.append(_spell_is_historic_ok)

    # "Whenever you cast your first spell with {X} in its mana cost each
    # turn, …" (Zimone Infinite Analyst, Owlin Spiralmancer, Nev, Lattice
    # Library, PAR-60) — `SPELL_CAST`'s ``first_x_spell`` bool, computed in
    # `cast_spell` against `GameState.cast_x_spell_this_turn`.
    if trigger.get("first_x_spell"):
        def _first_x_spell_ok(event: Any, context: Any) -> bool:
            return bool(event.get("first_x_spell"))

        predicates.append(_first_x_spell_ok)

    # "Whenever you cast an instant or sorcery spell with mana value 5 or
    # greater …" (Dirgur Focusmage, Leitmotif Composer, PAR-60) — the
    # ``>=`` mirror of ``spell_mana_value_at_most`` on the same
    # `SPELL_CAST` ``mana_value`` field.
    spell_mv_at_least = trigger.get("spell_mana_value_at_least")
    if spell_mv_at_least is not None:
        min_mv = int(spell_mv_at_least)

        def _spell_mv_min_ok(event: Any, context: Any, n=min_mv) -> bool:
            mv = event.get("mana_value")
            return mv is not None and mv >= n

        predicates.append(_spell_mv_min_ok)

    # "Whenever one or more creatures you control with mana value 3 or less
    # enter, …" (Tocasia's Welcome, PAR-60) — the ENTERS event carries only
    # ``instance_id``, so re-look-up the object for its printed mana value.
    entering_mv_at_most = trigger.get("entering_mana_value_at_most")
    if entering_mv_at_most is not None:
        max_mv = int(entering_mv_at_most)

        def _entering_mv_ok(event: Any, context: Any, n=max_mv) -> bool:
            state = getattr(context, "state", None)
            iid = event.get("instance_id")
            obj = state.find_object(iid) if state is not None and iid is not None else None
            if obj is None:
                return False
            return int(getattr(obj.card, "converted_mana_cost", 0) or 0) <= n

        predicates.append(_entering_mv_ok)

    # "Whenever you attack with two or more creatures, …" (Eiganjo
    # Dynastorian, Firemane Commando, PAR-60) — a threshold on
    # `EventType.PLAYER_ATTACKED`'s own per-(attacker, defender) ``count``.
    # Documented simplification: attackers split across multiple defenders
    # each get their own sub-``count``, so "attack 2 defenders with 1
    # creature each" doesn't reach the threshold — rare, and only in
    # multiplayer.
    attackers_at_least = trigger.get("attackers_at_least")
    if attackers_at_least is not None:
        min_attackers = int(attackers_at_least)

        def _attackers_at_least_ok(event: Any, context: Any, n=min_attackers) -> bool:
            return int(event.get("count", 0) or 0) >= n

        predicates.append(_attackers_at_least_ok)

    # "Whenever an opponent attacks with creatures, if two or more of those
    # creatures are attacking you …" (Mangara the Diplomat, Tomik Wielder of
    # Law, PAR-60) — the `PLAYER_ATTACKED` aggregate's ``defending_player_id``
    # must be this ability's own controller.
    if trigger.get("defender_is_you"):
        def _defender_is_you_ok(event: Any, context: Any, src=source) -> bool:
            return event.get("defending_player_id") == getattr(src, "controller_id", None)

        predicates.append(_defender_is_you_ok)

    # "Whenever a player attacks one of your opponents, …" (Combat
    # Calligrapher, Breena the Demagogue, PAR-60) — the `PLAYER_ATTACKED`
    # aggregate's ``defending_player_id`` must be someone *other* than this
    # ability's own controller (an opponent of it). The attacker itself can
    # be anyone, including this controller (they can attack an opponent).
    if trigger.get("defender_is_opponent"):
        def _defender_is_opponent_ok(event: Any, context: Any, src=source) -> bool:
            did = event.get("defending_player_id")
            return did is not None and did != getattr(src, "controller_id", None)

        predicates.append(_defender_is_opponent_ok)

    # "…if that opponent has more life than another of your opponents, …"
    # (Breena, the Demagogue, PAR-60) — an intervening-if on the
    # `PLAYER_ATTACKED` aggregate's ``defending_player_id``: the attacked
    # opponent must have strictly more life than at least one *other*
    # opponent of this ability's controller. Only meaningful with 2+
    # opponents (three-plus-player games).
    if trigger.get("defending_opponent_leads_an_opponent"):
        def _defending_opp_leads_ok(event: Any, context: Any, src=source) -> bool:
            state = getattr(context, "state", None) or context
            did = event.get("defending_player_id")
            cid = getattr(src, "controller_id", None)
            if did is None or did == cid:
                return False
            try:
                attacked = state.player_by_id(did)
            except (KeyError, ValueError, AttributeError):
                return False
            others = [
                p for p in state.players
                if p.id != cid and p.id != did
            ]
            return any((attacked.life or 0) > (p.life or 0) for p in others)

        predicates.append(_defending_opp_leads_ok)

    # "Whenever one or more creatures you control with power 7 or greater
    # deal combat damage to a player, …" (MEC-29, Tifa, Martial Artist) — a
    # threshold on `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`'s own
    # aggregated ``max_power`` field, the same "checked against a numeric
    # field the event itself stamps" idiom `spell_mana_value_at_most` uses
    # for `SPELL_CAST`. A `"group"` condition's own ``min_power``-style
    # filter can't be reused here: that reads *one* acting object's live
    # power off the board, but this event is an aggregate over however many
    # creatures connected this step and names none of them individually.
    contributor_power_at_least = trigger.get("contributor_power_at_least")
    if contributor_power_at_least is not None:
        threshold = int(contributor_power_at_least)

        def _contributor_power_ok(event: Any, context: Any, n=threshold) -> bool:
            power = event.get("max_power")
            return power is not None and power >= n

        predicates.append(_contributor_power_ok)

    # "Whenever one or more **Pirates** you control deal combat damage to a
    # player, …" (Malcolm, Keen-Eyed Navigator) — the tribal-filter sibling
    # of ``contributor_power_at_least`` just above, off the same aggregate
    # event's own ``subtypes`` field (the union of every contributing
    # creature's subtypes that step, stamped by `GameEngine.
    # _apply_combat_damage`) rather than a live per-object lookup, for the
    # same "no single acting object to check" reason.
    contributor_subtype = trigger.get("contributor_subtype")
    if contributor_subtype is not None:
        word = str(contributor_subtype).lower()

        def _contributor_subtype_ok(event: Any, context: Any, w=word) -> bool:
            subtypes = event.get("subtypes")
            return bool(subtypes) and w in subtypes

        predicates.append(_contributor_subtype_ok)

    # "Whenever a **commander** you control deals combat damage to an
    # opponent, …" (Kediss, Emberclaw Familiar) — the RULE 903-designation
    # sibling of ``contributor_subtype`` just above, off the same
    # aggregate event's own ``contributor_is_commander`` flag (stamped by
    # `GameEngine._apply_combat_damage`), for the same "no single acting
    # object to check `_build_group_ok`'s live-board `is_commander` filter
    # against" reason.
    if trigger.get("contributor_is_commander"):
        def _contributor_is_commander_ok(event: Any, context: Any) -> bool:
            return bool(event.get("contributor_is_commander"))

        predicates.append(_contributor_is_commander_ok)

    # "Whenever one or more creatures you control **each with power
    # greater than its base power** deals combat damage to a player, …"
    # (Kutzil, Malamet Exemplar, MEC-40) — the per-contributor qualifier
    # sibling of ``contributor_is_commander`` just above, off the same
    # aggregate event's own ``contributor_power_gt_base`` flag (stamped by
    # `GameEngine._apply_combat_damage`).
    if trigger.get("contributor_power_gt_base"):
        def _contributor_power_gt_base_ok(event: Any, context: Any) -> bool:
            return bool(event.get("contributor_power_gt_base"))

        predicates.append(_contributor_power_gt_base_ok)

    # "Whenever one or more creatures you control **with base power 0** deal
    # combat damage to a player, …" (Primo, the Unbounded, PAR-60) — the
    # printed-power sibling of ``contributor_power_gt_base`` just above, off
    # the same aggregate event's own ``any_base_power_0`` flag (stamped by
    # `combat_mixin._apply_combat_damage`).
    if trigger.get("contributor_base_power_zero"):
        def _contributor_base_power_zero_ok(event: Any, context: Any) -> bool:
            return bool(event.get("any_base_power_0"))

        predicates.append(_contributor_base_power_zero_ok)

    # "Whenever an opponent draws their **second** card each turn, …"
    # (Faerie Mastermind) — an ordinal on `GameState.cards_drawn_this_
    # turn`'s running per-player total (already incremented before `DRAW`
    # fires, RULE 121.1's own draw-tracking), not a live per-object filter
    # — the same "checked against a numeric field the event itself
    # implies" idiom `spell_mana_value_at_most`/`contributor_power_at_
    # least` use. Compares against the *range* this event's own ``count``
    # covers (not just equality) so a single "draw two cards" instruction
    # that crosses the Nth draw still fires exactly once, matching how a
    # real table would read it.
    nth_draw = trigger.get("is_nth_draw_this_turn")
    if nth_draw is not None:
        n = int(nth_draw)

        def _nth_draw_ok(event: Any, context: Any, n=n) -> bool:
            player_id = event.get("player_id")
            total = context.state.cards_drawn_this_turn.get(player_id, 0)
            count = event.get("count", 1) or 1
            return total - count < n <= total

        predicates.append(_nth_draw_ok)

    # "Whenever a player casts their **second** spell each turn, …"
    # (Hearthborn Battler) — `is_nth_draw_this_turn`'s own `SPELL_CAST`
    # sibling, now on the same "already incremented before firing" footing
    # `GameState.spells_cast_this_turn` shares with `cards_drawn_this_turn`
    # (`RulesEngine.__init__`'s subscription order). ``count`` is always 1
    # here (a cast is never batched the way a multi-card draw can be), but
    # the same range comparison is kept for symmetry with the draw row.
    nth_spell = trigger.get("is_nth_spell_cast_this_turn")
    if nth_spell is not None:
        n = int(nth_spell)

        def _nth_spell_ok(event: Any, context: Any, n=n) -> bool:
            player_id = event.get("player_id")
            total = context.state.spells_cast_this_turn.get(player_id, 0)
            return total == n

        predicates.append(_nth_spell_ok)

    # "Whenever a player casts a spell, if no mana was spent to cast it,
    # counter that spell." (Vexing Bauble) — RULE 601.2h's "free spell" hate,
    # off `SPELL_CAST`'s own ``mana_spent`` (`GameObject.mana_spent_to_cast`,
    # already 0 for a free-cast/alt-cost spell — `RulesEngine.cast_spell`'s
    # own ``free_cast``/alt-cost branches never bump it).
    if trigger.get("spell_no_mana_spent"):
        def _spell_no_mana_ok(event: Any, context: Any) -> bool:
            return not event.get("mana_spent")

        predicates.append(_spell_no_mana_ok)

    # "Whenever you cast a spell from exile, …" (Passionate Archaeologist's
    # granted trigger, PAR-32) — RULE 601.2a's cast zone, off the
    # `SPELL_CAST` event's ``from_exile`` key.
    if trigger.get("spell_from_exile"):
        def _spell_from_exile_ok(event: Any, context: Any) -> bool:
            return bool(event.get("from_exile"))

        predicates.append(_spell_from_exile_ok)

    # "Whenever an opponent casts a spell with mana value, power, or
    # toughness equal to the chosen number, …" (Talion, the Kindly Lord,
    # MEC-43) — reads the RULE 601.2b ETB choice this permanent's own
    # `ChooseNumberReplacement` stamped onto `GameObject.chosen_number`
    # (Sanctum Prelate's own sibling primitive) against three of
    # `SPELL_CAST`'s own numeric fields (`mana_value`, and the new
    # `power`/`toughness` this card needed added to the event — a spell
    # still on the stack reports its own printed characteristics via
    # `GameObject.power`/`toughness`'s existing off-battlefield fallback).
    # Any one of the three matching is enough (RULE 601.2b's own "or"
    # reading); an unset field on either side fails closed rather than
    # matching by accident (``None == None``).
    if trigger.get("spell_characteristic_equals_chosen_number"):
        def _spell_characteristic_matches_chosen_number(event: Any, context: Any, src=source) -> bool:
            n = getattr(src, "chosen_number", None)
            if n is None:
                return False
            for key in ("mana_value", "power", "toughness"):
                value = event.get(key)
                if value is not None and value == n:
                    return True
            return False

        predicates.append(_spell_characteristic_matches_chosen_number)

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

    # "Whenever you cast a spell that targets one or more permanents,
    # incubate 2." (Tiller of Flesh, RULE 608.2b) — reads the SPELL_CAST
    # event's ``targets_a_permanent`` flag, stamped at cast time by
    # `casting_mixin._targets_a_permanent` when the spell's chosen targets
    # include a battlefield permanent. "you cast" is the ordinary
    # ``{"subject": "group", "controller": "you"}`` check on the same
    # event; this only adds the targeting filter that check doesn't cover.
    if trigger.get("requires_spell_targets_permanent"):
        def _spell_targets_permanent_ok(event: Any, context: Any) -> bool:
            return bool(event.get("targets_a_permanent"))

        predicates.append(_spell_targets_permanent_ok)

    # "Whenever you cast a spell that targets ~, put a +1/+1 counter on ~."
    # (RULE 702.34a's un-keyworded template — Akroan Skyguard / Battlewise
    # Hoplite / Hero of Iroas / Legolas, Master Archer) — the spell's chosen
    # targets must include this ability's own source. Reads the SPELL_CAST
    # event's `target_instance_ids` frozenset (`casting_mixin._target_
    # instance_ids`); `source` here is the bound ability's own object.
    if trigger.get("requires_spell_targets_source"):
        def _spell_targets_source_ok(event: Any, context: Any, src=source) -> bool:
            sid = getattr(src, "instance_id", None)
            return sid is not None and sid in (event.get("target_instance_ids") or ())

        predicates.append(_spell_targets_source_ok)

    # "Whenever you cast a spell using teamwork, `<effect>`." (Virtual
    # Assistant, PAR-68, RULE 702.194b) — the SPELL_CAST event's own
    # ``instance_id`` still resolves to the spell on the stack (the same
    # lookup `spell_shares_creature_type_with_source` makes just below), so
    # its live `GameObject.teamwork_paid` flag (stamped at cast time,
    # `casting_mixin.cast_spell`) is readable straight off it — no new event
    # field needed, unlike `requires_tap_reason`'s own TAPPED-event case.
    if trigger.get("requires_spell_cast_via_teamwork"):
        def _spell_cast_via_teamwork_ok(event: Any, context: Any) -> bool:
            state = getattr(context, "state", None)
            spell = state.find_object(event.get("instance_id")) if state is not None else None
            return bool(spell is not None and getattr(spell, "teamwork_paid", False))

        predicates.append(_spell_cast_via_teamwork_ok)

    # "Whenever ~ becomes tapped to pay a teamwork cost, `<effect>`." (Agent
    # Maria Hill, PAR-68, RULE 702.194a) — `TAPPED` already fires generically
    # for every genuine tap transition (`set_tapped`'s own docstring); this
    # narrows to the one `reason` Teamwork's own tap-to-pay loop stamps onto
    # that event, so an ordinary attack/tap-ability transition (``reason``
    # unset) correctly doesn't also fire this trigger.
    if trigger.get("requires_tap_reason"):
        wanted_reason = trigger["requires_tap_reason"]

        def _tap_reason_ok(event: Any, context: Any, wanted=wanted_reason) -> bool:
            return event.get("reason") == wanted

        predicates.append(_tap_reason_ok)

    # "Whenever you cast a spell that shares a creature type with ~, …"
    # (Folk Hero's granted trigger, PAR-32) — the spell is still on the
    # stack (`event["instance_id"]`); compare its creature subtypes with
    # the ability's own source's.
    if trigger.get("spell_shares_creature_type_with_source"):
        def _spell_shares_type_ok(event: Any, context: Any, src=source) -> bool:
            state = getattr(context, "state", None)
            spell = state.find_object(event.get("instance_id")) if state is not None else None
            if spell is None or src is None:
                return False

            def _subs(o: Any) -> set[str]:
                tl = getattr(getattr(o, "card", None), "type_line", "") or ""
                return {w.lower() for w in tl.partition("—")[2].split()}

            shared = _subs(spell) & _subs(src)
            return bool(shared)

        predicates.append(_spell_shares_type_ok)

    # "…a spell with mana value equal to the number of charge counters on
    # this artifact, counter that spell." (Chalice of the Void, MEC-43) —
    # reads the firing SPELL_CAST event's own ``mana_value`` against a live
    # counter count on the ability's own source; the self-referential
    # sibling of `requires_source_instant_or_sorcery`'s "read a flag off
    # the event" idiom, just comparing against board state instead of a
    # precomputed flag.
    counter_kind = trigger.get("mana_value_equals_source_counters")
    if counter_kind:
        def _mv_equals_counters_ok(event: Any, context: Any, src=source, kind=str(counter_kind)) -> bool:
            mana_value = event.get("mana_value")
            if mana_value is None:
                return False
            return int(mana_value) == int((getattr(src, "counters", None) or {}).get(kind, 0))

        predicates.append(_mv_equals_counters_ok)

    # "Whenever a source you control deals noncombat damage to an
    # opponent, …" (Chandra's Incinerator, MEC-45) — the recipient half
    # `_subject_condition`'s ``"group"``/``"controller": "you"`` check
    # doesn't cover (that scopes the *source*, not who was hit): the DAMAGE
    # event's own player target must be some player other than this
    # ability's own controller. Combined with the DAMAGE event's own
    # ``"filter": {"combat": False}`` (an exact-match AND already
    # supported above) for the "noncombat" half.
    if trigger.get("requires_damage_to_opponent"):
        def _damage_to_opponent_ok(event: Any, context: Any, src=source) -> bool:
            if not event.get("is_player"):
                return False
            controller_id = getattr(src, "controller_id", None)
            target_id = event.get("target_id")
            return target_id is not None and target_id != controller_id

        predicates.append(_damage_to_opponent_ok)

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
    elif phase_relation == "attached_permanent":
        # "At the beginning of the upkeep of enchanted creature's
        # controller, …" (MEC-43 round 4F — Dance of the Dead) — unlike
        # ``"you"``/``"not_you"`` (compared against the ability's own
        # source's controller), this compares against whoever currently
        # controls the *host* this Aura/Equipment is attached to — read
        # live off ``source.attached_to`` each check (not snapshotted at
        # bind time), since control of the enchanted/equipped permanent
        # can change independently of the Aura's own controller over its
        # lifetime.
        def _phase_relation_attached_ok(event: Any, context: Any, src=source) -> bool:
            state = getattr(context, "state", None)
            active = getattr(state, "active_player", None) if state is not None else None
            if active is None:
                return False
            # `GameObject.attached_to` is an instance id, not the object
            # itself (`TapEffect`'s own ``target_kind="attached_permanent"``
            # mode resolves it the same way) — ``None`` while this Aura/
            # Equipment isn't attached to anything yet.
            host_id = getattr(src, "attached_to", None)
            host = state.find_object(host_id) if state is not None and host_id is not None else None
            host_controller_id = getattr(host, "controller_id", None)
            return host_controller_id is not None and active.id == host_controller_id

        predicates.append(_phase_relation_attached_ok)

    # MEC-19: "Whenever ~ becomes the target of a spell or ability **an
    # opponent controls**/**you control**, …" — unlike ``phase_relation``
    # (whose event carries no controller at all, so it compares "whose turn
    # is it" against the source) or the "group"/"you" subject's own
    # ``controller`` key (which scopes the *acting* object/player, always
    # read off ``_GROUP_CONTROLLER_EVENT_KEYS``), this compares a THIRD
    # party — the *caster* of the spell/ability doing the targeting
    # (`BECOMES_TARGET`'s own ``controller_id``, deliberately not reused as
    # that event's default subject/group key — see its docstring) — against
    # the triggered ability's own source. "an opponent controls" only makes
    # rules sense when the ability's own source has a controller to compare
    # against (never true off the battlefield), so a sourceless/ownerless
    # ability fails closed rather than matching every caster.
    caster_relation = trigger.get("caster_relation")
    if caster_relation in ("opponent", "you"):
        controller_id = getattr(source, "controller_id", None)

        def _caster_relation_ok(event: Any, context: Any, cid=controller_id, rel=caster_relation) -> bool:
            if cid is None:
                return False
            caster_id = event.get("controller_id")
            is_you = caster_id == cid
            return is_you if rel == "you" else (caster_id is not None and not is_you)

        predicates.append(_caster_relation_ok)

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

    # "When there are nine or more incarnation counters on this
    # enchantment, exile it." (Nine Lives, MEC-30) — the mirror image of
    # `source_counters_below` above (RULE 603.8's "as soon as" a threshold
    # is crossed is checked exactly like an SBA, but since this card's own
    # counters only ever arrive one at a time via its own `prevent_damage`
    # rider, gating an ordinary `EventType.COUNTER` trigger with this
    # "at least" check is rules-equivalent to a real state trigger for this
    # card specifically — no new state-checking subsystem needed).
    source_counters_at_least = trigger.get("source_counters_at_least")
    if source_counters_at_least is not None:
        instance_id = getattr(source, "instance_id", None)
        threshold = int(source_counters_at_least.get("count", 0))
        kind = str(source_counters_at_least.get("kind", "+1/+1"))

        def _source_counters_at_least_ok(
            event: Any, context: Any, iid=instance_id, want=threshold, k=kind,
        ) -> bool:
            state = getattr(context, "state", None)
            obj = state.find_object(iid) if state is not None and iid is not None else None
            if obj is None:
                return False
            return int((obj.counters or {}).get(k, 0)) >= want

        predicates.append(_source_counters_at_least_ok)

    # "When you control no Swamps, sacrifice ~." (RULE 603.8 state trigger —
    # Bog Serpent / Sea Serpent / Dandân cycle). A `LEAVES_BATTLEFIELD`
    # trigger gated on the ability's controller currently controlling zero
    # permanents of the named printed land subtype — the same live
    # battlefield scan `effects.ConditionalEffect`'s own
    # ``controls_none_of_type`` gate uses, and the same "gate an ordinary
    # event on a state read rather than build a state-trigger subsystem"
    # rationale as `source_counters_at_least` just above.
    controls_none_of_type = trigger.get("controls_none_of_type")
    if controls_none_of_type is not None:
        controller_id = getattr(source, "controller_id", None)
        subtype_word = str(controls_none_of_type).lower()

        def _controls_none_ok(
            event: Any, context: Any, cid=controller_id, w=subtype_word,
        ) -> bool:
            state = getattr(context, "state", None)
            if state is None:
                return False
            # RULE 603.6a "look back in time": LEAVES_BATTLEFIELD fires while
            # the leaving permanent is *still* on the battlefield, so the
            # object that just left is excluded here — the check is "will
            # the controller control none of that type once this leave
            # completes".
            leaving_id = event.get("instance_id")
            return not any(
                o.instance_id != leaving_id
                and o.controller_id == cid
                and w in o.card.type_line.partition("—")[2].strip().lower().split()
                for o in state.battlefield
            )

        predicates.append(_controls_none_ok)

    # "Whenever ~ attacks a player who controls N or more lands, …" (Owlbear
    # Cub — RULE 508.1). Gate the ordinary `ATTACKS` event on the *defending*
    # player's land count, read live off the event's ``defending_player_id``.
    # Same "gate an event on a state read rather than a state-trigger
    # subsystem" rationale as `controls_none_of_type` just above.
    defender_lands_min = trigger.get("defender_controls_lands_at_least")
    if defender_lands_min is not None:
        want_lands = int(defender_lands_min)

        def _defender_lands_ok(
            event: Any, context: Any, want=want_lands,
        ) -> bool:
            state = getattr(context, "state", None)
            did = (event or {}).get("defending_player_id")
            if state is None or did is None:
                return False
            n = sum(
                1 for o in state.battlefield
                if o.controller_id == did
                and (getattr(o, "is_land", False)
                     or "land" in o.card.type_line.partition("—")[0].lower().split())
            )
            return n >= want

        predicates.append(_defender_lands_ok)

    # "Whenever ~ attacks a player, if no opponent has more life than that
    # player, …" (Baldur's Gate "attack whoever's behind" cycle — Guild
    # Artisan &c, PAR-32). RULE 603.4 intervening-if: the attacked player's
    # life is ≤ every *other* opponent's (of this ability's controller),
    # read live off the ATTACKS event's ``defending_player_id``.
    if trigger.get("attacked_player_has_lowest_life"):
        predicates.append(
            attacked_player_lowest_life_predicate(getattr(source, "controller_id", None))
        )

    # PAR-28 / RULE 702.169c Solved / 702.178a Max Speed on a *triggered*
    # ability: "[Ability text]. This ability triggers only if [condition]."
    # The same whitelisted `static_conditions` dict a static's `active_if`
    # carries, checked live at trigger time against the ability's own source
    # and controller (the replacement-effect and static-ability halves of
    # this vocabulary already gate this way — see `build_replacements`).
    trigger_active_if = trigger.get("active_if")
    if isinstance(trigger_active_if, dict):
        controller_id = getattr(source, "controller_id", None)

        def _trigger_active_if_ok(
            event: Any, context: Any, cond=trigger_active_if,
            src=source, cid=controller_id,
        ) -> bool:
            state = getattr(context, "state", None)
            return state is not None and condition_holds(cond, state, src, cid)

        predicates.append(_trigger_active_if_ok)

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

    # "…if an opponent controls three or more creatures, …" (Defense of the
    # Heart, MEC-43) — a RULE 603.4 intervening-if scoped to the board as a
    # whole (any single opponent meeting the threshold, not a sum across
    # all of them), checked live at trigger time the same as every other
    # predicate here.
    min_opponent_creatures = trigger.get("min_opponent_creatures")
    if min_opponent_creatures is not None:
        controller_id = getattr(source, "controller_id", None)
        threshold = int(min_opponent_creatures)

        def _min_opponent_creatures_ok(event: Any, context: Any, cid=controller_id, n=threshold) -> bool:
            state = getattr(context, "state", None)
            if state is None or cid is None:
                return False
            for player in state.players:
                if player.id == cid:
                    continue
                count = sum(1 for o in state.permanents_controlled_by(player.id) if o.is_creature)
                if count >= n:
                    return True
            return False

        predicates.append(_min_opponent_creatures_ok)

    # "…if you've cast an instant or sorcery spell this turn, …" (Rootha,
    # Mastering the Moment, PAR-60) — a RULE 603.4 intervening-if reading
    # `GameState.cast_instant_or_sorcery_this_turn` for this ability's own
    # controller (the same per-player flag PAR-10's statics read).
    if trigger.get("cast_instant_or_sorcery_this_turn"):
        controller_id = getattr(source, "controller_id", None)

        def _is_cast_this_turn_ok(event: Any, context: Any, cid=controller_id) -> bool:
            state = getattr(context, "state", None)
            if state is None or cid is None:
                return False
            return bool(
                getattr(state, "cast_instant_or_sorcery_this_turn", {}).get(cid, False)
            )

        predicates.append(_is_cast_this_turn_ok)

    # "…if you haven't completed Tomb of Annihilation, …" (Acererak the
    # Archlich, MEC-43) — a RULE 603.4 intervening-if reading `Player.
    # completed_dungeons` (RULE 309.7's own record of which named dungeons
    # this player has finished), scoped to this ability's own controller.
    not_completed_dungeon = trigger.get("not_completed_dungeon")
    if not_completed_dungeon:
        controller_id = getattr(source, "controller_id", None)
        dungeon_name = str(not_completed_dungeon)

        def _not_completed_dungeon_ok(event: Any, context: Any, cid=controller_id, name=dungeon_name) -> bool:
            state = getattr(context, "state", None)
            if state is None or cid is None:
                return False
            player = next((p for p in state.players if p.id == cid), None)
            if player is None:
                return False
            return name not in (getattr(player, "completed_dungeons", None) or [])

        predicates.append(_not_completed_dungeon_ok)

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

    # RULE 603.4 intervening-if on the *dying* creature's own last-known
    # state (Blight Curse batch) — checked at trigger time so an untriggered
    # ability never prompts for a target. ``dying_toughness_below``:
    # "…dies, if its toughness was less than 1, …" (Massacre Girl, Known
    # Killer). ``dying_had_counter``: "…dies, if it had a -1/-1 counter on
    # it, …" (Blowfly Infestation). Both read the DIES event's snapshotted
    # ``toughness`` / ``counters`` (RULE 400.7), fail closed if absent.
    dying_toughness_below = trigger.get("dying_toughness_below")
    if dying_toughness_below is not None:
        def _dying_toughness_ok(event: Any, context: Any, n=int(dying_toughness_below)) -> bool:
            t = event.get("toughness")
            return t is not None and int(t) < n
        predicates.append(_dying_toughness_ok)

    dying_had_counter = trigger.get("dying_had_counter")
    if dying_had_counter is not None:
        def _dying_had_counter_ok(event: Any, context: Any, kind=str(dying_had_counter)) -> bool:
            return int((event.get("counters") or {}).get(kind, 0)) > 0
        predicates.append(_dying_had_counter_ok)

    if not predicates:
        return None
    if len(predicates) == 1:
        return predicates[0]

    def _all(event: Any, context: Any) -> bool:
        return all(p(event, context) for p in predicates)

    return _all


#: ENG-29: which param on a given `EffectSpec.type` carries the RULE 603.1
#: "implicit subject" convention (``None`` → the ability's own source,
#: ``"attached_permanent"`` → whatever the source is currently attached to —
#: `TapEffect`/`PumpEffect`/`CopyPermanentEffect`'s own ``target_kind``,
#: `FightEffect`/`DamageEqualToPowerEffect`'s ``fighter_kind``/``dealer_kind``,
#: the *acting* side, not the RULE 115 ``target_kind``/``other_kind`` half
#: those last two also carry). Deliberately a narrow whitelist, not "rewrite
#: any ``target_kind: None``" — most effect types (`regenerate`/`exile`/
#: `return_to_hand`/`goad`/…) also default an absent/``None`` ``target_kind``
#: to their own source, but have no ``"attached_permanent"`` mode at all
#: (no matching `_attached_mode` branch in `game/effects/core.py`), so retargeting
#: them here would hand a real `TargetSpec` an unrecognized kind instead of
#: leaving them alone.
_ATTACHED_PERMANENT_RETARGET_FIELDS: dict[str, str] = {
    "tap": "target_kind",
    "pump": "target_kind",
    "copy_permanent": "target_kind",
    "fight": "fighter_kind",
    "damage_equal_to_power": "dealer_kind",
}

#: MEC-28's ``{"subject": "group"}`` sibling of the whitelist above — see
#: `_retarget_implicit_subject_effects`'s docstring for why it's `tap`-only
#: today rather than mirroring the wider attached-permanent list.
_GROUP_SUBJECT_RETARGET_FIELDS: dict[str, str] = {
    "tap": "target_kind",
}


def _retarget_implicit_subject_effects(
    effect_specs: list[EffectSpec], trigger: dict[str, Any]
) -> list[EffectSpec]:
    """RULE 303.4/301.5: "whenever equipped/enchanted creature `<verb>`, it
    `<effect>`." — the trigger *condition* already scopes correctly to the
    attached permanent (`_subject_condition`'s ``"attached_permanent"``
    branch), but a bare "it" in the *effect body* was parsed with no subject
    context at all (`parser/oracle/segmenter.py`'s generic trigger dispatch
    only unlocks ``self_subject=True`` for an exact ``{"subject": "self"}``
    condition), so it fell through to the same unconditional ``target_kind:
    None`` "it" recognition every self-acting handler uses regardless of that
    flag — silently resolving to the Equipment/Aura itself (Genji Glove's
    "untap it" untapping the Equipment, not the attacking creature).

    Fixed at bind time rather than parse time: rewriting *every* self-acting
    handler in `catalogue/handlers.py` to thread a richer subject context
    through `parse_effect_body` would touch dozens of unrelated handlers for
    one trigger-subject shape. Here, once, for exactly the effect types that
    already understand the ``"attached_permanent"`` sentinel.

    Deliberately scoped to the plain ``"attached_permanent"`` subject only —
    not its ``"self_or_attached_permanent"`` sibling (Simian Sling-shaped
    "whenever this creature or equipped creature becomes blocked"), where a
    bare "it" would need to resolve to *whichever* of the two actually fired
    the event, a dynamic per-firing resolution this static bind-time rewrite
    can't express. No shipped card combines that subject with a self-acting
    "it" effect body today, so leaving it unhandled fails closed rather than
    silently picking the wrong one.

    MEC-28: a ``{"subject": "group"}`` condition ("whenever a creature you
    control attacks alone, ... untap it.", Raiyuu-shaped) is the same "it"
    ambiguity one level removed — there's no static field to repoint at all,
    since *which* object matched varies every firing, so this rewrites
    ``target_kind: None`` to ``"trigger_subject"`` instead (`TapEffect`'s new
    mode reading `GameContext.trigger_event` live, the same idiom
    `GrantKeywordToTriggerSubjectEffect` already uses for Tyvar Kell's
    emblem) and additionally stamps ``trigger_event_key`` so the effect knows
    *which* event field names the acting object — `_subject_event_key`'s own
    per-event-type lookup, the same one the trigger *condition* side already
    uses to check whether it fired. Scoped to `tap` alone for now — no
    shipped card needs this retarget for `pump`/`fight`/`copy_permanent`/
    `damage_equal_to_power` yet, and extending those means confirming each
    one actually reads `trigger_event_key` the way `TapEffect` was just
    given, not assuming the shape transfers for free.
    """
    condition = trigger.get("condition") or {}
    subject = condition.get("subject")
    if subject == "attached_permanent":
        retarget_fields, retarget_value = _ATTACHED_PERMANENT_RETARGET_FIELDS, "attached_permanent"
    elif subject == "group":
        retarget_fields, retarget_value = _GROUP_SUBJECT_RETARGET_FIELDS, "trigger_subject"
    else:
        return effect_specs
    retargeted: list[EffectSpec] = []
    for e in effect_specs:
        field_name = retarget_fields.get(e.type)
        if field_name is not None and field_name in e.params and e.params[field_name] is None:
            params = dict(e.params)
            params[field_name] = retarget_value
            if retarget_value == "trigger_subject":
                params["trigger_event_key"] = _subject_event_key(trigger)
            retargeted.append(EffectSpec(e.type, params, condition=e.condition))
        else:
            retargeted.append(e)
    return retargeted


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

    # Parser specs carry an exact oracle-text clause as provenance. Hand-authored
    # catalogue specs deliberately leave it blank: their display text must come
    # from the bound card, never from an unofficial translation in source code.
    description = _ability_description(source, spec)

    if spec.ability_kind == "replacement":
        # A different whitelist (ReplacementRegistry, not EffectRegistry) —
        # each `EffectSpec.type` here names a replacement family (e.g.
        # "prevent_damage"), not a one-shot effect.
        replacements = build_replacements(spec.effects, source)
        for effect in replacements:
            if not effect.description:
                effect.description = description
        return replacements

    if spec.ability_kind == "enter_replacement":
        # RULE 614.1c/614.12: bound through `EffectRegistry` (unlike
        # "replacement"'s `ReplacementRegistry`) since these aren't pure
        # event-transform `ReplacementEffect`s.
        effects = build_effects(spec.effects, source)
        for effect in effects:
            if not effect.description:
                effect.description = description
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
    once_per_game = False  # PAR-28 RULE 702.177a Exhaust / Power-up
    powerup_cost_reduction = False  # PAR-28 Power-up
    from_hand = False  # PAR-28 RULE 702.57a Forecast
    activation_condition: Optional[dict[str, Any]] = None
    effect_specs = spec.effects
    if spec.ability_kind == "activated":
        if any(e.type == ONCE_PER_TURN_MARKER for e in effect_specs):
            once_per_turn = True
        if any(e.type == SORCERY_SPEED_MARKER for e in effect_specs):
            sorcery_speed_only = True
        if any(e.type == ONLY_DURING_YOUR_TURN_MARKER for e in effect_specs):
            only_during_your_turn = True
        if any(e.type == ACTIVATE_ONLY_ONCE_MARKER for e in effect_specs):
            once_per_game = True
        if any(e.type == POWERUP_COST_REDUCTION_MARKER for e in effect_specs):
            powerup_cost_reduction = True
        if any(e.type == FROM_HAND_MARKER for e in effect_specs):
            from_hand = True
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
                ACTIVATE_ONLY_ONCE_MARKER, POWERUP_COST_REDUCTION_MARKER,
                FROM_HAND_MARKER,
            )
        ]

    if spec.ability_kind == "triggered":
        assert spec.trigger is not None  # validate() guarantees this
        effect_specs = _retarget_implicit_subject_effects(effect_specs, spec.trigger)

    effects = build_effects(effect_specs, source)

    if spec.ability_kind == "spell_effect":
        return effects

    if spec.ability_kind == "triggered":
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
                modes_repeatable=bool(spec.modes.get("repeatable", False)) if spec.modes else False,
                modes_exhaust_per_turn=bool(spec.modes.get("exhaust_per_turn", False)) if spec.modes else False,
                modes_optional=bool(spec.modes.get("optional", False)) if spec.modes else False,
                modes_override=spec.modes.get("override") if spec.modes else None,
                # PAR-30 (Confusion in the Ranks) — "its controller chooses
                # …": `TriggeredAbility.controller_from_trigger_event`.
                controller_from_trigger_event=(
                    spec.trigger.get("chooser") == "trigger_subject_controller"
                ),
                condition=_trigger_condition(single_trigger, source),
                optional=spec.optional,
                controller_id=getattr(source, "controller_id", None),
                source=source,
                description=description,
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
                # RULE 601.2i (MEC-43): "When you cast this spell, …" is
                # the one trigger shape genuinely meant to fire while its
                # source is still on the **stack** — inferred purely from
                # the trigger's own shape (a `SPELL_CAST` event scoped to
                # ``{"subject": "self"}``), never from an ordinary "you"/
                # "group" condition that would *also* happen to match the
                # object's own casting (see `TriggeredAbility.
                # functions_from_stack`'s own docstring for why that
                # distinction matters).
                functions_from_stack=(
                    event == EventType.SPELL_CAST
                    and isinstance(spec.trigger.get("condition"), dict)
                    and spec.trigger["condition"].get("subject") == "self"
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
                effect.description = description
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
    if any(isinstance(e, PutSelfOntoBattlefieldFromHandEffect) for e in effects):
        # "{N}: Put this card from your hand onto the battlefield." (Talon
        # Gates of Madara-shaped) — same inference, `hand_zone`'s own
        # branch of `can_activate`.
        cost.hand_zone = True
    if from_hand:
        # PAR-28 / RULE 702.57a: a forecast ability is activated from the
        # card's hand — same `hand_zone` branch of `can_activate`.
        cost.hand_zone = True
    activated_modes = None
    if spec.modes:
        # RULE 700.2 on an *activated* ability (MEC-43, Umezawa's Jitte's
        # "Remove a charge counter: Choose one — …") — the same
        # `_build_mode_entries` a modal spell/triggered ability already
        # uses. Deliberately scoped to the plain "choose one" shape only:
        # `GameEngine._resolve_activation_mode` (the only consumer of
        # `ActivatedAbility.modes`) has no "or both"/"choose N or more"
        # branch, since no activated ability in this cache needs one yet —
        # fail loudly here rather than silently mis-binding a shape the
        # engine side can't actually resolve.
        if spec.modes.get("choose", 1) != 1 or spec.modes.get("or_both") or spec.modes.get("at_least"):
            raise NotImplementedError(
                "modal activated abilities only support plain 'choose one' so far"
            )
        activated_modes = _build_mode_entries(spec.modes, source)
    if powerup_cost_reduction:
        cost.powerup_cost_reduction = True
    return ActivatedAbility(
        effects=effects,
        cost=cost,
        source=source,
        description=description,
        once_per_turn=once_per_turn,
        modes=activated_modes,
        once_per_game=once_per_game,
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


def _ability_description(source: Any, spec: AbilitySpec) -> str:
    """Use canonical card text; parser provenance is a fallback."""
    card = getattr(source, "card", source)
    return str(getattr(card, "oracle_text", "") or spec.raw_text or "")


def _keyword_activated_ability(obj: Any, spec: AbilitySpec) -> Optional[ActivatedAbility]:
    """Create a live activated ability for attach-style keywords like Equip,
    and for a card's own bare RULE 702.28/702.29 Cycling (PAR-9)."""
    keyword = spec.keyword or {}
    name = str(keyword.get("name") or "")
    if name == "cycling":
        return _cycling_activated_ability(obj, spec, keyword)
    if name == "crew":
        return _crew_activated_ability(obj, spec, keyword)
    if name == "saddle":
        return _saddle_activated_ability(obj, spec, keyword)
    if name == "station":
        return _station_activated_ability(obj, spec)
    if name == "specialize":
        return _specialize_activated_ability(obj, spec, keyword)
    if name in {"unearth", "embalm", "eternalize"}:
        return _graveyard_keyword_activated_ability(obj, spec, keyword)
    if name not in {"equip", "fortify", "reconfigure"}:
        return None

    cost_text = keyword.get("cost") or "{0}"
    target_kind = "permanent"
    # RULE 301.5c/306.2/702.151b: none of Equip/Fortify/Reconfigure tap the
    # source as part of their cost — it's exactly the printed cost, payable
    # (and re-payable) any number of times at sorcery speed. Don't graft a
    # {T} onto it: that would tap the permanent and block re-activation.
    cost = parse_activation_cost(cost_text)
    # Bug report, 2026-09-04: all three keywords' own reminder text ends
    # "Activate only as a sorcery." (RULE 702.6c/702.32b/702.151c) — the
    # comment above already said as much, but nothing here ever actually
    # set the flag `GameEngine._sorcery_speed_ok` checks, so Equip/Fortify/
    # Reconfigure were legal to activate at instant speed.
    cost.sorcery_speed_only = True
    return ActivatedAbility(
        effects=[AttachEffect(target_kind=target_kind)],
        cost=cost,
        source=obj,
        description=_ability_description(obj, spec) or f"{name}",
        attach_kind=name,
    )


#: RULE 702.41 Affinity — quality word (lower-cased, trailing "s" trimmed)
#: → the `continuous.count_selector` name for "for each `<quality>` you
#: control". Only the qualities `count_selector` actually supports; an
#: unrecognised one (a rare tribal "Affinity for Dwarves") synthesizes
#: nothing, leaving the keyword recognised-but-inert rather than wrong
#: (fail-closed, PAR-23).
_AFFINITY_SELECTORS: dict[str, str] = {
    "artifact": "artifacts_you_control",
    "creature": "creatures_you_control",
    "land": "lands_you_control",
    "plain": "lands_you_control_of_type_plains",
    "island": "lands_you_control_of_type_island",
    "swamp": "lands_you_control_of_type_swamp",
    "mountain": "lands_you_control_of_type_mountain",
    "forest": "lands_you_control_of_type_forest",
}


def _attach_affinity_static(obj: Any, spec: AbilitySpec) -> None:
    """RULE 702.41: "Affinity for `<quality>`" — "This spell costs {1} less
    to cast for each `<quality>` you control." Synthesized as a
    ``layer="cost"``/``affects="self"`` `StaticAbility` on ``obj.static_
    effects`` with ``params={"generic": 1, "per": <count_selector>}`` —
    exactly the shape `continuous.self_cost_reduction_for` /
    `_cost_static_amount` already read for a hand-authored Delve/Affinity-
    style reduction, just now driven by the keyword itself (PAR-23).
    """
    keyword = spec.keyword or {}
    if str(keyword.get("name") or "") != "affinity":
        return
    quality = str(keyword.get("quality") or "").strip().lower()
    quality = quality[:-1] if quality.endswith("s") else quality  # "artifacts" → "artifact"
    selector = _AFFINITY_SELECTORS.get(quality)
    if selector is None:
        return
    obj.static_effects.append(
        StaticAbility(
            layer="cost",
            affects="self",
            params={"generic": 1, "per": selector},
            source=obj,
            description=_ability_description(obj, spec) or f"Affinity for {keyword.get('quality')}",
        )
    )


def _graveyard_keyword_activated_ability(
    obj: Any, spec: AbilitySpec, keyword: dict[str, Any]
) -> Optional[ActivatedAbility]:
    """RULE 702.84 Unearth / 702.128 Embalm / 702.129 Eternalize — three
    `KeywordShape.COST` keywords whose whole rules text is a sorcery-speed
    activated ability that functions from the *graveyard* (PAR-25). All
    were parser-recognized (a bare keyword-line claim) but bound to
    nothing, the same "recognized but inert" gap PAR-9 closed for Cycling
    and MEC-29/MEC-40 for Crew/Saddle.

    `ActivationCost.graveyard_zone` (the source must sit in the player's
    graveyard — reused from PAR-10's "return this from your graveyard"
    activated-ability family) + `sorcery_speed_only`. Unearth returns the
    card itself; Embalm/Eternalize exile it and make a modified token copy.
    """
    name = str(keyword.get("name") or "")
    cost = parse_activation_cost(keyword.get("cost") or "{0}")
    cost.graveyard_zone = True
    cost.sorcery_speed_only = True
    if name == "unearth":
        effects: list[GameEffect] = [UnearthEffect(source=obj)]
    elif name == "eternalize":
        # RULE 702.129a: the token is a 4/4 (black Zombie) copy.
        effects = [EmbalmEternalizeEffect(set_power=4, set_toughness=4, source=obj)]
    else:  # embalm — RULE 702.128a: same P/T as the card, a white Zombie.
        effects = [EmbalmEternalizeEffect(source=obj)]
    return ActivatedAbility(
        effects=effects,
        cost=cost,
        source=obj,
        description=_ability_description(obj, spec) or name.capitalize(),
    )


def _specialize_activated_ability(
    obj: Any, spec: AbilitySpec, keyword: dict[str, Any]
) -> Optional[ActivatedAbility]:
    """MEC-48: "Specialize {cost}" — an Arena-only digital keyword (no paper
    CR) = "{cost}, Discard a card: This permanent specializes. Activate only
    as a sorcery."

    Like Cycling/Crew/Unearth before it, the keyword was parser-recognized
    (a bare keyword-line claim) but bound to nothing, so Specialize never
    became an offered action. The cost is the printed mana plus a
    discard-one-card additional cost (`ActivationCost.discard = 1`, the same
    `_resolve_discard_cost` auto-pick path a battlefield "discard a card"
    cost uses) at sorcery speed. The effect is `SpecializeEffect` — a
    designation + `EventType.SPECIALIZED`, no characteristic swap (the five
    specialized faces aren't in this repo's card seed).
    """
    cost_text = keyword.get("cost")
    if not cost_text:
        return None
    cost = parse_activation_cost(f"{cost_text}, Discard a card")
    cost.sorcery_speed_only = True  # RULE-analogue: "Activate only as a sorcery."
    return ActivatedAbility(
        effects=[SpecializeEffect(source=obj)],
        cost=cost,
        source=obj,
        description=_ability_description(obj, spec) or "Specialize",
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
        description=_ability_description(obj, spec) or "Cycling",
    )


def _crew_activated_ability(
    obj: Any, spec: AbilitySpec, keyword: dict[str, Any]
) -> Optional[ActivatedAbility]:
    """RULE 702.122a: "Crew N" — "Tap any number of other untapped creatures
    you control with total power N or greater: This permanent becomes an
    artifact creature until end of turn." Like Cycling before PAR-9, "Crew N"
    was recognized by the parser (a bare keyword spec, satisfying the
    coverage gate) but bound to nothing — `grep -rn "crewed_by"` in `game/`/
    `models/` found no state at all before MEC-29 — so no Vehicle ever
    actually became a creature through it.

    The cost (``ActivationCost.crew_power``) is resolved by `GameEngine.
    _resolve_crew_cost`/`_crew_pool`, a threshold "any number from a pool"
    choice distinct from `tap_others`' exact count; paying it also stamps
    the tapped creatures' ids onto ``obj.crewed_by_ids`` (RULE 702.122c),
    read by the `"crewed_by_self"` RULE 603.1 group-subject trigger
    condition (`_build_group_ok`) for "whenever a Vehicle crewed by ~ this
    turn attacks"-shaped abilities (Balthier and Fran).

    The effect reuses `GrantUntilEffect` exactly as an oracle-parsed "until
    end of turn" static grant would (``type_change``, ``add_types:
    ["creature"]``, ``target_kind=None`` — a self-targeted grant, per
    `GrantUntilEffect.apply`'s ``affects="self"`` default): RULE 702.122a's
    "becomes an artifact creature" is layer 4 (RULE 613.2d), so it goes
    through the same RULE 613 layer engine as any other type-change static
    rather than a bespoke flag, and correctly stacks with an existing
    printed artifact type instead of replacing it.
    """
    n = keyword.get("n")
    if not isinstance(n, int) or n <= 0:
        return None
    cost = ActivationCost(crew_power=n)
    # RULE 208.1: `Card.power`/`toughness` are refused on a noncreature
    # (`Card.__init__`'s own invariant), so a Vehicle's printed P/T lives in
    # `vehicle_power`/`vehicle_toughness` instead — without passing them
    # through here, ``type_change`` would leave the crewed permanent with no
    # power/toughness at all and RULE 613.3b's copiable-values default (0)
    # would apply, dying to RULE 704.5f the instant the next state-based
    # action check ran.
    type_change_params: dict[str, Any] = {"add_types": ["creature"]}
    vehicle_power = getattr(obj.card, "vehicle_power", None)
    vehicle_toughness = getattr(obj.card, "vehicle_toughness", None)
    if vehicle_power is not None:
        type_change_params["power"] = vehicle_power
    if vehicle_toughness is not None:
        type_change_params["toughness"] = vehicle_toughness
    effects: list[GameEffect] = [
        GrantUntilEffect(
            static={"type": "type_change", "params": type_change_params},
            duration="end_of_turn",
            target_kind=None,
            source=obj,
        )
    ]
    return ActivatedAbility(
        effects=effects,
        cost=cost,
        source=obj,
        description=_ability_description(obj, spec) or f"Crew {n}",
    )


def _saddle_activated_ability(
    obj: Any, spec: AbilitySpec, keyword: dict[str, Any]
) -> Optional[ActivatedAbility]:
    """RULE 702.171a: "Saddle N" — "Tap any number of other untapped
    creatures you control with total power N or greater: This permanent
    becomes saddled until end of turn." Same "recognized but inert"
    history as Crew before MEC-29/`_crew_activated_ability` — bare keyword
    recognition satisfied the coverage gate, but nothing bound it to any
    real behaviour (MEC-40).

    The cost (``ActivationCost.saddle_power``) reuses `GameEngine.
    _resolve_crew_cost`/`_crew_pool` unchanged (`activation_mixin.py`'s own
    dispatch checks ``crew_power`` and ``saddle_power`` as two independent
    fields, both routed through the same pool-selection helpers — RULE
    702.171a is worded identically to 702.122a's own "any number of other
    untapped creatures… total power N or greater"). RULE 702.171d:
    sorcery-speed only.
    """
    n = keyword.get("n")
    if not isinstance(n, int) or n <= 0:
        return None
    cost = ActivationCost(saddle_power=n, sorcery_speed_only=True)
    return ActivatedAbility(
        effects=[BecomeSaddledEffect(source=obj)],
        cost=cost,
        source=obj,
        description=_ability_description(obj, spec) or f"Saddle {n}",
    )


def _station_activated_ability(obj: Any, spec: AbilitySpec) -> Optional[ActivatedAbility]:
    """RULE 702.184a/721 Station: "Tap another untapped creature you
    control: Put a number of charge counters on this permanent equal to
    the tapped creature's power. Activate only as a sorcery." "Station" is
    a bare `FLAG` keyword (no ``n``/``cost`` parameter, unlike Crew/Saddle's
    own printed threshold) — the whole ability is fixed, so no keyword
    parameter is read here at all.

    The cost (``ActivationCost.station``) is resolved by `GameEngine.
    _resolve_station_cost`/`_crew_pool` — an exact-count-one choice from
    the same "other untapped creatures you control" pool Crew/Saddle
    already share, unlike their own "any subset meeting a power threshold"
    shape. RULE 721.4: no once-per-turn cap — repeatable regardless of how
    many charge counters are already on the permanent, so (unlike Class's
    own level-up ability) this needs no ``activation_condition`` gate at
    all beyond the cost itself always being payable again.

    The effect reuses the plain, already-registered ``"add_counters"``
    type (``kind="charge"``, RULE 702.184a's own counter kind — see
    `game/ability_catalogue/black.py` for another card that already
    puts charge counters on itself the same way) with
    ``amount_from_count_selector="station_tapped_power"`` — the amount is
    read fresh off `GameObject.station_tapped_power`, stamped by the cost
    payment itself (`GameEngine._pay_activation_cost`'s own ``station``
    branch) rather than a fixed number, so no new `GameEffect` subclass is
    needed for this at all.

    RULE 702.184c's rare "as though its power were equal to a different
    value" static modifier (a hypothetical "Tapestry Warden"-shaped card in
    the rule text's own example) is a deliberate, documented simplification
    — no real printed card checked against the ~35k-card Oracle cache uses
    it; this reads the tapped creature's own printed/derived power only.
    """
    charge_effect = EffectRegistry.create("add_counters", {
        "kind": "charge", "amount_from_count_selector": "station_tapped_power",
    })
    charge_effect.source = obj  # untargeted `AddCountersEffect` defaults its recipient to `self.source`
    cost = ActivationCost(station=True, sorcery_speed_only=True)
    return ActivatedAbility(
        effects=[charge_effect],
        cost=cost,
        source=obj,
        description=_ability_description(obj, spec) or "Station",
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
            description=_ability_description(obj, spec) or "Soulbond",
        ),
        TriggeredAbility(
            trigger_event=EventType.ENTERS_BATTLEFIELD,
            effects=[SoulbondPairEffect(source=obj)],
            condition=_other_creature_you_control_condition(obj),
            optional=True,
            controller_id=getattr(obj, "controller_id", None),
            source=obj,
            description=_ability_description(obj, spec) or "Soulbond",
        ),
    ]


def _kw_living_weapon(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    return [
        TriggeredAbility(
            trigger_event=EventType.ENTERS_BATTLEFIELD,
            effects=[LivingWeaponEffect(source=obj)],
            condition=_self_only_condition(getattr(obj, "instance_id", None)),
            source=obj,
            description=_ability_description(obj, spec) or "Living weapon",
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
            description=_ability_description(obj, spec) or f"Fading {n}",
        )
    ]


def _kw_vanishing(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    if n is None:
        return []
    # RULE 702.61b: "At the beginning of your upkeep, remove a time counter
    # from this permanent. When the last is removed, sacrifice it." Same
    # upkeep-trigger shape as Fading (`_kw_fading`), just a "time" counter
    # and `sacrifice_on_last_removed=True` — see `RemoveCounterOrSacrifice
    # Effect`'s docstring for the off-by-one this avoids. The entry counters
    # themselves (RULE 702.61a) are placed by `RulesEngine.
    # _apply_entry_counters`, alongside every other enters-with-counters
    # clause.
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
            effects=[RemoveCounterOrSacrificeEffect(
                kind="time", source=obj, sacrifice_on_last_removed=True,
            )],
            condition=_your_upkeep,
            controller_id=controller_id,
            source=obj,
            description=_ability_description(obj, spec) or f"Vanishing {n}",
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
            description=_ability_description(obj, spec) or f"Cumulative upkeep {cost}",
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
            description=_ability_description(obj, spec) or f"Renown {n}",
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
            description=_ability_description(obj, spec) or f"Annihilator {n}",
        )
    ]


def _kw_haunt(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    """RULE 702.55a's inherent dies trigger; the card-specific payoff when
    the haunted creature dies is represented separately by PAR-59."""
    return [
        TriggeredAbility(
            trigger_event=EventType.DIES,
            effects=[HauntEffect(source=obj)],
            condition=_self_only_condition(getattr(obj, "instance_id", None)),
            source=obj,
            description=_ability_description(obj, spec) or "Haunt",
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
            description=_ability_description(obj, spec) or f"Afflict {n}",
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
            description=_ability_description(obj, spec) or f"Bushido {n}",
        ),
        TriggeredAbility(
            trigger_event=EventType.BECOMES_BLOCKED,
            effects=[PumpEffect(power=n, toughness=n)],
            condition=condition,
            source=obj,
            description=_ability_description(obj, spec) or f"Bushido {n}",
        ),
    ]


def _kw_prowess(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    """RULE 702.108a Prowess — "Whenever you cast a noncreature spell, this
    creature gets +1/+1 until end of turn." Parser-recognized as a flag
    keyword but bound to nothing before PAR-24, so the ~50 UNMODELED and
    ~58 MODELED cache cards carrying it were all inert.

    "You" is read live off ``obj.controller_id`` in the condition (not baked
    at bind time) so a control-change hands the trigger to the new
    controller, RULE 702.108b. "Noncreature" reads the `SPELL_CAST` event's
    own ``object_types`` payload (`RulesEngine._cast_spell`).
    """

    def _cast_noncreature_you(event: Any, context: Any, src=obj) -> bool:
        if event.get("player_id") != getattr(src, "controller_id", None):
            return False
        return "creature" not in (event.get("object_types") or [])

    return [
        TriggeredAbility(
            trigger_event=EventType.SPELL_CAST,
            effects=[PumpEffect(power=1, toughness=1)],
            condition=_cast_noncreature_you,
            source=obj,
            description=_ability_description(obj, spec) or "Prowess",
        )
    ]


def _kw_exalted(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    """RULE 702.83a Exalted — "Whenever a creature you control attacks
    alone, that creature gets +1/+1 until end of turn." The lone-attacker
    aggregate `EventType.ATTACKS_ALONE` (`GameEngine._fire_attacks_alone_
    event`) already carries the attacker's ``player_id`` (its controller)
    and ``instance_id``; ``PumpEffect.trigger_subject`` pumps that object,
    "that creature", rather than the source (which may not even be the one
    attacking). RULE 702.83c: each instance triggers separately, which the
    Sublime-Archangel-style "other creatures you control have exalted"
    layer-6 grant already produces as a second keyword instance.
    """

    def _ally_attacks_alone(event: Any, context: Any, src=obj) -> bool:
        return event.get("player_id") == getattr(src, "controller_id", None)

    return [
        TriggeredAbility(
            trigger_event=EventType.ATTACKS_ALONE,
            effects=[PumpEffect(power=1, toughness=1, trigger_subject=True)],
            condition=_ally_attacks_alone,
            source=obj,
            description=_ability_description(obj, spec) or "Exalted",
        )
    ]


def _kw_battle_cry(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    """RULE 702.92a Battle Cry — "Whenever this creature attacks, each
    other attacking creature gets +1/+0 until end of turn." A self-only
    `ATTACKS` trigger whose effect is an untargeted group pump over the
    ``other_attacking_creatures`` selector (`continuous.group_selector_
    objects`, PAR-24) — every attacker except this one, regardless of
    controller (multiplayer edge, matching the literal text).
    """
    condition = _self_only_condition(getattr(obj, "instance_id", None))
    return [
        TriggeredAbility(
            trigger_event=EventType.ATTACKS,
            effects=[PumpEffect(power=1, toughness=0, selector="other_attacking_creatures")],
            condition=condition,
            source=obj,
            description=_ability_description(obj, spec) or "Battle cry",
        )
    ]


def _kw_mentor(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    """RULE 702.134a Mentor — "Whenever this creature attacks, put a +1/+1
    counter on target attacking creature with lesser power." A self-only
    `ATTACKS` trigger with a *targeted* `AddCountersEffect`: the target is
    an attacking creature whose power is strictly less than this creature's
    own, expressed as a `matches_object_filter` ``creature_filter``
    (``power_vs_reference: "less"`` anchored on the ability's source —
    PAR-24's `targeting._creature_matches_filter` reference pass-through).
    RULE 702.134b: multiple instances trigger separately.
    """
    condition = _self_only_condition(getattr(obj, "instance_id", None))
    return [
        TriggeredAbility(
            trigger_event=EventType.ATTACKS,
            effects=[
                AddCountersEffect(
                    amount=1,
                    kind="+1/+1",
                    target_kind="creature",
                    creature_filter={"attacking": True, "power_vs_reference": "less"},
                )
            ],
            condition=condition,
            source=obj,
            description=_ability_description(obj, spec) or "Mentor",
        )
    ]


def _kw_backup(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    """RULE 702.165a Backup N — "When this creature enters, put N +1/+1
    counters on target creature." (PAR-26 — the keyword was parser-
    recognised but placed no counters at all, `parser_probe.py card "Bola
    Slinger"`.)

    The counter-placement half only. RULE 702.165a's "If it's another
    creature, it gains the following abilities until end of turn." is a
    documented simplification — the "copy this creature's other abilities
    to the target" grant is a separate, un-built primitive (a resolve-time
    ability snapshot, MEC-23-shaped) — so a Backup creature's *own* other
    abilities still work, they just aren't lent out.

    ``target_kind="creature_including_self"`` because RULE 702.165a
    explicitly allows targeting the source itself (the common line: it
    entered alone).
    """
    if n is None:
        return []
    n = int(n)
    return [
        TriggeredAbility(
            trigger_event=EventType.ENTERS_BATTLEFIELD,
            effects=[AddCountersEffect(
                amount=n, kind="+1/+1", target_kind="creature_including_self",
            )],
            condition=_self_only_condition(getattr(obj, "instance_id", None)),
            source=obj,
            description=_ability_description(obj, spec) or f"Backup {n}",
        )
    ]


def _kw_firebending(obj: Any, spec: AbilitySpec, n: Any) -> list[TriggeredAbility]:
    """RULE 702.189 (approx) Firebending N (Doctor Who / Avatar: The Last
    Airbender) — "Whenever this creature attacks, add {R}×N. This mana lasts
    until end of combat."

    A self-only `ATTACKS` triggered **mana** ability (RULE 605.4 —
    resolves off-stack, so the {R} is spendable in the same combat). The
    "lasts until end of combat" note is a **documented simplification**:
    the mana is added to the pool now and empties at the ordinary step
    boundary rather than being tagged with a combat-scoped lifetime.

    A second, ordinary (stack-using) self-only `ATTACKS` trigger carries a
    `RecordBendEffect` — attacking with a Firebending creature is how a
    player "firebends" in the Avatar set (RULE 701.6x), and Avatar Aang's
    "whenever you … firebend" trigger reads `EventType.BENT`. Kept separate
    from the mana ability so the latter stays a pure mana effect (RULE
    605.4) and the marker still fires when N is 0 (Firebending X, X=0).

    Only reached from a *printed* Firebending keyword line. A *granted*
    "gains firebending N" (Sozin's Comet, Fire Nation Palace) needs
    parametric keyword grants — ENG-46 — so those cards stay UNMODELED
    (PAR-30).
    """
    if n is None:
        return []
    n = int(n)
    self_only = _self_only_condition(getattr(obj, "instance_id", None))
    return [
        TriggeredAbility(
            trigger_event=EventType.ATTACKS,
            effects=[AddManaEffect(colors=["R"] * n)],
            condition=self_only,
            source=obj,
            mana_ability=True,
            description=_ability_description(obj, spec) or f"Firebending {n}",
        ),
        TriggeredAbility(
            trigger_event=EventType.ATTACKS,
            effects=[RecordBendEffect(kind="firebend", source=obj)],
            condition=_self_only_condition(getattr(obj, "instance_id", None)),
            source=obj,
            description="Firebending — du feuerbändigst",
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
    "vanishing": _kw_vanishing,
    "cumulative_upkeep": _kw_cumulative_upkeep,
    "renown": _kw_renown,
    "annihilator": _kw_annihilator,
    "haunt": _kw_haunt,
    "afflict": _kw_afflict,
    "bushido": _kw_bushido,
    "prowess": _kw_prowess,
    "exalted": _kw_exalted,
    "battle_cry": _kw_battle_cry,
    "mentor": _kw_mentor,
    "backup": _kw_backup,
    "firebending": _kw_firebending,
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


def parametric_keyword_triggered_abilities(
    obj: Any, name: str, n: Any
) -> list[TriggeredAbility]:
    """ENG-31: synthesize the triggered abilities for a *granted* parametric
    keyword — "target creature gains firebending N until end of turn" (Fire
    Nation Palace), "creatures you control have firebending N" (Sozin's
    Comet). The printed-keyword path runs the same
    `_KEYWORD_TRIGGERED_BUILDERS` at bind-on-load via
    `_keyword_triggered_abilities`; a *grant* has no bind step, so
    `continuous._apply_layer_6_ability` calls this every recompute onto
    `GameObject._granted_triggered_abilities`. Only the keywords whose RULE
    702 text *is* a triggered ability (firebending / annihilator / afflict /
    bushido) have a builder; anything else returns ``[]``.
    """
    builder = _KEYWORD_TRIGGERED_BUILDERS.get(str(name))
    if builder is None:
        return []
    spec = AbilitySpec("keyword", keyword={"name": str(name), "n": n})
    return builder(obj, spec, n)


def _build_mode_entries(modes: dict[str, Any], source: Any) -> list[dict[str, Any]]:
    """Bind each mode's effects (RULE 700.2) into ``{"effects": [GameEffect,
    ...], "description": str}`` entries, one per printed mode — shared by a
    modal spell's ``obj.spell_modes`` (`_attach_modes`) and a modal
    triggered ability's own ``TriggeredAbility.modes``
    (`bind_ability`'s ``triggered`` branch).

    A ``"cost"`` key is added per entry when ``modes`` carries
    ``mode_costs`` (RULE 702.172a Spree, MEC-31 — a raw mana-cost string
    per mode, parallel to ``options``/``descriptions``), read by
    `GameEngine._modal_extra_cost` to price a chosen mode combination on
    top of the spell's own printed cost. Absent for every other modal
    shape, same as before this existed.
    """
    mode_costs = modes.get("mode_costs") or []
    entries = []
    for i, (option, description) in enumerate(
        zip(modes.get("options", []), modes.get("descriptions") or [])
    ):
        entry: dict[str, Any] = {"effects": build_effects(option, source), "description": description}
        if i < len(mode_costs) and mode_costs[i]:
            entry["cost"] = mode_costs[i]
        entries.append(entry)
    return entries


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
    obj.spell_modes_repeatable = bool(modes.get("repeatable", False))
    obj.spell_modes_override = modes.get("override")
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
            # PAR-30 / RULE 601.2b: "as an additional cost to cast this
            # spell, **you may** waterbend {N}." — offered as its own cast
            # variant, `GameObject.additional_cost_paid` recording whether it
            # was taken (`game/engine/casting_mixin.py`).
            if spec.additional_cost_optional:
                obj.additional_cast_cost_optional = True
        if spec.conditional_flash:
            spec.validate()
            obj.conditional_flash = spec.conditional_flash
        if spec.cast_timing_restriction:
            spec.validate()
            obj.cast_timing_restriction = spec.cast_timing_restriction
        if spec.flash_extra_cost:
            spec.validate()
            obj.flash_extra_cost = spec.flash_extra_cost
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
        if spec.cast_mana_source_restriction:
            # PAR-19: "Spend only mana produced by basic lands/creatures to
            # cast this spell." (Imperiosaur/Myr Superion) — a standing
            # restriction on the ordinary cast, read by `RulesEngine.
            # cast_spell`/`GameEngine.can_cast` via `getattr`, same
            # dynamic-attribute convention as `alt_cast_cost`.
            spec.validate()
            obj.mana_source_kind_restriction = spec.cast_mana_source_restriction
        if spec.cast_x_color_restriction:
            # "Spend only <color> mana on X." (Drain Life, MEC-43) — the
            # X-only sibling of `cast_mana_source_restriction` just above,
            # same dynamic-attribute convention, read by `GameEngine.
            # effective_cast_cost`'s `{X}`-resolution branch.
            spec.validate()
            obj.x_spend_color_restriction = spec.cast_x_color_restriction
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
            _attach_affinity_static(obj, spec)
            if str((spec.keyword or {}).get("name") or "") == "ninjutsu":
                # RULE 702.49a Ninjutsu (PAR-26): "[cost], Return an
                # unblocked attacker you control to hand: Put this card onto
                # the battlefield from your hand tapped and attacking." A
                # combat-timed special action (`GameEngine.ninjutsu`,
                # offered during the declare-blockers step) — its cost is
                # pure mana here, read off `obj.ninjutsu_cost`.
                obj.ninjutsu_cost = ManaCost.parse((spec.keyword or {}).get("cost") or "{0}")
            if str((spec.keyword or {}).get("name") or "") == "miracle":
                # RULE 702.94a Miracle (PAR-26): "You may cast this card for
                # its miracle cost when you draw it if it's the first card
                # you've drawn this turn." The cast half is a RULE 118.9-
                # style alternative cost (`obj.alt_cast_cost`); the draw
                # window is armed by `draw_discard_mixin._arm_miracle` and
                # `_offer_cast` gates the offer on `obj.miracle_armed`.
                obj.alt_cast_cost = parse_activation_cost((spec.keyword or {}).get("cost") or "{0}")
                obj.miracle = True
            if str((spec.keyword or {}).get("name") or "") == "madness":
                # RULE 702.35a Madness (PAR-26): "If you discard this card,
                # exile it instead of putting it into your graveyard. When
                # you do, you may cast it by paying its madness cost." The
                # cast half is a RULE 118.9-style alternative cost
                # (`obj.alt_cast_cost`, reused from Force of Will) — the
                # discard→exile interception + "to graveyard if not cast"
                # delayed trigger live in `draw_discard_mixin._maybe_madness`.
                obj.alt_cast_cost = parse_activation_cost((spec.keyword or {}).get("cost") or "{0}")
                obj.madness = True
            if str((spec.keyword or {}).get("name") or "") == "dash":
                # RULE 702.109 Dash (PAR-26): "You may cast this spell for
                # its dash cost." — modeled as a RULE 118.9-style
                # alternative cast cost (`obj.alt_cast_cost`, the
                # Force-of-Will machinery — offer/dispatch/payment all
                # already wired), plus a ``dash`` marker so resolution
                # grants haste (702.109c) and arms the "return to hand at
                # the beginning of the next end step" delayed trigger
                # (702.109d). Dash's cost is pure mana, so it needs mana in
                # the pool (the `alt_cost` path skips auto-tap) — a known
                # UX papercut, not a rules gap.
                obj.alt_cast_cost = parse_activation_cost((spec.keyword or {}).get("cost") or "{0}")
                obj.dash = True
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
            if str(keyword.get("name") or "") == "absorb":
                # RULE 702.64 (MEC-30): "Absorb N" ("If a source would deal
                # damage to this creature, prevent N of that damage.") — a
                # numbered keyword bound straight onto `obj.replacement_
                # effects`, no `AbilitySpec`/oracle-text detour needed since
                # its whole behaviour is the parameter itself. Unlike Ward
                # (fully bespoke/procedural, `RulesEngine.check_ward`) or the
                # triggered-only `_KEYWORD_TRIGGERED_BUILDERS` table just
                # below, this is the first keyword bound directly onto a
                # `ReplacementEffect` — reuses the same `"prevent_damage"`
                # factory an oracle-parsed standing shield (the Sphere
                # cycle/Shield of the Realm) binds through.
                n = int(keyword.get("n", 0) or 0)
                if n > 0:
                    effect = ReplacementRegistry.create("prevent_damage", {"to": "self", "amount": n})
                    effect.source = obj
                    obj.replacement_effects.append(effect)
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
                if effect.__class__.__name__ == "EstablishDayOnEntryEffect":
                    obj.establishes_day_on_entry = True
                    continue
                if isinstance(
                    effect,
                    (
                        ChooseCreatureTypeReplacement,
                        ChooseColorReplacement,
                        ChooseNamedModeReplacement,
                        ChooseBasicLandTypeReplacement,
                        ChooseCardNameReplacement,
                        ChooseNumberReplacement,
                        ChooseOpponentReplacement,
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
    from ..ability_catalogue import specs_for

    specs = specs_for(getattr(obj, "card", None))
    if specs:
        attach_to_object(obj, specs)
