"""One-shot damage prevention and redirection rows (PAR-216).

The resolve-time siblings of `catalogue.prevention_statics`: "prevent all combat damage that would be dealt to and
dealt by that creature this turn", "prevent all damage target creature would deal this turn", "prevent all damage a
source of your choice would deal this turn", "the next N damage that would be dealt to `<X>` this turn is dealt to
`<Y>` instead" and the damage riders ("excess damage is dealt to that creature's controller instead", "the damage can't
be prevented"). Every row reuses an existing engine shield (`PreventDamageEffect`, `PreventDamageFromTargetEffect`,
`RequestPreventDamageSourceEffect`) or the one-shot redirect `RedirectDamageShieldEffect` (RULE 615, 616.1); a phrase the
slots do not fully parse stays unclaimed.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..characteristic_phrase import parse_object_phrase
from .....models.cards.creature_types import CREATURE_SUBTYPES
from ..clause_hooks import match_clause
from ..clause_reading import ClauseReading
from ..subgrammars import (
    resolve_spell_filter,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    target_kind_allowed,
)
from ...spec import EffectSpec
from .damage_copy import parse_prevent_source_filter
from .shared import (
    MULTI_TARGET_ALT, MULTI_TARGET_QUANTIFIER, MULTI_TARGET_QUANTIFIER_X, EffectHandler,
    compile_clause, multi_target_params,
)

#: A pronoun naming the creature an earlier clause chose, or this ability's own source (RULE 608.2h).
_PRONOUNS = "it|that creature|the creature"
_HOSTS = "~|this creature|this permanent"

#: Target kinds a creature-side shield may name ("target creature", "target creature you control", "target attacking or
#: blocking creature"); the spell kind is the "target spell" sibling (RULE 608.2b: the spell is the damage's source).
_DEALER_KINDS = ("creature", "creature_you_control", "creature_you_dont_control", "attacking_or_blocking_creature")
_TARGET_WORDS = r"(?:target|up to one target) [a-z ]+?"
#: What a gain-life tally rider reads: "You gain life equal to the damage prevented this way." (Hallow).
_LIFE_TALLY = r"(?:\.\s+(?P<life>you gain life equal to the damage prevented this way))?"
_LIFE_RIDER: dict[str, str] = {"kind": "gain_life", "recipient": "you"}

# --- "prevent all combat damage that would be dealt to and dealt by <X> this turn" -------------------------------------

#: Maze of Ith / Fog Bank / Deftblade Elite: the recipient shield plus the same creature's own combat damage. A pronoun
#: row is offered only under the reading that gives it a referent (`EffectHandler.requires`).
_TO_AND_BY_TARGET_RE = compile_clause(
    rf"prevent all combat damage that would be dealt to and dealt by (?P<target>{_TARGET_WORDS}) this turn"
)
_TO_AND_BY_SELF_RE = compile_clause(
    rf"prevent all combat damage that would be dealt to and dealt by (?:{_HOSTS}) this turn"
)
_TO_AND_BY_PREVIOUS_RE = compile_clause(
    rf"prevent all combat damage that would be dealt to and dealt by (?:{_PRONOUNS}) this turn"
)
_TO_AND_BY_BASE: dict[str, Any] = {"amount": "all", "combat_only": True, "and_dealt_by": True}


def _to_and_by_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    text = m.group("target").strip()
    kind = resolve_target_kind(text)
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    params: dict[str, Any] = {**_TO_AND_BY_BASE, "target_kind": kind}
    if text.startswith("up to one "):
        params["optional"] = True
    state_filter = resolve_target_creature_state_filter(text)
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("prevent_damage_shield", params)]


def _to_and_by_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_damage_shield", {**_TO_AND_BY_BASE, "self_only": True})]


def _to_and_by_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_damage_shield", {**_TO_AND_BY_BASE, "previous_subject": True})]


# --- "prevent all damage <creature or spell> would deal this turn" ------------------------------------------------------

#: Chain of Silence / Inquisitor's Snare / Kry Shield / Hidden Retreat / Hallow: every point of damage the chosen source
#: would deal for the rest of the turn (`RulesEngine.prevent_damage_from_source`, "all" keeps the shield for the turn).
_PREVENT_DEALT_BY_TARGET_RE = compile_clause(
    r"prevent all damage (?:that would be dealt (?:this turn )?by (?P<by>target [a-z ]+?)(?: this turn)?"
    r"|(?P<dealer>target [a-z ]+?) would deal this turn)"
    + _LIFE_TALLY
)


def _prevent_dealt_by_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    text = (m.group("by") or m.group("dealer")).strip()
    params: dict[str, Any] = {}
    if text.endswith(" spell"):
        spell = resolve_spell_filter(text)
        if spell is None:
            return None
        params["target_kind"] = spell.pop("target_kind", "spell")
        if spell:
            params["spell_filter"] = spell
    else:
        kind = resolve_target_kind(text)
        if not target_kind_allowed(kind, _DEALER_KINDS) or resolve_target_creature_state_filter(text):
            return None
        params["target_kind"] = kind
    if m.group("life"):
        params["rider"] = dict(_LIFE_RIDER)
    return [EffectSpec("prevent_damage_from_target", params)]


# --- "prevent all [combat] damage that would be dealt this turn by <sources>" -----------------------------------------

#: Fog of War / Obscuring Haze / Snag / Tanglesap / Hunter's Ambush / Luminesce / Haze Frog: a recipient-less shield on a
#: class of damage sources (`RulesEngine._prevent_damage_by_sources`). The source slot is the shared object phrase, a
#: union of phrases ("black sources and red sources"), "unblocked creatures" or "other <phrase>" (everything but this
#: ability's own permanent); anything else stays unclaimed.
_UNION_SPLIT_RE = re.compile(r" and/or | and | or ")
_SOURCES_BY_RE = compile_clause(
    r"prevent all (?P<combat>combat )?damage that would be dealt (?:this turn )?by "
    r"(?P<src>[a-z][a-z0-9 '/+,-]*?)(?: this turn)?"
)
_SOURCES_WOULD_DEAL_RE = compile_clause(
    r"prevent all (?P<combat>combat )?damage (?:that )?(?P<src>[a-z][a-z0-9 '/+,-]*?) would deal this turn"
)


def _dealers_filter(text: str) -> Optional[dict[str, Any]]:
    """A damage-source phrase -> `_damage_source_matches`'s ``source_filter``, or ``None`` (fail-closed)."""
    text = text.strip()
    other = text.startswith("other ")
    if other:
        text = text[len("other "):]
    if text.startswith(("target ", "a ", "an ", "each ", "that ", "this ")) or text in ("it", "them"):
        return None  # a chosen or referenced source, not a class
    if text == "unblocked creatures":
        result: Optional[dict[str, Any]] = {"creature": True, "unblocked": True}
    else:
        result = parse_prevent_source_filter(text)
        if result is None:
            parts = _UNION_SPLIT_RE.split(text)
            parsed = [parse_object_phrase(part.strip(), plural=True) for part in parts]
            if len(parts) > 1 and all(p is not None and p[1] is None for p in parsed):
                result = {"object_filter": {"any_of": [p[0] for p in parsed if p is not None]}}
    if result is None:
        return None
    return {**result, "other": True} if other else result


#: Encircling Fissure: "... by creatures target opponent controls" -- the class (the shared object phrase) scoped to one
#: announced player (RULE 109.4, 115.1): the class filter plus ``controller: "target"``, resolved to that player's id when
#: the shield is made (`PreventDamageEffect`).
_TARGET_PLAYER_SCOPE_RE = re.compile(r"^(?P<cls>.+?) target (?P<who>opponent|player) controls$")
_TARGET_PLAYER_KINDS: dict[str, str] = {"opponent": "opponent", "player": "player"}


def _prevent_by_sources(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    text = m.group("src")
    scoped = _TARGET_PLAYER_SCOPE_RE.match(text.strip())
    source_filter = _dealers_filter(scoped.group("cls") if scoped else text)
    if source_filter is None:
        return None
    params: dict[str, Any] = {"amount": "all", "by_sources_only": True, "source_filter": source_filter}
    if scoped:
        if "other" in source_filter or "controller" in source_filter:
            return None
        params["source_filter"] = {**source_filter, "controller": "target"}
        params["target_kind"] = _TARGET_PLAYER_KINDS[scoped.group("who")]
    if m.group("combat"):
        params["combat_only"] = True
    return [EffectSpec("prevent_damage_shield", params)]


# --- multi-target shields: "prevent all damage that would be dealt this turn to up to two target creatures" ---------------

#: Redeem: the recipient shield of `_prevent_to_creatures`' sibling over N announced targets (RULE 115.1d), one
#: `prevent_damage_to_target` shield each (`PreventDamageEffect` loops its chosen targets).
_PREVENT_TO_MULTI_RE = compile_clause(
    rf"prevent all damage that would be dealt (?:this turn )?to {MULTI_TARGET_QUANTIFIER}(?P<target>{MULTI_TARGET_ALT})"
    r"(?: this turn)?"
)
#: Soul Parry / Serene Sunset: the by-source mirror -- "prevent all [combat] damage <N target creatures> would deal this
#: turn" (`PreventDamageFromTargetEffect` shields each chosen source). "X target creatures" is the announced X.
_PREVENT_BY_MULTI_RE = compile_clause(
    rf"prevent all (?P<combat>combat )?damage {MULTI_TARGET_QUANTIFIER_X}(?P<target>{MULTI_TARGET_ALT}) would deal this turn"
)
_MULTI_SHIELD_KINDS = ("creature", "creature_you_control", "creature_you_dont_control")


def _prevent_to_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = multi_target_params(m)
    if params is None or not target_kind_allowed(params["target_kind"], _MULTI_SHIELD_KINDS):
        return None
    return [EffectSpec("prevent_damage_shield", {"amount": "all", **params})]


def _prevent_by_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = multi_target_params(m)
    if params is None or not target_kind_allowed(params["target_kind"], _MULTI_SHIELD_KINDS):
        return None
    if m.group("combat"):
        params["combat_only"] = True
    return [EffectSpec("prevent_damage_from_target", params)]


# --- "prevent all [combat|noncombat] damage that would be dealt to <recipients> this turn" -----------------------------

#: Divine Light / Sivvi's Ruse / Pack Leader: a board-wide creature-recipient shield (`RulesEngine.
#: _prevent_damage_to_creatures`). The recipient slot is the shared object phrase restricted to creatures (a card type of
#: creature, or a creature subtype) controlled by you or by anyone; "combat"/"noncombat" is the event's own flag.
_COMBAT_FLAG: dict[str, bool] = {"combat ": True, "noncombat ": False}
_TO_CREATURES_RE = compile_clause(
    r"prevent all (?P<combat>combat |noncombat )?damage that would be dealt (?:this turn )?to "
    r"(?P<rec>[a-z][a-z0-9 '/+-]*?)(?: this turn)?"
)


def _is_creature_class(filt: dict[str, Any]) -> bool:
    return filt.get("card_type") == "creature" or str(filt.get("subtype", "")).lower() in CREATURE_SUBTYPES


def _prevent_to_creatures(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    parsed = parse_object_phrase(m.group("rec").strip(), plural=True)
    if parsed is None or parsed[1] not in (None, "you") or not _is_creature_class(parsed[0]):
        return None
    params: dict[str, Any] = {
        "amount": "all", "recipient_creatures_scope": "you_control" if parsed[1] == "you" else "all",
        "recipient_filter": {"object_filter": parsed[0]},
    }
    if m.group("combat"):
        params["source_filter"] = {"combat": _COMBAT_FLAG[m.group("combat").lower()]}
    return [EffectSpec("prevent_damage_shield", params)]


#: Druid's Deliverance / Blessed Sanctuary's spell siblings: the controller (and, for the union, the permanents of one class
#: they control) as the recipient of a combat or noncombat shield. A bare "you" with no qualifier is the older row's.
_TO_YOU_RE = compile_clause(
    r"prevent all (?P<combat>combat |noncombat )damage that would be dealt to you"
    r"(?: and (?P<scope>creatures|permanents|planeswalkers) you control)? this turn"
)


def _prevent_to_you(m: re.Match[str]) -> list[EffectSpec]:
    params: dict[str, Any] = {"amount": "all", "source_filter": {"combat": _COMBAT_FLAG[m.group("combat").lower()]}}
    if m.group("scope"):
        params["recipient_scope"] = m.group("scope").lower()
    return [EffectSpec("prevent_damage_shield", params)]


#: Decorated Griffin: "prevent the next N combat damage that would be dealt to you this turn".
_NEXT_COMBAT_TO_YOU_RE = compile_clause(
    r"prevent the next (?P<n>\d+) combat damage that would be dealt to you this turn"
)


def _next_combat_to_you(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_damage_shield", {"amount": int(m.group("n")), "source_filter": {"combat": True}})]


#: Noble Vestige / Wandering Mage: a budgeted shield for one chosen player or planeswalker.
_NEXT_TO_PLAYER_OR_PLANESWALKER_RE = compile_clause(
    r"prevent the next (?P<n>\d+) damage that would be dealt to target player or planeswalker this turn"
)


def _next_to_player_or_planeswalker(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_damage_shield", {"amount": int(m.group("n")), "target_kind": "player_or_planeswalker"})]


#: Telekinesis: "Tap target creature. Prevent all combat damage that would be dealt by that creature this turn." -- the
#: creature the earlier clause chose (`PreventCombatDamageDealtEffect` reads it as the previous target).
_COMBAT_DEALT_BY_PREVIOUS_RE = compile_clause(
    rf"prevent all combat damage that would be dealt by (?:{_PRONOUNS}) this turn"
)


def _combat_dealt_by_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_combat_damage_dealt", {"subject": "previous_target"})]


# --- "prevent all damage a source of your choice would deal [to you] this turn" ---------------------------------------

#: Pay No Heed / Rith's Charm / Prahv / Auriok Replica / Burrenton Forge-Tender: the chooser
#: (`RequestPreventDamageSourceEffect`) over every battlefield permanent matching the named quality, shielding the
#: whole turn ("all" keeps the shield) -- recipient ``any`` when the clause names none, the caster for "to you".
_CHOSEN_SOURCE_COLORS: dict[str, str] = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
_PREVENT_CHOSEN_SOURCE_RE = compile_clause(
    r"prevent all damage an? (?:(?P<color>white|blue|black|red|green) )?source of your choice would deal"
    r"(?P<to_you> to you)? this turn"
)


def _prevent_chosen_source(m: re.Match[str]) -> list[EffectSpec]:
    params: dict[str, Any] = {"amount": "all"}
    if not m.group("to_you"):
        params["recipient"] = "any"
    if m.group("color"):
        params["source_filter"] = {"color": _CHOSEN_SOURCE_COLORS[m.group("color").lower()]}
    return [EffectSpec("request_prevent_damage_source", params)]


#: Healing Grace: a budgeted shield for one chosen recipient against one chosen source.
_PREVENT_NEXT_CHOSEN_SOURCE_RE = compile_clause(
    r"prevent the next (?P<n>\d+) damage that would be dealt to any target this turn by a source of your choice"
)


def _prevent_next_chosen_source(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("request_prevent_damage_source", {"amount": int(m.group("n")), "target_kind": "any"})]


# --- "the next time a source of your choice would deal damage to you this turn, ..." ---------------------------------------

#: RULE 615/616.1: the one-shot ("next time") chosen-source shield -- unlike "prevent all damage a source of your choice
#: would deal", it ends after the first matching hit. Dark Sphere (prevent half, rounded down), the plain "prevent that
#: damage", Beacon of Destiny / General's Regalia (that damage is dealt to ~ / target creature you control instead).
_NEXT_TIME_SOURCE = (
    r"the next time an? (?:(?P<color>white|blue|black|red|green) )?source of your choice would deal damage to you this turn, "
)
_NEXT_TIME_PREVENT_RE = compile_clause(
    _NEXT_TIME_SOURCE + r"prevent (?:that damage|half that damage, rounded (?P<half>up|down))"
)
_NEXT_TIME_REDIRECT_RE = compile_clause(
    _NEXT_TIME_SOURCE + rf"that damage is dealt to (?P<rec>{_HOSTS}|target creature you control|target creature) instead"
)


def _next_time_prevent(m: re.Match[str]) -> list[EffectSpec]:
    params: dict[str, Any] = {"amount": {"half": m.group("half")} if m.group("half") else "all", "once": True}
    if m.group("color"):
        params["source_filter"] = {"color": _CHOSEN_SOURCE_COLORS[m.group("color").lower()]}
    return [EffectSpec("request_prevent_damage_source", params)]


def _next_time_redirect(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict[str, Any] = {"once": True, "only_to_you": True}
    recipient = m.group("rec")
    if recipient.startswith("target"):
        kind = resolve_target_kind(recipient)
        if not target_kind_allowed(kind, ("creature", "creature_you_control")):
            return None
        params.update(recipient="target", target_kind=kind)
    if m.group("color"):
        params["source_filter"] = {"color": _CHOSEN_SOURCE_COLORS[m.group("color").lower()]}
    return [EffectSpec("request_redirect_damage_source", params)]


#: Kor Chant / Oracle's Attendants: "all damage that would be dealt [this turn] to target creature [you control] [this
#: turn] by a source of your choice is dealt to ~ / another target creature instead" -- lasts the turn (no "next time"),
#: for one chosen source and one announced creature.
_ALL_FROM_CHOSEN_SOURCE_REDIRECT_RE = compile_clause(
    r"all damage that would be dealt (?:this turn )?to (?P<prot>target creature(?: you control)?)(?: this turn)? "
    rf"by a source of your choice is dealt to (?P<rec>{_HOSTS}|another target creature) instead"
)


def _all_from_chosen_source_redirect(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    protected = resolve_target_kind(m.group("prot"))
    if not target_kind_allowed(protected, ("creature", "creature_you_control")):
        return None
    params: dict[str, Any] = {"protected_target_kind": protected}
    if m.group("rec").startswith("another"):
        params.update(recipient="target", target_kind="creature")
    return [EffectSpec("request_redirect_damage_source", params)]


# --- a shield followed by a rider keyed on the damage it prevented --------------------------------------------------------

#: Comeuppance: "If damage from a creature source is prevented this way, ~ deals that much damage to that creature. If
#: damage from a noncreature source is prevented this way, ~ deals that much damage to the source's controller." -- two
#: riders gated on the type of the prevented source (`RulesEngine.apply_prevent_rider`).
_SHIELD_THEN_SOURCE_PUNISH_RE = compile_clause(
    r"(?P<shield>prevent all damage that would be dealt to [^.]+?)\.\s+"
    r"if damage from a creature source is prevented this way, ~ deals that much damage to that creature\.\s+"
    r"if damage from a noncreature source is prevented this way, ~ deals that much damage to the source'?s controller"
)
_SOURCE_PUNISH_RIDER: list[dict[str, Any]] = [
    {"kind": "shield_deals_damage", "to": "source", "if_source_creature": True},
    {"kind": "shield_deals_damage", "to": "source_controller", "if_source_creature": False},
]

COUNTER = r"[+\-]\d+/[+\-]\d+"
#: Brace for Impact ("all"), Sacred Boon ("at the beginning of the next end step ..."), Scars of the Veteran ("if it's a
#: creature ... at the beginning of the next end step"): +N/+N counters on the shielded creature, one per point actually
#: prevented, immediately or in a delayed trigger sized now (RULE 603.7). The immediate "the next N" form is the older
#: `prevent_shield_then_rider` row's.
_SHIELD_THEN_COUNTERS_RE = compile_clause(
    r"(?P<shield>prevent (?:the next (?:\d+|x)|all) damage that would be dealt to [^.]+? this turn)\.\s+"
    rf"(?:for each 1 damage prevented this way, put an? (?P<now>{COUNTER}) counter on that creature"
    rf"|at the beginning of the next end step, put an? (?P<end>{COUNTER}) counter on that creature "
    r"for each 1 damage prevented this way"
    rf"|if it'?s a creature, put an? (?P<end_if>{COUNTER}) counter on it for each 1 damage prevented this way "
    r"at the beginning of the next end step)"
)


def _shield_then_source_punish(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    shield = match_clause(m.group("shield"))
    if shield is None or len(shield) != 1 or shield[0].type != "prevent_damage_shield" or "rider" in shield[0].params:
        return None
    return [EffectSpec("prevent_damage_shield", {**shield[0].params, "rider": [dict(r) for r in _SOURCE_PUNISH_RIDER]})]


def _shield_then_counters(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    shield = match_clause(m.group("shield"))
    if shield is None or len(shield) != 1 or shield[0].type != "prevent_damage_shield" or "rider" in shield[0].params:
        return None
    kind = shield[0].params.get("target_kind")
    counter = m.group("now") or m.group("end") or m.group("end_if")
    # "that creature" needs a creature-only target; "if it's a creature" is the any-target form (Scars of the Veteran).
    if kind != ("any" if m.group("end_if") else "creature"):
        return None
    rider: dict[str, Any] = {"kind": "add_scaled_counters", "on": "recipient", "counter": counter}
    if not m.group("now"):
        rider["delayed"] = "next_end_step"
    return [EffectSpec("prevent_damage_shield", {**shield[0].params, "rider": rider})]


# --- damage riders: excess damage, "the damage can't be prevented" ------------------------------------------------------

#: Flame Spill / Pigment Storm: "~ deals N damage to target creature. Excess damage is dealt to that creature's
#: controller instead." (RULE 120.4a lethal damage, RULE 614.1 the replacement).
_DAMAGE_THEN_EXCESS_RE = compile_clause(
    r"(?P<damage>[^.]+?)\.\s+excess damage is dealt to that creature'?s controller instead"
)


def _damage_then_excess(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    damage = match_clause(m.group("damage"))
    if damage is None or len(damage) != 1 or damage[0].type != "damage":
        return None
    params = damage[0].params
    if params.get("target_kind") != "creature" or {"selector", "divided", "excess_to_controller"} & set(params):
        return None
    return [EffectSpec("damage", {**params, "excess_to_controller": True})]


#: "~ deals N damage to target X. The damage can't be prevented." (Pinpoint Avalanche; RULE 615.12).
_DAMAGE_THEN_UNPREVENTABLE_RE = compile_clause(
    r"(?P<damage>[^.]+?)\.\s+(?:the|that) damage can'?t be prevented"
)


def _damage_then_unpreventable(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    damage = match_clause(m.group("damage"))
    if damage is None or len(damage) != 1 or damage[0].type != "damage" or damage[0].params.get("unpreventable"):
        return None
    return [EffectSpec("damage", {**damage[0].params, "unpreventable": True})]


# --- "the next N damage that would be dealt to <X> this turn is dealt to <Y> instead" -----------------------------------

#: One redirect grammar for the one-shot family. The protected slot (what the damage is headed for) and the recipient slot
#: (where it goes instead) each name a host, "you" or one RULE 115 target; at most one of the two is a target
#: (`RedirectDamageShieldEffect`).
#: A slot's text runs to the next clause comma, except inside the one printed union "creature, planeswalker, or player".
_REDIRECT_SLOT_TEXT = r"(?:[^,]|, planeswalker, or player)+?"
_REDIRECT_SHIELD_RE = compile_clause(
    r"(?:the next (?P<n>\d+|x) damage|all (?P<combat>combat )?damage) that would be dealt "
    rf"(?:this turn )?to (?P<prot>{_REDIRECT_SLOT_TEXT})(?: this turn)?(?P<unblocked> by unblocked creatures)?(?: this turn)? "
    rf"is dealt to (?P<rec>{_REDIRECT_SLOT_TEXT}) instead"
)
_REDIRECT_ONCE_RE = compile_clause(
    r"the next time damage would be dealt to (?P<prot>[^,]+?) this turn, that damage is dealt to (?P<rec>[^,]+?) instead"
)
_REDIRECT_PROTECTED: dict[str, str] = {
    "~": "self", "this creature": "self", "you": "you", "you and permanents you control": "you_and_permanents",
    "~ and/or you": "you_and_self", "you and/or ~": "you_and_self", "enchanted creature": "attached",
}
_REDIRECT_RECIPIENT: dict[str, str] = {"~": "self", "this creature": "self", "you": "you", "enchanted creature": "attached"}
_REDIRECT_TARGET_KINDS = (
    "any", "creature", "creature_you_control", "player", "planeswalker", "permanent", "creature_planeswalker_or_player",
)
#: Captain's Maneuver: "target creature, planeswalker, or player" -- "any target" minus battles (RULE 115.4); only this
#: slot reads it, so no other clause's target pool changes.
_CREATURE_PLANESWALKER_OR_PLAYER_RE = re.compile(r"^(?:another )?target creature, planeswalker, or player$")


def _redirect_slot(text: str, table: dict[str, str]) -> Optional[tuple[str, dict[str, Any]]]:
    """A protected/recipient phrase -> (role word, target params), or ``None`` when it parses to nothing."""
    text = text.strip()
    if text in table:
        return table[text], {}
    if _CREATURE_PLANESWALKER_OR_PLAYER_RE.match(text):
        return "target", {"target_kind": "creature_planeswalker_or_player"}
    if text not in ("any target", "another target creature") and not text.startswith("target "):
        return None
    kind = resolve_target_kind(text.replace("another ", "", 1) if text.startswith("another ") else text)
    if not target_kind_allowed(kind, _REDIRECT_TARGET_KINDS):
        return None
    params: dict[str, Any] = {"target_kind": kind}
    state_filter = resolve_target_creature_state_filter(text)
    if state_filter:
        params["creature_filter"] = state_filter
    return "target", params


def _redirect_spec(
    prot: str, rec: str, *, amount: Any, once: bool, combat: bool, unblocked: bool, pronoun_self: bool = False,
) -> Optional[list[EffectSpec]]:
    """``pronoun_self``: "it" names this ability's own source (the caller's reading says so), else it names nothing."""
    protected = _redirect_slot("~" if pronoun_self and prot == "it" else prot, _REDIRECT_PROTECTED)
    recipient = _redirect_slot(rec, _REDIRECT_RECIPIENT)
    if protected is None or recipient is None:
        return None
    if protected[0] == "target" and unblocked:
        return None
    params: dict[str, Any] = {"amount": amount, "protected": protected[0], "recipient": recipient[0], **protected[1]}
    if protected[0] == "target" and recipient[0] == "target":
        # Carom / Razia: "... to target creature ... is dealt to another target creature instead" -- two announced
        # targets (RULE 115.1); "another" is what makes them different objects (RULE 115.3), so it is required.
        if not rec.strip().startswith("another "):
            return None
        params["recipient_target_kind"] = recipient[1]["target_kind"]
    else:
        params.update(recipient[1])
    if once:
        params["once"] = True
    if combat:
        params["combat_only"] = True
    if unblocked:
        params["source_filter"] = {"unblocked": True}
    return [EffectSpec("redirect_damage_shield", params)]


def _redirect_shield(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    n = m.group("n")
    amount: Any = "all" if n is None else ("x" if n.lower() == "x" else int(n))
    return _redirect_spec(
        m.group("prot"), m.group("rec"), amount=amount, once=False, combat=bool(m.group("combat")),
        unblocked=bool(m.group("unblocked")), pronoun_self=reading.self_subject,
    )


def _redirect_once(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    return _redirect_spec(
        m.group("prot"), m.group("rec"), amount="all", once=True, combat=False, unblocked=False,
        pronoun_self=reading.self_subject,
    )


ROWS: list[EffectHandler] = [
    EffectHandler("prevent_combat_damage_to_and_by_target", _TO_AND_BY_TARGET_RE, _to_and_by_target),
    EffectHandler("prevent_combat_damage_to_and_by_self", _TO_AND_BY_SELF_RE, _to_and_by_self),
    EffectHandler(
        "prevent_combat_damage_to_and_by_previous", _TO_AND_BY_PREVIOUS_RE, _to_and_by_previous,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler("prevent_all_damage_dealt_by_target", _PREVENT_DEALT_BY_TARGET_RE, _prevent_dealt_by_target),
    EffectHandler("prevent_damage_by_source_class", _SOURCES_BY_RE, _prevent_by_sources),
    EffectHandler("prevent_damage_source_class_would_deal", _SOURCES_WOULD_DEAL_RE, _prevent_by_sources),
    EffectHandler(
        "prevent_damage_to_creature_class", _TO_CREATURES_RE, _prevent_to_creatures,
        fallback_for=("prevent_all_damage_creatures",),
    ),
    EffectHandler("prevent_combat_or_noncombat_damage_to_you", _TO_YOU_RE, _prevent_to_you),
    EffectHandler("prevent_next_combat_damage_to_you", _NEXT_COMBAT_TO_YOU_RE, _next_combat_to_you),
    EffectHandler(
        "prevent_next_damage_to_player_or_planeswalker", _NEXT_TO_PLAYER_OR_PLANESWALKER_RE,
        _next_to_player_or_planeswalker,
    ),
    EffectHandler(
        "prevent_combat_damage_dealt_by_previous", _COMBAT_DEALT_BY_PREVIOUS_RE, _combat_dealt_by_previous,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler("prevent_damage_to_multi_target", _PREVENT_TO_MULTI_RE, _prevent_to_multi),
    EffectHandler("prevent_damage_by_multi_target", _PREVENT_BY_MULTI_RE, _prevent_by_multi),
    EffectHandler("prevent_next_time_chosen_source", _NEXT_TIME_PREVENT_RE, _next_time_prevent),
    EffectHandler("redirect_next_time_chosen_source", _NEXT_TIME_REDIRECT_RE, _next_time_redirect),
    EffectHandler("redirect_all_from_chosen_source", _ALL_FROM_CHOSEN_SOURCE_REDIRECT_RE, _all_from_chosen_source_redirect),
    EffectHandler("prevent_all_damage_chosen_source", _PREVENT_CHOSEN_SOURCE_RE, _prevent_chosen_source),
    EffectHandler("prevent_next_damage_chosen_source", _PREVENT_NEXT_CHOSEN_SOURCE_RE, _prevent_next_chosen_source),
    EffectHandler("prevent_shield_then_source_punish", _SHIELD_THEN_SOURCE_PUNISH_RE, _shield_then_source_punish),
    EffectHandler("prevent_shield_then_counters", _SHIELD_THEN_COUNTERS_RE, _shield_then_counters),
    EffectHandler("damage_then_excess_to_controller", _DAMAGE_THEN_EXCESS_RE, _damage_then_excess),
    EffectHandler("damage_then_unpreventable", _DAMAGE_THEN_UNPREVENTABLE_RE, _damage_then_unpreventable),
    EffectHandler(
        "redirect_damage_shield", _REDIRECT_SHIELD_RE, _redirect_shield, reading_aware=True,
        fallback_for=("redirect_damage_to_self",),
    ),
    EffectHandler("redirect_damage_once", _REDIRECT_ONCE_RE, _redirect_once, reading_aware=True),
]
