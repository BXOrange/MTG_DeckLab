"""`<object> becomes <colour | land type | artifact creature | <colour> <subtype> with base P/T N/M>` (PAR-217).

One singular row over the shared object phrase: a plural, group, pronoun or ``~`` operand reaches it through
`catalogue.object_phrase.object_phrase_specs`, which rewrites the operand to "target `<noun>`" (PAR-210). The row parks
layered statics with `grant_until`, so the layer engine (RULE 613) -- not the parser -- does the work:

* RULE 613.1d (layer 4): ``type_change`` -- ``set_types`` (RULE 205.1a: the card types are *replaced*), ``add_types`` for
  "that's still a planeswalker", ``set_creature_types`` (RULE 205.3m: only the creature types are replaced) and
  ``set_land_types`` ("becomes an Island": only the land types, RULE 305.7 strips the rules text of a basic type).
* RULE 613.1e (layer 5): ``color_change``.
* RULE 613.1f (layer 6): ``remove_all_abilities`` / ``grant_keyword``.
* RULE 613.4b (layer 7b): ``pt_set`` -- "base power and toughness N/M" and "power and toughness each equal to its mana
  value" are *set* values with their own timestamp, not the animation seed a ``type_change`` P/T would be.

"The colour / basic land type of your choice" opens the existing ``choose_for_source`` choice (RULE 608.2d) and reads
the answer back through its ``$chosen_*`` placeholder, so the pick is frozen into the effect when it is created.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .....models.cards.creature_types import CREATURE_SUBTYPES
from .....models.cards.subtype_types import SUBTYPES_BY_CARD_TYPE
from ..duration_phrase import FIXED_DURATION_PATTERN, FIXED_DURATIONS
from ..static_handlers import flag_keywords_and_ward, quoted_ability_grant_effects_list
from ..subgrammars import (
    COLOR_LETTERS,
    count_or_x_of,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    target_is_optional,
    target_kind_allowed,
    target_quality_filter,
    TARGET,
)
from ...spec import CHOSEN_COLOR_SENTINEL, CHOSEN_COLORS_SENTINEL, CHOSEN_LAND_TYPE_SENTINEL, EffectSpec
from ..clause_reading import ClauseReading, REVEALED, REVEALED_REFERENT
from .shared import compile_clause, EffectHandler, ANY_NUMBER_TARGET_CAP

#: The reading under which a bare "it" is the ability's own source.
SELF_SUBJECT_READING = ClauseReading(self_subject=True)

#: RULE 611.2c: an effect with no stated duration lasts for the rest of the game (what `game/durations.py` calls it).
_NO_DURATION = "rest_of_game"
#: RULE 611.2b: "for as long as ~ remains on the battlefield" / "until ~ leaves the battlefield" is the
#: `source_on_battlefield` condition of a `for_as_long_as` duration (`game/static_conditions.py`).
_WHILE_SOURCE_ON_BATTLEFIELD = ("for as long as ~ remains on the battlefield", "until ~ leaves the battlefield")
#: RULE 305.6: the five basic land types, which are also the only land types this row names.
_BASIC_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")
#: RULE 205.2a card types a "becomes" body can name. Land and planeswalker are only ever retained ("that's still a
#: land"), never newly granted, so they are not offered as a body word.
_BODY_CARD_TYPES = ("artifact", "creature", "enchantment")
_RETAINED_TYPES = ("land", "planeswalker", "artifact", "enchantment", "creature")

#: Kinds a characteristic change can address: permanents on the battlefield, never a player or a spell.
_BECOMES_KINDS = (
    "creature", "permanent", "nonland_permanent", "artifact", "artifact_or_creature", "land", "enchantment",
    "noncreature_artifact", "noncreature_artifact_you_control", "vehicle", "token_you_control",
)
#: Targets the shared TARGET phrase has no kind for but `game/targeting.py` already answers.
_EXTRA_TARGETS: dict[str, str] = {
    "target noncreature artifact": "noncreature_artifact",
    "target noncreature artifact you control": "noncreature_artifact_you_control",
    "target vehicle": "vehicle",
    "target spell or permanent": "spell_or_permanent",
    "target spell": "spell",
    "target instant or sorcery spell": "spell",
}
_EXTRA_TARGET_ALT = "|".join(sorted((re.escape(t) for t in _EXTRA_TARGETS), key=len, reverse=True))
#: Kinds the land-type body can address: the subject has to be a land.
_LAND_KINDS = ("land",)

#: "all colors" (Scrapbasket) is every one of the five colours of RULE 105.1.
_ALL_COLORS = "all colors"
_COLOR_WORD = "|".join(sorted(COLOR_LETTERS, key=len, reverse=True))
_COLOR_LIST = rf"(?:{_COLOR_WORD})(?: and (?:{_COLOR_WORD}))*"
_DURATION = rf"{FIXED_DURATION_PATTERN}|{'|'.join(re.escape(w) for w in _WHILE_SOURCE_ON_BATTLEFIELD)}"

_KEYWORDS = r"[a-z0-9{},' ]+?"
_BODY = (
    rf"(?:(?P<colors>colorless|{_ALL_COLORS}|{_COLOR_LIST})"
    r"|the (?P<choice>color or colors|color|basic land type) of your choice"
    r"|(?P<art>an? )?(?P<legendary>legendary )?(?:(?P<lp>\d+|x)/(?P<lt>\d+|x) )?(?P<words>[a-z' -]+?)"
    r"(?: with (?:base )?power and toughness (?:(?P<bp>\d+|x)/(?P<bt>\d+|x)|(?P<each>each equal to its mana value)))?)"
    r"(?: named (?P<name_before>[a-z0-9', -]+?))?"
    # "... base power and toughness 8/8, flying, and first strike"
    r"(?P<ckw>,(?! loses)(?: [a-z ]+?,)+ and (?!gains|has|loses)[a-z ]+?)?"
    r"(?P<loses>,? (?:and )?loses all abilities)?"
    rf'(?: with (?:(?P<wkw>{_KEYWORDS})(?: and )?)?(?:"(?P<wability>[^\"]+)")?)?'
    r"(?P<addition> in addition to its other (?P<scope>types|colors and types|colors))?"
    rf'(?:,? and (?:gains|has) (?:(?P<kw>{_KEYWORDS})(?: and )?)?(?:"(?P<ability>[^\"]+)")?)?'
    rf"(?:,? (?:and )?loses (?P<losekw>{_KEYWORDS}))?"
    r"(?: named (?P<name>[a-z0-9', -]+?))?"
    rf"(?: that'?s still an? (?P<still>{'|'.join(_RETAINED_TYPES)}))?"
)
#: "vehicles you control become artifact creatures" -- a plural group with no quantifier, so the shared object phrase
#: (which wants "each" / "all") does not read it. Group -> the `affects` selector (and subtype) of its statics.
_GROUPS: dict[str, dict[str, Any]] = {
    "vehicles you control": {"affects": "permanents_you_control", "subtype": "vehicle"},
    "artifacts you control": {"affects": "artifacts_you_control"},
}
_SUBJECT = (
    rf"(?:(?P<may>you may have )?(?:{TARGET}|(?P<extra>{_EXTRA_TARGET_ALT})|(?P<own>~))|(?P<group>{'|'.join(_GROUPS)})|(?P<multi>1 or more target creatures))"
)
_BECOMES_RE = compile_clause(
    rf"(?:(?P<lead>{_DURATION}), )?{_SUBJECT} (?P<verb>becomes?) {_BODY}(?: (?P<dur>{_DURATION}))?"
    rf"(?:\. it'?s still an? (?P<still_sentence>{'|'.join(_RETAINED_TYPES)}))?"
)


def _creature_type(word: str) -> str:
    return "-".join(part.capitalize() for part in word.split("-"))


def _split_words(words: str) -> Optional[tuple[list[str], list[str], list[str]]]:
    """``(colours, card types, subtypes)`` of "[<colours>] [<creature types>] [<card types>]", else ``None``.

    An unknown word is never guessed to be a type, and a colour has to lead (English order)."""
    tokens = words.split()
    colors: list[str] = []
    while tokens and tokens[0] in COLOR_LETTERS:
        colors.append(tokens.pop(0))
        if len(tokens) > 1 and tokens[0] == "and" and tokens[1] in COLOR_LETTERS:
            tokens.pop(0)
    types: list[str] = []
    while tokens and tokens[-1] in _BODY_CARD_TYPES:
        types.insert(0, tokens.pop())
    allowed = set().union(*(SUBTYPES_BY_CARD_TYPE[t] for t in types)) if types else CREATURE_SUBTYPES
    if len(set(types)) != len(types) or any(t in COLOR_LETTERS or t not in allowed for t in tokens):
        return None
    return colors, types, tokens


def _color_static(colors: list[str]) -> dict:
    if colors == [_ALL_COLORS]:
        letters = sorted({COLOR_LETTERS[c] for c in COLOR_LETTERS})
    else:
        letters = [] if colors == ["colorless"] else [COLOR_LETTERS[c] for c in colors]
    return {"type": "color_change", "params": {"colors": letters, "set": True, "affects": "self"}}


def _duration(m: re.Match[str]) -> tuple[str, Optional[dict]]:
    word = (m.group("lead") or m.group("dur") or "").lower()
    if word in _WHILE_SOURCE_ON_BATTLEFIELD:
        return "for_as_long_as", {"kind": "source_on_battlefield"}
    return (FIXED_DURATIONS[word] if word else _NO_DURATION), None


def _pt_static(m: re.Match[str]) -> Optional[dict]:
    """The layer-7b ``pt_set`` of "base power and toughness N/M" / "N/M <type> creature" / "each equal to its mana value"."""
    if m.group("each"):
        return {"type": "pt_set", "params": {"pt_selector": "mana_value", "affects": "self"}}
    power, toughness = m.group("bp") or m.group("lp"), m.group("bt") or m.group("lt")
    if power is None:
        return None
    return {"type": "pt_set", "params": {
        "power": count_or_x_of(power), "toughness": count_or_x_of(toughness), "affects": "self"}}


def _statics(m: re.Match[str], kind: Optional[str]) -> Optional[list[dict]]:
    """The layered statics of one body, in the order their timestamps must follow (ability removal before any grant)."""
    statics: list[dict] = []
    name = m.group("name") or m.group("name_before")
    if name:
        statics.append({"type": "name_change", "params": {"name": name.title(), "affects": "self"}})
    if m.group("loses"):
        statics.append({"type": "remove_all_abilities", "params": {}})
    if m.group("colors"):
        statics.append(_color_static(m.group("colors").split(" and ")))
    elif m.group("words"):
        body_words = m.group("words")
        legendary = bool(m.group("legendary") or "legendary" in body_words.split())
        body_words = re.sub(r"\blegendary ", "", body_words)
        words = _split_words(body_words.removesuffix("s") if m.group("group") else body_words)
        if words is None:
            words = _land_type_words(m.group("words"))
            if (words is None or not target_kind_allowed(kind, _LAND_KINDS)
                    or any(m.group(key) for key in ("addition", "ckw", "wkw", "kw", "ability", "wability", "losekw"))):
                return None
            return [*statics, {"type": "type_change", "params": {
                "set_land_types": [w.capitalize() for w in words], "affects": "self"}}]
        colors, types, subtypes = words
        if not (colors or types or subtypes) or (m.group("lp") and "creature" not in types):
            return None
        type_params: dict[str, Any] = {"affects": "self"}
        retained = m.group("still") or m.group("still_sentence")
        addition = m.group("addition")
        if addition and (m.group("scope") == "colors" or bool(colors) != (m.group("scope") == "colors and types")):
            return None  # the colour words and the stated scope have to agree on what is added
        if types and (retained or addition or {"artifact", "creature"} <= set(types)):
            type_params["add_types"] = types  # RULE 205.1b: retained types and artifact-creature animation keep prior card types
        elif types:
            type_params["set_types"] = types  # RULE 205.1a: the card types are replaced
        if subtypes:
            names = [_creature_type(w) for w in subtypes]
            # RULE 205.1b: "in addition to its other types" adds the creature types, otherwise they replace the old ones.
            subtype_key = "set_creature_types" if all(w in CREATURE_SUBTYPES for w in subtypes) else "set_subtypes"
            type_params["add_subtypes" if (addition or retained) else subtype_key] = names
        pt = _pt_static(m)
        if "creature" in types and pt is None:
            # RULE 301.7: a Vehicle brought to life keeps its printed power and toughness.
            type_params["pt_selector"] = "vehicle"
        if legendary:
            type_params["legendary"] = True  # RULE 205.4a
        if len(type_params) > 1:
            statics.append({"type": "type_change", "params": type_params})
        if colors:
            color = _color_static(colors)
            color["params"]["set"] = not addition  # RULE 613.1e: "in addition to its other colors" adds the colour
            statics.append(color)
        if pt is not None:
            statics.append(pt)
    elif not m.group("loses"):
        return None
    for group in ("ckw", "wkw", "kw"):
        if m.group(group):
            resolved = flag_keywords_and_ward(m.group(group).lstrip(", "))
            if resolved is None:
                return None
            keywords, ward_cost = resolved
            statics.append({"type": "grant_keyword", "params": {
                "keywords": keywords, **({"ward_cost": ward_cost} if ward_cost else {}), "affects": "self"}})
    if m.group("losekw"):
        resolved = flag_keywords_and_ward(m.group("losekw"))
        if resolved is None or resolved[1]:
            return None
        statics.append({"type": "remove_keyword", "params": {"keywords": resolved[0], "affects": "self"}})
    for group in ("ability", "wability"):
        if m.group(group):
            grants = quoted_ability_grant_effects_list(m.group(group))
            if not grants:
                return None
            statics.extend(g.to_dict() for g in grants)
    return statics or None


def _land_type_words(words: str) -> Optional[list[str]]:
    tokens = words.split()
    return tokens if len(tokens) == 1 and tokens[0] in _BASIC_LAND_TYPES else None


def _subject(m: re.Match[str]) -> Optional[tuple[Optional[str], dict]]:
    """``(kind, grant_until subject params)`` of the operand, or ``None`` when it is not addressable."""
    if m.group("multi"):
        return "creature", {"target_kind": "creature", "count": 1, "count_max": ANY_NUMBER_TARGET_CAP}
    if m.group("group"):
        return None, {"target_kind": None, "lock_group": True}  # RULE 611.2c: only what is on the battlefield now
    if m.group("own"):
        return None, {"self_subject": True, "target_kind": None}
    if m.group("extra"):
        kind = _EXTRA_TARGETS[m.group("extra")]
        return kind, {"target_kind": kind, **({"spell_filter": {"card_types": ["instant", "sorcery"]}} if m.group("extra") == "target instant or sorcery spell" else {})}
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _BECOMES_KINDS):
        return None
    # A union of three card types has no kind of its own and falls back to the all-permanent pool: refuse rather than widen.
    if "permanent" in (kind or "") and "permanent" not in m.group("target").lower():
        return None
    subject: dict = {"target_kind": kind}
    if target_is_optional(m):
        subject["optional"] = True
    narrowing = {**(resolve_target_creature_state_filter(m.group("target")) or {}),
                 **target_quality_filter(m.group("target"))}
    if narrowing:
        subject["creature_filter"] = narrowing
    return kind, subject


def _choice(m: re.Match[str], kind: Optional[str]) -> Optional[tuple[str, dict]]:
    """``(choose_for_source kind, static)`` of "the colour / basic land type of your choice", else ``None``."""
    if any(m.group(key) for key in ("loses", "kw", "wkw", "ckw", "addition", "ability", "wability", "losekw", "name", "name_before")):
        return None
    if m.group("choice") in ("color", "color or colors"):
        if m.group("choice") == "color or colors":
            return "colors", {"type": "color_change", "params": {"colors": [CHOSEN_COLORS_SENTINEL], "set": True, "affects": "self"}}
        return "color", {"type": "color_change", "params": {
            "colors": [CHOSEN_COLOR_SENTINEL], "set": True, "affects": "self"}}
    if not target_kind_allowed(kind, _LAND_KINDS):
        return None
    return "basic_land_type", {"type": "type_change", "params": {
        "set_land_types": [CHOSEN_LAND_TYPE_SENTINEL], "affects": "self"}}


def _becomes(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("lead") and m.group("dur"):
        return None
    # Number agreement: "you may have ~ become" and a plural group take "become", every other subject "becomes".
    plural = bool(m.group("may") or m.group("group") or m.group("multi"))
    if plural != (m.group("verb") == "become") or (m.group("may") and not m.group("own")):
        return None
    if bool(m.group("art")) == bool(m.group("group")) and not (m.group("colors") or m.group("choice")):
        return None  # a singular body takes its article, a plural group's body (artifact creatures) has none
    if m.group("group") and (m.group("choice") or m.group("words") is None or not m.group("words").endswith("creatures")):
        return None
    found = _subject(m)
    if found is None:
        return None
    kind, subject = found
    if kind in ("spell", "spell_or_permanent") and not (m.group("colors") or m.group("choice") in ("color", "color or colors")):
        return None
    duration, condition = _duration(m)
    chosen = None
    if m.group("choice"):
        chosen = _choice(m, kind)
        if chosen is None:
            return None
        statics = [chosen[1]]
    else:
        statics = _statics(m, kind)
        if statics is None:
            return None
    if m.group("group"):
        for static in statics:
            static["params"].update(_GROUPS[m.group("group")])
    params: dict[str, Any] = {"static": statics[0], "duration": duration, **subject}
    if len(statics) > 1:
        params["extra_statics"] = statics[1:]
    if condition:
        params["condition"] = condition
    grant = EffectSpec("grant_until", params)
    if m.group("may"):
        return [EffectSpec("optional", {"effects": [grant.to_dict()]})]  # "you may have ~ become ..."
    if chosen is None:
        return [grant]
    # RULE 608.2d: the choice is made as the effect resolves; the tail reads it back through the placeholder.
    return [EffectSpec("choose_for_source", {"kind": chosen[0]}), EffectSpec("seq", {"effects": [grant.to_dict()]})]


#: RULE 303.4f / 305.1c: "it becomes an Aura with enchant creature" (Cloudform, Lightform, Rageform). The permanent gains
#: the Aura subtype for good (RULE 613.1d, layer 4) and the existing `become_aura` effect stamps its enchant restriction, which
#: every attachment reader (`_attachment_kind` / `_attachment_legal`) takes from the live object.
_BECOMES_AURA = r"becomes an aura with enchant (?P<quality>creature|artifact|land)"
_BECOMES_AURA_SELF_RE = compile_clause(rf"~ {_BECOMES_AURA}")
_BECOMES_AURA_PRONOUN_RE = compile_clause(rf"it {_BECOMES_AURA}")


def _becomes_aura(m: re.Match[str]) -> list[EffectSpec]:
    aura_subtype = {"type": "type_change", "params": {"add_subtypes": ["Aura"], "affects": "self"}}
    return [
        EffectSpec("grant_until", {"static": aura_subtype, "duration": _NO_DURATION, "self_subject": True,
                                   "target_kind": None}),
        EffectSpec("become_aura", {"quality": m.group("quality")}),
    ]


#: RULE 613.4b / 608.2h: "Until your next turn, ~'s base power becomes twice that card's power
#: and its base toughness becomes twice that card's toughness" (Amplifire). Both amounts are
#: measured before creating the continuous effect; the shared bind node retains the snapshot.
_MEASURED_RE = compile_clause(
    rf"(?:(?P<lead>{_DURATION}), )?~'s base power becomes (?P<pm>twice )?"
    r"(?P<donor>that card|that creature|~)'s power and its base toughness becomes "
    r"(?P<tm>twice )?(?P=donor)'s toughness"
    rf"(?: (?P<dur>{_DURATION}))?"
)


def _measured_pt(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    donor = m.group("donor")
    if donor == "~":
        referent = "self"
    elif donor == "that card":
        refs = reading.referents_of(REVEALED)
        if len(refs) != 1:
            return None
        referent = refs[0].noun
    elif reading.previous_subject:
        referent = "previous_subject"
    elif reading.group_subject:
        referent = "trigger_subject"
    else:
        return None
    if m.group("lead") and m.group("dur"):
        return None
    duration, condition = _duration(m)
    grant = EffectSpec("grant_until", {"target_kind": None, "self_subject": True,
        "duration": duration, **({"condition": condition} if condition else {}),
        "static": {"type": "pt_set", "params": {"power": "$becomes_p", "toughness": "$becomes_t"}}})
    inner = grant
    for stat, group in (("toughness", "tm"), ("power", "pm")):
        inner = EffectSpec("bind", {"name": "becomes_p" if stat == "power" else "becomes_t",
            "amount": {"kind": "characteristic", "characteristic": stat, "of": referent,
                       **({"multiply": 2} if m.group(group) else {})}, "effects": [inner.to_dict()]})
    return [inner]


_REVEAL_MEASURED_RE = compile_clause(
    r"reveal cards from the top of your library until you reveal an? (?P<type>creature|artifact|enchantment|land) card\. "
    r"(?P<body>.+)\. put the revealed cards on the bottom of your library in a random order"
)


def _reveal_measured(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    body = _MEASURED_RE.fullmatch(m.group("body"))
    if body is None:
        return None
    measured = _measured_pt(body, ClauseReading(referents=(REVEALED_REFERENT,)))
    if measured is None:
        return None
    return [EffectSpec("reveal_until", {"criteria": {"type": m.group("type")}, "count": 1,
        "hit_destination": "library_bottom_random", "rest_destination": "library_bottom_random"}), *measured]


ROWS: list[EffectHandler] = [
    EffectHandler("becomes_reveal_measured_pt", _REVEAL_MEASURED_RE, _reveal_measured),
    EffectHandler("becomes_measured_pt", _MEASURED_RE, _measured_pt, reading_aware=True),
    EffectHandler("becomes_characteristics", _BECOMES_RE, _becomes, fallback_for=(
        "animate_quoted_cda", "animate_self", "animate_self_leading_eot", "animate_target",
        "animate_target_base_pt_order", "animate_target_leading_eot", "becomes_in_addition",
    )),
    EffectHandler("becomes_aura_self", _BECOMES_AURA_SELF_RE, _becomes_aura),
    # "it" is the source only when the whole ability speaks about the source ("When ~ enters, it becomes ...").
    EffectHandler("becomes_aura_pronoun", _BECOMES_AURA_PRONOUN_RE, _becomes_aura, requires=SELF_SUBJECT_READING),
]
