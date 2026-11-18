"""Static-ability helpers: cost patterns (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Optional
from ..subgrammars import COLOR_LETTERS, COUNT
from ..count_phrase import parse_count_phrase
from .anthem_patterns import CARD_TYPE_WORDS
from .object_scope import singularize

# "Activated abilities of <type>[s] can't be activated."  (RULE 602 prohibition,
# Collector Ouphe/Stony Silence/Null Rod) — global, not "you control"-scoped:
# it silences *every* qualifying permanent's activated abilities, including
# the prohibiting permanent's own if it itself qualifies (Null Rod is an
# Artifact and its printed text carries no self-exemption).
ACTIVATION_PROHIBITION_RE = re.compile(
    r"activated abilities of (?P<word>[a-z]+) can'?t be activated", re.IGNORECASE
)

# "Activated abilities of <type>[s] your opponents control can't be
# activated." (ENG-28, Linvala Keeper of Silence/Karn the Great Creator) —
# the opponent-scoped sibling of `ACTIVATION_PROHIBITION_RE` above: that one
# is global (Null Rod silences its own kind too), this one only reaches
# permanents someone *else* controls, so it needs `affects="opponents_
# permanents"` rather than the board-wide default.
ACTIVATION_PROHIBITION_OPPONENTS_RE = re.compile(
    r"activated abilities of (?P<word>[a-z]+) your opponents control can'?t be activated",
    re.IGNORECASE,
)

# "Your opponents can't cast spells or activate abilities of <type>[, <type>
# [,] or <type>]." (ENG-28, Grand Abolisher/Myrel, Shield of Argive — always
# printed under a leading "During your turn," gate, split off by
# `conditional_static_specs`'s "during your turn" wrapper before this ever
# sees the clause) — one sentence combining `cast_prohibition` (the "cast
# spells" half, no type filter — any spell) with `activation_prohibition`
# (the "activate abilities of …" half, opponent-scoped and type-filtered).
# Two independent specs from one clause, both riding whatever ``active_if``
# gate the caller stamps onto every spec `static_effect_specs` returns.
CANT_CAST_OR_ACTIVATE_OPPONENTS_RE = re.compile(
    r"your opponents can'?t cast spells or activate abilities of (?P<types>[a-z][a-z, ]*)",
    re.IGNORECASE,
)

# "Your opponents can't cast spells during your turn."  (Dragonlord Dromoka/
# Teferi, Time Raveler/Kutzil, Malamet Exemplar/Voice of Victory-shaped) —
# unlike `CANT_CAST_OR_ACTIVATE_OPPONENTS_RE`'s type-scoped sibling (always
# printed under a leading "During your turn," gate `_conditional_static_
# specs` peels off first), this trails its own turn-scope inline rather than
# leading with it, so it needs its own row: `cast_prohibition`'s existing
# ``scope="opponents"`` default plus an ordinary RULE 613.6 ``active_if``
# gate — no new engine primitive, both already exist for other cards'
# shapes. Conqueror's Flail's own "as long as this Equipment is attached to
# a creature, …" wrapping is peeled by `conditional_static_specs` before
# this is ever reached, same as any other conditional static.
CANT_CAST_OPPONENTS_YOUR_TURN_RE = re.compile(
    r"your opponents can'?t cast spells during your turn", re.IGNORECASE
)

# PAR-315 / RULE 508.1b + 601.3a: "[as long as ~ is attacking,] defending player can't cast spells." (Wardscale Dragon) -- the
# attacked player, resolved against the source's own attack at every cast attempt (`cast_prohibition`
# ``defending_player_of_source``); the "as long as ~ is attacking" gate is peeled off by the conditional-static wrapper.
CANT_CAST_DEFENDING_PLAYER_RE = re.compile(r"defending player can'?t cast spells", re.IGNORECASE)

#: A type list ("artifacts, creatures, or enchantments") → normalized
#: singular `CARD_TYPE_WORDS`, or ``None`` (fail-closed) if any word in it
#: isn't a recognised card type. Splits on a comma (with an optional trailing
#: "and"/"or") or a bare "and"/"or" — the two ways real cards print a list of
#: two or three types.
_TYPE_LIST_SPLIT_RE = re.compile(r",\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+", re.IGNORECASE)


def type_word_list(text: str) -> Optional[list[str]]:
    words = [w.strip() for w in _TYPE_LIST_SPLIT_RE.split(text.strip()) if w.strip()]
    if not words:
        return None
    result = []
    for word in words:
        singular = singularize(word.lower())
        if singular not in CARD_TYPE_WORDS:
            return None
        result.append(singular)
    return result


# "<Type> spells cost {N} more/less to cast."  (RULE 601.2f tax/discount,
# Thalia/Thorn of Amethyst/Vryn Wingmare-shaped) — the bare "<type> spells
# cost …" phrasing with no "you cast"/"your opponents cast" qualifier taxes
# *everyone*, the caster's own controller included; see
# `SPELL_COST_TAX_YOU_CAST_RE` below for the self-scoped "you cast" sibling.
SPELL_TYPE_WORDS: frozenset[str] = frozenset(
    {"noncreature", "creature", "artifact", "instant", "sorcery", "enchantment", "planeswalker"}
)
#: Printed *subtype* words a "<subtype> spells you cast cost {N} less" static
#: may name (RULE 205.3 — Banneret/Warchief tribal-discount cycle, plus the
#: Aura/Equipment/Arcane discounters). Emitted as ``spell_subtype``, which
#: `continuous.cost_reduction_for` already resolves through
#: `continuous.has_subtype` (a substring match on the stack object's printed
#: type line). Kept explicit for the same reason `CONDITION_SUBTYPE_WORDS`
#: is: an open subtype vocabulary would claim clauses whose word ("historic",
#: "commander", "colorless") is really a grouping or designation, not a
#: subtype `has_subtype` can check.
SPELL_COST_SUBTYPE_WORDS: frozenset[str] = frozenset({
    "aura", "equipment", "arcane",
    "dragon", "dinosaur", "goblin", "soldier", "angel", "hydra", "demon",
    "giant", "elf", "zombie", "human", "wizard", "merfolk", "vampire",
    "spirit", "knight", "warrior", "elemental", "dwarf", "faerie", "sliver",
    "rogue", "cleric", "shaman", "druid", "beast", "bird", "cat", "snake",
    "kavu", "ally", "rebel", "ninja", "samurai",
})
SPELL_COST_TAX_RE = re.compile(
    r"(?:(?P<word>[a-z]+) )?spells cost \{(?P<n>\d+)\} (?P<dir>more|less) to cast", re.IGNORECASE
)

# "[<Type> [and <type>]] spells you cast cost {N} more/less to cast."  (RULE
# 601.2f self-scoped discount/tax, Baral/Archmage of Runes/Pearl Medallion-
# adjacent — the "you cast" sibling of `SPELL_COST_TAX_RE`: unlike that
# unscoped tax, this only ever discounts/taxes *this permanent's own
# controller*'s spells (`continuous.cost_reduction_for`'s ownership check,
# ``affects="your_spells"`` — the `cost_reduction` registry's own default,
# so the emitted spec omits ``affects`` entirely). The two-type "instant and
# sorcery spells you cast …" compound (Baral, Chief of Compliance-shaped)
# passes both words through as a list — `continuous._spell_type_matches`
# ORs them. Colour-scoped variants ("White spells you cast cost {1} less…",
# the Medallion cycle) are now claimed too, by `SPELL_COST_TAX_COLOR_RE`
# below — not this regex's own ``word1``, since `_spell_type_matches` only
# reads `Card`'s main-type flags, not colour. Creature-subtype-scoped
# variants ("Equipment spells…", the Banneret cycle) remain a genuinely
# different filter kind, still deliberately left unclaimed rather than
# silently ignoring the qualifier.
SPELL_COST_TAX_YOU_CAST_RE = re.compile(
    r"(?:(?P<word1>[a-z]+)(?: and (?P<word2>[a-z]+))? )?spells you cast"
    # PAR-215: "…with mana value 5 or greater cost {1} less" (Spectacle Mage, Krosan Drover) -- the spell's own mana value.
    r"(?: with mana value (?P<mv>\d+) or (?P<mvdir>greater|less))? cost "
    r"\{(?P<n>\d+)\} (?P<dir>more|less) to cast",
    re.IGNORECASE,
)

# PAR-270 (RULE 205.3m / 601.2f): "<A> spells and <B> spells you cast cost {N} less" / "<A> and <B> spells you cast
# ..." -- a union of creature types, `continuous.cost_reduction_for` ORs a ``spell_subtype`` list. Each member must be a
# known subtype (`SUBTYPES`) that is not a main spell type, so "creature and artifact spells" (Baral's type pair)
# never reads as a tribe.
SPELL_COST_SUBTYPE_UNION_RE = re.compile(
    r"(?P<subjects>[a-z]+(?: spells)?(?:(?:, (?:and |or )?| and/or | and | or )[a-z]+(?: spells)?)+) spells you cast"
    r"(?: with mana value (?P<mv>\d+) or (?P<mvdir>greater|less))? cost "
    r"\{(?P<n>\d+)\} (?P<dir>more|less) to cast",
    re.IGNORECASE,
)
SPELL_UNION_SPLIT_RE = re.compile(r"(?: spells)?(?:, (?:and |or )?| and/or | and | or )")

# "<Color> spells you cast cost {N} more/less to cast."  (the Medallion
# cycle/Grand Arbiter Augustin IV-shaped colour filter `_SPELL_COST_TAX_YOU_
# CAST_RE`'s own docstring flagged as unbuilt — `continuous.cost_reduction_
# for`'s ``spell_color`` param already reads it, only the parser recognizer
# was missing.) Checked ahead of `SPELL_COST_TAX_YOU_CAST_RE` in dispatch
# order: that regex's own ``word1`` group also matches a colour word, and
# its handler fails closed (returns ``None``, claiming nothing) on a word
# outside `SPELL_TYPE_WORDS` rather than falling through to try this one.
SPELL_COST_TAX_COLOR_RE = re.compile(
    r"(?P<color>white|blue|black|red|green|colorless) spells you cast"
    r"(?: with mana value (?P<mv>\d+) or (?P<mvdir>greater|less))? cost "
    r"\{(?P<n>\d+)\} (?P<dir>more|less) to cast",
    re.IGNORECASE,
)

#: RULE 903.3 / 601.2f: "Commander spells you cast cost {1} less to cast." (Sagrada Familiar) -- the cast spell is a
#: commander (`GameObject.is_commander`), orthogonal to the card-type, color and subtype filters.
SPELL_COST_TAX_COMMANDER_RE = re.compile(
    r"commander spells you cast cost \{(?P<n>\d+)\} (?P<dir>more|less) to cast", re.IGNORECASE,
)

# "Spells your opponents cast cost {N} more/less to cast."  (Grand Arbiter
# Augustin IV's third line) — the tax-only mirror of
# `SPELL_COST_TAX_YOU_CAST_RE`'s ``"your_spells"`` default: `continuous.
# cost_reduction_for`'s ``affects="opponents_spells"`` branch applies to
# every player except the permanent's own controller.
SPELL_COST_TAX_OPPONENTS_RE = re.compile(
    r"spells your opponents cast cost \{(?P<n>\d+)\} (?P<dir>more|less) to cast",
    re.IGNORECASE,
)

# "Spells `<who>` cast that target `<X>` cost {N} more/less to cast." /
# "…cost an additional N life to cast."  (Icefall Regent / Boreal Elemental /
# Charix / Pursued Whale / Elderwood Scion; Kasmina, Esior, Monastery Siege,
# Terror of the Peaks) — the "that target `<X>`" narrowing on the
# you/opponents spell tax. `continuous.cost_reduction_for` checks the caster's
# chosen targets against this static (RULE 601.2c precedes 601.2f): ``~`` is
# the ``targets_source`` param, anything else an ``if_targets`` OR-list
# (`tax_target_alternatives`). Tried before the plain opponents row (whose
# regex would leave the "that target …" clause unconsumed and fail).
SPELL_COST_TAX_THAT_TARGET_RE = re.compile(
    r"spells (?P<who>you|your opponents) cast that target (?P<target>.+?) cost "
    r"(?:\{(?P<n>\d+)\} (?P<dir>more|less)|an additional (?P<life>\d+) life) to cast",
    re.IGNORECASE,
)
#: Plural spellings of the `CARD_TYPE_WORDS` a tax's target may name.
_TAX_TARGET_CONTROLLED_SUFFIX = " you control"
_TAX_TARGET_COUNT_PREFIX = "1 or more "


def tax_target_alternatives(target: str) -> "Optional[list[dict]]":
    """What a "spells … that target `<X>`" tax's ``<X>`` may be → a
    `continuous._spell_targets_hit` OR-list, or ``None`` (fail-closed for any
    word outside the vocabulary: ``you``, a card type, ``commander``).

    "you or a permanent you control" → the controller as a player, or one of
    their permanents; a trailing "you control" scopes every *permanent*
    alternative, never the bare "you"."""
    text = target.strip().lower()
    controlled = text.endswith(_TAX_TARGET_CONTROLLED_SUFFIX)
    if controlled:
        text = text[: -len(_TAX_TARGET_CONTROLLED_SUFFIX)]
    if text.startswith(_TAX_TARGET_COUNT_PREFIX):
        text = text[len(_TAX_TARGET_COUNT_PREFIX):]
    alternatives: list[dict] = []
    for part in text.split(" or "):
        word = re.sub(r"^(?:an?|the) ", "", part.strip())
        if part.strip() == "you":
            alternatives.append({"player": "controller"})
            continue
        word = word[:-1] if word.endswith("s") else word
        crit: dict = {"permanent": True}
        if word == "commander":
            crit["is_commander"] = True
        elif word in CARD_TYPE_WORDS:
            if word != "permanent":
                crit["card_type"] = word
        else:
            return None
        if controlled:
            crit["controller"] = "source_controller"
        elif word == "permanent":
            return None  # "target a permanent" taxes nothing in particular
        alternatives.append(crit)
    return alternatives or None


# "Activated abilities of <type> you control cost {N} less to activate[.
# This effect can't reduce the mana in that cost to less than {M} mana.]"
# (Training Grounds) — the main-card-type-scoped sibling of Sam, Loyal
# Attendant's hand-authored subtype scope (`continuous.
# activation_cost_reduction_for`'s ``card_type`` branch); the trailing floor
# clause is optional (folded into the same spec via ``min_total`` when
# present) since not every card of this shape prints one.
ACTIVATION_COST_REDUCTION_TYPE_RE = re.compile(
    r"activated abilities of (?P<word>[a-z]+) you control cost \{(?P<n>\d+)\} less to activate\.?"
    r"(?:\s*this effect can'?t reduce the mana in that cost to less than \{?(?P<floor>\d+)\}? mana\.?)?",
    re.IGNORECASE,
)

# RULE 702.6: "Equip abilities you activate [of other Equipment | that target ~]
# cost {N} less to activate." (Bureau Headmaster, Bladehold War-Whip, Cloud
# Planet's Champion, Dwarven Mauler, Helitrooper) — a static discount on the
# controller's equip activations (`continuous.activation_cost_reduction_for`'s
# ``attach_kind`` branch). The target slot is closed to "~"; any other target
# ("enchanted creature", Strong Back) stays unclaimed.
EQUIP_ACTIVATION_DISCOUNT_RE = re.compile(
    r"equip abilities you activate(?P<slot> of other equipment| that target ~)? "
    r"cost \{(?P<n>\d+)\} less to activate\.?",
    re.IGNORECASE,
)

# An Equipment's own "Equip {N}. This ability costs {M} less to activate for
# each <X>." (Plate Armor, Warrior's Blades). The keyword spec still supplies
# the equip ability and its printed cost; this row only carries the discount.
# Closed vocabulary: the count must be one the engine evaluates.
EQUIP_SELF_DISCOUNT_RE = re.compile(
    r"equip (?:\{[^}]+\})+\. this ability costs \{(?P<n>\d+)\} less to activate "
    r"for each (?P<what>other equipment you control|\+1/\+1 counter on the creature it targets)\.?",
    re.IGNORECASE,
)

# "This spell costs {N} less to cast for each `<X>`."  (RULE 601.2f
# self-scoped discount printed on the spell itself — Embercleave, Ghoultree,
# Primeval Protector, Vanquish the Horde) — ``affects="self"`` with a `per`
# count selector, the "cost {N} less for each <board count>" shape Delve/
# Affinity already exercise via `continuous.self_cost_reduction_for`. PAR-120:
# one row for every `<X>`; the phrase is read by the shared `count_phrase`
# grammar, and `_SELF_COST_PER_PHRASES` keeps the phrases that grammar can't
# express (a per-turn history, RULE 700.8's party matching, basic land types)
# plus the ones earlier per-phrase rows already emitted as named selectors —
# kept verbatim so no already-covered card's spec changes. This replaces five
# near-identical rows (attacking / history / party / graveyard / basic land
# types) that differed only in which selector their phrase mapped to.
SELF_COST_REDUCTION_FOR_EACH_RE = re.compile(
    r"this spell costs \{(?P<n>\d+)\} less to cast for each (?P<phrase>.+?)\.?",
    re.IGNORECASE,
)
#: "This spell costs {X} less to cast, where X is the greatest power among creatures you control." (Ghalta, The Great
#: Henge, Molten Monstrosity) — one generic less per point of the amount, so the same `per` selector a "for each"
#: phrase gives, read from the shared amount grammar (`count_phrase.parse_amount_phrase`).
SELF_COST_REDUCTION_WHERE_X_RE = re.compile(
    r"this spell costs \{x\} less to cast(?P<this_way> this way)?, where x is (?P<phrase>.+?)\.?",
    re.IGNORECASE,
)
DURING_OTHER_TURNS_COST_RE = re.compile(
    r"during turns other than yours, (?P<rest>.+ cost .+)", re.IGNORECASE,
)
_SELF_COST_PER_PHRASES: dict[str, str] = {
    "attacking creature": "attacking_creatures",
    "attacking creature you control": "attacking_creatures_you_control",
    # RULE 506.2: the attackers declared against the caster (Sentry Bot).
    "creature attacking you": "creatures_attacking_you",
    # RULE 508.1a: declared attackers this turn, not the live attacking set.
    "creature that attacked this turn": "creatures_attacked_this_turn",
    "creature that died this turn": "creatures_died_this_turn",
    "opponent you attacked this turn": "opponents_attacked_this_turn",  # Battlefront
    # RULE 700.8: a bipartite Cleric/Rogue/Warrior/Wizard matching.
    "creature in your party": "creatures_in_your_party",
    "basic land type among lands you control": "basic_land_types_among_lands_you_control",
    # RULE 701.17a: the `SACRIFICE` events' card types this turn (Korvold, Gleeful Glutton).
    "card type among permanents you've sacrificed this turn": "card_types_among_permanents_sacrificed_this_turn",
}


def self_cost_per(phrase: str) -> "Optional[str | dict]":
    """`<X>` of "costs {N} less to cast for each `<X>`" → a `continuous.
    count_selector` argument, or ``None`` (fail-closed)."""

    phrase = phrase.strip().lower()
    if phrase in _SELF_COST_PER_PHRASES:
        return _SELF_COST_PER_PHRASES[phrase]
    return parse_count_phrase(phrase)


SECOND_SPELL_COST_REDUCTION_RE = re.compile(
    r"the second spell you cast each turn costs \{(?P<n>\d+)\} less to cast",
    re.IGNORECASE,
)
SELF_GRAVEYARD_SHUFFLE_RE = re.compile(
    r"if ~ would be put into a graveyard from anywhere, reveal ~ and shuffle it into its owner'?s library instead",
    re.IGNORECASE,
)
# "This spell costs {N} less to cast if `<condition>`." (RULE 601.2f,
# Ghostfire Slice-shaped) — the self cost-reduction sibling of the above,
# gated by RULE 613.6's own "as long as `<condition>`" whitelist
# (`static_condition`) instead of a `per`-scaled count, so it reuses that
# same evaluator rather than growing a second one.
SELF_COST_REDUCTION_IF_RE = re.compile(
    r"this spell costs \{(?P<n>\d+)\} less to cast (?:if|as long as) (?P<cond>.+)",
    re.IGNORECASE,
)
SELF_COST_REDUCTION_COLORED_RE = re.compile(
    r"this spell costs (?P<symbols>(?:\{[WUBRG]\})+) less to cast if (?P<cond>.+)",
    re.IGNORECASE,
)


#: "…if it targets a `<criteria>`." (Ajani's Response / Knockout Blow /
#: Depower cycle) — a RULE 601.2f discount gated on the spell's own chosen
#: target rather than on board state, so it emits ``reduce_if_targets`` (a
#: criteria dict `continuous._obj_matches_target_criteria` checks) instead
#: of ``active_if``. Only the recognised permanent qualifiers below.
_TARGET_CRIT_KEYWORDS = frozenset({
    "flying", "trample", "first strike", "deathtouch", "lifelink", "vigilance",
    "reach", "menace", "haste", "defender", "hexproof", "indestructible",
})
_TARGET_CRIT_HEADS = frozenset({"creature", "permanent", "artifact", "enchantment", "land", "spell"})
_COLOR_WORD_TO_LETTER = COLOR_LETTERS
_TARGETS_CRITERIA_RE = re.compile(
    r"it targets an? (?P<body>[a-z' +/\-\d]+?)"
    r"(?P<ctrl> you control| you don'?t control)?$",
    re.IGNORECASE,
)


def targets_reduction_criteria(cond: str) -> "dict | None":
    """"it targets a `<criteria>`" → a criteria dict, or ``None`` (fail-closed
    for any shape not in the recognised vocabulary — a spell target, a
    mana-value cap, "a creature card", a counter clause, …).

    ``body`` is parsed word by word: an optional ``tapped``/``attacking``/
    ``blocking``/``legendary``, an optional colour, an optional subtype (or
    ``X or Y`` pair), an optional head noun, an optional ``token``, an
    optional ``with <keyword>`` — anything left over is unrecognised and the
    whole thing fails closed."""
    m = _TARGETS_CRITERIA_RE.fullmatch(cond.strip())
    if m is None:
        return None
    body = m.group("body").strip().lower()
    crit: dict = {}
    ctrl = (m.group("ctrl") or "").strip().lower()
    if ctrl == "you control":
        crit["controller"] = "you"
    elif ctrl.startswith("you don"):
        crit["controller"] = "not_you"

    kw_m = re.search(r" with ([a-z ]+)$", body)
    if kw_m:
        kw = kw_m.group(1).strip()
        if kw not in _TARGET_CRIT_KEYWORDS:
            return None
        crit["keyword"] = kw
        body = body[: kw_m.start()].strip()

    words = body.split()
    if words and words[-1] == "token":
        crit["is_token"] = True
        words = words[:-1]

    flags = {"tapped", "attacking", "blocking", "legendary"}
    while words and words[0] in flags:
        w = words.pop(0)
        crit["tapped" if w == "tapped" else w] = True
        if w == "legendary":
            crit["legendary"] = True
        elif w in ("attacking", "blocking"):
            crit[w] = True

    if words and words[0] in _COLOR_WORD_TO_LETTER:
        crit["color"] = _COLOR_WORD_TO_LETTER[words.pop(0)]

    head = None
    if words and words[-1] in _TARGET_CRIT_HEADS:
        head = words.pop()
    if head == "spell" and words and words[-1] in _TARGET_CRIT_HEADS:
        # "a creature spell" (Out of Air) — the word before "spell" is the
        # real card-type constraint.
        head = words.pop()
    if head and head not in ("permanent", "spell"):
        # "spell" (Mystical Dispute's "a blue spell") on its own adds no
        # card-type constraint — a spell on the stack still resolves through
        # `_obj_matches_target_criteria` off its underlying object's card.
        crit["card_type"] = head

    # Whatever's left is the subtype ("spider", "mount or vehicle").
    if words:
        subs = " ".join(words)
        parts = [p for p in subs.split(" or ") if p]
        if any(not p.isalpha() for p in parts):
            return None  # a stray "+1/+1 counter" etc. — fail closed
        if len(parts) > 1:
            crit["subtype_any"] = parts
        else:
            crit["subtype"] = parts[0]

    # A discount gated on nothing (bare "a permanent") is a no-op; a lone
    # ``controller`` scope is real (This Town Ain't Big Enough).
    return crit or None


# "Each player can't cast more than N spell(s) each turn."  (RULE 601-area
# prohibition, Eidolon of Rhetoric/Rule of Law/Archon of Emeria) — a flat,
# unscoped per-player-per-turn cast cap; ``normalize`` already folds a
# spelled-out "one" to "1" before this ever runs.
CAST_LIMIT_RE = re.compile(
    r"each player can'?t cast more than (?P<n>\d+) spells? each turn", re.IGNORECASE
)

#: "Your opponents can't cast spells from anywhere other than their
#: hands." (Drannith Magistrate) — `continuous.cast_prohibited`'s new
#: ``hand_only`` zone check.
CANT_CAST_OPPONENTS_HAND_ONLY_RE = re.compile(
    r"your opponents can'?t cast spells from anywhere other than their hands", re.IGNORECASE
)

#: The **noncreature**-scoped sibling (Deafening Silence) — `continuous.
#: max_noncreature_spells_per_turn`'s own ``noncreature`` flag.
CAST_LIMIT_NONCREATURE_RE = re.compile(
    r"each player can'?t cast more than (?P<n>\d+) noncreature spells? each turn", re.IGNORECASE
)

# "You may play [an|N] additional land[s] on/during each of your/their
# turns."  (RULE 305.2 permission static, Exploration/Dryad of the Ilysian
# Grove/Azusa-shaped) or its unscoped "Each player may play …" sibling
# (Rites of Flourishing/Storm Cauldron) — `EXTRA_LAND_DROP_RE.group("n")`
# via `count_of` handles both "an"/"a" and a digit count (Azusa's "two
# additional lands"→"2" after `normalize`'s spelled-out-number fold). The
# one-turn "…this turn" phrasing (Explore-shaped) is a different, resolve-
# time-effect shape claimed by `catalogue.handlers`' `extra_land_play` row
# instead, not this static family.
EXTRA_LAND_DROP_RE = re.compile(
    rf"(?P<subject>you|each player) may play {COUNT} additional lands? "
    r"(?:on|during) each of (?:your|their) turns",
    re.IGNORECASE,
)

# "You have no maximum hand size."  (RULE 402.2, A-Wizard Class/Body of
# Knowledge-shaped) or "Players have no maximum hand size." (Anvil of
# Bogardan/Folio of Fancies, unscoped). The durational "…for the rest of the
# game"/"…until your next turn" one-shot variants (Enter the Infinite/
# Choice of Fortunes-shaped) don't fullmatch this — they're a different,
# resolve-time-granted shape, deliberately left unclaimed.
NO_MAX_HAND_SIZE_RE = re.compile(
    r"(?P<subject>you have|players have) no maximum hand size", re.IGNORECASE
)

# "Your maximum hand size is reduced by 3." (Thought Eater) / "Each opponent's maximum hand size is
# reduced by 1." (Gnat Miser) / "Your maximum hand size is increased by 1." (Minamo Scrollkeeper) — the
# numeric RULE 402.2 sibling of `NO_MAX_HAND_SIZE_RE`, read by `continuous.hand_size_modifier_for`.
HAND_SIZE_MODIFIER_RE = re.compile(
    r"(?P<subject>your|each opponent's|each player's) maximum hand size is "
    r"(?P<direction>reduced|increased) by (?P<n>\d+)", re.IGNORECASE
)
# "Your maximum hand size is five." (MEC-129, normalized to a digit) — the absolute
# setter, read by `continuous.set_maximum_hand_size`.
HAND_SIZE_SET_RE = re.compile(r"(?P<subject>your) maximum hand size is (?P<n>\d+)", re.IGNORECASE)
HAND_SIZE_SUBJECT_AFFECTS = {"your": "you", "each opponent's": "opponents", "each player's": "each_player"}

# "Players skip their untap steps." (RULE 502.3-adjacent, Stasis) — the last
# open member of the "players can't `<verb>`" family
# (`docs/implementation-state/BACKLOG.md`'s MEC-12 entry). Unconditional and
# unscoped, unlike `NO_MAX_HAND_SIZE_RE` above: no card in the cache prints
# a "you"-only version of this clause, so there's no ``subject`` group to
# capture.
SKIP_UNTAP_STEPS_RE = re.compile(r"players skip their untap steps", re.IGNORECASE)

# "Players can't gain life." (Everlasting Torment / Forsaken Wastes / Havoc
# Festival / Leyline of Punishment) / "Your opponents can't gain life."
# (Erebos, God of the Dead) / "If a player would gain life, that player
# gains no life instead." (Sulfuric Vortex — a replacement-phrased
# equivalent) — a standing, board-wide RULE 119.3-adjacent rule
# modification, distinct from `effect_rows.destroy_exile_counter._CANT_GAIN_LIFE_RE`'s turn-scoped
# rider. Consulted live by `RulesEngine.gain_life` via
# `continuous.life_gain_prohibited_for`.
PLAYERS_CANT_GAIN_LIFE_RE = re.compile(
    r"(?:(?P<scope>players|your opponents) can'?t gain life"
    r"|if a player would gain life, that player gains no life instead)",
    re.IGNORECASE,
)

# "Skip your draw step." (MEC-38, Necropotence / Yawgmoth's Bargain /
# Solitary Confinement / Dragon Appeasement) — the *self*-scoped, standing
# step skip, `EffectSpec("skip_step", …)` (a `StaticAbility` layer read live
# by `RulesEngine.should_skip_step` via `continuous.skipped_steps_for`,
# unrelated to `SKIP_UNTAP_STEPS_RE`'s board-wide Stasis effect above). The
# effect had shipped for MEC-38 but only via a hand-authored catalogue
# entry; this is its oracle-text route. `should_skip_step` is consulted with
# every step's own name, so "untap"/"upkeep" work the same way — but "draw"
# is the only form real cards print, and untap/upkeep are left out until one
# does (fail-closed).
SKIP_YOUR_STEP_RE = re.compile(r"skip your (?P<step>draw) step", re.IGNORECASE)

# "Players can't cast spells from graveyards or libraries." (RULE
# 601.3a-adjacent, Grafdigger's Cage/Weathered Runestone) — the last open
# member of MEC-12's "players can't <verb>" family sweep.
# MEC-43 round 2 (Kunoros, Hound of Athreos): "Players can't cast spells
# from **graveyards**." — the graveyard-only sibling, no "or libraries" —
# the trailing zone clause is optional so both phrasings match.
GRAVEYARD_LIBRARY_CAST_PROHIBITION_RE = re.compile(
    r"players can'?t cast spells from graveyards(?P<libraries> or libraries)?", re.IGNORECASE
)
# "Creature cards in graveyards and libraries can't enter the battlefield."
# (Grafdigger's Cage) or "Nonland permanent cards in graveyards and
# libraries can't enter the battlefield." (Weathered Runestone), or just
# "Creature cards in **graveyards** can't enter the battlefield." (MEC-43
# round 2, Kunoros — no "and libraries") — the card-type word feeds
# `continuous.graveyard_library_entry_prohibited`'s ``card_type`` param
# verbatim, except "nonland permanent" which is its own sentinel (checked
# separately from the plain `_CARD_TYPE_ATTRS` words). Deliberately *not*
# `subgrammars.CARD_TYPE_WORD_ALT`: this row wants four of the five printed
# types (no real card here says "land cards … can't enter") plus the
# non-card-type "nonland permanent" sentinel — a different member set, so it
# stays hand-rolled rather than forcing the shared alternation to fit
# (PAR-63).
GRAVEYARD_LIBRARY_ENTRY_PROHIBITION_RE = re.compile(
    r"(?P<type>creature|artifact|enchantment|planeswalker|nonland permanent) cards "
    r"in graveyards(?P<libraries> and libraries)? can'?t enter the battlefield",
    re.IGNORECASE,
)

# "You may choose not to untap ~ during your untap step."  (RULE 502.1
# self-scoped opt-out, Rubinia Soulsinger/Hivis of the Scale/The Pandorica-
# shaped) — `~` covers all three printed subject wordings ("this creature"/
# "this artifact"/"this land", folded by `normalize._fold_self_reference`)
# uniformly. Unlike `NO_UNTAP_RE` below (an unconditional restriction), this
# only *permits* skipping untap — actually skipping it needs the controller
# to separately toggle `GameObject.skip_untap` on (`GameEngine.
# set_skip_untap`). Deliberately excludes every targeted/imposed "doesn't
# untap … for as long as this remains tapped" variant (Sand Squid/Ice Floe-
# shaped) — a different family entirely (an activated ability locking a
# *different* permanent), not "you may choose" at all.
NO_UNTAP_OPTIONAL_RE = re.compile(
    r"you may choose not to untap ~ during your untap step", re.IGNORECASE
)

# "You gain life rather than lose life from radiation."  (RULE 729.1a,
# Strong, the Brutish Thespian) — a per-player permission static redirecting
# a ``cause="radiation"`` life loss into a gain instead
# (`continuous.has_radiation_life_gain`, `RulesEngine.lose_life`). No
# "players gain..." unscoped variant exists in the real card pool yet, so
# unlike `NO_MAX_HAND_SIZE_RE` this has no ``subject`` alternation.
RADIATION_LIFE_GAIN_RE = re.compile(
    r"you gain life rather than lose life from radiation", re.IGNORECASE
)

# "~ doesn't untap during your untap step."  (RULE 502.3-adjacent
# self-restriction, Basalt Monolith/Grim Monolith/Mana Vault) — `~` is the
# self-reference token `normalize._fold_self_reference`/`_fold_self_name`
# folds "this artifact"/the card's own printed name to (Card-pool Batch 1),
# so this must match the folded form, not the literal "this <type>" text
# that normalize never leaves in place.
NO_UNTAP_RE = re.compile(
    r"~ doesn'?t untap during your untap step(?: if (?P<cond>.+))?", re.IGNORECASE
)

# "~ isn't a creature." (RULE 613.7f, always printed wrapped in a RULE 613.6
# "as long as <condition>, " gate — the Theros gods' own devotion threshold —
# so this row is only ever reached through `conditional_static_specs`,
# never as a bare unconditional clause: no real card removes creature-ness
# unconditionally.) `type_change`'s existing `remove_types` param already
# does the layer-4 removal; nothing new needed but the phrase.
NOT_A_CREATURE_RE = re.compile(r"~ isn'?t a creature", re.IGNORECASE)

# "Creatures with power N or greater don't untap during their controllers'
# untap steps."  (Meekstone) — the unattached group-scoped sibling of
# `NO_UNTAP_RE`/`NO_UNTAP_ATTACHED_RE` above: no `~`/attached subject at
# all, just a board-wide power qualifier, so it reuses `no_untap`'s ordinary
# ``affects="all_creatures"`` selector plus the standard ``min_power``
# post-filter (`continuous.group_selector_objects`) rather than a new field.
NO_UNTAP_GROUP_POWER_RE = re.compile(
    r"creatures with power (?P<n>\d+) or greater don'?t untap during their "
    r"controllers'? untap steps?",
    re.IGNORECASE,
)

# "Nonbasic lands don't untap during their controllers' untap steps."
# (Back to Basics) — `no_untap`'s unconditional, unlimited-count sibling to
# `UNTAP_CAP_RE`'s Winter Moon-shaped "…can't untap more than one nonbasic
# land…" (a cap that still lets the *first* one through each turn): this
# one blocks every nonbasic land, every turn. ``affects="all_lands"`` +
# the ordinary ``nonbasic`` selector `group_selector_objects` already
# applies to every other static family — no new engine code.
NO_UNTAP_NONBASIC_LANDS_RE = re.compile(
    r"nonbasic lands don'?t untap during their controllers'? untap steps?",
    re.IGNORECASE,
)

# "Players can't untap more than N [nonbasic] `<type>` during their untap
# steps."  (RULE 502.3-adjacent, Static Orb's "permanents"/Winter Moon's
# "nonbasic land" — Winter Orb's own "one land" is hand-authored, see
# `card_registry._winter_orb`, but shares this same `untap_cap` family)
# — always printed either bare (Winter Moon) or under a leading "as long as
# this artifact is untapped," gate peeled off by `conditional_static_specs`
# before this ever sees the clause (Static Orb).
UNTAP_CAP_RE = re.compile(
    r"players can'?t untap more than (?P<n>\d+) (?P<nonbasic>nonbasic )?"
    r"(?P<word>artifacts?|creatures?|lands?|permanents?) during their untap steps?",
    re.IGNORECASE,
)

# "Creatures entering don't cause abilities to trigger."  (RULE 603
# prohibition, Tocatli Honor Guard/Hushwing Gryff/Torpor Orb) — global: it
# silences *every* triggered ability (including the entering creature's own)
# that would otherwise fire off a matching battlefield-entry event, for as
# long as this static is in play, regardless of whose creature it is.
# "…or dying…" (MEC-43 round 2, Hushbringer) adds the DIES sibling as a
# second `EffectSpec` rather than widening this one — the two are
# independent `EventType`s the layer engine checks separately.
TRIGGER_PROHIBITION_RE = re.compile(
    r"(?P<word>[a-z]+) entering(?P<dying> or dying)? don'?t cause abilities to trigger", re.IGNORECASE
)

# "[Nonbasic] <type>[s] [and [nonbasic] <type>[s]] your opponents control
# enter tapped."  (RULE 614.1, board-wide — Manglehorn/Dauntless
# Dismantler's "artifacts", Archon of Emeria's "nonbasic lands", Blind
# Obedience's "artifacts and creatures", Thalia, Heretic Cathar's own mixed
# "creatures and nonbasic lands" — MEC-43 round 2) — distinct from
# `card_registry.enters_tapped` (a card's own printed tapped-entry
# clause about *itself*): this is a standing effect from a *different*
# permanent, scoped to "your opponents". Each ``and``-joined part carries
# its *own* optional "nonbasic" prefix (Thalia's creatures aren't nonbasic-
# restricted, only her lands are) rather than one flag for the whole
# clause; one spec is emitted per part (Blind Obedience/Thalia alike).
OPPONENTS_ENTER_TAPPED_RE = re.compile(
    r"(?P<parts>(?:nonbasic )?[a-z]+(?: and (?:nonbasic )?[a-z]+)*) your opponents control enter tapped",
    re.IGNORECASE,
)

# "[Nonbasic] <type>[s] [and <type>[s]] enter tapped."  (RULE 614.1,
# board-wide, Root Maze-shaped) — the *unscoped* sibling of
# `OPPONENTS_ENTER_TAPPED_RE`: no "your opponents control" qualifier at
# all, so it applies to every player's matching permanents, including the
# static's own controller's.
ALL_ENTER_TAPPED_RE = re.compile(
    r"(?:(?P<nonbasic>nonbasic) )?(?P<words>[a-z]+(?: and [a-z]+)?) enter tapped",
    re.IGNORECASE,
)

#: WUBRG basic-land-type word → the mana colour it taps for (RULE 305.6) —
#: a small local copy of `game/mana_abilities.BASIC_LAND_MANA`'s data (the
#: front-end can't import `game/`, and it's five literal pairs, not worth a
#: shared-data indirection).
_BASIC_LAND_COLOR: dict[str, str] = {
    "plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G",
}
#: Singular/plural basic-land-type word → its canonical (capitalised) name.
BASIC_LAND_WORDS: dict[str, str] = {}
for _name in _BASIC_LAND_COLOR:
    BASIC_LAND_WORDS[_name] = _name.capitalize()
    BASIC_LAND_WORDS[_name + "s"] = _name.capitalize()
del _name

# "Nonbasic lands are <BasicType>."  (RULE 613.5 full layer-4 type overwrite,
# board-wide — Magus of the Moon/Blood Moon) — unlike `type_change`'s ordinary
# "are also creatures" shape (which only *adds* a type), this *replaces* the
# land's subtypes outright (RULE 613.5's "loses all other types"). The
# resulting basic land's mana ability (RULE 305.6) is *not* a separate
# hand-paired `grant_mana_ability` spec here — `game/mana_abilities.py`'s
# `mana_abilities_for` derives it generically off whatever basic land types
# `continuous.has_subtype` reports once every layer-4 effect has resolved, so
# it stays correct however this stacks with an *additive* type grant like
# Urborg/Yavimaya's (`LAND_IS_BASIC_TYPE_RE` below) regardless of which
# effect's timestamp is newer.
TYPE_OVERWRITE_RE = re.compile(r"nonbasic lands are (?P<word>[a-z]+)", re.IGNORECASE)

# "Each land is a <BasicType> in addition to its other land types." (RULE
# 613.4a additive land-type grant, board-wide — Urborg, Tomb of Yawgmoth/
# Yavimaya, Cradle of Growth) — the land-type sibling of `_GROUP_CHOSEN_TYPE_
# RE`'s "…the chosen type in addition to its other types", except the type
# here is a fixed literal rather than an interactively chosen one. Emits only
# an `add_subtypes` `type_change` — same as `TYPE_OVERWRITE_RE` above, the
# matching mana ability isn't a paired spec; it falls out of the generic
# RULE 305.6 derivation once the land's subtype set is resolved.
LAND_IS_BASIC_TYPE_RE = re.compile(
    r"each land is a (?P<word>[a-z]+) in addition to its other land types", re.IGNORECASE
)

# "You may play lands [and cast [noncreature] spells [with mana value N or
# greater]] from the top of your library."/"You may cast [noncreature]
# spells [with mana value N or greater] from the top of your library."
# (RULE 701-adjacent standing permission, Oracle of Mul Daya/Glarb, Calamity's
# Augur/Future Sight/Bolas's Citadel/Elsha of the Infinite-shaped) — the
# generic sibling of the two hand-authored `top_library_permission` entries
# in `game/card_catalogue` (left registered rather than migrated; no
# harm in both existing side by side, the hand-authored registry always
# takes precedence for a registered card). ``TOP_LIBRARY_VERB_PARAMS``'
# five printed phrasings are a closed vocabulary, same precedent as
# `_ATTACHED_SUBJECTS`: "noncreature" is the one card-type restriction any
# real card needs today (Elsha) — not a general subtype filter.
#
# An optional trailing "If you cast a spell this way, ..." sentence on the
# *same* printed line (Elsha/Bolas's Citadel both fold their conditional
# tail into the permission's own paragraph, not a separate line) captures
# each card's own further conditional: "you may cast it as though it had
# flash" (``grants_flash``) or "pay life equal to its mana value rather than
# pay its mana cost" (``life_payment`` — a RULE 118 alternative cost,
# substituted automatically whenever a spell is actually cast this way, not
# offered as a separate choice — see `game/top_library.py`'s
# `top_library_life_payment_required`/`game/game_engine.py`'s
# `_top_library_life_payment`).
TOP_LIBRARY_VERB_PARAMS: dict[str, dict] = {
    "play lands and cast noncreature spells": {
        "play_lands": True, "cast_spells": True, "noncreature_only": True,
    },
    "play lands and cast spells": {"play_lands": True, "cast_spells": True},
    "play lands": {"play_lands": True},
    "cast noncreature spells": {"cast_spells": True, "noncreature_only": True},
    "cast spells": {"cast_spells": True},
}
TOP_LIBRARY_TAILS: dict[str, str] = {
    "you may cast it as though it had flash": "grants_flash",
    "pay life equal to its mana value rather than pay its mana cost": "life_payment",
}
TOP_LIBRARY_PERMISSION_RE = re.compile(
    r"you may (?P<verb>" + "|".join(re.escape(v) for v in TOP_LIBRARY_VERB_PARAMS) + r")"
    r"(?: with mana value (?P<mv>\d+) or greater)?"
    r" from the top of your library"
    r"(?:\. if you cast a spell this way, (?P<tail>"
    + "|".join(re.escape(t) for t in TOP_LIBRARY_TAILS) + r"))?",
    re.IGNORECASE,
)

#: PAR-88 / RULE 305.2: Crucible of Worlds/Ramunap Excavator's standing
#: permission is a land-only graveyard sibling of the top-library play grant.
GRAVEYARD_LAND_PLAY_PERMISSION_RE = re.compile(
    r"you may play lands from your graveyard", re.IGNORECASE
)

#: "You may look at the top card of your library any time." (Sphinx of Jwar
#: Isle/Fblthp, Lost on the Range/Glowcap Lantern/Iron Lad, Diverging
#: Destiny/Vesuvan Drifter-shaped — ~57 real cards) — the standalone,
#: look-only sibling of `TOP_LIBRARY_PERMISSION_RE` just above (whose own
#: grants already always carry ``look=True``, since playing from the top
#: implies seeing it). A genuine independent RULE 400.2-adjacent visibility
#: grant when printed with no accompanying play/cast permission, not the
#: purely-redundant sibling `segmenter._PLAY_WITH_TOP_REVEALED_RE` is (that
#: one is always paired with a play/cast grant on the same card). Previously
#: claimed as a no-op line at the `segmenter.segment_line` level; recognized
#: here instead so it reaches `game/top_library.py`'s
#: `may_look_at_top_of_library`, which `_redact_hidden_zones`'s
#: ``top_library_visible`` view flag and the goldfish/shared board's
#: library-zone UI already fully support for any active grant.
LOOK_AT_TOP_ANY_TIME_RE = re.compile(
    r"you may look at the top card of your library any time", re.IGNORECASE
)


# "~ can be your commander."  (RULE 903.3 deck-legality permission,
# Jeska/Tevesh Szat-shaped) — a plain-text line with **no in-game behavioral
# effect** (nothing about the battlefield/stack/turn structure changes), so
# unlike every family above this claims the line and emits *nothing* at all —
# the same "claim it, contribute no spec" treatment RULE 614.1 tapped-entry/
# entry-counter clauses get in `gate._process_line`. A generic self-reference
# match (``~``, folded from the card's own name by `normalize`), not
# hardcoded to any one card name.
_COMMANDER_ELIGIBLE_RE = re.compile(r"~ can be your commander", re.IGNORECASE)
_ANY_NUMBER_IN_DECK_RE = re.compile(r"a deck can have any number of cards named ~", re.IGNORECASE)


def commander_eligibility_line(line: str) -> bool:
    """Whether ``line`` is a RULE 903.3 "~ can be your commander." sentence —
    see `_COMMANDER_ELIGIBLE_RE`. Claimed at the `gate._process_line` level
    (before this module's `static_effect_specs` even runs), not through an
    `EffectSpec`, since it carries no behaviour to bind."""
    return bool(_COMMANDER_ELIGIBLE_RE.fullmatch(line.strip().rstrip(".").strip()))


def deck_any_number_line(line: str) -> bool:
    """Whether ``line`` is RULE 100.2a's inert deck-construction exception."""
    return bool(_ANY_NUMBER_IN_DECK_RE.fullmatch(line.strip().rstrip(".").strip()))
