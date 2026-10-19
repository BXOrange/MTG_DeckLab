"""Tap/untap, return-to-hand/library and graveyard-zone rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import re

from typing import Optional
from ..clause_hooks import parse_effect_body
from ..count_phrase import parse_count_phrase
from ..counters import KEYWORD_COUNTER_KINDS
from ..static_handlers import quoted_ability_grant_effects
from ..subgrammars import (
    COLOR_WORD_ALT,
    count_of,
    count_or_x_of,
    OTHER_PREFIX,
    resolve_color_word,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    TARGET,
    target_kind_allowed,
    target_macro,
    UP_TO_ONE,
)
from ..subtype_vocabulary import SUBTYPES
from ...normalize import SELF
from ...spec import EffectSpec
from ..clause_hooks import match_clause
from .shared import (
    ANY_NUMBER_TARGET_CAP,
    ATTACHED_SUBJECT,
    compile_clause,
    counter_sign,
    CREATURE_FILTER_KEYWORD_WORDS,
    EffectHandler,
    GRAVEYARD_SCOPE_WORD,
    graveyard_target_kind,
    GRAVEYARD_TYPE_WORD,
    MASS_DESTROY_FILTER,
    mass_destroy_filter_dict,
    mass_group_params,
    MULTI_TARGET_ALT,
    multi_target_params,
    MULTI_TARGET_QUANTIFIER,
    MULTI_TARGET_QUANTIFIER_X,
    NONCREATURE_SUBTYPE_WORDS,
    optional_param,
    SELF_SUBJECT,
    SINGLE_TYPE_PERMANENT_KINDS,
    two_color_letters,
)


#: An open-ended colour list — "red, white, or black", "white or blue",
#: "red, white, black, or green" — the N-colour generalization of a
#: `(?P<c1>…) or (?P<c2>…)` pair. Matched as one `(?P<colors>…)` group; hand
#: the raw text to `_color_word_list` to get the WUBRG letters.
_COLOR_WORD_LIST_INNER = (
    rf"(?:{COLOR_WORD_ALT})(?:,? (?:or )?(?:{COLOR_WORD_ALT}))+"
)


def _color_word_list(text: Optional[str]) -> Optional[list[str]]:
    """"red, white, or black" → ``["R", "W", "B"]`` (order preserved), or
    ``None`` for an empty/unrecognised list or a repeated colour. The
    N-colour sibling of `_two_color_letters` — used where a `TargetSpec`
    colour narrowing may name three or more colours (Offspring's Revenge)."""
    if not text:
        return None
    words = re.findall(COLOR_WORD_ALT, text)
    letters = [resolve_color_word(w) for w in words]
    if len(letters) < 2 or not all(letters) or len(set(letters)) != len(letters):
        return None
    return letters


#: "return all creatures to their owners' hands" / "return each other creature you control to
#: its owner's hand" (Evacuation, Denizen of the Deep — PAR-128): `ReturnToHandEffect.group`.
_RETURN_GROUP_RE = compile_clause(
    r"return (?P<quant>all|each) (?P<group>[a-z0-9' ,/+-]+?) to (?:their owners'?|its owner'?s?) hands?"
)


def _return_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = mass_group_params(m.group("group"), m.group("quant"))
    return None if params is None else [EffectSpec("return_to_hand", params)]


#: "put all creatures on the bottom of their owners' libraries" (Terminus, Hallowed Burial) — `ReturnToLibraryEffect.group`.
_PUT_GROUP_ON_BOTTOM_RE = compile_clause(
    r"put (?P<quant>all|each) (?P<group>[a-z0-9' ,/+-]+?) on the bottom of (?:their owners'?|its owner'?s?) librar(?:y|ies)"
)


def _put_group_on_bottom(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = mass_group_params(m.group("group"), m.group("quant"))
    if params is None or "group_player" in params:  # a "…target player controls" group needs a target; not built
        return None
    return [EffectSpec("return_to_library", {**params, "position": "bottom"})]


#: PAR-152 (Olivia, Crimson Bride): "It gains \"when you don't control a legendary Vampire, exile ~.\"" — a permanent
#: (RULE 611.2c: no duration, rest of the game) quoted-ability grant to the card the previous clause returned.
_IT_GAINS_QUOTED_ABILITY_RE = compile_clause(r"it gains \"(?P<inner>(?:when|whenever)[^\"]+)\"")


def _it_gains_quoted_ability(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    grant = quoted_ability_grant_effects(m.group("inner"))
    if grant is None:
        return None
    return [EffectSpec("grant_until", {
        "static": {"type": grant.type, "params": grant.params},
        "duration": "rest_of_game",
        "previous_subject": True,
        "target_kind": None,
    })]


#: "Whenever this creature deals combat damage to a creature, exile that
#: creature." (Kaldra Compleat) — this is not a second RULE 115 target:
#: ``that creature`` is the recipient recorded on the firing DAMAGE event.
#: `ExileEffect`'s trigger-subject mode reads ``target_id`` for such an
#: event and falls back to ``instance_id`` for object-subject triggers.
_EXILE_TRIGGER_REFERENT_RE = compile_clause(r"exile that creature")


def _exile_trigger_referent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {"target_kind": "trigger_subject"})]


#: The target kinds "tap/untap target X" accepts — the plain permanent
#: types plus the controller-scoped creature kinds ("tap target creature
#: **an opponent controls**", Chillbringer/Berg Strider &c.; `legal_targets`
#: resolves all three).
_TAP_TARGET_KINDS = (
    "creature", "permanent", "legendary_permanent", "forest",
    "creature_you_control", "creature_you_dont_control", "other_creature_you_control",
    "werewolf_creature",
    "creature_defending_player_controls",
    "permanent_you_control", "permanent_you_dont_control",
    *SINGLE_TYPE_PERMANENT_KINDS,
)


def _tap(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _TAP_TARGET_KINDS):
        return None
    untap = m.group("verb").lower() == "untap"
    params: dict = {"target_kind": kind, "untap": untap, **optional_param(m)}
    # See `_destroy`'s own comment. "Tap target untapped creature"/"tap
    # target tapped creature" is a real, printed shape (Backlash, Ana
    # Battlemage's kicker mode) that needs the qualifier too — a "would be
    # a no-op either way" case for tap specifically only when the two words
    # happen to agree with the verb, which they usually don't.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("tap", params)]


#: "tap target `<c1>` or `<c2>` creature[ an opponent controls]"
#: (Tidebinder Mage) — `TargetSpec.colors`' OR narrowing, the
#: `_pump_target_two_color` / `_destroy_color_adj` idiom (the shared
#: `TARGET` macro carries no colour slot). Tidebinder's "…doesn't untap
#: for as long as you control ~" tail rides the pronoun as its own
#: `previous_subject` clause, so only the tap itself is this row's job.
_TAP_TWO_COLOR_RE = compile_clause(
    rf"(?P<verb>tap|untap) target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) "
    rf"creature(?P<yc> (?:an opponent controls|you don't control))?"
)


def _tap_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = two_color_letters(m)
    if colors is None:
        return None
    kind = "creature_you_dont_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("tap", {
        "target_kind": kind, "untap": m.group("verb").lower() == "untap", "colors": colors,
    })]


#: "tap N target creatures" / "untap up to two target lands" (RULE 115.1a
#: generalized to N>=2, Snap-shaped — `TapEffect.count` already supported
#: this; only the grammar was missing). Restricted to the same
#: creature/permanent kinds the singular `_tap` handler allows.
def _tap_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = multi_target_params(m)
    if params is None or not target_kind_allowed(
        params["target_kind"], ("creature", "permanent", *SINGLE_TYPE_PERMANENT_KINDS),
    ):
        return None
    untap = m.group("verb").lower() == "untap"
    params["untap"] = untap
    return [EffectSpec("tap", params)]


#: "Tap one or two target creatures without horsemanship." (MEC-87, Broken
#: Dam-shaped) — `_tap_multi_target`'s own sibling narrowed by a creature
#: keyword filter (`TapEffect.creature_filter`, the same field `destroy`/
#: `damage`'s own single-target filter siblings already use). Restricted to
#: the bare "target creatures" phrase — the only plural row this filter
#: family is printed against on a real card so far.
_TAP_MULTI_TARGET_KEYWORD_FILTER_RE = compile_clause(
    rf"(?P<verb>tap|untap) {MULTI_TARGET_QUANTIFIER}(?P<target>target creatures) "
    rf"(?P<neg>with|without) (?P<kw>{'|'.join(CREATURE_FILTER_KEYWORD_WORDS)})"
)


def _tap_multi_target_keyword_filter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = multi_target_params(m)
    if params is None or params["target_kind"] != "creature":
        return None
    key = "without_keyword" if m.group("neg").lower() == "without" else "keyword"
    params["creature_filter"] = {key: CREATURE_FILTER_KEYWORD_WORDS[m.group("kw").lower()]}
    params["untap"] = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", params)]


def _tap_selector(m: re.Match[str]) -> list[EffectSpec]:
    # "untap all creatures you control" (Village Bell-Ringer's ETB) /
    # "untap each other creature you control" (Copperhorn Scout's own
    # attack trigger) — an untargeted mass effect, `game/effects/core.py`'s
    # `TapEffect.selector`, the same shape `_add_counters_selector` uses
    # for a mass counter effect.
    untap = m.group("verb").lower() == "untap"
    other = m.groupdict().get("other_all") or m.groupdict().get("other_each")
    selector = "other_creatures_you_control" if other else "creatures_you_control"
    return [EffectSpec("tap", {"selector": selector, "untap": untap})]


#: "tap all creatures target opponent controls" / "tap all lands target player
#: controls" (Tempest Caller, Gulf Squid, Mana Short — PAR-128): the mass group
#: scoped to a chosen player. The selector is written `of: "you"` and
#: `TapEffect.selector_player` evaluates it for that player.
_TAP_ALL_PLAYER_GROUP_RE = compile_clause(
    r"(?P<verb>tap|untap) all (?P<group>[a-z' -]+?) "
    r"(?P<who>target player|target opponent|defending player|that player) controls"
)
_TAP_ALL_PLAYER_SCOPES: dict[str, str] = {
    "target player": "player", "target opponent": "opponent",
    "defending player": "defending", "that player": "event_player",
}


def _tap_all_player_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    selector = parse_count_phrase(m.group("group"))
    if selector is None or selector.get("zone") != "battlefield" or selector.get("of") != "any":
        return None
    return [EffectSpec("tap", {
        "selector": {**selector, "of": "you"},
        "selector_player": _TAP_ALL_PLAYER_SCOPES[m.group("who")],
        "untap": m.group("verb").lower() == "untap",
    })]


def _tap_all_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    group = m.group("group")
    if "target" in group or "that player" in group:
        return None
    selector = parse_count_phrase(group)
    if selector is None or selector.get("zone") != "battlefield":
        return None
    return [EffectSpec("tap", {"selector": selector, "untap": m.group("verb").lower() == "untap"})]


#: MEC-28: "untap all attacking creatures" (Karlach, Fury of Avernus) /
#: "untap each attacking creature" (Hexplate Wallbreaker's Equipment ETB) —
#: `TapEffect.selector`'s `"attacking_creatures"` mode, unscoped by
#: controller (`continuous.group_selector_objects`'s existing branch, the
#: same one Motivated Pony's anthem already reads).
def _tap_attacking_creatures(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"selector": "attacking_creatures", "untap": untap})]


#: "Untap it and all Samurai you control." (Godo, Bandit Warlord's own
#: attack trigger) — the compound "self **and** a subtype group" untap
#: `_tap_self`/`_tap_selector` each only cover one half of; two ordinary
#: `tap` `EffectSpec`s in sequence (the ability's own effect list, RULE
#: 608.2 printed order) rather than a single effect trying to express both
#: recipients at once.
_TAP_SELF_AND_SUBTYPE_RE = compile_clause(
    r"(?P<verb>tap|untap) it and all (?P<subtype>[a-z]+) you control"
)


def _tap_self_and_subtype(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    subtype = m.group("subtype").rstrip("s")
    return [
        EffectSpec("tap", {"target_kind": None, "untap": untap}),
        EffectSpec("tap", {"selector": f"creatures_you_control_of_type_{subtype}", "untap": untap}),
    ]


def _tap_self(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    subject = m.group(0).split(None, 1)[1].lower()
    # An explicit "~" is the source itself, never a target a sibling clause announced
    # ("destroy target artifact and untap ~", Goblin Archaeologist); a bare "it" stays
    # the pronoun reading (`target_kind=None`, rewritten/read from the surrounding clauses).
    kind = "source" if subject == "~" else None
    return [EffectSpec("tap", {"target_kind": kind, "untap": untap})]


#: MEC-28: "untap that creature" (Finest Hour's own attacks-alone trigger) —
#: the `group_subject_only` sibling of `_tap_self`'s bare "it"/"~" pronoun:
#: "that creature" is genuinely ambiguous (it means *whichever creature
#: matched this ability's group-subject trigger condition* here, but means
#: an earlier clause's own target on `_lockdown`'s `previous_subject_only`
#: row), so it's a dedicated row rather than added to `_SELF_SUBJECT`, only
#: offered when the caller confirms the trigger really has a group subject.
#: Same output shape as `_tap_self` — `effect_binder.
#: _retarget_implicit_subject_effects` is what turns the resulting
#: ``target_kind: None`` into a live per-firing read at bind time.
_TAP_GROUP_SUBJECT_RE = compile_clause(r"(?P<verb>tap|untap) that creature")


#: "{U}: Tap enchanted creature."/"{U}: Untap enchanted creature." (Freed
#: from the Real/Pemmin's Aura-shaped Aura activated abilities).
def _tap_attached(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": "attached_permanent", "untap": untap})]


#: "return target creature to its owner's hand" / "return a land you control
#: to its owner's hand" (RULE 701.3) — the bounce family. ``target_kind``
#: reuses the shared `TARGET` grammar, so this claims both a genuine RULE 115
#: target and the "a land you control" controller-restricted choice the same
#: way; restricted to the shapes real bounce cards actually use.
#: ``other_creature_you_control`` (PAR-79 ninth increment — Deputy of
#: Acquittals/Jeskai Barricade's "you may return another target creature
#: you control to its owner's hand") is RULE 109.5's "another target
#: creature you control" — already whitelisted globally
#: (`ALLOWED_TARGET_KINDS`, built for Giver of Runes) and already resolved
#: by `resolve_target_kind`, just never added to this handler's own closed
#: kind list before now.
_RETURN_TO_HAND_KINDS: frozenset[str] = frozenset(
    {
        "creature", "permanent", "nonland_permanent", "nonland_permanent_you_control", "historic_permanent_you_control", "any", "creature_you_control",
        "land_you_control", "other_creature_you_control",
        # The single-type pools: "return target artifact to its owner's hand" and, plural, "return
        # X target artifacts …" (`targeting.TARGET_FRAMES`' artifact/enchantment/land).
        "artifact", "enchantment", "land",
    }
)


def _return_to_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _RETURN_TO_HAND_KINDS):
        return None
    params: dict = {"target_kind": kind, **optional_param(m)}
    # See `_destroy`'s own comment: "return target tapped creature to its
    # owner's hand" (Galestrike-shaped) needs the same qualifier.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("return_to_hand", params)]


#: RULE 601.2c mass "return all nonland permanents with mana value X or less
#: to their owners' hands." (Displacement Wave) — `ReturnToHandEffect`'s own
#: sibling of `_destroy_all`'s board wipe, reusing the exact same
#: `_MASS_DESTROY_FILTER`/`_mass_destroy_filter_dict` vocabulary (including
#: the ``"x"`` sentinel, substituted at cast time by `RulesEngine.
#: _substitute_x`, which already walks any effect's ``filter`` attribute
#: generically).
_RETURN_ALL_NONLAND_RE = compile_clause(
    rf"return all (?P<other>other )?nonland permanents{MASS_DESTROY_FILTER} to their owners'? hands?"
)


def _return_all_nonland(m: re.Match[str]) -> list[EffectSpec]:
    # PAR-128: RULE 109.5 "all other nonland permanents" (Kederekt Leviathan).
    params: dict = {"selector": "all_other_nonland_permanents" if m.group("other") else "all_nonland_permanents"}
    filt = mass_destroy_filter_dict(m)
    if filt:
        params["filter"] = filt
    return [EffectSpec("return_to_hand", params)]


#: "put target creature on top of its owner's library" (RULE 701.3 — Time
#: Ebb/Griptide/Roil Spout/Vedalken Dismisser-shaped tempo bounce, 10 SOLO
#: cards, `parser_probe.py blocked`) / "…on the bottom of its owner's
#: library" (rarer — same shape, ``position="bottom"``). `ReturnToLibraryEffect`
#: is `return_to_hand`'s library-destination sibling.
#: "… library third from the top" (RULE 401.7 — God-Eternal Oketra, Enigma Sphinx, Long-Term Plans).
_NTH_FROM_TOP_WORDS = {"second": 2, "third": 3, "fourth": 4, "fifth": 5}
_NTH_FROM_TOP = r"(?P<nth>" + "|".join(_NTH_FROM_TOP_WORDS) + r") from the top"
#: Where "put … into/on … its owner's library" lands: on top, on the bottom, or Nth from the top.
_LIBRARY_PLACEMENT = (
    rf"(?:on (?:top|the (?P<pos>bottom)) of its owner's library|into (?:its owner's|your) library {_NTH_FROM_TOP})"
)


def _library_placement_params(m: re.Match[str]) -> dict:
    groups = m.groupdict()
    if groups.get("nth"):
        return {"position": "top", "depth": _NTH_FROM_TOP_WORDS[groups["nth"]]}
    return {"position": "bottom" if groups.get("pos") == "bottom" else "top"}


def _return_to_library(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    # PAR-104: the three-type pool ("put target artifact, creature, or enchantment on the bottom of its owner's
    # library" — Banishing Stroke, Banishment Decree) has its own frame; before it, it read as any permanent.
    if not target_kind_allowed(kind, _RETURN_TO_HAND_KINDS | {"artifact_creature_or_enchantment"}):
        return None
    return [
        EffectSpec(
            "return_to_library",
            {"target_kind": kind, **_library_placement_params(m), **optional_param(m)},
        )
    ]


#: PAR-161: "target creature's owner puts it on their choice of the top or bottom of their library." / "the owner of
#: target nonland permanent puts it on …" (RULE 401.4: the *owner*, not the controller, picks top or bottom) —
#: `OwnerChoosesLibraryPositionEffect`, the effect Plan for All Outcomes / Endless Detour were hand-authored onto.
#: The mandatory form only: "up to one" is the optional flag the effect already carries.
_OWNER_TARGET_B = target_macro("_b")
#: Pools the shared `TARGET` grammar has no row for (it would leave the clause unclaimed): the literal phrase -> kind.
_OWNER_PUTS_EXTRA_TARGETS: dict[str, str] = {
    "target spell or nonland permanent": "spell_or_nonland_permanent",
    "target creature or spacecraft": "creature_or_spacecraft",
    "target spell or creature": "spell_or_creature",
}
_OWNER_PUTS_EXTRA_RE = "|".join(re.escape(p) for p in _OWNER_PUTS_EXTRA_TARGETS)
_OWNER_PUTS_TOP_OR_BOTTOM_RE = compile_clause(
    rf"(?:(?:{TARGET}|(?P<xtarget>{_OWNER_PUTS_EXTRA_RE}))'s owner|the owner of (?:{_OWNER_TARGET_B}|(?P<xtarget_b>{_OWNER_PUTS_EXTRA_RE}))) "
    r"puts it on (?:their|its owner's) choice of the top or bottom of their library"
)
_OWNER_PUTS_TOP_OR_BOTTOM_KINDS: frozenset[str] = frozenset(
    {"creature", "nonland_permanent", "artifact_or_creature", "spell_or_nonland_permanent", "creature_or_spacecraft"}
)


#: PAR-161: the *controller* chooses — "put target card from a graveyard on your choice of the top or bottom of its
#: owner's library" (Not Forgotten) / "you may put it on your choice of the top or bottom of its owner's library" (Arashin
#: Sovereign's dies trigger: the source itself, RULE 400.7). Same effect, ``chooser="controller"``.
_CONTROLLER_PUTS_TOP_OR_BOTTOM_RE = compile_clause(
    r"put target card from a graveyard on your choice of the top or bottom of its owner's library"
)
_CONTROLLER_MAY_PUT_SELF_TOP_OR_BOTTOM_RE = compile_clause(
    r"(?:you may )?put (?:~|it) on your choice of the top or bottom of its owner's library"
)


def _controller_puts_top_or_bottom(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("owner_puts_on_top_or_bottom", {
        "target_kind": "any_graveyard_card", "optional": False, "chooser": "controller",
    })]


def _controller_may_put_self_top_or_bottom(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("owner_puts_on_top_or_bottom", {
        "target_kind": None, "chooser": "controller",
    })]


def _owner_puts_top_or_bottom(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    extra = m.group("xtarget") or m.group("xtarget_b")
    suffix = "" if (m.group("target") or m.group("xtarget")) else "_b"
    if extra:
        return [EffectSpec("owner_puts_on_top_or_bottom", {
            "target_kind": _OWNER_PUTS_EXTRA_TARGETS[extra.lower()], "optional": False,
        })]
    kind = resolve_target_kind(m.group(f"target{suffix}"))
    if not target_kind_allowed(kind, _OWNER_PUTS_TOP_OR_BOTTOM_KINDS):
        return None
    if resolve_target_creature_state_filter(m.group(f"target{suffix}")):
        return None  # a qualifier the effect's TargetSpec does not carry would be dropped silently
    return [EffectSpec("owner_puts_on_top_or_bottom", {
        "target_kind": kind, "optional": bool(m.group(f"up_to_one{suffix}")),
    })]


#: "put ~ on top of / on the bottom of its owner's library", "put it into its owner's library third from
#: the top" (self form — Fell Horseman's and Murderous Rider's dies trigger, God-Eternal Oketra, Bookwurm's
#: graveyard ability). The source may already be in the graveyard (RULE 400.7), which
#: `RulesEngine.return_to_library` handles ("from wherever it is"). The pronoun form is only offered when
#: the caller says the implicit subject is the source (`EffectHandler.self_subject_only`).
_RETURN_SELF_TO_LIBRARY_RE = compile_clause(
    rf"put (?:~|this card)(?: from your graveyard)? {_LIBRARY_PLACEMENT}"
)
#: PAR-162: "put this card from your graveyard on top of your library" (Champion of Stray Souls, Gate Colossus) —
#: the source itself, which lives in (and acts from) the graveyard; "your library" is its owner's because the card
#: is in your graveyard. `ReturnSelfFromGraveyardToHandEffect`'s ``library_top`` destination.
_PUT_SELF_GRAVEYARD_TOP_RE = compile_clause(r"put (?:~|this card) from your graveyard on top of your library")


def _put_self_graveyard_top(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_self_from_graveyard_to_library_top", {})]

_RETURN_IT_TO_LIBRARY_RE = compile_clause(rf"put it {_LIBRARY_PLACEMENT}")


#: "put enchanted creature into its owner's library third from the top" (Shattered Ego) — the Aura's host.
_RETURN_ATTACHED_TO_LIBRARY_RE = compile_clause(rf"put enchanted (?:creature|permanent) {_LIBRARY_PLACEMENT}")


def _return_attached_to_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_library", {"target_kind": "attached_permanent", **_library_placement_params(m)})]


def _return_self_to_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_library", {"target_kind": None, **_library_placement_params(m)})]


#: "Put target card from a graveyard on the bottom of its owner's library."
#: (PAR-83 — Junktroller/Chrome Companion).  This is deliberately a
#: ``return_to_library`` spec rather than a shuffle: RulesEngine.
#: return_to_library already moves an object from any zone to its owner's
#: library without randomising it, and ``any_graveyard_card`` is the existing
#: RULE 115 target vocabulary for a card from any player's graveyard.
_GRAVEYARD_CARD_TO_LIBRARY_BOTTOM_RE = compile_clause(
    r"put target card from a graveyard on the bottom of its owner's library"
)


def _graveyard_card_to_library_bottom(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_library", {
        "target_kind": "any_graveyard_card", "position": "bottom",
    })]


#: "Return ~ to its owner's hand." (RULE 701.3, self form — no RULE 115
#: target and no player choice, the bounce sibling of `_sacrifice_self`/
#: `_exile_self`). Two families of real cards, both Aura-heavy:
#: Rancor/Launch/Aspect of Mongoose's "When ~ dies, return it to its
#: owner's hand." trigger (`normalize` folds RULE 700.4's long "is put
#: into a graveyard from the battlefield" phrasing to "dies", and ``it``
#: to ``~``), and Flickering Ward/Fiery Mantle's "{W}: Return ~ to its
#: owner's hand." activated ability. Resolves against the effect's own
#: source wherever it currently is — battlefield *or* graveyard, since a
#: dies-trigger's source has already moved (RULE 400.7) by the time the
#: ability resolves and `RulesEngine.return_to_hand` moves an object from
#: whatever zone it's in.
def _return_self_to_hand(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_hand", {"target_kind": None})]


#: "return ~ and target `<c1>` or `<c2>` creature[ you control] to their
#: owner's hand" (Snow Hound) — a compound bounce: two `return_to_hand`
#: specs in printed order (RULE 608.2), the self one (`target_kind=None`)
#: then the RULE 115 colour-narrowed target. Same "two sequenced specs
#: rather than one effect expressing both recipients" idiom
#: `_tap_self_and_subtype` uses.
_RETURN_SELF_AND_TWO_COLOR_RE = compile_clause(
    rf"return (?P<self>~|this creature) and target "
    rf"(?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) creature(?P<yc> you control)? "
    rf"to (?:its|their) owner'?s hand"
)


def _return_self_and_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = two_color_letters(m)
    if colors is None:
        return None
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [
        EffectSpec("return_to_hand", {"target_kind": None}),
        EffectSpec("return_to_hand", {"target_kind": kind, "colors": colors}),
    ]


#: PAR-165 (Coastal Wizard, Lady Sun): "return ~ and another target creature to their owners' hands" -- the same
#: two-spec self + RULE 115 target idiom; "another" is the plain `creature` kind's default source exclusion.
_RETURN_SELF_AND_ANOTHER_RE = compile_clause(
    r"return (?:~|this creature) and another target creature to (?:its|their) owner(?:'s|s'?)? hands?"
)


def _return_self_and_another(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("return_to_hand", {"target_kind": None}),
        EffectSpec("return_to_hand", {"target_kind": "creature"}),
    ]


#: "return two target creatures to their owners' hands" (RULE 115.1a
#: generalized to N>=2) — the plural sibling of `_return_to_hand`.
def _return_to_hand_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = multi_target_params(m)
    if params is None or not target_kind_allowed(params["target_kind"], _RETURN_TO_HAND_KINDS):
        return None
    return [EffectSpec("return_to_hand", params)]


#: "Return those creatures to their owners' hands." (PAR-1, Run Away
#: Together) — the indirect-referent sibling of `_return_to_hand_multi_
#: target`: the group was already announced (and, for "controlled by
#: different players", already constrained) by the preceding "choose N
#: target creatures …" clause (`_choose_targets_group`), so this clause
#: names no target of its own at all — only offered when that preceding
#: clause actually chose one (`EffectHandler.previous_subject_only`).
_RETURN_PREVIOUS_GROUP_RE = compile_clause(
    r"(?:then )?return (?:those creatures|them) to their owners'? hands?"
)


def _return_previous_group(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_hand", {"previous_subject": True})]
#: PAR-128: RULE 109.5's "another"/"other" before "target" on a graveyard card.
#: A slot, not a filter: the graveyard pool already leaves out the ability's own
#: source (`targeting.legal_targets`' `o is not source`), which is all "another"
#: asks for (Junk Diver's dies trigger names its own graveyard card).
_GRAVEYARD_OTHER = rf"(?:{OTHER_PREFIX})?"


#: "exile up to twice X target cards from graveyards." (Erebos's Intervention) / "exile X target cards
#: from graveyards" — several graveyard cards picked from any graveyards at once. The X forms size the
#: pick by the announced {X} (`TargetSpec.count_selector`, read at announce time); a literal count is
#: the plain multi-target shape. "a single graveyard" (a same-graveyard constraint) is not this row.
_EXILE_GRAVEYARD_CARDS_MULTI_RE = compile_clause(
    r"exile (?:(?P<x_count>(?P<x_up_to>up to )?(?P<twice>twice )?x )"
    r"|(?P<up_to>up to )?(?P<count>\d+) )target cards from graveyards"
)


def _exile_graveyard_cards_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("x_count"):
        return [EffectSpec("exile", {
            "target_kind": "any_graveyard_card", "count": ANY_NUMBER_TARGET_CAP, "optional": True,
            "count_selector": "source_twice_x_paid" if m.group("twice") else "source_x_paid",
        })]
    count = int(m.group("count"))
    if count < 2:
        return None
    params: dict = {"target_kind": "any_graveyard_card", "count": count}
    if m.group("up_to"):
        params["optional"] = True
    return [EffectSpec("exile", params)]


#: Colour-list ("`<c1>` or `<c2>`") siblings of the bounce / put-on-library
#: / graveyard-return handlers — `TargetSpec.colors`' OR narrowing, the
#: `_pump_target_two_color` / `_destroy_color_adj` idiom. Dedicated rows
#: because the shared `TARGET` macro carries no colour slot (see
#: `subgrammars.COLOR_WORD_ALT`'s note). Escape Routes (bounce), Hunting
#: Drake (library), Crypt Angel (graveyard).
_RETURN_TO_HAND_TWO_COLOR_RE = compile_clause(
    rf"return target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) "
    rf"creature(?P<yc> you control)? to its owner's hand"
)
_RETURN_TO_LIBRARY_TWO_COLOR_RE = compile_clause(
    rf"put target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) creature "
    rf"on (?:top|the (?P<pos>bottom)) of its owner's library"
)
_RETURN_FROM_GRAVEYARD_TWO_COLOR_RE = compile_clause(
    rf"return target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) creature card from "
    rf"(?P<scope>{GRAVEYARD_SCOPE_WORD}) graveyard to "
    r"(?P<dest>the battlefield|your hand|its owner'?s hand)"
)


def _return_to_hand_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = two_color_letters(m)
    if colors is None:
        return None
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("return_to_hand", {"target_kind": kind, "colors": colors})]


def _return_to_library_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = two_color_letters(m)
    if colors is None:
        return None
    position = "bottom" if m.group("pos") == "bottom" else "top"
    return [EffectSpec("return_to_library", {
        "target_kind": "creature", "position": position, "colors": colors,
    })]


def _return_from_graveyard_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = two_color_letters(m)
    if colors is None:
        return None
    kind = graveyard_target_kind("creature", m.group("scope"))
    if kind is None:
        return None
    destination = "battlefield" if m.group("dest") == "the battlefield" else "hand"
    return [EffectSpec("return_from_graveyard", {
        "target_kind": kind, "destination": destination, "colors": colors,
    })]


#: "return target [type] card [with mana value N or less] from [scope]
#: graveyard to the battlefield/your hand/its owner's hand" / "put target
#: [type] card from [scope] graveyard onto the battlefield under its
#: owner's control" (RULE 701.3, the Regrowth/Reanimate/Deathrite-adjacent
#: recursion family — see `game/targeting.py`'s `_GRAVEYARD_TARGET_KINDS`
#: for the scope × type vocabulary this claims). Both verb shapes land the
#: object under its own *owner*'s control — the "steal it for yourself"
#: shape is `_reanimate_under_your_control` below, a genuinely different
#: effect. The optional mana-value cap (Auriok Salvagers-shaped) is the
#: same `TargetSpec.max_mana_value` offer-time filter `destroy_mv` already
#: uses, not a new one.
_RETURN_FROM_GRAVEYARD_RE = compile_clause(
    rf"return (?P<up_to_one>{UP_TO_ONE}){_GRAVEYARD_OTHER}target (?:(?P<nonleg>nonlegendary) )?"
    # PAR-165: one leading adjective -- a colour ("black card", Xiahou Dun) or "legendary" ("legendary creature card", Loyal Retainers).
    rf"(?:(?P<adj>legendary|{COLOR_WORD_ALT}) )?"
    rf"(?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?card(?P<adv> that has an adventure)?"
    # PAR-143: "with power 2 or less" (Alesha) rides the same slot as the mana-value cap.
    # PAR-164: "…with mana value less than or equal to ~'s power" (Sandbender Scavengers) -- the ceiling is the
    # source's own power, `TargetSpec.max_mana_value`'s existing ``"source_power"`` sentinel.
    rf"(?: with (?:mana value (?P<mv>\d+)|power (?P<pw>\d+)) or less| with mana value (?P<emv>x)"
    r"| with mana value less than or equal to (?P<mvp>~'s power))? from "
    rf"(?P<scope>{GRAVEYARD_SCOPE_WORD}) graveyard to "
    r"(?P<dest>the battlefield|your hand|its owner'?s hand)"
    # PAR-143: "…to the battlefield tapped [and attacking]" (RULE 110.5b / 508.4).
    r"(?P<tapped> tapped)?(?P<atk> and attacking)?"
    # "…to the battlefield with a -1/-1 counter on it." (Persist — RULE
    # 701.3 recursion plus an enters-with rider, distinct from the Persist
    # *keyword*'s in-place return). MEC-108 widened the counter to a +1/+1 or
    # RULE 122.1b keyword counter and its amount ("with a flying counter on it",
    # "with 2 +1/+1 counters on it").
        # "with an additional +1/+1 counter on it" (Prison Break) is the same counter: it adds to what the card enters with.
    rf"(?: with (?P<ewc_n>a|an|\d+)(?: additional)? (?P<ewc_kind>-1/-1|\+1/\+1|corpse|finality|{'|'.join(KEYWORD_COUNTER_KINDS)}) counters? on it)?"
)
_PUT_FROM_GRAVEYARD_OWNER_CONTROL_RE = compile_clause(
    rf"put (?P<up_to_one>{UP_TO_ONE}){_GRAVEYARD_OTHER}target (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{GRAVEYARD_SCOPE_WORD}) graveyard onto the battlefield under its owner'?s control"
)


def _return_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    dest = m.groupdict().get("dest")
    destination = "battlefield" if dest is None or dest == "the battlefield" else "hand"
    params: dict = {"target_kind": kind, "destination": destination}
    if m.groupdict().get("up_to_one"):
        params["optional"] = True
    mv = m.groupdict().get("mv")
    if mv is not None:
        params["max_mana_value"] = int(mv)
    if m.groupdict().get("mvp"):
        params["max_mana_value"] = "source_power"
    if m.groupdict().get("pw") is not None:
        params["creature_filter"] = {"max_power": int(m.group("pw"))}
    if m.groupdict().get("adv"):
        params["creature_filter"] = {"has_adventure": True}  # Edgewall Inn
    adj = m.groupdict().get("adj")
    if adj == "legendary":
        params.setdefault("creature_filter", {})["legendary"] = True
    elif adj:
        color = resolve_color_word(adj)
        if color is None:
            return None
        params["colors"] = [color]
    if m.groupdict().get("emv"):
        params["exact_mana_value"] = "x"  # Isareth the Awakener: bound by the preceding "pay {X}"
    if m.groupdict().get("tapped") or m.groupdict().get("atk"):
        if destination != "battlefield":
            return None  # only a battlefield entry is tapped or attacking
        if m.group("tapped"):
            params["tapped"] = True
        if m.group("atk"):
            if not m.group("tapped"):
                return None  # "attacking" on its own isn't a printed spelling
            params["attacking"] = True
    if m.groupdict().get("nonleg"):
        params["exclude_legendary"] = True
    if m.groupdict().get("ewc_kind"):
        if destination != "battlefield":
            return None  # an enters-with rider is meaningless returning to hand
        params["extra_counters"] = {"kind": m.group("ewc_kind"), "count": count_of(m.group("ewc_n"))}
    return [EffectSpec("return_from_graveyard", params)]


#: "return up to two target creature cards from your graveyard to your
#: hand"/"...to the battlefield" (RULE 115.1a generalized to N>=2 — Back for
#: Seconds/Dead Revels/Death's Duet/Entreat the Dead-shaped, a large real
#: family) — the plural sibling of `_RETURN_FROM_GRAVEYARD_RE`. The type
#: word itself doesn't inflect ("creature cards", not "creatures cards").
_RETURN_FROM_GRAVEYARD_MULTI_RE = compile_clause(
    rf"return {MULTI_TARGET_QUANTIFIER}{_GRAVEYARD_OTHER}target "
    rf"(?:(?P<type>{GRAVEYARD_TYPE_WORD}) |(?P<subtype>[a-z-]+) creature )?cards "
    rf"(?:each with mana value (?P<mv>\d+) or less |with total "
    rf"(?P<measure>mana value|power) (?P<budget>\d+) or less )?from "
    rf"(?P<scope>{GRAVEYARD_SCOPE_WORD}) graveyards? to "
    r"(?P<dest>the battlefield|your hand|their owners'? hands)"
)


def _return_from_graveyard_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subtype = m.group('subtype')
    if subtype:
        if subtype not in SUBTYPES or subtype in NONCREATURE_SUBTYPE_WORDS:
            return None
    kind = graveyard_target_kind('creature' if subtype else m.group('type'), m.group('scope'))
    if kind is None:
        return None
    destination = 'battlefield' if m.group('dest') == 'the battlefield' else 'hand'
    params: dict = {'target_kind': kind, 'destination': destination}
    if destination == 'battlefield':
        params['under_your_control'] = True
    if m.group('any_number'):
        params.update(count=0, any_number=True, optional=True)
    elif m.group('range_min') is not None:
        minimum, maximum = int(m.group('range_min')), int(m.group('range_max'))
        if minimum < 1 or maximum <= minimum:
            return None
        params.update(count=minimum, count_max=maximum)
    else:
        count = int(m.group('count'))
        if count < 2:
            return None
        params['count'] = count
        if m.group('up_to'):
            params['optional'] = True
    if m.group('mv') is not None:
        params['max_mana_value'] = int(m.group('mv'))
    if m.group('budget') is not None:
        params['total_mana_value_max' if m.group('measure') == 'mana value' else 'total_power_max'] = int(m.group('budget'))
    if subtype:
        params['subtype'] = subtype.capitalize()
    return [EffectSpec('return_from_graveyard', params)]


#: "return [up to] X target `<type>` cards from [scope] graveyard to your
#: hand / the battlefield" (Death Denied, Entreat the Dead, Shattered
#: Crypt, Wake the Dead, Champion of Stray Souls) — the target count is
#: the spell/ability's own announced {X} (`GameObject.x_paid`), read at
#: target-gathering time via `TargetSpec.count_selector="source_x_paid"`,
#: the same idiom March of Swirling Mist's "up to X target creatures
#: phase out" and Change of Plans already use. Always `optional`: RULE
#: 601.2c lets an announced X be 0, and "up to X" is optional anyway.
_RETURN_FROM_GRAVEYARD_X_RE = compile_clause(
    rf"return (?:up to )?x {_GRAVEYARD_OTHER}target (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?cards from "
    rf"(?P<scope>{GRAVEYARD_SCOPE_WORD}) graveyards? to "
    r"(?P<dest>the battlefield|your hand)"
)


def _return_from_graveyard_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    destination = "battlefield" if m.group("dest") == "the battlefield" else "hand"
    return [EffectSpec("return_from_graveyard", {
        "target_kind": kind, "destination": destination,
        "count_selector": "source_x_paid", "optional": True,
    })]


#: "put target [type] card from [scope] graveyard onto the battlefield
#: under your control" (Reanimate/Rise from the Grave/Virtue of Persistence)
#: — unlike the two shapes above, this one *steals* the card for the
#: activating/casting player regardless of whose graveyard it came from.
_REANIMATE_UNDER_YOUR_CONTROL_RE = compile_clause(
    rf"put (?P<up_to_one>{UP_TO_ONE}){_GRAVEYARD_OTHER}target (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?card from "
    # PAR-152: "…from **defending player's** graveyard" (Chorale of the Void) — the attacked player's, read off the
    # firing attack event (`defending_graveyard_*` target kinds).
    rf"(?P<scope>{GRAVEYARD_SCOPE_WORD}|defending player'?s|that player'?s) graveyard onto the battlefield under your control"
    # PAR-152: "…under your control **tapped and attacking**" (RULE 508.4 — Chorale of the Void).
    r"(?P<tapped> tapped)?(?P<atk> and attacking)?"
    # PAR-139: "…with a corpse counter on it" (From the Catacombs) — a named enters-with counter.
    # PAR-148: "…with a finality counter on it" (RULE 122.1h; Coalstoke Gearhulk, Grim Reaper's Scythe).
    r"(?: with (?P<ewc_n>a|an|\d+) (?P<ewc_kind>corpse|finality) counters? on it)?"
)


def _reanimate_under_your_control(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind, "destination": "battlefield", "under_your_control": True}
    if m.groupdict().get("atk") and not m.groupdict().get("tapped"):
        return None  # "attacking" on its own isn't a printed spelling
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    if m.groupdict().get("atk"):
        params["attacking"] = True
    if m.groupdict().get("ewc_kind"):
        params["extra_counters"] = {"kind": m.group("ewc_kind"), "count": count_of(m.group("ewc_n"))}
    if m.groupdict().get("up_to_one"):
        params["optional"] = True
    return [EffectSpec("return_from_graveyard", params)]


#: PAR-152 (Thunderkin Awakener): "choose target `<subtype>` creature card in your graveyard with toughness less than
#: ~'s toughness. Return that card to the battlefield tapped and attacking." — the "choose" announces the target
#: (RULE 115), the return acts on it; one `return_from_graveyard` whose target carries the subtype and relative
#: toughness filter (`combat.matches_object_filter`'s ``toughness_vs_reference`` — the source is the reference).
_CHOOSE_GRAVEYARD_RETURN_RE = compile_clause(
    r"choose target (?:(?P<sub>[a-z-]+) )?creature card in your graveyard"
    rf"(?P<tl> with toughness less than {re.escape(SELF)}'?s toughness)?\. "
    r"return that card to the battlefield(?P<tapped> tapped)?(?P<atk> and attacking)?"
)


def _choose_graveyard_return(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("atk") and not m.group("tapped"):
        return None
    creature_filter: dict = {}
    if m.group("sub"):

        sub = m.group("sub").lower()
        if sub not in SUBTYPES or sub in NONCREATURE_SUBTYPE_WORDS:
            return None
        creature_filter["subtype"] = sub.capitalize()
    if m.group("tl"):
        creature_filter["toughness_vs_reference"] = "less"
    params: dict = {"target_kind": "graveyard_creature", "destination": "battlefield"}
    if creature_filter:
        params["creature_filter"] = creature_filter
    if m.group("tapped"):
        params["tapped"] = True
    if m.group("atk"):
        params["attacking"] = True
    return [EffectSpec("return_from_graveyard", params)]


#: "Put one, two, or three target creature cards from graveyards onto the
#: battlefield under your control. Each of them enters with an additional
#: -1/-1 counter on it." (Aberrant Return) — an enumerated RULE 601.2c
#: target-count range ("1, 2, or 3" → min 1, `count_max` 3) folded into the
#: same `return_from_graveyard` effect the singular reanimate row emits,
#: plus the whole-body enters-with rider (`ReturnFromGraveyardEffect.
#: extra_counters`, applied per returned card). Matched as one two-sentence
#: clause (`parse_effect_body` tries the whole body first) since the rider
#: has no standalone handler.
_REANIMATE_MULTI_UNDER_YOUR_CONTROL_RE = compile_clause(
    r"put (?P<lo>\d+), (?:\d+, )*or (?P<hi>\d+) target "
    rf"(?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?cards from graveyards "
    r"onto the battlefield under your control"
    r"(?:\. (?:each of them|they) enters? with an additional "
    r"(?P<ck>-1/-1|\+1/\+1) counter on it)?"
)


def _reanimate_multi_under_your_control(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = graveyard_target_kind(m.groupdict().get("type"), "a")  # "from graveyards" = any
    if kind is None:
        return None
    lo, hi = int(m.group("lo")), int(m.group("hi"))
    if lo < 1 or hi <= lo:
        return None
    params: dict = {
        "target_kind": kind, "destination": "battlefield", "under_your_control": True,
        "count": lo, "count_max": hi,
    }
    if m.groupdict().get("ck"):
        params["extra_counters"] = {"kind": m.group("ck"), "count": 1}
    return [EffectSpec("return_from_graveyard", params)]


#: PAR-15's "any number of" siblings of the two shapes above — always "your
#: own graveyard" on every real card using either ("put ... on top of your
#: library": Bone Harvest/Footbottom Feast/Forever Young/Gravepurge; "shuffle
#: ... into your library": Piper's Melody/Renewing Touch/Perpetual Timepiece/
#: The Bath Song), so unlike `_RETURN_FROM_GRAVEYARD_RE` neither needs the
#: full opponent/any-graveyard scope vocabulary. The shuffle shape is
#: modeled as "put on the bottom, then shuffle" — see `ReturnFromGraveyard
#: Effect.shuffle_after` — since the position `library_bottom` gives it is
#: immediately randomized away by the shuffle, matching "shuffled into your
#: library" exactly.
_RETURN_FROM_GRAVEYARD_TOP_ANY_RE = compile_clause(
    rf"put any number of target (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?cards from "
    r"your graveyard on top of your library"
)
_RETURN_FROM_GRAVEYARD_SHUFFLE_ANY_RE = compile_clause(
    rf"shuffle any number of target (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?cards from "
    r"your graveyard into your library"
)


def _return_from_graveyard_top_any(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = graveyard_target_kind(m.groupdict().get("type"), "your")
    if kind is None:
        return None
    return [EffectSpec("return_from_graveyard", {
        "target_kind": kind, "destination": "library_top",
        "count": ANY_NUMBER_TARGET_CAP, "optional": True,
    })]


def _return_from_graveyard_shuffle_any(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = graveyard_target_kind(m.groupdict().get("type"), "your")
    if kind is None:
        return None
    return [EffectSpec("return_from_graveyard", {
        "target_kind": kind, "destination": "library_bottom", "shuffle_after": True,
        "count": ANY_NUMBER_TARGET_CAP, "optional": True,
    })]


#: PAR-162: "put [up to one] target `<type>` card from `<scope>` graveyard on top of your / its owner's library"
#: (Reclaim, Golgari Thug, Haunted Crossroads, Dead Reckoning's first half), its "up to N target cards" plural
#: (Reinforcements) and the untargeted pick ("you may put a land card from your graveyard on top of your library" —
#: Glowspore Shaman, Halo-Charged Skaab). All ride `return_from_graveyard`'s ``library_top`` destination
#: (RULE 401.3 puts the card on top; RULE 400.7 makes it a new object; RULE 608.2b drops a target that left).
#: "your library" only follows "your graveyard" (the card is yours), "its owner's library" any other scope.
_GRAVEYARD_TO_TOP = (
    r"(?P<scope>{scope}) graveyard on top of (?:(?P<yours>your)|its owner'?s) library"
)
_PUT_GRAVEYARD_CARD_TOP_RE = compile_clause(
    rf"put (?P<up_to_one>{UP_TO_ONE}){_GRAVEYARD_OTHER}target (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?card from "
    + _GRAVEYARD_TO_TOP.format(scope=GRAVEYARD_SCOPE_WORD)
)
_PUT_GRAVEYARD_CARDS_TOP_RE = compile_clause(
    rf"put (?P<up_to>up to )?(?P<count>\d+) {_GRAVEYARD_OTHER}target (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?cards from "
    + _GRAVEYARD_TO_TOP.format(scope=GRAVEYARD_SCOPE_WORD)
)
_PUT_GRAVEYARD_PICK_TOP_RE = compile_clause(
    rf"(?P<may>you may )?put an? (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?card from "
    + _GRAVEYARD_TO_TOP.format(scope=GRAVEYARD_SCOPE_WORD)
)


def _graveyard_top_kind(m: re.Match[str]) -> Optional[str]:
    """The graveyard target kind, or ``None`` when the library possessive contradicts the graveyard's scope."""
    if bool(m.group("yours")) != (m.group("scope").strip().lower() == "your"):
        return None
    return graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))


def _put_graveyard_card_top(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_top_kind(m)
    if kind is None:
        return None
    params: dict = {"target_kind": kind, "destination": "library_top"}
    if m.groupdict().get("up_to_one"):
        params["optional"] = True
    return [EffectSpec("return_from_graveyard", params)]


def _put_graveyard_cards_top(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_top_kind(m)
    count = int(m.group("count"))
    if kind is None or count < 2:
        return None
    params: dict = {"target_kind": kind, "destination": "library_top", "count": count}
    if m.group("up_to"):
        params["optional"] = True
    return [EffectSpec("return_from_graveyard", params)]


def _put_graveyard_pick_top(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_top_kind(m)
    if kind is None:
        return None
    params: dict = {"target_kind": kind, "destination": "library_top", "pick": True}
    if m.group("may"):
        params["optional"] = True
    return [EffectSpec("return_from_graveyard", params)]


#: "Target player shuffles up to N target cards from their graveyard into
#: their library." (PAR-86 — Dwell on the Past/Krosan Reclamation).  This
#: has two linked choices: the player target identifies the graveyard and
#: the controller then chooses its cards, represented by the existing
#: Quandrix Command effect rather than independent card TargetSpecs.
_SHUFFLE_TARGET_GRAVEYARD_CARDS_RE = compile_clause(
    r"target player shuffles up to (?P<n>\d+) target cards from their graveyard into their library"
)


def _shuffle_target_graveyard_cards(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_target_graveyard_cards_into_library", {
        "count_max": int(m.group("n")),
    })]


#: Living Death family — "[each player returns / you return / return] all
#: [or each] creature card[s] from [their / your / its owner's] graveyard
#: to the battlefield [or their/your hand]". A mass, untargeted recursion
#: over every matching graveyard card (`ReturnFromGraveyardEffect.players`
#: = ``"you"`` / ``"each_player"``). Deliberately only the plain creature-
#: card shape both branches of a will-of-the-council vote and the classic
#: reanimation sweeps use — Magister of Worth (its grace branch), Empty
#: the Catacombs, Storm of Souls, Finale of Eternity. Riders on the
#: returned cards (a -1/-1 counter, "each is a 1/1 Spirit") stay
#: fail-closed.
#: PAR-143 widened the type word from "creature" to the graveyard type vocabulary ("return all land
#: cards from your graveyard to the battlefield tapped", Aftermath Analyst, Lumra) and added the
#: tapped entry; `ReturnFromGraveyardEffect` filters by the kind's own type predicate.
_MASS_RETURN_GRAVEYARD_RE = compile_clause(
    r"(?:(?P<each>each player returns)|you return|return) "
    rf"(?:all|each) (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?cards? from "
    r"(?:their|your|its owner'?s|(?P<all>all)) graveyards? to "
    r"(?P<dest>the battlefield|their hand|your hand)(?P<tapped> tapped)?"
    # "…from all graveyards to the battlefield under their owners' control" (Open the Vaults): every player's own cards.
    r"(?P<owners> under their owners'? control)?"
)


def _mass_return_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dest = m.group("dest")
    kind = graveyard_target_kind(m.groupdict().get("type"), "your")
    if kind is None or (m.group("tapped") and dest != "the battlefield"):
        return None
    params: dict = {
        "target_kind": kind,
        "destination": "battlefield" if dest == "the battlefield" else "hand",
        "players": "each_player" if m.group("each") or m.group("all") else "you",
    }
    if m.group("owners") and not m.group("all"):
        return None
    if m.group("all") and not m.group("owners"):
        return None  # "all graveyards" without "under their owners' control" would be under the caster's
    if m.group("tapped"):
        params["tapped"] = True
    return [EffectSpec("return_from_graveyard", params)]


#: PAR-143: "[you may] return a `<type>` card [with mana value N or less] from your graveyard to the
#: battlefield [tapped] / your hand" and "put a `<type>` card from a graveyard onto the battlefield
#: [tapped] under your control" (Blossoming Tortoise, Deeproot Wayfinder, Soul of Windgrace) — the
#: untargeted pick: no "target", so the controller chooses at resolution (`ReturnFromGraveyardEffect.pick`).
_RETURN_PICK_FROM_GRAVEYARD_RE = compile_clause(
    r"(?P<may>you may )?(?:"
    rf"return an? (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?card"
    rf"(?: with mana value (?P<mv>\d+) or less)? from (?P<scope>{GRAVEYARD_SCOPE_WORD}) graveyard to "
    r"(?P<dest>the battlefield|your hand)(?P<tapped> tapped)?"
    # RULE 614.1c: "…to the battlefield with a +1/+1 counter on it" — the counters follow the picked card.
    rf"(?: with (?P<ewc_n>a|an|\d+|x)(?: additional)? (?P<ewc_kind>-1/-1|\+1/\+1|{'|'.join(KEYWORD_COUNTER_KINDS)}) counters? on it)?"
    r"|"
    rf"put an? (?:(?P<type2>{GRAVEYARD_TYPE_WORD}) )?card from (?P<scope2>{GRAVEYARD_SCOPE_WORD}) graveyard "
    r"onto the battlefield(?P<tapped2> tapped)? under your control)"
)


def _return_pick_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    groups = m.groupdict()
    put = groups.get("scope2") is not None
    kind = graveyard_target_kind(
        groups["type2"] if put else groups.get("type"), groups["scope2"] if put else groups["scope"],
    )
    if kind is None:
        return None
    destination = "battlefield" if put or groups["dest"] == "the battlefield" else "hand"
    tapped = bool(groups.get("tapped2") if put else groups.get("tapped"))
    if tapped and destination != "battlefield":
        return None
    params: dict = {"target_kind": kind, "destination": destination, "pick": True}
    if groups.get("may"):
        params["optional"] = True
    if tapped:
        params["tapped"] = True
    if put:
        params["under_your_control"] = True
    if groups.get("mv") is not None:
        params["max_mana_value"] = int(groups["mv"])
    if groups.get("ewc_kind"):
        if destination != "battlefield":
            return None
        # The counters belong to the card the controller picked, so they ride its pick (`then_effects` run on it).
        params["then_effects"] = [{"type": "add_counters", "params": {
            "count": count_or_x_of(groups["ewc_n"]), "kind": groups["ewc_kind"], "previous_subject": True,
        }}]
    return [EffectSpec("return_from_graveyard", params)]


#: "exile [up to one] target [type] card from [scope] graveyard" (RULE
#: 701.5a) — the Deathrite Shaman/Scavenging Ooze/Lion Sash graveyard-hate
#: family; almost always "a graveyard" in practice, but the same scope
#: vocabulary applies. The `UP_TO_ONE` prefix (RULE 115.1a — PAR-18's own
#: "exile up to 1 target creature card from a graveyard[. create a token
#: that's a copy of that card]" antecedent, Ardyn/Anikthea-shaped) reuses
#: `_optional_param`/`target_is_optional` the same way every other
#: `{TARGET}`-bearing handler does, even though this clause hand-rolls its
#: own "target" grammar instead of embedding `TARGET` (the graveyard scope/
#: type vocabulary predates that macro and has its own word lists).
#: The determiner is ``target`` for the RULE 115 form (Deathrite Shaman) or a
#: bare ``a``/``an`` for the untargeted reanimator-cycle antecedent ("you may
#: exile a creature card from your graveyard. Create a token that's a copy of
#: that card." — God-Pharaoh's Gift/Séance); both resolve to the same
#: `graveyard_*` `EffectSpec`, the "target" nuance (redirect/"can't be
#: targeted") being immaterial for a graveyard-card pick this grammar models.
_EXILE_FROM_GRAVEYARD_RE = compile_clause(
    rf"exile (?P<up_to_one>{UP_TO_ONE})(?:target |an? )"
    rf"(?:(?P<colors>{_COLOR_WORD_LIST_INNER}) )?"
    # PAR-153: a creature-subtype adjective ("target Assassin creature card", Altaïr Ibn-La'Ahad).
    r"(?:(?P<sub>[a-z-]+) (?=creature card))?"
    rf"(?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?card(?P<cycling> with a cycling ability)?"
    # PAR-153: "…creature card **with lesser power** from your graveyard" (Gyrus) — less than the source's power.
    r"(?P<lesser> with lesser power)? from "
    rf"(?P<scope>{GRAVEYARD_SCOPE_WORD}) graveyard"
    # PAR-153: "…from your graveyard **with a memory counter on it**" — the card is exiled carrying it.
    r"(?: with an? (?P<ckind>[a-z]+) counter on it)?"
)


def _exile_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    if m.groupdict().get("cycling"):
        # PAR-163 (Rooting Moloch): "card with a cycling ability" -- only the untyped card pool carries that filter.
        if m.groupdict().get("type"):
            return None
        kind = kind.removesuffix("_card") + "_card_with_cycling"
    params: dict = {"target_kind": kind, **optional_param(m)}
    #: "exile target red, white, or black creature card from your graveyard"
    #: (Offspring's Revenge) — `TargetSpec.colors`' OR narrowing on a
    #: graveyard-card target, the N-colour sibling of `_exile_target_two_color`.
    colors = _color_word_list(m.groupdict().get("colors"))
    if colors:
        params["colors"] = colors
    elif m.groupdict().get("colors"):
        return None  # a colour list we couldn't resolve — fail closed
    creature_filter: dict = {}
    if m.groupdict().get("sub"):

        sub = m.group("sub").lower()
        if sub not in SUBTYPES or sub in NONCREATURE_SUBTYPE_WORDS or m.groupdict().get("type") != "creature":
            return None
        creature_filter["subtype"] = sub.capitalize()
    if m.groupdict().get("lesser"):
        if m.groupdict().get("type") != "creature":
            return None  # only a creature card has the power to compare
        creature_filter["power_vs_reference"] = "less"
    if creature_filter:
        params["creature_filter"] = creature_filter
    if m.groupdict().get("ckind"):
        params["exile_counters"] = {m.group("ckind").lower(): 1}
    return [EffectSpec("exile", params)]


#: "Exile N cards from your graveyard." is a mandatory resolve-time choice,
#: distinct from the targeted one-card grammar above. Number words have
#: already been converted to digits by oracle normalization.
_EXILE_OWN_GRAVEYARD_CARDS_RE = compile_clause(
    r"exile (?P<count>\d+) cards? from your graveyard"
)


def _exile_own_graveyard_cards(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile_own_graveyard_cards", {"count": int(m.group("count"))})]


#: "exile target player's graveyard." (Bojuka Bog) / "exile all cards from
#: target player's graveyard." (Tormod's Crypt) — a whole *graveyard*
#: targeted by player, not a single card from one (`_EXILE_FROM_GRAVEYARD_RE`
#: above) — the two phrasings are the same effect, so one builder claims both.
_EXILE_TARGET_GRAVEYARD_RE = compile_clause(
    r"exile (?:all cards from )?target player'?s graveyard"
)


def _exile_target_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("exile_target_graveyard", {"target_kind": "player"})]


_EXILE_TRIGGER_CONTROLLER_GRAVEYARD_RE = compile_clause(
    r"exile (?:all cards from )?(?:its|(?:that|the) (?:creature|permanent)'?s) controller'?s graveyard"
)


def _exile_trigger_controller_graveyard(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile_target_graveyard", {"player_from_trigger_event": True})]


#: "exile all creatures with power 5 or greater until ~ leaves the battlefield." / "exile each nonland permanent with mana
#: value 2 or less until ~ leaves …" (Aligned Hedron Network, Consulate Crackdown, Temporary Lockdown): the plain mass
#: exile, read by the shared "exile all/each" rows, with the linked-return flags the targeted form carries.
_EXILE_ALL_UNTIL_LEAVES_RE = compile_clause(r"(?P<head>exile (?:all|each) .+?) until ~ leaves the battlefield")


def _exile_all_until_leaves(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    specs = match_clause(m.group("head"))
    if not specs or len(specs) != 1 or specs[0].type != "exile":
        return None
    params = specs[0].params
    if params.get("selector") is None and params.get("group") is None:
        return None  # only the untargeted mass exile has a linked set to return
    return [EffectSpec("exile", {**params, "until_source_leaves": True})]


#: "…tap up to 2 target creatures. Put a stun counter on **each of them**."
#: (Out Cold, Homesickness, Donatello — PAR-128) — the plural pronoun of
#: `tap_and_stun`'s "on it": every object the preceding clause chose
#: (`AddCountersEffect.previous_group`). Only the counter kinds whose engine
#: reader is known (+1/+1, -1/-1, stun — RULE 122.1c).
_ADD_COUNTERS_PREVIOUS_GROUP_RE = compile_clause(
    r"put (?P<n>an?|\d+) (?P<ckind>\+1/\+1|-1/-1|−1/−1|stun) counters? on "
    r"(?:each of them|each of those creatures|those creatures)(?P<scope> you don't control)?"
)


def _add_counters_previous_group(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "kind": counter_sign(m.group("ckind")) if m.group("ckind") != "stun" else "stun",
        "count": count_of(m.group("n")), "previous_subject": True, "previous_group": True,
    }
    if m.group("scope"):
        # "tap X target creatures. Put a stun counter on each of those creatures you don't
        # control." (Lost in the Maze) — the earlier clause's targets, narrowed by controller.
        params["previous_group_scope"] = "not_you"
    return [EffectSpec("add_counters", params)]


def _add_counters_previous_selector(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """`_add_counters_previous_group`'s sibling for a preceding *mass selector*
    ("tap all creatures your opponents control, then put a stun counter on each of
    those creatures" — Monstrosity of the Lake)."""
    if m.group("scope"):
        return None  # a mass selector is replayed by name; it can't carry a controller narrowing
    [spec] = _add_counters_previous_group(m)
    params = {k: v for k, v in spec.params.items() if k not in ("previous_subject", "previous_group")}
    return [EffectSpec("add_counters", {**params, "previous_selector": True})]


#: PAR-152 (Meandering Towershell, Noctis, Heir Apparent): "Exile `<it>`. Return it to the battlefield under
#: `<your|its owner's>` control tapped and attacking at the beginning of the declare attackers step on your next turn /
#: of that player's next declare attackers step. [It can't be blocked that combat.]" — an exile now plus a RULE 603.7
#: delayed return (`return_specific_to_battlefield`, which puts the exiled card into the combat that is starting,
#: RULE 508.4) armed on the source itself.
_EXILE_RETURN_AT_DECLARE_ATTACKERS_RE = compile_clause(
    rf"exile (?:{re.escape(SELF)}|it)\. return (?:{re.escape(SELF)}|it) to the battlefield under "
    r"(?P<who>your|its owner'?s) control tapped and attacking at the beginning of "
    r"(?:the declare attackers step on your next turn|that player'?s next declare attackers step)"
    r"(?P<unblockable>\. it can'?t be blocked that combat)?"
)


def _exile_return_at_declare_attackers(m: re.Match[str]) -> list[EffectSpec]:
    inner: list[dict] = [{"type": "return_specific_to_battlefield", "params": {
        "tapped": True, "attacking": True, "under_your_control": m.group("who") == "your",
    }}]
    if m.group("unblockable"):
        inner.append({"type": "grant_until", "params": {
            "target_kind": None, "self_subject": True, "duration": "end_of_combat",
            "static": {"type": "grant_keyword", "params": {"keywords": ["cant_be_blocked"]}},
        }})
    return [
        EffectSpec("exile", {"target_kind": None}),
        EffectSpec("create_delayed_trigger", {
            "step": "declare_attackers", "scope": "controller",
            "min_turn_offset": 1 if m.group("who") == "your" else 0,
            "step_player": "owner" if m.group("who") != "your" else None, "capture": "self",
            "effects": inner,
        }),
    ]


#: PAR-152 (Doors of Durin): "Until your next turn, it gains trample if you control a Dwarf and hexproof if you
#: control an Elf." — the duration leads, and each keyword has its own "if you control a `<subtype>`" condition
#: (RULE 611.2 / 608.2: checked as the instruction resolves). It reads as one gated `grant_until` per keyword, the
#: shape "it gains `<kw>` until your next turn if `<condition>`" already produces.
_UNTIL_NEXT_TURN_CONDITIONAL_GAINS_RE = compile_clause(
    r"until your next turn, it gains (?P<kw1>[a-z ]+?) (?P<c1>if you control an? [a-z]+)"
    r"(?: and (?P<kw2>[a-z ]+?) (?P<c2>if you control an? [a-z]+))?"
)


def _until_next_turn_conditional_gains(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    specs: list[EffectSpec] = []
    for kw, cond in ((m.group("kw1"), m.group("c1")), (m.group("kw2"), m.group("c2"))):
        if kw is None:
            continue
        part = parse_effect_body(f"it gains {kw} until your next turn {cond}", previous_subject=True)
        if not part or len(part) != 1 or part[0].type != "grant_until" or part[0].condition is None:
            return None
        specs.extend(part)
    return specs


ROWS: list[EffectHandler] = [
    # "tap target <c1> or <c2> creature[ an opponent controls]" (Tidebinder
    # Mage) — colour-list tap; tried before the plain `tap` row (its
    # "<c> or <c>" prefix isn't a TARGET row).
    EffectHandler(
        "tap_two_color",
        _TAP_TWO_COLOR_RE,
        _tap_two_color,
    ),
    # "you may tap or untap target permanent/creature" (Derevi, Empyrial
    # Tactician; Ghostly Touch's quoted attached-creature grant; Teller of
    # Tales' "creature"-scoped sibling, PAR-74). This is one target chosen
    # under RULE 115, followed by the resolution-time tap/untap choice
    # represented by TapEffect.choose_tap_or_untap -- not two independently
    # optional effects.
    EffectHandler(
        "tap_or_untap",
        compile_clause(r"(?:you may )?tap or untap target (?P<kind>permanent|creature)"),
        lambda m: [EffectSpec("tap", {
            "target_kind": m.group("kind"),
            "choose_tap_or_untap": True,
        })],
    ),
    # "…then put a stun counter on each of those creatures." after a mass selector.
    EffectHandler(
        "add_counters_previous_selector",
        _ADD_COUNTERS_PREVIOUS_GROUP_RE,
        _add_counters_previous_selector,
        previous_selector_only=True,
    ),
    # "Put a stun counter on each of them." after a multi-target clause.
    EffectHandler(
        "add_counters_previous_group",
        _ADD_COUNTERS_PREVIOUS_GROUP_RE,
        _add_counters_previous_group,
        previous_subject_only=True,
    ),
    # "tap [up to one] target creature[ an opponent controls] and put a stun
    # counter on it." (Champions of the Shoal, Alchemax Slayer-Bots,
    # Constrictor Sage &c. — PAR-30, a ~30-card SOLO cluster). One clause,
    # two effects: the tap, then a stun counter on the same creature
    # (`AddCountersEffect.previous_subject`). RULE 122.1c's skip-untap
    # replacement is enforced engine-side in `RulesEngine.set_tapped`.
    # Above the plain `tap` row so the trailing "and put a stun counter…"
    # isn't dropped.
    EffectHandler(
        "tap_and_stun",
        compile_clause(
            r"(?P<verb>tap) (?:up to (?:one|1) )?target creature"
            r"(?P<yc> an opponent controls| you don't control)? "
            r"and put a stun counter on it"
        ),
        lambda m: [
            EffectSpec("tap", {
                "target_kind": (
                    "creature_you_dont_control" if m.group("yc") else "creature"
                ),
                "optional": bool(re.search(r"up to (?:one|1)", m.group(0))),
            }),
            EffectSpec("add_counters", {
                "kind": "stun", "amount": 1, "previous_subject": True,
            }),
        ],
    ),
    EffectHandler(
        "exile_trigger_referent",
        _EXILE_TRIGGER_REFERENT_RE,
        _exile_trigger_referent,
        self_subject_only=True,
    ),
    # "tap target creature" / "untap target permanent"
    EffectHandler(
        "tap",
        compile_clause(rf"(?P<verb>tap|untap) {TARGET}"),
        _tap,
    ),
    # "tap two target creatures" / "untap up to two target lands" (RULE
    # 115.1a generalized to N>=2, Snap-shaped).
    EffectHandler(
        "tap_multi_target",
        compile_clause(rf"(?P<verb>tap|untap) {MULTI_TARGET_QUANTIFIER_X}(?:other )?(?P<target>{MULTI_TARGET_ALT})"),
        _tap_multi_target,
    ),
    # "tap 1 or 2 target creatures without horsemanship." (MEC-87, Broken
    # Dam-shaped).
    EffectHandler(
        "tap_multi_target_keyword_filter",
        _TAP_MULTI_TARGET_KEYWORD_FILTER_RE,
        _tap_multi_target_keyword_filter,
    ),
    # "tap all creatures your opponents control" / "tap all nonwhite creatures" /
    # "tap all artifacts" (Bond of Discipline, Blinding Light, Metal Fatigue —
    # PAR-128) — the general mass form: the group is whatever the shared noun-
    # phrase grammar reads (`parse_count_phrase`), carried as a structured
    # selector `TapEffect` resolves through `group_selector_objects`. Primary over the
    # named tap rows (PAR-169), which keep only what it declines.
    EffectHandler(
        "tap_all_group",
        compile_clause(r"(?P<verb>tap|untap) all (?P<group>[a-z' -]+?)"),
        _tap_all_group,
    ),
    EffectHandler("tap_all_player_group", _TAP_ALL_PLAYER_GROUP_RE, _tap_all_player_group, fallback_for=("tap_all_group",)),
    # "untap all attacking creatures" / "untap each attacking creature"
    # (Karlach, Fury of Avernus/Hexplate Wallbreaker) — tried above `tap_self`
    # too, same "specific mass phrase before the bare pronoun row" ordering.
    EffectHandler(
        "tap_attacking_creatures",
        compile_clause(r"(?P<verb>tap|untap) (?:all attacking creatures|each attacking creature)"),
        _tap_attacking_creatures,
        fallback_for=("tap_all_group",),
    ),
    # "untap all creatures you control" (Village Bell-Ringer) / "untap all
    # other creatures you control" (Ahn-Crop Champion/Combat Celebrant's
    # own exert rider) / "untap each other creature you control" (Copperhorn
    # Scout) — must sit above `tap_self`/the bare `_SELF_SUBJECT` row so
    # "all [other] creatures you control" (not a self-reference) is
    # recognised on its own.
    EffectHandler(
        "tap_selector",
        compile_clause(
            r"(?P<verb>tap|untap) (?:all (?P<other_all>other )?creatures you control"
            r"|each (?P<other_each>other) creature you control)"
        ),
        _tap_selector,
        fallback_for=("tap_all_group",),
    ),
    # "Untap it and all Samurai you control." (Godo, Bandit Warlord) — tried
    # before `tap_self` since that row's bare `_SELF_SUBJECT` would consume
    # only "it" and leave "and all Samurai you control" unclaimed.
    EffectHandler("tap_self_and_subtype", _TAP_SELF_AND_SUBTYPE_RE, _tap_self_and_subtype),
    # "untap this creature" / "untap ~" / "tap it" — the self form (Devoted
    # Druid's "Put a -1/-1 counter on this creature: Untap this creature.").
    EffectHandler(
        "tap_self",
        compile_clause(rf"(?P<verb>tap|untap) {SELF_SUBJECT}"),
        _tap_self,
    ),
    # "untap that creature" (Finest Hour, MEC-28) — only offered from a
    # group-subject trigger body, where "that creature" unambiguously means
    # whichever creature matched the trigger.
    EffectHandler(
        "tap_group_subject",
        _TAP_GROUP_SUBJECT_RE,
        _tap_self,
        group_subject_only=True,
    ),
    # "tap enchanted creature" / "untap enchanted creature" (Freed from the
    # Real/Pemmin's Aura-shaped Aura activated abilities).
    EffectHandler(
        "tap_attached",
        compile_clause(rf"(?P<verb>tap|untap) {ATTACHED_SUBJECT}"),
        _tap_attached,
    ),
    # "Exile enchanted creature." (Spiral into Solitude — an Aura's own
    # `{cost}, Blight N, Sacrifice ~:` removal body). `ExileEffect`'s
    # ``attached_permanent`` self-acting mode, no RULE 115 target.
    EffectHandler(
        "exile_attached",
        compile_clause(rf"exile {ATTACHED_SUBJECT}"),
        lambda m: [EffectSpec("exile", {"target_kind": "attached_permanent"})],
    ),
    # "Return ~ to its owner's hand." (RULE 701.3, self form) — before the
    # targeted sibling below, whose `TARGET` grammar has no ``~``
    # alternative to compete with but would otherwise have first claim on
    # the surrounding phrase.
    EffectHandler(
        # "return **this card** to its owner's hand" (Ringskipper — a
        # "when ~ dies" clash-win body, so the source is in the graveyard;
        # `RulesEngine.return_to_hand` moves it from whatever zone it's in).
        # Scoped here rather than widening the shared `_SELF_SUBJECT` macro.
        "return_self_to_hand",
        compile_clause(rf"return (?:{SELF_SUBJECT}|this card) to its owner's hand"),
        _return_self_to_hand,
    ),
    # "return ~ and target <c1> or <c2> creature[ you control] to their
    # owner's hand" (Snow Hound) — compound self+target bounce; before the
    # colour-list and plain rows (its "return ~ and target …" would else be
    # left unclaimed).
    EffectHandler("return_self_and_another", _RETURN_SELF_AND_ANOTHER_RE, _return_self_and_another),
    EffectHandler(
        "return_self_and_two_color",
        _RETURN_SELF_AND_TWO_COLOR_RE,
        _return_self_and_two_color,
    ),
    # "return target <c1> or <c2> creature[ you control] to its owner's
    # hand" (Escape Routes) — colour-list bounce; tried before the plain
    # `return_to_hand` row (its "<c> or <c>" prefix isn't a TARGET row).
    EffectHandler(
        "return_to_hand_two_color",
        _RETURN_TO_HAND_TWO_COLOR_RE,
        _return_to_hand_two_color,
    ),
    # "return target creature to its owner's hand" / "return a land you
    # control to its owner's hand" (RULE 701.3 — the bounce family).
    EffectHandler(
        "return_to_hand",
        compile_clause(rf"return {TARGET} to its owner's hand"),
        _return_to_hand,
    ),
    # "put target <c1> or <c2> creature on top of its owner's library"
    # (Hunting Drake) — colour-list tempo bounce.
    EffectHandler(
        "return_to_library_two_color",
        _RETURN_TO_LIBRARY_TWO_COLOR_RE,
        _return_to_library_two_color,
    ),
    # "put target creature on top/the bottom of its owner's library" (RULE
    # 701.3 — Time Ebb/Griptide-shaped tempo bounce).
    EffectHandler(
        "return_to_library",
        compile_clause(rf"put {TARGET} {_LIBRARY_PLACEMENT}"),
        _return_to_library,
    ),
    EffectHandler("owner_puts_top_or_bottom", _OWNER_PUTS_TOP_OR_BOTTOM_RE, _owner_puts_top_or_bottom),
    EffectHandler("controller_puts_top_or_bottom", _CONTROLLER_PUTS_TOP_OR_BOTTOM_RE, _controller_puts_top_or_bottom),
    EffectHandler(
        "controller_may_put_self_top_or_bottom", _CONTROLLER_MAY_PUT_SELF_TOP_OR_BOTTOM_RE,
        _controller_may_put_self_top_or_bottom, self_subject_only=True,
    ),
    # "put ~ / it … on the bottom of / third from the top of its owner's library" (self form).
    EffectHandler("return_self_to_library", _RETURN_SELF_TO_LIBRARY_RE, _return_self_to_library),
    EffectHandler("put_self_graveyard_top", _PUT_SELF_GRAVEYARD_TOP_RE, _put_self_graveyard_top),
    EffectHandler("return_attached_to_library", _RETURN_ATTACHED_TO_LIBRARY_RE, _return_attached_to_library),
    EffectHandler("exile_all_until_leaves", _EXILE_ALL_UNTIL_LEAVES_RE, _exile_all_until_leaves),
    EffectHandler(
        "return_it_to_library", _RETURN_IT_TO_LIBRARY_RE, _return_self_to_library, self_subject_only=True,
    ),
    # "Put target card from a graveyard on the bottom of its owner's
    # library." (PAR-83 — Junktroller/Chrome Companion).  Its target is a
    # card in any graveyard, not the battlefield target the generic tempo-
    # bounce row directly above accepts.
    EffectHandler(
        "graveyard_card_to_library_bottom",
        _GRAVEYARD_CARD_TO_LIBRARY_BOTTOM_RE,
        _graveyard_card_to_library_bottom,
    ),
    # PAR-128: "return all creatures to their owners' hands" — after `return_all_nonland`.
    EffectHandler("return_group", _RETURN_GROUP_RE, _return_group),
    # "return all nonland permanents with mana value X or less to their
    # owners' hands." (Displacement Wave).
    EffectHandler(
        "return_all_nonland",
        _RETURN_ALL_NONLAND_RE,
        _return_all_nonland,
        fallback_for=("return_group",),
    ),
    EffectHandler("put_group_on_bottom", _PUT_GROUP_ON_BOTTOM_RE, _put_group_on_bottom),
    # "return two target creatures to their owners' hands" (RULE 115.1a
    # generalized to N>=2) — the plural sibling of `return_to_hand`.
    EffectHandler(
        "return_to_hand_multi_target",
        compile_clause(rf"return {MULTI_TARGET_QUANTIFIER_X}(?:other )?(?P<target>{MULTI_TARGET_ALT}) to (?:their owners'?|their owner'?s?) hands?"),
        _return_to_hand_multi_target,
    ),
    # "Return those creatures to their owners' hands." (PAR-1, Run Away
    # Together) — the indirect-referent sibling of `return_to_hand_multi_
    # target`; only offered when a preceding "choose N target creatures …"
    # clause actually announced the group (`EffectHandler.
    # previous_subject_only`, `_choose_targets_group`).
    EffectHandler(
        "return_previous_group", _RETURN_PREVIOUS_GROUP_RE, _return_previous_group,
        previous_subject_only=True,
    ),
    # "return target <c1> or <c2> creature card from [scope] graveyard to
    # [dest]" (Crypt Angel) — colour-list graveyard recursion; tried
    # before the plain row (its "<c> or <c>" prefix isn't a TARGET row).
    EffectHandler(
        "return_from_graveyard_two_color",
        _RETURN_FROM_GRAVEYARD_TWO_COLOR_RE,
        _return_from_graveyard_two_color,
    ),
    # "return target [type] card from [scope] graveyard to the
    # battlefield/your hand/its owner's hand" / "put target [type] card
    # from [scope] graveyard onto the battlefield under its owner's
    # control" (RULE 701.3, the Regrowth/Reanimate/Deathrite-adjacent
    # recursion family — own/any/opponent graveyard scope).
    EffectHandler(
        "return_from_graveyard",
        _RETURN_FROM_GRAVEYARD_RE,
        _return_from_graveyard,
    ),
    # Living Death family — "each player returns / you return all creature
    # cards from [their/your] graveyard to the battlefield / hand" — a
    # mass, untargeted recursion (`ReturnFromGraveyardEffect.players`).
    EffectHandler(
        "mass_return_graveyard",
        _MASS_RETURN_GRAVEYARD_RE,
        _mass_return_graveyard,
    ),
    # PAR-162: "put [up to one] target `<type>` card from your graveyard on top of your library" and its plural / pick siblings.
    EffectHandler("put_graveyard_card_top", _PUT_GRAVEYARD_CARD_TOP_RE, _put_graveyard_card_top),
    EffectHandler("put_graveyard_cards_top", _PUT_GRAVEYARD_CARDS_TOP_RE, _put_graveyard_cards_top),
    EffectHandler("put_graveyard_pick_top", _PUT_GRAVEYARD_PICK_TOP_RE, _put_graveyard_pick_top),
    EffectHandler(
        "return_pick_from_graveyard",
        _RETURN_PICK_FROM_GRAVEYARD_RE,
        _return_pick_from_graveyard,
    ),
    EffectHandler(
        "return_from_graveyard_owner_control",
        _PUT_FROM_GRAVEYARD_OWNER_CONTROL_RE,
        _return_from_graveyard,
    ),
    # "return up to two target creature cards from your graveyard to your
    # hand"/"...to the battlefield" (RULE 115.1a generalized to N>=2) — the
    # plural sibling of `return_from_graveyard`.
    # "return [up to] X target creature cards from your graveyard to your
    # hand / the battlefield" — the count is the spell's announced {X}
    # (`count_selector="source_x_paid"`). Tried before the numeric-N
    # plural handler (its `\d+` count can't match the "x" token anyway).
    EffectHandler(
        "return_from_graveyard_x",
        _RETURN_FROM_GRAVEYARD_X_RE,
        _return_from_graveyard_x,
    ),
    EffectHandler(
        "return_from_graveyard_multi_target",
        _RETURN_FROM_GRAVEYARD_MULTI_RE,
        _return_from_graveyard_multi_target,
    ),
    # "put target [type] card from [scope] graveyard onto the battlefield
    # under your control" (Reanimate/Rise from the Grave/Virtue of
    # Persistence) — a genuinely different effect from the two above: the
    # activating player takes control, not the card's owner.
    EffectHandler(
        "reanimate_under_your_control",
        _REANIMATE_UNDER_YOUR_CONTROL_RE,
        _reanimate_under_your_control,
    ),
    EffectHandler("choose_graveyard_return", _CHOOSE_GRAVEYARD_RETURN_RE, _choose_graveyard_return),
    EffectHandler(
        "exile_return_at_declare_attackers", _EXILE_RETURN_AT_DECLARE_ATTACKERS_RE,
        _exile_return_at_declare_attackers,
    ),
    EffectHandler(
        "it_gains_quoted_ability", _IT_GAINS_QUOTED_ABILITY_RE, _it_gains_quoted_ability, previous_subject_only=True,
    ),
    EffectHandler(
        "until_next_turn_conditional_gains", _UNTIL_NEXT_TURN_CONDITIONAL_GAINS_RE,
        _until_next_turn_conditional_gains,
    ),
    # "put 1, 2, or 3 target creature cards from graveyards onto the
    # battlefield under your control. each of them enters with an
    # additional -1/-1 counter on it." (Aberrant Return) — enumerated
    # RULE 601.2c range + whole-body enters-with rider.
    EffectHandler(
        "reanimate_multi_under_your_control",
        _REANIMATE_MULTI_UNDER_YOUR_CONTROL_RE,
        _reanimate_multi_under_your_control,
    ),
    # PAR-15's "any number of" graveyard-recursion siblings — new
    # destinations (library top / shuffle into library) rather than a new
    # targeting primitive.
    EffectHandler(
        "return_from_graveyard_top_any",
        _RETURN_FROM_GRAVEYARD_TOP_ANY_RE,
        _return_from_graveyard_top_any,
    ),
    EffectHandler(
        "return_from_graveyard_shuffle_any",
        _RETURN_FROM_GRAVEYARD_SHUFFLE_ANY_RE,
        _return_from_graveyard_shuffle_any,
    ),
    EffectHandler(
        "shuffle_target_graveyard_cards",
        _SHUFFLE_TARGET_GRAVEYARD_CARDS_RE,
        _shuffle_target_graveyard_cards,
    ),
    # "exile target [type] card from [scope] graveyard" (RULE 701.5a,
    # Deathrite Shaman/Scavenging Ooze/Lion Sash-shaped graveyard hate).
    EffectHandler(
        "exile_from_graveyard",
        _EXILE_FROM_GRAVEYARD_RE,
        _exile_from_graveyard,
    ),
    EffectHandler(
        "exile_graveyard_cards_multi",
        _EXILE_GRAVEYARD_CARDS_MULTI_RE,
        _exile_graveyard_cards_multi,
    ),
    EffectHandler(
        "exile_own_graveyard_cards",
        _EXILE_OWN_GRAVEYARD_CARDS_RE,
        _exile_own_graveyard_cards,
    ),
    # "exile target player's graveyard."/"exile all cards from target
    # player's graveyard." (Bojuka Bog/Tormod's Crypt-shaped whole-graveyard
    # hate, as opposed to a single card from one above).
    EffectHandler(
        "exile_target_graveyard",
        _EXILE_TARGET_GRAVEYARD_RE,
        _exile_target_graveyard,
    ),
    EffectHandler(
        "exile_trigger_controller_graveyard",
        _EXILE_TRIGGER_CONTROLLER_GRAVEYARD_RE, _exile_trigger_controller_graveyard,
        group_subject_only=True,
    ),
]
