"""Add/remove counters and can't-block / can't-be-blocked rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import re

from ..clause_reading import ClauseReading
from typing import Optional
from ..clause_primitives import split_keywords_with_parametric
from ..count_phrase import parse_count_phrase
from ..counters import counter_choice_list, parse_counter_choice_items
from ..static_handlers import object_filter
from ..subgrammars import (
    COUNT,
    count_of,
    count_or_x_of,
    COUNT_X,
    DEVOTION,
    devotion_selector,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    TARGET,
    target_kind_allowed,
)
from ...spec import EffectSpec, GROUP_SUBJECT_KEY_SENTINEL
from .shared import (
    ANY_NUMBER_TARGET_CAP,
    compile_clause,
    counter_sign,
    CREATURE_FILTER_SUFFIX,
    creature_quality_filter,
    EffectHandler,
    except_by_restriction,
    MULTI_TARGET_ALT,
    multi_target_params,
    MULTI_TARGET_QUANTIFIER,
    MULTI_TARGET_QUANTIFIER_X,
    NAMED_COUNTER_KIND,
    optional_param,
    PT_DELTA,
    pump_target,
    pump_target_creature_filter,
    SELF_SUBJECT,
    signed_int,
    SINGLE_TYPE_PERMANENT_KINDS,
    SUBJECT,
)


#: RULE 701.8: "Target opponent chooses a creature they control. Destroy that creature." (Imperial Edict,
#: Wei Assassins) — an edict whose removal is not a sacrifice (regeneration / indestructible still matter, no
#: "sacrificed" triggers). The targeted player picks from their own permanents through the ordinary
#: `choose_objects` selection, and the removal reads that pick back as its subject.
_OPPONENT_CHOOSES_THEN_RE = compile_clause(
    r"(?P<who>target opponent|target player) chooses (?:a|an) (?P<what>creature|artifact|enchantment|land|planeswalker|permanent) "
    r"they control\. destroy (?:that (?P=what)|it)"
)


def _opponent_chooses_then(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("choose_objects", {
        "action": "select_referent", "what": m.group("what"), "count": 1,
        "player_selector": "target",
        # `resolve_target_kind` reads "target opponent" as the broader "player"; an edict must keep the restriction.
        "target_kind": "opponent" if m.group("who") == "target opponent" else "player",
        "then": [{"type": "destroy", "params": {"previous_subject": True}}],
    })]


#: A "±N/±M" P/T counter token (RULE 122.1a). The engine keeps P/T counters as plain kind
#: strings: "+1/+1" and "-1/-1" are the net `GameObject.plus_one_counters` pair, and any other
#: "+a/+b" is an ordinary counter kind that layer 7c adds its own delta for
#: (`continuous._apply_pt_counters`) — so "+0/+1" (Coral Reef, Shield Sphere) is exactly that,
#: not a +1/+1 counter that would have handed the creature power it never had.
_PT_COUNTER_TOKEN = r"[+\-−]\d+/[+\-−]\d+"


def _counter_kind_and_multiplier(token: str) -> tuple[str, int]:
    """A "±N/±M" counter token → ``(kind, count multiplier)``. **Documented simplification:**
    a symmetric "+2/+2 counter" (Baron Sengir, RULE 122.1c — one counter worth +2/+2) is
    modeled as *two* +1/+1 counters — identical for net P/T, differing only for a later
    "remove a +1/+1 counter" / "has a +1/+1 counter" reading. An asymmetric one is its own
    counter kind, spelled with an ASCII sign ("+0/+1"), one counter each."""
    sign = counter_sign(token)
    m = re.match(r"\s*[+\-−](\d+)/[+\-−](\d+)", token)
    if m and m.group(1) == m.group(2):
        return sign, max(1, int(m.group(1)))
    return token.strip().replace("−", "-"), 1


def _add_counters_target_params(
    m: re.Match[str], params: dict, reading: ClauseReading, include_optional: bool = True
) -> Optional[list[EffectSpec]]:
    """The shared selfref-or-target tail every ``add_counters`` builder below
    shares: "on ~" buffs the source untargeted; otherwise the target phrase
    must resolve to a permanent-ish kind (RULE 122.1a — +1/+1 counters can sit
    on *any* permanent, incl. the controller-restricted "target creature you
    control" pick, Archdruid's Charm-shaped) or the clause is unclaimed.
    ``include_optional`` is ``False`` for the one caller
    (`_add_counters_from_trigger_amount`) whose regex has no "up to" group to
    read."""
    if m.groupdict().get("attached"):
        # RULE 303.4m: an explicit enchanted host needs no antecedent;
        # "that creature" only has this meaning under an attached head.
        if m.group("attached") == "that creature" and not reading.attached_subject:
            return None
        params["target_kind"] = "attached_permanent"
        return [EffectSpec("add_counters", params)]
    if m.groupdict().get("selfref"):
        if reading.group_clause and m.group("selfref").lower() == "it":
            # Under a group trigger a bare "it" is the firing object, not the ability's source
            # (PAR-123) — the group readings own it; the source is only ever named ("~").
            return None
        return [EffectSpec("add_counters", params)]
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, (
        "creature", "permanent", "creature_you_control", "other_creature_you_control",
        *SINGLE_TYPE_PERMANENT_KINDS,
    )):
        return None
    params["target_kind"] = kind
    if include_optional:
        params.update(optional_param(m))
    # See `_destroy`'s own comment: "put a counter on target attacking
    # creature" (Sparring Regimen's Lesson-shaped) needs it too.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("add_counters", params)]


#: PAR-71: "put X +1/+1 counters on target creature [you control], where X is
#: that spell's mana value." (Dancing from Dark to Dawn's cast trigger) — the
#: ``mana_value`` sibling of `_add_counters_from_trigger_amount`'s ``"amount"``
#: field. Deliberately **target-only**, no self ("~") alternative: Draining
#: Whelk prints the identical "put X +1/+1 counters on ~, where X is that
#: spell's mana value" tail after "counter target spell" rather than a cast
#: trigger, where "that spell" is the *countered* target
#: (`GameContext.previous_targets`), not a `SPELL_CAST` event — reading
#: `context.trigger_event` there would silently measure 0 (see
#: `_lose_life_spell_mv_that_player`'s docstring for the same trap); it's
#: handled by its own dedicated two-clause row instead.
_ADD_COUNTERS_SPELL_MV_RE = compile_clause(
    rf"put x \+1/\+1 counters? on {TARGET}, where x is that spell'?s mana value"
)


def _add_counters_spell_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent", "creature_you_control", *SINGLE_TYPE_PERMANENT_KINDS)):
        return None
    return [EffectSpec("add_counters", {
        "kind": "+1/+1", "target_kind": kind, "amount_from_trigger_event": "mana_value",
    })]


def _add_counters(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    kind, mag = _counter_kind_and_multiplier(m.group("ckind"))
    count = count_or_x_of(m.group("n"))
    if count == "x":
        if mag != 1:
            return None  # "X +2/+2 counters" — no printed card; don't guess the product
        params: dict = {"count": "x", "kind": kind}
    else:
        params = {"count": count * mag, "kind": kind}
    return _add_counters_target_params(m, params, reading)


_TRANSFER_EVENT_COUNTERS_RE = compile_clause(
    r"put (?:those|its) counters on (?P<optional>up to 1 )?target creature(?P<you> you control)?"
)


def _transfer_event_counters(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("transfer_event_counters", {
        "target_kind": "creature_you_control" if m.group("you") else "creature",
        "optional": bool(m.group("optional")),
    })]


#: PAR-117: "whenever a `<type>` [you control] deals damage, put a `<kind>`
#: counter on **it**." (Rakish Heir/Stensia Masquerade) — "it" is RULE
#: 603.1's group-subject firing object, not this ability's own source, so it
#: needs its own row rather than falling into `_add_counters`'s shared
#: `_SELF_SUBJECT` alternation: that macro folds "it" in with "~"/"this
#: creature"/a card's own name as one undifferentiated self-reference, which
#: is correct for every other caller (a self-damage "Enrage"-shaped trigger's
#: bare "it" really does mean the ability's own source) but wrong here — a
#: card naming *itself* under a group condition ("…dies, put a +1/+1 counter
#: on Malakir Cullblade.") must still buff its own source, not the object
#: that triggered it, so that reading has to stay reachable too. Splitting
#: this into its own `group_subject_only`-gated row, tried *before* the
#: generic one below, keeps both readings: an explicit "~"/name still falls
#: through unclaimed here to the generic row's self-buff, while a bare "it"
#: is claimed here first. The ``"__group_subject__"`` sentinel is resolved
#: to the real event field by `effect_binder._retarget_implicit_subject_
#: effects` (the same pass `TapEffect`'s "untap it" retarget uses) — this
#: handler can't know the field name itself (``instance_id`` vs. `DAMAGE`'s
#: own ``source_id``), only that the clause is a group-subject "it".
_ADD_COUNTERS_GROUP_SUBJECT_IT_RE = compile_clause(
    rf"put {COUNT} (?P<ckind>{_PT_COUNTER_TOKEN}) counters? on it"
)


def _add_counters_group_subject_it(m: re.Match[str]) -> list[EffectSpec]:
    kind, mag = _counter_kind_and_multiplier(m.group("ckind"))
    return [EffectSpec("add_counters", {
        "count": count_of(m.group("n")) * mag, "kind": kind,
        "trigger_subject_key": GROUP_SUBJECT_KEY_SENTINEL,
    })]


#: "Put a -1/-1 counter on target creature, two -1/-1 counters on another
#: target creature, and three -1/-1 counters on a third target creature."
#: (Incremental Blight; the +1/+1 sibling is Incremental Growth) — three
#: escalating RULE 115 targets in one clause, each getting a different
#: number of counters, so it can't be one ``add_counters`` with a target
#: ``count``. Emitted as three ``add_counters`` `EffectSpec`s (the spell-
#: resolution loop partitions its targets per effect); the 2nd/3rd carry
#: ``distinct_from_others`` for RULE 109.5's "another"/"a third".
_INCREMENTAL_COUNTERS_RE = compile_clause(
    r"put a (?P<k1>[+\-−]1/[+\-−]1) counter on target creature, "
    r"(?P<n2>\d+) (?P<k2>[+\-−]1/[+\-−]1) counters on another target creature, "
    r"and (?P<n3>\d+) (?P<k3>[+\-−]1/[+\-−]1) counters on a third target creature"
)


def _incremental_counters(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kinds = {counter_sign(m.group("k1")), counter_sign(m.group("k2")), counter_sign(m.group("k3"))}
    if len(kinds) != 1:
        return None  # all three clauses use the same counter kind on every real card
    kind = kinds.pop()
    n2, n3 = int(m.group("n2")), int(m.group("n3"))
    return [
        EffectSpec("add_counters", {"count": 1, "kind": kind, "target_kind": "creature"}),
        EffectSpec("add_counters", {
            "count": n2, "kind": kind, "target_kind": "creature", "distinct_from_others": True,
        }),
        EffectSpec("add_counters", {
            "count": n3, "kind": kind, "target_kind": "creature", "distinct_from_others": True,
        }),
    ]


# MEC-46 (Galadriel, Elven-Queen) — "[you ]put a +1/+1 counter on your
# Ring-bearer": no RULE 115 target, resolved against `continuous.
# ring_bearer_of` at resolution (`AddCountersEffect.ring_bearer`).
_ADD_COUNTERS_RING_BEARER_RE = compile_clause(
    rf"(?:you )?put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on your ring-bearer"
)


def _add_counters_ring_bearer(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": count_of(m.group("n")),
        "kind": counter_sign(m.group("ckind")),
        "ring_bearer": True,
    })]


# "put a +1/+1 counter on target suspected creature you control" (RULE
# 701.60, PAR-29 — Deadly Complication) — the one adjective-qualified TARGET
# phrase `subgrammars.TARGET`'s own alternation doesn't carry (unlike
# "target attacking/tapped creature", it isn't worth widening that shared
# macro for a single-card phrase), so its own small row feeding
# `combat.matches_object_filter`'s new ``is_suspected`` key.
def _add_counters_suspected_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": count_of(m.group("n")), "kind": counter_sign(m.group("ckind")),
        "target_kind": "creature_you_control", "creature_filter": {"is_suspected": True},
    })]


#: MEC-27: "put x +1/+1 counters on ~/target creature, where x is the number
#: of `<noun phrase>` you control." (Domain-shaped triggers, "the number of
#: Elves you control", etc.) — `subgrammars.DEVOTION`'s wider RULE 613.7c
#: reading, previously wired into `damage`/`lose_life` only
#: (`_damage_selector_devotion`/`_lose_life_selector_devotion`); this is
#: that same reading applied to the counter family via `AddCountersEffect`'s
#: new `amount_from_count_selector`. Requires the literal "x" (not `{COUNT}`
#: — a plain digit/"a"/"an" amount has no "where x is" tail to resolve
#: against), so it's a genuinely separate row from `_add_counters` above,
#: not a widening of its ``{COUNT}`` group.
_ADD_COUNTERS_DEVOTION_RE = compile_clause(
    rf"put x (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
    rf"(?:{TARGET}|(?P<selfref>{SELF_SUBJECT})), where x is {DEVOTION}"
)


def _add_counters_devotion(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    params: dict = {"amount_from_count_selector": dsel, "kind": counter_sign(m.group("ckind"))}
    return _add_counters_target_params(m, params, reading, include_optional=False)
#: `COUNT_X` (not the plain `COUNT`) so an {X}-costed activated ability's
#: own "put X charge counters on ~" (Blast Zone, Ventifact Bottle — PAR-47)
#: is recognized too: the "x" token becomes `EffectSpec`'s literal ``"x"``
#: sentinel via `count_or_x_of`, which `AddCountersEffect.amount` carries
#: unresolved until `RulesEngine._substitute_x` rewrites it against the
#: ability's actually-announced {X} at resolve time — the exact mechanism
#: `_pump_x` already relies on for "gets +x/+x", not a new one.
_ADD_NAMED_COUNTER_RE = compile_clause(
    rf"put {COUNT_X} (?P<ckind>{NAMED_COUNTER_KIND}) counters? on "
    rf"(?:{TARGET}|(?P<selfref>{SELF_SUBJECT}))"
)


#: "put an impostor counter on each creature you control" (Illicit
#: Masquerade) / "put a hone counter on each Equipment you control" (Dwalin) —
#: a named counter on a mass group (`AddCountersEffect.group`, the group read
#: through the shared `parse_count_phrase` grammar).
_ADD_NAMED_COUNTER_GROUP_RE = compile_clause(
    rf"put {COUNT_X} (?P<ckind>{NAMED_COUNTER_KIND}) counters? on each (?P<other>other )?(?P<group>[a-z' -]+?)"
)

#: Batch 5: the +1/+1 / -1/-1 sibling over the same group grammar — "put a +1/+1 counter on each creature you
#: control with a +1/+1 counter on it" (Dueling Coach, Oran-Rief, Edgar), "…on each other Dragon you control"
#: (Acid-Spewer Dragon, Belltoll Dragon), "…on each Ooze you control" (Biogenic Ooze). Registered *after* the
#: closed `add_counters_selector` row, which keeps the named selectors it always read.
_ADD_PT_COUNTER_GROUP_RE = compile_clause(
    rf"put {COUNT_X} (?P<ckind>[+\-−]1/[+\-−]1) counters? on each (?P<other>other )?(?P<group>[a-z0-9' +/\-−]+?)"
)


def _add_counter_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    phrase = m.group("group")
    group = parse_count_phrase(phrase)
    if group is None or group.get("zone") != "battlefield" or "target" in phrase:
        return None
    ckind = m.group("ckind")
    kind = counter_sign(ckind) if ckind[0] in "+-−" else ckind
    params: dict = {"count": count_or_x_of(m.group("n")), "kind": kind, "group": group}
    if m.group("other"):
        params["group_other"] = True
    return [EffectSpec("add_counters", params)]


def _add_named_counter_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _add_counter_group(m)


_ADD_LOYALTY_COUNTER_RE = compile_clause(
    # only the named source: a bare "it" is a referent, and a target creature is not a planeswalker
    rf"put {COUNT_X} loyalty counters? on ~"
)


def _add_loyalty_counter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("add_counters", {"count": count_or_x_of(m.group("n")), "kind": "loyalty"})]


def _add_named_counter(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    params: dict = {"count": count_or_x_of(m.group("n")), "kind": m.group("ckind")}
    return _add_counters_target_params(m, params, reading)


#: MEC-108: "put a +1/+1 counter and a lifelink counter on target creature" /
#: "put a flying counter, a first strike counter, and a lifelink counter on ~" —
#: a fixed list of two or more counter kinds onto one recipient. One
#: `add_counters` per kind: the first carries the recipient (target or self),
#: the rest re-read it (`previous_subject`, the RULE 608.2 referent the first
#: one's target seeds) so a single RULE 115 target serves the whole list.
_COUNTER_LIST_KIND = rf"{_PT_COUNTER_TOKEN}|{NAMED_COUNTER_KIND}"
_COUNTER_LIST_ITEM = rf"(?:a|an|\d+) (?:{_COUNTER_LIST_KIND}) counters?"
_COUNTER_LIST_PART_RE = re.compile(rf"(?P<n>a|an|\d+) (?P<ckind>{_COUNTER_LIST_KIND}) counters?")
_ADD_COUNTER_LIST_RE = compile_clause(
    rf"put (?P<items>{_COUNTER_LIST_ITEM}(?:, {_COUNTER_LIST_ITEM})*,? and {_COUNTER_LIST_ITEM}) on "
    rf"(?:{TARGET}|(?P<selfref>{SELF_SUBJECT}))"
)


def _add_counter_list(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    parts = list(_COUNTER_LIST_PART_RE.finditer(m.group("items")))
    if len(parts) < 2:
        return None
    specs: list[EffectSpec] = []
    for index, part in enumerate(parts):
        token = part.group("ckind")
        kind, mag = _counter_kind_and_multiplier(token) if token[0] in "+-−" else (token, 1)
        params: dict = {"count": count_or_x_of(part.group("n")) * mag, "kind": kind}
        if index == 0:
            built = _add_counters_target_params(m, params, reading)
            if built is None:
                return None
            specs.extend(built)
        else:
            if specs[0].params.get("target_kind"):
                params["previous_subject"] = True
            specs.append(EffectSpec("add_counters", params))
    return specs


#: PAR-140: "put a menace counter on **a creature you control**" / "…on another artifact you control" — a
#: counter on one permanent the controller picks at resolution, no "target" (RULE 122.1, not 115).
#: `AddCountersEffect.choose_one` over the structured group selector the shared count-phrase grammar
#: already reads; "another" is that grammar's "other" (excludes the source).
_ADD_COUNTER_PICK_RE = compile_clause(
    rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1|{NAMED_COUNTER_KIND}) counters? on "
    r"(?:an? |(?P<other>another|other) )(?P<group>[a-z' -]+? you control)"
)


def _add_counter_pick(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    group = parse_count_phrase(("other " if m.group("other") else "") + m.group("group"))
    if group is None or group.get("zone") != "battlefield" or group.get("of") != "you":
        return None
    token = m.group("ckind")
    kind, mag = _counter_kind_and_multiplier(token) if token[0] in "+-−" else (token, 1)
    return [EffectSpec("add_counters", {
        "count": count_or_x_of(m.group("n")) * mag, "kind": kind, "group": group, "choose_one": True,
    })]


#: MEC-108: "put your choice of a +1/+1, first strike, or trample counter on
#: that creature" (Assaultron Dominator) / "…your choice of a menace, trample,
#: reach, or haste counter on ~" / "…a +1/+1 counter or 2 charge counters on
#: up to 1 other target artifact" (Inspirit) — one `add_counters` whose
#: ``kind_options`` the controller picks from at resolution.
_ADD_COUNTER_CHOICE_RE = compile_clause(
    r"put your choice of " + counter_choice_list(NAMED_COUNTER_KIND)
    + rf" on (?:{TARGET}|(?P<selfref>{SELF_SUBJECT}))"
)


def _add_counter_choice(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    options = parse_counter_choice_items(m.group("items"))
    if options is None:
        return None
    return _add_counters_target_params(m, {"kind_options": options}, reading)


#: MEC-108: "remove a menace counter from ~" / "remove 2 charge counters from
#: this creature" — the effect-side sibling of the `remove N <kind> counters`
#: *cost* (`cost_text._REMOVE_COUNTERS_RE`); untargeted, the source's own
#: counters, exactly ``count`` of one kind (none on it: nothing happens).
_REMOVE_NAMED_COUNTER_SELF_RE = compile_clause(
    rf"remove {COUNT} (?P<ckind>{NAMED_COUNTER_KIND}|[+\-−]1/[+\-−]1) "
    rf"counters? from (?P<selfref>{SELF_SUBJECT})"
)


def _remove_named_counter_self(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    if reading.group_clause and m.group("selfref").lower() == "it":
        return None  # under a group trigger a bare "it" is the firing object, not the source
    ckind = m.group("ckind")
    kind = "+1/+1" if ckind[0] == "+" else ("-1/-1" if ckind[0] in "-−" else ckind)
    return [EffectSpec("remove_counters", {
        "self_only": True, "kind": kind, "count": count_or_x_of(m.group("n")),
    })]


def _add_counters_from_trigger_amount(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    params: dict = {"kind": counter_sign(m.group("ckind")), "amount_from_trigger_event": "amount"}
    return _add_counters_target_params(m, params, reading, include_optional=False)


#: "~ gets +X/+X until end of turn, where X is the amount of life you
#: gained." (Field-Tested Frying Pan's granted Equipment ability) — the
#: dynamic-magnitude sibling of `_pump`'s literal-int "+N/+N until end of
#: turn"; only ever seen self-referential (a granted quoted ability's own
#: "~" resolves to whatever object received the grant — the equipped
#: creature — at bind time, see `continuous._apply_layer_6_ability`'s
#: ``source=obj``), so no target form is needed.
_PUMP_SELF_FROM_LIFE_GAINED_RE = compile_clause(
    rf"{SELF_SUBJECT} gets \+x/\+x until end of turn, "
    r"where x is the amount of life you gained"
)


def _pump_self_from_life_gained(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {"amount_from_trigger_event": "amount"})]


#: ENG-32 (Flexible Waterbender / Katara, Water Tribe's Hope) — "~ / creatures
#: you control ha[s|ve] base power and toughness N/M until end of turn"
#: (a resolve-time layer-7b `pt_set`, parked in `GameState.floating_statics`
#: via `grant_until` so it ends at cleanup like any RULE 611 duration).
#: Literal digits or the `{X}` form (Katara — "X can't be 0", a documented
#: simplification: X is announced, and 0 is already meaningless for it).
_BASE_PT_UNTIL_EOT_RE = compile_clause(
    rf"(?:{SELF_SUBJECT}|(?P<group>creatures you control)"
    # "target creature [you control] has base power and toughness N/N until
    # end of turn" (Quandrix Charm / Turn to Frog / Snakeform / Creeperhulk
    # / Ovinize — 59 SOLO). `grant_until` already resolves a RULE 115 target
    # and scopes the parked `pt_set` to those ids.
    rf"|(?P<tgt>target creature(?: you control)?)) "
    rf"(?:has|have) base power and toughness (?P<p>\d+|x)/(?P<t>\d+|x) until end of turn"
    rf"(?:\. x can'?t be 0)?(?:\. activate only during your turn)?"
)


def _base_pt_until_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    def _v(g: str) -> "int | str":
        return "x" if g.lower() == "x" else int(g)

    tgt = (m.groupdict().get("tgt") or "").strip()
    params: dict = {
        "power": _v(m.group("p")), "toughness": _v(m.group("t")),
        "affects": "creatures_you_control" if m.groupdict().get("group") else "self",
    }
    target_kind = None
    if tgt:
        target_kind = "creature_you_control" if "you control" in tgt else "creature"
    return [EffectSpec("grant_until", {
        "static": {"type": "pt_set", "params": params},
        "duration": "end_of_turn",
        "target_kind": target_kind,
    })]


#: PAR-49 / RULE 205.3d + 613.4a: Mistform Dreamer's ``{1}: ~ becomes
#: the creature type of your choice until end of turn.`` This *replaces*
#: the source's existing creature subtypes, unlike "in addition" forms.
_CHOOSE_CREATURE_TYPE_UNTIL_EOT_RE = compile_clause(
    rf"{SELF_SUBJECT} becomes the creature type of your choice until end of turn"
)


def _choose_creature_type_until_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("_request_choose_creature_type_grant", {
        "then_specs": [{
            "type": "grant_until",
            "params": {
                "static": {"type": "type_change", "params": {
                    "set_subtypes_from_source": True,
                }},
                "duration": "end_of_turn",
                "target_kind": None,
                "self_subject": True,
            },
        }],
    })]


#: "put a +1/+1 counter on each of up to two target creatures" (RULE 115.1a
#: generalized to N>=2 — the Support-keyword-shaped family; a live query
#: against the cached Oracle DB found 100+ real cards spelling this out,
#: e.g. Ajani, Adversary of Tyrants/Arcade Cabinet/Basri's Aegis/Bretagard
#: Stronghold). Two numbers in one clause (counter amount vs. target count,
#: the same shape `_damage_each_multi_target` already handles for damage) —
#: ``target_count`` is a deliberately distinct `EffectSpec` key from
#: ``count``/``amount`` (both already mean the *counter* amount here).
def _add_counters_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    mt = multi_target_params(m)
    if mt is None or not target_kind_allowed(
        mt["target_kind"], ("creature", "permanent", *SINGLE_TYPE_PERMANENT_KINDS),
    ):
        return None
    params: dict = {
        "count": count_of(m.group("n")),
        "kind": counter_sign(m.group("ckind")),
        "target_kind": mt["target_kind"],
        "target_count": mt["count"],
    }
    if mt.get("count_selector"):
        # "put a +1/+1 counter on each of X target creatures": the announced X, not a fixed count.
        params.pop("target_count")
        params["target_count_selector"] = mt["count_selector"]
    if mt.get("optional"):
        params["optional"] = True
    if mt.get("count_max") is not None:
        # ENG-30: "put a +1/+1 counter on each of 1 or 2 target creatures" —
        # `target_count`/`target_count_max` is the *target* range, distinct
        # from `count`/`amount` (both already the counter amount per card).
        params["target_count_max"] = mt["count_max"]
    return [EffectSpec("add_counters", params)]


#: PAR-15's "distribute N +1/+1 counters among any number of target
#: creatures[ you control]" (Blessings of Nature/Jugan, the Rising Star/
#: Verdurous Gearhulk) — the *divided pool* sibling of `_add_counters_
#: multi_target`'s "each of up to N" full-amount-per-target shape, mirroring
#: `_divided_damage`'s relationship to `_damage_each_multi_target`
#: (`AddCountersEffect.divided`).
_DISTRIBUTE_COUNTERS_RE = compile_clause(
    r"distribute (?P<n>\d+) (?P<ckind>\+1/\+1|-1/-1|−1/−1) counters among any number "
    r"of target creatures(?P<yc> you control)?"
)


def _distribute_counters(m: re.Match[str]) -> list[EffectSpec]:
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("add_counters", {
        "count": int(m.group("n")), "kind": counter_sign(m.group("ckind")), "target_kind": kind,
        "target_count": ANY_NUMBER_TARGET_CAP, "optional": True, "divided": True,
    })]


#: ENG-30: "distribute N +1/+1 counters among 1 or 2 target creatures[ you
#: control]" (Armament Corps/Contagion/Elven Rite/Splendid Agony-shaped) —
#: the *fixed range* sibling of `_DISTRIBUTE_COUNTERS_RE`'s "any number of":
#: a genuine RULE 601.2c minimum of one, not 0..cap.
_DISTRIBUTE_COUNTERS_RANGE_RE = compile_clause(
    r"distribute (?P<n>\d+) (?P<ckind>\+1/\+1|-1/-1|−1/−1) counters among "
    r"(?P<range_min>\d+)(?:, \d+,)? or (?P<range_max>\d+) target creatures(?P<yc> you control)?"
)
#: "distribute N +1/+1 counters among **up to M** target creatures[ you control]" (Court of Garenbrig,
#: Storm the Seedcore) — the divided pool over a RULE 601.2c "up to" target count.
_DISTRIBUTE_COUNTERS_UP_TO_RE = compile_clause(
    r"distribute (?P<n>\d+) (?P<ckind>\+1/\+1|-1/-1|−1/−1) counters among "
    r"up to (?P<up_to>\d+) target creatures(?P<yc> you control)?"
)


def _distribute_counters_up_to(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    up_to = int(m.group("up_to"))
    if up_to < 2:
        return None
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("add_counters", {
        "count": int(m.group("n")), "kind": counter_sign(m.group("ckind")), "target_kind": kind,
        "target_count": up_to, "optional": True, "divided": True,
    })]


def _distribute_counters_range(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
    if range_min < 1 or range_max <= range_min:
        return None
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("add_counters", {
        "count": int(m.group("n")), "kind": counter_sign(m.group("ckind")), "target_kind": kind,
        "target_count": range_min, "target_count_max": range_max, "divided": True,
    })]


#: "put N +1/+1 counters on each creature you control" (RULE 601.2c mass
#: effect, Vastwood Surge-shaped) — a genuinely different shape from
#: `_add_counters`'s RULE 115 target/self forms, so its own handler row
#: rather than folding "each creature you control" into `TARGET` (that
#: grammar deliberately keeps "each ..." selectors out, see
#: `subgrammars._TARGET_ROWS`'s note).
def _add_counters_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = {
        "each creature you control": "each_creature_you_control",
        "each other creature you control": "each_other_creature_you_control",
        "each other planeswalker you control": "each_other_planeswalker_you_control",
        "each creature": "each_creature",
        "each other creature": "each_other_creature",
        "each creature your opponents control": "each_creature_opponents_control",
    }[m.group("selector")]
    amount = count_or_x_of(m.group("n"))
    params: dict = {"kind": counter_sign(m.group("ckind")), "selector": selector}
    if m.groupdict().get("has_counter"):
        params["creature_filter"] = {"has_counter_kind": "+1/+1"}
    if amount == "x":
        # RULE 107.3c: an X in a resolving spell reads that spell's announced X.
        params["x_multiplier"] = 1
    else:
        params["count"] = amount
    return [EffectSpec("add_counters", params)]


#: "target creature gets +1/+0 until end of turn and can't be blocked this
#: turn" (You Come to a River-shaped) — the P/T-then-unblockable ordering
#: (unlike `_pump`'s "and gains <kw> until end of turn", the keyword clause
#: sits *before* "until end of turn"; here "can't be blocked this turn"
#: trails it instead). Widened to the broader `_SUBJECT` (PAR-72, Seafloor
#: Stalker's own activated-ability self-pump "~ gets +1/+0 … and can't be
#: blocked this turn") rather than `TARGET` alone.
_PUMP_UNBLOCKABLE_RE = compile_clause(
    rf"{SUBJECT} gets? {PT_DELTA} until end of turn and can'?t be blocked this turn"
)


def _pump_unblockable(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    # PAR-79: "target creature you control gets +1/+0 … and can't be
    # blocked this turn" (Teleportal) — this row's own allowed set had
    # fallen behind its keyword-grant sibling `_pump_keyword_unblockable`
    # (which already allows the controller-scoped kinds, Apocalypse
    # Runner) and the bare `_cant_be_blocked_turn` row, both of which
    # treat "you control"/"you don't control" as ordinary legal unblockable
    # subjects; this row had simply never been widened to match.
    if target_kind is not None and not target_kind_allowed(target_kind, (
        "creature", "permanent", "creature_you_control", "creature_you_dont_control",
    )):
        return None
    params: dict = {
        "power": signed_int(m.group("p")), "toughness": signed_int(m.group("t")),
        "unblockable": True,
    }
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: ENG-32: a bare "~ / target creature can't be blocked this turn" (Giant
#: Koi's own activated ability / Waterbender Ascension) — the standalone
#: `UnblockableEffect`, no P/T delta (that's `_PUMP_UNBLOCKABLE_RE` above).
#: PAR-79 widened it with the same optional "with power N or less/greater"
#: suffix as `_PUMP_KEYWORD_UNBLOCKABLE_RE` (Crafty Pathmage-shaped).
#: PAR-79: an optional "except by `<filter>`" tail (Departed Deckhand/
#: Gingerbrute/Joven's Tools/Resilient Roadrunner/Tin Street Dodger/
#: Varchild's Crusader) — RULE 509.1b's *permitted*-set restriction
#: (`combat.blocker_allowed`'s existing `"only_blocked_by"` arm, already
#: shipped for the standing static — `static_handlers.py`'s own "~ can
#: only be blocked by `<filter>`" row), reusing `object_filter`'s existing
#: vocabulary rather than a new one. Routes to a different `EffectSpec`
#: type (`combat_restriction_this_turn`) than the bare form, so this stays
#: in `_cant_be_blocked_turn` rather than becoming a second regex.
#: PAR-98 widened the target qualifier from "with power N or less/greater" to
#: the shared `_CREATURE_FILTER_SUFFIX` vocabulary (power/toughness/keyword/
#: counter), so Speed, Young Avenger's "target creature **with haste** can't be
#: blocked this turn except by creatures with haste" parses alongside it.
CANT_BE_BLOCKED_TURN_RE = compile_clause(
    rf"(?:(?P<selfref>{SELF_SUBJECT})|{TARGET})"
    rf"(?: {CREATURE_FILTER_SUFFIX})? can'?t be blocked this turn"
    r"(?: except by (?P<filter>.+))?"
)


def cant_be_blocked_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {}
    if m.groupdict().get("selfref"):
        params["target_kind"] = None
    else:
        kind = resolve_target_kind(m.group("target"))
        # "another target creature you control can't be blocked this turn
        # except by spirits." (Departed Deckhand, PAR-79) — RULE 109.5's
        # "another … you control" resolves to `other_creature_you_control`
        # (`subgrammars.py`), the same kind `_pump_target`'s own broader
        # allowed set already accepts.
        if not target_kind_allowed(kind, (
            "creature", "permanent", "creature_you_control", "creature_you_dont_control",
            "other_creature_you_control",
        )):
            return None
        params["target_kind"] = kind
    quality_filter = creature_quality_filter(m)
    if quality_filter is not None and params["target_kind"] is None:
        return None  # a target-quality qualifier needs a real RULE 115 target, not the bare self form
    if m.groupdict().get("filter"):
        restriction_params: dict = {}
        restriction = except_by_restriction(m.group("filter"))
        if restriction is None:
            return None
        restriction_params["restriction"] = restriction
        if params["target_kind"] is not None:
            restriction_params["target_kind"] = params["target_kind"]
        if quality_filter is not None:
            restriction_params["creature_filter"] = quality_filter
        return [EffectSpec("combat_restriction_this_turn", restriction_params)]
    if quality_filter is not None:
        params["creature_filter"] = quality_filter
    # "up to one target attacking creature can't be blocked this turn"
    # (Alora, Merry Thief) / "…with power 3 or less…" (Gossip's Talent) —
    # see `_destroy`'s own comment: `resolve_target_kind` alone drops the
    # qualifier, same bug in this effect family.
    if not m.groupdict().get("selfref"):
        state_filter = resolve_target_creature_state_filter(m.group("target"))
        if state_filter:
            params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("unblockable", params)]


#: PAR-79: the multi-target form — "up to 2 target creatures can't be
#: blocked this turn." (Ghostform) — RULE 115.1a generalized to N>=2, the
#: shared `_MULTI_TARGET_QUANTIFIER`/`_multi_target_params` machinery
#: every other multi-target row in this file already uses.
_CANT_BE_BLOCKED_TURN_MULTI_RE = compile_clause(
    rf"{MULTI_TARGET_QUANTIFIER}(?P<target>target creatures) can'?t be blocked this turn"
)


def _cant_be_blocked_turn_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = multi_target_params(m)
    if params is None or params["target_kind"] != "creature":
        return None
    out: dict = {"target_kind": "creature", "count": params["count"]}
    if "count_max" in params:
        out["count_max"] = params["count_max"]
    if params.get("optional"):
        out["optional"] = True
    return [EffectSpec("unblockable", out)]


#: PAR-79: the untargeted mass form — "creatures [you control] can't be
#: blocked this turn." (Jace, Arcane Strategist/Keeper of Keys/Veiling
#: Oddity) — RULE 601.2c, no RULE 115 target at all, `UnblockableEffect`'s
#: new `selector` param (mirroring `CantBlockEffect`'s own mass form).
_CANT_BE_BLOCKED_TURN_MASS_RE = compile_clause(
    r"(?P<group>creatures you control|creatures) can'?t be blocked this turn"
)


def _cant_be_blocked_turn_mass(m: re.Match[str]) -> list[EffectSpec]:
    selector = "creatures_you_control" if m.group("group") == "creatures you control" else "all_creatures"
    return [EffectSpec("unblockable", {"selector": selector})]


#: PAR-79: "~ gains lifelink until end of turn and can't be blocked this
#: turn." (Apocalypse Runner/Break Through the Line/Cephalid Inkshrouder-
#: shaped) — the keyword-grant sibling of `_PUMP_UNBLOCKABLE_RE` above (that
#: one is a P/T delta plus unblockable; this is a keyword list plus
#: unblockable, no P/T change). `PumpEffect` already accepts `keywords` and
#: `unblockable` together (see `_pump_keywords`/`_pump_unblockable`) — this
#: is a parser-recognition gap only, not a new primitive. The optional
#: "with power N or less/greater" suffix (Apocalypse Runner/Break Through
#: the Line) mirrors `_GAIN_CONTROL_EOT_RE`'s own identical suffix —
#: `creature_filter`'s `min_power`/`max_power` keys (`targeting.py`), not a
#: new filter shape.
_PUMP_KEYWORD_UNBLOCKABLE_RE = compile_clause(
    rf"{SUBJECT}(?: with power (?P<pn>\d+) or (?P<pcmp>less|greater))?"
    r" gains? (?P<kw>[a-z0-9, ]+?) until end of turn and can'?t be blocked this turn"
)


def _pump_keyword_unblockable(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    # Same allowed set as `_cant_be_blocked_turn` above — "creature you
    # control"/"…don't control" are legal unblockable-grant subjects too
    # (Apocalypse Runner); unlike `_pump_unblockable`, this handler has no
    # P/T delta to worry about conflicting with a non-creature target.
    if target_kind is not None and not target_kind_allowed(target_kind, (
        "creature", "permanent", "creature_you_control", "creature_you_dont_control",
    )):
        return None
    split = split_keywords_with_parametric(m.group("kw"))
    if split is None:
        return None
    flags, parametric = split
    if not flags and not parametric:
        return None
    params: dict = {"unblockable": True}
    if flags:
        params["keywords"] = flags
    if parametric:
        params["parametric_keywords"] = parametric
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    if m.group("pn"):
        key = "max_power" if m.group("pcmp") == "less" else "min_power"
        params["creature_filter"] = {key: int(m.group("pn"))}
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: PAR-79: "[another ]target `<object-filter phrase>` can't be blocked this
#: turn." (Merfolk Sovereign's "target Merfolk creature"; Aquatic Incursion's
#: bare "target merfolk"; Corsairs of Umbar's "target goblin, orc, or
#: pirate"; Private Eye's "target detective"; Bessie, the Doctor's Roadster's
#: "another target attacking creature"/"another target legendary creature";
#: K-9, Mark I's bare "target legendary creature") — one row over the
#: *shared* `static_handlers.object_filter` vocabulary instead of a
#: hand-rolled, ever-growing word list per adjective: that function
#: resolves a bare subtype, a "`<subtype>` creature[s]" noun phrase, an "A,
#: B, or C"/"A or B" list, and — since `object_filter`'s own
#: `_OBJECT_FILTER_FLAG_WORDS` step — a leading "tapped"/"attacking"/
#: "blocking"/"legendary" flag word too, uniformly (all widenings made to
#: `object_filter` itself, so every other caller — the "except by"
#: restriction, the standing static equivalents — benefits too, not just
#: this one search phrase). This row used to sit *after* two now-deleted
#: dedicated regexes for "attacking"/"legendary" specifically, tried first
#: so `object_filter` never saw those words and mis-guessed them as a bogus
#: subtype (`_scope` doesn't know either word); now that `object_filter`
#: strips them itself, this one row is a strict superset of both and they
#: were removed rather than kept as now-dead duplicates. "another " is a
#: no-op beyond widening the match: plain "creature" target kind already
#: defaults `exclude_source=True` (`targeting.py`), same as
#: `_pump_other_attacking_creature`.
_CANT_BE_BLOCKED_TURN_OBJECT_FILTER_RE = compile_clause(
    r"(?:another )?target (?P<filter>[a-z][a-z, ]*?) can'?t be blocked this turn"
)


def _cant_be_blocked_turn_object_filter(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    filt = object_filter(m.group("filter"))
    if filt is None:
        return None
    return [EffectSpec("unblockable", {"target_kind": "creature", "creature_filter": filt})]


#: "Target creature can't block this turn" (Falter/Ahn-Crop Crasher/Abandon
#: the Post) — the *resolve-time* half of the combat-restriction family, and
#: by far its largest: an ordinary one-shot effect (`game/effects/core.py`'s
#: `CantBlockEffect` → `GameObject.temp_cant_block`, cleared at cleanup),
#: not the standing `combat_restriction` static that
#: `catalogue/static_handlers.py` binds. Three shapes, in the order tried
#: below: N targets ("up to two target creatures"), one target, and the
#: untargeted mass form.
_CANT_BLOCK_TURN_MULTI_RE = compile_clause(
    rf"{MULTI_TARGET_QUANTIFIER}(?P<target>{MULTI_TARGET_ALT}) can'?t block this turn"
)
_CANT_BLOCK_TURN_RE = compile_clause(rf"{TARGET} can'?t block this turn")

#: The untargeted mass form's own subject vocabulary (RULE 601.2c) — a
#: `continuous.group_selector_objects` selector plus an optional
#: characteristic narrowing (`combat.matches_object_filter`), since
#: "creatures **without flying**" is a real printed scope no selector name
#: covers. Bare "creatures" is every creature on the battlefield.
_CANT_BLOCK_TURN_GROUPS: dict[str, tuple[str, dict]] = {
    "creatures": ("all_creatures", {}),
    "all creatures": ("all_creatures", {}),
    "creatures without flying": ("all_creatures", {"without_keyword": "flying"}),
    "creatures with flying": ("all_creatures", {"keyword": "flying"}),
    "creatures your opponents control": ("opponents_permanents", {}),
    # PAR-128: the controller scope written after the quality filter
    # (Stoneshock Giant's "creatures without flying your opponents control").
    "creatures without flying your opponents control": (
        "opponents_permanents", {"without_keyword": "flying"}),
    "creatures with flying your opponents control": ("opponents_permanents", {"keyword": "flying"}),
    "creatures you control": ("creatures_you_control", {}),
    "creatures you don't control": ("opponents_permanents", {}),
}
_CANT_BLOCK_TURN_GROUP_RE = compile_clause(
    r"(?P<group>" + "|".join(re.escape(g) for g in _CANT_BLOCK_TURN_GROUPS)
    + r") can'?t block this turn"
)


#: "Target creature can't be regenerated this turn." (Gravebind, Hurr Jackal, Furnace
#: Brood) / "It can't be regenerated this turn." (Engulfing Flames, Rage of Purphoros) /
#: "A creature dealt damage this way can't be regenerated this turn." (Incinerate,
#: Flamebreak) — `CantBeRegeneratedEffect`, RULE 701.16. The pronoun and "dealt damage
#: this way" forms only compete once a preceding clause supplied the referent.
_CANT_BE_REGENERATED_TARGET_RE = compile_clause(rf"{TARGET} can'?t be regenerated this turn")
_CANT_BE_REGENERATED_PREV_RE = compile_clause(r"(?:it|that creature) can'?t be regenerated this turn")
_CANT_BE_REGENERATED_HIT_RE = compile_clause(
    r"(?:an?|each) creatures? dealt damage this way can'?t be regenerated this turn"
    r"|creatures dealt damage this way can'?t be regenerated this turn"
)


def _cant_be_regenerated_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or not target_kind_allowed(
        kind, ("creature", "creature_you_control", "creature_you_dont_control")
    ):
        return None
    return [EffectSpec("cant_be_regenerated", {"target_kind": kind})]


def _cant_be_regenerated_prev(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_be_regenerated", {"previous_subject": True})]


#: PAR-109 (Lim-Dul's Cohort): "Whenever ~ blocks or becomes blocked by a creature, that creature can't be
#: regenerated this turn." -- under a block-relation head "that creature" is the creature on the other side of the
#: block (RULE 509 / 506), not an earlier clause's pick. Emitted with ``trigger_related`` and no filter yet:
#: `segmenter._retarget_block_relation` fills in the head's `related_filter`, and any other head fails closed.
_CANT_BE_REGENERATED_RELATED_RE = compile_clause(r"that creature can'?t be regenerated this turn")


def _cant_be_regenerated_related(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_be_regenerated", {"trigger_related": True})]


def _cant_be_regenerated_hit(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_be_regenerated", {"damaged_this_way": True})]


def _cant_block_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    return [EffectSpec("cant_block_this_turn", {"target_kind": kind, **optional_param(m)})]


def _cant_block_turn_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = multi_target_params(m)
    if params is None or params["target_kind"] != "creature":
        return None
    return [EffectSpec("cant_block_this_turn", params)]


#: "If it's a creature, it can't block this turn." (Searing Barb's own
#: damage-rider tail — "~ deals 2 damage to any target." precedes it; the
#: "any target" can resolve onto a player/planeswalker/battle, so the
#: restriction is gated on the previous clause's target actually being a
#: creature). `CantBlockEffect.previous_subject` acts on
#: `GameContext.previous_targets`; the `ConditionalEffect` gate then
#: short-circuits a non-creature target (`previous_target_is_creature`).
_IF_PREV_CREATURE_CANT_BLOCK_RE = compile_clause(
    r"if it'?s a creature, (?:it|that creature) can'?t block this turn"
)


def _if_prev_creature_cant_block(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(
        "cant_block_this_turn",
        {"previous_subject": True},
        condition={"previous_target_is_creature": True},
    )]


#: "~ can't be blocked by creatures with power 2 or less this turn" (Cavern
#: Stomper) / "target creature can't be blocked by Walls this turn" (Tower of
#: Coireall) — the resolve-time sibling of the standing static that
#: `catalogue/static_handlers.py` claims. Reuses that module's own
#: `_object_filter` so the blocker vocabulary is literally the same one, and
#: only the two subjects real cards print here (``~`` and a single target).
_CANT_BE_BLOCKED_BY_TURN_RE = compile_clause(
    rf"(?:(?P<selfref>~)|{TARGET}) can'?t be blocked by (?P<filter>.+) this turn"
)


def _cant_be_blocked_by_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    filt = object_filter(m.group("filter"))
    if filt is None:
        return None
    params: dict = {"restriction": {"kind": "cant_be_blocked_by", "filter": filt}}
    if not m.group("selfref"):
        kind = resolve_target_kind(m.group("target"))
        if not target_kind_allowed(kind, ("creature", "creature_you_control")):
            return None
        params["target_kind"] = kind
    return [EffectSpec("combat_restriction_this_turn", params)]


def _cant_block_turn_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector, filt = _CANT_BLOCK_TURN_GROUPS[m.group("group").lower()]
    params: dict = {"selector": selector}
    if filt:
        params["filter"] = dict(filt)
    return [EffectSpec("cant_block_this_turn", params)]


#: "Target creature can't block ~ this turn." (RULE 509.1a, Provoke-adjacent
#: but without the untap half) — the *pairwise* sibling of `_cant_block_turn`
#: above: that one bars the target from blocking anything, this one bars it
#: from blocking only this ability's own source. Can't be told apart from a
#: standing static's own filter at parse time (the source's instance id
#: doesn't exist yet), so it rides `GrantCombatRestrictionEffect`'s
#: ``restrict_to_source`` instead — see its docstring.
_CANT_BLOCK_SOURCE_TURN_RE = compile_clause(rf"{TARGET} can'?t block (?:~|it|this creature) this turn")

#: "Target creature blocks ~ this turn if able." — the resolve-time,
#: targeted sibling of the standing "~ must be blocked if able." static:
#: forces one specific (usually opposing) creature to block this ability's
#: own source, checked by `GameEngine._enforce_block_requirements` via the
#: `must_block_target` restriction kind.
_BLOCKS_SOURCE_TURN_IF_ABLE_RE = compile_clause(rf"{TARGET} blocks (?:~|it|this creature) this turn if able")


def _cant_block_source_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    return [EffectSpec("combat_restriction_this_turn", {
        "target_kind": kind,
        "restriction": {"kind": "cant_block_filtered"},
        "restrict_to_source": True,
    })]


def _blocks_source_turn_if_able(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    return [EffectSpec("combat_restriction_this_turn", {
        "target_kind": kind,
        "restriction": {"kind": "must_block_target"},
        "restrict_to_source": True,
    })]


#: "Target creature attacks this turn if able." — the resolve-time, targeted
#: sibling of the standing "~ attacks each combat if able." static (RULE
#: 508.1a): a plain temporary keyword grant (`PumpEffect`'s ``keywords``),
#: since `GameEngine._enforce_attacks_if_able` already reads `combat.has()`,
#: which unions in a `temp_keywords` grant the same as a printed one — no new
#: engine code needed, unlike the pairwise "blocks ~"/"can't block ~" shapes
#: above (which name a *specific* attacker no bare flag can carry).
_ATTACKS_TURN_IF_ABLE_RE = compile_clause(rf"{TARGET} attacks this turn if able")


def _attacks_turn_if_able(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    return [EffectSpec("pump", {"keywords": ["attacks_if_able"], "target_kind": kind})]


#: "Target creature must be blocked this turn if able." (Irresistible Prey/
#: Goldenhide Ox/Head Banger/Satyr Piper) / "~ must be blocked this turn if
#: able." (Loathsome Catoblepas) — the bare (no P/T delta, no "and gains …"
#: suffix) sibling of `_ATTACKS_TURN_IF_ABLE_RE` just above, same "flag
#: keyword, no new engine code" reasoning (RULE 509.1c, `combat.has`).
#: `_SUBJECT`/`_pump_target` resolve the same self/target shapes `_pump`/
#: `_pump_keywords` already do.
_MUST_BE_BLOCKED_TURN_RE = compile_clause(rf"{SUBJECT} must be blocked this turn if able")


def _must_be_blocked_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {"keywords": ["must_be_blocked"]}
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    return [EffectSpec("pump", params)]


ROWS: list[EffectHandler] = [
    # MEC-27: "put x +1/+1 counters on target creature, where x is the
    # number of Elves you control." — tried before the plain `add_counters`
    # row below since "x" never matches that row's `{COUNT}` (digit/"a"/"an"
    # only).
    EffectHandler("add_counters_devotion", _ADD_COUNTERS_DEVOTION_RE, _add_counters_devotion, reading_aware=True),
    # "put a +1/+1 counter on target suspected creature you control" (PAR-29)
    # — tried before the plain `add_counters` row below, whose `TARGET`
    # alternation has no "suspected" adjective row.
    EffectHandler(
        "add_counters_suspected_target",
        compile_clause(rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on target suspected creature you control"),
        _add_counters_suspected_target,
    ),
    # MEC-46 (Galadriel) — "put a +1/+1 counter on your Ring-bearer" —
    # before the plain `add_counters` row (whose `TARGET` alternation has
    # no "your ring-bearer" phrase).
    EffectHandler(
        "add_counters_ring_bearer",
        _ADD_COUNTERS_RING_BEARER_RE,
        _add_counters_ring_bearer,
    ),
    # "put a -1/-1 counter on target creature, two -1/-1 counters on another
    # target creature, and three -1/-1 counters on a third target creature."
    # (Incremental Blight / Incremental Growth) — three escalating targets,
    # tried before the plain `add_counters` row.
    EffectHandler(
        "incremental_counters",
        _INCREMENTAL_COUNTERS_RE,
        _incremental_counters,
    ),
    # PAR-117: the group-subject "it" reading, tried *before* the generic
    # row below so a bare "it" is claimed here while an explicit "~"/name
    # still falls through to that row's self-buff — see
    # `_add_counters_group_subject_it`'s own docstring.
    EffectHandler(
        "add_counters_group_subject_it",
        _ADD_COUNTERS_GROUP_SUBJECT_IT_RE,
        _add_counters_group_subject_it,
        requires=ClauseReading(group_subject=True),
    ),
    # Longstalk Brawl: a preceding "choose target creature you control and
    # target creature you don't control" already announced the pair.  "The
    # creature you control" is the first member, not a new target.
    EffectHandler(
        "add_counters_chosen_creature_you_control",
        compile_clause(
            rf"put {COUNT} (?P<ckind>{_PT_COUNTER_TOKEN}) counters? "
            r"on the creature you control"
        ),
        lambda m: [EffectSpec("add_counters", {
            "count": count_of(m.group("n")) * _counter_kind_and_multiplier(m.group("ckind"))[1],
            "kind": _counter_kind_and_multiplier(m.group("ckind"))[0],
            "previous_subject": True,
        })],
        requires=ClauseReading(previous_subject=True),
    ),
    # "Manifest dread, then put three +1/+1 counters on **that creature**." (Weight Room, Slimy Aquarium) — the object a
    # preceding create/manifest clause left (`created_objects`), named "that creature" rather than "it".
    EffectHandler(
        "add_counters_that_creature",
        compile_clause(
            rf"put {COUNT} (?P<ckind>{_PT_COUNTER_TOKEN}) counters? "
            r"on that creature"
        ),
        lambda m: [EffectSpec("add_counters", {
            "count": count_of(m.group("n")) * _counter_kind_and_multiplier(m.group("ckind"))[1],
            "kind": _counter_kind_and_multiplier(m.group("ckind"))[0],
            "previous_subject": True,
        })],
        requires=ClauseReading(previous_subject=True),
    ),
    # "put a +1/+1 counter on target creature" / "put a -1/-1 counter on …" /
    # "… on ~"/"this creature" (Walking Ballista's "{4}: Put a +1/+1 counter
    # on this creature." — `_SELF_SUBJECT`, the same self-reference
    # vocabulary `_tap_self` already uses, not just the literal ``~`` a
    # card's own name folds to).
    EffectHandler(
        "add_counters",
        compile_clause(
            # "+1/+1" / "-1/-1" — and "+N/+N" for N>1 (Baron Sengir's
            # "+2/+2 counter"), modeled as N +1/+1 counters (see
            # `_counter_kind_and_multiplier`).
            rf"put {COUNT_X} (?P<ckind>{_PT_COUNTER_TOKEN}) counters? on "
            rf"(?:{TARGET}|(?P<selfref>{SELF_SUBJECT})|"
            r"(?P<attached>enchanted (?:creature|artifact|land|enchantment|permanent)|that creature))"
        ),
        _add_counters,
        reading_aware=True,
    ),
    EffectHandler("transfer_event_counters", _TRANSFER_EVENT_COUNTERS_RE,
                  _transfer_event_counters),
    # "put a spore counter on ~" (Deathspore Thallid/Elvish Farmer-shaped)
    # / "…on target fungus" (Fungal Bloom) — the named-counter sibling of
    # the P/T-only row just above.
    EffectHandler(
        "add_named_counter",
        _ADD_NAMED_COUNTER_RE,
        _add_named_counter,
        reading_aware=True,
    ),
    # RULE 306.5b / 122.1: "put a loyalty counter on ~" (Ral, Crackling Wit; Ajani Resolute; Lolth) — a planeswalker's own
    # loyalty is a counter kind the engine keys off (`add_counters` kind ``loyalty``), so it is reserved from the
    # open named-counter row above and read here for the one recipient that is unambiguous: the source itself.
    EffectHandler("add_loyalty_counter", _ADD_LOYALTY_COUNTER_RE, _add_loyalty_counter),
    EffectHandler("opponent_chooses_then", _OPPONENT_CHOOSES_THEN_RE, _opponent_chooses_then),
    EffectHandler("add_named_counter_group", _ADD_NAMED_COUNTER_GROUP_RE, _add_named_counter_group),
    EffectHandler("add_counter_pick", _ADD_COUNTER_PICK_RE, _add_counter_pick),
    EffectHandler("add_counter_list", _ADD_COUNTER_LIST_RE, _add_counter_list, reading_aware=True),
    EffectHandler("add_counter_choice", _ADD_COUNTER_CHOICE_RE, _add_counter_choice, reading_aware=True),
    EffectHandler(
        "remove_named_counter_self", _REMOVE_NAMED_COUNTER_SELF_RE, _remove_named_counter_self, reading_aware=True,
    ),
    # "whenever you gain life, put that many +1/+1 counters on ~/target
    # creature" (Ageless Entity/Karlov-adjacent lifegain payoffs) — tried
    # before the plain `add_counters` row above so its "that many" wins
    # over that row's literal-`COUNT` alternation. `self_subject_only`:
    # its ``(?P<selfref>{_SELF_SUBJECT})`` branch includes the bare pronoun
    # "it", which under a *group*-subject trigger ("whenever a creature you
    # control deals combat damage to a player, put that many +1/+1 counters
    # on it" — Necropolis Regent) means whichever group member fired it,
    # not this ability's own source — claiming it blind would silently
    # buff the wrong object. A player-subject trigger ("whenever you gain
    # life") introduces no such group, so `segmenter.segment_line`'s player-
    # event branch passes ``self_subject=True`` and this row is offered.
    EffectHandler(
        "add_counters_from_trigger_amount",
        compile_clause(
            rf"put that many (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
            rf"(?:{TARGET}|(?P<selfref>{SELF_SUBJECT}))"
        ),
        _add_counters_from_trigger_amount,
        requires=ClauseReading(self_subject=True),
        reading_aware=True,
    ),
    EffectHandler(
        "add_counters_spell_mv", _ADD_COUNTERS_SPELL_MV_RE, _add_counters_spell_mv,
    ),
    # "~ gets +x/+x until end of turn, where x is the amount of life you
    # gained." (Field-Tested Frying Pan's granted ability) — same pronoun-
    # ambiguity gate as the row above.
    EffectHandler(
        "pump_self_from_life_gained",
        _PUMP_SELF_FROM_LIFE_GAINED_RE,
        _pump_self_from_life_gained,
        requires=ClauseReading(self_subject=True),
    ),
    # ENG-32: "~ / creatures you control ha[s|ve] base power and toughness
    # N/M until end of turn" (Flexible Waterbender / Katara, Water Tribe's
    # Hope) — a resolve-time layer-7b `pt_set` via `grant_until`.
    EffectHandler(
        "base_pt_until_eot",
        _BASE_PT_UNTIL_EOT_RE,
        _base_pt_until_eot,
    ),
    EffectHandler(
        "choose_creature_type_until_eot",
        _CHOOSE_CREATURE_TYPE_UNTIL_EOT_RE,
        _choose_creature_type_until_eot,
    ),
    # "put a +1/+1 counter on each of up to two target creatures" (RULE
    # 115.1a generalized to N>=2 — the Support-keyword-shaped family).
    EffectHandler(
        "add_counters_multi_target",
        compile_clause(
            rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on each of "
            rf"{MULTI_TARGET_QUANTIFIER_X}(?:other )?(?P<target>{MULTI_TARGET_ALT})"
        ),
        _add_counters_multi_target,
    ),
    # PAR-15: "distribute N +1/+1 counters among any number of target
    # creatures[ you control]" — a divided pool, not "each of N" full-amount.
    EffectHandler(
        "distribute_counters",
        _DISTRIBUTE_COUNTERS_RE,
        _distribute_counters,
    ),
    # ENG-30: "distribute N +1/+1 counters among 1 or 2 target creatures
    # [you control]" — a genuine RULE 601.2c range, tried before the plain
    # `distribute_counters` row since "1 or 2" would otherwise also satisfy
    # that row's own `\d+` (it doesn't — that row requires "any number of"
    # literally — but keeping the more specific row first matches this
    # file's usual ordering convention for overlapping shapes).
    EffectHandler(
        "distribute_counters_range",
        _DISTRIBUTE_COUNTERS_RANGE_RE,
        _distribute_counters_range,
    ),
    EffectHandler(
        "distribute_counters_up_to", _DISTRIBUTE_COUNTERS_UP_TO_RE, _distribute_counters_up_to,
    ),
    # Garruk's Wolf token carries this printed death-trigger body (RULE 111.3).
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/game/catalogue/cards/test_squirreled_away_deck.py (Garruk's Wolf, a hand-registered card whose text the parser still reads).
    EffectHandler(
        "add_loyalty_counter_garruk_group",
        compile_clause(r"put a loyalty counter on each garruk you control"),
        lambda m: [EffectSpec("add_counters", {
            "kind": "loyalty", "count": 1,
            "group": {"zone": "battlefield", "of": "you", "filter": {"card_type": "planeswalker", "subtype": "Garruk"}},
        })],
    ),
    EffectHandler("add_pt_counter_group", _ADD_PT_COUNTER_GROUP_RE, _add_counter_group),
    # "put N +1/+1 counters on each creature you control" (RULE 601.2c mass
    # effect, Vastwood Surge-shaped).
    EffectHandler(
        "add_counters_selector",
        compile_clause(
            rf"put {COUNT_X} (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
            r"(?P<selector>each other planeswalker you control|each other creature you control"
            r"|each creature your opponents control|each other creature|each creature you control|each creature)"
            r"(?P<has_counter> that has a \+1/\+1 counter on it)?"
        ),
        _add_counters_selector,
        fallback_for=("add_pt_counter_group",),
    ),
    # "target creature gets +1/+0 until end of turn and can't be blocked
    # this turn" (You Come to a River-shaped) — tried before the plain
    # `pump` handler below since it's a strict superset of that shape (a
    # trailing unblockable clause `_pump`'s own grammar doesn't recognise).
    EffectHandler(
        "pump_unblockable",
        _PUMP_UNBLOCKABLE_RE,
        _pump_unblockable,
    ),
    # ENG-32: bare "~ / target creature can't be blocked this turn" (Giant
    # Koi / Waterbender Ascension) — no P/T delta.
    # PAR-79: "up to 2 target creatures can't be blocked this turn." —
    # tried before the singular `cant_be_blocked_this_turn` row below,
    # whose `TARGET` alternation has no multi-target quantifier of its own.
    EffectHandler(
        "cant_be_blocked_this_turn_multi",
        _CANT_BE_BLOCKED_TURN_MULTI_RE,
        _cant_be_blocked_turn_multi,
    ),
    # PAR-79: the untargeted mass form — "creatures [you control] can't be
    # blocked this turn."
    EffectHandler(
        "cant_be_blocked_this_turn_mass",
        _CANT_BE_BLOCKED_TURN_MASS_RE,
        _cant_be_blocked_turn_mass,
    ),
    # PAR-79: "~ gains lifelink until end of turn and can't be blocked this
    # turn" — a strict superset of the plain `pump_keyword` row's shape (a
    # trailing unblockable clause `pump_keyword`'s own grammar doesn't
    # recognise); fullmatch means the two can never both match the same
    # clause, so order between them doesn't matter for correctness.
    EffectHandler(
        "pump_keyword_unblockable",
        _PUMP_KEYWORD_UNBLOCKABLE_RE,
        _pump_keyword_unblockable,
    ),
    EffectHandler(
        "cant_be_blocked_this_turn",
        CANT_BE_BLOCKED_TURN_RE,
        cant_be_blocked_turn,
    ),
    # PAR-79: "[another ]target `<object-filter phrase>` can't be blocked
    # this turn" (Merfolk Sovereign's "target Merfolk creature", Corsairs of
    # Umbar's "target goblin, orc, or pirate", Bessie/Clammy Prowler's
    # "another target attacking/legendary creature", K-9, Mark I's bare
    # "target legendary creature") — one general row over
    # `static_handlers.object_filter`, which now strips a leading
    # "attacking"/"legendary"/"blocking"/"tapped" flag word itself before
    # falling through to subtype/colour parsing, so it no longer needs two
    # dedicated fixed-phrase rows tried ahead of it for exactly those words.
    EffectHandler(
        "cant_be_blocked_this_turn_object_filter",
        _CANT_BE_BLOCKED_TURN_OBJECT_FILTER_RE,
        _cant_be_blocked_turn_object_filter,
        fallback_for=("cant_be_blocked_this_turn",),
    ),
    # "Up to two target creatures can't block this turn" / "target creature
    # can't block this turn" / "creatures without flying can't block this
    # turn" — the multi form first, since its "up to two target creatures"
    # phrase is not something the singular `TARGET` alternation can claim.
    EffectHandler("cant_be_regenerated_target", _CANT_BE_REGENERATED_TARGET_RE, _cant_be_regenerated_target),
    EffectHandler(
        "cant_be_regenerated_prev", _CANT_BE_REGENERATED_PREV_RE, _cant_be_regenerated_prev,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler("cant_be_regenerated_hit", _CANT_BE_REGENERATED_HIT_RE, _cant_be_regenerated_hit),
    EffectHandler(
        "cant_be_regenerated_related", _CANT_BE_REGENERATED_RELATED_RE, _cant_be_regenerated_related,
        requires=ClauseReading(self_subject=True),
    ),
    EffectHandler(
        "cant_block_this_turn_multi",
        _CANT_BLOCK_TURN_MULTI_RE,
        _cant_block_turn_multi,
    ),
    EffectHandler(
        "cant_block_this_turn",
        _CANT_BLOCK_TURN_RE,
        _cant_block_turn,
    ),
    EffectHandler(
        "cant_block_this_turn_group",
        _CANT_BLOCK_TURN_GROUP_RE,
        _cant_block_turn_group,
    ),
    # "If it's a creature, it can't block this turn." (Searing Barb's
    # damage-rider tail) — acts on the previous clause's target.
    EffectHandler(
        "if_prev_creature_cant_block",
        _IF_PREV_CREATURE_CANT_BLOCK_RE,
        _if_prev_creature_cant_block,
    ),
    # "~ can't be blocked by creatures with power 2 or less this turn" — the
    # resolve-time sibling of the standing combat-restriction static.
    EffectHandler(
        "cant_be_blocked_by_this_turn",
        _CANT_BE_BLOCKED_BY_TURN_RE,
        _cant_be_blocked_by_turn,
    ),
    # "Target creature can't block ~ this turn." — the pairwise sibling of
    # `cant_block_this_turn` above (bars blocking *this* source specifically,
    # not every attacker).
    EffectHandler(
        "cant_block_source_this_turn",
        _CANT_BLOCK_SOURCE_TURN_RE,
        _cant_block_source_turn,
    ),
    # "Target creature blocks ~ this turn if able." (RULE 509.1c, resolve-time)
    EffectHandler(
        "blocks_source_this_turn_if_able",
        _BLOCKS_SOURCE_TURN_IF_ABLE_RE,
        _blocks_source_turn_if_able,
    ),
    # "Target creature attacks this turn if able." (RULE 508.1a, resolve-time)
    EffectHandler(
        "attacks_this_turn_if_able",
        _ATTACKS_TURN_IF_ABLE_RE,
        _attacks_turn_if_able,
    ),
    # "Target creature must be blocked this turn if able."/"~ must be
    # blocked this turn if able." (RULE 509.1c, resolve-time, PAR-124).
    EffectHandler(
        "must_be_blocked_this_turn_if_able",
        _MUST_BE_BLOCKED_TURN_RE,
        _must_be_blocked_turn,
    ),
]
