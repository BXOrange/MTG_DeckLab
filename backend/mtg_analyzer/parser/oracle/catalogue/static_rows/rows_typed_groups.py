"""Composite standing statements over a typed group or the attached permanent (PAR-289 M4).

One predicate grammar, two subjects:

* a **group** subject read by the shared object grammar (`characteristic_phrase.parse_object_phrase`): "all
  permanents", "nonland permanents", "noncreature artifacts", "creatures you control with +1/+1 counters on them",
  "other creatures", "birds", "commander creatures you own" -- global unless the phrase names a controller;
* the **attached** subject ("enchanted creature", "equipped creature", ...), whose group is the permanent the Aura or
  Equipment is attached to (RULE 303.4 / 301.5).

The predicate is a ", and"-joined list of clauses, each a layer of its own (RULE 613):

* "gets +P/+T [for each <X>]" and "gets +X/+0, where X is <a live count>" -- layer 7d (`anthem`); references
  such as "other Skeletons" and "each of its colors" are measured for each affected member;
* "has/have base power and toughness P/T" (or "X/X, where X is <a live count>") and "has base toughness T" -- layer
  7b (`pt_set`);
* "is/are <types> in addition to its/their other [creature] types" -- layer 4 *adding* the types (RULE 205.1b), "is/are
  legendary" (RULE 205.4a) and, "is every creature type" (RULE 702.73a);
* "is/are <colour>" -- layer 5, replacing the colours (RULE 105.2c);
* "is a <colour> <creature type>" (attached subject only) -- the *replacing* statement, which drops the old creature
  types (RULE 205.3m) and colours;
* "has/have <keywords>" -- layer 6 `grant_keyword` (a parametric keyword the engine can grant rides
  ``parametric_keywords``), "has/have "<quoted ability>"", and "loses/lose <keywords>" -- `remove_keyword`.

Every clause carries the same ``affects`` selector, so each layer reads the same set of objects and an object that
stops matching (or whose source leaves) stops being affected. A clause the grammar cannot read fails the whole
statement closed; a half-modelled sentence is never emitted.

Pure regex + data; no ``game/`` imports.
"""

from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from ..characteristic_phrase import parse_object_phrase
from ..clause_primitives import split_keywords_with_parametric
from .....models.cards.creature_types import CREATURE_SUBTYPES
from ..count_phrase import parse_amount_phrase
from ..subgrammars import COLOR_LETTERS
from .combat_restrictions import ATTACHED_SUBJECT_PATTERN
from .granted_abilities import quoted_ability_grant_effects_list, type_addition_params
from .keyword_flags import flag_keywords, flag_keywords_and_ward
from .matcher_types import DECLINE, StaticContext, StaticResult
from .object_scope import group_selector, scoped_group_selector, singularize
from .rows_attached_transform import type_words
from .self_statics import for_each_count_selector

_ATTACHED = {"affects": "attached_permanent"}
#: A clause separator inside the predicate.
_SEPARATOR_RE = re.compile(r",? and |, ")
_VERB_AHEAD = r"(?:is|are|gets?|has|have|loses?|attacks?)"
#: A keyword list ends where the next clause starts ("has defender and loses flying", "has menace, and is a pirate").
_LIST_END = rf"(?=,? and {_VERB_AHEAD} |, {_VERB_AHEAD} |\Z)"
_COLOR_WORDS = "white|blue|black|red|green"
#: One type/colour word of a type list: never a verb that would open the next clause.
_WORD = rf"(?!{_VERB_AHEAD} )[a-z-]+"
#: "zombies", "black zombie", "clerics, rogues, warriors, and wizards".
_WORD_LIST = rf"{_WORD}(?:(?:,? and |, | ){_WORD})*?"

#: One predicate clause: (name, regex). Tried in order at the current position; the first to match wins.
_CLAUSES: tuple[tuple[str, "re.Pattern[str]"], ...] = tuple(
    (name, re.compile(pattern)) for name, pattern in (
        ("pump_each", rf"gets? (?P<p>[+-]\d+)/(?P<t>[+-]\d+) for each (?P<what>[a-z0-9+' ~,/-]+?){_LIST_END}"),
        ("pump", r"gets? (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"),
        ("pump_x", rf"gets? (?P<p>[+-](?:x|\d+))/(?P<t>[+-](?:x|\d+)), where x is (?P<what>[a-z' ]+?){_LIST_END}"),
        ("base_pt_x", rf"(?:has|have) base power and toughness x/x, where x is (?P<what>[a-z' ]+?){_LIST_END}"),
        ("base_pt", r"(?:has|have) base power and toughness (?P<bp>\d+)/(?P<bt>\d+)"),
        ("base_toughness", r"(?:has|have) base toughness (?P<bt>\d+)"),
        ("mana_value_pt", r"(?:has|have) base power and (?:base )?toughness each equal to its mana value"),
        ("mana_value_creature", r"(?:is|are) (?:an? )?(?P<words>[a-z]+(?: [a-z]+)*?) creature with power and toughness "
                                r"each equal to its mana value"),
        ("no_untap", r"doesn'?t untap during its controller'?s untap step"),
        ("force_attack", r"attacks? each combat if able"),
        ("quote", r'(?:has|have) "(?P<inner>[^"]+)"'),
        ("addition", rf"(?:is|are) (?:an? )?(?P<words>{_WORD_LIST}) in addition to (?:its|their) other "
                     r"(?:creature )?types"),
        ("legendary", r"(?:is|are) legendary"),
        ("every_type", r"(?:is|are) (?:every|all) creature types?"),
        ("color", rf"(?:is|are) (?P<colors>(?:{_COLOR_WORDS})(?: and (?:{_COLOR_WORDS}))*)"),
        ("replace", rf"(?:is|are) (?:an? )?(?P<words>{_WORD_LIST}){_LIST_END}"),
        ("lose", rf"loses? (?P<kw>[a-z][a-z ,]*?){_LIST_END}"),
        ("keywords", rf"(?:has|have) (?P<kw>[a-z][a-z0-9 ,{{}}]*?){_LIST_END}"),
    )
)

#: A subject head: the verb that opens the predicate. "has"/"have" can sit inside a subject only as part of a "with"
#: qualifier, which the shared object grammar owns, so the first verb word splits subject from predicate.
_SPLIT_RE = re.compile(r"^(?P<subject>.+?) (?P<predicate>(?:gets?|has|have|is|are|loses?|attacks?) .+)$")
#: RULE 303.4 / 301.5: the printed subjects that mean the host of an Aura or Equipment (not a group).
_ATTACHED_SUBJECT_RE = re.compile(rf"(?:{ATTACHED_SUBJECT_PATTERN})")
#: A ward cost this grammar can carry: mana symbols or a life payment (RULE 702.21a). Anything longer is not a cost.
_WARD_COST_RE = re.compile(r"(?:\{[^}]+\})+|pay \d+ life")
_COUNTER_ON_SOURCE_RE = re.compile(r"counters? on ~")
#: Subject words that make a phrase a host or the source rather than a group: "equipped artifact" is not the Equipment
#: subject (the closed attached list above owns those), and a pronoun or "target" is not a standing group.
_NOT_A_GROUP_WORDS = frozenset({"enchanted", "equipped", "fortified", "that", "those", "they", "target"})
#: The bonus clauses that need a creature group; a base-P/T clause may ride along a "is a creature" addition (Opalescence).
_PT_CLAUSES = frozenset({"pump", "pump_each", "pump_x"})
_PLURAL_ES = "es"
#: The `pt_set` / `type_change` ``pt_selector`` value reading each affected object's own mana value
#: (`game.continuous.PT_SELECTOR_MANA_VALUE`; the parser may not import `game/`).
_MANA_VALUE_SELECTOR = "mana_value"
#: RULE 205.1a: the permanent card types a "is a <types> creature" statement can name.
_SET_CARD_TYPES = frozenset({"artifact", "enchantment", "land"})


def _plural_to_singular_candidates(word: str) -> tuple[str, ...]:
    """A plural type word's singular spellings ("heroes" -> "hero", "bears" -> "bear", "elves" -> "elf")."""
    stripped = word[: -len(_PLURAL_ES)] if word.endswith(_PLURAL_ES) else word
    return (word, singularize(word), stripped)


def _addition_params(words: str) -> Optional[dict]:
    """"<card/sub types>" of an "in addition to its other types" clause -> layer-4 add params, accepting the plural
    spelling a group clause prints ("are heroes", "are enchantments")."""
    singular: list[str] = []
    for word in re.split(r",? and |, | ", words):
        for candidate in _plural_to_singular_candidates(word):
            if type_addition_params(candidate) is not None:
                singular.append(candidate)
                break
        else:
            return None
    return type_addition_params(" ".join(singular))


def _selector(subject: str) -> Optional[dict]:
    """The structured ``affects`` group of a plural subject phrase, or ``None`` (fail closed)."""
    words = subject.split()
    if not words:
        return None
    if words[0] in ("all", "each"):
        words = words[1:]
    other = bool(words) and words[0] == "other"
    if other:
        words = words[1:]
    if not words:
        return None
    text = " ".join(words)
    if text == "commander creatures you own":
        # RULE 903.3: ownership, not control, so a stolen commander still counts.
        return scoped_group_selector("any", {"card_type": "creature", "is_commander": True, "owned_by_you": True})
    history = re.fullmatch(
        r"creatures? you control that you've put (?:1 or more|a) ([+\-]1/[+\-]1) counters? on this turn", text,
    )
    if history:
        return scoped_group_selector("you", {
            "card_type": "creature", "counter_placed_by_you_this_turn": history[1],
            **({"not_reference": True} if other else {}),
        })
    if _NOT_A_GROUP_WORDS.intersection(words):
        return None
    parsed = parse_object_phrase(text, plural=True)
    if parsed is None:
        return None
    filt, controller = dict(parsed[0]), parsed[1]
    # A bare adjective ("black") names no object class; "permanents" names every permanent (RULE 110.1).
    if not filt and words[-1] != "permanents":
        return None
    if other:
        filt["not_reference"] = True  # RULE 109.5
    owner = {"you": "you", "not_you": "opponents", None: "any"}.get(controller)
    if owner is None:
        return None
    return scoped_group_selector(owner, filt)


def _clauses(predicate: str, *, attached: bool) -> Optional[list[tuple[str, "re.Match[str]"]]]:
    """The predicate split into its clauses, or ``None`` when any part is not one this grammar reads."""
    found: list[tuple[str, re.Match[str]]] = []
    pos = 0
    while pos < len(predicate):
        for name, pattern in _CLAUSES:
            if name == "replace" and not attached:
                continue
            m = pattern.match(predicate, pos)
            if m is not None and m.end() > pos:
                found.append((name, m))
                pos = m.end()
                break
        else:
            return None
        if pos < len(predicate):
            sep = _SEPARATOR_RE.match(predicate, pos)
            if sep is None:
                return None
            pos = sep.end()
    return found or None


def _keyword_params(text: str) -> Optional[dict]:
    """A "has <list>" keyword list -> `grant_keyword` params (flags, ward, grantable parametric), else ``None``."""
    resolved = flag_keywords_and_ward(text)
    if resolved is not None:
        keywords, ward = resolved
        if ward is not None and _WARD_COST_RE.fullmatch(ward) is None:
            return None  # a tail the ward pattern swallowed ("ward {10} as long as it was cast") is a condition
        return {**({"keywords": keywords} if keywords else {}), **({"ward_cost": ward} if ward else {})}
    split = split_keywords_with_parametric(text)
    if split is None:
        return None
    flags, parametric = split
    return {**({"keywords": flags} if flags else {}), **({"parametric_keywords": parametric} if parametric else {})}


def _affected_count(what: str) -> Optional[dict]:
    """RULE 613.4d: bind its/other/that creature to each recipient."""
    what = what.removeprefix("the number of ")
    if what == "of its colors":
        return {"affected_count": "colors"}
    types = re.fullmatch(r"of its creature types(?:, to a maximum of (\d+))?", what)
    if types:
        return {"affected_count": "creature_types", **({"maximum": int(types[1])} if types[1] else {})}
    pip = re.fullmatch(r"(white|blue|black|red|green) mana symbol in its mana cost", what)
    if pip:
        return {"affected_count": "mana_symbols", "color": COLOR_LETTERS[pip[1]]}
    counters = re.fullmatch(r"([+-]1/[+-]1|[a-z]+) counters? on it", what)
    if counters:
        return {"counters_on": "affected", "kind": counters[1]}
    if what == "point of bushido it has":
        return {"affected_count": "bushido"}
    if what == "other creature you control with the same name as that creature":
        return {"affected_count": "objects", "selector": scoped_group_selector("you", {
            "card_type": "creature", "not_reference": True, "named_as_reference": True,
        })}
    group = re.fullmatch(r"other (.+) you control", what)
    if group:
        for plural in (group[1], group[1] + "s"):
            selector = _selector("other " + plural + " you control")
            if selector is not None:
                return {"affected_count": "objects", "selector": selector}
    return None


def _amount_selector(what: str, *, group: bool) -> "Optional[str | dict]":
    """A "where X is <count>" amount as a count selector, refusing a reading relative to the affected object ("on it",
    and for a group "the number of other Skeletons": each Skeleton excludes *itself*, the selector excludes the source):
    a selector is evaluated once against the source's controller."""
    # "on it" / "its": the host's own counters or characteristics, which the source-relative selector cannot read.
    if re.search(r"\bits?\b", what) or (group and re.search(r"\b(?:other|another)\b", what)):
        return _affected_count(what) if group else None
    return parse_amount_phrase(what)


def _creature_group(affects: object) -> bool:
    """Whether a P/T clause on this subject can matter: a host or self always, a group only when it is a creature group
    (RULE 208.1: only creatures have power and toughness). "Artifacts you control get +1/+1" stays unclaimed, as does
    a land group's "as long as it's a planeswalker" gate, the way every earlier anthem row keeps it."""
    if isinstance(affects, str):
        return True
    filt = affects["filter"] if isinstance(affects, dict) else {}
    return (
        filt.get("card_type") == "creature"
        or "creature" in filt.get("card_type_all", ())
        or filt.get("subtype", "") in CREATURE_SUBTYPES
        or bool(filt.get("is_commander"))
    )


def _build(
    affects: object, clauses: list[tuple[str, "re.Match[str]"]], *, attached: bool
) -> Optional[list[EffectSpec]]:
    specs: list[EffectSpec] = []
    for name, m in clauses:
        if name in _PT_CLAUSES and not _creature_group(affects):
            return None
        if name in ("pump", "pump_each"):
            params: dict = {"power": int(m.group("p")), "toughness": int(m.group("t")), "affects": affects}
            if name == "pump_each":
                what = m.group("what")
                selector = (_affected_count(what) if isinstance(affects, dict)
                            else for_each_count_selector(what, self_form=False))
                if selector is None:
                    return None
                params.update(power_count=selector, toughness_count=selector)
            specs.append(EffectSpec("anthem", params))
        elif name == "pump_x":
            # RULE 107.3 / 613.4c: "+X/+0, where X is <a live count>"; each X is the printed sign over the same count.
            selector = _amount_selector(m.group("what"), group=not isinstance(affects, str))
            if selector is None:
                return None
            params = {"affects": affects}
            for axis, group in (("power", "p"), ("toughness", "t")):
                value = m.group(group)
                params[axis] = (-1 if value.startswith("-") else 1) if value.endswith("x") else int(value)
                if value.endswith("x"):
                    params[axis + "_count"] = selector
            specs.append(EffectSpec("anthem", params))
        elif name == "force_attack":
            specs.append(EffectSpec("grant_keyword", {"keywords": ["attacks_if_able"], "affects": affects}))
        elif name == "base_pt_x":
            selector = _amount_selector(m.group("what"), group=not isinstance(affects, str))
            if selector is None or (isinstance(selector, dict) and ("affected_count" in selector or "counters_on" in selector)):
                return None
            specs.append(EffectSpec("pt_set", {"affects": affects, "power": 0, "toughness": 0,
                                               "power_count": selector, "toughness_count": selector}))
        elif name == "base_pt":
            specs.append(EffectSpec("pt_set", {"affects": affects, "power": int(m.group("bp")),
                                               "toughness": int(m.group("bt"))}))
        elif name == "mana_value_pt":
            # RULE 613.4b: each affected object's own mana value, read per object every recompute.
            specs.append(EffectSpec("pt_set", {"affects": affects, "pt_selector": _MANA_VALUE_SELECTOR}))
        elif name == "mana_value_creature":
            types = m.group("words").split()
            if any(t not in _SET_CARD_TYPES for t in types):
                return None
            # RULE 205.1a: "is an artifact creature" sets the card types (no "in addition"), so the object keeps
            # only the named types; the P/T rides the same layer-4 effect (RULE 613.4b).
            specs.append(EffectSpec("type_change", {
                "affects": affects, "set_types": [*types, "creature"], "pt_selector": _MANA_VALUE_SELECTOR}))
        elif name == "no_untap":
            if not attached:
                return None
            specs.append(EffectSpec("no_untap", {"affects": affects}))
        elif name == "base_toughness":
            # RULE 613.4b: only the toughness is set; the power half keeps its earlier-layer value.
            specs.append(EffectSpec("pt_set", {"affects": affects, "power": None, "toughness": int(m.group("bt"))}))
        elif name == "quote":
            if attached and _COUNTER_ON_SOURCE_RE.search(m.group("inner")):
                # "put a blood counter on <the Equipment's own name>": the folded "~" names the Equipment here, but a
                # granted ability's "~" binds to the host, so the counter would land on the wrong permanent.
                return None
            grants = quoted_ability_grant_effects_list(m.group("inner"))
            if grants is None:
                return None
            for grant in grants:
                grant.params["affects"] = affects
            specs.extend(grants)
        elif name == "addition":
            added = _addition_params(m.group("words"))
            if added is None:
                return None
            specs.append(EffectSpec("type_change", {"affects": affects, **added}))  # RULE 205.1b / 613.1d
        elif name == "legendary":
            specs.append(EffectSpec("type_change", {"affects": affects, "legendary": True}))
        elif name == "every_type":
            specs.append(EffectSpec("type_change", {"affects": affects, "add_subtypes": ["Changeling"]}))
        elif name == "color":
            colors = [COLOR_LETTERS[w] for w in re.findall(_COLOR_WORDS, m.group("colors"))]
            specs.append(EffectSpec("color_change", {"affects": affects, "colors": colors, "set": True}))
        elif name == "replace":
            parsed = type_words(m.group("words"))
            if parsed is None or parsed[1] or not parsed[2]:
                return None  # only "<colours> <creature types>"; a card type word is a different statement
            color_letters, _, subtypes = parsed
            specs.append(EffectSpec("type_change", {"affects": affects, "set_creature_types": subtypes}))
            if color_letters:
                specs.append(EffectSpec("color_change", {"affects": affects, "colors": color_letters, "set": True}))
        elif name == "lose":
            keywords = flag_keywords(m.group("kw"))
            if keywords is None:
                return None
            specs.append(EffectSpec("remove_keyword", {"keywords": keywords, "affects": affects}))
        else:  # "keywords"
            params = _keyword_params(m.group("kw"))
            if params is None:
                return None
            specs.append(EffectSpec("grant_keyword", {**params, "affects": affects}))
    return specs or None


def static_typed_group_statement(ctx: StaticContext) -> StaticResult:
    """"<group or host> <clause>, <clause>, and <clause>" -- see the module doc."""
    text = re.sub(r'^(~ has [a-z, ]+) and ("[^"]+")$', r'\1 and has \2', ctx.text)
    split = _SPLIT_RE.fullmatch(text)
    if split is None:
        return None
    subject = split.group("subject")
    attached = _ATTACHED_SUBJECT_RE.fullmatch(subject) is not None
    if attached:
        affects: object = _ATTACHED["affects"]
    elif subject == "~":
        affects = "self"
    else:
        affects = _selector(subject)
    if affects is None:
        return None
    clauses = _clauses(split.group("predicate"), attached=attached)
    if clauses is None:
        return None
    specs = _build(affects, clauses, attached=attached)
    return DECLINE if specs is None else specs
