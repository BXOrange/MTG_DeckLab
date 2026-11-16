"""Static-ability helpers: anthem patterns (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Optional
from ..subgrammars import COLOR_LETTERS
from ..count_phrase import parse_amount_phrase


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
GRANTABLE_TRIGGER_EVENTS = frozenset(
    {"ENTERS_BATTLEFIELD", "LEAVES_BATTLEFIELD", "STATE_CHECK", "DIES", "ATTACKS", "ATTACKS_ALONE", "BLOCKS", "UNTAPPED", "DAMAGE", "BECOMES_TARGET",
     "STEP_BEGIN", "LIFE_GAINED", "DRAW", "SPELL_CAST", "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"}
)
#: PAR-32: trigger-dict gate keys that survive re-granting unchanged — a
#: filter on the firing event, not on any host-relative state. Passed
#: straight through to `grant_triggered_ability`'s params; each has its own
#: `effect_binder` predicate that `continuous._apply_layer_6_ability`
#: composes onto the re-granted trigger's condition.
REGRANT_PASSTHROUGH_TRIGGER_KEYS = frozenset(
    {"attacked_player_has_lowest_life", "spell_from_exile", "controls_none_matching",
     "spell_shares_creature_type_with_source", "spell_exclude_card_types", "contributors",
     "spell_filter", "spell_cast_from", "recipient_relation", "recipient_filter"}
)

#: MEC-55: inner-static `affects` scopes that can't be re-granted to a
#: group — "self"/"attached_permanent" only mean something relative to a
#: single host permanent, which a regranted static has no notion of.
_REGRANT_UNSUPPORTED_AFFECTS = frozenset({"self", "attached_permanent"})

#: PAR-32: `{"subject": "group"}` trigger-condition keys that stay
#: meaningful when the ability is re-granted to another permanent — every
#: one is a filter on the *acting* object or a "you control"/"other"
#: re-scoping, resolved by `effect_binder._build_group_ok` against the
#: granted-to permanent (`_apply_layer_6_ability` passes it that permanent
#: as the source). A condition carrying any *other* key (a filter tied to
#: this ability's own source's history — `crewed_by_self`,
#: `damaged_by_source_this_turn`, …) fails closed for the whole body.
REGRANT_SAFE_GROUP_KEYS = frozenset(
    {"subject", "type", "subtypes", "excluded_subtypes", "nontoken", "nonland", "filter",
     "nonbasic", "controller", "owner", "other", "goaded", "in_combat", "is_player", "combat"}
)

#: Type words that are *not* creature subtypes — a scope built on one of these
#: isn't a creature anthem/grant, so we don't claim it. ``enchanted``/
#: ``equipped`` belong here too (PAR-3 spot-check, Greater Auramancy's
#: "Enchanted creatures you control have shroud."): they're a characteristic
#: filter, not a subtype — `_has_subtype` would never see "Enchanted" on any
#: real creature's type line, so guessing one as a subtype silently matches
#: nothing instead of the intended creatures. Leading attachment adjectives
#: now use `scope_adjective`'s individual live filters, just like the trailing
#: "that are enchanted/equipped" qualifiers. Keep these words out of the
#: subtype fallback; the combined enchanted-or-equipped selector is broader.
NONCREATURE_TYPES: frozenset[str] = frozenset(
    {"creature", "artifact", "enchantment", "land", "permanent", "planeswalker", "token",
     "enchanted", "equipped"}
)

#: RULE 300.2's artifact subtypes that are never also a creature subtype (a
#: Vehicle isn't a creature until crewed, RULE 702.122a) — a bare "Vehicles
#: [you control]" scope must not fall into `parse_scope`'s ordinary singular-word
#: branch below, which would otherwise silently guess it as a *creature*
#: subtype and scope the anthem to ``creatures_you_control``: a Vehicle that
#: hasn't been crewed yet is never a creature, so that pool would (wrongly)
#: exclude every uncrewed Vehicle instead of the printed "Vehicles you
#: control" reading (Balthier and Fran). Kept distinct from
#: `NONCREATURE_TYPES` (main *types*, not subtypes) so its own docstring
#: stays accurate; `vehicle_scope_params`/`is_vehicle_scope` below are the
#: artifact-subtype-scoped fallback `ANTHEM_RE`/`GRANT_RE`/`QUOTED_GRANT_RE`
#: all reach for exactly this word, the same "fall back to the permanent
#: family instead of guessing a creature subtype" idiom `_permanent_type_
#: scope` already uses for the bare main-type words.
ARTIFACT_SUBTYPES: frozenset[str] = frozenset({"vehicle"})

#: Colour words → their WUBRG/C symbol, for a colour-scoped anthem. PAR-63:
#: the shared five plus the one entry this use genuinely adds, so the common
#: part stays common instead of being re-typed.
COLOR_WORDS: dict[str, str] = {**COLOR_LETTERS, "colorless": "C"}


#: An optional "of the chosen type/color" tail (RULE 601.2b, Adaptive
#: Automaton/Ward Sliver-shaped) — the dynamic sibling of a literal subtype/
#: colour scope, sitting between the "you control" clause and "get"/"have".
CHOSEN_TAIL = r"(?: of the chosen (?P<chosen>type|color))?"
#: PAR-109: an optional "with `<qualifier>`" / "that are enchanted" tail between "you control" and "get"/"have"
#: ("Creatures you control **with flying** get +1/+1", "…**with +1/+1 counters on them** have trample", "…**with
#: the chosen name** have haste"). Read back by `parse_scope_params` (`_qualifier_params`); a qualifier outside the
#: vocabulary fails the whole clause.
_QUAL_TAIL = (
    r"(?P<qual> (?:with|that (?:are|entered)) (?:(?!get\b|gets\b|have\b|has\b)[a-z0-9+/' -])+?)?"
)

# "[Other] <scope> [you control] [of the chosen type/color] get +N/+N [and
# have <keywords>]"  (anthem, +grant)
ANTHEM_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ,/]*?)(?P<yours> you control)?"
    rf"{CHOSEN_TAIL}{_QUAL_TAIL} "
    r"get (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    # PAR-65: braces/digits alongside the ordinary bare-word list admit
    # Ward's own "{cost}" (`_flag_keywords_and_ward`, not `flag_keywords`).
    r"(?: and have (?P<kw>[a-z0-9][a-z0-9,{}— ]*)"
    # PAR-266 (Koloth, Tribble Hunter): "All Tribbles get +1/+0 and are goaded." -- RULE 701.15b goad as a standing
    # group static, the P/T sibling of `GROUP_GOADED_RE` (RULE 611.3a: it lasts while the source is on the battlefield).
    r"| and (?P<goaded>are goaded))?",
    re.IGNORECASE,
)
# The controller-opposite sibling of the ordinary group anthem.  It has its
# own selector because "your opponents control" is not an adjective inside a
# creature subtype; `continuous.group_selector_objects` already supplies the
# matching live group.
OPPONENT_CREATURE_ANTHEM_RE = re.compile(
    r"creatures your opponents control get (?P<p>[+-]\d+)/(?P<t>[+-]\d+)",
    re.IGNORECASE,
)
SELF_ANTHEM_PER_OPPONENT_COLOR_PERMANENT_RE = re.compile(
    r"~ gets \+(?P<p>\d+)/\+(?P<t>\d+) for each (?P<color>white|blue|black|red|green) permanent your opponents control",
    re.IGNORECASE,
)
# "[Other] <scope> [you control] [of the chosen type/color] have <keywords>"
# (keyword grant, layer 6)
GRANT_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ,/]*?)(?P<yours> you control)?"
    rf"{CHOSEN_TAIL}{_QUAL_TAIL} "
    # PAR-65: admits Ward's own "{cost}" — see `_flag_keywords_and_ward`.
    r"have (?P<kw>[a-z0-9][a-z0-9,{}— ]*)",
    re.IGNORECASE,
)
# PAR-31: "Artifacts, creatures, enchantments, and lands you control have
# <keywords>." (Elspeth, Knight-Errant's −8 emblem; also a standing static
# on a handful of permanents) — a keyword grant whose scope is an
# explicit *list* of two or more permanent-type words rather than the
# single word `GRANT_RE`/`permanent_type_scope` handles. `GRANT_RE`'s
# own `body` group is comma-free (`[a-z][a-z ]*?`), so this never
# competes with it. Emits one `grant_keyword` scoped to
# `permanents_you_control` narrowed by the `card_type` list
# `continuous.affected_objects` already ORs (Grand Abolisher-shaped).
MULTI_PERMANENT_TYPE_GRANT_RE = re.compile(
    r"(?P<body>(?:artifacts|creatures|enchantments|lands|planeswalkers)"
    r"(?:,? (?:and )?(?:artifacts|creatures|enchantments|lands|planeswalkers))+)"
    # PAR-65: admits Ward's own "{cost}" — see `_flag_keywords_and_ward`.
    r" you control have (?P<kw>[a-z0-9][a-z0-9,{}— ]*)",
    re.IGNORECASE,
)
# "Each creature you control with a +1/+1 counter on it has <keywords>."
# (PAR-34 — the Abzan "outlast" cycle: Abzan Falconer / Abzan Battle
# Priest / Ainok Bond-Kin / Hardened Scales-adjacent). A `grant_keyword`
# static scoped to `creatures_you_control` **filtered by counter
# presence** — `continuous.affected_objects`' `has_counter_kind` param
# (MEC-21, Agatha's Soul Cauldron) already narrows the group that way, so
# no engine change. Singular "has" (subject is "each creature"), so it
# doesn't collide with `GRANT_RE`'s plural "have".
GROUP_COUNTER_GRANT_RE = re.compile(
    r"each creature you control with a \+1/\+1 counter on it has "
    r"(?P<kw>[a-z][a-z, ]*)",
    re.IGNORECASE,
)

# "[Other] <scope> [you control] [of the chosen type/color] have \"<ability>\""
# (Tyvar Kell/Acidic Sliver-shaped — "Elves you control have '{T}: Add
# {B}.'"/"All Slivers have '{2}, Sacrifice this permanent: ...'") — the
# non-attached sibling of `ATTACHED_QUOTED_GRANT_RE`/`_ATTACHED_QUOTED_
# ANTHEM_GRANT_RE` above: a group-scoped grant of a *full* ability
# (recursively parsed via `quoted_ability_grant_effects`, same as the
# attached family) rather than a bare keyword list (`GRANT_RE` just
# above). Shares `parse_scope`/`parse_scope_params` with `GRANT_RE`/`ANTHEM_RE` for
# the `affects` (+ subtype/colour/tokens/chosen) params.
QUOTED_GRANT_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ,/]*?)(?P<yours> you control)?"
    rf"{CHOSEN_TAIL}{_QUAL_TAIL} "
    r'''have (?P<quote>["'])(?P<inner>.+)(?P=quote)''',
    re.IGNORECASE | re.DOTALL,
)

# "Commander creatures you own have \"<ability>\"" (Acolyte of Bahamut/Agent
# of the Iron Throne/Candlekeep Sage-shaped cEDH support cards) — a fixed,
# single-phrase scope rather than routing through `parse_scope`/`QUOTED_GRANT_RE`'s
# general vocabulary: "commander" is a designation (`GameObject.
# is_commander`), not a card type or creature subtype `parse_scope` recognises,
# and no real card pairs it with a colour/subtype/token qualifier the
# general grammar would otherwise need to carry. Tried before
# `QUOTED_GRANT_RE` below (which would otherwise fail closed on it anyway —
# "commander" isn't in `parse_scope`'s or `permanent_type_scope`'s vocabulary —
# but keeping the dedicated, unambiguous phrase first avoids relying on that
# fallthrough).
COMMANDER_CREATURES_QUOTED_GRANT_RE = re.compile(
    r'commander creatures you own have "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)


#: Card-type words the "opponent-scoped"/"prohibition"/"type-overwrite"
#: families below recognise as a `card_type` selector (`continuous.
#: _has_card_type` reads the matching `Card.is_<word>` flag) — deliberately
#: small: only the categories that actually appear in this shape on real
#: cards (a spell-only type like "instant" never does, since none of these
#: clauses talk about spells).
CARD_TYPE_WORDS: frozenset[str] = frozenset(
    {"artifact", "creature", "enchantment", "land", "planeswalker", "permanent"}
)

#: The creature/artifact subtypes real "as long as enchanted `<x>` is a `<y>`"
#: clauses actually name. Kept small and explicit: an open subtype
#: vocabulary here would claim clauses whose word is really something else
#: entirely. Moved above
#: `_STATIC_CONDITION_RES` (PAR-120) once its own "it was a `<subtype>`" rows
#: started referencing it inside that list literal at module-load time.
CONDITION_SUBTYPE_WORDS: frozenset[str] = frozenset(
    {"vehicle", "human", "goblin", "elf", "zombie", "spirit", "warrior", "knight", "soldier",
     "equipment", "aura", "dragon", "angel", "demon", "wizard", "cleric", "rogue", "beast"}
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
PT_CDA_RE = re.compile(
    r"~'?s power and toughness are each equal to (?P<what>.+)",
    re.IGNORECASE,
)
TURN_SPLIT_FIXED_PT_RE = re.compile(
    r"during turns other than yours, ~'?s power and toughness are each (?P<n>\d+)",
    re.IGNORECASE,
)
TURN_SPLIT_PT_RE = re.compile(
    r"(?P<first>during your turn, ~'?s power and toughness are each equal to [^.]+)\.\s*"
    r"(?P<second>during turns other than yours, ~'?s power and toughness are each \d+)",
    re.IGNORECASE,
)

#: PAR-43: the *single-characteristic* CDA — "~'s power is equal to the
#: number of `<X>`." (Ironroot Warlord / Kolaghan Forerunners / Suki, Kyoshi
#: Warrior — a printed toughness, power defined by a live count) and the
#: rarer toughness form (Traproot Kami). `continuous.recompute`'s 7a
#: `pt_cda` pass already applies `power_count` / `toughness_count`
#: independently, so a spec with only one of them is enough — no engine
#: change. Both forms read the shared count phrase grammar.
PT_CDA_SINGLE_RE = re.compile(
    r"~'?s (?P<char>power|toughness) is equal to (?P<what>.+)",
    re.IGNORECASE,
)
PT_CDA_THAT_NUMBER_RE = re.compile(
    r"~'?s power is equal to (?P<what>.+?) and its toughness is equal to that number plus (?P<plus>\d+)\.?",
    re.IGNORECASE,
)

#: PAR-72: see the ``static_effect_specs`` dispatch entry using this below.
BURAKOS_SELF_TYPES_RE = re.compile(
    r"~ is also a cleric, rogue, warrior, and wizard", re.IGNORECASE,
)

#: PAR-120: the `<X>` phrases `PT_CDA_RE` accepts that the shared
#: `count_phrase` noun-phrase grammar (below) doesn't cover — RULE 700.8's
#: party count is a bipartite-matching special case, not a `{zone, of,
#: filter}` selector, so it stays its own named string rather than a
#: duplicate table entry. Every phrase the grammar *does* cover (the four
#: this table used to also list: "cards in your hand", "lands you control",
#: "cards in your graveyard", "creatures you control") now reaches
#: `continuous.count_selector` as a structured selector instead, retiring
#: those four rows — `pt_cda_selector` below tries the grammar first.
_PT_CDA_SELECTORS: dict[str, str] = {
    # PAR-72: "~'s power is equal to the number of creatures in your
    # party." (Archpriest of Iona) — same `creatures_in_your_party`
    # selector `_SELF_ANTHEM_FOR_EACH_SELECTORS` above now also carries.
    "creatures in your party": "creatures_in_your_party",
}


def pt_cda_selector(what: str) -> "Optional[str | dict]":
    """`<X>` from `PT_CDA_RE`/`PT_CDA_SINGLE_RE` → a `continuous.
    count_selector` argument (structured dict or named string), or
    ``None`` for an unwhitelisted quantity (fail-closed — RULE 604.3 must
    never silently define a creature as 0/0)."""

    structured = parse_amount_phrase(what)
    if structured is not None:
        return structured
    if what.startswith("the number of "):
        return _PT_CDA_SELECTORS.get(what[len("the number of "):])
    return None
