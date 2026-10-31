"""`<object> loses all abilities` (PAR-214): the one-shot RULE 613.7f ability removal over the shared object phrase.

Only the singular operation lives here. A plural, group, pronoun or ``~`` operand reaches it through
`catalogue.object_phrase.object_phrase_specs`, which rewrites the operand to "target `<noun>`", asks the handler table for
this one-target row and composes the iteration/reference around its IR (PAR-210). The row parks the existing
`remove_all_abilities` static with `grant_until`, so the layer engine (RULE 613.1f, 613.7f) -- not the parser -- does the
removal; a "has base power and toughness N/M" rider on the same subject is a second static on the same chosen object.
"""

from __future__ import annotations

import re
from typing import Optional

from ..duration_phrase import FIXED_DURATION_PATTERN, FIXED_DURATIONS
from ..subtype_vocabulary import SUBTYPES
from ..subgrammars import (
    COLOR_LETTERS,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    target_is_optional,
    target_kind_allowed,
    target_quality_filter,
    TARGET,
)
from ...spec import EffectSpec
from .shared import compile_clause, EffectHandler

#: Kinds the layer-6 removal can address: permanents on the battlefield, never a player or a spell.
_LOSING_KINDS = (
    "creature", "permanent", "nonland_permanent", "artifact", "artifact_or_creature", "land", "enchantment",
    "creature_or_planeswalker", "planeswalker", "artifact_creature_or_planeswalker", "artifact_or_enchantment",
)
#: RULE 611.2c: an effect with no stated duration lasts for the rest of the game (what `game/durations.py` calls it).
_NO_DURATION = "rest_of_game"
#: RULE 611.2b: "for as long as ~ remains on the battlefield" is the `source_on_battlefield` condition of a
#: `for_as_long_as` duration (`game/static_conditions.py`).
_WHILE_SOURCE_ON_BATTLEFIELD = "for as long as ~ remains on the battlefield"

_COLOR_WORD = "|".join(sorted(COLOR_LETTERS, key=len, reverse=True))
#: "... and becomes a green Elk creature with base power and toughness 3/3": the colour(s), the creature type(s) and the
#: layer-7b base power/toughness all replace what the object had (RULE 205.1a, 613.1d-f). "creature" is optional
#: because the object already is one; the clause is only claimed for a creature subject (see `_loses_target`).
_BECOMES = (
    rf" and becomes an? (?P<colors>(?:colorless|(?:{_COLOR_WORD})(?: and (?:{_COLOR_WORD}))*) )?"
    r"(?P<kinds>[a-z]+(?: [a-z]+)?) with base power and toughness (?P<bp>\d+)/(?P<bt>\d+)"
)
_TAIL = (
    r"loses all abilities"
    rf"(?:(?P<pt> and has base power and toughness (?P<p>\d+)/(?P<t>\d+))|(?P<becomes>{_BECOMES}))?"
    rf"(?: (?P<dur>{FIXED_DURATION_PATTERN}|{_WHILE_SOURCE_ON_BATTLEFIELD}))?"
)
_LOSES_TARGET_RE = compile_clause(rf"{TARGET} {_TAIL}")
_LOSES_SELF_RE = compile_clause(rf"(?:~|this (?:creature|permanent|artifact|land|enchantment)) {_TAIL}")


def _statics(m: re.Match[str]) -> Optional[list[dict]]:
    statics = [{"type": "remove_all_abilities", "params": {}}]
    if m.group("pt"):
        # `pt_set` is the layer-7b base-power/toughness static the existing "has base power and toughness" row parks.
        statics.append({"type": "pt_set", "params": {
            "power": int(m.group("p")), "toughness": int(m.group("t")), "affects": "self"}})
    if m.group("becomes"):
        extra = _becomes_statics(m)
        if not extra:
            return None
        statics.extend(extra)
    return statics


def _becomes_statics(m: re.Match[str]) -> list[dict]:
    """The creature-type, colour and base-P/T statics of a "becomes a <colour> <Type> creature ..." tail."""
    words = m.group("kinds").lower().split()
    if words[-1] == "creature":
        words.pop()
    if not words or any(word not in SUBTYPES for word in words):
        return []  # an unknown word is never guessed to be a type
    colors = (m.group("colors") or "").lower().replace(" and ", " ").split()
    statics = [{"type": "type_change", "params": {
        "add_types": ["creature"], "set_subtypes": [word.capitalize() for word in words],
        "power": int(m.group("bp")), "toughness": int(m.group("bt")), "affects": "self"}}]
    if colors:
        statics.append({"type": "color_change", "params": {
            "colors": [] if colors == ["colorless"] else [COLOR_LETTERS[c] for c in colors], "set": True,
            "affects": "self"}})
    return statics


def _duration(m: re.Match[str]) -> tuple[str, Optional[dict]]:
    word = (m.group("dur") or "").lower()
    if word == _WHILE_SOURCE_ON_BATTLEFIELD:
        return "for_as_long_as", {"kind": "source_on_battlefield"}
    return (FIXED_DURATIONS[word] if word else _NO_DURATION), None


def _grant(m: re.Match[str], subject: dict) -> Optional[list[EffectSpec]]:
    statics = _statics(m)
    if statics is None:
        return None
    duration, condition = _duration(m)
    params = {"static": statics[0], "duration": duration, **subject}
    if len(statics) > 1:
        params["extra_statics"] = statics[1:]
    if condition:
        params["condition"] = condition
    return [EffectSpec("grant_until", params)]


def _loses_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _LOSING_KINDS):
        return None
    if m.group("becomes") and not target_kind_allowed(kind, ("creature",)):
        return None  # a non-creature would also lose its other card types (RULE 205.1a): not modeled, so refused
    # A union of three card types ("artifact, creature, or planeswalker") has no kind of its own and falls back to
    # the all-permanent pool, which would let enchantments and lands be chosen: refuse rather than widen.
    if "permanent" in (kind or "") and "permanent" not in m.group("target").lower():
        return None
    subject: dict = {"target_kind": kind}
    if target_is_optional(m):
        subject["optional"] = True
    narrowing = {**(resolve_target_creature_state_filter(m.group("target")) or {}),
                 **target_quality_filter(m.group("target"))}
    if narrowing:
        subject["creature_filter"] = narrowing
    return _grant(m, subject)


def _loses_self(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("becomes"):
        return None  # the source may be a noncreature permanent, which would lose its other card types as well
    return _grant(m, {"self_subject": True, "target_kind": None})


ROWS: list[EffectHandler] = [
    EffectHandler("loses_all_abilities_self", _LOSES_SELF_RE, _loses_self),
    EffectHandler("loses_all_abilities_target", _LOSES_TARGET_RE, _loses_target),
]
