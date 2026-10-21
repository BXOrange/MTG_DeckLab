"""Keyword pump/grant/loss and protection rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import re

from ..clause_reading import ClauseReading
from typing import Any, Optional
from ..clause_primitives import grantable_flag_slug, split_keywords_with_parametric
from ..count_phrase import parse_amount_phrase
from ..static_handlers import quoted_ability_grant_effects, quoted_ability_grant_effects_list
from ..subgrammars import (
    DEVOTION,
    devotion_selector,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    TARGET,
    target_kind_allowed,
    target_is_optional,
)
from ...normalize import SELF
from ...spec import EffectSpec, GROUP_SUBJECT_KEY_SENTINEL
from .shared import (
    ANY_NUMBER_TARGET_CAP,
    BIA_KEYWORD_LIST,
    compile_clause,
    CREATURE_FILTER_KEYWORD_WORDS,
    EffectHandler,
    MULTI_TARGET_ALT,
    multi_target_params,
    MULTI_TARGET_QUANTIFIER,
    MULTI_TARGET_QUANTIFIER_X,
    PREV_SUBJECT_SINGULAR,
    PREVIOUS_SUBJECT,
    PT_DELTA,
    pump_,
    pump_target,
    pump_target_creature_filter,
    renamed_target_count,
    signed_int,
    SUBJECT,
    subject_handlers,
    temporary_keyword_change,
    THEN,
    token_keywords,
)


#: "When you next cast an instant or sorcery spell this turn, **copy that spell**. You may
#: choose new targets for the copy." (Doublecast, Galvanic Iteration, Teach by Example, Dual
#: Strike) — the copier is the trigger's controller and "that spell" is the one that fired it
#: (`CopySpellEffect.spell_from_trigger_event`). "twice"/"N times" is the copy count; "X times"
#: (Storm King's Thunder) is this ability's *own* announced {X} — a literal string here, not yet
#: a number, since the value isn't known until the spell that carries this ability is cast, well
#: before it fires (`_substitute_x`'s nested walk into `CreateTurnTriggerEffect.inner_specs`
#: resolves the sentinel at that earlier point). "an additional time" (Howl of the Horde's own
#: Raid-gated second ability) makes one more copy on top of whatever an unconditional sibling
#: instance of this same trigger already grants — from this instance's own perspective that is
#: just an ordinary single copy, same as no suffix at all.
_COPY_THAT_SPELL_RE = compile_clause(
    r"copy (?:that spell|it)(?: (?P<n>twice|x times|an additional time|\d+ times))?\.\s*"
    r"you may choose new targets for the cop(?:y|ies)"
)


def _copy_that_spell(m: re.Match[str]) -> list[EffectSpec]:
    word = m.group("n")
    params: dict = {"spell_from_trigger_event": "instance_id", "choose_new_targets": True}
    if word == "x times":
        params["count"] = "x"
    elif word not in (None, "an additional time"):
        count = 2 if word == "twice" else int(word.split()[0])
        if count != 1:
            params["count"] = count
    return [EffectSpec("copy_spell", params)]


#: PAR-102(b): "[Until end of turn, ]target creature gets +2/+0 and gains [<keywords> and ]"<quoted
#: ability>"[ until end of turn]." (Abnormal Endurance, Hunter's Prowess, Supernatural Stamina, Unnatural
#: Moonrise …) — a pump that also hands out a whole quoted triggered/activated ability. Two specs share
#: one choice of recipient: the `pump` (P/T + any flag keywords) picks it, and the quoted grant — a
#: `grant_until` over the same `static_handlers.quoted_ability_grant_effects` the Aura/Equipment and
#: "gains "…" until end of turn" rows use — replays it (`previous_subject`; a group subject re-states its
#: selector as the static's ``affects``, a self subject its own source). The duration must be written
#: (prefix or suffix) — without one the grant would be permanent, a different card.


def _pump_and_quoted_grant(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    if bool(m.group("dur_pre")) == bool(m.group("dur_post")):
        return None  # no duration (permanent) or two of them
    inner = quoted_ability_grant_effects(m.group("inner"))
    if inner is None:
        return None
    return _pump_then_grant(m, {"type": inner.type, "params": dict(inner.params)})


def _pump_then_grant(m: re.Match[str], static: dict) -> Optional[list[EffectSpec]]:
    """A `pump` for ``m``'s subject and P/T (+ flag keywords) followed by a `grant_until` of ``static`` on
    that same subject until end of turn — the shared tail of the "pump and also grant …" rows."""
    if m.groupdict().get("attached"):
        return None  # "enchanted creature gets … and has …" is a standing static, not a resolving effect
    pump = pump_(m)
    if pump is None:
        return None
    target_kind, selector = pump_target(m) or (None, None)
    grant: dict = {"static": static, "duration": "end_of_turn", "target_kind": None}
    if target_kind:
        grant["previous_subject"] = True
    elif selector:
        grant["static"]["params"]["affects"] = selector
        grant["lock_group"] = True  # RULE 611.2c: the set is fixed when the spell resolves
    else:
        grant["self_subject"] = True
    return [*pump, EffectSpec("grant_until", grant)]


#: "…gets +0/+1 and gains all creature types until end of turn" (Shields of Velis Vel-shaped) — RULE
#: 702.73a, as a layer-4 `ALL_CREATURE_TYPES` marker like the "is every creature type" static.
def _pump_and_all_creature_types(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _pump_then_grant(m, {"type": "type_change", "params": {"add_subtypes": ["Changeling"]}})


#: PAR-102: "[Until end of turn, ]<subject> [gets +N/+N and ]gains your choice of flying, vigilance, deathtouch,
#: or haste[ until end of turn]." (Alchemist's Gift, Argivian Avenger, the Avenger/Courier abilities, Manifold
#: Mouse, Gideon Blackblade's +1 …) — one `pump` whose ``keyword_options`` the controller picks from when it
#: resolves (RULE 608.2d). Only flag keywords: a parametric or quality option ("protection from red") leaves
#: the clause unclaimed rather than dropping a choice.
def _pump_keyword_choice(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if bool(m.group("dur_pre")) == bool(m.group("dur_post")):
        return None  # a missing duration is a permanent grant; two are a typo
    options: list[str] = []
    for part in re.split(r",\s*or\s+|\s+or\s+|,\s*", m.group("opts")):
        slug = grantable_flag_slug(part.strip())
        if slug is None or slug in options:
            return None
        options.append(slug)
    if len(options) < 2:
        return None
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    if selector:
        return None  # "creatures you control gain your choice of …" — one pick for the group is a different clause
    params: dict = {"keyword_options": options}
    if m.groupdict().get("p") is not None:
        params["power"] = signed_int(m.group("p"))
        params["toughness"] = signed_int(m.group("t"))
    if target_kind:
        params["target_kind"] = target_kind
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("pump", params)]


def _pump_keywords(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    split = split_keywords_with_parametric(m.group("kw"))
    if split is None:
        return None
    flags, parametric = split
    if not flags and not parametric:
        return None
    if m.groupdict().get("must_blocked"):
        # PAR-124: "…gains deathtouch until end of turn and must be blocked
        # this turn if able." (Deadly Allure) — same flag-keyword tail
        # `_pump`'s own "and must be blocked…" suffix already grants.
        flags = [*flags, "must_be_blocked"]
    params: dict = {}
    if flags:
        params["keywords"] = flags
    if parametric:  # ENG-31: "gains firebending N until end of turn"
        params["parametric_keywords"] = parametric
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: "Up to two target creatures each get +N/+N [and gain `<keywords>`] until
#: end of turn." (Dauntless Onslaught-shaped — the single biggest pump
#: template found in the cache, 19 SOLO cards, `parser_probe.py blocked`) /
#: "One or two target creatures…" (Opera Love Song/Heroic Teamwork-shaped) —
#: ENG-30: these are no longer the same shape. "Up to two" is RULE 115.1a's
#: 0..2 `optional` idiom; "one or two" is a genuine RULE 601.2c *range*
#: (`TargetSpec.count_max`, at least one) — previously both were folded to
#: `count=2, optional=True` as a documented simplification (declining below
#: the "one or two" minimum was never a choice a real player would make
#: differently); now that the engine has a real range primitive, the two
#: wordings get their real, distinct shapes instead.
_PUMP_UP_TO_TWO_RE = compile_clause(
    r"up to 2 target creatures each gets? "
    r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)
_PUMP_ONE_OR_TWO_RE = compile_clause(
    r"1 or 2 target creatures each gets? "
    r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)


def _pump_up_to_two(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": signed_int(m.group("p")), "toughness": signed_int(m.group("t")),
        # `EffectRegistry`'s "pump" factory reads the *target* count as
        # "target_count" (distinct from a magnitude key also spelled
        # "count" elsewhere in this file) — a bare "count" here was a
        # dormant bug: every "up to two target creatures" pump spell (19
        # SOLO cards, Dauntless Onslaught-shaped) silently only ever
        # offered *one* target, since `PumpEffect`'s own `count` defaulted
        # to 1 and this key was never read. Found while building ENG-30's
        # neighboring "one or two" range shape just below.
        "target_kind": "creature", "target_count": 2, "optional": True,
    }
    if m.groupdict().get("kw"):
        keywords = token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _pump_one_or_two(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": signed_int(m.group("p")), "toughness": signed_int(m.group("t")),
        "target_kind": "creature", "target_count": 1, "target_count_max": 2,
    }
    if m.groupdict().get("kw"):
        keywords = token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: ENG-30: "1 or 2 target creatures gain `<kw>` until end of turn." (Wind
#: Sail) — the keyword-only sibling of `_PUMP_ONE_OR_TWO_RE` (no P/T delta
#: at all, unlike every other row in this family).
#: PAR-98: the optional "each" (Run for Your Life's "1 or 2 target creatures
#: **each** gain haste until end of turn").
_PUMP_ONE_OR_TWO_KW_RE = compile_clause(
    r"1 or 2 target creatures (?:each )?gains? (?P<kw>[a-z][a-z, ]*?) until end of turn"
)


def _pump_one_or_two_kw(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "target_kind": "creature", "target_count": 1, "target_count_max": 2, "keywords": keywords,
    })]


#: "Each creature your opponents control gets -1/-1 until end of turn for
#: each poison counter its controller has." (Phyresis Outbreak-shaped) —
#: `PumpEffect.per_recipient_controller_counter`'s own dedicated grammar:
#: unlike every other group-pump row, each recipient's boost scales
#: independently by *its own controller's* count of a player counter kind,
#: not one shared magnitude. Deliberately narrow to "poison" (a direct
#: `Player.poison` attribute) — a "rad"/"energy" variant would read
#: `Player.counters` instead, unneeded by any real card yet.
_PUMP_PER_CONTROLLER_COUNTER_RE = compile_clause(
    r"each creature your opponents control "
    r"gets? (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+) until end of turn "
    r"for each (?P<kind>poison) counter its controller has"
)


def _pump_per_controller_counter(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "power": signed_int(m.group("p")), "toughness": signed_int(m.group("t")),
        "selector": "creatures_opponents_control",
        "per_recipient_controller_counter": m.group("kind"),
    })]


#: "Creatures you control gain trample and get +X/+X until end of turn,
#: where X is the number of creatures you control." (Craterhoof Behemoth-
#: shaped) — `PumpEffect.amount_from_count_selector`'s own dedicated
#: grammar: one shared magnitude for the whole "creatures you control"
#: group, computed live from the board rather than a fixed int. The
#: keyword-list-*then*-P/T word order ("gain `<kw>` and get +X/+X") is the
#: opposite of `_pump`'s own "+N/+N and gain `<kw>`", so this needs its
#: own row rather than widening that one.
_GROUP_PUMP_COUNT_SELECTOR_RE = compile_clause(
    r"creatures you control gain (?P<kw>[a-z, ]+?) and get \+x/\+x until end of turn, "
    r"where x is the number of creatures you control"
)


def _group_pump_count_selector(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "keywords": keywords, "selector": "creatures_you_control",
        "amount_from_count_selector": "creatures_you_control",
    })]


#: "Other creatures you control gain trample and get +X/+X until end of
#: turn, where X is this creature's power." (Dragon Throne of Tarkir) — the
#: source-power sibling of the ordinary group pump.  ``other`` is important:
#: the granted ability lives on the equipped creature and must not buff that
#: creature itself (RULE 109.5).
_GROUP_PUMP_OTHER_SOURCE_POWER_RE = compile_clause(
    r"other creatures you control gain (?P<kw>[a-z, ]+?) and get \+x/\+x until end of turn, "
    r"where x is ~'?s power"
)


def _group_pump_other_source_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "keywords": keywords,
        "selector": "other_creatures_you_control",
        "amount_from_count_selector": "source_power",
    })]


#: "Target creature gets +1/+1 until end of turn for each creature you
#: control" (Friendly Neighborhood) / "…gets +1/+1 for each creature you
#: control and gains trample. It must be blocked this turn if able."
#: (King Harald's Revenge, PAR-124 — the "for each" clause sits *before*
#: an "and gains `<kw>`" tail instead of after "until end of turn", and the
#: duration word can trail either the P/T delta or the whole sentence).
#: The target and the count source are independent: the selected creature
#: need not be controlled by the player.
_PUMP_TARGET_PER_CREATURE_YOU_CONTROL_RE = compile_clause(
    r"(?:until end of turn, )?target creature gets? \+1/\+1"
    r"(?: until end of turn)? for each creature you control"
    r"(?: and gains? (?P<kw>[a-z, ]+?))?"
    r"(?: until end of turn)?"
)


def _pump_target_per_creature_you_control(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "target_kind": "creature", "amount_from_count_selector": "creatures_you_control",
    }
    kw = m.groupdict().get("kw")
    if kw:
        keywords = token_keywords(kw)
        if keywords is None:
            return None
        params["keywords"] = keywords
    return [EffectSpec("pump", params)]


#: RULE 202.2f/700.6 "target creature gets +X/+X until end of turn, where X
#: is your devotion to `<colour(s)/wedge>`." (Aspect of Hydra/Devoted Temur-
#: shaped) — the `DEVOTION` fragment feeding `PumpEffect.amount_from_count_
#: selector` via `continuous.count_selector`'s existing `devotion_to_<key>`
#: vocabulary, same shape `_GROUP_PUMP_COUNT_SELECTOR_RE` uses for a board
#: count instead of a mana-symbol one.
_PUMP_DEVOTION_TARGET_RE = compile_clause(rf"{TARGET} gets? \+x/\+x until end of turn, where x is {DEVOTION}")
#: The mass sibling — "creatures you control get +X/+X …" (Klothys's
#: Design) — same amount grammar, group subject instead of a RULE 115
#: target.
_GROUP_PUMP_DEVOTION_RE = compile_clause(
    rf"creatures you control gets? \+x/\+x until end of turn, where x is {DEVOTION}"
)
#: The debuff sibling — "target creature [an opponent controls] gets -X/-X
#: until end of turn, where X is your devotion to `<colour>`." (Blight-
#: Breath Catoblepas) — `PumpEffect.amount_from_count_selector_negative`
#: flips the always-nonnegative devotion count into the printed "-X/-X".
_PUMP_DEVOTION_NEGATIVE_TARGET_RE = compile_clause(
    rf"{TARGET} gets? -x/-x until end of turn, where x is {DEVOTION}"
)
#: "Another target creature you control gets +X/+X until end of turn, where
#: X is ~'s power." (Hardy Outlander's granted attack trigger, PAR-32) —
#: `continuous.count_selector`'s `source_power`, its own row rather than a
#: `{DEVOTION}` addition (that subgrammar is reused far too widely).
_PUMP_TARGET_SOURCE_POWER_RE = compile_clause(
    rf"{TARGET} (?:gets? \+x/\+x(?: and gains? (?P<kw>[a-z, ]+?))?"
    r"|gains? (?P<kw2>[a-z, ]+?) and gets? \+x/\+x)"
    r" until end of turn, where x is ~'?s power"
)


def _pump_target_source_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector_subject = subject
    params: dict = {"amount_from_count_selector": "source_power"}
    granted = m.group("kw") or m.group("kw2")
    if granted:
        # "gains trample and gets +X/+X …" (Ashroot Animist): the keyword rides the same pump.
        keywords = token_keywords(granted)
        if keywords is None:
            return None
        params["keywords"] = keywords
    if target_kind is not None:
        params["target_kind"] = target_kind
    if selector_subject is not None:
        params["selector"] = selector_subject
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: PAR-71: "<subject> gets +X/+X [or +X/+0] until end of turn, where X is
#: that spell's mana value." (Manaplasm/Jamie McCrimmon's symmetric form;
#: Erratic Cyclops/Livaan's power-only form) — the `PumpEffect.
#: amount_from_trigger_event` sibling of the `DEVOTION`-scaled pump rows
#: above, reading the firing `SPELL_CAST` event's own ``mana_value`` field
#: (already stamped on every such event by `casting_mixin.cast_spell` —
#: see its own "Shark Typhoon-shaped spell-cast payoffs" comment — so this
#: is pure recognition, no new engine work).
_PUMP_MANA_VALUE_RE = compile_clause(
    rf"(?:{TARGET}|(?P<selfref>{re.escape(SELF)})) gets? \+x/\+(?P<taxis>x|0) until end of turn, "
    r"where x is that spell'?s mana value"
)


def _pump_mana_value(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {"amount_from_trigger_event": "mana_value"}
    if m.group("taxis") == "0":
        params["amount_from_count_selector_axis"] = "power"
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: PAR-80: "target creature gets +X/+0[/+X] until end of turn." — the
#: base X-spell/X-ability pump, no "where X is…" tail at all (Bloodcurdling
#: Scream/Enrage/Hatred/Howl from Beyond, all bare instants with an
#: announced ``{X}`` cost; Cackling Witch/Kessig Wolf Run/Secluded
#: Starforge, the identical body on an ``{X}…`` activated ability instead).
#: X here is simply RULE 107.3c's announced {X} — `RulesEngine._substitute_x`
#: already walks any bound effect's own ``power``/``toughness`` for the
#: literal ``"x"``/``"-x"`` sentinel (Bring to Light/Toxic Deluge's own
#: precedent, `game/card_registry/competitive_interaction.py`'s "x"/"x"
#: pump), so this is pure recognition — no new engine primitive.
#: An optional trailing "and gains `<keyword list>`" (Kessig Wolf Run's
#: "…and gains trample"; Pedal to the Metal's "…and gains first strike") —
#: `_pump`'s own tail grammar, mirrored here since this row's magnitude
#: (``"x"``) is what keeps it from just widening that row directly.
_PUMP_TARGET_X_RE = compile_clause(
    rf"{TARGET} gets? \+x/(?P<taxis>\+x|\+0)"
    r"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
)


def _pump_target_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {"power": "x", "toughness": "x" if m.group("taxis") == "+x" else 0}
    if m.groupdict().get("kw"):
        keywords = token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: PAR-80: "target creature gets +X/+0[/+X] until end of turn, where X is
#: `<quantity>`." — ENG-37's general `bind`/`effect_amounts` measurement,
#: not a `PumpEffect` ``amount_from_*`` parameter per referent. PAR-120: a
#: count or aggregate ("the number of Mountains you control", "the greatest
#: power among creatures you control", "the amount of life you gained this
#: turn", "3 plus the number of cards named ~ in all graveyards") is read by
#: the shared amount vocabulary (`count_phrase.parse_amount_phrase`); only
#: the referents that aren't a quantity of the board stay a table — the
#: target's *own* current power (``of: "target"``, read before this same
#: effect's pump applies, Drain Life's proven `bind` pattern) and the most
#: recent `RollDieEffect` total.
_PUMP_X_REFERENT_AMOUNTS: dict[str, dict] = {
    "its power": {"kind": "characteristic", "characteristic": "power", "of": "target"},
    "that creature's power": {"kind": "characteristic", "characteristic": "power", "of": "target"},
    "the result": {"kind": "die_result"},
}
_PUMP_TARGET_X_AMOUNT_RE = compile_clause(
    rf"{TARGET} gets? \+x/(?P<taxis>\+x|\+0) until end of turn, "
    r"where x is (?P<phrase>.+)"
)


def _pump_target_x_amount(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    phrase = m.group("phrase")
    referent = _PUMP_X_REFERENT_AMOUNTS.get(phrase)
    if referent is not None:
        amount_spec = dict(referent)
    else:

        counted = parse_amount_phrase(phrase)
        if counted is None:
            return None
        amount_spec = {"kind": "count_selector", "selector": counted}
    pump_params: dict = {
        "power": "$px", "toughness": "$px" if m.group("taxis") == "+x" else 0,
    }
    if target_kind:
        pump_params["target_kind"] = target_kind
    if selector:
        pump_params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        pump_params["creature_filter"] = state_filter
    return [EffectSpec("bind", {
        "name": "px", "amount": amount_spec,
        "effects": [{"type": "pump", "params": pump_params}],
    })]


#: PAR-80: "Roll a `<n>`-sided die. Target creature gets +X/+X until end of
#: turn, where X is the result." (Growth Spurt) needs no dedicated handler
#: of its own for the first sentence — "Roll a `<n>`-sided die." already
#: parses standalone (``roll_die``) — only the second sentence's "the
#: result" referent, in `_PUMP_X_REFERENT_AMOUNTS` above.
#:
#: "target creature gets +X/+<N> until end of turn, where X is a number
#: from A to B chosen at random." (Hapato's Might) is a *different*
#: primitive from the die roll above (RULE 706.11 only treats literal "roll
#: a die" text as subject to dice-replacement effects), so it gets its own
#: small effect (`RandomNumberEffect`/``"random_number"``) and amount kind
#: (``"random_result"``) rather than being folded into ``die_result``.
#: ``A``/``B`` are captured, not hardcoded to 0/6, so a future card with a
#: different range reuses this same row.
_PUMP_TARGET_X_RANDOM_RE = compile_clause(
    rf"{TARGET} gets? \+x/(?P<taxis>\+x|\+0) until end of turn, "
    r"where x is a number from (?P<lo>\d+) to (?P<hi>\d+) chosen at random"
)


def _pump_target_x_random(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    pump_params: dict = {
        "power": "$px", "toughness": "$px" if m.group("taxis") == "+x" else 0,
    }
    if target_kind:
        pump_params["target_kind"] = target_kind
    if selector:
        pump_params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        pump_params["creature_filter"] = state_filter
    return [
        EffectSpec("random_number", {"min": int(m.group("lo")), "max": int(m.group("hi"))}),
        EffectSpec("bind", {
            "name": "px", "amount": {"kind": "random_result"},
            "effects": [{"type": "pump", "params": pump_params}],
        }),
    ]


#: PAR-80: "Target opponent reveals a card at random from their hand.
#: Target creature gets +X/+<N> until end of turn, where X is the revealed
#: card's mana value." (Planeswalker's Favor) — a genuinely singleton
#: two-target compound (the reveal's own "target opponent" plus the pump's
#: "target creature"), built the same `bind`-over-`pump` way as the
#: phrase-table family above, just with its own leading reveal clause
#: instead of a board count.
_REVEAL_RANDOM_HAND_CARD_PUMP_MV_RE = compile_clause(
    r"target opponent reveals a card at random from their hand\. "
    rf"{TARGET} gets? \+x/(?P<taxis>\+x|\+0) until end of turn, "
    r"where x is the revealed card'?s mana value"
)


def _reveal_random_hand_card_pump_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    pump_params: dict = {
        "power": "$px", "toughness": "$px" if m.group("taxis") == "+x" else 0,
    }
    if target_kind:
        pump_params["target_kind"] = target_kind
    if selector:
        pump_params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        pump_params["creature_filter"] = state_filter
    return [
        EffectSpec("reveal_random_hand_card", {"target_kind": "opponent"}),
        EffectSpec("bind", {
            "name": "px",
            "amount": {"kind": "characteristic", "characteristic": "mana_value", "of": "revealed"},
            "effects": [{"type": "pump", "params": pump_params}],
        }),
    ]


#: PAR-80: "Reveal any number of green cards in your hand. Target creature
#: gets +X/+X until end of turn, where X is the number of cards revealed
#: this way." (Ivy Seer, Scent of Ivy — the identical body under an
#: activated-ability cost and a bare sorcery respectively; the cost prefix
#: is split off before this handler ever sees the text, same as every other
#: ``<cost>: <effect>`` row in this file). Only "green" is in this closed
#: table today — widen ``_REVEAL_ANY_NUMBER_COLOR_WORDS`` the day a second
#: color shows up rather than guessing an open vocabulary now.
_REVEAL_ANY_NUMBER_COLOR_WORDS: dict[str, str] = {"green": "G"}
_REVEAL_ANY_NUMBER_COLOR_ALT = "|".join(_REVEAL_ANY_NUMBER_COLOR_WORDS)
_REVEAL_ANY_NUMBER_PUMP_RE = compile_clause(
    rf"reveal any number of (?P<color>{_REVEAL_ANY_NUMBER_COLOR_ALT}) cards in your hand\. "
    rf"{TARGET} gets? \+x/(?P<taxis>\+x|\+0) until end of turn, "
    r"where x is the number of cards revealed this way"
)


def _reveal_any_number_pump(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    color = _REVEAL_ANY_NUMBER_COLOR_WORDS.get(m.group("color"))
    if color is None:
        return None
    pump_params: dict = {
        "power": "$px", "toughness": "$px" if m.group("taxis") == "+x" else 0,
    }
    if target_kind:
        pump_params["target_kind"] = target_kind
    if selector:
        pump_params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        pump_params["creature_filter"] = state_filter
    return [
        EffectSpec("reveal_any_number_hand_cards", {"colors": [color]}),
        EffectSpec("bind", {
            "name": "px",
            "amount": {"kind": "count_selector", "selector": "revealed_with_count"},
            "effects": [{"type": "pump", "params": pump_params}],
        }),
    ]


def _pump_devotion_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector_subject = subject
    selector = devotion_selector(m)
    if not selector:
        return None
    params: dict = {"amount_from_count_selector": selector}
    if target_kind:
        params["target_kind"] = target_kind
    if selector_subject:
        params["selector"] = selector_subject
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _pump_devotion_negative_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector_subject = subject
    selector = devotion_selector(m)
    if not selector:
        return None
    params: dict = {"amount_from_count_selector": selector, "amount_from_count_selector_negative": True}
    if target_kind:
        params["target_kind"] = target_kind
    if selector_subject:
        params["selector"] = selector_subject
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _group_pump_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = devotion_selector(m)
    if not selector:
        return None
    return [EffectSpec("pump", {"selector": "creatures_you_control", "amount_from_count_selector": selector})]


# ---------------------------------------------------------------------------
# PAR-81: "Switch target creature's power and toughness until end of turn."
# — the resolving one-shot form (Twisted Image-shaped). `"pt_switch"`
# already existed as a `StaticAbility` layer 7e type for a granted/printed
# standing ability; this is its `"switch_power_toughness"` one-shot sibling
# (`SwitchPowerToughnessEffect`, `game/effects/counters_tokens.py`).
# ---------------------------------------------------------------------------

#: The RULE 115 targeted form — "switch target creature's power and
#: toughness until end of turn." (About Face/Twisted Image and siblings).
_SWITCH_PT_TARGET_RE = compile_clause(
    rf"switch {TARGET}'?s power and toughness until end of turn"
)


def _switch_pt_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent")):
        return None
    return [EffectSpec("switch_power_toughness", {"target_kind": kind})]


#: The self-referential form — "switch ~'s power and toughness until end
#: of turn." (Aeromoeba/Aquamoeba's own activated ability) / "switch its
#: power and toughness until end of turn." (Valakut Fireboar's own attack
#: trigger — "its" naming the ability's own source, RULE 603.1 subject
#: scoping already strips the trigger condition before this clause is
#: reached). No target at all — acts on the effect's own bound `source`.
_SWITCH_PT_SELF_RE = compile_clause(r"switch (?:~'s|its) power and toughness until end of turn")


def _switch_pt_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("switch_power_toughness", {})]


#: The mass, untargeted form — "switch each creature's power and toughness
#: until end of turn." (Mannichi, the Fevered Dream) — RULE 601.2c, no
#: RULE 115 target at all, reusing `continuous.group_selector_objects`'s
#: existing ``"all_creatures"`` selector the same way `_cant_block_turn_
#: group`'s own mass form does.
_SWITCH_PT_MASS_RE = compile_clause(r"switch each creature'?s power and toughness until end of turn")


def _switch_pt_mass(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("switch_power_toughness", {"selector": "all_creatures"})]


#: The multi-target form — "switch the power and toughness of each of
#: `<up to N|any number of>` target creatures until end of turn." (Invert
#: // Invent's "up to 2"; Inversion Behemoth's "any number of") — RULE
#: 115.1a generalized to N>=2, the identical "any number of"/"up to N"
#: quantifier pair `_MULTI_TARGET_QUANTIFIER` uses elsewhere, but this
#: phrase wraps the quantifier+target *inside* "each of…" rather than
#: leading with it, so it gets its own small regex instead of that shared
#: macro.
_SWITCH_PT_MULTI_RE = compile_clause(
    r"switch the power and toughness of each of "
    r"(?:up to (?P<n>\d+)|(?P<any>any number of)) target creatures until end of turn"
)


def _switch_pt_multi(m: re.Match[str]) -> list[EffectSpec]:
    count = ANY_NUMBER_TARGET_CAP if m.group("any") else int(m.group("n"))
    return [EffectSpec("switch_power_toughness", {
        "target_kind": "creature", "count": count, "optional": True,
    })]


#: The devotion/count-scaled sibling of `_pump_self_subject`'s fixed-int
#: form — "it gets +X/+X until end of turn, where X is `{DEVOTION}`"
#: (Angelic Exaltation/Akroan Hoplite-adjacent self-buff-on-attack — see
#: `{DEVOTION}`'s own docstring for the wider "the number of `<noun
#: phrase>` you control" reading this also picks up). Symmetric only
#: (``+x/+x``/``-x/-x``): `PumpEffect.amount_from_count_selector` always
#: sets power and toughness to the *same* resolved amount, so an
#: asymmetric "+X/+0" (Akroan Hoplite's own real printing) has no way to
#: express "only power scales" yet and stays unclaimed — a smaller,
#: separate gap from the amount-resolver this row closes.
_PUMP_SELF_SUBJECT_DEVOTION_RE = compile_clause(
    rf"it gets? (?P<sign>\+|-)x/(?P=sign)x until end of turn, where x is {DEVOTION}"
)


def _pump_self_subject_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = devotion_selector(m)
    if not selector:
        return None
    params: dict = {"amount_from_count_selector": selector}
    if m.group("sign") == "-":
        params["amount_from_count_selector_negative"] = True
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _pump_self_subject(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """The bare-pronoun sibling of `_pump`'s untargeted self form —
    "it gets +N/+N [and gains <keyword>] until end of turn" (Akroan Hoplite/
    Aurochs-shaped: an attack/enters trigger whose own body refers back to
    the source as "it" rather than "~", `self_subject_only`-gated)."""
    params: dict = {
        "power": signed_int(m.group("p")),
        "toughness": signed_int(m.group("t")),
    }
    if m.groupdict().get("kw"):
        keywords = token_keywords(m.group("kw"))
        if keywords is None:
            return None  # unmodeled granted ability → fail-closed
        params["keywords"] = keywords
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _grant_self_subject_kw(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Whenever ~ attacks, it gains double strike until end of turn."
    (Flaming Fist) — a keyword-only self-pump (no P/T delta), `it` bound to
    the ability's own source (`self_subject_only`)."""
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None  # unmodeled granted ability → fail-closed
    return [EffectSpec("pump", {"keywords": keywords})]


def _grant_group_subject_kw(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Whenever a creature … attacks, it gains skulk until end of turn
    [and must be blocked this turn if able]."

    Here ``it`` is neither this ability's source nor a preceding RULE 115
    target: it is the particular RULE 603.1 group object that fired the
    trigger. `GrantKeywordToTriggerSubjectEffect` already owns that live
    event-reference behaviour (Tyvar Kell's emblem); this parser row merely
    routes the ordinary creature-event spelling to it. PAR-124's own
    "and must be blocked this turn if able" tail (Descend on the Prey) is
    a second, independent flag keyword on the same trigger subject — this
    effect type only ever carries one ``keyword``, so it's a second spec
    rather than a list, both reading the identical event at resolution.
    """
    keywords = token_keywords(m.group("kw"))
    if keywords is None or len(keywords) != 1:
        return None
    specs = [EffectSpec("grant_keyword_to_trigger_subject", {
        "keyword": keywords[0], "event_key": GROUP_SUBJECT_KEY_SENTINEL,
    })]
    if m.groupdict().get("must_blocked"):
        specs.append(EffectSpec("grant_keyword_to_trigger_subject", {
            "keyword": "must_be_blocked", "event_key": GROUP_SUBJECT_KEY_SENTINEL,
        }))
    return specs


#: "it gets +X/+X until end of turn" (PAR-123) — the pronoun subject with the
#: symmetric X magnitude, whose X a trailing ", where X is the number of …"
#: binds (`segmenter._where_x_specs`: Angelic Exaltation, Thoughtweft Imbuer,
#: Altar of the Goyf). One regex, three subject flavours (source / group
#: trigger's firing object / a preceding clause's target).
_PUMP_IT_X_RE = compile_clause(
    r"it gets? \+x/\+x(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
)


def _pump_it_x(m: re.Match[str], *, subject: str) -> Optional[list[EffectSpec]]:
    params: dict = {"power": "x", "toughness": "x"}
    if m.groupdict().get("kw"):
        keywords = token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    if subject == "group":
        params["trigger_subject"] = True
        params["trigger_event_key"] = GROUP_SUBJECT_KEY_SENTINEL
    elif subject == "previous":
        params["previous_subject"] = True
    return [EffectSpec("pump", params)]


def _pump_group_subject(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Whenever a creature … attacks, **it** gets +N/+N [and gains `<keyword>`] until end of
    turn." — the object that fired the group trigger, read live off the event
    (`PumpEffect.trigger_subject`, the mechanism Exalted uses)."""
    specs = _pump_self_subject(m)
    if specs is None:
        return None
    params = dict(specs[0].params)
    params["trigger_subject"] = True
    params["trigger_event_key"] = GROUP_SUBJECT_KEY_SENTINEL
    return [EffectSpec("pump", params)]


#: The durations a grant may carry beyond "until end of turn", as printed →
#: `game/durations.py`'s vocabulary. "Until end of turn" is deliberately
#: absent: that is exactly what the `pump` family's ``temp_*`` fields already
#: are (cleared at RULE 514.2 cleanup), and routing it here too would give one
#: phrasing two implementations. These are the ones ``temp_*`` *cannot*
#: express, because it has nowhere to record any other ending.
_GRANT_DURATIONS: dict[str, str] = {
    "until your next turn": "your_next_turn",
    "until the end of your next turn": "end_of_your_next_turn",  # PAR-163, RULE 611.2
    "until end of combat": "end_of_combat",
    "until the end of combat": "end_of_combat",
    "until the beginning of the next end step": "next_end_step",
}


def _target_quoted_until_source_cast(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """RULE 611.2a: a quoted grant and the independently bounded self-cast permission."""
    target = resolve_target_kind(m['target'])
    if not target_kind_allowed(target, ('creature', 'land', 'artifact', 'enchantment', 'permanent', 'planeswalker')):
        return None
    grants = quoted_ability_grant_effects_list(m['inner'])
    if not grants:
        return None
    payloads = [{'type': grant.type, 'params': dict(grant.params)} for grant in grants]
    effects = [EffectSpec('grant_until', {
        'target_kind': target,
        'optional': target_is_optional(m),
        'creature_filter': resolve_target_creature_state_filter(m['target']),
        'duration': 'until_source_cast_from_exile',
        'static': payloads[0],
        **({'extra_statics': payloads[1:]} if len(payloads) > 1 else {}),
    })]
    if m['permission']:
        effects.append(EffectSpec('grant_conditional_cast_from_exile', {'source_exiled_as_cost': True}))
    return effects


def _source_quoted_ability(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    grants = quoted_ability_grant_effects_list(m['inner'])
    if not grants:
        return None
    duration = 'rest_of_game' if not m['dur'] else ('end_of_turn' if m['dur'] == 'until end of turn'
        else _GRANT_DURATIONS.get(m['dur']))
    if duration is None:
        return None
    return [EffectSpec('grant_until', {
        'self_subject': True, 'target_kind': None, 'duration': duration,
        'static': {'type': grant.type, 'params': {**grant.params, 'affects': 'self'}},
    }) for grant in grants]


def _grant_until(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Target creature gains flying until your next turn." (RULE 611)

    The keyword-pump handler's sibling for every duration other than end of
    turn — same subjects, same keyword vocabulary, but the grant becomes a
    real continuous effect on `GameState.floating_statics` rather than a
    turn-scoped ``temp_*`` stamp.
    """
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    static: dict = {"type": "grant_keyword", "params": {"keywords": keywords}}
    params: dict = {"static": static, "duration": duration}
    if target_kind:
        params["target_kind"] = target_kind
    else:
        # A group grant ("creatures you control gain flying until your next
        # turn") has no target: the static keeps the selector as its own
        # ``affects``, so the floating effect covers whatever matches it at
        # each recompute (RULE 611.2c).
        params["target_kind"] = None
        static["params"]["affects"] = selector
    return [EffectSpec("grant_until", params)]


#: MEC-88's temporary-removal sibling of `_grant_until` — "target creature
#: loses banding and all "bands with other" abilities until end of turn."
#: (Tolaria's own body, minus its separate "activate only during any
#: upkeep step" timing-restriction sentence — a genuinely new activation-
#: window marker this batch doesn't build, so Tolaria itself stays
#: UNMODELED) / "target creature loses all "bands with other" abilities
#: until end of turn." (Shelkin Brownie). RULE 613.7f ability-removal via
#: a `grant_until`-parked `remove_keyword` static (`game/effects/
#: registry.py`'s `remove_keyword`, built for Colossus Hammer's own
#: standing version of the same removal) rather than the standing
#: layer-6 grant family — collapses to plain Banding removal, the same
#: "bands with other `<quality>` == banding" simplification the grant
#: side (`static_handlers.quoted_ability_grant_effects_list`) already
#: uses.
_LOSE_BANDING_RE = compile_clause(
    r'target creature loses (?:banding and )?all "bands with other" abilities until end of turn'
)


def _lose_banding(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_until", {
        "static": {"type": "remove_keyword", "params": {"keywords": ["banding"]}},
        "duration": "end_of_turn",
        "target_kind": "creature",
    })]


#: PAR-13's P/T sibling of `_grant_until` — "target creature gets -4/-0
#: until your next turn" (Fungi Cavern/A-Binding Geist/Hag of Inner
#: Weakness/Wasp, Shrinking Savior-shaped; "creatures your opponents
#: control get -3/-0 until your next turn" — Mouth of the Storm — via the
#: same widened `_GROUP`). The `anthem` static (layer 7c) is already the
#: general P/T-delta static every plain pump uses; this is the first
#: oracle-text route to it with a non-end-of-turn duration.
def _pump_until(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    static: dict = {
        "type": "anthem",
        "params": {"power": signed_int(m.group("p")), "toughness": signed_int(m.group("t"))},
    }
    params: dict = {"static": static, "duration": duration}
    if target_kind:
        params["target_kind"] = target_kind
    else:
        params["target_kind"] = None
        static["params"]["affects"] = selector
    return [EffectSpec("grant_until", params)]


#: MEC-87's permanent sibling of `_pump_until`/`_grant_until` combined —
#: "Target creature gets +2/+2 and gains horsemanship." (Riding the Dilu
#: Horse-shaped, Portal Three Kingdoms' own "This effect lasts
#: indefinitely." reminder text, stripped by `normalize`). No "until …" tail
#: at all: RULE 611.2c's own omitted-duration default is `game/durations.py`'s
#: ``rest_of_game``, not something read off the text — so this is a fixed
#: duration rather than a row in `_GRANT_DURATIONS`. Plain `TARGET` only
#: (not the fuller `_SUBJECT`): no printed card needs the self/group/attached
#: variants of a *permanent* pump-and-grant, and guessing an ``affects``
#: selector for those would be wrong more often than right.
def _pump_and_grant_indefinite(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent")):
        return None
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("grant_until", {
        "static": {
            "type": "anthem",
            "params": {"power": signed_int(m.group("p")), "toughness": signed_int(m.group("t"))},
        },
        "extra_statics": [{"type": "grant_keyword", "params": {"keywords": keywords}}],
        "duration": "rest_of_game",
        "target_kind": kind,
    })]


#: "{2}{G}, {T}: Target Elf creature gets +2/+2 and has trample for as long as ~ remains tapped." (the
#: Mirage/Alliances tap-to-bestow creatures — Elven/Goblin/Zombie/Wizard/Soldier Cohort-shaped). One
#: `grant_until` carries both statics (the P/T `anthem` and the keyword) on the chosen creature for a
#: RULE 611.2b condition-bounded duration — `_LOCKDOWN_CONDITIONS`' own ``source_tapped``.


def _pump_grant_while_tapped(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    # See `_pump_subtype_target`: the bare `[a-z]+` capture can't tell a subtype from a state word.
    target_text = f"target {m.group('subtype')} creature"
    creature_filter = resolve_target_creature_state_filter(target_text) or {
        "subtype": m.group("subtype").capitalize(),
    }
    return [EffectSpec("grant_until", {
        "static": {
            "type": "anthem",
            "params": {"power": signed_int(m.group("p")), "toughness": signed_int(m.group("t"))},
        },
        "extra_statics": [{"type": "grant_keyword", "params": {"keywords": keywords}}],
        "duration": "for_as_long_as",
        "condition": {"kind": "source_tapped"},
        "target_kind": "creature",
        "creature_filter": creature_filter,
    })]


#: PAR-13's "can't attack"/"can't block" sibling — "target creature can't
#: attack until your next turn" (Dungeon of the Mad Mage's own Twisted
#: Caverns). The plain, unqualified restriction rides the same synthetic
#: `grant_keyword` flag (`cant_attack`/`cant_block`) its permanent-static
#: cousin uses (`combat_restriction`'s own docstring) — not `_token_
#: keywords`, since these verbs aren't real RULE 702 keyword names.
_CANT_ATTACK_OR_BLOCK_UNTIL_RE = compile_clause(
    rf"{TARGET} can'?t (?P<verb>attack|block) "
    r"(?P<dur>until (?:your next turn|the end of your next turn|the end of combat|end of combat|"
    r"the beginning of the next end step))"
)


def _cant_attack_or_block_until(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent")):
        return None
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    flag = "cant_attack" if m.group("verb") == "attack" else "cant_block"
    return [EffectSpec("grant_until", {
        "static": {"type": "grant_keyword", "params": {"keywords": [flag]}},
        "duration": duration, "target_kind": kind,
    })]


#: "It gains haste until your next turn." (Offspring's Revenge) — the
#: previous-subject sibling of the `_SUBJECT`-anchored `grant_until` row
#: below: the "it" is whatever the preceding clause created/targeted (here,
#: the just-made token copy), so it rides `EffectHandler.previous_subject_
#: only` + `previous_subject: True` exactly like `_lockdown` /
#: `_return_to_hand_previous`, not a fresh `TargetSpec`.
_GRANT_UNTIL_PREVIOUS_RE = compile_clause(
    rf"{THEN}{PREVIOUS_SUBJECT} gains? (?P<kw>[a-z, ]+?) "
    r"(?P<dur>until (?:your next turn|the end of your next turn|the end of combat|end of combat|"
    r"the beginning of the next end step))"
)


def _grant_until_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    return [EffectSpec("grant_until", {
        "static": {"type": "grant_keyword", "params": {"keywords": keywords}},
        "duration": duration,
        "previous_subject": True,
        "target_kind": None,
    })]


#: The lock-down family's own "for as long as <cond>" durations (PAR-11),
#: matched against `game/static_conditions.py`'s vocabulary.
_LOCKDOWN_CONDITIONS: list[tuple[re.Pattern[str], dict]] = [
    (re.compile(r"~ remains tapped", re.I), {"kind": "source_tapped"}),
    (re.compile(r"you control ~", re.I), {"kind": "source_on_battlefield"}),
    (re.compile(r"~ remains on the battlefield", re.I), {"kind": "source_on_battlefield"}),
]


def _lockdown(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"It doesn't untap during its controller's untap step for as long as ~
    remains tapped." (RULE 502.1 + RULE 611.2b — Sand Squid/Ice Floe-shaped.)

    The second sentence of a tap-then-lock ability, so its subject is the
    *previous* clause's target. Composes three pieces that already existed
    separately and had never met: the `previous_subject_only` pronoun, the
    ``no_untap`` static, and this batch's condition-bounded duration — which
    is what made this family unreachable until now (PAR-11).
    """
    condition = next(
        (cond for pattern, cond in _LOCKDOWN_CONDITIONS if pattern.fullmatch(m.group("cond").strip())),
        None,
    )
    if condition is None:
        return None
    return [
        EffectSpec(
            "grant_until",
            {
                "static": {"type": "no_untap", "params": {}},
                "duration": "for_as_long_as",
                "condition": dict(condition),
                "previous_subject": True,
                "target_kind": None,
            },
        )
    ]


#: "up to X target creatures gain flying until end of turn, where X is the number of times ~ was kicked." (Voyager
#: Drake) / "... where X is your devotion to black." (Mogis's Marauder): the dynamic count is read at announce time
#: (`targeting.resolved_count`'s ``source_kicker_count`` / ``devotion_to_<colour>``).
_MULTI_TARGET_X_TAIL = (
    r"(?:, where x is (?P<x_def>the number of times ~ was kicked"
    r"|your devotion to (?P<x_devotion>white|blue|black|red|green)))?"
)


def _multi_target_x_selector(m: re.Match[str]) -> Optional[str]:
    """The ``count_selector`` a ", where X is ..." tail names; ``"source_x_paid"`` (the announced {X}) when the
    clause carries no definition; ``None`` when it names one this table doesn't know."""
    if m.groupdict().get("x_devotion"):
        return f"devotion_to_{m.group('x_devotion').lower()}"
    if m.groupdict().get("x_def"):
        return "source_kicker_count"
    return "source_x_paid"


def _multi_target_pump_params(m: re.Match[str]) -> Optional[dict]:
    params = multi_target_params(m)
    if params is None:
        return None
    if params.get("count_selector"):
        selector = _multi_target_x_selector(m)
        if selector is None:
            return None
        params["count_selector"] = selector
    return renamed_target_count(params)


#: "up to four target permanents you control gain indestructible until end of turn." (Invisible Force Field) /
#: "up to X target creatures each gain intimidate and haste until end of turn, where X is ..." -- the plural of
#: `pump_keyword`, over `PumpEffect`'s ``target_count``/``count_selector``.
_PUMP_KEYWORD_MULTI_RE = compile_clause(
    rf"{MULTI_TARGET_QUANTIFIER_X}(?:other )?(?P<target>{MULTI_TARGET_ALT}) (?:each )?gains? "
    rf"(?P<kw>[a-z0-9, ]+?) until end of turn{_MULTI_TARGET_X_TAIL}"
)


def _pump_keyword_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_pump_params(m)
    split = split_keywords_with_parametric(m.group("kw"))
    if params is None or split is None or not (split[0] or split[1]):
        return None
    flags, parametric = split
    if flags:
        params["keywords"] = flags
    if parametric:
        params["parametric_keywords"] = parametric
    return [EffectSpec("pump", params)]


#: "up to two target creatures you control each get +2/+1 until end of turn." (Elspeth, Sun's Nemesis) -- the
#: scoped / counted generalisation of `_PUMP_UP_TO_TWO_RE` (which keeps the bare "up to 2 target creatures each"
#: wording and its `pump_up_to_two` name).
_PUMP_MULTI_RE = compile_clause(
    rf"{MULTI_TARGET_QUANTIFIER}(?:other )?(?P<target>{MULTI_TARGET_ALT}) (?:each )?gets? "
    r"(?P<p>[+\-\u2212]\d+)/(?P<t>[+\-\u2212]\d+)(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)


def _pump_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_pump_params(m)
    if params is None:
        return None
    params["power"], params["toughness"] = signed_int(m.group("p")), signed_int(m.group("t"))
    if m.group("kw"):
        keywords = token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    return [EffectSpec("pump", params)]

_PUMP_GRANT_WHILE_TAPPED_RE = compile_clause(
    rf"target (?P<subtype>[a-z]+) creature gets? {PT_DELTA} and has (?P<kw>[a-z, ]+?) "
    r"for as long as ~ remains tapped"
)

_PUMP_AND_QUOTED_GRANT_RE = compile_clause(
    rf"(?P<dur_pre>until end of turn, )?{SUBJECT} gets? {PT_DELTA} and gains? "
    r"(?:(?P<kw>[a-z, ]+?),? and )?\"(?P<inner>[^\"]+)\"(?P<dur_post> until end of turn)?"
)
_PUMP_AND_ALL_TYPES_RE = compile_clause(
    rf"{SUBJECT} gets? {PT_DELTA} and gains? all creature types until end of turn"
)
_PUMP_KEYWORD_CHOICE_RE = compile_clause(
    rf"(?P<dur_pre>until end of turn, )?{SUBJECT} (?:gets? {PT_DELTA} and )?gains? your choice of "
    r"(?P<opts>[a-z, ]+?)(?P<dur_post> until end of turn)?"
)
#: "that creature has base power and toughness 3/1 and has flying" (Aven Mimeomancer) — a layer-7b base P/T
#: (the same `type_change` ``power``/``toughness`` the animate rows set) plus an optional keyword list, on the
#: pick an earlier clause made. Duration-less here: "for as long as it has a feather counter on it" re-times it.
_BASE_PT_PREVIOUS_RE = compile_clause(
    r"(?:it|that (?:creature|permanent|land|artifact)) has base power and toughness (?P<p>\d+)/(?P<t>\d+)"
    rf"(?: and has (?P<kws>{BIA_KEYWORD_LIST}))?"
)


def _base_pt_previous(m: re.Match[str]) -> list[EffectSpec]:
    params: dict[str, Any] = {
        "static": {"type": "type_change", "params": {"power": int(m.group("p")), "toughness": int(m.group("t"))}},
        "previous_subject": True, "target_kind": None,
    }
    if m.group("kws"):
        keywords = [CREATURE_FILTER_KEYWORD_WORDS[w] for w in re.split(r", and |, | and ", m.group("kws")) if w]
        params["extra_statics"] = [{"type": "grant_keyword", "params": {"keywords": keywords}}]
    return [EffectSpec("grant_until", params)]


ROWS: list[EffectHandler] = [
    # "target creature gains flying until end of turn" (keyword-only pump) /
    # "creatures you control gain flying until end of turn".
    EffectHandler(
        "pump_keyword",
        # ``0-9`` in the keyword capture is ENG-31's parametric grant
        # ("gains firebending 4 until end of turn"); `_pump_keywords` splits
        # a "<name> <N>" entry off into ``parametric_keywords`` and
        # fail-closes on anything that isn't a FLAG or a grantable
        # parametric keyword.
        compile_clause(
            rf"{SUBJECT} gains? (?P<kw>[a-z0-9, ]+?) until end of turn"
            # PAR-124: "…gains deathtouch until end of turn and must be
            # blocked this turn if able." (Deadly Allure).
            rf"(?P<must_blocked> and must be blocked this turn if able)?"
        ),
        _pump_keywords,
    ),
    # PAR-102(b): the pump that also grants a quoted ability.
    EffectHandler("pump_and_quoted_grant", _PUMP_AND_QUOTED_GRANT_RE, _pump_and_quoted_grant),
    EffectHandler("pump_and_all_creature_types", _PUMP_AND_ALL_TYPES_RE, _pump_and_all_creature_types),
    EffectHandler("pump_keyword_choice", _PUMP_KEYWORD_CHOICE_RE, _pump_keyword_choice),
    # "Each creature your opponents control gets -1/-1 until end of turn
    # for each poison counter its controller has." (Phyresis Outbreak).
    EffectHandler(
        "pump_per_controller_counter",
        _PUMP_PER_CONTROLLER_COUNTER_RE,
        _pump_per_controller_counter,
    ),
    # "Up to two target creatures each get +N/+N [and gain <keywords>]
    # until end of turn." (Dauntless Onslaught-shaped).
    EffectHandler(
        "pump_up_to_two",
        _PUMP_UP_TO_TWO_RE,
        _pump_up_to_two,
    ),
    # ENG-30: "One or two target creatures…" (Opera Love Song/Heroic
    # Teamwork-shaped) — a genuine RULE 601.2c range, not "up to two"; see
    # `_PUMP_ONE_OR_TWO_RE`'s own comment for why this is now split out.
    EffectHandler(
        "pump_one_or_two",
        _PUMP_ONE_OR_TWO_RE,
        _pump_one_or_two,
    ),
    # ENG-30: "1 or 2 target creatures gain <kw> until end of turn." (Wind
    # Sail) — the keyword-only sibling of the row above.
    EffectHandler(
        "pump_one_or_two_kw",
        _PUMP_ONE_OR_TWO_KW_RE,
        _pump_one_or_two_kw,
    ),
    # PAR-150: the plural, scoped / counted keyword grant and pump ("up to four target permanents you control
    # gain indestructible ...", "up to 2 target creatures you control each get +2/+1 ..."); the exact bare
    # "up to 2 target creatures each get" wording stays with `pump_up_to_two` above.
    EffectHandler("pump_keyword_multi", _PUMP_KEYWORD_MULTI_RE, _pump_keyword_multi),
    EffectHandler("pump_multi_target", _PUMP_MULTI_RE, _pump_multi),
    # "Creatures you control gain trample and get +X/+X until end of turn,
    # where X is the number of creatures you control." (Craterhoof
    # Behemoth-shaped) — tried before the plain `pump_keyword` row above
    # since it's a strict superset of that shape.
    EffectHandler(
        "group_pump_count_selector",
        _GROUP_PUMP_COUNT_SELECTOR_RE,
        _group_pump_count_selector,
    ),
    EffectHandler(
        "group_pump_other_source_power",
        _GROUP_PUMP_OTHER_SOURCE_POWER_RE,
        _group_pump_other_source_power,
    ),
    EffectHandler(
        "pump_target_per_creature_you_control",
        _PUMP_TARGET_PER_CREATURE_YOU_CONTROL_RE,
        _pump_target_per_creature_you_control,
    ),
    # RULE 202.2f/700.6 "target creature gets +X/+X until end of turn, where
    # X is your devotion to <colour(s)/wedge>." (Aspect of Hydra/Devoted
    # Temur-shaped) and its "-X/-X" debuff sibling (Blight-Breath
    # Catoblepas) / mass "creatures you control get +X/+X …" sibling
    # (Klothys's Design) — tried before the plain digit-amount `pump` row
    # below since "x" would otherwise never match that row's `\d+`.
    # RULE 608.2 / 301.5a: Bronze Cudgels uses completed resolutions, not activations.
    EffectHandler(
        "pump_attached_resolution_count",
        compile_clause(r"until end of turn, equipped creature gets \+x/\+0, where x is the number of times this ability has resolved this turn"),
        lambda m: [EffectSpec("pump", {
            "target_kind": "attached_permanent", "power": 0, "toughness": 0,
            "dynamic_amount": {"kind": "ability_resolution_count"},
            "amount_from_count_selector_axis": "power",
        })],
    ),
    EffectHandler("pump_mana_value", _PUMP_MANA_VALUE_RE, _pump_mana_value),
    EffectHandler(
        "pump_target_source_power", _PUMP_TARGET_SOURCE_POWER_RE, _pump_target_source_power
    ),
    # PAR-80: "target creature gets +X/+0[/+X] until end of turn, where X
    # is <quantity>." — kept before the bare `pump_target_x` row below by
    # this file's more-specific-first convention.
    EffectHandler(
        "pump_target_x_amount", _PUMP_TARGET_X_AMOUNT_RE, _pump_target_x_amount
    ),
    EffectHandler("pump_devotion_target", _PUMP_DEVOTION_TARGET_RE, _pump_devotion_target, fallback_for=("pump_target_x_amount",)),
    EffectHandler(
        "pump_target_x_random", _PUMP_TARGET_X_RANDOM_RE, _pump_target_x_random
    ),
    EffectHandler(
        "reveal_random_hand_card_pump_mv",
        _REVEAL_RANDOM_HAND_CARD_PUMP_MV_RE, _reveal_random_hand_card_pump_mv,
    ),
    EffectHandler(
        "reveal_any_number_pump", _REVEAL_ANY_NUMBER_PUMP_RE, _reveal_any_number_pump
    ),
    # PAR-80: the base X-spell/X-ability pump, no "where X is…" tail —
    # RULE 107.3c's announced {X}, substituted generically at resolve time
    # by `RulesEngine._substitute_x` (no new primitive).
    EffectHandler("pump_target_x", _PUMP_TARGET_X_RE, _pump_target_x),
    EffectHandler(
        "pump_devotion_negative_target", _PUMP_DEVOTION_NEGATIVE_TARGET_RE, _pump_devotion_negative_target
    ),
    EffectHandler("group_pump_devotion", _GROUP_PUMP_DEVOTION_RE, _group_pump_devotion),
    # PAR-81: "Switch target creature's power and toughness until end of
    # turn." and siblings — tried as a block, most-specific (multi-target)
    # first so a shorter row never shadows it.
    EffectHandler("switch_pt_multi", _SWITCH_PT_MULTI_RE, _switch_pt_multi),
    EffectHandler("switch_pt_mass", _SWITCH_PT_MASS_RE, _switch_pt_mass),
    EffectHandler("switch_pt_target", _SWITCH_PT_TARGET_RE, _switch_pt_target),
    EffectHandler("switch_pt_self", _SWITCH_PT_SELF_RE, _switch_pt_self),
    # "Whenever ~ attacks, it gets +X/+X until end of turn, where X is …"
    # (Angelic Exaltation-adjacent self-buff-on-attack) — tried before the
    # flat-amount row below, whose `\d+` would never match a bare "x".
    EffectHandler(
        "pump_self_subject_devotion",
        _PUMP_SELF_SUBJECT_DEVOTION_RE,
        _pump_self_subject_devotion,
        requires=ClauseReading(self_subject=True),
    ),
    # "Whenever ~ attacks, it gets +1/+0 until end of turn." (Akroan Hoplite-
    # adjacent self-buff-on-attack, `it` bound to the ability's own source —
    # `self_subject_only`, only ever offered from a self-subject trigger
    # body).
    EffectHandler(
        "pump_self_subject",
        compile_clause(
            rf"it gets? {PT_DELTA}"
            rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump_self_subject,
        requires=ClauseReading(self_subject=True),
    ),
    # "Whenever ~ attacks, it gains double strike until end of turn."
    # (Flaming Fist) — the keyword-only sibling of `pump_self_subject`
    # above (no P/T delta), `it` bound to the ability's own source.
    EffectHandler(
        "grant_self_subject_kw",
        compile_clause(r"it gains? (?P<kw>[a-z, ]+?) until end of turn"),
        _grant_self_subject_kw,
        requires=ClauseReading(self_subject=True),
    ),
    EffectHandler(
        "lose_previous_subject_kw",
        compile_clause(
            rf"{PREV_SUBJECT_SINGULAR}(?: also)? loses? (?P<lost>[a-z, ]+?)"
            r"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        lambda m: temporary_keyword_change(m, previous_referent=True),
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler("copy_that_spell", _COPY_THAT_SPELL_RE, _copy_that_spell),
    EffectHandler(
        "pump_group_subject",
        compile_clause(
            rf"it gets? {PT_DELTA}"
            rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump_group_subject,
        requires=ClauseReading(group_subject=True),
    ),
    *subject_handlers([
        ("pump_group_subject_x", "group", _PUMP_IT_X_RE, lambda m: _pump_it_x(m, subject="group")),
        ("pump_self_subject_x", "self", _PUMP_IT_X_RE, lambda m: _pump_it_x(m, subject="self")),
        ("pump_previous_subject_x", "previous", _PUMP_IT_X_RE, lambda m: _pump_it_x(m, subject="previous")),
    ]),
    EffectHandler(
        "grant_group_subject_kw",
        compile_clause(
            r"it gains? (?P<kw>[a-z, ]+?) until end of turn"
            # PAR-124: "…and must be blocked this turn if able." (Descend
            # on the Prey).
            r"(?P<must_blocked> and must be blocked this turn if able)?"
        ),
        _grant_group_subject_kw,
        requires=ClauseReading(group_subject=True),
        fallback_for=("pump_prev_singular_kw", "grant_self_subject_kw"),
    ),
    # "It doesn't untap during its controller's untap step for as long as ~
    # remains tapped." — the tap-then-lock family (PAR-11), whose subject is
    # the previous clause's target.
    EffectHandler(
        "lockdown_no_untap",
        compile_clause(
            r"(?:it|that creature|that permanent|that land|that artifact) doesn'?t untap "
            r"during its controller'?s untap step for as long as (?P<cond>.+)"
        ),
        _lockdown,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler("base_pt_previous", _BASE_PT_PREVIOUS_RE, _base_pt_previous, requires=ClauseReading(previous_subject=True)),
    # The same grant with any *other* duration (RULE 611) — "…until your next
    # turn", "…until end of combat". Ordered after the end-of-turn row above,
    # which it can't collide with (that duration isn't in `_GRANT_DURATIONS`).
    EffectHandler('target_quoted_until_source_cast', compile_clause(
        rf'{TARGET} gains? "(?P<inner>.+)" until (?:this card|~) is cast from exile'
        r'(?P<permission>\. you may cast (?:this card|~) for as long as it remains exiled)?'
    ), _target_quoted_until_source_cast),
    EffectHandler('source_quoted_ability', compile_clause(
        r"(?:~|this saga) gains? (?P<quote>[\"'])(?P<inner>.+)(?P=quote)"
        r"(?: (?P<dur>until end of turn|until your next turn|until the end of your next turn|"
        r"until end of combat|until the end of combat|until the beginning of the next end step))?"
    ), _source_quoted_ability),
    EffectHandler(
        "grant_until",
        compile_clause(
            rf"{SUBJECT} gains? (?P<kw>[a-z, ]+?) "
            r"(?P<dur>until (?:your next turn|the end of your next turn|the end of combat|end of combat|"
            r"the beginning of the next end step))"
        ),
        _grant_until,
    ),
    # MEC-88: "target creature loses banding and all 'bands with other'
    # abilities until end of turn." (Tolaria's body) / "…loses all 'bands
    # with other' abilities until end of turn." (Shelkin Brownie).
    EffectHandler(
        "lose_banding",
        _LOSE_BANDING_RE,
        _lose_banding,
    ),
    # The same grant on a *previous* clause's subject ("It gains haste until
    # your next turn." — Offspring's Revenge). Ordered after the `_SUBJECT`
    # row: that one's `_SUBJECT` never matches a bare "it", so no collision.
    EffectHandler(
        "grant_until_previous",
        _GRANT_UNTIL_PREVIOUS_RE,
        _grant_until_previous,
        requires=ClauseReading(previous_subject=True),
    ),
    # PAR-13: the P/T sibling of the row above — "target creature gets
    # -4/-0 until your next turn"/"creatures your opponents control get
    # -3/-0 until your next turn".
    EffectHandler(
        "pump_until",
        compile_clause(
            rf"{SUBJECT} gets? {PT_DELTA} "
            r"(?P<dur>until (?:your next turn|the end of your next turn|the end of combat|end of combat|"
            r"the beginning of the next end step))"
        ),
        _pump_until,
    ),
    # MEC-87: the permanent (no "until …" tail at all) sibling of the row
    # above — "target creature gets +2/+2 and gains horsemanship."
    EffectHandler(
        "pump_and_grant_indefinite",
        compile_clause(rf"{TARGET} gets {PT_DELTA} and gains? (?P<kw>[a-z, ]+)"),
        _pump_and_grant_indefinite,
    ),
    EffectHandler("pump_grant_while_tapped", _PUMP_GRANT_WHILE_TAPPED_RE, _pump_grant_while_tapped),
    # PAR-13: "target creature can't attack/block until <duration>" — the
    # resolve-time-grant sibling of the permanent-static "~ can't attack."
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par13_dungeons_and_variants.py (dungeon room text, not a pool card).
    EffectHandler(
        "cant_attack_or_block_until",
        _CANT_ATTACK_OR_BLOCK_UNTIL_RE,
        _cant_attack_or_block_until,
    ),
]
