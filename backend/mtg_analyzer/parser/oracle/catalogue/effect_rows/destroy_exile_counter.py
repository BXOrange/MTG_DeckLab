"""Destroy, regenerate, counter, mill, exile and sacrifice rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import re

from typing import Optional
from ..clause_hooks import parse_effect_body
from ..clause_reading import COUNTERED_REFERENT, ClauseReading
from ..static_handlers import quoted_ability_grant_effects, static_effect_specs
from ..subgrammars import (
    all_permanent_type_selector,
    CANT_BE_COUNTERED_RE,
    COLOR_LETTERS,
    COLOR_WORD_ALT,
    IF_COLOR_SUFFIX,
    PERMANENT_TYPE_WORDS,
    pluralize_permanent_type,
    resolve_color_word,
    resolve_spell_filter,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    SPELL_TARGET,
    TARGET,
    target_kind_allowed,
    THAT_PLAYER_TAIL,
)
from ...normalize import SELF
from ...spec import EffectSpec
from .shared import (
    ANY_NUMBER_TARGET_CAP,
    compile_clause,
    counter_sign,
    CREATURE_FILTER_KEYWORD_WORDS,
    CREATURE_FILTER_SCOPED,
    CREATURE_FILTER_SUFFIX,
    creature_quality_filter,
    damaged_creature_kind,
    DAMAGED_THIS_TURN_TAIL,
    EffectHandler,
    MASS_DESTROY_FILTER,
    mass_destroy_filter_dict,
    mass_group_params,
    MULTI_TARGET_ALT,
    MULTI_TARGET_DISTINCT_CONTROLLERS,
    multi_target_params,
    MULTI_TARGET_QUANTIFIER_X,
    optional_param,
    scoped_creature_kind,
    SELF_SUBJECT,
    SINGLE_TYPE_PERMANENT_KINDS,
    two_color_letters,
    UNLESS_COST,
)

#: "exile any number of target spells." (Mindbreak Trap) — a spell-kind
#: target row, deliberately *not* folded into the shared `_MULTI_TARGET_
#: ROWS`/`_MULTI_TARGET_ALT` every other multi-target family (destroy/
#: damage/tap/return_to_hand/…) also reads: "destroy target spells"/
#: "N damage to target spells" aren't real templates (you counter or exile
#: a spell, never destroy/damage one), so widening the shared alternation
#: would have let `destroy_multi_target` silently claim a nonsense clause
#: too (caught by `tests/test_multi_target.py`'s own unrecognized-phrase
#: regression test). Only `exile`'s own regex opts into this wider
#: alternation. Reuses the same `TargetSpec(kind="spell", …)` `CopyPermanentEffect`'s
#: "copy any number of target instant and/or sorcery spells" (Display of
#: Power) already exercises.
_MULTI_TARGET_ALT_WITH_SPELL = MULTI_TARGET_ALT + "|(?:target spells)"


def _destroy(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, (
        "creature", "attacking_or_blocking_creature", "permanent", "permanent_you_dont_control",
        # "destroy target nonland permanent [an opponent controls]"
        # (Binding the Old Gods' chapter I, Assassin's Trophy-adjacent) —
        # `targeting.legal_targets` has all three branches (RULE 115.1c).
        "nonland_permanent", "nonland_permanent_you_control",
        "nonland_permanent_you_dont_control",
        *SINGLE_TYPE_PERMANENT_KINDS,
    )):
        return None
    color = resolve_color_word(m.groupdict().get("cond_color"))
    params: dict = {"target_kind": kind, **optional_param(m)}
    if color:
        params["color"] = color
    # "destroy target tapped creature" (Assassinate-shaped) — `resolve_
    # target_kind` deliberately collapses "target attacking/blocking/
    # tapped/untapped creature" onto the bare "creature" kind (RULE 115's
    # own precision-loss convention); without this the qualifier is
    # silently dropped and the spell destroys *any* creature.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("destroy", params)]


#: "destroy target Equipment attached to it" — Shackles of Treachery's own
#: granted quoted trigger ("whenever this creature deals damage, …"), where
#: "it" is the granted-to creature, i.e. this ability's source
#: (`targeting.legal_targets`' new ``equipment_attached_to_source`` kind).
_DESTROY_EQUIPMENT_ATTACHED_TO_IT_RE = compile_clause(
    r"destroy target equipment attached to it"
)


def _destroy_equipment_attached_to_it(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("destroy", {"target_kind": "equipment_attached_to_source"})]


#: "flip ~" (RULE 710, the Kamigawa flip cards) — the source flips itself.
_FLIP_SELF_RE = compile_clause(rf"flip (?P<subject>{re.escape(SELF)}|it)")


def _flip_self(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    # RULE 608.2c: a condition naming the source supplies the antecedent of
    # "flip it" on the ki-counter cycle; other pronoun readings must decline.
    if m.group("subject") == "it" and not reading.self_subject:
        return None
    return [EffectSpec("flip", {"source_only": True})]


#: "destroy ~" — the source destroys itself (Sandals of Abdallah, PAR-154); no RULE 115 target.
_DESTROY_SELF_RE = compile_clause(rf"destroy {re.escape(SELF)}")


def _destroy_pronoun(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    # RULE 608.2c: a bound object pronoun introduces no new RULE 115 target.
    if reading.previous_subject:
        params = {"previous_subject": True}
    elif reading.attached_subject:
        params = {"target_kind": "attached_permanent"}
    elif reading.self_subject and m.group("object") == "it":
        params = {"source_only": True}
    else:
        return None
    return [EffectSpec("destroy", params)]


#: "destroy target Equipment" (Manriki-Gusari).  Equipment is an artifact
#: subtype rather than a card type, so it deliberately is not part of the
#: broad ``TARGET`` grammar used by the ordinary destroy row.  The targeting
#: layer already has the precise subtype predicate.
_DESTROY_EQUIPMENT_RE = compile_clause(rf"destroy target equipment(?P<that_player>{THAT_PLAYER_TAIL})?")


def _destroy_equipment(m: re.Match[str]) -> list[EffectSpec]:
    # PAR-130: "… that player controls" (Rustmouth Ogre's sibling Goblin
    # Gaveleer-shaped heads) — the trigger-scoped equipment pool.
    kind = "equipment_that_player_controls" if m.group("that_player") else "equipment"
    return [EffectSpec("destroy", {"target_kind": kind})]


#: "exile target `<c1>` or `<c2>` creature/permanent[ you don't control]"
#: (Celestial Purge) — `TargetSpec.colors`' OR narrowing, the
#: `_pump_target_two_color` / `_destroy_color_adj` sibling. The shared
#: `TARGET` macro's fixed rows have no colour slot, so a dedicated row.
#: The same color restriction reads "that's 1 or more colors" as any of
#: the five colors (Devourer of Destiny), independent of the noun or scope.
_EXILE_TARGET_TWO_COLOR_RE = compile_clause(
    rf"exile target (?:(?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) )?"
    rf"(?P<noun>creature|permanent)(?P<yc> (?:you don't control|an opponent controls))?"
    rf"(?P<that_player>{THAT_PLAYER_TAIL})?"
    r"(?P<colored> that'?s 1 or more colors)?"
)


def _exile_target_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # RULE 105.2: one or more colors is any WUBRG color, never color identity.
    # Require exactly one color reading, so bare/unrepresented counts decline.
    if bool(m.group("c1")) == bool(m.group("colored")):
        return None
    colors = list(COLOR_LETTERS.values()) if m.group("colored") else two_color_letters(m)
    if colors is None:
        return None
    noun = m.group("noun")
    kind = "permanent" if noun == "permanent" else "creature"
    if m.groupdict().get("yc"):
        kind = "permanent_you_dont_control" if noun == "permanent" else "creature_you_dont_control"
    elif m.groupdict().get("that_player"):
        kind = f"{kind}_that_player_controls"  # PAR-130
    return [EffectSpec("exile", {"target_kind": kind, "colors": colors})]


def _destroy_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "destroy target nonland permanent with mana value 3 or less"
    # (Abrupt Decay-shaped) — a target-offer-time mana-value cap
    # (`targeting.TargetSpec.max_mana_value`), tried before the plain
    # `_destroy` handler since it's a strict superset of that shape (the
    # trailing "with mana value N or less" clause `_destroy`'s own grammar
    # doesn't recognise). MEC-40: "nonland_permanent" was missing from this
    # tuple despite the docstring already naming Abrupt Decay by name — the
    # kind itself (`targeting.py`'s "nonland_permanent" branch) already
    # honours `max_mana_value`, so this was a plain oversight, not a missing
    # engine primitive.
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent", "nonland_permanent", *SINGLE_TYPE_PERMANENT_KINDS)):
        return None
    value = m.group("mv")
    return [EffectSpec("destroy", {"target_kind": kind, **optional_param(m), _mana_value_bound_key(m): "x" if value == "x" else int(value)})]


def _mana_value_bound_key(m: re.Match[str]) -> str:
    """"…with mana value N or less" is a ceiling, "…or greater" a floor (`TargetSpec.max_/min_mana_value`)."""
    return ("exact_mana_value" if not m.group("cmp") else
            "min_mana_value" if m.group("cmp") == "greater" else "max_mana_value")


def _exile_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # RULE 115.1: a mana-value bound composes with type and controller scope.
    phrase = m.group("target") + (m.group("tail_scope") or "")
    kind = resolve_target_kind(phrase)
    if not target_kind_allowed(kind, (
        "creature", "permanent", "nonland_permanent", *SINGLE_TYPE_PERMANENT_KINDS,
        "artifact_or_creature", "artifact_creature_or_enchantment",
    )):
        return None
    params = {"target_kind": kind, **optional_param(m), _mana_value_bound_key(m): int(m.group("mv"))}
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("exile", params)]


def _quality_filter_builder(effect_type: str):
    """`_destroy_creature_filter`/`_exile_creature_filter`'s shared body —
    they differ only in which `EffectSpec` type the resolved creature-quality
    filter (power/toughness/keyword) attaches to."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        filt = creature_quality_filter(m)
        kind = scoped_creature_kind(m)
        if filt is None or kind is None:
            return None
        return [EffectSpec(effect_type, {"target_kind": kind, "creature_filter": filt})]

    return build


_destroy_creature_filter = _quality_filter_builder("destroy")
_exile_creature_filter = _quality_filter_builder("exile")

#: PAR-104: "destroy|exile [up to 1] target artifact, enchantment, or creature with flying / power 4 or greater"
#: (Mutant Chain Reaction, Spider Food, Broken Wings, Return to the Earth, Shoot Down, Exorcise, Make Your Move,
#: Vivien Reid's -3, …) — the three-type pool with the quality on its *creature* members only
#: (`TargetFrame.creature_filter_creatures_only`: an artifact or enchantment needs no flying).
_ARTIFACT_ENCHANTMENT_OR_CREATURE_FILTER_RE = compile_clause(
    rf"(?P<verb>destroy|exile) (?P<up_to>up to 1 )?target artifact, enchantment, or creature {CREATURE_FILTER_SUFFIX}"
)


def _artifact_enchantment_or_creature_filter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    filt = creature_quality_filter(m)
    if filt is None:
        return None
    params: dict = {"target_kind": "artifact_creature_or_enchantment", "creature_filter": filt}
    if m.group("up_to"):
        params["optional"] = True
    return [EffectSpec(m.group("verb"), params)]
_DESTROY_DAMAGED_CREATURE_RE = compile_clause(
    rf"destroy target creature{DAMAGED_THIS_TURN_TAIL}(?P<no_regen>\. it can'?t be regenerated)?"
)


def _destroy_damaged_creature(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"target_kind": damaged_creature_kind(m), "creature_filter": {"damaged_this_turn": True}}
    if m.group("no_regen"):
        params["can_be_regenerated"] = False
    return [EffectSpec("destroy", params)]


#: "destroy target non<word> creature[, optionally 'It can't be
#: regenerated.']" (RULE 105's colour-hoser *negated* adjective form,
#: Doom Blade/Dark Banishing/Cast Down-shaped — the single most repeated
#: removal template in the cache). ``neg`` covers the five colour words
#: (`combat.matches_object_filter`'s new ``without_color``) plus
#: "artifact" (its pre-existing ``without_card_type`` — Go for the Throat's
#: own filter shape, previously only reachable by hand-authoring since
#: nothing recognized this phrasing from oracle text).
_NEG_CREATURE_FILTER_WORDS: dict[str, tuple[str, str]] = {
    "black": ("without_color", "B"), "blue": ("without_color", "U"),
    "white": ("without_color", "W"), "red": ("without_color", "R"),
    "green": ("without_color", "G"),
    "artifact": ("without_card_type", "artifact"),
}
_DESTROY_NON_CREATURE_RE = compile_clause(
    rf"destroy target (?P<land_or>land or )?(?P<tapped>tapped )?non(?P<neg>{'|'.join(_NEG_CREATURE_FILTER_WORDS)})"
    rf"(?:, non(?P<second_neg>{'|'.join(_NEG_CREATURE_FILTER_WORDS)}))? creature"
    rf"(?P<that_player>{THAT_PLAYER_TAIL})?"
    r"(?P<no_regen>\. it can'?t be regenerated)?"
)


def _destroy_non_creature(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    key, value = _NEG_CREATURE_FILTER_WORDS[m.group("neg")]
    # PAR-130: "… that player controls" (Tooth Collector-shaped heads) —
    # `gate._that_player_antecedent_ok` checks the trigger names that player.
    kind = "creature_that_player_controls" if m.group("that_player") else "creature"
    if m.group("land_or"):
        if m.group("that_player"):
            return None
        kind = "permanent"
    params: dict = {"target_kind": kind, "creature_filter": {key: value}}
    if m.group("tapped"):
        # PAR-165 (Stone Catapult): "tapped" composes with the negation, the same `tapped` filter key
        # "destroy target tapped creature" (King's Assassin) already uses.
        params["creature_filter"]["tapped"] = True
    # Terror/Shriekmaw's two independent negatives ("nonartifact,
    # nonblack") compose two already-supported target filters.  Do not accept
    # a duplicate filter key yet: no real card needs e.g. two colors here,
    # and silently choosing one would mis-model that future wording.
    if m.group("second_neg") is not None:
        second_key, second_value = _NEG_CREATURE_FILTER_WORDS[m.group("second_neg")]
        if second_key == key:
            return None
        params["creature_filter"][second_key] = second_value
    if m.group("land_or"):
        params["creature_filter"] = {"any_of": [
            {"card_type": "land"}, {"card_type": "creature", **params["creature_filter"]},
        ]}
    if m.group("no_regen"):
        params["can_be_regenerated"] = False
    return [EffectSpec("destroy", params)]


#: "destroy target [color] creature/permanent/artifact/enchantment/land"
#: (RULE 105's colour-hoser adjective form, Red Elemental Blast-shaped) — a
#: small dedicated noun list rather than a color slot spliced into the
#: shared `TARGET` macro's fixed rows (which many other handlers reuse
#: as-is); covers the same nouns `_destroy`'s plain `TARGET`-based match
#: already accepts. Tried before the plain `destroy` handler below — with
#: no colour word present it matches identically (same `target_kind`
#: mapping), so it never changes behaviour for an uncoloured clause.
#: RULE 115.1c: each single printed permanent type maps to its own narrow
#: target kind (`targeting.legal_targets` has a dedicated
#: artifact/enchantment/land branch that still honours `_color_ok`), exactly
#: as `_destroy`'s `resolve_target_kind` route does — so "destroy target
#: artifact" (Abrade's second mode) offers only artifacts, not every
#: permanent. This row used to collapse those three to "permanent"; once the
#: plain `_destroy` handler stopped doing that, this was the one place the
#: broad-pool bug still survived.
_DESTROY_COLOR_NOUN_KINDS: dict[str, str] = {
    "creature": "creature", "permanent": "permanent", "artifact": "artifact",
    "enchantment": "enchantment", "land": "land",
}
#: A two-colour adjective list ("black or red") — `TargetSpec.colors`'
#: OR narrowing, the multi-letter sibling of the single ``color`` form
#: (Deathmark, Wallop). Only ever two colours on a real card in this shape.
_DESTROY_COLOR_ADJ_RE = compile_clause(
    rf"destroy target "
    rf"(?:(?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) |(?P<color>{COLOR_WORD_ALT}) )?"
    rf"(?P<noun>{'|'.join(_DESTROY_COLOR_NOUN_KINDS)})"
    rf"(?: with (?P<kw>{'|'.join(CREATURE_FILTER_KEYWORD_WORDS)}))?"
    # "…that's attacking or blocking" (Surge of Righteousness) — RULE 506.4
    # attacker / RULE 509.1 blocker status, a `creature_filter` boolean the
    # same offer-time way `attacking` already is.
    rf"(?: that'?s (?P<combat_state>attacking or blocking|attacking|blocking))?"
    + IF_COLOR_SUFFIX
)


def _destroy_color_adj(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    gd = m.groupdict()
    params: dict = {"target_kind": _DESTROY_COLOR_NOUN_KINDS[m.group("noun")]}
    if gd.get("c1") and gd.get("c2"):
        colors = two_color_letters(m)
        if colors is None:
            return None
        params["colors"] = colors
    else:
        color = resolve_color_word(gd.get("color")) or resolve_color_word(gd.get("cond_color"))
        if color:
            params["color"] = color
    kw = gd.get("kw")
    if kw:
        if params["target_kind"] != "creature":
            return None
        params["creature_filter"] = {"keyword": CREATURE_FILTER_KEYWORD_WORDS[kw]}
    combat_state = gd.get("combat_state")
    if combat_state:
        if params["target_kind"] != "creature":
            return None
        key = {
            "attacking or blocking": "attacking_or_blocking",
            "attacking": "attacking", "blocking": "blocking",
        }[combat_state]
        params.setdefault("creature_filter", {})[key] = True
    return [EffectSpec("destroy", params)]


def _multi_target_builder(effect_type: str, allow_spell: bool = False):
    """`_destroy_multi_target`/`_exile_multi_target`'s shared body — they
    differ only in the emitted `EffectSpec` type and whether "target spell"
    is a legal recipient (legal to exile a spell, RULE 701.20b, not to
    destroy one)."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        params = multi_target_params(m, allow_spell=allow_spell)
        if params is None:
            return None
        return [EffectSpec(effect_type, params)]

    return build


_destroy_multi_target = _multi_target_builder("destroy")


#: RULE 601.2c mass "destroy/exile all X [with a numeric filter]" board wipe
#: (Wrath of God/Damnation/Citywide Bust-shaped) — untargeted, the same
#: `selector` vocabulary `game/effects/core.py`'s `DestroyEffect`/`ExileEffect`
#: already support (previously only reachable via hand-authoring individual
#: cards in `card_catalogue`; this is the general oracle-text form).
#: Only the two numeric filter kinds `_mass_selector_objects` actually
#: implements are recognized here — "power N or greater" has no mass-form
#: engine support, so it's deliberately left unmatched (fail-closed) rather
#: than silently dropped.
#: Both keyed off the shared `PERMANENT_TYPE_WORDS` vocabulary
#: (`subgrammars.py`) rather than independently hand-typing the same
#: five-to-seven words twice, once per number — "destroy all nonland
#: permanents..."/"Destroy **each** nonland permanent..." (Culling Ritual,
#: MEC-40) both reach the same "all_nonland_permanents" selector
#: (`_mass_selector_objects`, built for `_return_all_nonland`'s bounce
#: sibling) this way for free.
_MASS_DESTROY_NOUNS: dict[str, str] = {
    pluralize_permanent_type(w): all_permanent_type_selector(w) for w in PERMANENT_TYPE_WORDS
}
#: "Destroy **each** artifact with mana value X or less." (Meltdown) —
#: the singular-noun/"each" phrasing of the same mass wipe, alongside the
#: far more common plural-noun/"all" one above; same selector targets, just
#: matched against a singular noun word.
_MASS_DESTROY_NOUNS_SINGULAR: dict[str, str] = {
    w: all_permanent_type_selector(w) for w in PERMANENT_TYPE_WORDS
}


_DESTROY_ALL_RE = compile_clause(
    rf"destroy (?:all (?P<noun>{'|'.join(_MASS_DESTROY_NOUNS)})"
    rf"|each (?P<noun_sg>{'|'.join(_MASS_DESTROY_NOUNS_SINGULAR)}))"
    rf"(?P<opp> your opponents control)?{MASS_DESTROY_FILTER}"
)

#: "Destroy all enchantments **your opponents control**." (Spring Cleaning)
#: — the opponent-scoped `_mass_selector_objects` sibling exists only for
#: artifacts/enchantments so far (no card needs "destroy all lands your
#: opponents control" &c. yet), so an ``opp`` scope on any other noun
#: fails closed.
_DESTROY_ALL_OPP_SELECTORS = {
    "all_enchantments": "opponents_enchantments",
    "all_artifacts": "opponents_artifacts",
    # PAR-128: "destroy all creatures your opponents control" (Dread Cacodemon) —
    # `opponents_creatures` already served Llawan's bounce.
    "all_creatures": "opponents_creatures",
}


def _destroy_all(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    noun = m.groupdict().get("noun")
    selector = _MASS_DESTROY_NOUNS[noun] if noun else _MASS_DESTROY_NOUNS_SINGULAR[m.group("noun_sg")]
    if m.groupdict().get("opp"):
        selector = _DESTROY_ALL_OPP_SELECTORS.get(selector)
        if selector is None:
            return None
    params: dict = {"selector": selector}
    filt = mass_destroy_filter_dict(m)
    if filt:
        params["filter"] = filt
    return [EffectSpec("destroy", params)]


#: "Destroy all other creatures." / "…all creatures other than ~" / "…all
#: creatures except [for] ~" — a self-excluding mass wipe (RULE 400's
#: "other"), reaching the new `all_other_creatures` /
#: `other_creatures_you_control` (`effects._mass_selector_objects`)
#: selectors. Whole-body match (both sentences, like
#: `_DESTROY_ALL_NO_REGEN_RE`) so an optional "they/those creatures can't
#: be regenerated" tail is claimed here rather than fail-closing the split.
#: Novablast Wurm, Mageta the Lion, Magister of Worth's vote branch.
_DESTROY_ALL_OTHER_RE = compile_clause(
    r"destroy all (?:other creatures(?P<you_control> you control)?"
    r"|creatures (?:other than|except(?: for)?) ~)"
    r"(?P<no_regen>\.? (?:those creatures|they) can'?t be regenerated)?"
)


def _destroy_all_other(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "selector": "other_creatures_you_control" if m.group("you_control")
        else "all_other_creatures",
    }
    if m.group("no_regen"):
        params["can_be_regenerated"] = False
    return [EffectSpec("destroy", params)]


#: "destroy/exile all `<group>`" / "…each `<group>`" (PAR-128) — the general mass form: the group
#: is whatever the shared noun-phrase grammar reads (`parse_count_phrase`), carried as
#: `DestroyEffect.group` / `ExileEffect.group`. Primary over the named-selector rows (PAR-169), which
#: stay as fallbacks for what this grammar declines (an X mana-value bound, "other than ~").
_MASS_GROUP_RE = compile_clause(
    r"(?P<verb>destroy|exile) (?P<quant>all|each) (?P<group>[a-z0-9' ,/+~-]+?)"
    r"(?P<no_regen>\.? (?:they|those [a-z ]+) can'?t be regenerated)?"
)


def _mass_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = mass_group_params(m.group("group"), m.group("quant"))
    if params is None:
        return None
    if m.group("no_regen"):
        if m.group("verb") != "destroy":
            return None
        params["can_be_regenerated"] = False
    return [EffectSpec(m.group("verb"), params)]


def _regenerate(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent")):
        return None
    return [EffectSpec("regenerate", {"target_kind": kind})]


def _regenerate_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("regenerate", {"target_kind": None})]


#: "regenerate enchanted creature" (RULE 701.16 / 303 — an Aura's own
#: activated ability regenerating its host: Regeneration / Gaea's Embrace /
#: Blessing of Leeches / Dark Privilege). No RULE 115 target — the host is
#: `RegenerateEffect`'s existing ``target_kind="attached_permanent"`` mode,
#: the same "act on whatever this Aura is attached to" resolution
#: `PumpEffect`/`GrantKeywordEffect`'s attached forms use.
_REGENERATE_ATTACHED_RE = compile_clause(r"regenerate (?:enchanted|equipped) creature")


def _regenerate_attached(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("regenerate", {"target_kind": "attached_permanent"})]


#: "Regenerate another target Elf." (Ezuri, Renegade Leader/Mad Auntie/
#: Baron Sengir-shaped) — a creature-subtype-filtered target. "another" is
#: cosmetic here: the plain ``"creature"`` target kind's own `legal_targets`
#: branch already excludes the ability's own source unconditionally (every
#: real card in this shape is an activated ability on a creature of the
#: named subtype, so it would otherwise be offered as its own legal
#: target) — the same reason a bare "target creature" ability doesn't need
#: an explicit "other" qualifier to stay off itself in this engine.
_REGENERATE_ANOTHER_TARGET_RE = compile_clause(r"regenerate another target (?P<subtype>[a-z]+)")
_REGENERATE_TARGET_SUBTYPE_RE = compile_clause(r"regenerate target (?P<subtype>[a-z]+)")


def _regenerate_another_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("regenerate", {
        "target_kind": "creature",
        "creature_filter": {"subtype": m.group("subtype").capitalize()},
    })]


def _regenerate_target_subtype(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subtype = m.group("subtype").lower()
    # The broader subtype grammar is tried before the ordinary target row;
    # main type nouns must fall through to that row, never become a fictional
    # creature subtype such as "Creature".
    if subtype in {"creature", "permanent"}:
        return None
    return [EffectSpec("regenerate", {
        "target_kind": "creature",
        "creature_filter": {"subtype": subtype.capitalize()},
    })]


def _counter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "counter target spell" / "… target noncreature spell" / "… target
    # instant or sorcery spell" / "… target spell with mana value N" — the
    # filter is extracted by the dedicated `SPELL_TARGET` companion grammar
    # (RULE 601.2c/115), not the generic TARGET rows (a countered spell's
    # "kind" is always "spell"; only *which* spells vary). "unless its
    # controller pays <cost>" (RULE 601 "Mana Leak" template) is an optional
    # tail on the same clause, independent of the filter.
    filt = resolve_spell_filter(m.group("target"))
    if filt is None:
        return None
    params: dict = dict(filt)
    if m.groupdict().get("cost"):
        # "pays twice {X}" (Thassa's Intervention) is two X symbols: `ManaCost.with_x` fills both.
        params["unless_pays"] = "{x}{x}" if m.group("cost") == "twice {x}" else m.group("cost")
        # "…pays {1} plus an additional {1} for each creature in your
        # party." (Concerted Defense, PAR-72) — `CounterSpellEffect.
        # unless_pays_extra_selector` adds one more generic to the fixed
        # base cost per point of `creatures_in_your_party` at resolution
        # time, read for the counter spell's own caster.
        if m.groupdict().get("party_tax"):
            params["unless_pays_extra_selector"] = "creatures_in_your_party"
        # "…unless its controller pays {1} for each card in your graveyard." (Circular Logic) — a
        # zero base plus one generic per card, the same extra-selector mechanism.
        if m.groupdict().get("graveyard_tax"):
            if m.group("cost") != "{1}":
                return None
            params["unless_pays"] = "{0}"
            params["unless_pays_extra_selector"] = "cards_in_your_graveyard"
    cond_color = resolve_color_word(m.groupdict().get("cond_color"))
    if cond_color:
        params["color"] = cond_color
    # "…unless its controller pays {4}. **If they do**, you incubate 2."
    # (Assimilate Essence) — a reflexive follow-up on the branch where the
    # target's controller pays (`CounterSpellEffect.on_pay_effect_specs`).
    # Only meaningful after an "unless … pays" cost; the sub-body is parsed
    # recursively and must fully claim, else fail closed.
    reflexive = m.groupdict().get("reflexive")
    if reflexive:
        if not m.groupdict().get("cost"):
            return None

        sub = parse_effect_body(reflexive)
        if not sub:
            return None
        params["on_pay_effect_specs"] = [s.to_dict() for s in sub]
    return [EffectSpec("counter", params)]


#: "Until end of turn, target creature gains '`<cost>`: `<effect>`.'"
#: (Retraction Helix-shaped, ~23 cache-wide cards on this template) — a
#: *resolve-time* grant of a full quoted ability (activated/triggered/
#: mana), unlike every other "gains `<keyword>` until end of turn" row
#: above (a bare flag keyword, no quotes). Reuses `static_handlers.
#: quoted_ability_grant_effects` (the Aura/Equipment quoted-grant parser,
#: already general over all three ability kinds) wrapped in `GrantUntil
#: Effect`'s existing ``duration="end_of_turn"`` resolve-time shape
#: instead of a standing layer-6 static.
_GRANT_QUOTED_ABILITY_UNTIL_EOT_RE = compile_clause(
    r"until end of turn, (?P<subject>target creature|[a-z ]+) gains? \"(?P<inner>.+)\""
)


def _grant_quoted_ability_until_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    if m.group("subject") != "target creature":
        grants = static_effect_specs(f'{m.group("subject")} have "{m.group("inner")}"')
        if not grants or any(s.type not in {"grant_triggered_ability", "grant_activated_ability",
                                           "grant_mana_ability"} for s in grants):
            return None
        return [EffectSpec("grant_until", {
            "static": grants[0].to_dict(), "extra_statics": [s.to_dict() for s in grants[1:]],
            "duration": "end_of_turn", "target_kind": None, "lock_group": True,
        })]
    grant = quoted_ability_grant_effects(m.group("inner"))
    if grant is None:
        return None
    return [EffectSpec("grant_until", {
        "static": {"type": grant.type, "params": grant.params},
        "duration": "end_of_turn",
        "target_kind": "creature",
    })]


def _cant_be_countered(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_be_countered", {})]


#: RULE 119.3's "can't gain life this turn" rider — "your opponents"
#: (Roiling Vortex's activated-ability effect) or "players" (Skullcrack /
#: Call In a Professional / Rain of Gore — a burn spell's own rider). The
#: bare, *permanent* "Players can't gain life." is a standing static
#: (`static_handlers._PLAYERS_CANT_GAIN_LIFE_RE` → `prevent_all_life_gain`).
_CANT_GAIN_LIFE_RE = compile_clause(r"(?P<who>your opponents|players) can'?t gain life this turn")


def _cant_gain_life(m: re.Match[str]) -> list[EffectSpec]:
    who = "all" if m.group("who").lower() == "players" else "opponents"
    return [EffectSpec("prevent_life_gain", {"recipient": who})]


def _change_target(m: re.Match[str]) -> list[EffectSpec]:
    # "…spell or ability…" always goes through `ChangeTargetEffect`'s
    # ``spell_or_ability`` branch (ENG-26's union stack-item lookup) rather
    # than folding "with a single target" into a spell-only filter — the
    # engine's own single-existing-target MVP limit already applies inside
    # that branch regardless of what's printed (see the effect's own
    # docstring), so the printed "with a single target" here is redundant
    # with, not narrower than, that limit.
    if m.group("kind") == "spell or ability":
        return [EffectSpec("change_target", {"spell_or_ability": True})]
    return [EffectSpec("change_target", {"single_target": True})]


#: PAR-71: "[you may ][have ]target player mill X cards, where X is that
#: spell's mana value." (Cloudhoof Kirin's spirit-or-arcane cast trigger) —
#: `MillEffect.count_from_trigger_event`'s ``mana_value`` reading, the same
#: `SPELL_CAST` event field `_pump_mana_value`/`_add_counters_spell_mv`
#: already use. RULE 601.2c's "have [player] mill" phrasing (rather than
#: bare "target player mills") doesn't change who does the milling —
#: `MillEffect` already only tracks the milled player, not who "had" it
#: happen — so the leading "have " is just consumed and dropped.
_MILL_SPELL_MV_RE = compile_clause(
    r"(?:have )?target (?P<who>player|opponent) mills? x cards?, where x is that spell'?s mana value"
)


def _mill_spell_mv(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {"target_kind": "player", "count_from_trigger_event": "mana_value"})]


#: PAR-82: "target player mills X cards, where X is ~'s power/toughness."
#: (Phenax, God of Deception's own granted ability) — `MillEffect.
#: count_selector`'s already-shipped ``"source_power"``/``"source_
#: toughness"`` reading (`continuous.count_selector`, evaluated against
#: this effect's own bound ``source`` — the granted-to creature, once
#: regranted per RULE 613.7f); a parser-recognition gap only.
_MILL_SOURCE_PT_RE = compile_clause(
    r"target (?P<who>player|opponent) mills? x cards?, where x is ~'?s (?P<pt>power|toughness)"
)


def _mill_source_pt(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {
        "target_kind": "player", "count_selector": f"source_{m.group('pt')}",
    })]


#: "target player mills half their library, rounded down." (Cut Your Losses, Traumatize, Kitsune's Technique,
#: Fleet Swallower) — `MillEffect.half`.
_MILL_HALF_RE = compile_clause(
    r"target (?P<who>player|opponent) mills half their library, rounded (?P<dir>down|up)"
)


def _mill_half(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {
        "target_kind": "opponent" if m.group("who") == "opponent" else "player", "half": m.group("dir"),
    })]


#: "defending player mills half their library, rounded up." (Terisian Mindbreaker) — `MillEffect`'s ``defending_player``
#: selector with the same ``half`` count.
_MILL_HALF_DEFENDING_RE = compile_clause(r"defending player mills half their library, rounded (?P<dir>down|up)")


def _mill_half_defending(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {"selector": "defending_player", "half": m.group("dir")})]


def _mill(m: re.Match[str]) -> list[EffectSpec]:
    # "you mill N" / bare "mill N" → self; "target player/opponent mills N" → targeted.
    who = (m.groupdict().get("who") or "").strip()
    count_word = m.group("n").lower()
    # "x" is the announced {X} (RULE 107.3c) or a ``bind``-measured X ("…mills x cards, where x is the result").
    params: dict = {"count": "twice_x" if count_word == "twice x" else "x" if count_word == "x" else 1 if count_word == "a" else int(count_word)}
    if who in ("target player", "target opponent"):
        params["target_kind"] = "opponent" if who == "target opponent" else "player"
    return [EffectSpec("mill", params)]


def _exile(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    # ``nonland_permanent`` ("exile target nonland permanent" — Excise the
    # Imperfect) is a real `targeting.legal_targets` kind (RULE 115.1c),
    # just never previously reachable from the plain exile handler.
    if not target_kind_allowed(kind, (
        "creature", "attacking_or_blocking_creature", "permanent", "nonland_permanent", *SINGLE_TYPE_PERMANENT_KINDS,
        "artifact_creature_or_enchantment",
    )):
        return None
    params: dict = {"target_kind": kind, **optional_param(m)}
    # See `_destroy`'s own comment: "exile target tapped creature" needs the
    # same qualifier `resolve_target_kind` alone discards.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("exile", params)]


#: "{1}{R}{G}, {T}: Exile ~ and target creature without flying that's attacking you." (Hunting Kavu,
#: Giant Trap Door Spider, Mangara of Corondor) — the source and one RULE 115 target, both exiled.
_EXILE_SELF_AND_TARGET_RE = compile_clause(rf"exile ~ and {TARGET}")


def _exile_self_and_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    target = _exile(m)
    return None if target is None else [EffectSpec("exile", {"target_kind": None}), *target]


_exile_multi_target = _multi_target_builder("exile", allow_spell=True)


#: "Sacrifice ~."/"Sacrifice this enchantment." (Dress Down/Underworld
#: Breach-shaped standing end-step self-sac) — the self form, no player
#: choice or RULE 115 target (RULE 701.17).
def _sacrifice_self(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    # "Whenever equipped creature deals combat damage to a player, you may sacrifice **it**." (Foot Chopper): under an
    # attached-permanent trigger the bare pronoun is the host, not the Equipment/Aura carrying the ability; there is no
    # host-sacrifice effect to emit, so the clause stays unclaimed instead of sacrificing the wrong object.
    if reading.attached_subject and re.fullmatch(r"sacrifice it", m.group(0).strip(), re.IGNORECASE):
        return None
    return [EffectSpec("sacrifice_self", {})]
#: "`<sacrifice | destroy | tap | exile>` ~ unless you pay `<cost>`" (RULE 118.3) — one
#: row over the leading verb instead of four near-identical ones (PAR-121): the four
#: differ only in which consequence the *unpaid* branch performs, which
#: `_SELF_CONSEQUENCE_UNLESS_PAY` maps. "Pay its mana cost" is a sacrifice-only cost.
_SELF_UNLESS_PAY_RE = compile_clause(
    rf"(?P<verb>sacrifice|destroy|tap|exile) {SELF_SUBJECT} unless you "
    rf"(?P<cost>{UNLESS_COST}|pay its mana cost)"
)

#: "Sacrifice this creature unless it attacked this turn." (Instill Furor)
#: is a noninteractive condition, unlike the similarly worded payment form.
_SACRIFICE_UNLESS_ATTACKED_RE = compile_clause(
    rf"sacrifice {SELF_SUBJECT} unless it attacked this turn"
)


def _self_unless_pay(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    verb, cost = m.group("verb"), m.group("cost")
    if verb == "sacrifice":
        return [EffectSpec("sacrifice_unless_pay", {
            "cost": "source_mana_cost" if cost == "pay its mana cost" else cost,
        })]
    if cost == "pay its mana cost":
        return None  # only the sacrifice form has this cost
    if verb == "destroy":
        return [EffectSpec("destroy_unless_pay", {"cost": cost})]
    # tap / exile: paying costs the resource and nothing happens, else the source
    # is tapped / exiled (`pay_cost_then` with the consequence in ``else_effects``).
    consequence = (
        {"type": "tap", "params": {"target_kind": None}} if verb == "tap"
        else {"type": "exile", "params": {"target_kind": None}}
    )
    return [EffectSpec("pay_cost_then", {
        "cost": cost, "effects": [], "else_effects": [consequence],
    })]


#: PAR-117: Fade Away / Killing Wave.  This is leading, unscoped
#: per-creature iteration, unlike the parser's existing trailing "for each"
#: connective.  The outer iterator snapshots every creature; the normal
#: composition runtime then pauses for each controller's individual choice.
_EACH_CREATURE_SACRIFICES_UNLESS_RE = compile_clause(
    r"for each creature, its controller sacrifices "
    r"(?P<subject>a permanent of their choice|it) unless they "
    r"(?P<cost>pay \{1\}|pay x life)"
)


def _each_creature_sacrifices_unless(m: re.Match[str]) -> list[EffectSpec]:
    is_self = m.group("subject") == "it"
    cost: object = {"pay_life": "x"} if m.group("cost") == "pay x life" else "{1}"
    consequence = (
        {"type": "sacrifice_target", "params": {}}
        if is_self else
        {"type": "sacrifice_controller_permanent", "params": {"what": "permanent"}}
    )
    return [EffectSpec("for_each", {
        "over": {"selector": "all_creatures"},
        "effects": [{"type": "pay_cost_then", "params": {
            "cost": cost,
            "payer": "target_controller",
            "effects": [],
            "else_effects": [consequence],
        }}],
    })]


#: "Exile ~."/"Exile this card." (Teferi's Protection/Mnemonic Betrayal's
#: trailing self-exile) — the self form, `ExileEffect`'s `target_kind=None`.
def _exile_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {"target_kind": None})]


#: PAR-30 "Threaten … tails residue" — the *old two-sentence* O-Ring
#: templating's return half, printed as its own `LEAVES_BATTLEFIELD`
#: trigger line rather than folded into an "exile … until ~ leaves" clause
#: (Journey to Nowhere, Petravark, Slithery Stalker, Faceless Butcher &c.):
#: "return the exiled card[s] to the battlefield under its/their owner's
#: control." → `ReturnLinkedExileEffect`. `gate.parse_oracle`'s own
#: cross-line pass stamps ``remember=True`` onto the companion ETB exile so
#: `GameObject.linked_exile_id` is populated for this to read back.
#:
#: PAR-30: "return the exiled card to its owner's **hand**." is the Lorwyn
#: "Champion" cycle's return half (Champion of the Clachan &c.), paired with
#: a ``behold_exile`` additional cast cost (`segmenter.
#: _ADDITIONAL_COST_BEHOLD_EXILE_RE`) that stamps `linked_exile_id` itself —
#: `ReturnLinkedExileEffect(destination="hand")`.
_RETURN_EXILED_CARD_RE = compile_clause(
    r"return the exiled cards? to (?:"
    r"the battlefield under (?:its owner'?s|their owners'?) control"
    r"|(?P<hand>its owner'?s hand)"
    r")"
)


def _return_exiled_card(m: re.Match[str]) -> list[EffectSpec]:
    if m.groupdict().get("hand"):
        return [EffectSpec("return_linked_exile", {"destination": "hand"})]
    return [EffectSpec("return_linked_exile", {})]


#: PAR-30 "Threaten … tails residue" — Driftgloom Coyote's own O-Ring
#: after-tail: "if that creature had power N or less, put a +1/+1 counter
#: on ~." — the exiled creature (`GameContext.previous_targets`, read at a
#: documented simplification: its last-known power, the object is off the
#: battlefield by now) gates a self-counter (`ConditionalEffect`'s
#: `previous_target_power_at_most`).
_IF_PREV_POWER_SELF_COUNTER_RE = compile_clause(
    r"if (?:that creature|it) had power (?P<n>\d+) or less, "
    r"put a (?P<ck>\+1/\+1|-1/-1|−1/−1) counter on ~"
)


def _if_prev_power_self_counter(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": 1, "kind": counter_sign(m.group("ck")),
    }, condition={"previous_target_power_at_most": int(m.group("n"))})]


#: "counter up to two target spells." (Double Negative) / "counter up to four target spells and/or abilities."
#: (Katara's Reversal) -- RULE 701.5 over `CounterSpellEffect`'s ``target_count``; the "and/or abilities" pool is the
#: `spell_or_ability` target kind (Disallow's). Not folded into `_MULTI_TARGET_ALT`: "destroy target spells" is no
#: real template (see `_MULTI_TARGET_ALT_WITH_SPELL`).
_COUNTER_MULTI_RE = compile_clause(
    r"counter (?:(?P<any_number>any number of )|(?P<up_to>up to )?(?P<count>\d+) )"
    r"target (?P<what>spells and/or abilities|spells)"
)


def _counter_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("any_number"):
        count, optional = ANY_NUMBER_TARGET_CAP, True
    else:
        count, optional = int(m.group("count")), bool(m.group("up_to"))
    if count < 2:
        return None  # N=1 is the singular row's job
    params: dict = {
        "target_kind": "spell_or_ability" if "abilities" in m.group("what") else "spell",
        "target_count": count,
    }
    if optional:
        params["optional"] = True
    return [EffectSpec("counter", params)]


#: PAR-175 M4: "If that spell is countered this way, `<exile it | put it on top of its owner's library | put it into its
#: owner's hand>` instead of putting it into its owner's graveyard." (Dissipate, Memory Lapse, Remand, Syncopate ...) --
#: the replacement destination of the spell the preceding clause countered (RULE 701.5a, 614.1). Offered only right
#: after a counter (`ClauseReading.referents` has COUNTERED); the sequence folds it into that `counter` spec.
_COUNTERED_THIS_WAY_RE = compile_clause(
    r"if (?:that spell|it) is countered this way, (?:"
    r"(?P<exile>exile it instead of putting it into its owner's graveyard)"
    r"|(?P<top>put (?:it|that card) on top of its owner's library instead of into (?:that player's|its owner's) graveyard)"
    r"|(?P<hand>put (?:it|that card) into its owner's hand instead of into (?:that player's|its owner's) graveyard))"
)


def _countered_this_way(m: re.Match[str]) -> list[EffectSpec]:
    destination = "exile" if m.group("exile") else "library_top" if m.group("top") else "hand"
    return [EffectSpec("counter_destination", {"destination": destination})]


ROWS: list[EffectHandler] = [
    # "destroy target nonland permanent with mana value 3 or less"
    # (Abrupt Decay-shaped) — tried before the plain `destroy` handler
    # below (see `_destroy_mv`'s docstring for why it's safe to try first).
    EffectHandler(
        "destroy_mv",
        compile_clause(rf"destroy {TARGET} with mana value (?P<mv>\d+|x)(?: or (?P<cmp>less|greater))?"),
        _destroy_mv,
    ),
    # "exile target permanent with mana value 4 or greater" — the exile sibling of `destroy_mv`.
    EffectHandler(
        "exile_mv",
        compile_clause(rf"exile {TARGET} with mana value (?P<mv>\d+) or (?P<cmp>less|greater)(?P<tail_scope> an opponent controls| you don\'t control| you control)?"),
        _exile_mv,
    ),
    # "destroy target creature with power 4 or greater" / "…with flying"
    # (RULE 115/601.2c power/toughness/keyword quality filter) — tried
    # before the plain `destroy` handler below for the same reason as
    # `destroy_mv` (a strict superset of the bare "target creature" shape).
    EffectHandler(
        "destroy_creature_filter",
        compile_clause(rf"destroy target creature{CREATURE_FILTER_SCOPED}"),
        _destroy_creature_filter,
    ),
    EffectHandler("destroy_damaged_creature", _DESTROY_DAMAGED_CREATURE_RE, _destroy_damaged_creature),
    EffectHandler(
        "artifact_enchantment_or_creature_filter",
        _ARTIFACT_ENCHANTMENT_OR_CREATURE_FILTER_RE,
        _artifact_enchantment_or_creature_filter,
    ),
    # "destroy target creature" / "destroy target artifact" / "destroy
    # target permanent if it's blue" (the trailing-clause old-templating
    # colour variant, Pyroblast-shaped — see `IF_COLOR_SUFFIX`).
    EffectHandler(
        "destroy",
        compile_clause(rf"destroy {TARGET}" + IF_COLOR_SUFFIX),
        _destroy,
    ),
    # "destroy target nonblack creature[. It can't be regenerated.]"
    # (Doom Blade-shaped) — tried before the plain `destroy` handler for
    # the same "strict superset" reason as `destroy_mv`/
    # `destroy_creature_filter` just above.
    EffectHandler(
        "destroy_non_creature",
        _DESTROY_NON_CREATURE_RE,
        _destroy_non_creature,
        fallback_for=("destroy",),
    ),
    # "destroy target [color] creature/permanent/artifact/enchantment/land"
    # (RULE 105 colour-hoser adjective, Red Elemental Blast-shaped) — tried
    # before the plain `destroy` handler below (see `_DESTROY_COLOR_ADJ_RE`'s
    # docstring for why it's safe to try first).
    EffectHandler(
        "destroy_color_adj",
        _DESTROY_COLOR_ADJ_RE,
        _destroy_color_adj,
        fallback_for=("destroy",),
    ),
    # "destroy target Equipment attached to it" (Shackles of Treachery's
    # granted quoted trigger — "it" is the ability's own source).
    EffectHandler(
        "destroy_equipment_attached_to_it",
        _DESTROY_EQUIPMENT_ATTACHED_TO_IT_RE,
        _destroy_equipment_attached_to_it,
    ),
    # "…, flip ~." (Initiate of Blood and the other Kamigawa flip cards).
    EffectHandler("flip_self", _FLIP_SELF_RE, _flip_self, reading_aware=True),
    # "…, destroy ~." (Sandals of Abdallah's "when that creature dies this turn") — the ability's own source.
    EffectHandler(
        "destroy_self", _DESTROY_SELF_RE, lambda m: [EffectSpec("destroy", {"source_only": True})],
    ),
    EffectHandler(
        "destroy_pronoun", compile_clause(r"destroy (?P<object>it|that creature|that permanent|that artifact|that land)"),
        _destroy_pronoun, reading_aware=True,
    ),
    EffectHandler(
        "destroy_equipment",
        _DESTROY_EQUIPMENT_RE,
        _destroy_equipment,
    ),
    # "destroy two target creatures" / "destroy up to two target artifacts
    # and/or enchantments" (RULE 115.1a generalized to N>=2 — Curtains'
    # Call/Force of Vigor-shaped), optionally "… controlled by different
    # players" (Cloud's Limit Break-adjacent cross-target constraint —
    # `_MULTI_TARGET_DISTINCT_CONTROLLERS`).
    EffectHandler(
        "destroy_multi_target",
        compile_clause(
            rf"destroy {MULTI_TARGET_QUANTIFIER_X}(?P<target>{MULTI_TARGET_ALT})"
            rf"{MULTI_TARGET_DISTINCT_CONTROLLERS}"
        ),
        _destroy_multi_target,
    ),
    # "Regenerate another target Elf." (Ezuri, Renegade Leader/Mad Auntie/
    # Baron Sengir-shaped) — tried before the plain `regenerate` row below
    # since it's a strict superset of that shape.
    EffectHandler(
        "regenerate_another_target",
        _REGENERATE_ANOTHER_TARGET_RE,
        _regenerate_another_target,
    ),
    # "Regenerate target Sliver." (Crypt Sliver / Poultice Sliver) — the
    # same subtype-filtered target primitive as the "another target" form.
    EffectHandler(
        "regenerate_target_subtype",
        _REGENERATE_TARGET_SUBTYPE_RE,
        _regenerate_target_subtype,
    ),
    # "regenerate enchanted/equipped creature" — an Aura/Equipment's own
    # activated ability on its host (RULE 303), tried before the plain
    # `regenerate` row (whose `TARGET` grammar has no "enchanted creature"
    # entry anyway, so no overlap — ordered here for locality).
    EffectHandler(
        "regenerate_attached",
        _REGENERATE_ATTACHED_RE,
        _regenerate_attached,
    ),
    # "regenerate target creature" (RULE 701.16).
    EffectHandler(
        "regenerate",
        compile_clause(rf"regenerate {TARGET}"),
        _regenerate,
    ),
    # "regenerate ~" / "regenerate it" / "regenerate this creature" — the
    # *self* form (Broodhatch Nantuko/Thorn Elemental-shaped "{cost}:
    # Regenerate ~."), mirroring `tap_self`'s no-RULE-115-target shape.
    EffectHandler(
        "regenerate_self",
        compile_clause(rf"regenerate {SELF_SUBJECT}"),
        _regenerate_self,
    ),
    # "counter target spell" / "counter target noncreature spell" / "counter
    # target instant or sorcery spell" / "counter target spell with mana
    # value N" / "counter target creature or battle spell" / "counter target
    # blue spell" (RULE 105 colour-hoser adjective, inline via
    # `SPELL_TARGET`'s own ``color`` group) / any of those "… unless its
    # controller pays {N}" (the "Mana Leak" unless-pay template) — with an
    # optional reflexive "… If they do, `<effect>`." on the pay branch
    # (Assimilate Essence) — and/or "… if it's blue" (the trailing-clause
    # old-templating colour variant, Red Elemental Blast/Pyroblast-shaped).
    EffectHandler(
        "counter",
        compile_clause(
            rf"counter {SPELL_TARGET}"
            + r"(?: unless (?:its controller pays|they pay) (?P<cost>\{[^}]+\}|twice \{x\})"
            + r"(?P<party_tax> plus an additional \{1\} for each creature in your party)?"
            + r"(?P<graveyard_tax> for each card in your graveyard)?)?"
            + r"(?:\. if they do, (?P<reflexive>.+?))?\.?"
            + IF_COLOR_SUFFIX
        ),
        _counter,
    ),
    EffectHandler(
        "countered_this_way_destination", _COUNTERED_THIS_WAY_RE, _countered_this_way,
        requires=ClauseReading(referents=(COUNTERED_REFERENT,)),
    ),
    # PAR-150: "counter up to two target spells [and/or abilities]" (RULE 115.1a plural of the row above).
    EffectHandler("counter_multi_target", _COUNTER_MULTI_RE, _counter_multi),
    # "counter target spell, activated ability, or triggered ability." (Disallow, Voidslime, Deny the Witch) —
    # `TargetSpec` kind ``spell_or_ability`` (Deflecting Swat's union of the stack's spells and abilities).
    EffectHandler(
        "counter_spell_or_ability",
        compile_clause(r"counter target spell, activated ability, or triggered ability"),
        lambda m: [EffectSpec("counter", {"target_kind": "spell_or_ability"})],
    ),
    # RULE 701.6a / 602.1: Stifle's broad ability category and Bind's activated-only subset.
    EffectHandler(
        "counter_activated_or_triggered_ability",
        compile_clause(r"counter target activated(?P<triggered> or triggered)? ability"),
        lambda m: [EffectSpec("counter_ability", {} if m.group("triggered") else {"target_kind": "activated_ability"})],
    ),
    # "counter target instant spell, sorcery spell, activated ability, or triggered ability." (Sister of Silence) — the
    # same union with the spell half narrowed to the two card types.
    EffectHandler(
        "counter_typed_spell_or_ability",
        compile_clause(r"counter target instant spell, sorcery spell, activated ability, or triggered ability"),
        lambda m: [EffectSpec("counter", {"target_kind": "spell_or_ability", "card_types": ["instant", "sorcery"]})],
    ),
    # "this spell can't be countered." / "~ can't be countered." (RULE
    # 118-area) — a spell's own property, docked as a marker the counter
    # effect refuses to act on (`RulesEngine._is_cant_be_countered`).
    EffectHandler(
        "cant_be_countered",
        CANT_BE_COUNTERED_RE,
        _cant_be_countered,
    ),
    EffectHandler(
        "grant_quoted_ability_until_eot",
        _GRANT_QUOTED_ABILITY_UNTIL_EOT_RE,
        _grant_quoted_ability_until_eot,
    ),
    # RULE 119.3: "Your opponents can't gain life this turn." (Roiling
    # Vortex's activated-ability rider).
    EffectHandler(
        "cant_gain_life",
        _CANT_GAIN_LIFE_RE,
        _cant_gain_life,
    ),
    # "Change the target of target spell with a single target." (Deflection/
    # Shunt/Swerve-shaped) / "…target spell or ability with a single
    # target." (Bolt Bend/Redirect Lightning/Untimely Malfunction/
    # Willbender-shaped) — RULE 115.4/601.2c, the oracle-text front-end for
    # `ChangeTargetEffect`, previously only reachable by hand-authoring
    # (Misdirection/Deflecting Swat, `card_catalogue`) since no
    # generic handler had claimed the phrase.
    EffectHandler(
        "change_target",
        compile_clause(r"change the target of target (?P<kind>spell or ability|spell) with a single target"),
        _change_target,
    ),
    # "mill 3 cards" / "you mill 3 cards" / "target player mills a card"
    EffectHandler(
        "mill",
        compile_clause(r"(?:(?P<who>you|target player|target opponent) )?mills? (?P<n>\d+|a|x|twice x) cards?"),
        _mill,
    ),
    EffectHandler("mill_half", _MILL_HALF_RE, _mill_half),
    EffectHandler("mill_half_defending", _MILL_HALF_DEFENDING_RE, _mill_half_defending),
    EffectHandler("mill_spell_mv", _MILL_SPELL_MV_RE, _mill_spell_mv),
    EffectHandler("mill_source_pt", _MILL_SOURCE_PT_RE, _mill_source_pt),
    # "exile target creature with power 4 or greater" / "…with flying" —
    # tried before the plain `exile` handler below, same reasoning as
    # `destroy_creature_filter`.
    EffectHandler(
        "exile_creature_filter",
        compile_clause(rf"exile target creature{CREATURE_FILTER_SCOPED}"),
        _exile_creature_filter,
    ),
    # "exile target creature" / "exile target artifact"
    # "exile target <c1> or <c2> creature/permanent[ you don't control]"
    # (Celestial Purge) — `TargetSpec.colors` OR narrowing; a dedicated
    # row since the shared `TARGET` macro carries no colour slot. Tried
    # before the plain `exile` row (which its "<c> or <c>" prefix would
    # otherwise leave unclaimed).
    EffectHandler(
        "exile_target_two_color",
        _EXILE_TARGET_TWO_COLOR_RE,
        _exile_target_two_color,
    ),
    EffectHandler(
        "exile",
        compile_clause(rf"exile {TARGET}"),
        _exile,
    ),
    EffectHandler("exile_self_and_target", _EXILE_SELF_AND_TARGET_RE, _exile_self_and_target),
    # "exile another target creature/nonland permanent" (Faceless Butcher / old two-sentence O-Ring ETB) is
    # the plain `exile` row above: `TARGET` carries the "another" prefix itself (PAR-128), so a dedicated row
    # is a strict subset (PAR-121 audit) and was deleted.
    # "return the exiled card[s] to the battlefield under its/their owner's
    # control." — old two-sentence O-Ring's own LEAVES_BATTLEFIELD line
    # (Journey to Nowhere, Petravark, Faceless Butcher …).
    EffectHandler(
        "return_exiled_card",
        _RETURN_EXILED_CARD_RE,
        _return_exiled_card,
    ),
    # Driftgloom Coyote: "if that creature had power N or less, put a +1/+1
    # counter on ~." — an O-Ring exile clause's own conditional after-tail.
    EffectHandler(
        "if_prev_power_self_counter",
        _IF_PREV_POWER_SELF_COUNTER_RE,
        _if_prev_power_self_counter,
        requires=ClauseReading(previous_subject=True),
    ),
    # "exile two target creatures" / "exile up to two target artifacts" /
    # "exile any number of target spells" (Mindbreak Trap — the one row
    # `_MULTI_TARGET_ALT_WITH_SPELL` adds on top of the shared alternation)
    # (RULE 115.1a generalized to N>=2), optionally "… controlled by
    # different players" (Protector of the Wastes-shaped cross-target
    # constraint — `_MULTI_TARGET_DISTINCT_CONTROLLERS`).
    EffectHandler(
        "exile_multi_target",
        compile_clause(
            rf"exile {MULTI_TARGET_QUANTIFIER_X}(?P<target>{_MULTI_TARGET_ALT_WITH_SPELL})"
            rf"{MULTI_TARGET_DISTINCT_CONTROLLERS}"
        ),
        _exile_multi_target,
    ),
    # PAR-128: "destroy all white permanents" / "exile all artifacts and enchantments your
    # opponents control" — primary over `destroy_all`/`destroy_all_other` (PAR-169 fallbacks).
    EffectHandler("mass_group", _MASS_GROUP_RE, _mass_group),
    # "destroy all other creatures[ you control]" / "…creatures other than
    # ~" — the self-excluding wipe, before the plain `destroy_all` (whose
    # ``all creatures`` noun row would otherwise consume the prefix and
    # then fail the fullmatch on the trailing "other than ~").
    EffectHandler(
        "destroy_all_other",
        _DESTROY_ALL_OTHER_RE,
        _destroy_all_other,
        fallback_for=("mass_group",),
    ),
    # "destroy all creatures[.]" / "destroy all artifacts with mana value 3
    # or less." (RULE 601.2c untargeted mass board wipe — Damnation/Citywide
    # Bust-shaped; Wrath of God itself is hand-authored in
    # `card_catalogue`, this is the general oracle-text form).
    EffectHandler(
        "destroy_all",
        _DESTROY_ALL_RE,
        _destroy_all,
        fallback_for=("mass_group",),
    ),
    # "sacrifice/destroy/tap/exile ~ unless you pay <cost>" — one row over the
    # verb (PAR-121), registered *before* the plain `tap_self`/`exile_self`/
    # `sacrifice_self` handlers (whose regexes are a prefix of this one) so the
    # "unless you pay" half isn't silently dropped.
    EffectHandler(
        "self_unless_pay",
        _SELF_UNLESS_PAY_RE,
        _self_unless_pay,
    ),
    # "exile ~" / "exile this card" — the self form (Teferi's Protection/
    # Mnemonic Betrayal's trailing self-exile).
    EffectHandler(
        "exile_self",
        compile_clause(rf"exile {SELF_SUBJECT}"),
        _exile_self,
    ),
    EffectHandler(
        "each_creature_sacrifices_unless",
        _EACH_CREATURE_SACRIFICES_UNLESS_RE,
        _each_creature_sacrifices_unless,
    ),
    EffectHandler(
        "sacrifice_unless_attacked",
        _SACRIFICE_UNLESS_ATTACKED_RE,
        lambda m: [EffectSpec("sacrifice_unless_attacked", {})],
    ),
    # "sacrifice ~" / "sacrifice this enchantment" — the self form (Dress
    # Down/Underworld Breach's standing end-step self-sac).
    EffectHandler(
        "sacrifice_self",
        compile_clause(rf"sacrifice {SELF_SUBJECT}"),
        _sacrifice_self, reading_aware=True,
    ),
]
