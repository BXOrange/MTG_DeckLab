"""Pump, base-P/T, double/switch and prevention-adjacent rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import re

from typing import Optional
from ..clause_hooks import parse_effect_body
from ..clause_primitives import split_keywords_with_parametric
from ..static_handlers import quoted_ability_grant_effects
from ..subgrammars import (
    COLOR_WORD_ALT,
    NOT_YOU_TAIL,
    NOT_YOU_TARGET_KINDS,
    resolve_color_word,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    TARGET,
    target_kind_allowed,
)
from ...normalize import SELF
from ...spec import EffectSpec, GROUP_SUBJECT_KEY_SENTINEL
from .shared import (
    ANY_NUMBER_TARGET_CAP,
    COLOR_WORDS,
    compile_clause,
    DELAYED_TAIL_INNER,
    EffectHandler,
    optional_param,
    PREV_SUBJECT_SINGULAR,
    PT_DELTA,
    pump_,
    pump_target,
    pump_target_creature_filter,
    SELF_SUBJECT,
    signed_int,
    SUBJECT,
    subject_handlers,
    temporary_keyword_change,
    token_keywords,
)


def _pump_x_power_only(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """`_pump_x`'s power-only sibling — "+x/+0" (the toughness is untouched)."""
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {"power": "x", "toughness": 0}
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


#: "Target Sliver creature gets +2/+2 until end of turn." (Firewake
#: Sliver) — a subtype-filtered creature target, using the same target
#: filter that regenerate/destroy/exile already carry.
_PUMP_SUBTYPE_TARGET_RE = compile_clause(
    r"target (?P<subtype>[a-z]+) creature gets? (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+) until end of turn"
)


def _pump_subtype_target(m: re.Match[str]) -> list[EffectSpec]:
    # "Target attacking/blocking/tapped/untapped creature gets +N/+M…" is
    # RULE 508/509's board-state qualifier, not a real creature subtype —
    # this regex's bare `[a-z]+` capture doesn't know the difference and
    # would otherwise stamp a `creature_filter` naming a subtype
    # ("Attacking") no real creature ever has, making the target
    # unsatisfiable rather than just imprecise (found auditing the same
    # `resolve_target_kind` collapse this file's `_destroy`/`_pump_target`
    # fix addresses one layer down).
    state_filter = resolve_target_creature_state_filter(f"target {m.group('subtype')} creature")
    creature_filter = state_filter or {"subtype": m.group("subtype").capitalize()}
    return [EffectSpec("pump", {
        "power": signed_int(m.group("p")),
        "toughness": signed_int(m.group("t")),
        "target_kind": "creature",
        "creature_filter": creature_filter,
    })]


#: MEC-88's keyword-only sibling of the row above — "Target Bird creature
#: gains banding until end of turn." (Soraya the Falconer) — no P/T delta
#: at all, just a subtype-filtered keyword grant.
_GRANT_SUBTYPE_TARGET_RE = compile_clause(
    r"target (?P<subtype>[a-z]+) creature gains? (?P<kw>[a-z, ]+?) until end of turn"
)


def _grant_subtype_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    # See `_pump_subtype_target`'s own comment: the bare `[a-z]+` capture
    # can't tell a real subtype from a combat-state qualifier.
    state_filter = resolve_target_creature_state_filter(f"target {m.group('subtype')} creature")
    creature_filter = state_filter or {"subtype": m.group("subtype").capitalize()}
    return [EffectSpec("pump", {
        "keywords": keywords,
        "target_kind": "creature",
        "creature_filter": creature_filter,
    })]


def _pump_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"<subject> gets +x/+x [and gains <kw>] until end of turn" — an
    {X}-cost spell/ability's own announced {X} scaling the pump (Tyvar's
    Stand, Untamed Might, Primal Might's first clause). Emits the ``"x"``
    power/toughness sentinel that `RulesEngine._substitute_x` already
    rewrites to `GameObject.x_paid` at resolution; `PumpEffect.
    target_polarity` already tolerates the bare string. Only the symmetric
    "+x/+x"/"-x/-x" forms (no "where X is …" tail — that's a *dynamic board
    count*, a different family). "-x/-x" (Death Wind/Chill Haunting-shaped
    X-cost removal, and PAR-47's "remove X `<kind>` counters from ~: target
    creature gets -x/-x" spend clause — Infused Arrows) reuses the exact
    same ``x_paid``/`StackItem.x` mechanism regardless of whether the
    announced X paid a mana cost or a non-mana one like counters removed
    (`ActivationMixin._pay_activation_cost` stamps ``source.x_paid`` either
    way); `_substitute_x` already resolves the literal ``"-x"`` sentinel on
    a ``power``/``toughness`` attribute (Toxic Deluge's own "-X/-X" needed
    it first)."""
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    sign = m.group("sign")
    magnitude = "-x" if sign in ("-", "−") else "x"
    params: dict = {"power": magnitude, "toughness": magnitude}
    if m.groupdict().get("kw"):
        keywords = token_keywords(m.group("kw"))
        if keywords is None:
            return None  # unmodeled granted ability → fail-closed
        params["keywords"] = keywords
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


_PUMP_X_NONLAND_PERMANENTS_RE = compile_clause(
    r"(?:~|it|this creature) gets? \+x/\+x until end of turn, where x is the number of nonland permanents you control"
)


def _pump_x_nonland_permanents(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "power": 0, "toughness": 0,
        "amount_from_count_selector": "nonland_permanents_you_control",
    })]


#: "Another target attacking creature gains indestructible until end of
#: turn" (Iconic Shield). This is a combat-state target restriction, not a
#: subtype quality the ordinary `_SUBJECT` grammar can represent.
_PUMP_OTHER_ATTACKING_CREATURE_RE = compile_clause(
    r"another target attacking creature gains? (?P<kw>[a-z, ]+?) until end of turn"
)


def _pump_other_attacking_creature(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "target_kind": "creature", "creature_filter": {"attacking": True}, "keywords": keywords,
    })]


#: "target `<c1>` or `<c2>` creature gets +N/+M [and gains `<kw>`] / gains
#: `<kw>` until end of turn" — the Weaver cycle (Hate/Rage/Sky/Might/
#: Spirit Weaver, Sootstoke Kindler, Wilderness Hypnotist). `TargetSpec.
#: colors`' OR narrowing (`_DAMAGE_TARGET_TWO_COLOR_RE`'s pump sibling);
#: the shared `TARGET` macro's fixed rows carry no colour slot, so a
#: dedicated row like Rending Volley's. Only ever two colours on a real
#: card in this shape.
#: P/T delta ("+1/+0" / "-2/-0", ASCII or unicode minus) — inlined rather
#: than `_PT_DELTA` (defined later in this file).
_PUMP_TARGET_TWO_COLOR_RE = compile_clause(
    rf"target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) creature "
    r"(?:gets? (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)(?: and gains? (?P<kw>[a-z, ]+?))?"
    r"|gains? (?P<kw2>[a-z, ]+?))"
    r" until end of turn"
)


def _pump_target_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = [resolve_color_word(m.group("c1")), resolve_color_word(m.group("c2"))]
    if not all(colors) or colors[0] == colors[1]:
        return None
    params: dict = {"target_kind": "creature", "colors": colors}
    if m.groupdict().get("p") is not None:
        params["power"] = signed_int(m.group("p"))
        params["toughness"] = signed_int(m.group("t"))
    kw = m.groupdict().get("kw") or m.groupdict().get("kw2")
    if kw:
        kws = token_keywords(kw)
        if kws is None:
            return None  # a non-flag granted ability → fail-closed
        params["keywords"] = kws
    if "power" not in params and "keywords" not in params:
        return None
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


# RULE 701.10/11 "double"/"triple `<creature>`'s power and toughness [until
# end of turn]" — a `PumpEffect.self_multiplier` recipient-relative pump
# (each recipient's own current power/toughness, not a flat/shared amount),
# PAR-29. Three surface shapes on real cards, each its own row: "double the
# power and toughness of `<TARGET>`/each creature you control" (Dragonclaw
# Strike/Roar of Endless Song), the possessive "double `<TARGET>`'s/~'s
# power and toughness" (Nylea's Colossus/Reckless Amplimancer/Tifa's Limit
# Break's own "triple"), and the bare pronoun "double its power and
# toughness" — offered both `self_subject_only` (Grunn's "whenever ~
# attacks alone, double its power and toughness") and `previous_subject_
# only` (World War Hulk's "choose target creature you control. … double its
# power and toughness.").
_DOUBLE_PT_MULTIPLIERS: dict[str, int] = {"double": 2, "triple": 3}
_DOUBLE_PT_TARGET_KINDS = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control"}
)
#: PAR-135: which half of the stats "double"/"triple" scales — a slot of the four rows below, not a row per
#: wording ("double target creature's power", Bulk Up; "double its power", Death Kiss — 11 cards).
_DOUBLE_STAT = r"(?P<stat>power and toughness|power|toughness)"
_DOUBLE_STAT_PARAM: dict[str, str] = {"power and toughness": "both", "power": "power", "toughness": "toughness"}


def _double_pump(m: re.Match[str], params: dict) -> Optional[list[EffectSpec]]:
    """The one `pump` every double/triple row emits: its multiplier, plus the stat slot."""
    mult = _DOUBLE_PT_MULTIPLIERS.get(m.group("mult"))
    if mult is None:
        return None
    params = {**params, "self_multiplier": mult}
    stat = _DOUBLE_STAT_PARAM[m.group("stat").lower()]
    if stat != "both":
        params["self_multiplier_stat"] = stat
    return [EffectSpec("pump", params)]


_DOUBLE_PRONOUN_RE = compile_clause(rf"(?P<mult>double|triple) its {_DOUBLE_STAT} until end of turn")


def _double_pt_of(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.groupdict().get("each_group"):
        return _double_pump(m, {"selector": "creatures_you_control"})
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _DOUBLE_PT_TARGET_KINDS):
        return None
    return _double_pump(m, {"target_kind": kind, **optional_param(m)})


def _double_pt_possessive(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.groupdict().get("selfposs"):
        return _double_pump(m, {})
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _DOUBLE_PT_TARGET_KINDS):
        return None
    return _double_pump(m, {"target_kind": kind, **optional_param(m)})


def _double_pt_pronoun(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _double_pump(m, {})


def _double_pt_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _double_pump(m, {"previous_subject": True})


def _double_pt_attached(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Whenever equipped creature attacks, double **its** power" — RULE 301.5/303.4 the host
    (`PumpEffect`'s ``attached_permanent`` mode, the one "enchanted creature gains …" already uses)."""
    return _double_pump(m, {"target_kind": "attached_permanent"})


def _double_pt_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Whenever a creature … attacks, double **its** power" — the creature that fired the group trigger,
    read live off the event (`PumpEffect.trigger_subject`, the same route `_pump_group_subject` takes)."""
    return _double_pump(m, {"trigger_subject": True, "trigger_event_key": GROUP_SUBJECT_KEY_SENTINEL})


#: "Target attacking Elf you control gains deathtouch until end of turn."
#: (Gnarlroot Trapper-shaped) — RULE 506.4's attacker status composed with
#: a creature-subtype filter (`combat.matches_object_filter`'s new
#: ``"attacking"`` key), a target phrase the shared `TARGET` macro has no
#: row for.
_PUMP_ATTACKING_SUBTYPE_TARGET_RE = compile_clause(
    r"target attacking (?P<subtype>[a-z]+) you control gains? (?P<kw>[a-z, ]+?) until end of turn"
)


def _pump_attacking_subtype_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "keywords": keywords, "target_kind": "creature_you_control",
        "creature_filter": {"attacking": True, "subtype": m.group("subtype").capitalize()},
    })]

#: "Nonblack creatures get -2/-2 until end of turn." — a normal
#: untargeted group pump with the existing negated-colour object filter.
#: Keep the colour captured so the same catalogue row covers every colour.
_NONCOLOR_CREATURES_PUMP_RE = compile_clause(
    rf"non(?P<color>white|blue|black|red|green) creatures gets? {PT_DELTA} until end of turn"
)


def _noncolor_creatures_pump(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "power": signed_int(m.group("p")), "toughness": signed_int(m.group("t")),
        "selector": "all_creatures",
        "creature_filter": {"without_color": COLOR_WORDS[m.group("color").lower()]},
    })]

#: PAR-15's "any number of target creatures each get +N/+N [and gain
#: `<keyword>`] until end of turn" (Aerial Formation/Ajani's Presence/Cruel
#: Feeding/Desperate Stand/Rouse the Mob-shaped) — the pump-family sibling of
#: `_add_counters_multi_target`'s "each of up to N" shape: every chosen
#: creature gets the *full* stated boost (`PumpEffect`'s ``target_count``,
#: not a divided pool).
_PUMP_MULTI_TARGET_RE = compile_clause(
    rf"any number of target creatures each get {PT_DELTA}"
    rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
)


def _pump_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": signed_int(m.group("p")), "toughness": signed_int(m.group("t")),
        "target_kind": "creature", "target_count": ANY_NUMBER_TARGET_CAP, "optional": True,
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


#: "Untap those creatures." (Colossal Heroics' own trailing sentence,
#: following "Any number of target creatures each get +2/+2 until end of
#: turn.") — the tap-family sibling of `_return_previous_group`: no target
#: of its own, only offered when a preceding multi-target clause actually
#: chose a group (`EffectHandler.previous_subject_only`).
_UNTAP_PREVIOUS_GROUP_RE = compile_clause(r"(?:then )?untap (?:those creatures|them)")


def _untap_previous_group(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("tap", {"previous_subject": True, "untap": True})]


#: "Creatures you control get +2/+1 until end of turn. **Untap those
#: creatures.**" (War Flare, PAR-128) — the mass-selector sibling of
#: `_untap_previous_group`: offered only when the preceding clause acted on a
#: replayable group (`EffectHandler.previous_selector_only`), read back off
#: `GameContext.previous_selector` at resolution.
_TAP_PREVIOUS_SELECTOR_RE = compile_clause(r"(?:then )?(?P<verb>tap|untap) (?:those creatures|them)")


def _tap_previous_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("tap", {"selector": "previous_selector", "untap": m.group("verb").lower() == "untap"})]


#: "…, then untap **that land**." (Avatar Kyoshi — PAR-30, following
#: "earthbend N") / "…, then tap **that permanent**." — the singular
#: `previous_subject` sibling of `_UNTAP_PREVIOUS_GROUP_RE`: "that
#: `<permanent-word>`" names the single object the preceding clause chose
#: (`EffectHandler.previous_subject_only`, `GameContext.previous_targets`).
#: Distinct from `_TAP_GROUP_SUBJECT_RE` ("that creature", `group_subject_
#: only`) and `_tap_self` ("it"/"this ~", the ability's own source).
_TAP_PREVIOUS_SUBJECT_RE = compile_clause(
    r"(?:then )?(?P<verb>tap|untap) that (?:land|permanent|artifact|creature)"
)


def _tap_previous_subject(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("tap", {"previous_subject": True, "untap": m.group("verb").lower() == "untap"})]


#: "[That / target / ~] `<permanent>` doesn't untap during
#: [its controller's / your / the player's] next untap step." — Barl's Cage
#: and the ~95-card "Tap X. It doesn't untap …" tempo family (Chillbringer,
#: Berg Strider, the Frost Lynx cycle, Entangling Trap / Pollen Lullaby
#: clash payoffs, …). `SkipNextUntapEffect` sets `GameObject.
#: skip_next_untap`, RULE 702.19b's own one-time flag. Three subject shapes,
#: routed by the same `_PERMANENT_NOUN`/`~`/pronoun split every other
#: family here uses.
_DONT_UNTAP_SUFFIX = (
    # PAR-150: "their controllers' next untap steps" -- the plural wording of a multi-target tap (Sudden Storm).
    r" do(?:es)?n'?t untap during (?:its controller'?s|their controller'?s|their controllers'|your|the player'?s)"
    r" next untap steps?"
)
_SKIP_UNTAP_TARGET_RE = compile_clause(
    rf"target (?P<what>creature|artifact|land|permanent)(?P<scope>{NOT_YOU_TAIL})?{_DONT_UNTAP_SUFFIX}"
)
_SKIP_UNTAP_PREV_RE = compile_clause(
    rf"(?:it|that (?:creature|artifact|land|permanent)|those creatures){_DONT_UNTAP_SUFFIX}"
)
_SKIP_UNTAP_SELF_RE = compile_clause(rf"(?:~|this (?:creature|artifact|permanent)){_DONT_UNTAP_SUFFIX}")


def _skip_untap_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = m.group("what")
    if m.group("scope"):
        # PAR-128: "target creature an opponent controls doesn't untap …" (Fogwalker).
        kind = NOT_YOU_TARGET_KINDS.get(kind)
        if kind is None:
            return None
    return [EffectSpec("skip_next_untap", {"target_kind": kind})]


def _skip_untap_prev(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_untap", {"previous_subject": True})]


#: PAR-128: "…tap all attacking creatures. **Those creatures** don't untap
#: during their controller's next untap step." (Clinging Mists) — the
#: mass-selector sibling of `_SKIP_UNTAP_PREV_RE`, plural wording included
#: ("their controllers' next untap steps").
_SKIP_UNTAP_PREV_SELECTOR_RE = compile_clause(
    r"(?:they|those creatures) don'?t untap during "
    r"(?:their controller'?s next untap step|their controllers'? next untap steps|"
    # Sleep: the chosen player's own creatures, so "that player's" is their controller's.
    r"that player'?s next untap step)"
)


def _skip_untap_prev_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_untap", {"target_kind": None, "subject": "previous_selector"})]


def _skip_untap_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_untap", {"target_kind": None})]


#: "Whenever ~ deals combat damage to a creature, tap that creature and it
#: doesn't untap during its controller's next untap step." (PAR-84 —
#: Kashi-Tribe Reaver and siblings).  Both pronouns name the DAMAGE event's
#: *recipient*, rather than the source that dealt it; `target_operand` keeps
#: this distinct from a normal RULE 115 target and reads that event payload at
#: resolution time.
_TAP_DAMAGE_RECIPIENT_AND_SKIP_UNTAP_RE = compile_clause(
    rf"tap that creature and it{_DONT_UNTAP_SUFFIX}"
)


def _tap_damage_recipient_and_skip_untap(m: re.Match[str]) -> list[EffectSpec]:
    params = {"target_operand": "damage_recipient"}
    return [EffectSpec("tap", params), EffectSpec("skip_next_untap", params)]


#: "The next N damage that would be dealt to ~ this turn is dealt to target
#: creature you control instead." (PAR-85 — en-Kor).  This watches damage's
#: recipient, unlike the existing chosen-*source* redirect family.
_REDIRECT_DAMAGE_TO_SELF_RE = compile_clause(
    rf"the next (?P<n>\d+) damage that would be dealt to ~ this turn is dealt to target creature you control instead"
)


def _redirect_damage_to_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("redirect_damage_to_target_creature", {"amount": int(m.group("n"))})]


#: "[`<TARGET>` / ~ / it] gains protection from the color of your choice
#: until end of turn." (Gods Willing / Emerge Unscathed / Jareth / Feat of
#: Resistance — RULE 702.16, ~27 SOLO). The engine primitive
#: (`effects.GrantProtectionEffect` / `RulesEngine.grant_protection_choice`
#: — the interactive `grant_protection_color` pick, `temp_protections`,
#: cleared at cleanup) is Mother of Runes'; only the parser recognition of
#: this exact phrasing was missing.
_PROT_CHOICE_SUFFIX = r" gains? protection from the colou?r of your choice until end of turn"
_GRANT_PROT_CHOICE_TARGET_RE = compile_clause(rf"{TARGET}{_PROT_CHOICE_SUFFIX}")
_GRANT_PROT_CHOICE_SELF_RE = compile_clause(rf"{SELF_SUBJECT}{_PROT_CHOICE_SUFFIX}")
_GRANT_PROT_CHOICE_PREV_RE = compile_clause(rf"it{_PROT_CHOICE_SUFFIX}")
_GRANT_PROT_CHOICE_KINDS = frozenset({"creature", "creature_you_control", "permanent_you_control"})


def _grant_prot_choice_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _GRANT_PROT_CHOICE_KINDS):
        return None
    return [EffectSpec("grant_protection", {"target_kind": kind})]


def _grant_prot_choice_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_protection", {"target_kind": None})]


def _grant_prot_choice_prev(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_protection", {"previous_subject": True})]


_GROUP_FIXED_PROTECTION_RE = compile_clause(
    r"(?P<group>creatures you control|all creatures|creatures your opponents control) "
    r"gain protection from (?P<color>white|blue|black|red|green) until end of turn"
)
_GROUP_FIXED_PROTECTION_SELECTORS = {
    "creatures you control": "creatures_you_control",
    "all creatures": "all_creatures",
    "creatures your opponents control": "creatures_opponents_control",
}


def _group_fixed_protection(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_fixed_protection_group", {
        "selector": _GROUP_FIXED_PROTECTION_SELECTORS[m.group("group")],
        "color": COLOR_WORDS[m.group("color")],
    })]


#: "Reveal cards from the top of your library until you reveal a `<land /
#: creature / artifact / enchantment / nonland / basic land>` card. Put that
#: card `<onto the battlefield / into your hand>` and the rest `<on the
#: bottom of your library in a random order / into your graveyard / shuffle
#: into your library>`." (Recross the Paths, Clifftop Lookout, Atla Palani,
#: Bloodline Pretender-cycle, ~40 real cards.) `RulesEngine.dig_until` /
#: `effects.DigUntilEffect` — the generalized cascade dig — is the engine
#: primitive; this is its "reveal until a *type* predicate" recognition.
#: **Documented simplification**: "in any order" is modeled as the engine's
#: only bottoming mode, a *random* order — the player doesn't get to choose
#: the sequence of the bottomed cards.
_DIG_UNTIL_PRED = {
    "a land": {"type": "land"},
    "a basic land": {"type": "land", "basic": True},
    "a creature": {"type": "creature"},
    "an artifact": {"type": "artifact"},
    "an enchantment": {"type": "enchantment"},
    "a nonland": {"without_type": "land"},
    "a nonartifact, nonland": {"without_type": ["artifact", "land"]},
}
_DIG_UNTIL_HIT = {
    # PAR-148 (RULE 508.4): listed first so the longer phrase wins the alternation.
    "onto the battlefield tapped and attacking": "battlefield_attacking",
    "onto the battlefield": "battlefield",
    "into your hand": "hand",
}
#: The "…and the rest `<somewhere>`" tail — matched as a whole phrase
#: (`re.search` inside the leftover) so the many "put all other cards
#: revealed this way" / "the rest" / ", then shuffle" connector spellings
#: don't each need a row.
_DIG_UNTIL_REST_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"bottom of your library in (?:a random|any) order", re.I), "library_bottom_random"),
    (re.compile(r"shuffle .*?into your library", re.I), "library_shuffled"),
    (re.compile(r"(?:cards? .*?)?into your graveyard", re.I), "graveyard"),
]
_REVEAL_UNTIL_TYPE_RE = compile_clause(
    r"reveal cards from the top of your library until you reveal "
    rf"(?P<pred>{'|'.join(map(re.escape, _DIG_UNTIL_PRED))}) card\. "
    rf"put that card (?P<hit>{'|'.join(map(re.escape, _DIG_UNTIL_HIT))})"
    r"(?P<rest>.+)"
)


#: PAR-75: "Reveal cards from the top of your library until you reveal a
#: Doctor card, a card with doctor's companion, or a Vehicle card. Put that
#: card into your hand and the rest on the bottom of your library in a
#: random order." (An Unearthly Child) — a three-way OR predicate
#: `_DIG_UNTIL_PRED`'s single-bare-type grammar can't express (one of its
#: three arms is a printed-keyword check, not a card type/subtype at all).
#: `card_query.matches`'s existing `"or"` key composes the three arms
#: directly, so this is a fixed singleton row rather than a new compositional
#: OR grammar — no other cached card shares this exact three-way shape.
_DIG_UNTIL_DOCTOR_COMPANION_VEHICLE_RE = compile_clause(
    r"reveal cards from the top of your library until you reveal a doctor card, "
    r"a card with doctor'?s companion, or a vehicle card\. "
    r"put that card into your hand and the rest on the bottom of your library "
    r"in a random order"
)


def _dig_until_doctor_companion_vehicle(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("dig_until", {
        "criteria": {"or": [
            {"type": "Doctor"},
            {"has_keyword": "Doctor's Companion"},
            {"type": "Vehicle"},
        ]},
        "hit_destination": "hand",
        "rest_destination": "library_bottom_random",
    })]


#: PAR-76: "`<base effect>`. If you have a full party, `<bigger effect>`
#: instead." (RULE 700.8/702.129) — a resolve-time magnitude override, the
#: same "if `<card-specific condition>`, `<bigger effect>` instead" shape
#: `DealDamageEffect.amount_if_kicked`/`amount_if_raid` already establish
#: for Kicker/Raid, generalized to a new `amount_if_full_party` field on
#: both `DealDamageEffect` and `AddCountersEffect` (RULE 700.8's "full
#: party" is exactly 4 — one each of Cleric/Rogue/Warrior/Wizard — the
#: `"creatures_in_your_party"` count selector's own cap, checked live at
#: resolution as a threshold rather than read as a magnitude the way
#: PAR-72's `count_selector_multiplier` family does). Two fixed singleton
#: rows (matched as one whole two-sentence clause, before the connector
#: split ever runs) rather than a general "if `<condition>`, `<bigger
#: effect>` instead" grammar — no other cached card pairs "full party" with
#: a magnitude override on a *third* effect shape yet.
_DAMAGE_EACH_OPPONENT_FULL_PARTY_RE = compile_clause(
    r"~ deals (?P<n>\d+) damage to each opponent\. "
    r"if you have a full party, it deals (?P<n2>\d+) damage to each opponent instead"
)


def _damage_each_opponent_full_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "selector": "each_opponent",
        "amount_if_full_party": int(m.group("n2")),
    })]


_ADD_COUNTER_TARGET_FULL_PARTY_RE = compile_clause(
    r"put an? \+1/\+1 counter on target creature you control\. "
    r"if you have a full party, put (?P<n2>\d+) \+1/\+1 counters on that creature instead"
)


def _add_counter_target_full_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "kind": "+1/+1", "target_kind": "creature_you_control",
        "amount_if_full_party": int(m.group("n2")),
    })]


def _reveal_until_type(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    tail = m.group("rest")
    # "put that card onto the battlefield **tapped**" (Clifftop Lookout) —
    # `dig_until`'s `_place_dig_hit` has no tapped-entry mode, and a land
    # entering tapped vs untapped is a real difference; fail closed.
    if re.match(r"(?i)^\s*tapped\b", tail):
        return None
    # "…onto the battlefield **and attach ~ to it**" (Shifting Shadow) — the attachment is a separate instruction
    # `dig_until` has no slot for; claiming the row would silently drop it.
    if re.search(r"(?i)\battach\b", tail):
        return None
    rest_dest = next((d for rx, d in _DIG_UNTIL_REST_RES if rx.search(tail)), None)
    if rest_dest is None:
        return None
    return [EffectSpec("dig_until", {
        "criteria": dict(_DIG_UNTIL_PRED[m.group("pred")]),
        "hit_destination": _DIG_UNTIL_HIT[m.group("hit")],
        "rest_destination": rest_dest,
    })]


#: PAR-30 — the single biggest RULE 701-trail sub-cluster (~100 SOLO cache
#: cards): a trailing "[Then] sacrifice / exile <it / that creature / that
#: token / them / those tokens> at the beginning of [the/your] next end
#: step." (Kiki-Jiki / Twinflame / every "create a token …, exile it" and
#: "reanimate …, sacrifice it" card). RULE 603.7 delayed trigger over
#: `create_delayed_trigger` — the same primitive the hand-authored
#: Kiki-Jiki/Twinflame entries use, with a new ``capture="previous_or_
#: self"`` that bakes in whatever the *earlier clause of this same
#: resolution* chose (RULE 115 target — `GameContext.previous_targets`) or
#: created (RULE 608.2 — `created_objects`), falling back to the ability's
#: own source for a bare self-subject "sacrifice it" (Brackwater Elemental /
#: Deathknell Kami). Deliberately **not** `previous_subject_only`: the
#: capture no-ops cleanly on an empty referent chain (same safety the
#: exile→copy connector relies on), and a create-token antecedent never
#: sets the segmenter's `previous_subject` flag, so gating would miss the
#: majority of the cluster.
#: PAR-80: "~" (Wine of Blood and Iron's "Sacrifice ~ at the beginning of
#: the next end step.") is an *explicit* self-reference, unlike "it"/"that
#: creature"'s `previous_or_self` chain — it never means whatever an
#: earlier clause of the same resolution targeted/created (Wine of Blood
#: and Iron's own earlier clause targets the creature it *pumps*, not
#: itself), so it gets its own unconditional ``capture="self"`` rather than
#: joining the ``obj`` alternation's `previous_or_self` group.
#: PAR-117 (residue): an optional "**its controller** sacrifices/exiles/
#: destroys `<it>` …" subject (Celestial Sword/Goblin Ski Patrol — "Its
#: controller sacrifices it at the beginning of the next end step.") is
#: *not* a fourth referent needing its own plumbing: RULE 701.17a already
#: means "sacrifice" is inherently self-directed — a permanent's sacrifice
#: always comes from **its own** controller, never another player's — so
#: `SacrificeSpecificEffect.apply` (`context.engine.put_into_graveyard
#: (obj)`) never reads a player at all, only the object. "Its controller
#: sacrifices it" and a bare "sacrifice it" therefore compile to the
#: identical spec; only the recognition needed widening, not `capture`/the
#: effect type. Third-person "sacrifices"/"exiles"/"destroys" only ever
#: appears with this explicit subject present (an unprefixed clause is
#: always the imperative "sacrifice"/"exile"/"destroy"), so the two forms
#: don't need disambiguating beyond the verb conjugation itself.
DELAYED_SAC_EXILE_TAIL_RE = compile_clause(
    r"(?:then )?(?:"
    # PAR-98: Goblin Sappers destroys the earlier target *and* itself at
    # end of combat.  These become two delayed triggers because each has a
    # different captured referent.
    r"(?P<verb_double>destroy) (?P<obj_double>it) and (?P<obj_double_self>~)"
    r"|"
    r"(?:its controller (?P<verb_ctrl>sacrifices|exiles|destroys)"
    r"|(?P<verb>sacrifice|exile|destroy)) "
    r"(?:(?P<obj>it|that creature|that token|the tokens?|that permanent|that artifact|those tokens|them|all tokens created this way)|(?P<obj_self>~))"
    # "Return that creature to its owner's hand" (Ilharg, Zara, Alora) — a
    # loan bounced end of turn; the object is the same `previous_or_self`
    # referent the sacrifice/exile forms use.
    r"|(?P<verb_return>return) (?:it|that creature|that token|that permanent) to (?:your|its owner'?s) hand"
    # "It phases out at end of combat" (Teferi's Veil, PAR-123) — the subject leads the verb.
    r"|(?P<phase_subject>it|that creature|that permanent) phases? out"
    # PAR-152 / RULE 701.28a: "convert ~ at end of combat" (Ultra Magnus) — the source flips its face then.
    rf"|(?P<verb_turn>transform|convert) (?P<obj_turn>{re.escape(SELF)}|it)"
    r") "
    # "at end of combat" (Kari Zev, Calamity, every "tapped and attacking"
    # token) fires at the `end_combat` step, "the/your next end step" at the
    # ordinary `end` step (RULE 603.7).
    r"(?P<when>at the beginning of (?:the|your) next end step|at end of combat)"
)


def _delayed_sac_exile_tail(m: re.Match[str]) -> list[EffectSpec]:
    if m.groupdict().get("verb_double"):
        step = "end_combat" if m.group("when").lower() == "at end of combat" else "end"
        return [
            EffectSpec("create_delayed_trigger", {
                "step": step, "scope": "any", "capture": "previous_or_self",
                "effects": [{"type": "destroy_specific", "params": {}}],
            }),
            EffectSpec("create_delayed_trigger", {
                "step": step, "scope": "any", "capture": "self",
                "effects": [{"type": "destroy_specific", "params": {}}],
            }),
        ]
    if m.groupdict().get("phase_subject"):
        step = "end_combat" if m.group("when").lower() == "at end of combat" else "end"
        return [EffectSpec("create_delayed_trigger", {
            "step": step, "scope": "any", "capture": "previous_or_self",
            "effects": [{"type": "phase_out", "params": {}}],
        })]
    if m.groupdict().get("verb_turn"):
        step = "end_combat" if m.group("when").lower() == "at end of combat" else "end"
        return [EffectSpec("create_delayed_trigger", {
            "step": step, "scope": "any",
            "capture": "self" if m.group("obj_turn") == SELF else "previous_or_self",
            "effects": [{"type": "transform", "params": {}}],
        })]
    verb_ctrl = m.groupdict().get("verb_ctrl")
    verb = (
        m.groupdict().get("verb") or m.groupdict().get("verb_return")
        or (verb_ctrl.rstrip("s") if verb_ctrl else "")
    ).lower()
    inner = DELAYED_TAIL_INNER[verb]
    step = "end_combat" if m.group("when").lower() == "at end of combat" else "end"
    obj = (m.groupdict().get("obj") or "").lower()
    if m.groupdict().get("obj_self"):
        capture = "self"
    elif obj in _DELAYED_TAIL_TOKEN_SUBJECTS:
        capture = "created_objects"
    else:
        capture = "previous_or_self"
    return [EffectSpec("create_delayed_trigger", {
        "step": step,
        "scope": "any",
        "capture": capture,
        "effects": [{"type": inner, "params": {}}],
    })]


#: PAR-139: "If that creature would leave the battlefield, exile it instead of putting it anywhere else." — the
#: tail of a corpse-counter reanimation (From the Catacombs, Isareth the Awakener). "That creature" is the card
#: the earlier clause returned, so the row is gated on that clause having chosen one (`previous_subject_only`).
_EXILE_INSTEAD_OF_LEAVING_RE = compile_clause(
    r"if that creature would leave the battlefield, exile it instead of putting it anywhere else"
)


def _exile_instead_of_leaving(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile_instead_of_leaving", {})]


#: PAR-139: "its owner shuffles their graveyard into their library" — the tail of "When ~ is put into a graveyard
#: from anywhere, …" (Emrakul, the Aeons Torn; Ulamog, the Infinite Gyre). "Its" is the ability's own source.
_OWNER_SHUFFLES_GRAVEYARD_RE = compile_clause(r"its owner shuffles their graveyard into their library")


def _owner_shuffles_graveyard(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_graveyard_into_library", {"owner_of_source": True})]


#: PAR-136: "Return that card to the battlefield under its owner's control at the beginning of the next end
#: step." — the delayed half of a flicker (Flickerwisp, Turn to Mist, Aetherling's self-blink, Ghostway).
#: A separate, *gated* row rather than a verb of `DELAYED_SAC_EXILE_TAIL_RE`: "it" must name a card an
#: earlier clause of the same ability just **exiled** (`previous_subject_only`, or the ability's own source
#: for "exile ~. Return it …", `self_subject_only`). Ungated it also claimed a *dies* trigger's
#: "return it to the battlefield …" (Resurrection Orb), where nothing is in exile and the effect would
#: silently do nothing.
_DELAYED_RETURN_BATTLEFIELD_RE = compile_clause(
    r"return (?:it|that card|that creature|that permanent|them|those cards|the exiled cards?) to the "
    r"battlefield(?P<tapped> tapped)? under (?:its|their) (?:owner'?s|owners') control at the beginning of the next end step"
)


def _delayed_return_battlefield(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_delayed_trigger", {
        "step": "end", "scope": "any", "capture": "previous_or_self",
        "effects": [{"type": "return_specific_to_battlefield", "params": {"tapped": True} if m.group("tapped") else {}}],
    })]


#: The *when-first* sibling of `DELAYED_SAC_EXILE_TAIL_RE` — "At the
#: beginning of the next end step, sacrifice/exile/return `<it>`[ unless
#: `<X>`][. If you do, `<effect>`.]" (Apprentice Necromancer, Momo's Heist,
#: Skirk Alarmist, The Beamtown Bullies, Sauron the Necromancer — MEC-52;
#: the "return" branch and the trailing "if you do" — PAR-79 eighth
#: increment — add the Alora cycle, Ilharg/Zara's own "when-first" phrasing
#: sibling). Same `previous_or_self` capture and inner effect as the tail
#: form; the optional trailing "unless ~ is your Ring-bearer" rider (RULE
#: 603.4 intervening-if — Sauron only) is threaded as `create_delayed_
#: trigger`'s new whitelisted ``condition`` param
#: (`_ALLOWED_CONDITION_KEYS["is_ring_bearer"]`, ``False`` = "…unless").
#: Other "unless" riders on this shape (Satya "unless you pay {E}…",
#: Tilonalli's Summoner "unless you have the city's blessing") are a
#: pay-cost / designation check this doesn't model — they stay fail-closed.
#:
#: RULE 603.3's "if you do" here is the *delayed ability's own* reflexive
#: trigger, not `_may_effect_then`'s "you may" gate — nothing about this
#: shape makes the antecedent optional at all (there's no "may"; sacrifice/
#: exile/return happens unconditionally once the delayed ability fires), so
#: unlike `_SACRIFICE_THEN_WHEN_YOU_DO_RE`'s "certain, so collapse" idiom
#: this isn't a simplification — RULE 603.3's "if you do" is trivially true
#: whenever the antecedent could apply at all (`ReturnSpecificToHandEffect`/
#: `SacrificeSpecificEffect`'s own "skip if it already left the battlefield"
#: no-op is the one case it doesn't, and this ability then correctly does
#: nothing further either). The recursively-parsed "after" tail is appended
#: to the *same* delayed trigger's ``effects`` list rather than opened as a
#: second delayed trigger of its own, so both run off the one `DelayedTrigger`
#: this ability arms — correct RULE 608.2/603.7 sequencing (the follow-up
#: never fires as a separate, independently-timed trigger). No `previous_
#: subject` propagation into the "after" parse: `CreateDelayedTriggerEffect`'s
#: own ``capture="previous_or_self"`` bakes the referent directly onto every
#: inner effect exposing ``.objects``/``.target`` *at arm time* (this
#: resolution's `GameContext.previous_targets`), not read again when the
#: delayed ability fires — by then `previous_targets` could hold anything
#: (a wholly unrelated later resolution's targets) or nothing, so an "if you
#: do" tail naming "it" again (Alora, Cheerful Scout's "it perpetually gets
#: +1/+1") isn't reachable through this recursive parse and stays fail-closed
#: (a `.target`-bearing effect built with no target set is worse than
#: UNMODELED) — real, separately-scoped residue, not attempted here.
_DELAYED_SAC_EXILE_WHEN_FIRST_RE = compile_clause(
    r"at the beginning of (?:the|your) next end step, "
    r"(?:"
    r"(?P<verb>sacrifice|exile) "
    r"(?P<obj>it|that creature|that token|that permanent|that artifact|that vehicle|those tokens|the tokens?)"
    r"|(?P<verb_return>return) "
    r"(?P<obj_return>it|that creature|that token|that permanent) to "
    r"(?:your|its owner'?s) hand"
    r")"
    r"(?P<unless> unless ~ is your ring-bearer)?"
    # PAR-153 (Satya, Aetherflux Genius): "sacrifice that token unless you pay an amount of {E} equal to its mana value".
    r"(?P<unless_energy> unless you pay an amount of \{e\} equal to its mana value)?"
    r"(?:\.\s*(?:if|when) you do,\s*(?P<after>.+))?"
)

#: Object phrases that can only mean "the token(s) an earlier clause of this
#: same resolution *created*" (RULE 608.2) — never a RULE 115 target it also
#: chose. For these the delayed trigger must capture `GameContext.created_
#: objects` directly; "it"/"that creature"/"that permanent" stay on
#: `previous_or_self` (target first, then created, then the source).
_DELAYED_TAIL_TOKEN_SUBJECTS: frozenset[str] = frozenset(
    {"that token", "those tokens", "the token", "the tokens", "all tokens created this way"}
)


def _delayed_sac_exile_when_first(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    verb = (m.groupdict().get("verb") or m.groupdict().get("verb_return") or "").lower()
    inner = DELAYED_TAIL_INNER[verb]
    obj = (m.groupdict().get("obj") or m.groupdict().get("obj_return") or "").strip().lower()
    effects_list: list[dict] = [{"type": inner, "params": {}}]
    if m.groupdict().get("unless_energy"):
        if verb != "sacrifice":
            return None
        effects_list = [{"type": "sacrifice_unless_pay", "params": {"cost": "energy_equal_mana_value"}}]
    after = (m.groupdict().get("after") or "").strip()
    if after:
        # No `previous_subject`/`self_subject` here on purpose — see this
        # regex's own docstring on why a pronoun naming "it"/"that creature"
        # again can't be resolved through this recursive parse and must
        # fail closed instead of guessing.
        after_specs = parse_effect_body(after)
        if after_specs is None:
            return None  # fail closed — the "if you do" follow-up isn't modeled
        if any(s.params.get("target_kind") for s in after_specs):
            # A genuine RULE 115 target needs its own announced-target step
            # (same reasoning `_may_effect_then` rejects one for) — this
            # delayed trigger's effects resolve off-stack with no
            # target-gathering of their own.
            return None
        effects_list.extend(s.to_dict() for s in after_specs)
    params: dict = {
        "step": "end",
        "scope": "any",
        "capture": (
            "created_objects" if obj in _DELAYED_TAIL_TOKEN_SUBJECTS
            else "previous_or_self"
        ),
        "effects": effects_list,
    }
    if m.groupdict().get("unless"):
        # "…unless ~ is your Ring-bearer" — the delayed ability doesn't
        # trigger at all while ~ is the Ring-bearer (so the token stays).
        params["condition"] = {"is_ring_bearer": False}
    return [EffectSpec("create_delayed_trigger", params)]


#: ENG-30: "They [each] get +N/+N [and gain `<kw>`]/gain `<kw>` until end of
#: turn." (A-Bretagard Stronghold/Fancy Footwork-shaped, following "…1 or 2
#: target creatures…") — the pump-family sibling of `_UNTAP_PREVIOUS_GROUP_
#: RE` just above: "they" is the RULE 115 target *group* the preceding
#: clause chose (`PumpEffect.previous_subject`/`GameContext.
#: previous_targets`), not a mass selector — that's `_PUMP_PREVIOUS_
#: SELECTOR_RE`'s own, separately-gated (`previous_selector_only`) row,
#: which this can't collide with since `match_clause` only ever tries the
#: one whose gate the actual preceding clause satisfied. Two rows (P/T vs.
#: keyword-only) rather than one combined regex, mirroring `_pump`/`_pump_
#: keyword`'s own split for the ordinary targeted form.
#: "they"/"those creatures"/"each of those creatures" — all name the RULE
#: 115 target group the preceding clause chose (`GameContext.
#: previous_targets`); the wordier forms are what most real cards actually
#: print ("Arm the Cathars", "Cauldron Haze", …).
_PREV_GROUP_SUBJECT = r"(?:they|those creatures|each of those creatures)"
_PUMP_PREVIOUS_TARGETS_PT_RE = compile_clause(
    rf"{_PREV_GROUP_SUBJECT}(?: each)? gets? (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"
    r"(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)
_PUMP_PREVIOUS_TARGETS_KW_RE = compile_clause(
    rf"{_PREV_GROUP_SUBJECT}(?: each)? gains? (?P<kw>[a-z][a-z, ]*?) until end of turn"
)


def _pump_previous_targets_pt(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": signed_int(m.group("p")), "toughness": signed_int(m.group("t")),
        "previous_subject": True,
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


def _pump_previous_targets_kw(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    if m.groupdict().get("must_blocked"):
        keywords = [*keywords, "must_be_blocked"]
    return [EffectSpec("pump", {"keywords": keywords, "previous_subject": True})]
_PUMP_PREV_SINGULAR_PT_RE = compile_clause(
    rf"{PREV_SUBJECT_SINGULAR}(?: also)? gets? (?:an additional )?(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"
    r"(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)
_PUMP_PREV_SINGULAR_KW_RE = compile_clause(
    rf"{PREV_SUBJECT_SINGULAR}(?: also)? gains? (?P<kw>[a-z][a-z, ]*?) until end of turn"
    # PAR-124: "…and must be blocked this turn if able." (Magitek Scythe).
    rf"(?P<must_blocked> and must be blocked this turn if able)?"
)

#: Batch 4: the bare "It gains haste." / "That token gains haste." a token- or copy-making (or reanimating)
#: clause is followed by — no duration is printed, so the grant is what it says: indefinite (RULE 611.2c's
#: omitted-duration default, `rest_of_game`). Haste only: any other bare grant stays unclaimed.
_PUMP_PREV_HASTE_BARE_RE = compile_clause(rf"{PREV_SUBJECT_SINGULAR} gains haste")


def _pump_prev_haste_bare(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_until", {
        "static": {"type": "grant_keyword", "params": {"keywords": ["haste"]}},
        "duration": "rest_of_game", "previous_subject": True, "target_kind": None,
    })]


#: PAR-30 "Threaten / 'it gains haste' tails residue" — the *rich* leading-
#: "until end of turn, it …" restatement a threaten clause pairs with,
#: beyond a bare keyword grant (`segmenter._GAIN_CONTROL_HASTE_TAIL_RE`
#: recurses this whole sentence here with ``previous_subject`` on):
#:   * "…it gains haste and '<quoted ability>'" (Furnace Reins, Shackles of
#:     Treachery) — reuses `static_handlers._quoted_ability_grant_effects`
#:     wrapped in `grant_until(previous_subject=True)`;
#:   * "…it becomes a <subtype> in addition to its other types and gains
#:     haste" (Loki's Scepter) — a layer-4 `type_change` add-subtype grant;
#:   * "…it has base power and toughness N/N and gains <kws>" (Flayer of
#:     Loyalties) — a layer-7b `pt_set` grant + the residual keyword list.
#: The redundant "haste" is dropped (the `gain_control_until_eot` effect
#: already grants it as part of the control change).
_GAIN_CONTROL_RICH_PREV_GRANT_RE = compile_clause(
    r"until end of turn, (?:it|they) (?:"
    r"gains? haste and \"(?P<quoted>.+)\""
    r"|becomes? an? (?P<subtype>[a-z][a-z]+) in addition to its other types and gains? haste"
    r"|has base power and toughness (?P<bp>\d+)/(?P<bt>\d+) and gains? (?P<kw>[a-z0-9, ]+)"
    r")"
)


def _gain_control_rich_prev_grant(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("quoted"):

        grant = quoted_ability_grant_effects(m.group("quoted"))
        if grant is None:
            return None
        params = {k: v for k, v in grant.params.items() if k != "affects"}
        return [EffectSpec("grant_until", {
            "static": {"type": grant.type, "params": params},
            "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
        })]
    if m.group("subtype"):
        return [EffectSpec("grant_until", {
            "static": {"type": "type_change",
                       "params": {"add_subtypes": [m.group("subtype").capitalize()]}},
            "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
        })]
    split = split_keywords_with_parametric(m.group("kw"))
    if split is None:
        return None
    flags, parametric = split
    flags = [f for f in flags if f != "haste"]
    out: list[EffectSpec] = [EffectSpec("grant_until", {
        "static": {"type": "pt_set",
                   "params": {"power": int(m.group("bp")), "toughness": int(m.group("bt"))}},
        "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
    })]
    if flags or parametric:
        pump_params: dict = {"previous_subject": True}
        if flags:
            pump_params["keywords"] = flags
        if parametric:
            pump_params["parametric_keywords"] = parametric
        out.append(EffectSpec("pump", pump_params))
    return out


#: PAR-30 "Threaten … tails residue" — the two card-specific conditional
#: after-tails a threaten clause carries, each gated on the creature the
#: threaten just chose (`ConditionalEffect`'s `previous_target_*` keys,
#: reading `GameContext.previous_targets`):
#:   * "if that creature is a <subtype>, it also gets +N/+M until end of
#:     turn" (Goatnap — "if that creature is a Goat, it also gets +3/+0");
#:   * "if it's equipped, you may destroy all Equipment attached to that
#:     creature" (Awaken the Sleeper — the "you may" isn't offered as an
#:     interactive choice, see `_MASS_DESTROY_SELECTORS`).
_IF_PREV_SUBTYPE_PUMP_RE = compile_clause(
    r"if (?:that creature|it) is an? (?P<sub>[a-z][a-z-]+), "
    r"(?:it|that creature) (?:also )?gets (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+) until end of turn"
)


def _if_prev_subtype_pump(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "power": signed_int(m.group("p")), "toughness": signed_int(m.group("t")),
        "previous_subject": True,
    }, condition={"previous_target_has_subtype": m.group("sub")})]


_IF_PREV_EQUIPPED_DESTROY_RE = compile_clause(
    r"if (?:it'?s|that creature is) equipped, (?:you may )?destroy all equipment "
    r"attached to (?:it|that creature)"
)


def _if_prev_equipped_destroy(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("destroy", {
        "selector": "equipment_attached_to_previous",
    }, condition={"previous_target_is_equipped": True})]


#: MEC-28: "They gain first strike until end of turn." (Karlach, Fury of
#: Avernus's own trailing sentence, following "untap all attacking
#: creatures.") — the *mass-selector* sibling of the row above: "they" isn't
#: a RULE 115 targeted group at all (`_UNTAP_PREVIOUS_GROUP_RE`'s own
#: `previous_subject`/`GameContext.previous_targets` idiom), it's whichever
#: group the *previous clause's own selector* (RULE 601.2c, untargeted) just
#: acted on — `PumpEffect`'s new ``selector="previous_selector"`` sentinel,
#: resolved at apply time off the new `GameContext.previous_selector` field
#: `_apply_effects_partitioned` now tracks alongside `previous_targets`.
#: Only offered when the preceding split clause's own spec really used a
#: recognised group selector (`segmenter._announces_group_selector`,
#: `EffectHandler.previous_selector_only`) — never reused for
#: `previous_subject_only`'s existing meaning, a deliberately separate gate.
_PUMP_PREVIOUS_SELECTOR_RE = compile_clause(
    rf"{_PREV_GROUP_SUBJECT} gains? (?P<kw>[a-z, ]+?) until end of turn"
)


def _pump_previous_selector(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {"keywords": keywords, "selector": "previous_selector"})]


ROWS: list[EffectHandler] = [
    # "target <c1> or <c2> creature gets +N/+M / gains <kw> until end of
    # turn" (the Weaver cycle) — `TargetSpec.colors` OR narrowing; a
    # dedicated row since the shared `TARGET` macro has no colour slot.
    EffectHandler(
        "pump_target_two_color",
        _PUMP_TARGET_TWO_COLOR_RE,
        _pump_target_two_color,
    ),
    # "<subject> gets +x/+x [and gains <kw>] until end of turn" — the
    # {X}-cost-spell pump (Tyvar's Stand, Untamed Might). Tried before the
    # plain `pump` row below, whose `_PT_DELTA` only matches digits anyway.
    EffectHandler(
        "pump_x_nonland_permanents",
        _PUMP_X_NONLAND_PERMANENTS_RE,
        _pump_x_nonland_permanents,
    ),
    # "<subject> gets +x/+x …" / "<subject> gets -x/-x …" — same X-scaled
    # pump, either polarity. A backreference on `sign` (not a bare `[+\-−]`
    # each side) keeps a nonsensical "+x/-x" split unclaimed rather than
    # silently accepted — no real card mixes the sign within one X-pump.
    EffectHandler(
        "pump_x",
        compile_clause(
            rf"{SUBJECT} gets? (?P<sign>[+\-−])x/(?P=sign)x"
            rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump_x,
    ),
    # "<subject> gets +x/+0 [and gains <kw>] until end of turn" — the power-only X pump (Painiac's "…, where x is
    # the result" binds the X; PAR-147).
    EffectHandler(
        "pump_x_power_only",
        compile_clause(
            rf"{SUBJECT} gets? \+x/\+0"
            rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump_x_power_only,
    ),
    EffectHandler(
        "pump_subtype_target",
        _PUMP_SUBTYPE_TARGET_RE,
        _pump_subtype_target,
    ),
    EffectHandler(
        "grant_subtype_target",
        _GRANT_SUBTYPE_TARGET_RE,
        _grant_subtype_target,
    ),
    # "target creature gets +3/+3 until end of turn" / "gets -2/-2 …" /
    # "gets +1/+1 and gains trample until end of turn" / "~ gets +1/+0 …" /
    # "creatures you control get +2/+1 until end of turn" (plural "get").
    EffectHandler(
        "noncolor_creatures_pump",
        _NONCOLOR_CREATURES_PUMP_RE,
        _noncolor_creatures_pump,
    ),
    EffectHandler(
        "pump",
        compile_clause(
            rf"{SUBJECT} gets? {PT_DELTA}"
            rf"(?: and gains? (?P<kw>[a-z0-9, ]+?))? until end of turn"
            # PAR-124: "…and must be blocked this turn if able." (Compelled
            # Duel/Emergent Growth/Joraga Invocation).
            rf"(?P<must_blocked> and must be blocked this turn if able)?"
        ),
        pump_,
    ),
    # RULE 701.10/11 "double"/"triple the power and toughness of <target
    # creature[ you control]>/each creature you control until end of turn"
    # (Dragonclaw Strike/Roar of Endless Song).
    EffectHandler(
        "double_pt_of",
        compile_clause(
            rf"(?P<mult>double|triple) the {_DOUBLE_STAT} of "
            rf"(?:{TARGET}|(?P<each_group>each creature you control)) until end of turn"
        ),
        _double_pt_of,
    ),
    # The possessive phrasing — "double/triple <target creature>'s/~'s
    # power and toughness until end of turn" (Nylea's Colossus/Reckless
    # Amplimancer/Tifa's Limit Break's own "triple"), or just "power" (Bulk Up).
    EffectHandler(
        "double_pt_possessive",
        compile_clause(
            rf"(?P<mult>double|triple) (?:(?P<selfposs>~)|{TARGET})'s "
            rf"{_DOUBLE_STAT} until end of turn"
        ),
        _double_pt_possessive,
    ),
    # The bare pronoun — "double its power and toughness until end of
    # turn." Self-subject (Grunn's "whenever ~ attacks alone, double its
    # power and toughness"), the previous-clause pronoun (World War
    # Hulk's "choose target creature you control. … double its power and
    # toughness.") and the group trigger's firing creature (Death Kiss) are
    # genuinely different referents, so three rows.
    *subject_handlers([
        ("double_pt_self_pronoun", "self", _DOUBLE_PRONOUN_RE, _double_pt_pronoun),
        ("double_pt_previous", "previous", _DOUBLE_PRONOUN_RE, _double_pt_previous),
        ("double_pt_group_pronoun", "group", _DOUBLE_PRONOUN_RE, _double_pt_group),
        ("double_pt_attached_pronoun", "attached", _DOUBLE_PRONOUN_RE, _double_pt_attached),
    ]),
    # PAR-15: "any number of target creatures each get +N/+N [and gain
    # `<keyword>`] until end of turn" — every chosen creature gets the full
    # boost, not a divided pool.
    EffectHandler(
        "pump_multi_target",
        _PUMP_MULTI_TARGET_RE,
        _pump_multi_target,
    ),
    # "Untap those creatures." (Colossal Heroics) — the previous clause's own
    # multi-target group, read back the same way `return_previous_group` does.
    EffectHandler(
        "untap_previous_group",
        _UNTAP_PREVIOUS_GROUP_RE,
        _untap_previous_group,
        previous_subject_only=True,
    ),
    # "Those creatures don't untap …" after a mass selector (Clinging Mists).
    EffectHandler(
        "skip_untap_previous_selector",
        _SKIP_UNTAP_PREV_SELECTOR_RE,
        _skip_untap_prev_selector,
        previous_selector_only=True,
    ),
    # "Untap those creatures." after a mass selector (War Flare, PAR-128).
    EffectHandler(
        "tap_previous_selector",
        _TAP_PREVIOUS_SELECTOR_RE,
        _tap_previous_selector,
        previous_selector_only=True,
    ),
    # "…, then untap that land." (Avatar Kyoshi, following "earthbend N") —
    # the singular previous-subject sibling of the row just above.
    EffectHandler(
        "tap_previous_subject",
        _TAP_PREVIOUS_SUBJECT_RE,
        _tap_previous_subject,
        previous_subject_only=True,
    ),
    # "target/that/~ <permanent> doesn't untap during … next untap step"
    # (Barl's Cage + the ~95-card "Tap X. It doesn't untap …" family).
    EffectHandler("skip_next_untap_target", _SKIP_UNTAP_TARGET_RE, _skip_untap_target),
    EffectHandler(
        "skip_next_untap_prev", _SKIP_UNTAP_PREV_RE, _skip_untap_prev,
        previous_subject_only=True,
    ),
    # With no earlier clause to refer back to, "that land" is the object the firing
    # event names (Vorinclex's "whenever an opponent taps a land for mana, that land
    # doesn't untap …", PAR-119) — nothing outside a trigger.
    EffectHandler(
        "skip_next_untap_event_object",
        compile_clause(rf"that (?:land|permanent){_DONT_UNTAP_SUFFIX}"),
        lambda m: [EffectSpec("skip_next_untap", {"target_operand": {"of": "entering"}})],
    ),
    EffectHandler(
        "skip_next_untap_self", _SKIP_UNTAP_SELF_RE, _skip_untap_self,
        self_subject_only=True,
    ),
    # "Whenever ~ deals combat damage to a creature, tap that creature and
    # it doesn't untap …" (PAR-84 — Kashi-Tribe Reaver/Warriors).  The
    # DAMAGE recipient is neither a normal target nor the trigger source;
    # this tightly scoped row reads it from the firing event.
    EffectHandler(
        "tap_damage_recipient_and_skip_untap",
        _TAP_DAMAGE_RECIPIENT_AND_SKIP_UNTAP_RE,
        _tap_damage_recipient_and_skip_untap,
        self_subject_only=True,
    ),
    EffectHandler(
        "redirect_damage_to_self",
        _REDIRECT_DAMAGE_TO_SELF_RE,
        _redirect_damage_to_self,
    ),
    # "[TARGET / ~ / it] gains protection from the color of your choice
    # until end of turn" (RULE 702.16 — Gods Willing, Jareth, Feat of
    # Resistance &c.; the engine primitive is Mother of Runes').
    EffectHandler(
        "grant_prot_choice_target", _GRANT_PROT_CHOICE_TARGET_RE, _grant_prot_choice_target,
    ),
    EffectHandler(
        "grant_prot_choice_self", _GRANT_PROT_CHOICE_SELF_RE, _grant_prot_choice_self,
        self_subject_only=True,
    ),
    EffectHandler(
        "grant_prot_choice_prev", _GRANT_PROT_CHOICE_PREV_RE, _grant_prot_choice_prev,
        previous_subject_only=True,
    ),
    EffectHandler(
        "group_fixed_protection", _GROUP_FIXED_PROTECTION_RE, _group_fixed_protection,
    ),
    # "Reveal cards from the top of your library until you reveal a <type>
    # card. Put that card <onto the battlefield / into your hand> and the
    # rest <bottom / graveyard / shuffle>." (Recross the Paths, Clifftop
    # Lookout, Atla Palani, … — `RulesEngine.dig_until`).
    EffectHandler("reveal_until_type", _REVEAL_UNTIL_TYPE_RE, _reveal_until_type),
    EffectHandler(
        "dig_until_doctor_companion_vehicle",
        _DIG_UNTIL_DOCTOR_COMPANION_VEHICLE_RE,
        _dig_until_doctor_companion_vehicle,
    ),
    EffectHandler(
        "damage_each_opponent_full_party",
        _DAMAGE_EACH_OPPONENT_FULL_PARTY_RE,
        _damage_each_opponent_full_party,
    ),
    EffectHandler(
        "add_counter_target_full_party",
        _ADD_COUNTER_TARGET_FULL_PARTY_RE,
        _add_counter_target_full_party,
    ),
    # PAR-30: "[Then] sacrifice/exile <it/that creature/that token/them/
    # those tokens> at the beginning of [the/your] next end step." — the
    # RULE 603.7 delayed-trigger tail on every "create a token …, exile it"
    # / "reanimate …, sacrifice it" card (~100 SOLO). Ungated: `capture=
    # "previous_or_self"` resolves the referent (prev target → created
    # object → the source) at arm time and no-ops on an empty chain.
    EffectHandler(
        "delayed_sac_exile_tail",
        DELAYED_SAC_EXILE_TAIL_RE,
        _delayed_sac_exile_tail,
    ),
    # The when-first sibling — "At the beginning of the next end step,
    # sacrifice/exile <it>[ unless ~ is your Ring-bearer]." (MEC-52).
    EffectHandler(
        "exile_instead_of_leaving", _EXILE_INSTEAD_OF_LEAVING_RE, _exile_instead_of_leaving,
        previous_subject_only=True,
    ),
    EffectHandler(
        "owner_shuffles_graveyard", _OWNER_SHUFFLES_GRAVEYARD_RE, _owner_shuffles_graveyard,
        self_subject_only=True,
    ),
    EffectHandler(
        "delayed_return_battlefield_previous", _DELAYED_RETURN_BATTLEFIELD_RE,
        _delayed_return_battlefield, previous_subject_only=True,
    ),
    EffectHandler(
        "delayed_return_battlefield_self", _DELAYED_RETURN_BATTLEFIELD_RE,
        _delayed_return_battlefield, self_subject_only=True,
    ),
    EffectHandler(
        "delayed_sac_exile_when_first",
        _DELAYED_SAC_EXILE_WHEN_FIRST_RE,
        _delayed_sac_exile_when_first,
    ),
    # ENG-30: "They [each] get +N/+N [and gain <kw>] until end of turn."
    # (A-Bretagard Stronghold/Fancy Footwork) — the pump-family sibling of
    # `untap_previous_group`, same previous-target-group gate.
    EffectHandler(
        "pump_previous_targets_pt",
        _PUMP_PREVIOUS_TARGETS_PT_RE,
        _pump_previous_targets_pt,
        previous_subject_only=True,
    ),
    # ENG-30: "They [each] gain <kw> until end of turn." — the keyword-only
    # sibling of the row above (tried after it since a P/T delta present
    # would otherwise be swallowed by this row's own bare-keyword capture).
    EffectHandler(
        "pump_previous_targets_kw",
        _PUMP_PREVIOUS_TARGETS_KW_RE,
        _pump_previous_targets_kw,
        previous_subject_only=True,
    ),
    # PAR-30 "Threaten … tails residue" — the *rich* leading-"until end of
    # turn, it …" restatement (quoted ability / becomes-subtype / base P/T),
    # tried before the plain pronoun-pump rows so its longer shape wins.
    EffectHandler(
        "gain_control_rich_prev_grant",
        _GAIN_CONTROL_RICH_PREV_GRANT_RE,
        _gain_control_rich_prev_grant,
        previous_subject_only=True,
    ),
    # PAR-30 "Threaten … tails residue" — card-specific conditional
    # after-tails gated on the just-controlled creature (Goatnap "if that
    # creature is a Goat …", Awaken the Sleeper "if it's equipped …").
    EffectHandler(
        "if_prev_subtype_pump",
        _IF_PREV_SUBTYPE_PUMP_RE,
        _if_prev_subtype_pump,
        previous_subject_only=True,
    ),
    EffectHandler(
        "if_prev_equipped_destroy",
        _IF_PREV_EQUIPPED_DESTROY_RE,
        _if_prev_equipped_destroy,
        previous_subject_only=True,
    ),
    # PAR-30: the singular-pronoun siblings — "it [also] gets +N/+N …" /
    # "it [also] gains <kw> until end of turn" (threaten restatement tails,
    # clash "if you win, that creature …" payoffs). P/T row first so a
    # delta isn't swallowed by the keyword row's bare capture.
    EffectHandler(
        "pump_prev_singular_pt",
        _PUMP_PREV_SINGULAR_PT_RE,
        _pump_previous_targets_pt,
        previous_subject_only=True,
    ),
    EffectHandler(
        "pump_prev_singular_kw",
        _PUMP_PREV_SINGULAR_KW_RE,
        _pump_previous_targets_kw,
        previous_subject_only=True,
    ),
    EffectHandler(
        "pump_prev_haste_bare", _PUMP_PREV_HASTE_BARE_RE, _pump_prev_haste_bare, previous_subject_only=True,
    ),
    # "They gain first strike until end of turn." (Karlach, Fury of
    # Avernus, MEC-28) — the mass-selector sibling: only offered when the
    # preceding clause's own spec used a real group selector.
    EffectHandler(
        "pump_previous_selector",
        _PUMP_PREVIOUS_SELECTOR_RE,
        _pump_previous_selector,
        previous_selector_only=True,
    ),
    # "Target attacking Elf you control gains deathtouch until end of
    # turn." (Gnarlroot Trapper-shaped) — tried before the plain
    # `pump_keyword` row below since the shared `TARGET` macro has no
    # "attacking `<subtype>` you control" row for that one to match.
    EffectHandler(
        "pump_attacking_subtype_target",
        _PUMP_ATTACKING_SUBTYPE_TARGET_RE,
        _pump_attacking_subtype_target,
    ),
    EffectHandler(
        "pump_other_attacking_creature",
        _PUMP_OTHER_ATTACKING_CREATURE_RE,
        _pump_other_attacking_creature,
    ),
    # MEC-105 / RULE 613.1f: temporary ability removal. Compound rows come
    # first and remain one effect, so "gains flying and loses trample" (or a
    # P/T change plus a loss) shares one recipient and one duration.
    EffectHandler(
        "pump_and_lose_keyword",
        compile_clause(
            rf"{SUBJECT} gets? {PT_DELTA} and loses? "
            r"(?P<lost>[a-z, ]+?) until end of turn"
        ),
        temporary_keyword_change,
    ),
    EffectHandler(
        "gain_and_lose_keyword",
        compile_clause(
            rf"{SUBJECT} gains? (?P<kw>[a-z, ]+?) and loses? "
            r"(?P<lost>[a-z, ]+?) until end of turn"
        ),
        temporary_keyword_change,
    ),
    EffectHandler(
        "lose_and_gain_keyword",
        compile_clause(
            rf"{SUBJECT} loses? (?P<lost>[a-z, ]+?) and gains? "
            r"(?P<kw>[a-z, ]+?) until end of turn"
        ),
        temporary_keyword_change,
    ),
    EffectHandler(
        "lose_keyword_until_eot",
        compile_clause(rf"{SUBJECT} loses? (?P<lost>[a-z, ]+?) until end of turn"),
        temporary_keyword_change,
    ),
]
