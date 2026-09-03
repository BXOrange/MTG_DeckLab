"""Static continuous-ability handlers — anthems and keyword grants (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md (effect-family handlers), RULE 613
(the layer system these feed). A *permanent's* standing sentence like "Other
creatures you control get +1/+1" or "Goblins you control have haste" is a
**static** ability, not a one-shot effect — it reshapes other permanents
continuously while its source is in play. This module recognises those two
families and emits `EffectSpec`s the binder turns into `StaticAbility`s
(`anthem` → layer 7c, `grant_keyword` → layer 6), with a tribal **subtype**
filter for lords (Goblin King, Lord of Atlantis).

Only creature scopes are claimed — "creatures you control", a plural creature
type ("goblins you control"), or "<type> creatures you control" — with a small
block-list keeping non-creature scopes ("artifacts you control …") from being
mis-read as anthems (fail-closed). Anything with an "until end of turn" tail is
a *temporary* effect an instant grants, not a static ability, and won't
full-match here.

A second, closed family recognises an Aura/Equipment/Fortification's own
attached-permanent buff — "equipped creature gets +2/+2", "enchanted creature
has trample" (RULE 303.4/301.5, docs/11 §6 "attached_permanent"). Unlike the
"you control" scopes above, these five printed subject phrases
(`_ATTACHED_SUBJECTS`) always resolve off the ability's own source's
`attached_to`, so they emit `affects="attached_permanent"` rather than any
controller-scoped selector; `game/continuous.py`'s `group_selector_objects`
already honours that selector for both `anthem` and `grant_keyword` (it's the
same code path the hand-authored Armadillo Cloak entry in
`game/ability_catalogue.py` uses) — only the parser recognition was missing.

A third family (Card-pool Batch 7) recognises RULE 601.2b's "as ~ enters,
choose a creature type/color" (`enter_choice_specs`, a sibling entry point
segmenter.py calls separately since it wraps as an ``enter_replacement``
`AbilitySpec`, not ``static``) plus the "… of the chosen type/color …"
dynamic tail on the anthem/grant families above (`_CHOSEN_TAIL`) and "~ is
the chosen type in addition to its other types" (`_IS_CHOSEN_TYPE_RE`) — see
`game/continuous.py`'s ``subtype_from_source``/``color_from_source``/
``add_subtypes_from_source`` params for how the layer engine reads the
choice back.

A fourth family (Card-pool Batch 8) recognises three "permission" statics
that aren't about a permanent's own characteristics at all: "you may play an
additional land on each of your turns" (`extra_land_drop`), "you have no
maximum hand size" (`no_max_hand_size`), and "you may choose not to untap ~
during your untap step" (`no_untap_optional`) — all consulted by
per-*player*/per-*object* helpers in `game/continuous.py` rather than the
RULE 613 layer engine proper (the same treatment `cast_limit`/`draw_limit`/
`no_untap` already got).

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import re
from typing import Any, Callable, NamedTuple, Optional

from ..spec import EffectSpec, ParserProvenance
from .handlers import (
    ONCE_PER_TURN_MARKER,
    SORCERY_SPEED_MARKER,
    _split_keywords_with_parametric,
)
from .keywords import KEYWORDS, KeywordShape, keyword_slug, resolve_keyword
from .subgrammars import CANT_BE_COUNTERED_RE, COUNT, DEVOTION, count_of, devotion_selector

#: Trigger events a granted triggered ability can be safely re-scoped to a
#: *different* object each time it's granted (`continuous.
#: _granted_trigger_condition` matches by the event's own subject key —
#: ``instance_id`` for the RULE 603.1 object-subject four, ``source_id`` for
#: ``DAMAGE`` — see `continuous._GRANTED_EVENT_KEYS`).
#:
#: ``STEP_BEGIN`` is the odd one out: a RULE 500.7 phase trigger ("At the
#: beginning of your upkeep, …", Commander's Authority/Clawing Torment/Aura
#: Flux-shaped) has no object subject at all, so it isn't re-scoped by
#: identity — instead the grant threads the segmenter's ``phase_relation``
#: through to `continuous._granted_trigger_condition`, which resolves "your"
#: against the **granted-to** permanent's own controller. That's what makes
#: it safe to regrant: each affected permanent's copy fires on its own
#: controller's upkeep, exactly as the printed reminder text on these cards
#: reads.
#: ``LIFE_GAINED`` is a second odd one out alongside ``STEP_BEGIN``: RULE
#: 119.3's "Whenever **you** gain life, …" (Field-Tested Frying Pan/Light of
#: Promise/Sunbond) also carries no object-identity key — it's player-
#: scoped (`player_id`), re-scoped the same "resolve against the granted-to
#: permanent's own controller" way `game/continuous.py`'s
#: `_PLAYER_SUBJECT_GRANTED_EVENTS` documents.
_GRANTABLE_TRIGGER_EVENTS = frozenset(
    {"ENTERS_BATTLEFIELD", "LEAVES_BATTLEFIELD", "DIES", "ATTACKS", "BLOCKS", "DAMAGE",
     "STEP_BEGIN", "LIFE_GAINED"}
)

#: MEC-55: inner-static `affects` scopes that can't be re-granted to a
#: group — "self"/"attached_permanent" only mean something relative to a
#: single host permanent, which a regranted static has no notion of.
_REGRANT_UNSUPPORTED_AFFECTS = frozenset({"self", "attached_permanent"})

#: Type words that are *not* creature subtypes — a scope built on one of these
#: isn't a creature anthem/grant, so we don't claim it. ``enchanted``/
#: ``equipped`` belong here too (PAR-3 spot-check, Greater Auramancy's
#: "Enchanted creatures you control have shroud."): they're a characteristic
#: filter, not a subtype — `_has_subtype` would never see "Enchanted" on any
#: real creature's type line, so guessing one as a subtype silently matches
#: nothing instead of the intended creatures. The engine's own selector for
#: this shape (`continuous.py`'s ``enchanted_or_equipped_creatures_you_
#: control``) combines *both* qualities, which "enchanted creatures" alone
#: would over-match — a genuinely separate, still-open parser gap, not a
#: PAR-3 widening; fail-closed here rather than half-modeled.
_NONCREATURE_TYPES: frozenset[str] = frozenset(
    {"creature", "artifact", "enchantment", "land", "permanent", "planeswalker", "token",
     "enchanted", "equipped"}
)

#: RULE 300.2's artifact subtypes that are never also a creature subtype (a
#: Vehicle isn't a creature until crewed, RULE 702.122a) — a bare "Vehicles
#: [you control]" scope must not fall into `_scope`'s ordinary singular-word
#: branch below, which would otherwise silently guess it as a *creature*
#: subtype and scope the anthem to ``creatures_you_control``: a Vehicle that
#: hasn't been crewed yet is never a creature, so that pool would (wrongly)
#: exclude every uncrewed Vehicle instead of the printed "Vehicles you
#: control" reading (Balthier and Fran). Kept distinct from
#: `_NONCREATURE_TYPES` (main *types*, not subtypes) so its own docstring
#: stays accurate; `_vehicle_scope_params`/`_is_vehicle_scope` below are the
#: artifact-subtype-scoped fallback `_ANTHEM_RE`/`_GRANT_RE`/`_QUOTED_GRANT_RE`
#: all reach for exactly this word, the same "fall back to the permanent
#: family instead of guessing a creature subtype" idiom `_permanent_type_
#: scope` already uses for the bare main-type words.
_ARTIFACT_SUBTYPES: frozenset[str] = frozenset({"vehicle"})

#: Colour words → their WUBRG/C symbol, for a colour-scoped anthem.
_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G", "colorless": "C",
}

#: An optional "of the chosen type/color" tail (RULE 601.2b, Adaptive
#: Automaton/Ward Sliver-shaped) — the dynamic sibling of a literal subtype/
#: colour scope, sitting between the "you control" clause and "get"/"have".
_CHOSEN_TAIL = r"(?: of the chosen (?P<chosen>type|color))?"

# "[Other] <scope> [you control] [of the chosen type/color] get +N/+N [and
# have <keywords>]"  (anthem, +grant)
_ANTHEM_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)?"
    rf"{_CHOSEN_TAIL} "
    r"get (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    r"(?: and have (?P<kw>[a-z][a-z, ]*))?",
    re.IGNORECASE,
)
# "[Other] <scope> [you control] [of the chosen type/color] have <keywords>"
# (keyword grant, layer 6)
_GRANT_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)?"
    rf"{_CHOSEN_TAIL} "
    r"have (?P<kw>[a-z][a-z, ]*)",
    re.IGNORECASE,
)
# PAR-31: "Artifacts, creatures, enchantments, and lands you control have
# <keywords>." (Elspeth, Knight-Errant's −8 emblem; also a standing static
# on a handful of permanents) — a keyword grant whose scope is an
# explicit *list* of two or more permanent-type words rather than the
# single word `_GRANT_RE`/`_permanent_type_scope` handles. `_GRANT_RE`'s
# own `body` group is comma-free (`[a-z][a-z ]*?`), so this never
# competes with it. Emits one `grant_keyword` scoped to
# `permanents_you_control` narrowed by the `card_type` list
# `continuous.affected_objects` already ORs (Grand Abolisher-shaped).
_MULTI_PERMANENT_TYPE_GRANT_RE = re.compile(
    r"(?P<body>(?:artifacts|creatures|enchantments|lands|planeswalkers)"
    r"(?:,? (?:and )?(?:artifacts|creatures|enchantments|lands|planeswalkers))+)"
    r" you control have (?P<kw>[a-z][a-z, ]*)",
    re.IGNORECASE,
)
# "Each creature you control with a +1/+1 counter on it has <keywords>."
# (PAR-34 — the Abzan "outlast" cycle: Abzan Falconer / Abzan Battle
# Priest / Ainok Bond-Kin / Hardened Scales-adjacent). A `grant_keyword`
# static scoped to `creatures_you_control` **filtered by counter
# presence** — `continuous.affected_objects`' `has_counter_kind` param
# (MEC-21, Agatha's Soul Cauldron) already narrows the group that way, so
# no engine change. Singular "has" (subject is "each creature"), so it
# doesn't collide with `_GRANT_RE`'s plural "have".
_GROUP_COUNTER_GRANT_RE = re.compile(
    r"each creature you control with a \+1/\+1 counter on it has "
    r"(?P<kw>[a-z][a-z, ]*)",
    re.IGNORECASE,
)

# "[Other] <scope> [you control] [of the chosen type/color] have \"<ability>\""
# (Tyvar Kell/Acidic Sliver-shaped — "Elves you control have '{T}: Add
# {B}.'"/"All Slivers have '{2}, Sacrifice this permanent: ...'") — the
# non-attached sibling of `_ATTACHED_QUOTED_GRANT_RE`/`_ATTACHED_QUOTED_
# ANTHEM_GRANT_RE` above: a group-scoped grant of a *full* ability
# (recursively parsed via `_quoted_ability_grant_effects`, same as the
# attached family) rather than a bare keyword list (`_GRANT_RE` just
# above). Shares `_scope`/`_scope_params` with `_GRANT_RE`/`_ANTHEM_RE` for
# the `affects` (+ subtype/colour/tokens/chosen) params.
_QUOTED_GRANT_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)?"
    rf"{_CHOSEN_TAIL} "
    r'have "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)

# "Commander creatures you own have \"<ability>\"" (Acolyte of Bahamut/Agent
# of the Iron Throne/Candlekeep Sage-shaped cEDH support cards) — a fixed,
# single-phrase scope rather than routing through `_scope`/`_QUOTED_GRANT_RE`'s
# general vocabulary: "commander" is a designation (`GameObject.
# is_commander`), not a card type or creature subtype `_scope` recognises,
# and no real card pairs it with a colour/subtype/token qualifier the
# general grammar would otherwise need to carry. Tried before
# `_QUOTED_GRANT_RE` below (which would otherwise fail closed on it anyway —
# "commander" isn't in `_scope`'s or `_permanent_type_scope`'s vocabulary —
# but keeping the dedicated, unambiguous phrase first avoids relying on that
# fallthrough).
_COMMANDER_CREATURES_QUOTED_GRANT_RE = re.compile(
    r'commander creatures you own have "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)

#: Card-type words the "opponent-scoped"/"prohibition"/"type-overwrite"
#: families below recognise as a `card_type` selector (`continuous.
#: _has_card_type` reads the matching `Card.is_<word>` flag) — deliberately
#: small: only the categories that actually appear in this shape on real
#: cards (a spell-only type like "instant" never does, since none of these
#: clauses talk about spells).
_CARD_TYPE_WORDS: frozenset[str] = frozenset(
    {"artifact", "creature", "enchantment", "land", "planeswalker", "permanent"}
)

# "~'s power and toughness are each equal to the number of <X>."  (RULE 604.3
# characteristic-defining ability — Maro / Molimo / Psychosis Crawler / Dakkon
# Blackblade). The engine layer (`continuous.recompute`'s 7a `pt_cda` pass,
# reading a `count_selector` for both power and toughness) has existed since
# the Ashaya batch but was only ever hand-authored; this is its first oracle-
# text route (PAR-20's named follow-up). `<X>` is matched against a fixed
# whitelist of phrases that already have a `continuous.count_selector` (plus
# `cards_in_your_hand`, added alongside this) — any other phrase fails closed,
# since a CDA reading an unmodeled quantity would silently define the creature
# as 0/0.
_PT_CDA_RE = re.compile(
    r"~'?s power and toughness are each equal to the number of (?P<what>.+)",
    re.IGNORECASE,
)

#: PAR-43: the *single-characteristic* CDA — "~'s power is equal to the
#: number of `<X>`." (Ironroot Warlord / Kolaghan Forerunners / Suki, Kyoshi
#: Warrior — a printed toughness, power defined by a live count) and the
#: rarer toughness form (Traproot Kami). `continuous.recompute`'s 7a
#: `pt_cda` pass already applies `power_count` / `toughness_count`
#: independently, so a spec with only one of them is enough — no engine
#: change. Same `_PT_CDA_SELECTORS` whitelist as `_PT_CDA_RE` (so today only
#: "creatures you control" is claimed; the "forests you control" / "basic
#: land types" toughness cards stay UNMODELED until those selectors exist).
_PT_CDA_SINGLE_RE = re.compile(
    r"~'?s (?P<char>power|toughness) is equal to the number of (?P<what>.+)",
    re.IGNORECASE,
)

#: The `<X>` phrases `_PT_CDA_RE` accepts → their `continuous.count_selector`
#: string. Deliberately exact-match and small: the two PAR-20 named
#: ("cards in your hand", "lands you control") plus the two adjacent ones a
#: real cache card prints in this exact shape and that already have a
#: selector. "creature cards in your graveyard", "cards in all graveyards",
#: "<type> you control" &c. are each a *different* selector and stay
#: unclaimed until one is actually wired.
_PT_CDA_SELECTORS: dict[str, str] = {
    "cards in your hand": "cards_in_your_hand",
    "lands you control": "lands_you_control",
    "cards in your graveyard": "cards_in_your_graveyard",
    "creatures you control": "creatures_you_control",
}

# "Activated abilities of <type>[s] can't be activated."  (RULE 602 prohibition,
# Collector Ouphe/Stony Silence/Null Rod) — global, not "you control"-scoped:
# it silences *every* qualifying permanent's activated abilities, including
# the prohibiting permanent's own if it itself qualifies (Null Rod is an
# Artifact and its printed text carries no self-exemption).
_ACTIVATION_PROHIBITION_RE = re.compile(
    r"activated abilities of (?P<word>[a-z]+) can'?t be activated", re.IGNORECASE
)

# "Activated abilities of <type>[s] your opponents control can't be
# activated." (ENG-28, Linvala Keeper of Silence/Karn the Great Creator) —
# the opponent-scoped sibling of `_ACTIVATION_PROHIBITION_RE` above: that one
# is global (Null Rod silences its own kind too), this one only reaches
# permanents someone *else* controls, so it needs `affects="opponents_
# permanents"` rather than the board-wide default.
_ACTIVATION_PROHIBITION_OPPONENTS_RE = re.compile(
    r"activated abilities of (?P<word>[a-z]+) your opponents control can'?t be activated",
    re.IGNORECASE,
)

# "Your opponents can't cast spells or activate abilities of <type>[, <type>
# [,] or <type>]." (ENG-28, Grand Abolisher/Myrel, Shield of Argive — always
# printed under a leading "During your turn," gate, split off by
# `_conditional_static_specs`'s "during your turn" wrapper before this ever
# sees the clause) — one sentence combining `cast_prohibition` (the "cast
# spells" half, no type filter — any spell) with `activation_prohibition`
# (the "activate abilities of …" half, opponent-scoped and type-filtered).
# Two independent specs from one clause, both riding whatever ``active_if``
# gate the caller stamps onto every spec `static_effect_specs` returns.
_CANT_CAST_OR_ACTIVATE_OPPONENTS_RE = re.compile(
    r"your opponents can'?t cast spells or activate abilities of (?P<types>[a-z][a-z, ]*)",
    re.IGNORECASE,
)

# "Your opponents can't cast spells during your turn."  (Dragonlord Dromoka/
# Teferi, Time Raveler/Kutzil, Malamet Exemplar/Voice of Victory-shaped) —
# unlike `_CANT_CAST_OR_ACTIVATE_OPPONENTS_RE`'s type-scoped sibling (always
# printed under a leading "During your turn," gate `_conditional_static_
# specs` peels off first), this trails its own turn-scope inline rather than
# leading with it, so it needs its own row: `cast_prohibition`'s existing
# ``scope="opponents"`` default plus an ordinary RULE 613.6 ``active_if``
# gate — no new engine primitive, both already exist for other cards'
# shapes. Conqueror's Flail's own "as long as this Equipment is attached to
# a creature, …" wrapping is peeled by `_conditional_static_specs` before
# this is ever reached, same as any other conditional static.
_CANT_CAST_OPPONENTS_YOUR_TURN_RE = re.compile(
    r"your opponents can'?t cast spells during your turn", re.IGNORECASE
)

#: A type list ("artifacts, creatures, or enchantments") → normalized
#: singular `_CARD_TYPE_WORDS`, or ``None`` (fail-closed) if any word in it
#: isn't a recognised card type. Splits on a comma (with an optional trailing
#: "and"/"or") or a bare "and"/"or" — the two ways real cards print a list of
#: two or three types.
_TYPE_LIST_SPLIT_RE = re.compile(r",\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+", re.IGNORECASE)


def _type_word_list(text: str) -> Optional[list[str]]:
    words = [w.strip() for w in _TYPE_LIST_SPLIT_RE.split(text.strip()) if w.strip()]
    if not words:
        return None
    result = []
    for word in words:
        singular = _singularize(word.lower())
        if singular not in _CARD_TYPE_WORDS:
            return None
        result.append(singular)
    return result

# "<Type> spells cost {N} more/less to cast."  (RULE 601.2f tax/discount,
# Thalia/Thorn of Amethyst/Vryn Wingmare-shaped) — the bare "<type> spells
# cost …" phrasing with no "you cast"/"your opponents cast" qualifier taxes
# *everyone*, the caster's own controller included; see
# `_SPELL_COST_TAX_YOU_CAST_RE` below for the self-scoped "you cast" sibling.
_SPELL_TYPE_WORDS: frozenset[str] = frozenset(
    {"noncreature", "creature", "artifact", "instant", "sorcery", "enchantment", "planeswalker"}
)
_SPELL_COST_TAX_RE = re.compile(
    r"(?:(?P<word>[a-z]+) )?spells cost \{(?P<n>\d+)\} (?P<dir>more|less) to cast", re.IGNORECASE
)

# "[<Type> [and <type>]] spells you cast cost {N} more/less to cast."  (RULE
# 601.2f self-scoped discount/tax, Baral/Archmage of Runes/Pearl Medallion-
# adjacent — the "you cast" sibling of `_SPELL_COST_TAX_RE`: unlike that
# unscoped tax, this only ever discounts/taxes *this permanent's own
# controller*'s spells (`continuous.cost_reduction_for`'s ownership check,
# ``affects="your_spells"`` — the `cost_reduction` registry's own default,
# so the emitted spec omits ``affects`` entirely). The two-type "instant and
# sorcery spells you cast …" compound (Baral, Chief of Compliance-shaped)
# passes both words through as a list — `continuous._spell_type_matches`
# ORs them. Colour-scoped variants ("White spells you cast cost {1} less…",
# the Medallion cycle) are now claimed too, by `_SPELL_COST_TAX_COLOR_RE`
# below — not this regex's own ``word1``, since `_spell_type_matches` only
# reads `Card`'s main-type flags, not colour. Creature-subtype-scoped
# variants ("Equipment spells…", the Banneret cycle) remain a genuinely
# different filter kind, still deliberately left unclaimed rather than
# silently ignoring the qualifier.
_SPELL_COST_TAX_YOU_CAST_RE = re.compile(
    r"(?:(?P<word1>[a-z]+)(?: and (?P<word2>[a-z]+))? )?spells you cast cost "
    r"\{(?P<n>\d+)\} (?P<dir>more|less) to cast",
    re.IGNORECASE,
)

# "<Color> spells you cast cost {N} more/less to cast."  (the Medallion
# cycle/Grand Arbiter Augustin IV-shaped colour filter `_SPELL_COST_TAX_YOU_
# CAST_RE`'s own docstring flagged as unbuilt — `continuous.cost_reduction_
# for`'s ``spell_color`` param already reads it, only the parser recognizer
# was missing.) Checked ahead of `_SPELL_COST_TAX_YOU_CAST_RE` in dispatch
# order: that regex's own ``word1`` group also matches a colour word, and
# its handler fails closed (returns ``None``, claiming nothing) on a word
# outside `_SPELL_TYPE_WORDS` rather than falling through to try this one.
_SPELL_COST_TAX_COLOR_RE = re.compile(
    r"(?P<color>white|blue|black|red|green|colorless) spells you cast cost "
    r"\{(?P<n>\d+)\} (?P<dir>more|less) to cast",
    re.IGNORECASE,
)

# "Spells your opponents cast cost {N} more/less to cast."  (Grand Arbiter
# Augustin IV's third line) — the tax-only mirror of
# `_SPELL_COST_TAX_YOU_CAST_RE`'s ``"your_spells"`` default: `continuous.
# cost_reduction_for`'s ``affects="opponents_spells"`` branch applies to
# every player except the permanent's own controller.
_SPELL_COST_TAX_OPPONENTS_RE = re.compile(
    r"spells your opponents cast cost \{(?P<n>\d+)\} (?P<dir>more|less) to cast",
    re.IGNORECASE,
)

# "Spells your opponents cast that target ~ cost {N} more to cast."
# (Icefall Regent / Boreal Elemental / Charix, the Raging Isle / Elderwood
# Scion / Pursued Whale / Frost Titan-adjacent) — the "that target ~"
# narrowing on the opponents-tax above; `continuous.cost_reduction_for`
# checks the caster's chosen targets against this static's own source
# (`targets_source` param). Tried before the plain opponents row (whose
# regex would leave the "that target ~" clause unconsumed and fail).
_SPELL_COST_TAX_OPPONENTS_TARGET_RE = re.compile(
    r"spells your opponents cast that target ~ cost \{(?P<n>\d+)\} (?P<dir>more|less) to cast",
    re.IGNORECASE,
)

# "Activated abilities of <type> you control cost {N} less to activate[.
# This effect can't reduce the mana in that cost to less than {M} mana.]"
# (Training Grounds) — the main-card-type-scoped sibling of Sam, Loyal
# Attendant's hand-authored subtype scope (`continuous.
# activation_cost_reduction_for`'s ``card_type`` branch); the trailing floor
# clause is optional (folded into the same spec via ``min_total`` when
# present) since not every card of this shape prints one.
_ACTIVATION_COST_REDUCTION_TYPE_RE = re.compile(
    r"activated abilities of (?P<word>[a-z]+) you control cost \{(?P<n>\d+)\} less to activate\.?"
    r"(?:\s*this effect can'?t reduce the mana in that cost to less than \{?(?P<floor>\d+)\}? mana\.?)?",
    re.IGNORECASE,
)

# "This spell costs {N} less to cast for each attacking creature [you
# control]."  (RULE 601.2f self-scoped discount printed on the spell itself
# — Embercleave/Ancient Stone Idol-shaped, MEC-6) — unlike `_SPELL_COST_TAX_RE`
# above (a battlefield permanent taxing *other* spells), this is `affects=
# "self"` with a `per` count-selector, the same "cost {N} less for each
# <board count>" shape Delve/Affinity already exercise via `continuous.
# self_cost_reduction_for`/`_cost_static_amount` — only the selector
# (`attacking_creatures_you_control`/`attacking_creatures`) is new.
_SELF_COST_REDUCTION_ATTACKING_RE = re.compile(
    r"this spell costs \{(?P<n>\d+)\} less to cast for each attacking creature"
    r"(?P<yours> you control)?",
    re.IGNORECASE,
)

# "This spell costs {N} less to cast if `<condition>`." (RULE 601.2f,
# Ghostfire Slice-shaped) — the self cost-reduction sibling of the above,
# gated by RULE 613.6's own "as long as `<condition>`" whitelist
# (`static_condition`) instead of a `per`-scaled count, so it reuses that
# same evaluator rather than growing a second one.
_SELF_COST_REDUCTION_IF_RE = re.compile(
    r"this spell costs \{(?P<n>\d+)\} less to cast if (?P<cond>.+)",
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
_COLOR_WORD_TO_LETTER = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
_TARGETS_CRITERIA_RE = re.compile(
    r"it targets an? (?P<body>[a-z' +/\-\d]+?)"
    r"(?P<ctrl> you control| you don'?t control)?$",
    re.IGNORECASE,
)


def _targets_reduction_criteria(cond: str) -> "dict | None":
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
_CAST_LIMIT_RE = re.compile(
    r"each player can'?t cast more than (?P<n>\d+) spells? each turn", re.IGNORECASE
)

#: "Your opponents can't cast spells from anywhere other than their
#: hands." (Drannith Magistrate) — `continuous.cast_prohibited`'s new
#: ``hand_only`` zone check.
_CANT_CAST_OPPONENTS_HAND_ONLY_RE = re.compile(
    r"your opponents can'?t cast spells from anywhere other than their hands", re.IGNORECASE
)

#: The **noncreature**-scoped sibling (Deafening Silence) — `continuous.
#: max_noncreature_spells_per_turn`'s own ``noncreature`` flag.
_CAST_LIMIT_NONCREATURE_RE = re.compile(
    r"each player can'?t cast more than (?P<n>\d+) noncreature spells? each turn", re.IGNORECASE
)

# "You may play [an|N] additional land[s] on/during each of your/their
# turns."  (RULE 305.2 permission static, Exploration/Dryad of the Ilysian
# Grove/Azusa-shaped) or its unscoped "Each player may play …" sibling
# (Rites of Flourishing/Storm Cauldron) — `_EXTRA_LAND_DROP_RE.group("n")`
# via `count_of` handles both "an"/"a" and a digit count (Azusa's "two
# additional lands"→"2" after `normalize`'s spelled-out-number fold). The
# one-turn "…this turn" phrasing (Explore-shaped) is a different, resolve-
# time-effect shape claimed by `catalogue.handlers`' `extra_land_play` row
# instead, not this static family.
_EXTRA_LAND_DROP_RE = re.compile(
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
_NO_MAX_HAND_SIZE_RE = re.compile(
    r"(?P<subject>you have|players have) no maximum hand size", re.IGNORECASE
)

# "Players skip their untap steps." (RULE 502.3-adjacent, Stasis) — the last
# open member of the "players can't `<verb>`" family
# (`docs/implementation-state/BACKLOG.md`'s MEC-12 entry). Unconditional and
# unscoped, unlike `_NO_MAX_HAND_SIZE_RE` above: no card in the cache prints
# a "you"-only version of this clause, so there's no ``subject`` group to
# capture.
_SKIP_UNTAP_STEPS_RE = re.compile(r"players skip their untap steps", re.IGNORECASE)

# "Players can't gain life." (Everlasting Torment / Forsaken Wastes / Havoc
# Festival / Leyline of Punishment) / "Your opponents can't gain life."
# (Erebos, God of the Dead) / "If a player would gain life, that player
# gains no life instead." (Sulfuric Vortex — a replacement-phrased
# equivalent) — a standing, board-wide RULE 119.3-adjacent rule
# modification, distinct from `handlers._CANT_GAIN_LIFE_RE`'s turn-scoped
# rider. Consulted live by `RulesEngine.gain_life` via
# `continuous.life_gain_prohibited_for`.
_PLAYERS_CANT_GAIN_LIFE_RE = re.compile(
    r"(?:(?P<scope>players|your opponents) can'?t gain life"
    r"|if a player would gain life, that player gains no life instead)",
    re.IGNORECASE,
)

# "Skip your draw step." (MEC-38, Necropotence / Yawgmoth's Bargain /
# Solitary Confinement / Dragon Appeasement) — the *self*-scoped, standing
# step skip, `EffectSpec("skip_step", …)` (a `StaticAbility` layer read live
# by `RulesEngine.should_skip_step` via `continuous.skipped_steps_for`,
# unrelated to `_SKIP_UNTAP_STEPS_RE`'s board-wide Stasis effect above). The
# effect had shipped for MEC-38 but only via a hand-authored catalogue
# entry; this is its oracle-text route. `should_skip_step` is consulted with
# every step's own name, so "untap"/"upkeep" work the same way — but "draw"
# is the only form real cards print, and untap/upkeep are left out until one
# does (fail-closed).
_SKIP_YOUR_STEP_RE = re.compile(r"skip your (?P<step>draw) step", re.IGNORECASE)

# "Players can't cast spells from graveyards or libraries." (RULE
# 601.3a-adjacent, Grafdigger's Cage/Weathered Runestone) — the last open
# member of MEC-12's "players can't <verb>" family sweep.
# MEC-43 round 2 (Kunoros, Hound of Athreos): "Players can't cast spells
# from **graveyards**." — the graveyard-only sibling, no "or libraries" —
# the trailing zone clause is optional so both phrasings match.
_GRAVEYARD_LIBRARY_CAST_PROHIBITION_RE = re.compile(
    r"players can'?t cast spells from graveyards(?P<libraries> or libraries)?", re.IGNORECASE
)
# "Creature cards in graveyards and libraries can't enter the battlefield."
# (Grafdigger's Cage) or "Nonland permanent cards in graveyards and
# libraries can't enter the battlefield." (Weathered Runestone), or just
# "Creature cards in **graveyards** can't enter the battlefield." (MEC-43
# round 2, Kunoros — no "and libraries") — the card-type word feeds
# `continuous.graveyard_library_entry_prohibited`'s ``card_type`` param
# verbatim, except "nonland permanent" which is its own sentinel (checked
# separately from the plain `_CARD_TYPE_ATTRS` words).
_GRAVEYARD_LIBRARY_ENTRY_PROHIBITION_RE = re.compile(
    r"(?P<type>creature|artifact|enchantment|planeswalker|nonland permanent) cards "
    r"in graveyards(?P<libraries> and libraries)? can'?t enter the battlefield",
    re.IGNORECASE,
)

# "You may choose not to untap ~ during your untap step."  (RULE 502.1
# self-scoped opt-out, Rubinia Soulsinger/Hivis of the Scale/The Pandorica-
# shaped) — `~` covers all three printed subject wordings ("this creature"/
# "this artifact"/"this land", folded by `normalize._fold_self_reference`)
# uniformly. Unlike `_NO_UNTAP_RE` below (an unconditional restriction), this
# only *permits* skipping untap — actually skipping it needs the controller
# to separately toggle `GameObject.skip_untap` on (`GameEngine.
# set_skip_untap`). Deliberately excludes every targeted/imposed "doesn't
# untap … for as long as this remains tapped" variant (Sand Squid/Ice Floe-
# shaped) — a different family entirely (an activated ability locking a
# *different* permanent), not "you may choose" at all.
_NO_UNTAP_OPTIONAL_RE = re.compile(
    r"you may choose not to untap ~ during your untap step", re.IGNORECASE
)

# "You gain life rather than lose life from radiation."  (RULE 728.1a,
# Strong, the Brutish Thespian) — a per-player permission static redirecting
# a ``cause="radiation"`` life loss into a gain instead
# (`continuous.has_radiation_life_gain`, `RulesEngine.lose_life`). No
# "players gain..." unscoped variant exists in the real card pool yet, so
# unlike `_NO_MAX_HAND_SIZE_RE` this has no ``subject`` alternation.
_RADIATION_LIFE_GAIN_RE = re.compile(
    r"you gain life rather than lose life from radiation", re.IGNORECASE
)

# "~ doesn't untap during your untap step."  (RULE 502.3-adjacent
# self-restriction, Basalt Monolith/Grim Monolith/Mana Vault) — `~` is the
# self-reference token `normalize._fold_self_reference`/`_fold_self_name`
# folds "this artifact"/the card's own printed name to (Card-pool Batch 1),
# so this must match the folded form, not the literal "this <type>" text
# that normalize never leaves in place.
_NO_UNTAP_RE = re.compile(
    r"~ doesn'?t untap during your untap step", re.IGNORECASE
)

# "~ isn't a creature." (RULE 613.7f, always printed wrapped in a RULE 613.6
# "as long as <condition>, " gate — the Theros gods' own devotion threshold —
# so this row is only ever reached through `_conditional_static_specs`,
# never as a bare unconditional clause: no real card removes creature-ness
# unconditionally.) `type_change`'s existing `remove_types` param already
# does the layer-4 removal; nothing new needed but the phrase.
_NOT_A_CREATURE_RE = re.compile(r"~ isn'?t a creature", re.IGNORECASE)

# "Creatures with power N or greater don't untap during their controllers'
# untap steps."  (Meekstone) — the unattached group-scoped sibling of
# `_NO_UNTAP_RE`/`_NO_UNTAP_ATTACHED_RE` above: no `~`/attached subject at
# all, just a board-wide power qualifier, so it reuses `no_untap`'s ordinary
# ``affects="all_creatures"`` selector plus the standard ``min_power``
# post-filter (`continuous.group_selector_objects`) rather than a new field.
_NO_UNTAP_GROUP_POWER_RE = re.compile(
    r"creatures with power (?P<n>\d+) or greater don'?t untap during their "
    r"controllers'? untap steps?",
    re.IGNORECASE,
)

# "Nonbasic lands don't untap during their controllers' untap steps."
# (Back to Basics) — `no_untap`'s unconditional, unlimited-count sibling to
# `_UNTAP_CAP_RE`'s Winter Moon-shaped "…can't untap more than one nonbasic
# land…" (a cap that still lets the *first* one through each turn): this
# one blocks every nonbasic land, every turn. ``affects="all_lands"`` +
# the ordinary ``nonbasic`` selector `group_selector_objects` already
# applies to every other static family — no new engine code.
_NO_UNTAP_NONBASIC_LANDS_RE = re.compile(
    r"nonbasic lands don'?t untap during their controllers'? untap steps?",
    re.IGNORECASE,
)

# "Players can't untap more than N [nonbasic] `<type>` during their untap
# steps."  (RULE 502.3-adjacent, Static Orb's "permanents"/Winter Moon's
# "nonbasic land" — Winter Orb's own "one land" is hand-authored, see
# `ability_catalogue._winter_orb`, but shares this same `untap_cap` family)
# — always printed either bare (Winter Moon) or under a leading "as long as
# this artifact is untapped," gate peeled off by `_conditional_static_specs`
# before this ever sees the clause (Static Orb).
_UNTAP_CAP_RE = re.compile(
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
_TRIGGER_PROHIBITION_RE = re.compile(
    r"(?P<word>[a-z]+) entering(?P<dying> or dying)? don'?t cause abilities to trigger", re.IGNORECASE
)

# "[Nonbasic] <type>[s] [and [nonbasic] <type>[s]] your opponents control
# enter tapped."  (RULE 614.1, board-wide — Manglehorn/Dauntless
# Dismantler's "artifacts", Archon of Emeria's "nonbasic lands", Blind
# Obedience's "artifacts and creatures", Thalia, Heretic Cathar's own mixed
# "creatures and nonbasic lands" — MEC-43 round 2) — distinct from
# `ability_catalogue.enters_tapped` (a card's own printed tapped-entry
# clause about *itself*): this is a standing effect from a *different*
# permanent, scoped to "your opponents". Each ``and``-joined part carries
# its *own* optional "nonbasic" prefix (Thalia's creatures aren't nonbasic-
# restricted, only her lands are) rather than one flag for the whole
# clause; one spec is emitted per part (Blind Obedience/Thalia alike).
_OPPONENTS_ENTER_TAPPED_RE = re.compile(
    r"(?P<parts>(?:nonbasic )?[a-z]+(?: and (?:nonbasic )?[a-z]+)*) your opponents control enter tapped",
    re.IGNORECASE,
)

# "[Nonbasic] <type>[s] [and <type>[s]] enter tapped."  (RULE 614.1,
# board-wide, Root Maze-shaped) — the *unscoped* sibling of
# `_OPPONENTS_ENTER_TAPPED_RE`: no "your opponents control" qualifier at
# all, so it applies to every player's matching permanents, including the
# static's own controller's.
_ALL_ENTER_TAPPED_RE = re.compile(
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
_BASIC_LAND_WORDS: dict[str, str] = {}
for _name in _BASIC_LAND_COLOR:
    _BASIC_LAND_WORDS[_name] = _name.capitalize()
    _BASIC_LAND_WORDS[_name + "s"] = _name.capitalize()
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
# Urborg/Yavimaya's (`_LAND_IS_BASIC_TYPE_RE` below) regardless of which
# effect's timestamp is newer.
_TYPE_OVERWRITE_RE = re.compile(r"nonbasic lands are (?P<word>[a-z]+)", re.IGNORECASE)

# "Each land is a <BasicType> in addition to its other land types." (RULE
# 613.4a additive land-type grant, board-wide — Urborg, Tomb of Yawgmoth/
# Yavimaya, Cradle of Growth) — the land-type sibling of `_GROUP_CHOSEN_TYPE_
# RE`'s "…the chosen type in addition to its other types", except the type
# here is a fixed literal rather than an interactively chosen one. Emits only
# an `add_subtypes` `type_change` — same as `_TYPE_OVERWRITE_RE` above, the
# matching mana ability isn't a paired spec; it falls out of the generic
# RULE 305.6 derivation once the land's subtype set is resolved.
_LAND_IS_BASIC_TYPE_RE = re.compile(
    r"each land is a (?P<word>[a-z]+) in addition to its other land types", re.IGNORECASE
)

# "You may play lands [and cast [noncreature] spells [with mana value N or
# greater]] from the top of your library."/"You may cast [noncreature]
# spells [with mana value N or greater] from the top of your library."
# (RULE 701-adjacent standing permission, Oracle of Mul Daya/Glarb, Calamity's
# Augur/Future Sight/Bolas's Citadel/Elsha of the Infinite-shaped) — the
# generic sibling of the two hand-authored `top_library_permission` entries
# in `game/ability_catalogue.py` (left registered rather than migrated; no
# harm in both existing side by side, the hand-authored registry always
# takes precedence for a registered card). ``_TOP_LIBRARY_VERB_PARAMS``'
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
_TOP_LIBRARY_VERB_PARAMS: dict[str, dict] = {
    "play lands and cast noncreature spells": {
        "play_lands": True, "cast_spells": True, "noncreature_only": True,
    },
    "play lands and cast spells": {"play_lands": True, "cast_spells": True},
    "play lands": {"play_lands": True},
    "cast noncreature spells": {"cast_spells": True, "noncreature_only": True},
    "cast spells": {"cast_spells": True},
}
_TOP_LIBRARY_TAILS: dict[str, str] = {
    "you may cast it as though it had flash": "grants_flash",
    "pay life equal to its mana value rather than pay its mana cost": "life_payment",
}
_TOP_LIBRARY_PERMISSION_RE = re.compile(
    r"you may (?P<verb>" + "|".join(re.escape(v) for v in _TOP_LIBRARY_VERB_PARAMS) + r")"
    r"(?: with mana value (?P<mv>\d+) or greater)?"
    r" from the top of your library"
    r"(?:\. if you cast a spell this way, (?P<tail>"
    + "|".join(re.escape(t) for t in _TOP_LIBRARY_TAILS) + r"))?",
    re.IGNORECASE,
)

#: "You may look at the top card of your library any time." (Sphinx of Jwar
#: Isle/Fblthp, Lost on the Range/Glowcap Lantern/Iron Lad, Diverging
#: Destiny/Vesuvan Drifter-shaped — ~57 real cards) — the standalone,
#: look-only sibling of `_TOP_LIBRARY_PERMISSION_RE` just above (whose own
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
_LOOK_AT_TOP_ANY_TIME_RE = re.compile(
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


def commander_eligibility_line(line: str) -> bool:
    """Whether ``line`` is a RULE 903.3 "~ can be your commander." sentence —
    see `_COMMANDER_ELIGIBLE_RE`. Claimed at the `gate._process_line` level
    (before this module's `static_effect_specs` even runs), not through an
    `EffectSpec`, since it carries no behaviour to bind."""
    return bool(_COMMANDER_ELIGIBLE_RE.fullmatch(line.strip().rstrip(".").strip()))


#: The subject phrases an Aura/Equipment/Fortification's own buff clause is
#: printed with — a closed list (not a general noun-phrase parse like
#: `_scope`, since only these five shapes actually appear on cards) rather
#: than any combination of "equipped/enchanted/fortified" x
#: "creature/land/permanent" ("equipped land"/"fortified creature" don't
#: exist and stay unclaimed).
_ATTACHED_SUBJECTS = (
    "equipped creature",
    "enchanted creature",
    "fortified land",
    "enchanted permanent",
    "enchanted land",
)
_ATTACHED_SUBJECT_PATTERN = "|".join(re.escape(s) for s in _ATTACHED_SUBJECTS)

# "Enchanted/equipped <subject> doesn't untap during its controller's untap
# step."  (RULE 502.3-adjacent, attached-permanent form — e.g. Paralyzing
# Grasp) — the Aura/Equipment-grant sibling of `_NO_UNTAP_RE` above.
_NO_UNTAP_ATTACHED_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) doesn'?t untap during its "
    r"controller'?s untap step",
    re.IGNORECASE,
)

# "~"/an attached-permanent subject can't attack, can't block, can't be
# blocked, or must attack each combat (RULE 508.1a/509.1a self-restrictions)
# — modeled as synthetic layer-6 "keyword" flags (`"cant_attack"`/
# `"cant_block"`/`"cant_be_blocked"`/`"attacks_if_able"`/`"must_be_blocked"`/
# `"all_must_block"`; *not* real RULE 702 keywords, just internal markers
# `game/combat.py`'s `has()` and the engine's `_can_attack`/`can_block`/
# attack-declaration/block-requirement enforcement checks alongside
# the real keyword union) reusing the exact same `grant_keyword` StaticAbility
# / layer-6 plumbing — zero new engine code for the restriction half. The
# "…and its activated abilities can't be activated" tail reuses the existing
# board-wide `activation_prohibition` family (RULE 602) scoped to just this
# one object instead of a card-type filter — the selector vocabulary
# (``affects="self"``/``"attached_permanent"``) already supports that.
# The *qualified* variants ("except by…", "unless…", "…alone") are claimed
# separately, by the `combat_restriction` family further down — each regex
# here is `fullmatch`ed, so a trailing qualifier leaves this row unmatched
# and falls through to those rather than being silently dropped. RULE
# 509.1b's multi-block *permissions* ("~ can block an additional creature
# each combat."/"~ can block any number of creatures.") ride that
# `combat_restriction` family directly instead (`"extra_blocks"`/
# `"unlimited_blocks"`), since the count actually matters there.
_COMBAT_RESTRICTION_SUBJECT_PATTERN = rf"~|{_ATTACHED_SUBJECT_PATTERN}"
_CANT_ATTACK_OR_BLOCK_LOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack or "
    r"block, and its activated abilities can'?t be activated"
    r"(?P<mana_exception> unless they'?re mana abilities)?",
    re.IGNORECASE,
)
_CANT_ATTACK_OR_BLOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack or block",
    re.IGNORECASE,
)
_CANT_BLOCK_AND_CANT_BE_BLOCKED_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t block and "
    r"can'?t be blocked",
    re.IGNORECASE,
)
_CANT_ATTACK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack", re.IGNORECASE
)
_CANT_BLOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t block", re.IGNORECASE
)
_CANT_BE_BLOCKED_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t be blocked",
    re.IGNORECASE,
)
_ATTACKS_IF_ABLE_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) attacks each combat if able",
    re.IGNORECASE,
)

# RULE 509.1c/d combat *requirements* — the mirror image of the restriction
# family above (they force a block rather than forbid one), but the same two
# self/attached subjects and the same synthetic flag-keyword plumbing:
# "must_be_blocked"/"all_must_block" are consulted by `GameEngine.
# _enforce_block_requirements` exactly like `attacks_if_able` is by
# `_enforce_attacks_if_able`, both checked as the relevant declare step
# closes rather than at recompute time (a requirement needs to see who
# actually got blocked/declared, same reason the restrictions above do).
_MUST_BE_BLOCKED_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) must be blocked if able",
    re.IGNORECASE,
)
#: "All creatures able to block ~ do so." (Lure-shaped) — unlike every other
#: row in this family, the printed *subject* of the sentence is the set of
#: candidate blockers, not the restricted/required permanent itself (which
#: appears only as the object of "block …"), so it needs its own regex
#: rather than a `_QUALIFIED_SUBJECT`-shaped one.
_ALL_MUST_BLOCK_RE = re.compile(
    rf"all creatures able to block (?P<subject>~|it|{_ATTACHED_SUBJECT_PATTERN}) do so",
    re.IGNORECASE,
)

# RULE 509.1b multi-block *permissions* — same self/attached subject family,
# but a `combat_restriction` param entry (`extra_blocks`/`unlimited_blocks`)
# rather than a bare flag, since the count matters (`game/combat.py`'s
# `max_blocks_for`).
_BLOCK_ADDITIONAL_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can block an additional creature "
    r"each combat",
    re.IGNORECASE,
)
_BLOCK_ANY_NUMBER_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can block any number of creatures",
    re.IGNORECASE,
)
#: "…can block an additional **N** creatures each combat" — the counted form
#: of `_BLOCK_ADDITIONAL_RE` (Temperamental Oozewagg's "an additional 99").
_BLOCK_ADDITIONAL_N_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can block an additional "
    r"(?P<n>\d+) creatures each combat",
    re.IGNORECASE,
)
#: RULE 508.1a attack *permission* — "~ can attack as though it didn't have
#: defender". Not a keyword removal (the creature keeps Defender); see
#: `combat.COMBAT_RESTRICTIONS`' ``attacks_as_though_no_defender``.
_ATTACK_AS_THOUGH_NO_DEFENDER_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can attack as though "
    r"(?:it|they) didn'?t have defender",
    re.IGNORECASE,
)

#: The combat *permission* tails that may follow a keyword grant in one
#: clause ("…has trample **and can attack as though it didn't have
#: defender**"). Each maps the tail text to its `combat_restriction` params;
#: the subject is the grant's own, so these carry no subject of their own.
_PERMISSION_TAIL_RES: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(r"can attack as though (?:it|they) didn'?t have defender", re.I),
     lambda m: {"kind": "attacks_as_though_no_defender"}),
    (re.compile(r"can block an additional (?P<n>\d+) creatures each combat", re.I),
     lambda m: {"kind": "extra_blocks", "count": int(m.group("n"))}),
    (re.compile(r"can block an additional creature each combat", re.I),
     lambda m: {"kind": "extra_blocks", "count": 1}),
    (re.compile(r"can block any number of creatures", re.I),
     lambda m: {"kind": "unlimited_blocks"}),
]


def _permission_tail_params(text: str) -> Optional[dict]:
    """A trailing combat-permission phrase → `combat_restriction` params.

    ``None`` for anything else, which fails the whole clause closed — the
    tail exists precisely because dropping it would leave a card that says
    "has trample and can attack as though it didn't have defender" granting
    only the trample, i.e. quietly wrong rather than merely unmodeled.
    """
    stripped = text.strip().rstrip(".").strip()
    for pattern, build in _PERMISSION_TAIL_RES:
        m = pattern.fullmatch(stripped)
        if m is not None:
            return build(m)
    return None


def _combat_restriction_affects(subject: str) -> str:
    return "self" if subject == "~" else "attached_permanent"


def _combat_restriction_specs(
    subject: str, flags: list[str], lock: bool = False, mana_exception: bool = False
) -> list[EffectSpec]:
    affects = _combat_restriction_affects(subject)
    specs = [EffectSpec("grant_keyword", {"keywords": flags, "affects": affects})]
    if lock:
        params: dict = {"affects": affects}
        if mana_exception:
            # RULE 605.1a: "…unless they're mana abilities" (Imprisoned in
            # the Moon/Kasmina's Transmutation) — the same prohibition with a
            # carve-out `continuous.activation_prohibited` honours.
            params["except_mana_abilities"] = True
        specs.append(EffectSpec("activation_prohibition", params))
    return specs


# -- The *qualified* combat restrictions (RULE 508.1a / 509.1b) --------------
#
# Everything above is a plain flag ("~ can't attack."). Their qualified
# siblings carry a parameter — a blocker filter, a count, or an "unless"
# condition — and so bind to a ``combat_restriction`` `EffectSpec` instead,
# stamped onto `GameObject.combat_restrictions` and evaluated at combat time
# (`game/combat.py`'s `COMBAT_RESTRICTIONS` whitelist / `GameEngine.
# _combat_condition_met`). Still fail-closed: an unrecognised filter or
# condition returns ``None`` for the whole clause rather than dropping the
# qualifier and claiming the plain restriction, which would be strictly
# *wrong* behaviour rather than merely missing behaviour.

#: A blocker filter's colour/subtype/keyword/power vocabulary, as it appears
#: after "can't be blocked by …"/"…except by …". Ordered most-specific-first
#: (`object_filter` tries them in order); every one is anchored, so an
#: unlisted phrasing falls through to ``None``.
_FILTER_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"creatures with power (?P<n>\d+) or less", re.I), "max_power"),
    (re.compile(r"creatures with power (?P<n>\d+) or greater", re.I), "min_power"),
    (re.compile(r"creatures with toughness (?P<n>\d+) or less", re.I), "max_toughness"),
    (re.compile(r"creatures with toughness (?P<n>\d+) or greater", re.I), "min_toughness"),
    (re.compile(r"creatures with greater power", re.I), "greater_power"),
    (
        # "creatures with power less than ~'s power" (Sedge Troll-shaped) —
        # anchored to the *source's own* power. The sibling phrasing whose
        # threshold is a board count instead ("…less than the number of
        # Islands you control", Kraken of the Straits) is a dynamic value,
        # not a literal int, so it gets its own regex below rather than a
        # row in this literal-int table.
        re.compile(r"creatures with power less than (?:~'?s power|its power|~)", re.I),
        "lesser_power",
    ),
]

#: A basic land type's singular/plural pair → the `subtype` this pool's
#: `continuous.count_selector`'s ``lands_you_control_of_type_<x>`` reads.
#: "Plains" has no distinct singular, unlike the other four.
_BASIC_LAND_PLURALS: dict[str, str] = {
    "islands": "island", "swamps": "swamp", "mountains": "mountain",
    "forests": "forest", "plains": "plains",
}
#: "creatures with power less than the number of Islands you control"
#: (Kraken of the Straits) — the dynamic-threshold sibling of the literal
#: ``_FILTER_RES`` rows above, resolved fresh at combat time
#: (`combat.matches_object_filter`'s ``power_lt_count_selector``) rather
#: than baked into a fixed int at parse time.
_POWER_LT_COUNT_RE = re.compile(
    r"creatures with power less than the number of (?P<type>[a-z]+) you control", re.I
)

#: The flag keywords a "creatures with <keyword>[ or <keyword>]" filter may
#: name — the evasion-relevant subset of RULE 702 `game/combat.py` can check
#: on a blocker. Deliberately small; anything else fails closed.
_FILTER_KEYWORD_WORDS: dict[str, str] = {
    "flying": "flying",
    "reach": "reach",
    "shadow": "shadow",
    "defender": "defender",
    "first strike": "first_strike",
    "menace": "menace",
}
_FILTER_KEYWORDS_RE = re.compile(
    r"creatures with (?P<kws>[a-z ]+?(?: or [a-z ]+?)*)$", re.I
)
_FILTER_WITHOUT_KEYWORD_RE = re.compile(r"creatures without (?P<kw>[a-z ]+)$", re.I)


def object_filter(text: str) -> Optional[dict]:
    """An object-describing phrase → a `combat.matches_object_filter` param
    dict, or ``None`` (fail-closed) for a phrasing outside the closed
    vocabulary above.

    Shared by every half of this family: the blocker set of "can't be blocked
    by <text>"/"…except by <text>", the counted set of "can't attack unless
    you control <text>", and — from `catalogue/handlers.py` — the same
    blocker set on the resolve-time "…this turn" variant. Public (no leading
    underscore) for that last cross-module use.
    """
    text = text.strip().rstrip(".").strip()
    if not text:
        return None
    if text in ("creatures", "creature"):
        # No narrowing beyond the type itself — which still matters for the
        # "unless you control another creature" counting half, where a land
        # would otherwise be counted.
        return {"card_type": "creature"}
    if _singularize(text) in _CARD_TYPE_WORDS:
        # A bare card type ("unless you control another **artifact**") — the
        # anthem `_scope` parser below deliberately rejects these (a "+1/+1"
        # scope really is creatures-only), but a count/blocker filter is happy
        # with any permanent type.
        return {"card_type": _singularize(text)}
    m = _POWER_LT_COUNT_RE.fullmatch(text)
    if m is not None:
        land_type = _BASIC_LAND_PLURALS.get(m.group("type").lower())
        return (
            None if land_type is None
            else {"power_lt_count_selector": f"lands_you_control_of_type_{land_type}"}
        )
    for pattern, key in _FILTER_RES:
        m = pattern.fullmatch(text)
        if m is None:
            continue
        if key == "greater_power":
            return {"power_vs_reference": "greater"}
        if key == "lesser_power":
            return {"power_vs_reference": "less"}
        return {key: int(m.group("n"))}
    m = _FILTER_WITHOUT_KEYWORD_RE.fullmatch(text)
    if m is not None:
        keyword = _FILTER_KEYWORD_WORDS.get(m.group("kw").strip().lower())
        return {"without_keyword": keyword} if keyword else None
    m = _FILTER_KEYWORDS_RE.fullmatch(text)
    if m is not None:
        words = [w.strip().lower() for w in re.split(r"\s+or\s+", m.group("kws"))]
        keywords = [_FILTER_KEYWORD_WORDS[w] for w in words if w in _FILTER_KEYWORD_WORDS]
        if len(keywords) != len(words):
            return None
        return {"keyword": keywords[0]} if len(keywords) == 1 else {"keyword_any": keywords}
    if " or " in text and " with " not in text:
        # "another Wolf or Werewolf" (Howlpack Wolf) — an OR over subtypes,
        # which `_scope` below can't express (it returns one subtype). Every
        # alternative must itself be a recognisable single-word subtype, or
        # the whole phrase fails closed.
        parts = [p.strip() for p in text.split(" or ")]
        subtypes = []
        for part in parts:
            sub = _scope(part)
            if sub is None or not sub.subtype or " " in sub.subtype:
                return None
            subtypes.append(sub.subtype)
        return {"subtype_any": subtypes}
    # "black creatures" / "artifact creatures" / "Walls" — reuse the anthem
    # family's own scope parser so the subtype/colour vocabulary can't drift
    # between "black creatures get +1/+1" and "can't be blocked by black
    # creatures".
    if text.endswith(" creatures") or text.endswith(" creature"):
        head = text.rsplit(" ", 1)[0]
        if head in _CARD_TYPE_WORDS:
            return {"card_type": head}
    scope = _scope(text)
    if scope is None:
        return None
    filt: dict = {}
    if scope.subtype:
        if " " in scope.subtype:
            return None  # a multi-word "subtype" is `_scope` guessing — fail closed
        filt["subtype"] = scope.subtype
    if scope.colors:
        if len(scope.colors) != 1:
            return None  # a multi-colour blocker filter needs an OR this shape can't carry
        filt["color"] = scope.colors[0]
    if scope.tokens or not filt:
        return None if scope.tokens else {}
    return filt


#: A basic land type / permanent type "defending player controls …" may name.
_CONTROLS_FILTERS: dict[str, dict] = {
    **{
        f"a{'n' if t[0] in 'aeiou' else ''} {t}": {"subtype": t.capitalize()}
        for t in ("plains", "island", "swamp", "mountain", "forest")
    },
    **{
        f"a{'n' if t[0] in 'aeiou' else ''} {t}": {"card_type": t}
        for t in ("creature", "artifact", "enchantment", "land")
    },
}

#: Number words a "you control three or more creatures" count may use.
_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
}


def _you_control_condition(m: "re.Match[str]") -> Optional[dict]:
    """The "unless you control …" condition family — a count + an optional
    "another"/"other" self-exclusion + a `_blocker_filter`-shaped narrowing."""
    article = (m.group("article") or "").lower()
    other = bool(m.group("other")) or article == "another"
    if m.group("count"):
        count = int(m.group("count"))
        if count > 1 and not (m.group("or_more") or m.group("at_least")):
            return None  # an exact count isn't a threshold — don't guess
    else:
        count = 1
    what = m.group("what").strip().lower()
    filt = object_filter(what)
    if filt is None:
        return None
    if m.group("power"):
        filt = {**filt, "min_power": int(m.group("power"))}
    condition: dict = {"kind": "you_control", "min": count}
    if filt:
        condition["filter"] = filt
    if other:
        condition["other"] = True
    return condition


#: "unless <condition>" → a `GameEngine._combat_condition_met` condition dict.
#: A closed list, ordered most-specific-first; anything unlisted fails closed
#: (the whole clause stays unclaimed).
_CONDITION_RES: list[tuple[re.Pattern[str], Callable[["re.Match[str]"], Optional[dict]]]] = [
    (
        re.compile(r"defending player controls (?P<what>.+)", re.I),
        lambda m: (
            {"kind": "defending_player_controls", "filter": _CONTROLS_FILTERS[m.group("what")]}
            if m.group("what") in _CONTROLS_FILTERS else None
        ),
    ),
    (
        re.compile(r"defending player is the monarch", re.I),
        lambda m: {"kind": "opponent_is_monarch"},
    ),
    (
        re.compile(r"defending player is poisoned", re.I),
        lambda m: {"kind": "opponent_is_poisoned"},
    ),
    (
        re.compile(r"you control more (?P<what>creatures|lands) than "
                   r"(?:defending|attacking) player", re.I),
        lambda m: {
            "kind": "more_creatures_than_opponent" if m.group("what") == "creatures"
            else "more_lands_than_opponent"
        },
    ),
    (
        re.compile(r"a creature died under your control this turn", re.I),
        lambda m: {"kind": "creature_died_this_turn"},
    ),
    (
        re.compile(r"there are (?P<n>\d+) or more cards in your graveyard", re.I),
        lambda m: {"kind": "cards_in_graveyard", "min": int(m.group("n"))},
    ),
    (
        re.compile(r"you have (?P<n>\d+) or (?P<dir>more|fewer) cards? in hand", re.I),
        lambda m: {
            "kind": "cards_in_hand",
            **({"min": int(m.group("n"))} if m.group("dir") == "more"
               else {"max": int(m.group("n"))}),
        },
    ),
    (
        # "you control another Giant" / "you control a Vampire" / "you control
        # another artifact" / "you control another creature with power 4 or
        # greater" / "you control three or more creatures" / "you control at
        # least two other creatures". A bare exact count ("you control 2
        # creatures") isn't a threshold and is rejected below, so ``or more``/
        # ``at least`` is what licenses the numeric branch.
        re.compile(
            r"you control (?:(?P<at_least>at least )?(?P<count>\d+)(?P<or_more> or more)?"
            r"|(?P<article>a|an|another)) "
            r"(?P<other>other )?(?P<what>.+?)"
            r"(?: with power (?P<power>\d+) or greater)?$",
            re.I,
        ),
        _you_control_condition,
    ),
]

def _fold_number_words(text: str) -> str:
    """Spelled-out counts → digits ("three or more creatures" → "3 or more
    creatures"), so one numeric grammar covers both spellings."""
    for word, value in _NUMBER_WORDS.items():
        text = re.sub(rf"\b{word}\b", str(value), text, flags=re.I)
    return text


def _combat_condition(text: str) -> Optional[dict]:
    """An "unless <text>" clause → a condition dict, or ``None`` (fail-closed)."""
    text = _fold_number_words(text.strip().rstrip(".").strip())
    for pattern, build in _CONDITION_RES:
        m = pattern.fullmatch(text)
        if m is not None:
            return build(m)
    return None


#: The subject of a qualified restriction — the same self/attached vocabulary
#: the plain flags use, plus a "you control"-style *group* scope so
#: "Each creature you control with a +1/+1 counter on it …"-free group forms
#: ("Creatures you control can't be blocked by Walls") land too. The group
#: branch reuses the anthem family's `_scope`/`_scope_params`, hence the
#: ``scope``/``yours`` group names those two expect. The trailing ``qkind``/
#: ``qn``/``qdir`` group is a per-object power/toughness qualifier on the
#: scope itself ("Each creature you control **with power 4 or greater**
#: can't be blocked by more than one creature." — Challenger Troll/
#: Flopsie-shaped) — distinct from the restriction *tail*'s own filter
#: (which describes the *other* creature in the interaction, e.g. the
#: blocker), so it gets its own group rather than reusing `object_filter`.
_QUALIFIED_SUBJECT = (
    rf"(?P<subject>~|{_ATTACHED_SUBJECT_PATTERN})"
    rf"|(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)?"
    rf"(?: with (?P<qkind>power|toughness) (?P<qn>\d+) or (?P<qdir>greater|less))?"
)
#: The restriction *tails* (everything after the subject), each mapped to the
#: `combat_restriction` param dicts it means. Ordered so a counted form is
#: tried before the filter form that would otherwise swallow it ("two or more
#: creatures" read as a blocker *description*), and the compound "attack or
#: block" before its two halves. A tail whose filter/condition falls outside
#: the closed vocabulary returns ``None`` — the whole clause then stays
#: unclaimed rather than losing its qualifier.
_TAIL_RES: list[tuple[re.Pattern[str], Callable[["re.Match[str]"], Optional[list[dict]]]]] = [
    (
        re.compile(r"can'?t be blocked by more than (?P<n>\d+) creatures?", re.I),
        lambda m: [{"kind": "max_blockers", "count": int(m.group("n"))}],
    ),
    (
        re.compile(r"can'?t be blocked except by (?P<n>\d+) or more creatures", re.I),
        lambda m: [{"kind": "min_blockers", "count": int(m.group("n"))}],
    ),
    (
        re.compile(r"can'?t be blocked except by (?P<filter>.+)", re.I),
        lambda m: _filter_restriction(m, "only_blocked_by"),
    ),
    (
        re.compile(r"can'?t be blocked as long as it'?s attacking alone", re.I),
        lambda m: [{"kind": "cant_be_blocked_if_attacking_alone"}],
    ),
    (
        re.compile(r"can'?t be blocked by (?P<filter>.+)", re.I),
        lambda m: _filter_restriction(m, "cant_be_blocked_by"),
    ),
    (
        re.compile(r"can'?t attack or block unless (?P<cond>.+)", re.I),
        lambda m: _condition_restriction(m, "cant_attack_unless", "cant_block_unless"),
    ),
    (
        re.compile(r"can'?t attack unless (?P<cond>.+)", re.I),
        lambda m: _condition_restriction(m, "cant_attack_unless"),
    ),
    (
        re.compile(r"can'?t block unless (?P<cond>.+)", re.I),
        lambda m: _condition_restriction(m, "cant_block_unless"),
    ),
    (
        re.compile(r"can'?t attack or block alone", re.I),
        lambda m: [{"kind": "cant_attack_alone"}, {"kind": "cant_block_alone"}],
    ),
    (
        re.compile(r"can'?t attack alone", re.I),
        lambda m: [{"kind": "cant_attack_alone"}],
    ),
    (
        re.compile(r"can'?t block alone", re.I),
        lambda m: [{"kind": "cant_block_alone"}],
    ),
    # The blocker-side pair — printed on the creature doing the blocking
    # rather than the one being blocked. Last, so the "…unless"/"…alone"
    # tails above keep their own rows instead of being read as a (nonsense)
    # blocker filter.
    (
        re.compile(r"can block only (?P<filter>.+)", re.I),
        lambda m: _filter_restriction(m, "can_block_only"),
    ),
    (
        re.compile(r"can'?t block (?P<filter>.+)", re.I),
        lambda m: _filter_restriction(m, "cant_block_filtered"),
    ),
]

#: The *inverted* phrasing of a blocking restriction, where the printed
#: subject is the blocker set and the ability's own source is the object:
#: "Creatures with power less than ~'s power can't block it." (Sedge
#: Troll-shaped). Same `cant_be_blocked_by` restriction as "~ can't be
#: blocked by <filter>", just read off the other end of the sentence — so it
#: gets its own regex rather than a `_QUALIFIED_SUBJECT` row (whose subject
#: group *is* the restricted permanent).
_INVERTED_CANT_BLOCK_RE = re.compile(
    r"(?P<filter>.+?) can'?t block (?:~|it)", re.IGNORECASE
)

#: Subject + an optional "has <keywords> and" grant + the restriction tail.
#: The grant half exists because a handful of Auras print both in one
#: sentence ("Enchanted creature has hexproof and can't be blocked by more
#: than one creature." — Alpha Authority); splitting it here keeps the
#: existing `_ATTACHED_GRANT_RE` family (whose `fullmatch` the tail defeats)
#: unchanged.
_QUALIFIED_CLAUSE_RE = re.compile(
    rf"(?:{_QUALIFIED_SUBJECT})"
    r"(?: (?:has|have) (?P<kw>[a-z, ]+?) and)?"
    # Every tail is a "can't …" except the one *permitted*-set phrasing,
    # "can block only <filter>" (RULE 509.1a, Wall of Air-shaped).
    r" (?P<tail>can'?t .+|can block only .+)",
    re.IGNORECASE,
)


def _filter_restriction(m: "re.Match[str]", kind: str) -> Optional[list[dict]]:
    filt = object_filter(m.group("filter"))
    return None if filt is None else [{"kind": kind, "filter": filt}]


def _condition_restriction(m: "re.Match[str]", *kinds: str) -> Optional[list[dict]]:
    condition = _combat_condition(m.group("cond"))
    return None if condition is None else [{"kind": k, "condition": condition} for k in kinds]


def _qualified_affects(m: "re.Match[str]") -> Optional[dict]:
    """The ``affects``(+selector) params for a `_QUALIFIED_SUBJECT` match, or
    ``None`` for a group scope outside `_scope`'s vocabulary (fail-closed)."""
    subject = m.groupdict().get("subject")
    if subject:
        return {"affects": _combat_restriction_affects(subject)}
    scope = _scope(m.group("body") or "")
    if scope is None:
        return None
    params = _scope_params(scope, m)
    qkind = m.groupdict().get("qkind")
    if qkind:
        # "…with power/toughness N or greater/less" (Challenger Troll/
        # Flopsie-shaped) — a per-object qualifier on the scope itself,
        # `group_selector_objects`'s ``min_power``/``max_power``/
        # ``min_toughness``/``max_toughness``, read fresh off each affected
        # object's own *derived* characteristics at recompute time.
        n = int(m.group("qn"))
        greater = m.group("qdir") == "greater"
        key = f"{'min' if greater else 'max'}_{qkind}"
        params[key] = n
    return params


def _qualified_combat_restriction_specs(text: str) -> Optional[list[EffectSpec]]:
    """The whole qualified-restriction family for one already-normalized
    clause, or ``None`` if it isn't one of these shapes (or is, but names a
    filter/condition outside the closed vocabulary — fail-closed).
    """
    # Spelled-out counts ("more than **one** creature", "except by **two** or
    # more creatures") folded to digits up front, so one numeric grammar
    # covers both spellings — and so the counted tails win the ordering.
    text = _fold_number_words(text)
    inverted = _INVERTED_CANT_BLOCK_RE.fullmatch(text)
    if inverted is not None:
        filt = object_filter(inverted.group("filter"))
        if filt is None:
            return None
        return [EffectSpec("combat_restriction", {
            "kind": "cant_be_blocked_by", "filter": filt, "affects": "self",
        })]

    m = _QUALIFIED_CLAUSE_RE.fullmatch(text)
    if m is None:
        return None
    affects = _qualified_affects(m)
    if affects is None:
        return None
    for pattern, build in _TAIL_RES:
        tail = pattern.fullmatch(m.group("tail"))
        if tail is None:
            continue
        entries = build(tail)
        if entries is None:
            return None
        specs = [EffectSpec("combat_restriction", {**entry, **affects}) for entry in entries]
        if m.group("kw"):  # the "has <keywords> and …" half (Alpha Authority)
            keywords = _flag_keywords(m.group("kw"))
            if keywords is None:
                return None
            specs.insert(0, EffectSpec("grant_keyword", {"keywords": keywords, **affects}))
        return specs
    return None



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
# ``color_from_source`` selector params below (and `_IS_CHOSEN_TYPE_RE`) read
# back.
_CHOOSE_CREATURE_TYPE_ON_ENTER_RE = re.compile(
    r"as ~ enters, choose a creature type", re.IGNORECASE
)
_CHOOSE_COLOR_ON_ENTER_RE = re.compile(r"as ~ enters, choose a color", re.IGNORECASE)
# PAR-4 — Realmwright/A-Thran Portal's "As ~ enters, choose a basic land
# type.": a third `enter_choice_effects` sibling, alongside creature
# type/color above. Anchored on "basic land type" specifically (never just
# "land type" on a real card) so it can't collide with the creature-type row.
_CHOOSE_BASIC_LAND_TYPE_ON_ENTER_RE = re.compile(
    r"as ~ enters, choose a basic land type", re.IGNORECASE
)


def enter_choice_specs(clause: str) -> Optional[list[EffectSpec]]:
    """`EffectSpec`s for a RULE 601.2b "as ~ enters, choose a …" ``clause``,
    or ``None`` — see the module comment above `_CHOOSE_CREATURE_TYPE_ON_
    ENTER_RE`. Called by `segmenter.segment_line` *before*
    `static_effect_specs`, since the two clause families are wrapped as
    different `AbilitySpec.ability_kind`s (``enter_replacement`` vs.
    ``static``).
    """
    text = clause.strip().rstrip(".").strip()
    if _CHOOSE_CREATURE_TYPE_ON_ENTER_RE.fullmatch(text):
        return [EffectSpec("choose_creature_type_on_enter", {})]
    if _CHOOSE_COLOR_ON_ENTER_RE.fullmatch(text):
        return [EffectSpec("choose_color_on_enter", {})]
    if _CHOOSE_BASIC_LAND_TYPE_ON_ENTER_RE.fullmatch(text):
        return [EffectSpec("choose_basic_land_type_on_enter", {})]
    return None


# "~ is the chosen type in addition to its other types." (RULE 601.2b/613.4a,
# A-Thran Portal/Adaptive Automaton-shaped self grant) — the layer-4 sibling
# of the dynamic anthem/grant ``subtype_from_source`` params above, scoped to
# just the source itself (``affects="self"``) rather than a controlled group.
_IS_CHOSEN_TYPE_RE = re.compile(
    r"~ is the chosen type in addition to its other types", re.IGNORECASE
)

# The *group* sibling of `_IS_CHOSEN_TYPE_RE` — "Creatures you control are
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
_GROUP_CHOSEN_TYPE_RE = re.compile(
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
_GRAVEYARD_CHOSEN_TYPE_RE = re.compile(
    r"each creature card in your graveyard has the chosen creature type "
    r"in addition to its other types",
    re.IGNORECASE,
)


def _chosen_type_group_affects(body: str) -> Optional[dict]:
    """The `affects` (+ subtype narrowing) params for a `_GROUP_CHOSEN_TYPE_RE`
    subject phrase, or ``None`` for one this can't express (fail-closed).

    Lands get their own branch since `_scope` deliberately only claims
    *creature* scopes; everything else goes through `_scope` so a tribal
    narrowing ("Vehicle creatures you control", Lifecraft Engine) comes out
    as the usual ``subtype`` param.
    """
    words = body.strip().split()
    if words and words[0] in ("all", "each"):
        words = words[1:]
    if words in (["land"], ["lands"]):
        return {"affects": "lands_you_control"}
    scope = _scope(" ".join(words))
    if scope is None:
        return None
    params: dict = {"affects": "creatures_you_control"}
    if scope.subtype:
        params["subtype"] = scope.subtype
    return params

# "You control enchanted creature/permanent." (Mind Control/Control Magic-
# shaped, RULE 613.2 layer-2 control-grant) — the existing `control_change`
# `StaticAbility` already defaults to ``affects="attached_permanent"`` and a
# controller of "the source's own controller" (exactly "you"), so this needed
# no new engine code, only the parser recognition.
_CONTROL_GRANT_RE = re.compile(
    r"you control (?:enchanted creature|enchanted permanent)", re.IGNORECASE
)

# "<equipped/enchanted/fortified subject> [gets +N/+N and] has \"<ability>\""
# (Sword-of-X-and-Y/Assassin Gauntlet/Caustic Tar-shaped, Umbral Mantle/
# Squirrel Nest-shaped) — an Aura/Equipment granting its host a *full*
# ability rather than a flag keyword. The quoted text is itself an ordinary
# ability line, so it's parsed the same way any top-level card's own line
# would be (`segmenter.segment_line`, imported lazily in
# `_quoted_ability_grant_effects` below — `segmenter` imports *this* module,
# so a module-level import would cycle) and wrapped as a
# `grant_triggered_ability`/`grant_activated_ability` when that recursive
# parse comes back a plain, unconditional shape: a self-scoped trigger on
# one of `_GRANTABLE_TRIGGER_EVENTS`, or a bare `<cost>: <effect>` activated
# ability (fail-closed on everything else: a controller-scoped phase
# trigger like "at the beginning of your upkeep" granted this way is a
# pre-existing gap, not special to grants; see `_GRANTABLE_TRIGGER_EVENTS`).
_ATTACHED_QUOTED_ANTHEM_GRANT_RE = re.compile(
    rf'(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) '
    r'and has "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)
_ATTACHED_QUOTED_GRANT_RE = re.compile(
    rf'(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) has "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)

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
_SOULBOND_QUOTED_GRANT_RE = re.compile(
    rf'{_SOULBOND_SUBJECT} has "(?P<inner>.+)"', re.IGNORECASE | re.DOTALL
)
_SOULBOND_ANTHEM_RE = re.compile(
    rf"{_SOULBOND_SUBJECT} gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    r"(?: and has (?P<kw>[a-z][a-z, ]*))?",
    re.IGNORECASE,
)
_SOULBOND_GRANT_RE = re.compile(
    rf"{_SOULBOND_SUBJECT} (?:has|have) (?P<kw>[a-z][a-z, ]*)", re.IGNORECASE
)

# RULE 701.15b as a *group* static rather than an Aura's ("Creatures your
# opponents control [with power less than ~'s power] are goaded." — Baeloth
# Barrityl, The War Games). The optional power qualifier is a **dynamic**
# threshold read off the source's own derived power every recompute
# (`continuous.dynamic_threshold`), which is why it can't be the literal
# ``max_power`` the group scope already had: an anthem on ~ moves it.
_GROUP_GOADED_RE = re.compile(
    r"(?:all )?creatures (?:your opponents control|you don'?t control)"
    r"(?: with power (?P<cmp>less|greater) than ~'?s power)?"
    r" are goaded",
    re.IGNORECASE,
)


#: WUBRG, for a granted "add N mana of any [one] color" ability — one
#: single-colour production option per colour, the payer picking which
#: (mirrors `game/mana_abilities.py`'s own `_parse_clause` representation
#: exactly; kept as a local literal rather than imported, since this module
#: must stay free of `game/` imports).
_ALL_COLORS = ("W", "U", "B", "R", "G")

#: A granted **mana** ability's inner body — "{T}: Add {B}." (Tyvar Kell),
#: "{T}: Add 1 mana of any color." (Abundant Growth), "{T}: Add 2 mana of any
#: 1 color." (Find the Path — `normalize` folds both number words to digits,
#: including the "any *one* color" one). Recognised *here* rather than by the
#: nested `segment_line` parse below because a plain top-level mana ability is
#: claimed-**without**-a-spec by `segmenter.py`: mana production is covered
#: directly by `game/mana_abilities.py`'s own text recognition off the printed
#: card, not by the `EffectRegistry` pipeline, so the recursive parse comes
#: back with `spec is None` and nothing to re-emit. `grant_mana_ability`
#: (`game/effects.py`, layer 6/RULE 613.7f) is the existing engine primitive
#: — only this front end was missing.
#:
#: `{T}`-only by design: a mana ability with any *other* cost component
#: ("{T}, Sacrifice a creature: …", Animal Boneyard) isn't expressible as a
#: bare `mana` production list, so it stays unclaimed (fail-closed).
_GRANTED_MANA_ABILITY_RE = re.compile(
    r"\{t\}:\s*add\s+(?:"
    r"(?P<syms>(?:\{[wubrgc]\})+)"
    r"|(?P<n>\d+) mana of any (?:1 )?colou?r"
    r")\.?",
    re.IGNORECASE,
)


def _granted_mana_options(inner: str) -> Optional[list[dict[str, int]]]:
    """A quoted mana ability's ``mana`` production options, or ``None``.

    Returns the same "list of ``{colour: amount}`` options, payer picks one"
    shape `mana_abilities.mana_options_for` already consumes for a printed
    ability — a fixed pip run collapses to a single option, an "any colour"
    clause fans out to one option per colour.
    """
    m = _GRANTED_MANA_ABILITY_RE.fullmatch(inner.strip())
    if m is None:
        return None
    syms = m.group("syms")
    if syms:
        option: dict[str, int] = {}
        for sym in re.findall(r"\{([wubrgc])\}", syms, re.IGNORECASE):
            option[sym.upper()] = option.get(sym.upper(), 0) + 1
        return [option]
    amount = int(m.group("n"))
    if amount < 1:
        return None
    return [{color: amount} for color in _ALL_COLORS]


def _quoted_ability_grant_effects(inner: str) -> Optional[EffectSpec]:
    """Recursively parse a quoted granted-ability body into a single
    `grant_triggered_ability`/`grant_activated_ability`/`grant_mana_ability`
    `EffectSpec`, or ``None``. Thin wrapper over `_quoted_ability_grant_
    effects_list` for the callers that only ever expect one spec — returns
    ``None`` when the body would produce more than one (a compound-event
    trigger; those callers pass through the list-returning helper instead)."""
    specs = _quoted_ability_grant_effects_list(inner)
    return specs[0] if specs and len(specs) == 1 else None


def _quoted_ability_grant_effects_list(inner: str) -> Optional[list[EffectSpec]]:
    """Recursively parse a quoted granted-ability body into one or more
    grant `EffectSpec`s, or ``None`` if it isn't a plain self-scoped trigger
    on a `_GRANTABLE_TRIGGER_EVENTS` event (incl. a compound "enters or
    leaves the battlefield" one → one `grant_triggered_ability` per event),
    a controller-scoped phase trigger, a plain `<cost>: <effect>` activated
    ability, or a bare `{T}: Add <mana>` mana ability (see the module
    comment above `_ATTACHED_QUOTED_GRANT_RE`)."""
    from ..segmenter import segment_line  # lazy: segmenter imports this module

    mana = _granted_mana_options(inner)
    if mana is not None:
        return [EffectSpec("grant_mana_ability", {
            "mana": mana, "affects": "attached_permanent",
        })]

    ward = _GRANTED_WARD_RE.fullmatch(inner.strip().rstrip("."))
    if ward is not None:
        return [EffectSpec("grant_keyword", {
            "ward_cost": ward.group("cost").strip(), "affects": "attached_permanent",
        })]

    segment = segment_line(
        inner.strip(),
        allow_spell_effect=False,
        provenance=ParserProvenance(version="nested", source="rule:oracle"),
    )
    spec = segment.spec
    if spec is None or spec.modes:
        return None

    if spec.ability_kind == "activated":
        # "<host> has '{cost}: <effect>.'" (Umbral Mantle/Squirrel
        # Nest-shaped) — layer 6, ability-adding (RULE 613.7f), granting a
        # full activated ability. `once_per_turn`/`sorcery_speed_only`
        # markers mirror `effect_binder.bind_ability`'s own stripping for a
        # top-level activated ability (no real card needs either yet, but a
        # quoted "Activate only once each turn." shouldn't silently leak a
        # marker EffectSpec into `grant_effects` for `build_effects` to choke
        # on) — this nested parse doesn't go through `bind_ability` itself.
        effect_specs = spec.effects
        once_per_turn = any(e.type == ONCE_PER_TURN_MARKER for e in effect_specs)
        sorcery_speed_only = any(e.type == SORCERY_SPEED_MARKER for e in effect_specs)
        effect_specs = [
            e for e in effect_specs
            if e.type not in (ONCE_PER_TURN_MARKER, SORCERY_SPEED_MARKER)
        ]
        return [EffectSpec("grant_activated_ability", {
            "cost": dict(spec.cost or {}),
            "grant_effects": [{"type": e.type, "params": e.params} for e in effect_specs],
            "once_per_turn": once_per_turn,
            "sorcery_speed_only": sorcery_speed_only,
            "affects": "attached_permanent",
        })]

    if spec.ability_kind == "static":
        # MEC-55: "X have '<static ability>'" — an anthem / lord / keyword
        # grant, re-granted per affected object. The inner static's own
        # `affects` must be controller-relative (a group selector — "creature
        # tokens you control get +2/+2", Inspiring Leader); a `self` /
        # `attached_permanent` inner scope would be meaningless once
        # regranted, so fail closed.
        inner_scopes = {e.params.get("affects") for e in spec.effects}
        if not spec.effects or inner_scopes & _REGRANT_UNSUPPORTED_AFFECTS:
            return None
        if any(e.params.get("affects") is None for e in spec.effects):
            return None
        return [EffectSpec("grant_static_ability", {
            "static_specs": [{"type": e.type, "params": e.params} for e in spec.effects],
            "affects": "attached_permanent",
        })]

    if spec.ability_kind != "triggered":
        return None
    trigger = spec.trigger or {}
    event = trigger.get("event")
    # A compound "enters or leaves the battlefield" inner trigger
    # (`segmenter._SELF_MULTI_EVENT_RE`) stamps a *list* of events on
    # `AbilitySpec.trigger`. Re-grant it as one `grant_triggered_ability`
    # per event (each independently identity-scoped by
    # `_granted_trigger_condition`) — every event in the list must itself be
    # grantable and `{"subject": "self"}`, else fail closed for the whole
    # body. `LEAVES_BATTLEFIELD` fires *before* removal (RULE 603.6a), so
    # the granted-to permanent (and its granted ability) still exists when
    # the trigger is collected.
    events = event if isinstance(event, list) else [event]
    if any(e not in _GRANTABLE_TRIGGER_EVENTS for e in events):
        return None
    if len(events) > 1 and trigger.get("condition") != {"subject": "self"}:
        return None
    if len(events) == 1:
        event = events[0]
    if event == "STEP_BEGIN":
        # A RULE 500.7 phase trigger carries no object subject to re-scope
        # (see `_GRANTABLE_TRIGGER_EVENTS`) — only a `phase_relation`, which
        # must resolve against the granted-to permanent's controller. An
        # un-scoped "at the beginning of *each* upkeep" one would fire once
        # per affected permanent per upkeep with no way to tell whose it is,
        # so only the two scoped forms are claimed (fail-closed).
        if trigger.get("phase_relation") not in ("you", "not_you"):
            return None
    elif event == "LIFE_GAINED":
        # RULE 119.3's "Whenever **you** gain life, …" is itself a
        # player-subject condition (`{"subject": "you"}`, not the object-
        # subject `{"subject": "self"}` the `elif` below requires) — the
        # `LIFE_GAINED` branch of `game/continuous.py`'s
        # `_granted_trigger_condition` is what resolves "you" against the
        # granted-to permanent's own controller once regranted.
        if trigger.get("condition") != {"subject": "you"}:
            return None
    elif len(events) == 1 and trigger.get("condition") != {"subject": "self"}:
        return None  # a "group"/other subject wouldn't mean the same thing once regranted
    grant_effects = [{"type": e.type, "params": e.params} for e in spec.effects]
    out: list[EffectSpec] = []
    for ev in events:
        params: dict = {
            "trigger_event": ev,
            "grant_effects": grant_effects,
            "optional": spec.optional,
            "affects": "attached_permanent",
        }
        if trigger.get("filter"):  # RULE 120.3 DAMAGE combat/is_player, STEP_BEGIN's step
            params["filter"] = dict(trigger["filter"])
        if trigger.get("phase_relation"):
            params["phase_relation"] = trigger["phase_relation"]
        out.append(EffectSpec("grant_triggered_ability", params))
    return out


# RULE 702.16 **standing** protection grants — the layer-6 sibling of the
# resolve-time "until end of turn" grant (Mother of Runes) the engine
# already had. Three printed subjects, each its own regex because the verb
# and the `affects` selector differ:
#
#   * a controlled/global group — "Cats you control have protection from
#     Rats." (Hungry Lynx), "White creatures you control have protection
#     from black." (Righteous War), "All creatures have protection from
#     black." (Absolute Grace/Absolute Law). Shares `_scope`/`_scope_params`
#     with `_ANTHEM_RE`/`_GRANT_RE`.
#   * an attached permanent — "Enchanted creature has protection from the
#     chosen color." (Flickering Ward/Cho-Manno's Blessing/Pentarch Ward).
#   * the source itself — "~ has protection from the chosen color." (Voice
#     of All/Order of the Stars).
#
# These must be checked *before* `_GRANT_RE`/`_ATTACHED_GRANT_RE`, whose
# `_flag_keywords` would reject "protection from black" outright (protection
# isn't a RULE 702 flag keyword — it carries a parameter) and fail the whole
# clause closed.
#
# The quality itself is captured as printed and normalized engine-side
# (`continuous._protection_qualities` → `combat.protections_of_text`), which
# is what keeps this module free of `game/` imports. "…and from <quality>"
# multi-quality tails (the Sword cycle's printed form) are left to that same
# splitter by passing the whole clause through.
_PROTECTION_QUALITY = r"(?P<quality>the chosen colou?r|[a-z][a-z ]*?)"
# RULE 702.16n/p's own carve-out on an attached-permanent grant — "This
# effect doesn't remove this Aura/these Auras and Equipment." (Black Ward &c,
# Benevolent Blessing) — an Aura whose granted protection would otherwise
# make *itself* an illegal attachment (RULE 704.5m) the next SBA pass
# (`RulesEngine._attachment_legal`'s `_protection_self_exempt` check). Kept
# optional and non-capturing since it's purely a modifier on the grant, not
# a separate effect; only the attached-permanent shape needs it — no shipped
# card pairs this tail with the group/self forms.
_PROTECTION_SELF_EXEMPT_TAIL = r"(?P<exempt>\. this effect doesn'?t remove [^.]*)?"
_GROUP_PROTECTION_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)?"
    rf"{_CHOSEN_TAIL} "
    rf"have protection from {_PROTECTION_QUALITY}",
    re.IGNORECASE,
)
_ATTACHED_PROTECTION_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) has protection from {_PROTECTION_QUALITY}"
    rf"{_PROTECTION_SELF_EXEMPT_TAIL}",
    re.IGNORECASE,
)
_SELF_PROTECTION_RE = re.compile(
    rf"~ has protection from {_PROTECTION_QUALITY}", re.IGNORECASE
)

# The compound "+N/+N **and** protection" forms — the whole Sword-of-X-and-Y
# cycle ("Equipped creature gets +2/+2 and has protection from red and from
# blue.", 24 cards) and its group sibling (Feline Sovereign/Haytham Kenway's
# "Other Cats you control get +1/+1 and have protection from Dogs."). These
# need their own rows rather than an extra tail on `_ATTACHED_ANTHEM_RE`/
# `_ANTHEM_RE`, whose "and has/have <keywords>" tail goes through
# `_flag_keywords` — protection isn't a RULE 702 flag keyword (it carries a
# parameter), so that tail rejects it and fails the whole clause closed.
_ATTACHED_ANTHEM_PROTECTION_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) "
    rf"and has protection from {_PROTECTION_QUALITY}"
    rf"{_PROTECTION_SELF_EXEMPT_TAIL}",
    re.IGNORECASE,
)
_GROUP_ANTHEM_PROTECTION_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)?"
    rf"{_CHOSEN_TAIL} "
    rf"get (?P<p>[+-]\d+)/(?P<t>[+-]\d+) and have protection from {_PROTECTION_QUALITY}",
    re.IGNORECASE,
)


def _protection_params(quality: str) -> Optional[dict]:
    """The `grant_protection` quality params for a captured ``quality``, or
    ``None`` for one this can't express (fail-closed).

    "the chosen color" (RULE 601.2b) becomes the dynamic flag the layer
    engine re-reads off the source every pass; "each color"/"each colour"
    (Spectra Ward) is a fixed blanket quality — unlike Rebbec's "each mana
    value among..." below, it names no board-dependent computation, so it
    folds to the same "all colors" word `combat.protections_of_text`
    already recognizes. Anything else is passed through verbatim as a
    printed quality word for that function to normalize. Rebbec's
    "protection from each mana value among artifacts you control" and
    Pledge of Loyalty's "the colors of permanents you control" are
    deliberately *not* expressible — a per-source computed quality, not a
    fixed one — and neither is a plain quality word/phrase, so both fall out
    here (" each "/" of ") rather than being mis-stored as one.
    """
    quality = quality.strip().rstrip(".").strip()
    if quality in ("the chosen color", "the chosen colour"):
        return {"protection_from_chosen_color": True}
    if quality in ("each color", "each colour"):
        return {"protections": ["all colors"]}
    if quality == "creatures of the chosen type":
        return {"protection_from_chosen_type": True}
    if not quality or " each " in f" {quality} " or " of " in f" {quality} ":
        return None
    return {"protections": [q.strip() for q in re.split(r"\s+and\s+from\s+", quality)]}


# PAR-8: "Each [<filter>] card in your hand has cycling `<cost>`." (Jo
# Grant/Rhet-Tomb Mystic/Tectonic Reformation) — a layer-6 ability grant
# whose *targets* are hand cards, a zone `_scope`/`_GRANT_RE`'s battlefield
# selectors never reach; `game/continuous.py`'s dedicated
# `_apply_hand_cycling_grants` pass is the engine side. ``filter`` is an
# optional printed card type, or "historic" (CR glossary: legendary, an
# artifact, or a Saga) — bare "each card in your hand" (no filter) is also
# real wording (the ticket's own example) and simply omits the group. Never
# collides with `_GRANT_RE`/`_ANTHEM_RE` (plural "have"/"get") or the
# attached-subject rows (enchanted/equipped/fortified only) — this is
# singular "has" over a subject none of those recognize.
_HAND_CYCLING_TYPES = (
    "creature", "land", "artifact", "enchantment", "instant", "sorcery",
    "planeswalker", "historic",
)
_HAND_CYCLING_GRANT_RE = re.compile(
    rf"each (?:(?P<filter>{'|'.join(_HAND_CYCLING_TYPES)}) )?card in your hand "
    rf"has cycling (?P<cost>\{{[^}}]+\}}(?:\{{[^}}]+\}})*)",
    re.IGNORECASE,
)


# MEC-53 / PAR-31: "[<filter>] cards in your graveyard have retrace."
# (Wrenn and Six's −7 emblem — "instant and sorcery cards …"; Deeproot
# Historian — "Merfolk and Druid cards …"; bare "cards in your graveyard
# have retrace"). Retrace is the only keyword that means anything on a
# *graveyard* card (RULE 702.81 — a cast-from-graveyard permission), so
# this row hardcodes it rather than sharing `_flag_keywords`. `<filter>`
# is an optional list of main-type words (`card_types`) and/or creature
# subtypes (`subtypes`), split in `_graveyard_retrace_grant_specs`.
_GRAVEYARD_RETRACE_GRANT_RE = re.compile(
    r"(?:(?P<filter>[a-z][a-z, ]*?) )?cards in your graveyard have retrace",
    re.IGNORECASE,
)


# "<equipped/enchanted/fortified subject> gets +N/+N [and has <keywords>]"
# (attached-permanent anthem, +grant) — singular "gets"/"has", unlike the
# plural "get"/"have" of `_ANTHEM_RE`/`_GRANT_RE` above (those two families
# never collide on the same clause text).
_ATTACHED_ANTHEM_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) "
    r"gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    r"(?: and has (?P<kw>[a-z][a-z, ]*?))?"
    # RULE 701.15b: "…and is goaded" (Acquired Mutation and 7 siblings — the
    # single most common goad phrasing on a card). A tail rather than its own
    # row because it only ever appears *after* the P/T (and optionally the
    # keyword) grant of the same Aura/Equipment.
    r"(?P<goaded> and is goaded)?",
    re.IGNORECASE,
)
# "<equipped/enchanted/fortified subject> has <keywords>"  (keyword-only grant)
_ATTACHED_GRANT_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) has (?P<kw>[a-z][a-z, ]*?)"
    r"(?P<goaded> and is goaded)?",
    re.IGNORECASE,
)
# "<enchanted subject> is goaded" — the bare designation with no other grant
# alongside it (RULE 701.15b).
_ATTACHED_GOADED_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) is goaded",
    re.IGNORECASE,
)
# RULE 613.6/701.37b: "As long as ~ is monstrous, it has <keywords>."
# (Chillerpillar, Colossus of Akros &c) — the *conditional* sibling of the
# self-grant rows, gating the grant on the source's own monstrous
# designation. Only the keyword-grant tail is claimed: the two real cards
# whose tail also says "and can attack as though it didn't have defender" /
# "can block an additional 99 creatures" stay unclaimed, whole clause, rather
# than being half-modeled.
_MONSTROUS_GRANT_RE = re.compile(
    r"as long as ~ is monstrous, (?:it|~) has (?P<kw>[a-z][a-z, ]*)",
    re.IGNORECASE,
)


class _Scope(NamedTuple):
    subtype: Optional[str]  # a creature type ("Goblin"), or None for "creatures"
    tokens: bool  # True for "<…> tokens" (Intangible Virtue)
    colors: list  # WUBRG/C symbols; empty = no colour restriction (Bad Moon)
    #: PAR-3: "Artifact creatures you control get +1/+1" (Chief of the
    #: Foundry-shaped) — still a *creature* scope (RULE 205.2b: an artifact
    #: creature is both types), just narrowed by the printed card type
    #: rather than a creature subtype. Kept distinct from ``subtype``:
    #: `continuous.py`'s ``_has_subtype`` reads the type line's text
    #: *after* the em dash, where "Artifact" never appears (it's a type
    #: word, not a subtype) — this instead rides the generic ``card_type``
    #: filter param every `affected_objects` selector already supports.
    card_type: Optional[str] = None


def _singularize(word: str) -> str:
    """A plural creature type → singular ("goblins"→"goblin", "elves"→"elf")."""
    if word.endswith("ves"):
        return word[:-3] + "f"
    if word.endswith("s"):
        return word[:-1]
    return word


def _scope(body: str) -> Optional[_Scope]:
    """Parse a scope phrase into a `_Scope`, or ``None`` for a non-creature scope.

    Handles a leading global marker ("all"/"each"), leading colour words
    ("black", "white and blue"), "creatures", a plural type ("goblins"),
    "<type> creatures", and the "<…> tokens" variants — always fail-closed
    (returns ``None`` rather than guess a scope it doesn't recognise).
    """
    words = body.split()
    while words and words[0] in ("all", "each"):  # global emphasis, no scope change
        words = words[1:]

    colors: list = []
    while words:
        if words[0] in _COLOR_WORDS:
            colors.append(_COLOR_WORDS[words[0]])
            words = words[1:]
        elif words[0] in ("and", "or") and len(words) > 1 and words[1] in _COLOR_WORDS:
            words = words[1:]  # skip a colour connector ("white and blue")
        else:
            break

    tokens = False
    if words and words[-1] == "tokens":
        tokens = True
        words = words[:-1]
        if not words:  # bare "tokens" (creature tokens implied)
            return _Scope(None, True, colors)

    if words in (["creature"], ["creatures"]):
        return _Scope(None, tokens, colors)
    if not words:
        return None
    if words[-1] == "creatures":
        prefix = words[:-1]
        # "Artifact/Enchantment/Land/Planeswalker creatures [you control]
        # get/have …" (PAR-3) — a single printed card-type word ahead of
        # "creatures" narrows *which* creatures, it doesn't change the scope
        # away from creatures the way a bare "Artifacts you control" would.
        if len(prefix) == 1 and prefix[0] in (_CARD_TYPE_WORDS - {"creature"}):
            return _Scope(None, tokens, colors, card_type=prefix[0])
        sub = _singularize(" ".join(prefix))
    elif len(words) == 1:
        sub = _singularize(words[0])
        # A *bare* artifact-subtype word ("Vehicles [you control]") is never
        # a creature scope — unlike the "<word> creatures" branch above
        # (RULE 205.2b's "Vehicle creatures", genuinely creature-scoped,
        # just narrowed further by the printed subtype), nothing here says
        # "creatures" at all, so this must fall through to `_ANTHEM_RE`/
        # `_GRANT_RE`/`_QUOTED_GRANT_RE`'s `_vehicle_scope_params` fallback
        # instead of being guessed as a creature subtype (a Vehicle isn't a
        # creature until crewed, RULE 702.122a).
        if sub in _ARTIFACT_SUBTYPES:
            return None
    else:
        return None  # multi-word non-"creatures" scope — don't guess
    if not sub or sub in _NONCREATURE_TYPES:
        return None
    return _Scope(sub.capitalize(), tokens, colors)


def _scope_params(scope: _Scope, m: "re.Match[str]") -> dict:
    """Build the `affects` + filter params from a scope and the clause match.

    ``affects`` is the base set; "you control" scopes it to the controller (and
    "other" excludes the source), while its absence makes the anthem global
    (RULE 613 — all creatures). Subtype/colour/tokens narrow the set further.
    """
    other = bool(m.group("scope"))
    yours = bool(m.group("yours"))
    if yours:
        params: dict = {"affects": "other_creatures_you_control" if other
                        else "creatures_you_control"}
    else:
        params = {"affects": "all_creatures"}
        if other:  # a global "Other creatures …" excludes just the source
            params["exclude_self"] = True
    if scope.subtype:
        params["subtype"] = scope.subtype
    if scope.card_type:  # "Artifact/Enchantment/… creatures …" (PAR-3)
        params["card_type"] = scope.card_type
    # "… of the chosen type/color …" (RULE 601.2b) — a dynamic sibling of the
    # literal subtype/colour params above, read fresh off the ability's own
    # source at recompute time (`continuous.group_selector_objects`). Only
    # `_ANTHEM_RE`/`_GRANT_RE` carry a "chosen" group; every other caller of
    # this function matches a body with no such group at all.
    chosen = m.groupdict().get("chosen")
    if chosen == "type":
        params["subtype_from_source"] = True
    elif chosen == "color":
        params["color_from_source"] = True
    if scope.tokens:
        params["tokens"] = True
    if scope.colors:
        params["color"] = scope.colors
    return params


#: PAR-3 — a *bare* non-creature permanent **type** word ("artifacts", "other
#: enchantments"), for `_GRANT_RE`/`_QUOTED_GRANT_RE` (and, since Balthier and
#: Fran, `_ANTHEM_RE` too — a bare "+N/+N" clause on a non-creature permanent
#: *is* printed on a real card after all: "Vehicles you control get +1/+1").
#: word -> (the "you control" selector, the global selector). Every selector
#: named here already exists in `game/continuous.py`'s `group_selector_
#: objects` — PAR-3 is parser-side recognition only, no new engine primitive.
#: A bare *subtype* word ("vehicles") isn't in this table at all — see
#: `_ARTIFACT_SUBTYPES`/`_vehicle_scope_params` instead.
_PERMANENT_TYPE_AFFECTS: dict[str, tuple[str, str]] = {
    "artifact": ("artifacts_you_control", "all_permanents"),
    "enchantment": ("permanents_you_control", "all_permanents"),
    "land": ("lands_you_control", "all_lands"),
    "planeswalker": ("permanents_you_control", "all_permanents"),
    "permanent": ("permanents_you_control", "all_permanents"),
}

#: Which selector above already filters by the word on its own — everything
#: else (enchantment/planeswalker, or the global sibling of artifact/land)
#: is broader than the printed word and needs the generic `card_type` filter
#: layered on top, same as the "Artifact creatures" case in `_scope_params`.
_PERMANENT_TYPE_INHERENT: dict[str, str] = {
    "artifacts_you_control": "artifact",
    "lands_you_control": "land",
    "all_lands": "land",
}


def _permanent_type_scope(body: str) -> Optional[str]:
    """A bare `_PERMANENT_TYPE_AFFECTS` word ("artifacts", "other
    enchantments") → the word itself, or ``None`` for anything `_scope`
    should own instead (a creature scope) or that this deliberately doesn't
    guess (a compound "artifacts and enchantments" — no engine selector
    ORs two card types yet; colour/subtype narrowing — no real card
    combines them with a non-creature scope).
    """
    words = body.split()
    while words and words[0] in ("all", "each"):
        words = words[1:]
    if len(words) != 1:
        return None
    word = _singularize(words[0])
    return word if word in _PERMANENT_TYPE_AFFECTS else None


def _permanent_scope_params(word: str, m: "re.Match[str]") -> dict:
    """The `affects`(+``card_type``) params for a `_permanent_type_scope`
    word — the non-creature sibling of `_scope_params`'s "you control"/
    "other"/global logic, over `_PERMANENT_TYPE_AFFECTS`'s selectors.

    Unlike the creature family (which has a dedicated "other_creatures_you_
    control" selector), there's no "other_enchantments_you_control" here —
    "other" always goes through the general `exclude_self` filter instead,
    in *both* the "you control" and global cases ("Other enchantments **you
    control** have shroud." — Sterling Grove; "Other enchantments have
    '…'." — Aura Flux).
    """
    other = bool(m.group("scope"))
    yours = bool(m.group("yours"))
    you_control_sel, global_sel = _PERMANENT_TYPE_AFFECTS[word]
    params: dict = {"affects": you_control_sel if yours else global_sel}
    if other:
        params["exclude_self"] = True
    if _PERMANENT_TYPE_INHERENT.get(params["affects"]) != word:
        params["card_type"] = word
    return params


def _multi_permanent_type_list(body: str) -> Optional[list[str]]:
    """A "artifacts, creatures, enchantments, and lands" scope phrase →
    the ordered, de-duplicated list of singular `_CARD_TYPE_WORDS` in it,
    or ``None`` (fail-closed) if it isn't two or more recognised
    permanent-type words. Splits on commas and "and" (RULE-text list
    punctuation), tolerating the Oxford comma.
    """
    words = [
        _singularize(p.strip())
        for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", body.strip())
        if p.strip()
    ]
    if not words or any(w not in _CARD_TYPE_WORDS for w in words):
        return None
    seen: list[str] = []
    for w in words:
        if w not in seen:
            seen.append(w)
    return seen if len(seen) >= 2 else None


#: Subtypes accepted in a graveyard-retrace grant's `<filter>` list
#: (Deeproot Historian's tribal scope). Kept tiny and explicit — only the
#: subtypes a real printed Retrace-grant card names.
_RETRACE_GRANT_SUBTYPES: frozenset[str] = frozenset({"merfolk", "druid"})
#: Main-type words a graveyard-card filter can name — the permanent types
#: plus instant/sorcery (a graveyard holds non-permanent cards too), all of
#: which `continuous._has_card_type` already recognises.
_GRAVEYARD_CARD_TYPE_WORDS: frozenset[str] = _CARD_TYPE_WORDS | {"instant", "sorcery"}


def _graveyard_retrace_grant_specs(filt: Optional[str]) -> Optional[list[EffectSpec]]:
    """The `grant_retrace` spec for a "[<filter>] cards in your graveyard
    have retrace" clause, or ``None`` (fail-closed) on an unrecognised
    filter word. ``filt`` is ``None`` for the bare form, else a comma/"and"
    list of `_CARD_TYPE_WORDS` (→ ``card_types``) and/or
    `_RETRACE_GRANT_SUBTYPES` (→ ``subtypes``); "nonland" alone sets
    ``nonland_only``.
    """
    params: dict[str, Any] = {}
    if filt:
        words = [
            _singularize(p.strip())
            for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", filt.strip())
            if p.strip()
        ]
        card_types: list[str] = []
        subtypes: list[str] = []
        for w in words:
            if w == "nonland":
                params["nonland_only"] = True
            elif w in _GRAVEYARD_CARD_TYPE_WORDS:
                card_types.append(w)
            elif w in _RETRACE_GRANT_SUBTYPES:
                subtypes.append(w.capitalize())
            else:
                return None
        if card_types:
            params["card_types"] = card_types
        if subtypes:
            params["subtypes"] = subtypes
        if not params:
            return None
    return [EffectSpec("grant_retrace", params)]


def _is_vehicle_scope(body: str) -> bool:
    """A bare "[other] Vehicles [you control]" scope (Balthier and Fran) —
    the `_ARTIFACT_SUBTYPES` sibling of `_permanent_type_scope`'s bare
    main-type check, since "vehicle" is a *subtype* (`continuous.
    _has_subtype`), not one of `_PERMANENT_TYPE_AFFECTS`'s main-type words.
    """
    words = body.split()
    while words and words[0] in ("all", "each"):
        words = words[1:]
    return len(words) == 1 and _singularize(words[0]) in _ARTIFACT_SUBTYPES


def _vehicle_scope_params(m: "re.Match[str]") -> dict:
    """The `affects`(+``subtype``) params for a bare Vehicle scope — the
    `_ARTIFACT_SUBTYPES` sibling of `_permanent_scope_params`, always
    narrowed to the printed subtype (unlike that function's ``card_type``,
    which only appears when the base selector is broader than the printed
    word — ``artifacts_you_control``/``all_permanents`` are both broader
    than "Vehicles" alone, so this narrows every time).
    """
    other = bool(m.group("scope"))
    yours = bool(m.group("yours"))
    params: dict = {
        "affects": "artifacts_you_control" if yours else "all_permanents",
        "subtype": "Vehicle",
    }
    if not yours:
        params["card_type"] = "artifact"
    if other:
        params["exclude_self"] = True
    return params


# ---------------------------------------------------------------------------
# RULE 613.6 "as long as <condition>, <static>" — the general conditional
# wrapper (`game/static_conditions.py` holds the evaluator + the whitelist).
#
# Both printed orders are real and roughly as common: the condition leads
# ("As long as ~ is monstrous, it has trample.") or trails ("Creatures you
# control get +1/+1 as long as you control an artifact."). Either way this
# parses the *condition* here and hands the remaining clause back to
# `static_effect_specs`, so a conditional static is exactly its unconditional
# self plus an ``active_if`` — no family needs its own conditional variant.
# ---------------------------------------------------------------------------

#: The condition sub-grammar: (regex over the condition text, builder). Only
#: shapes whose `static_conditions` kind exists — anything else leaves the
#: whole clause unclaimed (fail-closed), which is why this list is ordered
#: most-specific-first.
_STATIC_CONDITION_RES: list[tuple[re.Pattern[str], Any]] = [
    # -- The source's own state. "it"/"~" both appear; after `normalize` the
    # card's own name is already `~`, and a leading "it" in this position can
    # only mean the source (the condition precedes any target).
    (re.compile(r"(?:~|it)(?:'s| is| remains) untapped", re.I),
     lambda m: {"kind": "source_untapped"}),
    (re.compile(r"(?:~|it)(?:'s| is| remains) tapped", re.I),
     lambda m: {"kind": "source_tapped"}),
    (re.compile(r"(?:~|it)(?:'s| is) monstrous", re.I),
     lambda m: {"kind": "source_monstrous"}),
    (re.compile(r"(?:~|it)(?:'s| is) attacking", re.I),
     lambda m: {"kind": "source_attacking"}),
    (re.compile(r"(?:~|it)(?:'s| is) blocking", re.I),
     lambda m: {"kind": "source_blocking"}),
    (re.compile(r"(?:~|it) is paired with another creature", re.I),
     lambda m: {"kind": "source_paired"}),
    (re.compile(r"(?:~|it) is attached to a creature", re.I),
     lambda m: {"kind": "source_attached"}),
    (re.compile(r"(?:~|it)(?:'s| is) equipped", re.I),
     lambda m: {"kind": "source_equipped"}),
    (re.compile(r"(?:~|it)(?:'s| is) enchanted", re.I),
     lambda m: {"kind": "source_enchanted"}),
    # "~ has three or more +1/+1 counters on it" / "…a +1/+1 counter on it"
    (re.compile(r"(?:~|it) has (?P<n>a|an|\d+) or more (?P<kind>[+\-]\d/[+\-]\d|[a-z ]+?) counters? on it", re.I),
     lambda m: {"kind": "source_counters", "counter": _counter_kind(m.group("kind")),
                "min": _count_word(m.group("n"))}),
    (re.compile(r"(?:~|it) has (?P<n>a|an|\d+) (?P<kind>[+\-]\d/[+\-]\d|[a-z ]+?) counters? on it", re.I),
     lambda m: {"kind": "source_counters", "counter": _counter_kind(m.group("kind")),
                "min": _count_word(m.group("n"))}),
    # -- The *attached permanent*'s characteristics, not the source's
    # ("as long as enchanted permanent is a creature"/"…is red"/"…is a
    # Human"). Same kinds as any other subject; the ``of`` key is what aims
    # them at the Aura/Equipment's host (RULE 303.4a/301.5c).
    (re.compile(rf"(?:{_ATTACHED_SUBJECT_PATTERN}) is an? (?P<what>[a-z]+)", re.I),
     lambda m: _attached_characteristic(m.group("what"))),
    (re.compile(rf"(?:{_ATTACHED_SUBJECT_PATTERN}) is (?P<what>[a-z]+)", re.I),
     lambda m: _attached_characteristic(m.group("what"))),
    # -- Whose turn it is.
    (re.compile(r"it's your turn", re.I), lambda m: {"kind": "your_turn"}),
    (re.compile(r"it's not your turn", re.I), lambda m: {"kind": "not_your_turn"}),
    # -- The controller's designations (RULE 725/726/702.131c) — MEC-12.
    (re.compile(r"you'?re the monarch", re.I), lambda m: {"kind": "is_monarch"}),
    (re.compile(r"you have the initiative", re.I), lambda m: {"kind": "has_initiative"}),
    (re.compile(r"you have the city'?s blessing", re.I), lambda m: {"kind": "has_city_blessing"}),
    # -- Board counts, over `continuous.count_selector`'s own vocabulary.
    (re.compile(r"you control (?P<n>\d+) or more (?P<what>[a-z ]+)", re.I),
     lambda m: _control_count_condition(m.group("what"), int(m.group("n")))),
    # "you control a creature with power N or greater" (Bolt Bend and 50+
    # other cache cards' cost-reduction/activation-condition gates) — a
    # per-object power qualifier layered onto the plain existence count
    # `_control_count_condition` handles; tried before that catch-all row
    # (though it can never match this text anyway — its ``[a-z ]+`` can't
    # span the digit).
    (re.compile(r"you control a creature with power (?P<n>\d+) or greater", re.I),
     lambda m: {"kind": "control_count", "selector": "creatures_you_control",
                "min": 1, "min_power": int(m.group("n"))}),
    (re.compile(r"you control (?:a|an) (?P<what>[a-z ]+)", re.I),
     lambda m: _control_count_condition(m.group("what"), 1)),
    (re.compile(r"there are (?P<n>\d+) or more cards in your graveyard", re.I),
     lambda m: {"kind": "control_count", "selector": "cards_in_your_graveyard",
                "min": int(m.group("n"))}),
    # The Odyssey-block Threshold phrasing — "as long as **seven or more
    # cards are in your graveyard**" (subject-verb order rather than the
    # "there are …" existential above; the "Threshold —" ability-word label
    # is stripped by `normalize._strip_ability_words` first).
    (re.compile(r"(?P<n>\d+) or more cards are in your graveyard", re.I),
     lambda m: {"kind": "control_count", "selector": "cards_in_your_graveyard",
                "min": int(m.group("n"))}),
    # RULE 702.137 "Delirium" ("delirium — as long as there are 4 or more
    # card types among cards in your graveyard, …" — the ability word itself
    # is stripped by `normalize._strip_ability_words` before this ever runs,
    # leaving the bare "as long as" clause `_conditional_static_specs`
    # already routes here).
    (re.compile(r"there are (?P<n>\d+) or more card types among cards in your graveyard", re.I),
     lambda m: {"kind": "card_types_in_graveyard_at_least", "amount": int(m.group("n"))}),
    # PAR-30: "as long as there's a `<subtype>` card in your graveyard" (the
    # Avatar: TLA "Lesson" cards). Bounded to a single subtype word so it
    # can't swallow a longer "N or more <x> cards" phrasing (handled above).
    (re.compile(r"there(?:'s| is| are) an? (?P<sub>[a-z][a-z-]+) card in your graveyard", re.I),
     lambda m: {"kind": "subtype_in_graveyard", "subtype": m.group("sub").lower()}),
    # -- The controller's own resources.
    (re.compile(r"you have (?P<n>\d+) or more life", re.I),
     lambda m: {"kind": "life_at_least", "amount": int(m.group("n"))}),
    (re.compile(r"you have (?P<n>\d+) or less life", re.I),
     lambda m: {"kind": "life_at_most", "amount": int(m.group("n"))}),
    (re.compile(r"you have (?P<n>\d+) or more cards in hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_least", "amount": int(m.group("n"))}),
    (re.compile(r"you have (?P<n>\d+) or fewer cards in hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_most", "amount": int(m.group("n"))}),
    (re.compile(r"you have no cards in hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_most", "amount": 0}),
    # "as long as you've drawn two or more cards this turn" — read off
    # `GameState.cards_drawn_this_turn`, which already exists for the
    # draw-limit permission.
    (re.compile(r"you'?ve drawn (?P<n>\d+) or more cards this turn", re.I),
     lambda m: {"kind": "drawn_cards_at_least", "amount": int(m.group("n"))}),
    # "as long as an opponent has eight or more cards in their graveyard" —
    # `control_count`'s opponent-scoped sibling; "an opponent" means *any*
    # one of them satisfies it.
    (re.compile(
        r"an opponent has (?P<n>\d+) or more cards in (?:their|his or her) graveyard", re.I),
     lambda m: {"kind": "opponent_count", "selector": "cards_in_your_graveyard",
                "min": int(m.group("n"))}),
    # "an opponent controls a multicolored permanent" (Ghostfire Slice) —
    # `opponent_count`'s sibling to the "you control a/an `<x>`" row above.
    (re.compile(r"an opponent controls (?:a|an) (?P<what>[a-z ]+)", re.I),
     lambda m: _opponent_control_condition(m.group("what"))),
    # PAR-10: "as long as you've cast an instant or sorcery spell this
    # turn" (Haunting Figment/Leapfrog/Piston-Fist Cyclops) — the same
    # `cast_instant_or_sorcery_this_turn` condition kind
    # `catalogue.handlers`'s activation-condition family reuses for Hall of
    # Oracles/Jin-Gitaxias's "Activate only … and only if …" shape.
    (re.compile(r"you'?ve cast an instant or sorcery spell this turn", re.I),
     lambda m: {"kind": "cast_instant_or_sorcery_this_turn"}),
    # RULE 202.2f/700.6: "as long as your devotion to `<colour(s)/wedge>` is
    # less than `<n>`, `<name>` isn't a creature." (Purphoros/Heliod/Erebos'
    # own single-colour gods; Athreos/Karametra's "white and black"/"green
    # and white" two-colour reading) — `control_count`'s existing ``max``
    # bound already expresses a strict "less than" as "at most N-1"; no new
    # condition kind needed, just this phrase recognized into it.
    (re.compile(rf"{DEVOTION} is less than (?P<n>\d+)", re.I),
     lambda m: (
         {"kind": "control_count", "selector": devotion_selector(m), "max": int(m.group("n")) - 1}
         if devotion_selector(m) else None
     )),
]

#: The characteristic words an "as long as `<attached subject>` is `<word>`"
#: condition may name — a card type, a colour, or a creature subtype, in that
#: precedence order. Deliberately closed: a word that is none of the three
#: (an ability word, a supertype) fails the whole clause closed rather than
#: becoming a subtype filter that silently never matches.
def _attached_characteristic(word: str) -> Optional[dict]:
    word = word.strip().lower()
    if word in _CARD_TYPE_WORDS:
        return {"kind": "is_card_type", "card_type": word, "of": "attached"}
    if word in _COLOR_CONDITION_WORDS:
        return {"kind": "is_color", "color": _COLOR_CONDITION_WORDS[word], "of": "attached"}
    if word in _CONDITION_SUBTYPE_WORDS:
        return {"kind": "is_subtype", "subtype": word, "of": "attached"}
    return None


#: RULE 105.1's five colours as an "…is red" condition would print them.
_COLOR_CONDITION_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

#: The creature/artifact subtypes real "as long as enchanted `<x>` is a `<y>`"
#: clauses actually name. Kept small and explicit for the same reason
#: `_CONTROL_COUNT_SELECTORS` is: an open subtype vocabulary here would claim
#: clauses whose word is really something else entirely.
_CONDITION_SUBTYPE_WORDS: frozenset[str] = frozenset(
    {"vehicle", "human", "goblin", "elf", "zombie", "spirit", "warrior", "knight", "soldier",
     "equipment", "aura", "dragon", "angel", "demon", "wizard", "cleric", "rogue", "beast"}
)

#: "you control an <what>" → the `count_selector` name, or ``None``
#: (fail-closed) for a scope that has no selector. Deliberately small: only
#: the selectors `continuous.count_selector` actually implements.
_CONTROL_COUNT_SELECTORS: dict[str, str] = {
    "artifact": "artifacts_you_control",
    "artifacts": "artifacts_you_control",
    "creature": "creatures_you_control",
    "creatures": "creatures_you_control",
    "land": "lands_you_control",
    "lands": "lands_you_control",
    "permanent": "permanents_you_control",
    "permanents": "permanents_you_control",
    "multicolored permanent": "multicolored_permanents_you_control",
    "multicolored permanents": "multicolored_permanents_you_control",
}


def _control_count_condition(what: str, minimum: int) -> Optional[dict]:
    selector = _CONTROL_COUNT_SELECTORS.get(what.strip().lower())
    return None if selector is None else {
        "kind": "control_count", "selector": selector, "min": minimum
    }


def _opponent_control_condition(what: str) -> Optional[dict]:
    """"An opponent controls a/an `<filter>`." (Ghostfire Slice's own
    `active_if`) — `opponent_count`'s sibling to `_control_count_condition`,
    same selector dict, always ``min=1`` (a plain "controls a" has no count
    of its own to carry, unlike "controls N or more `<x>`")."""
    selector = _CONTROL_COUNT_SELECTORS.get(what.strip().lower())
    return None if selector is None else {
        "kind": "opponent_count", "selector": selector, "min": 1
    }


def _counter_kind(text: str) -> str:
    """A counter name as printed → the engine's own kind string."""
    text = text.strip().lower()
    return "+1/+1" if text in ("+1/+1", "+1/+1 ") else text


def _count_word(text: str) -> int:
    return 1 if text.strip().lower() in ("a", "an") else int(text)


def static_condition(text: str) -> Optional[dict]:
    """A condition phrase ("~ is monstrous") → an ``active_if`` dict.

    ``None`` for anything outside the whitelist, which fails the *whole*
    clause closed rather than dropping the condition and applying the static
    unconditionally — a static that should be gated but isn't is strictly
    worse than an unmodeled card.
    """
    stripped = text.strip().rstrip(".").strip()
    for pattern, build in _STATIC_CONDITION_RES:
        if pattern.fullmatch(stripped):
            return build(pattern.fullmatch(stripped))
    return None


#: "As long as <cond>, <static>." and "<static> as long as <cond>." The inner
#: clause is bounded away from a second "as long as" so a doubly-conditional
#: line fails closed instead of silently binding only the outer gate.
_AS_LONG_AS_LEADING_RE = re.compile(
    r"(?:for )?as long as (?P<cond>[^,]+), (?P<inner>.+)", re.I
)
_AS_LONG_AS_TRAILING_RE = re.compile(
    r"(?P<inner>.+?) (?:for )?as long as (?P<cond>(?!.*\bas long as\b)[^,]+)", re.I
)

#: "During your turn, <static>." (ENG-28, RULE 613.6's other common gate
#: phrasing besides "as long as" — Ahn-Crop Invader/Blood Burglar/Grand
#: Abolisher-shaped, 156 solo-blocked cards cache-wide). Fixed to the
#: ``your_turn`` condition rather than routed through `static_condition`,
#: since the phrase itself is the whole condition — there's no separate
#: ``cond``/``inner`` split to parse a *kind* out of. Leading-only: every
#: sampled card prints the gate first, and a trailing "…during your turn."
#: form risks colliding with an "activate only during your turn" *activation*
#: timing restriction (a different, `condition_query.py` concept) if ever
#: added later, so that form is deliberately not claimed here.
_DURING_YOUR_TURN_LEADING_RE = re.compile(r"during your turn,\s*(?P<inner>.+)", re.IGNORECASE)

#: "Ward—Pay 2 life." as a *quoted granted* keyword line (Hexing Squelcher's
#: "Other creatures you control have 'Ward—Pay 2 life.'") — RULE 702.21's
#: cost may be any clause (mana, life, sacrifice, discard, …), not just
#: mana, so the raw text is handed to `costs.parse_activation_cost`
#: downstream rather than re-parsed here.
_GRANTED_WARD_RE = re.compile(r"^ward[\s—-]+(?P<cost>.+)$", re.IGNORECASE)

#: "Lands you control are every basic land type in addition to their other
#: types." (Dryad of the Ilysian Grove-shaped) — RULE 613.4a `add_
#: subtypes`, the fixed five-basic-type list.
_LANDS_EVERY_BASIC_TYPE_RE = re.compile(
    r"^lands you control are every basic land type in addition to their other types$",
    re.IGNORECASE,
)
_BASIC_LAND_TYPE_LIST: tuple[str, ...] = ("plains", "island", "swamp", "mountain", "forest")

#: "You may cast [noncreature/creature] spells as though they had flash."
#: (High Fae Trickster/Valley Floodcaller-shaped) — `continuous.has_
#: standing_flash_permission`'s own two scope flags.
_FLASH_PERMISSION_RE = re.compile(
    r"^you may cast (?P<scope>noncreature |creature )?spells as though they had flash$",
    re.IGNORECASE,
)

#: "Spells you control can't be countered." / "Creature spells you control
#: can't be countered." (Hexing Squelcher/Rionya, Sky Coyote-shaped) —
#: `GrantCantBeCounteredEffect`'s own two printed scopes.
_GRANT_CANT_BE_COUNTERED_RE = re.compile(
    r"^(?P<creature>creature )?spells you control can'?t be countered$", re.IGNORECASE
)

#: "Your opponents can't search libraries." (Stranglehold-shaped).
_GRANT_SEARCH_PROHIBITED_RE = re.compile(
    r"^your opponents can'?t search libraries$", re.IGNORECASE
)

#: "If an opponent would begin an extra turn, that player skips that turn
#: instead." (Stranglehold's own second clause). "a player" (unscoped —
#: still opponents-only per `GrantSkipExtraTurnsEffect`'s own single
#: printed shape) is the wider sibling seen on other real cards.
_GRANT_SKIP_EXTRA_TURNS_RE = re.compile(
    r"^if an? (?:opponent|player) would begin an extra turn, that player "
    r"skips that turn instead$", re.IGNORECASE
)

#: The trailing sibling above's docstring deliberately left "…during your
#: turn." unclaimed generally (an "activate only during your turn" cost
#: restriction risk); this row is narrow enough to dodge that collision —
#: matched only when the *whole* clause is a bare keyword grant ending in
#: "during your turn" ("~ has first strike during your turn.", Razorkin
#: Needlehead-shaped), never an activation-cost sentence (those don't start
#: with "~ has"/"~ have").
_DURING_YOUR_TURN_TRAILING_KEYWORD_RE = re.compile(
    r"^~ (?:has|have) (?P<inner>.+) during your turn$", re.IGNORECASE
)


def _flag_keywords(text: str) -> Optional[list[str]]:
    """A "have <keywords>" list → grantable keyword slugs, or ``None`` if any
    isn't recognised (fail-closed — most other granted parametric keywords,
    e.g. "ward {2}", need behaviour the grant can't express yet).

    Almost every entry must be a parameterless FLAG keyword ("flying",
    "trample"). Two parametric exceptions: a landwalk variant ("forestwalk",
    "islandwalk", …) — RULE 702.14's land type lives in the slug itself, and
    `combat._landwalk_slugs` already matches any ``granted_keywords`` entry
    ending in "walk" directly, so the grant mechanism needs no separate
    quality param the way "protection from <color>" would — and a *bare*
    "hexproof" (RULE 702.11b's QUALITY shape, PAR-5, exists for the scoped
    "hexproof from <colour>" variant; unscoped "hexproof" is still its own
    complete keyword and grants exactly like a FLAG one). A bare "landwalk"
    with no type, or a real "hexproof from <colour>" scope (whose slug never
    resolves via `keyword_slug` to bare "hexproof"), still fails closed.
    """
    slugs: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        slug = keyword_slug(part)
        kdef = KEYWORDS.get(slug)
        if kdef is not None and (kdef.shape is KeywordShape.FLAG or kdef.slug == "hexproof"):
            slugs.append(kdef.slug)
            continue
        resolved = resolve_keyword(slug)
        if resolved is not None and resolved.slug == "landwalk" and slug != "landwalk":
            slugs.append(slug)
            continue
        return None
    return slugs or None


#: "~ gets +N/+N [and has <keywords>]" / "~ has <keywords>" — the **self**
#: -scoped anthem/grant, `_ATTACHED_ANTHEM_RE`'s sibling for a permanent
#: talking about itself. Real cards print this shape essentially only inside
#: a RULE 613.6 conditional ("As long as ~ is monstrous, it has trample.") —
#: unconditionally a creature just prints the keyword on its own line — but
#: the rows are written standalone so the conditional wrapper stays a pure
#: wrapper, with no grammar of its own.
#:
#: Both rows accept a trailing combat *permission* ("…and can attack as
#: though it didn't have defender") — the compound MEC-13 shape. It is its
#: own group rather than part of the keyword list because a permission is a
#: `combat_restriction` param entry, not a grantable keyword.
#: The trailing ``, and attacks each combat if able`` on ``_SELF_ANTHEM_RE``
#: (RULE 702.137 Delirium's own compound shape — "~ gets +2/+2, has flying,
#: and attacks each combat if able.", Dragon's Rage Channeler-shaped) is an
#: Oxford-comma third list item, not another " and "-joined clause, so both
#: the ``kw``/``attacks`` separators accept a bare comma as well as " and ".
#: `_ATTACKS_IF_ABLE_RE` already proves "attacks each combat if able" is
#: just the synthetic flag keyword ``"attacks_if_able"`` through the *same*
#: `grant_keyword` machinery as "has flying" — no new spec shape, just one
#: more keyword folded into the same list (or its own `grant_keyword` when
#: there's no ``kw`` tail to join).
_SELF_ANTHEM_RE = re.compile(
    r"~ gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    r"(?:(?:,\s*|\s+and\s+)has (?P<kw>[a-z][a-z, ]*?))?"
    r"(?:\s+and (?P<perm>can (?:attack|block)[a-z0-9 ']*))?"
    r"(?:(?:,\s*and\s+|,\s*|\s+and\s+)(?P<attacks_if_able>attacks each combat if able))?",
    re.IGNORECASE,
)
#: RULE 202.2f/700.6 "~ gets +X/+X, where X is your devotion to
#: `<colour(s)/wedge/hybrid>`." (Blended Twistling-shaped) — a standing,
#: self-scoped anthem whose amount is `continuous.count_selector`'s
#: `devotion_to_<key>` vocabulary rather than a literal digit, unlike
#: `_SELF_ANTHEM_RE` above.
_ANTHEM_DEVOTION_SELF_RE = re.compile(
    rf"~ gets? \+x/\+x, where x is {DEVOTION}", re.IGNORECASE,
)
#: PAR-30: "~ gets +P/+T for each `<subtype>` card in your graveyard"
#: (Katara, Seeking Revenge — "+1/+1 for each lesson card in your
#: graveyard"). A standing self-anthem whose per-unit +P/+T scales by
#: `continuous.count_selector`'s `<subtype>_cards_in_your_graveyard` prefix
#: (a live type-line scan). Bounded to a single subtype word so it stays
#: fail-closed for any other "for each" quantity.
_SELF_ANTHEM_FOR_EACH_GY_SUBTYPE_RE = re.compile(
    r"~ gets \+(?P<p>\d+)/\+(?P<t>\d+) for each (?P<sub>[a-z][a-z-]+) card in your graveyard",
    re.IGNORECASE,
)

#: PAR-43: "~ gets +P/+T for each `<X>`" — the general standing self-anthem
#: whose per-unit +P/+T scales by a `continuous.count_selector` value
#: (Akiri, Line-Slinger "+1/+0 for each artifact you control"; Adelbert
#: Steiner "+1/+1 for each Equipment you control"; Nemata "+1/+1 for each
#: Saproling…" &c.). ``<X>`` is matched against a fixed whitelist of phrases
#: that **already have a `count_selector`** (`_SELF_ANTHEM_FOR_EACH_
#: SELECTORS` + the `<basic land type> you control` special-case) — any
#: other quantity fails closed, exactly like `_PT_CDA_RE` / the GY-subtype
#: row above, since an anthem reading an unmodeled count would silently
#: apply +0. Tried after the GY-subtype row (more specific) and before
#: `_SELF_ANTHEM_RE` (whose fixed-digit `[+-]\d+/[+-]\d+` would claim the
#: "+1/+1" prefix and drop the "for each …" scaling).
_SELF_ANTHEM_FOR_EACH_RE = re.compile(
    r"~ gets \+(?P<p>\d+)/\+(?P<t>\d+) for each (?P<what>.+?)\.?",
    re.IGNORECASE,
)
_SELF_ANTHEM_FOR_EACH_SELECTORS: dict[str, str] = {
    "artifact you control": "artifacts_you_control",
    # "for each Equipment attached to it" — the source's *own* attachments
    # (Nemata-adjacent), not a board-wide "Equipment you control" count
    # (which has no `count_selector` yet — that phrase stays unclaimed).
    "equipment attached to it": "equipment_attached_to_self",
    "creature you control": "creatures_you_control",
    "legendary creature you control": "legendary_creatures_you_control",
    "land you control": "lands_you_control",
    "permanent you control": "permanents_you_control",
    "card in your hand": "cards_in_your_hand",
    "artifact and/or enchantment you control": "artifacts_and_or_enchantments_you_control",
}
_BASIC_LAND_TYPES: frozenset[str] = frozenset(
    {"plains", "island", "swamp", "mountain", "forest"}
)
_SELF_GRANT_RE = re.compile(
    # ``0-9`` in the keyword capture is ENG-31's parametric self-grant ("~
    # has firebending 2 as long as there's a lesson card in your graveyard"
    # — Fire Nation Cadets); `_split_keywords_with_parametric` splits a
    # "<name> N" entry off into ``parametric_keywords`` and fail-closes on
    # any other numbered keyword.
    r"~ has (?P<kw>[a-z][a-z, 0-9]*?)"
    r"(?: and (?P<perm>can (?:attack|block)[a-z0-9 ']*))?",
    re.IGNORECASE,
)

#: The inner clause of a conditional static says "it" where the standalone
#: form says "~" ("As long as ~ is monstrous, **it** has trample."). The
#: pronoun can only mean the source here — the condition has already named
#: it, and a static clause has no target to compete for the referent.
_INNER_SELF_PRONOUN_RE = re.compile(r"^it\b", re.I)

#: …except when the condition named the *attached permanent* instead ("As
#: long as enchanted permanent is a Vehicle, **it**'s a creature…", Aerial
#: Modification): the antecedent is then that permanent, not the Aura, so
#: the pronoun is rewritten to whichever attached-subject phrase the
#: condition used and the inner clause parses through the ordinary
#: `_ATTACHED_*` rows with ``affects="attached_permanent"``.
_CONDITION_ATTACHED_SUBJECT_RE = re.compile(rf"({_ATTACHED_SUBJECT_PATTERN})", re.I)


def _self_permission_spec(m: "re.Match[str]"):
    """A self-grant row's optional permission tail → its `EffectSpec`.

    Three-valued on purpose: ``None`` (no tail — the ordinary case),
    an `EffectSpec` (a recognised permission), or ``False`` (a tail that
    isn't in the vocabulary, which must fail the *whole* clause rather than
    granting the keywords and dropping the permission).
    """
    tail = m.groupdict().get("perm")
    if not tail:
        return None
    params = _permission_tail_params(tail)
    if params is None:
        return False
    return EffectSpec("combat_restriction", {**params, "affects": "self"})


def _conditional_static_specs(text: str) -> Optional[list[EffectSpec]]:
    """"As long as `<cond>`, `<static>`" / "`<static>` as long as `<cond>`" →
    the inner static's specs, each carrying an ``active_if`` gate.

    ``None`` when the clause isn't conditional at all, *or* when either half
    fails to parse — an unrecognised condition must not degrade into an
    ungated static (RULE 613.6: a static whose gate is dropped applies when
    it shouldn't, which is worse than an unmodeled card).
    """
    for pattern in (_AS_LONG_AS_LEADING_RE, _AS_LONG_AS_TRAILING_RE):
        m = pattern.fullmatch(text)
        if m is None:
            continue
        condition = static_condition(m.group("cond"))
        if condition is None:
            return None
        inner = m.group("inner").strip().rstrip(",").strip()
        if condition.get("of") == "attached":
            subject = _CONDITION_ATTACHED_SUBJECT_RE.search(m.group("cond"))
            if subject is None:
                return None  # fail closed — no phrase to rewrite the pronoun to
            inner = _INNER_SELF_PRONOUN_RE.sub(subject.group(1).lower(), inner)
        else:
            inner = _INNER_SELF_PRONOUN_RE.sub("~", inner)
        specs = static_effect_specs(inner)
        if not specs:
            return None
        for spec in specs:
            # A `combat_restriction` keeps its own ``condition`` param for the
            # combat-time vocabulary; the RULE 613.6 gate is always
            # ``active_if``, on every spec shape alike.
            spec.params["active_if"] = dict(condition)
        return specs

    m = _DURING_YOUR_TURN_LEADING_RE.fullmatch(text)
    if m is not None:
        inner = _INNER_SELF_PRONOUN_RE.sub("~", m.group("inner").strip())
        specs = static_effect_specs(inner)
        if not specs:
            return None
        for spec in specs:
            spec.params["active_if"] = {"kind": "your_turn"}
        return specs
    m = _DURING_YOUR_TURN_TRAILING_KEYWORD_RE.fullmatch(text)
    if m is not None:
        inner = f"~ has {m.group('inner').strip()}"
        specs = static_effect_specs(inner)
        if not specs:
            return None
        for spec in specs:
            spec.params["active_if"] = {"kind": "your_turn"}
        return specs
    return None


def static_effect_specs(clause: str) -> Optional[list[EffectSpec]]:
    """`EffectSpec`s for a static anthem/keyword-grant ``clause``, or ``None``.

    Full-matches the clause (like the one-shot handler table) so a partial or
    "until end of turn" phrasing isn't claimed. A compound "get +N/+N and have
    <keywords>" emits both an ``anthem`` and a ``grant_keyword`` spec. The specs
    carry ``affects`` + optional ``subtype``/``tokens`` for the layer engine.
    Also claims the attached-permanent shape ("equipped/enchanted creature
    gets +N/+N [and has <keywords>]", "equipped/enchanted creature has
    <keywords>") with ``affects="attached_permanent"`` — see
    `_ATTACHED_SUBJECTS` above.
    """
    text = clause.strip().rstrip(".").strip()

    # RULE 613.6: "as long as <condition>, <static>" (either printed order) —
    # parse the gate, then re-enter with the bare static and hand every spec
    # it returns the same ``active_if``. Done *first*, so no unconditional
    # row can claim a conditional clause by matching a prefix of it, and
    # recursion-guarded: the inner clause is strictly shorter, and a second
    # "as long as" inside it fails the whole line closed (see
    # `_AS_LONG_AS_TRAILING_RE`).
    conditional = _conditional_static_specs(text)
    if conditional is not None:
        return conditional

    # RULE 604.3 characteristic-defining P/T — "~'s power and toughness are
    # each equal to the number of <X>."  (see `_PT_CDA_RE`).
    m = _PT_CDA_RE.fullmatch(text)
    if m is not None:
        selector = _PT_CDA_SELECTORS.get(m.group("what").strip().rstrip("."))
        if selector is None:
            return None  # fail-closed — an unwhitelisted quantity phrase
        return [EffectSpec("pt_cda", {
            "affects": "self",
            "power_count": selector,
            "toughness_count": selector,
        })]

    m = _PT_CDA_SINGLE_RE.fullmatch(text)
    if m is not None:
        selector = _PT_CDA_SELECTORS.get(m.group("what").strip().rstrip("."))
        if selector is None:
            return None  # fail-closed
        key = "power_count" if m.group("char").lower() == "power" else "toughness_count"
        return [EffectSpec("pt_cda", {"affects": "self", key: selector})]

    # "This spell can't be countered." (RULE 118-area) — printed on a
    # permanent as a standing line even though it only matters while the
    # object is still a spell on the stack; `catalogue.handlers` claims the
    # identical phrase for the instant/sorcery spell_effect path, see
    # `CANT_BE_COUNTERED_RE`'s docstring for why both need it.
    if CANT_BE_COUNTERED_RE.fullmatch(text):
        return [EffectSpec("cant_be_countered", {})]

    # "Spells you control can't be countered." / "Creature spells you
    # control can't be countered." (Hexing Squelcher/Rionya-shaped) — a
    # standing grant, not the spell's own bare flag `CANT_BE_COUNTERED_RE`
    # claims above.
    m = _GRANT_CANT_BE_COUNTERED_RE.fullmatch(text)
    if m is not None:
        scope = "creature_spells_you_control" if m.group("creature") else "you"
        return [EffectSpec("grant_cant_be_countered", {"scope": scope})]

    # RULE 701.19a: "Your opponents can't search libraries." (Stranglehold)
    if _GRANT_SEARCH_PROHIBITED_RE.fullmatch(text):
        return [EffectSpec("grant_search_prohibited", {})]

    # RULE 500.7/700.4: "If an opponent would begin an extra turn, that
    # player skips that turn instead." (Stranglehold's own second clause)
    if _GRANT_SKIP_EXTRA_TURNS_RE.fullmatch(text):
        return [EffectSpec("grant_skip_extra_turns", {})]

    if _LANDS_EVERY_BASIC_TYPE_RE.fullmatch(text):
        return [EffectSpec("type_change", {
            "affects": "lands_you_control", "add_subtypes": list(_BASIC_LAND_TYPE_LIST),
        })]

    m = _FLASH_PERMISSION_RE.fullmatch(text)
    if m is not None:
        scope = (m.group("scope") or "").strip()
        params: dict[str, Any] = {}
        if scope == "noncreature":
            params["noncreature_only"] = True
        elif scope == "creature":
            params["creature_only"] = True
        return [EffectSpec("flash_permission", params)]

    m = _ACTIVATION_PROHIBITION_OPPONENTS_RE.fullmatch(text)
    if m is not None:
        card_type = _singularize(m.group("word"))
        if card_type not in _CARD_TYPE_WORDS:
            return None  # fail-closed — an unrecognised type-scope
        return [
            EffectSpec(
                "activation_prohibition",
                {"affects": "opponents_permanents", "card_type": card_type},
            )
        ]

    if _CANT_CAST_OPPONENTS_YOUR_TURN_RE.fullmatch(text):
        return [EffectSpec("cast_prohibition", {"scope": "opponents", "active_if": {"kind": "your_turn"}})]

    if _CANT_CAST_OPPONENTS_HAND_ONLY_RE.fullmatch(text):
        return [EffectSpec("cast_prohibition", {"scope": "opponents", "hand_only": True})]

    m = _CANT_CAST_OR_ACTIVATE_OPPONENTS_RE.fullmatch(text)
    if m is not None:
        card_types = _type_word_list(m.group("types"))
        if card_types is None:
            return None  # fail-closed — an unrecognised type in the list
        return [
            EffectSpec("cast_prohibition", {"scope": "opponents"}),
            EffectSpec(
                "activation_prohibition",
                {"affects": "opponents_permanents", "card_type": card_types},
            ),
        ]

    m = _ACTIVATION_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        card_type = _singularize(m.group("word"))
        if card_type not in _CARD_TYPE_WORDS:
            return None  # fail-closed — an unrecognised type-scope
        return [EffectSpec("activation_prohibition", {"card_type": card_type})]

    m = _SPELL_COST_TAX_RE.fullmatch(text)
    if m is not None:
        word = (m.group("word") or "").lower()
        # A bare "spells cost {N} more/less to cast" (no type word — Sphere of
        # Resistance) taxes *every* spell: a falsy ``spell_type`` means "no
        # type filter" in `continuous.cost_reduction_for`. A typed variant
        # must name a recognised card type (fail-closed).
        if word and word not in _SPELL_TYPE_WORDS:
            return None
        params: dict = {
            "affects": "all_spells",
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
        }
        if word:
            params["spell_type"] = word
        return [EffectSpec("cost_reduction", params)]

    m = _SPELL_COST_TAX_COLOR_RE.fullmatch(text)
    if m is not None:
        params = {
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
            "spell_color": _COLOR_WORDS[m.group("color").lower()],
        }
        return [EffectSpec("cost_reduction", params)]

    m = _SPELL_COST_TAX_OPPONENTS_TARGET_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("cost_reduction", {
            "affects": "opponents_spells",
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
            "targets_source": True,
        })]

    m = _SPELL_COST_TAX_OPPONENTS_RE.fullmatch(text)
    if m is not None:
        params = {
            "affects": "opponents_spells",
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
        }
        return [EffectSpec("cost_reduction", params)]

    m = _SPELL_COST_TAX_YOU_CAST_RE.fullmatch(text)
    if m is not None:
        words = [w.lower() for w in (m.group("word1"), m.group("word2")) if w]
        if any(w not in _SPELL_TYPE_WORDS for w in words):
            return None  # fail-closed — colour/subtype-scoped, not a main type
        params = {
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
        }
        if len(words) == 1:
            params["spell_type"] = words[0]
        elif len(words) == 2:
            params["spell_type"] = words
        return [EffectSpec("cost_reduction", params)]

    m = _ACTIVATION_COST_REDUCTION_TYPE_RE.fullmatch(text)
    if m is not None:
        card_type = _singularize(m.group("word").lower())
        if card_type not in _CARD_TYPE_WORDS:
            return None  # fail-closed — an unrecognised type-scope
        params = {
            "scope": "activation",
            "card_type": card_type,
            "generic": int(m.group("n")),
        }
        if m.group("floor"):
            params["min_total"] = int(m.group("floor"))
        return [EffectSpec("cost_reduction", params)]

    m = _SELF_COST_REDUCTION_ATTACKING_RE.fullmatch(text)
    if m is not None:
        selector = "attacking_creatures_you_control" if m.group("yours") else "attacking_creatures"
        return [
            EffectSpec(
                "cost_reduction",
                {"affects": "self", "generic": int(m.group("n")), "per": selector},
            )
        ]

    m = _SELF_COST_REDUCTION_IF_RE.fullmatch(text)
    if m is not None:
        cond_text = m.group("cond")
        target_crit = _targets_reduction_criteria(cond_text)
        if target_crit is not None:
            return [
                EffectSpec(
                    "cost_reduction",
                    {"affects": "self", "generic": int(m.group("n")),
                     "reduce_if_targets": target_crit},
                )
            ]
        condition = static_condition(cond_text)
        if condition is None:
            return None  # fail-closed — an unrecognised condition clause
        return [
            EffectSpec(
                "cost_reduction",
                {"affects": "self", "generic": int(m.group("n")), "active_if": condition},
            )
        ]

    m = _CAST_LIMIT_NONCREATURE_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("cast_limit", {"max_per_turn": int(m.group("n")), "noncreature": True})]

    m = _CAST_LIMIT_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("cast_limit", {"max_per_turn": int(m.group("n"))})]

    m = _EXTRA_LAND_DROP_RE.fullmatch(text)
    if m is not None:
        affects = "each_player" if m.group("subject").lower() == "each player" else "you"
        return [EffectSpec("extra_land_drop", {"affects": affects, "count": count_of(m.group("n"))})]

    m = _NO_MAX_HAND_SIZE_RE.fullmatch(text)
    if m is not None:
        affects = "each_player" if m.group("subject").lower() == "players have" else "you"
        return [EffectSpec("no_max_hand_size", {"affects": affects})]

    if _SKIP_UNTAP_STEPS_RE.fullmatch(text):
        return [EffectSpec("skip_untap_step", {})]

    m = _PLAYERS_CANT_GAIN_LIFE_RE.fullmatch(text)
    if m is not None:
        params = {"scope": "opponents"} if (m.group("scope") or "").lower() == "your opponents" else {}
        return [EffectSpec("prevent_all_life_gain", params)]

    m = _SKIP_YOUR_STEP_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("skip_step", {"step": m.group("step").lower()})]

    m = _GRAVEYARD_LIBRARY_CAST_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        params: dict = {} if m.group("libraries") else {"zones": ["graveyard"]}
        return [EffectSpec("graveyard_library_cast_prohibition", params)]

    m = _GRAVEYARD_LIBRARY_ENTRY_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        word = m.group("type").lower()
        card_type = "nonland_permanent" if word == "nonland permanent" else word
        params = {"card_type": card_type}
        if not m.group("libraries"):
            params["zones"] = ["graveyard"]
        return [EffectSpec("graveyard_library_entry_prohibition", params)]

    if _RADIATION_LIFE_GAIN_RE.fullmatch(text):
        return [EffectSpec("radiation_life_gain", {})]

    m = _TOP_LIBRARY_PERMISSION_RE.fullmatch(text)
    if m is not None:
        params: dict = {"look": True, **_TOP_LIBRARY_VERB_PARAMS[m.group("verb").lower()]}
        if m.group("mv"):
            params["min_mana_value"] = int(m.group("mv"))
        tail = m.group("tail")
        if tail is not None:
            params[_TOP_LIBRARY_TAILS[tail.lower()]] = True
        return [EffectSpec("top_library_permission", params)]

    if _LOOK_AT_TOP_ANY_TIME_RE.fullmatch(text):
        return [EffectSpec("top_library_permission", {"look": True})]

    if _NOT_A_CREATURE_RE.fullmatch(text):
        return [EffectSpec("type_change", {"remove_types": ["creature"]})]

    if _NO_UNTAP_OPTIONAL_RE.fullmatch(text):
        return [EffectSpec("no_untap_optional", {})]

    if _NO_UNTAP_RE.fullmatch(text):
        return [EffectSpec("no_untap", {"affects": "self"})]

    m = _NO_UNTAP_ATTACHED_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("no_untap", {"affects": "attached_permanent"})]

    m = _NO_UNTAP_GROUP_POWER_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("no_untap", {"affects": "all_creatures", "min_power": int(m.group("n"))})]

    if _NO_UNTAP_NONBASIC_LANDS_RE.fullmatch(text):
        return [EffectSpec("no_untap", {"affects": "all_lands", "nonbasic": True})]

    m = _UNTAP_CAP_RE.fullmatch(text)
    if m is not None:
        card_type = _singularize(m.group("word").lower())
        if card_type not in _CARD_TYPE_WORDS:
            return None  # fail-closed — an unrecognised type-scope
        params: dict = {"count": int(m.group("n")), "card_type": card_type}
        if m.group("nonbasic"):
            params["nonbasic"] = True
        return [EffectSpec("untap_cap", params)]

    m = _TRIGGER_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        subject_type = _singularize(m.group("word"))
        if subject_type not in _CARD_TYPE_WORDS:
            return None
        specs = [
            EffectSpec(
                "trigger_prohibition",
                {"event": "ENTERS_BATTLEFIELD", "subject_type": subject_type},
            )
        ]
        if m.group("dying"):
            specs.append(
                EffectSpec("trigger_prohibition", {"event": "DIES", "subject_type": subject_type})
            )
        return specs

    m = _OPPONENTS_ENTER_TAPPED_RE.fullmatch(text)
    if m is not None:
        specs = []
        for part in m.group("parts").split(" and "):
            nonbasic = part.startswith("nonbasic ")
            word = part[len("nonbasic "):] if nonbasic else part
            card_type = _singularize(word)
            if card_type not in _CARD_TYPE_WORDS:
                return None
            params: dict = {"affects": "opponents_permanents", "card_type": card_type}
            if nonbasic:
                params["nonbasic"] = True
            specs.append(EffectSpec("enters_tapped_static", params))
        return specs

    m = _ALL_ENTER_TAPPED_RE.fullmatch(text)
    if m is not None:
        card_types = [_singularize(w) for w in m.group("words").split(" and ")]
        if any(t not in _CARD_TYPE_WORDS for t in card_types):
            return None
        specs = []
        for card_type in card_types:
            params = {"affects": "all_permanents", "card_type": card_type}
            if m.group("nonbasic"):
                params["nonbasic"] = True
            specs.append(EffectSpec("enters_tapped_static", params))
        return specs

    m = _TYPE_OVERWRITE_RE.fullmatch(text)
    if m is not None:
        basic_type = _BASIC_LAND_WORDS.get(m.group("word").lower())
        if basic_type is None:
            return None  # fail-closed — an unrecognised "are <X>" overwrite
        return [
            EffectSpec("type_change", {
                "affects": "all_lands", "nonbasic": True, "set_subtypes": [basic_type],
            }),
        ]

    m = _LAND_IS_BASIC_TYPE_RE.fullmatch(text)
    if m is not None:
        basic_type = _BASIC_LAND_WORDS.get(m.group("word").lower())
        if basic_type is None:
            return None  # fail-closed — an unrecognised "is a <X>" grant
        return [EffectSpec("type_change", {"affects": "all_lands", "add_subtypes": [basic_type]})]

    # RULE 702.16 standing protection grants — before every anthem/
    # keyword-grant family below, whose `_flag_keywords` would reject
    # "protection from <quality>" (not a flag keyword) and fail the clause
    # closed. Compound "+N/+N and protection" first, since the bare forms
    # are prefixes of it.
    m = _ATTACHED_ANTHEM_PROTECTION_RE.fullmatch(text)
    if m is not None:
        params = _protection_params(m.group("quality"))
        if params is None:
            return None
        if m.group("exempt"):
            params["exempt_own_attachment"] = True
        return [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"}),
            EffectSpec("grant_protection_static",
                       {"affects": "attached_permanent", **params}),
        ]

    m = _GROUP_ANTHEM_PROTECTION_RE.fullmatch(text)
    if m is not None:
        scope = _scope(m.group("body"))
        if scope is None:
            return None
        params = _protection_params(m.group("quality"))
        if params is None:
            return None
        scoped = _scope_params(scope, m)
        return [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   **scoped}),
            EffectSpec("grant_protection_static", {**scoped, **params}),
        ]

    m = _SELF_PROTECTION_RE.fullmatch(text)
    if m is not None:
        params = _protection_params(m.group("quality"))
        if params is None:
            return None
        return [EffectSpec("grant_protection_static", {"affects": "self", **params})]

    m = _ATTACHED_PROTECTION_RE.fullmatch(text)
    if m is not None:
        params = _protection_params(m.group("quality"))
        if params is None:
            return None
        if m.group("exempt"):
            params["exempt_own_attachment"] = True
        return [EffectSpec("grant_protection_static", {"affects": "attached_permanent", **params})]

    m = _GROUP_PROTECTION_RE.fullmatch(text)
    if m is not None:
        scope = _scope(m.group("body"))
        if scope is None:
            return None
        params = _protection_params(m.group("quality"))
        if params is None:
            return None
        return [EffectSpec("grant_protection_static", {**_scope_params(scope, m), **params})]

    # Attached-permanent shape first ("equipped creature gets +2/+2 [and has
    # <keywords>]") — a closed subject list, so this never competes with the
    # "you control" scopes below (singular "gets"/"has" vs. their plural
    # "get"/"have"). `affects="attached_permanent"` is honoured by both
    # `anthem` (layer 7c) and `grant_keyword` (layer 6) in `game/continuous.py`.
    m = _ATTACHED_ANTHEM_RE.fullmatch(text)
    if m is not None:
        specs = [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"})
        ]
        if m.group("kw"):  # "… and has <keywords>" tail
            keywords = _flag_keywords(m.group("kw"))
            if keywords is None:
                return None  # e.g. a granted landwalk — fail-closed, whole clause
            specs.append(EffectSpec("grant_keyword", {"keywords": keywords,
                                                        "affects": "attached_permanent"}))
        if m.group("goaded"):  # "… and is goaded" tail (RULE 701.15b)
            specs.append(EffectSpec("goaded", {"affects": "attached_permanent"}))
        return specs

    # Attached-permanent keyword-only grant ("equipped creature has trample",
    # "enchanted creature has indestructible and is goaded").
    m = _ATTACHED_GRANT_RE.fullmatch(text)
    if m is not None:
        keywords = _flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        specs = [EffectSpec("grant_keyword", {"keywords": keywords,
                                              "affects": "attached_permanent"})]
        if m.group("goaded"):
            specs.append(EffectSpec("goaded", {"affects": "attached_permanent"}))
        return specs

    # The bare "enchanted creature is goaded." (RULE 701.15b) — no other
    # grant on the Aura at all.
    m = _ATTACHED_GOADED_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("goaded", {"affects": "attached_permanent"})]

    # "~ gets +X/+X, where X is your devotion to <colour(s)/wedge/hybrid>."
    # (RULE 202.2f/700.6, Blended Twistling-shaped) — a standing, self-
    # scoped anthem whose amount is `continuous.count_selector`'s
    # `devotion_to_<key>` vocabulary, tried before `_SELF_ANTHEM_RE`
    # (fixed-digit only) since "x" would never match that row's ``\d+``.
    # PAR-30: "~ gets +P/+T for each `<subtype>` card in your graveyard"
    # (Katara, Seeking Revenge). Tried before `_SELF_ANTHEM_RE` since that
    # row's `[+-]\d+/[+-]\d+` would claim the "+1/+1" prefix and drop the
    # "for each …" scaling.
    m = _SELF_ANTHEM_FOR_EACH_GY_SUBTYPE_RE.fullmatch(text)
    if m is not None:
        selector = f"{m.group('sub').lower()}_cards_in_your_graveyard"
        return [EffectSpec("anthem", {
            "affects": "self",
            "power": int(m.group("p")), "toughness": int(m.group("t")),
            "power_count": selector, "toughness_count": selector,
        })]

    # PAR-43: "~ gets +P/+T for each <X>" — general standing self-anthem
    # whose per-unit +P/+T scales by a `continuous.count_selector` value.
    m = _SELF_ANTHEM_FOR_EACH_RE.fullmatch(text)
    if m is not None:
        what = m.group("what").strip().lower()
        selector = _SELF_ANTHEM_FOR_EACH_SELECTORS.get(what)
        if selector is None and what.endswith(" you control"):
            land_type = what[: -len(" you control")]
            if land_type in _BASIC_LAND_TYPES:
                selector = f"lands_you_control_of_type_{land_type}"
        if selector is not None:
            return [EffectSpec("anthem", {
                "affects": "self",
                "power": int(m.group("p")), "toughness": int(m.group("t")),
                "power_count": selector, "toughness_count": selector,
            })]
        # A "for each …" quantity with no wired selector — fail closed
        # (an anthem reading an unmodeled count would silently apply +0).

    m = _ANTHEM_DEVOTION_SELF_RE.fullmatch(text)
    if m is not None:
        selector = devotion_selector(m)
        if selector:
            # ``power``/``toughness`` are the *per-unit* amount `_pt_mod_
            # count` multiplies by the count selector's value (RULE
            # 202.2f's "+X/+X" is 1 per point of devotion, not a flat 0).
            return [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 1,
                "power_count": selector, "toughness_count": selector,
            })]

    # Self-scoped anthem/grant ("~ gets +2/+2 and has flying", "~ has
    # trample [and can attack as though it didn't have defender]") — the
    # inner half of nearly every RULE 613.6 conditional.
    m = _SELF_ANTHEM_RE.fullmatch(text)
    if m is not None:
        specs = [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "self"})
        ]
        keywords: Optional[list[str]] = None
        if m.group("kw"):
            keywords = _flag_keywords(m.group("kw"))
            if keywords is None:
                return None
        if m.group("attacks_if_able"):
            keywords = (keywords or []) + ["attacks_if_able"]
        if keywords:
            specs.append(EffectSpec("grant_keyword", {"keywords": keywords, "affects": "self"}))
        tail = _self_permission_spec(m)
        if tail is False:
            return None
        if tail is not None:
            specs.append(tail)
        return specs

    m = _SELF_GRANT_RE.fullmatch(text)
    if m is not None:
        kw_text = m.group("kw")
        keywords = _flag_keywords(kw_text)
        parametric: list[dict[str, object]] = []
        if keywords is None:
            # ENG-31: "~ has firebending N …" (Fire Nation Cadets) — only
            # reached when `_flag_keywords` fails, so the ordinary
            # landwalk/flag path is untouched.
            split = _split_keywords_with_parametric(kw_text)
            if split is None:
                return None
            keywords, parametric = split
        if not keywords and not parametric:
            return None
        params: dict[str, Any] = {"affects": "self"}
        if keywords:
            params["keywords"] = keywords
        if parametric:
            params["parametric_keywords"] = parametric
        specs = [EffectSpec("grant_keyword", params)]
        tail = _self_permission_spec(m)
        if tail is False:
            return None
        if tail is not None:
            specs.append(tail)
        return specs

    # RULE 508.1a's standalone attack permission ("~ can attack as though it
    # didn't have defender.") and the counted multi-block one.
    m = _ATTACK_AS_THOUGH_NO_DEFENDER_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("combat_restriction", {
            "kind": "attacks_as_though_no_defender",
            "affects": _combat_restriction_affects(m.group("subject")),
        })]

    m = _BLOCK_ADDITIONAL_N_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("combat_restriction", {
            "kind": "extra_blocks", "count": int(m.group("n")),
            "affects": _combat_restriction_affects(m.group("subject")),
        })]

    # Combat-restriction family ("~ can't attack.", "enchanted creature can't
    # be blocked.", "~ attacks each combat if able.", …) — see
    # `_combat_restriction_specs` above. Ordered most-specific-first so a
    # combined clause matches its own row rather than a shorter prefix; since
    # every branch uses `fullmatch`, a shorter regex simply fails on any
    # unconsumed trailing text (fail-closed), so the ordering is for clarity
    # rather than correctness.
    m = _CANT_ATTACK_OR_BLOCK_LOCK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(
            m.group("subject"), ["cant_attack", "cant_block"], lock=True,
            mana_exception=bool(m.group("mana_exception")),
        )

    m = _CANT_ATTACK_OR_BLOCK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_attack", "cant_block"])

    m = _CANT_BLOCK_AND_CANT_BE_BLOCKED_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_block", "cant_be_blocked"])

    m = _CANT_ATTACK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_attack"])

    m = _CANT_BLOCK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_block"])

    m = _CANT_BE_BLOCKED_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_be_blocked"])

    m = _ATTACKS_IF_ABLE_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["attacks_if_able"])

    # RULE 509.1c/d combat requirements — "~ must be blocked if able."/"All
    # creatures able to block ~ do so." (Lure-shaped).
    m = _MUST_BE_BLOCKED_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["must_be_blocked"])

    m = _ALL_MUST_BLOCK_RE.fullmatch(text)
    if m is not None:
        subject = m.group("subject")
        affects = "self" if subject in ("~", "it") else "attached_permanent"
        return [EffectSpec("grant_keyword", {"keywords": ["all_must_block"], "affects": affects})]

    # RULE 509.1b multi-block permissions — "~ can block an additional
    # creature each combat."/"~ can block any number of creatures."
    m = _BLOCK_ADDITIONAL_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("combat_restriction", {
            "kind": "extra_blocks", "count": 1,
            "affects": _combat_restriction_affects(m.group("subject")),
        })]

    m = _BLOCK_ANY_NUMBER_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("combat_restriction", {
            "kind": "unlimited_blocks",
            "affects": _combat_restriction_affects(m.group("subject")),
        })]

    # …and their *qualified* siblings ("can't be blocked by creatures with
    # power 2 or less", "can't attack unless defending player controls an
    # Island", "can't attack alone") — tried after the plain flags above,
    # which are `fullmatch`ed and so can never swallow a qualifier.
    qualified = _qualified_combat_restriction_specs(text)
    if qualified is not None:
        return qualified

    if _CONTROL_GRANT_RE.fullmatch(text):
        return [EffectSpec("control_change", {})]

    if _IS_CHOSEN_TYPE_RE.fullmatch(text):
        return [EffectSpec("type_change", {"affects": "self", "add_subtypes_from_source": True})]

    if _GRAVEYARD_CHOSEN_TYPE_RE.fullmatch(text):
        return [EffectSpec("type_change", {
            "affects": "off_battlefield_only",  # no battlefield half at all
            "add_subtypes_from_source": True,
            "off_battlefield": "your_graveyard",
        })]

    m = _GROUP_CHOSEN_TYPE_RE.fullmatch(text)
    if m is not None:
        params = _chosen_type_group_affects(m.group("body"))
        if params is None:
            return None
        params["add_subtypes_from_source"] = True
        if m.group("off"):
            params["off_battlefield"] = "cards_you_own"
        return [EffectSpec("type_change", params)]

    m = _GROUP_GOADED_RE.fullmatch(text)
    if m is not None:
        params: dict = {"affects": "creatures_opponents_control"}
        if m.group("cmp"):
            params["power_lt_selector" if m.group("cmp") == "less" else "power_gt_selector"] = (
                "source_power"
            )
        return [EffectSpec("goaded", params)]

    m = _SOULBOND_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        grants = _quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return None
        for g in grants:
            g.params["affects"] = "soulbond_pair"
        return grants

    m = _SOULBOND_ANTHEM_RE.fullmatch(text)
    if m is not None:
        specs = [EffectSpec("anthem", {"power": int(m.group("p")),
                                       "toughness": int(m.group("t")),
                                       "affects": "soulbond_pair"})]
        if m.group("kw"):
            keywords = _flag_keywords(m.group("kw"))
            if keywords is None:
                return None
            specs.append(EffectSpec("grant_keyword",
                                    {"keywords": keywords, "affects": "soulbond_pair"}))
        return specs

    m = _SOULBOND_GRANT_RE.fullmatch(text)
    if m is not None:
        keywords = _flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        return [EffectSpec("grant_keyword", {"keywords": keywords, "affects": "soulbond_pair"})]

    m = _ATTACHED_QUOTED_ANTHEM_GRANT_RE.fullmatch(text)
    if m is not None:
        grants = _quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return None
        return [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"}),
            *grants,
        ]

    m = _ATTACHED_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        grants = _quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return None
        return grants

    m = _ANTHEM_RE.fullmatch(text)
    if m is not None:
        scope = _scope(m.group("body"))
        if scope is not None:
            params = _scope_params(scope, m)
        elif _is_vehicle_scope(m.group("body")):
            # "Vehicles you control get +1/+1 and have vigilance and
            # reach." (Balthier and Fran) — the `_ARTIFACT_SUBTYPES`
            # fallback: a Vehicle isn't a creature until crewed, so this
            # must not fall through to `_scope`'s ordinary (creature-only)
            # reading, which would wrongly scope the anthem to
            # ``creatures_you_control`` and so exclude every uncrewed
            # Vehicle it's printed to buff.
            params = _vehicle_scope_params(m)
        else:
            return None
        specs = [
            EffectSpec("anthem",
                       {"power": int(m.group("p")), "toughness": int(m.group("t")), **params})
        ]
        if m.group("kw"):  # "… and have <keywords>" tail
            keywords = _flag_keywords(m.group("kw"))
            if keywords is None:
                return None  # e.g. a granted landwalk — fail-closed, whole clause
            specs.append(EffectSpec("grant_keyword", {"keywords": keywords, **params}))
        return specs

    m = _COMMANDER_CREATURES_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        grants = _quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return None
        for g in grants:
            g.params["affects"] = "commander_creatures_you_own"
        return grants

    m = _QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        scope = _scope(m.group("body"))
        if scope is not None:
            scope_params = _scope_params(scope, m)
        elif _is_vehicle_scope(m.group("body")):
            scope_params = _vehicle_scope_params(m)
        else:
            # PAR-3: a bare non-creature scope ("Other enchantments have
            # '…'", Aura Flux) — `_scope` deliberately stays creature-only
            # (kept for `_ANTHEM_RE`), so a grant family falls back to the
            # permanent-type sibling instead of failing closed.
            word = _permanent_type_scope(m.group("body"))
            if word is None:
                return None
            scope_params = _permanent_scope_params(word, m)
        grants = _quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return None
        for g in grants:
            g.params.update(scope_params)
        return grants

    m = _GROUP_COUNTER_GRANT_RE.fullmatch(text)
    if m is not None:
        keywords = _flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        return [EffectSpec("grant_keyword", {
            "keywords": keywords,
            "affects": "creatures_you_control",
            "has_counter_kind": "+1/+1",
        })]

    m = _GRAVEYARD_RETRACE_GRANT_RE.fullmatch(text)
    if m is not None:
        return _graveyard_retrace_grant_specs(m.group("filter"))

    m = _MULTI_PERMANENT_TYPE_GRANT_RE.fullmatch(text)
    if m is not None:
        card_types = _multi_permanent_type_list(m.group("body"))
        if card_types is None:
            return None
        keywords = _flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        return [EffectSpec("grant_keyword", {
            "keywords": keywords,
            "affects": "permanents_you_control",
            "card_type": card_types,
        })]

    m = _GRANT_RE.fullmatch(text)
    if m is not None:
        scope = _scope(m.group("body"))
        if scope is not None:
            scope_params = _scope_params(scope, m)
        elif _is_vehicle_scope(m.group("body")):
            scope_params = _vehicle_scope_params(m)
        else:
            # PAR-3, same fallback as `_QUOTED_GRANT_RE` above — "Artifacts
            # you control have hexproof." (Leonin Abunas-shaped).
            word = _permanent_type_scope(m.group("body"))
            if word is None:
                return None
            scope_params = _permanent_scope_params(word, m)
        keywords = _flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        return [EffectSpec("grant_keyword", {"keywords": keywords, **scope_params})]

    m = _HAND_CYCLING_GRANT_RE.fullmatch(text)
    if m is not None:
        params: dict[str, Any] = {"cost": m.group("cost")}
        if m.group("filter"):
            params["card_type"] = m.group("filter").lower()
        return [EffectSpec("grant_cycling_to_hand", params)]

    return None
