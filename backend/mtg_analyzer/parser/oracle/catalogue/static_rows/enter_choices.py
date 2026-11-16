"""Static-ability helpers: enter choices (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Optional
from ..named_choice import enter_card_name_specs
from ...spec import EffectSpec, ParserProvenance
from ..counters import ENTER_COUNTER_CHOICE_RE, parse_counter_choice_items
from ..characteristic_phrase import KEYWORD_WORDS
from ..clause_hooks import segment_line
from .object_scope import parse_scope, singularize
from .combat_restrictions import ATTACHED_SUBJECT_PATTERN
from .granted_abilities import type_addition_params

# "As ~ enters, choose a creature type."/"As ~ enters, choose a color."
# (RULE 601.2b — a characteristic-defining choice made *as part of*
# entering, not a triggered ability) — recognised separately from every
# other family in this module: the segmenter wraps its `EffectSpec`s as an
# ``enter_replacement`` `AbilitySpec` (RULE 614.1c/614.12's family, the same
# one Clever Impersonator's hand-authored "enter as a copy" uses) rather than
# ``static``, so `enter_choice_specs` below is a sibling entry point to
# `static_effect_specs`, not folded into it — see `segmenter.segment_line`'s
# call site. The choice itself is offered interactively by `RulesEngine.
# _offer_enter_choices` and stamped onto `GameObject.chosen_type`/
# `chosen_color`, which the dynamic ``subtype_from_source``/
# ``color_from_source`` selector params below (and `IS_CHOSEN_TYPE_RE`) read
# back.
_CHOOSE_CREATURE_TYPE_ON_ENTER_RE = re.compile(
    r"as ~ enters, choose a creature type", re.IGNORECASE
)
# ``it`` is the immediately preceding permanent in a compound entry clause
# (Thriving lands: "~ enters tapped. As it enters, choose a color other than
# red.").  The gate only forwards that form after ``lands.py`` has full-matched
# the complete entry replacement, so accepting it here does not broaden a
# free-standing pronoun grammar.
_CHOOSE_COLOR_ON_ENTER_RE = re.compile(
    r"as (?:~|it) enters, choose a color(?: other than [a-z]+)?", re.IGNORECASE
)
# PAR-4 — Realmwright/A-Thran Portal's "As ~ enters, choose a basic land
# type.": a third `enter_choice_effects` sibling, alongside creature
# type/color above. Anchored on "basic land type" specifically (never just
# "land type" on a real card) so it can't collide with the creature-type row.
_CHOOSE_BASIC_LAND_TYPE_ON_ENTER_RE = re.compile(
    r"as ~ enters, choose a basic land type", re.IGNORECASE
)
_CHOOSE_OPPONENT_ON_ENTER_RE = re.compile(r"as ~ enters, choose an opponent", re.IGNORECASE)


#: PAR-142: "you may have ~ enter the battlefield as a copy of `<what>`[, except `<tail>`]" (RULE 614.1c/707.9 —
#: Clone, Copy Artifact, Phantasmal Image, Mirrorhall Mimic …): an ``enter_replacement`` over the engine's
#: `EnterAsCopyReplacement`. ``<what>`` is a closed table onto the targeting pools the engine already offers;
#: unrepresented pools still fail closed; graveyard pools use the same scoped card-kind vocabulary.
_ENTER_AS_COPY_RE = re.compile(
    r"you may have (?:~|it) enter(?: the battlefield)?(?P<tapped> tapped)? as a copy of (?P<what>[a-z ]+?)"
    r"(?:, except (?P<tail>.+))?",
    re.IGNORECASE,
)
_ENTER_AS_COPY_POOLS: dict[str, str] = {
    "a creature card in a graveyard": "any_graveyard_creature",
    "any creature card in a graveyard": "any_graveyard_creature",
    "any creature card in your graveyard": "graveyard_creature",
    "any land card in a graveyard": "any_graveyard_land",
    "any creature on the battlefield": "creature",
    "a creature you control": "creature_you_control",
    "a creature an opponent controls": "creature_you_dont_control",
    "any artifact on the battlefield": "artifact",
    "any enchantment on the battlefield": "enchantment",
    "an enchantment you control": "enchantment_you_control",
    "any land on the battlefield": "land",
    "any permanent on the battlefield": "permanent",
    "any nonland permanent on the battlefield": "nonland_permanent",
    "any artifact or creature on the battlefield": "artifact_or_creature",
    "any artifact or enchantment on the battlefield": "artifact_or_enchantment",
}


#: Stand-in for a quoted ability while an "except" tail is split into pieces (no card text contains NUL).
_QUOTED_PLACEHOLDER = "\x00quoted"


def _granted_ability_line(body: str) -> Optional[str]:
    """The quoted ability of "except it has \"<ability>\"" when the ordinary ability grammar fully models it, else
    ``None`` (RULE 707.9a). Validated through the same ``segment_line`` path any ability line takes, so a body nothing
    models never leaves the copy silently without it."""
    line = body.strip().rstrip(" ,.;")
    if not line:
        return None
    ability = segment_line(line, allow_spell_effect=False, provenance=ParserProvenance())
    if not ability.claimed or (ability.spec is None and not ability.mana_ability):
        return None
    return line


#: RULE 702.105: keywords a copy's "except it has …" may grant that stay out of `KEYWORD_WORDS` (the vocabulary of
#: object filters such as "creature with <keyword>"); the engine resolves dethrone from the keyword itself (`check_dethrone`).
_COPY_EXCEPTION_KEYWORDS: frozenset[str] = frozenset({"dethrone"})


def _all_copy_keywords() -> frozenset[str]:
    return frozenset(KEYWORD_WORDS) | _COPY_EXCEPTION_KEYWORDS


def enter_as_copy_tail(tail: str) -> Optional[dict]:
    """A copy's "except …" clause → `EnterAsCopyReplacement` params, or ``None`` (fail closed)."""

    params: dict = {}
    pieces: list[str] = []
    # RULE 707.9a: a quoted ability is one opaque piece; set it aside so its own commas / "and"s are not split.
    quoted: list[str] = []

    def _stash(q: re.Match[str]) -> str:
        quoted.append(q.group(1))
        return f"{_QUOTED_PLACEHOLDER}{len(quoted) - 1}"

    tail = re.sub(r'"([^"]*)"', _stash, tail.strip().rstrip("."))
    # RULE 707.9: pronouns all describe the resulting copy.
    tail = re.sub(r"\b(?:he|she)'s\b", "it's", tail)
    tail = re.sub(r"\b(?:he|she) has\b", "it has", tail)
    tail = re.sub(r"\b(?:his|her)\b", "its", tail)
    for chunk in re.split(r",\s*(?:and\s+)?", tail):
        pieces.extend(p for p in re.split(r"\s+and\s+", chunk) if p.strip())
    after_keywords = False
    for piece in pieces:
        piece = piece.strip()
        if re.match(r"^is an? ", piece):
            piece = "it's " + piece[len("is "):]
        elif re.match(r"^has ", piece):
            piece = "it " + piece
        if re.fullmatch(r"it isn'?t legendary|it'?s not legendary", piece):
            params["not_legendary"] = True
            continue
        m = re.fullmatch(r"it'?s an? (?P<words>[a-z ]+?) in addition to its other types", piece)
        if m is not None:
            added = type_addition_params(m.group("words"))
            if added is None:
                return None
            if added.get("legendary"):
                params["add_types"] = [*params.get("add_types", []), "Legendary"]
            if added.get("add_types"):
                params["add_types"] = [*params.get("add_types", []), *(t.capitalize() for t in added["add_types"])]
            if added.get("add_subtypes"):
                params["add_subtypes"] = [*params.get("add_subtypes", []), *added["add_subtypes"]]
            continue
        # "it has haste and dethrone": the " and " split leaves the second keyword bare; it continues the "has" list.
        if after_keywords and piece in _all_copy_keywords():
            piece = f"it has {piece}"
        m = re.fullmatch(r"it has (?P<kws>[a-z ,]+?)", piece)
        after_keywords = False
        if m is not None:
            words = [w.strip() for w in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group("kws")) if w.strip()]
            if not words or any(w not in KEYWORD_WORDS and w not in _COPY_EXCEPTION_KEYWORDS for w in words):
                return None
            params["add_keywords"] = [*params.get("add_keywords", []), *(w.title() for w in words)]
            after_keywords = True
            continue
        m = re.fullmatch(rf"it has {_QUOTED_PLACEHOLDER}(?P<index>\d+)", piece)
        if m is not None:
            line = _granted_ability_line(quoted[int(m.group("index"))])
            if line is None:
                return None
            params["add_ability_lines"] = [*params.get("add_ability_lines", []), line]
            continue
        if re.fullmatch(r"(?:its|his|her) name is ~", piece):
            params["set_name"] = "~"
            continue
        if piece == "it enters with x additional +1/+1 counters on it":
            params["extra_counters_from_x"] = True
            continue
        return None  # an unrecognised piece is never dropped
    return params


def copy_exception_params(tail: str) -> Optional[dict]:
    """A become-a-copy effect's "except …" tail → effect params, or ``None`` (fail closed).

    RULE 707.9a: "it has this ability" (also "it has flying and this ability") keeps the one resolving ability
    (``keep_own_abilities``); everything else is the enter-as-copy vocabulary (`enter_as_copy_tail`)."""
    params: dict = {}
    leading = re.search(r"\bit has this ability and (?=\S)", tail)
    if leading is not None:
        # "it has this ability and "<ability>"" (Aurora Shifter): the rest is what else it has.
        params["keep_own_abilities"] = True
        tail = tail[: leading.start()] + "it has " + tail[leading.end():]
    keep_own = (None if leading is not None else re.search(r"(?:,\s*(?:and\s+)?|\s+and\s+)?\bit has this ability\b", tail)
                or re.search(r"(?<=\w)\s+and\s+this ability\b", tail))
    if keep_own is not None:
        params["keep_own_abilities"] = True
        tail = (tail[: keep_own.start()] + tail[keep_own.end():]).strip(" ,.")
    if tail:
        extra = enter_as_copy_tail(tail)
        if extra is None or "extra_counters_from_x" in extra:
            return None
        params.update(extra)
    return params


def enter_as_copy_specs(clause: str) -> Optional[list[EffectSpec]]:
    """`EffectSpec`s for an "enter as a copy of …" replacement ``clause``, or ``None``."""
    text = clause.strip().rstrip(".").strip()
    counters = re.fullmatch(
        r"(?P<base>you may have .+)\. if you do, it enters with additional counters on it "
        r"equal to the same number and kinds of counters the copied permanent has on it", text)
    if counters:
        specs = enter_as_copy_specs(counters.group("base"))
        if specs:
            specs[0].params["copy_counters"] = True
        return specs
    m = _ENTER_AS_COPY_RE.fullmatch(text)
    if m is None:
        return None
    what = re.sub(r"\s+", " ", m.group("what").lower())
    died = what.endswith(" that was put there from the battlefield this turn")
    if died:
        what = what.removesuffix(" that was put there from the battlefield this turn")
    kind = _ENTER_AS_COPY_POOLS.get(what)
    if kind is None:
        return None
    params: dict = {"target_kind": kind}
    if died:
        if kind not in ("graveyard_creature", "any_graveyard_creature"):
            return None
        params["creature_filter"] = {"died_this_turn": True}
    if m.group("tapped"):
        params["enter_tapped"] = True  # RULE 614.12: "enter tapped as a copy" (Callidus Assassin)
    if m.group("tail"):
        extra = enter_as_copy_tail(m.group("tail"))
        if extra is None:
            return None
        params.update(extra)
    return [EffectSpec("enter_as_copy", params)]


def enter_choice_specs(clause: str) -> Optional[list[EffectSpec]]:
    """`EffectSpec`s for a RULE 601.2b "as ~ enters, choose a …" ``clause``,
    or ``None`` — see the module comment above `_CHOOSE_CREATURE_TYPE_ON_
    ENTER_RE`. Called by `segmenter.segment_line` *before*
    `static_effect_specs`, since the two clause families are wrapped as
    different `AbilitySpec.ability_kind`s (``enter_replacement`` vs.
    ``static``).
    """
    text = clause.strip().rstrip(".").strip()

    copy_specs = enter_as_copy_specs(text)
    if copy_specs is not None:
        return copy_specs
    if _CHOOSE_CREATURE_TYPE_ON_ENTER_RE.fullmatch(text):
        return [EffectSpec("choose_creature_type_on_enter", {})]
    if _CHOOSE_COLOR_ON_ENTER_RE.fullmatch(text):
        return [EffectSpec("choose_color_on_enter", {})]
    if _CHOOSE_BASIC_LAND_TYPE_ON_ENTER_RE.fullmatch(text):
        return [EffectSpec("choose_basic_land_type_on_enter", {})]
    if _CHOOSE_OPPONENT_ON_ENTER_RE.fullmatch(text):
        return [EffectSpec("choose_opponent_on_enter", {})]
    # MEC-134: "As ~ enters, choose a nonland card name." / "…look at an opponent's hand, then choose any card name."
    named = enter_card_name_specs(text)
    if named is not None:
        return named
    # MEC-108 / RULE 614.1: "~ enters with your choice of a flying counter or a
    # first strike counter on it." — the counter pick is an as-it-enters choice.
    choice = ENTER_COUNTER_CHOICE_RE.fullmatch(text)
    if choice is not None:
        options = parse_counter_choice_items(choice.group("items"))
        if options is not None:
            return [EffectSpec("choose_enter_counter", {"options": options})]
    return None


# "~ is the chosen type in addition to its other types." (RULE 601.2b/613.4a,
# A-Thran Portal/Adaptive Automaton-shaped self grant) — the layer-4 sibling
# of the dynamic anthem/grant ``subtype_from_source`` params above, scoped to
# just the source itself (``affects="self"``) rather than a controlled group.
IS_CHOSEN_TYPE_RE = re.compile(
    r"~ is the chosen type in addition to its other types", re.IGNORECASE
)

# The *group* sibling of `IS_CHOSEN_TYPE_RE` — "Creatures you control are
# the chosen type in addition to their other types." (Arcane Adaptation/
# Leyline of Transformation), "Each creature you control is …" (Xenograft),
# "Lands you control are …" (Realmwright), "Vehicle creatures you control
# are the chosen creature type …" (Lifecraft Engine).
#
# The optional ``off`` tail is Arcane Adaptation's second sentence, which
# extends the very same grant *past the battlefield* — the layer engine's
# ordinary walk only visits permanents, so it becomes an
# ``off_battlefield="cards_you_own"`` param handled by `continuous.
# _apply_off_battlefield_types`. Two sentences on one printed line, so it
# has to be claimed by one regex (the segmenter splits on newlines, not
# sentences); leaving the tail unmatched would fail the whole clause closed.
GROUP_TYPE_ADDITION_RE = re.compile(
    r"(?:each )?(?P<body>[a-z][a-z ]*?) you control (?:is|are) (?:an? )?(?P<words>[a-z]+(?: [a-z]+)*?) "
    r"in addition to (?:its|their) other (?:creature )?types",
    re.IGNORECASE,
)


def type_addition_plural_words(words: str) -> Optional[dict]:
    """"Forest lands"/"squirrels"/"artifacts" (a group's plural spelling) → `type_addition_params`, reading
    each word either as printed or singularized; ``None`` if any word is in neither vocabulary."""
    singular: list[str] = []
    for word in words.lower().split():
        for candidate in (word, singularize(word)):
            if type_addition_params(candidate) is not None:
                singular.append(candidate)
                break
        else:
            return None
    return type_addition_params(" ".join(singular))


GROUP_CHOSEN_TYPE_RE = re.compile(
    r"(?:each )?(?P<body>[a-z][a-z ]*?) you control (?:is|are) the chosen "
    r"(?:creature )?type in addition to (?:its|their) other (?:creature )?types"
    r"(?P<off>\. the same is true for creature spells you control and creature "
    r"cards you own that aren'?t on the battlefield)?",
    re.IGNORECASE,
)

# "Each creature card in your graveyard has the chosen creature type in
# addition to its other types." (Ashes of the Fallen) — the same RULE 613.4a
# grant with *no* battlefield half at all, so its `affects` deliberately
# names a selector `continuous.group_selector_objects` doesn't recognise
# (which safely picks out nothing) and all the work happens in the
# off-battlefield pass.
GRAVEYARD_CHOSEN_TYPE_RE = re.compile(
    r"each creature card in your graveyard has the chosen creature type "
    r"in addition to its other types",
    re.IGNORECASE,
)


def chosen_type_group_affects(body: str) -> Optional[dict]:
    """The `affects` (+ subtype narrowing) params for a `GROUP_CHOSEN_TYPE_RE`
    subject phrase, or ``None`` for one this can't express (fail-closed).

    Lands get their own branch since `parse_scope` deliberately only claims
    *creature* scopes; everything else goes through `parse_scope` so a tribal
    narrowing ("Vehicle creatures you control", Lifecraft Engine) comes out
    as the usual ``subtype`` param.
    """
    words = body.strip().split()
    if words and words[0] in ("all", "each"):
        words = words[1:]
    if words in (["land"], ["lands"]):
        return {"affects": "lands_you_control"}
    scope = parse_scope(" ".join(words))
    if scope is None:
        return None
    if scope.attacking or scope.permanents:
        return None  # a selector this grant can't express — fail closed rather than widen
    params: dict = {"affects": "creatures_you_control"}
    if scope.subtype:
        params["subtype"] = scope.subtype
    if scope.filt:  # PAR-134
        params["object_filter"] = scope.filt
    # PAR-142: "creature **tokens** you control are Squirrels", "**white** creatures you control are …",
    # "**artifact** creatures you control are …" — dropped, each would silently widen to every creature.
    if scope.tokens:
        params["tokens"] = True
    if scope.colors:
        params["color"] = scope.colors
    if scope.card_type:
        params["card_type"] = scope.card_type
    return params


# "You control enchanted creature/permanent." (Mind Control/Control Magic-
# shaped, RULE 613.2 layer-2 control-grant) — the existing `control_change`
# `StaticAbility` already defaults to ``affects="attached_permanent"`` and a
# controller of "the source's own controller" (exactly "you"), so this needed
# no new engine code, only the parser recognition.
CONTROL_GRANT_RE = re.compile(
    r"you control (?:enchanted creature|enchanted permanent)", re.IGNORECASE
)

# "<equipped/enchanted/fortified subject> [gets +N/+N and] has \"<ability>\""
# (Sword-of-X-and-Y/Assassin Gauntlet/Caustic Tar-shaped, Umbral Mantle/
# Squirrel Nest-shaped) — an Aura/Equipment granting its host a *full*
# ability rather than a flag keyword. The quoted text is itself an ordinary
# ability line, so it's parsed the same way any top-level card's own line
# would be (`segmenter.segment_line`, imported lazily in
# `quoted_ability_grant_effects` below — `segmenter` imports *this* module,
# so a module-level import would cycle) and wrapped as a
# `grant_triggered_ability`/`grant_activated_ability` when that recursive
# parse comes back a plain, unconditional shape: a self-scoped trigger on
# one of `GRANTABLE_TRIGGER_EVENTS`, or a bare `<cost>: <effect>` activated
# ability (fail-closed on everything else: a controller-scoped phase
# trigger like "at the beginning of your upkeep" granted this way is a
# pre-existing gap, not special to grants; see `GRANTABLE_TRIGGER_EVENTS`).
ATTACHED_QUOTED_ANTHEM_GRANT_RE = re.compile(
    rf'(?P<subject>{ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) '
    r'and has "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)
ATTACHED_QUOTED_ANTHEM_GRANT_AND_TYPE_RE = re.compile(
    rf'(?P<subject>{ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+),? '
    r'has "(?P<inner>.+)"(?:,)? and is an? (?P<subtype>[a-z-]+) '
    r'in addition to its other types\.?',
    re.IGNORECASE | re.DOTALL,
)
ATTACHED_ANTHEM_KEYWORD_AND_QUOTED_GRANT_RE = re.compile(
    rf'(?P<subject>{ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)(?:,| and) '
    r'has (?P<keywords>[a-z, ]+?) and "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)
ATTACHED_KEYWORD_AND_QUOTED_GRANT_RE = re.compile(
    rf'(?P<subject>{ATTACHED_SUBJECT_PATTERN}) has (?P<keywords>[a-z, ]+?) and "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)
ATTACHED_WARD_AND_QUOTED_GRANT_RE = re.compile(
    rf'(?P<subject>{ATTACHED_SUBJECT_PATTERN}) has ward (?P<cost>.+?) and "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)
ATTACHED_QUOTED_GRANT_RE = re.compile(
    rf'(?P<subject>{ATTACHED_SUBJECT_PATTERN}) has "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)
ATTACHED_DOUBLE_QUOTED_GRANT_RE = re.compile(
    rf'(?P<subject>{ATTACHED_SUBJECT_PATTERN}) has "(?P<first>.+)" and "(?P<second>.+)"',
    re.IGNORECASE | re.DOTALL,
)
ATTACHED_LOOK_TOP_AND_QUOTED_GRANT_RE = re.compile(
    rf'(?P<subject>{ATTACHED_SUBJECT_PATTERN}) has '
    r'"you may look at the top card of your library any time" and "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)
ATTACHED_QUOTED_GRANT_AND_TYPE_RE = re.compile(
    rf'(?P<subject>{ATTACHED_SUBJECT_PATTERN}) has "(?P<inner>.+)" '
    r'and is an? (?P<subtype>[a-z-]+) in addition to its other types',
    re.IGNORECASE | re.DOTALL,
)

#: "Enchanted land has 'Untap this land during each other player's untap
#: step.'" (Urban Burgeoning). This imperative-duration wording is a
#: triggered ability in rules terms, but not a regular "when/whenever"
#: sentence for `segment_line` to unwrap.
ATTACHED_UNTAP_OTHER_PLAYERS_RE = re.compile(
    rf'(?P<subject>{ATTACHED_SUBJECT_PATTERN}) has "untap (?:this land|~) '
    r"during each other player'?s untap step\.?\"",
    re.IGNORECASE,
)


def attached_untap_other_players(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_triggered_ability", {
        "trigger_event": "STEP_BEGIN",
        "phase_relation": "not_you",
        "grant_effects": [{"type": "tap", "params": {"target_kind": None, "untap": True}}],
        "optional": False,
        "affects": "attached_permanent",
    })]

# RULE 702.94b soulbond: "As long as ~ is paired with another creature,
# **each of those creatures** has …" — the third grant scope, alongside a
# group ("Elves you control have …") and an attachment ("equipped creature
# has …"). The engine side is the already-shipped ``soulbond_pair`` selector
# (`continuous.group_selector_objects`), which resolves to the source *and*
# its partner and yields nothing while unpaired; only the phrase was missing.
# Every real card in the pool grants a **quoted** ability this way, but the
# bare-keyword and anthem forms are written out too so the scope isn't a
# special case of one grant family.
_SOULBOND_SUBJECT = r"each of (?:those|these) creatures"
SOULBOND_QUOTED_GRANT_RE = re.compile(
    rf'{_SOULBOND_SUBJECT} has "(?P<inner>.+)"', re.IGNORECASE | re.DOTALL
)
SOULBOND_ANTHEM_RE = re.compile(
    rf"{_SOULBOND_SUBJECT} gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    r"(?: and has (?P<kw>[a-z][a-z, ]*))?",
    re.IGNORECASE,
)
SOULBOND_GRANT_RE = re.compile(
    rf"{_SOULBOND_SUBJECT} (?:has|have) (?P<kw>[a-z][a-z, ]*)", re.IGNORECASE
)

# RULE 701.15b as a *group* static rather than an Aura's ("Creatures your
# opponents control [with power less than ~'s power] are goaded." — Baeloth
# Barrityl, The War Games). The optional power qualifier is a **dynamic**
# threshold read off the source's own derived power every recompute
# (`continuous.dynamic_threshold`), which is why it can't be the literal
# ``max_power`` the group scope already had: an anthem on ~ moves it.
GROUP_GOADED_RE = re.compile(
    r"(?:all )?creatures (?:your opponents control|you don'?t control)"
    r"(?: with power (?P<cmp>less|greater) than ~'?s power)?"
    r" are goaded",
    re.IGNORECASE,
)
