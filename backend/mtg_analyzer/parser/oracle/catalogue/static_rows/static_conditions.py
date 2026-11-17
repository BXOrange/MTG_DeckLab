"""Static-ability helpers: static conditions (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional
from ...spec import EffectSpec
from ..count_phrase import NUMBER_WORD_PATTERN, number_value, parse_count_condition, parse_count_phrase
from ..subgrammars import CARD_TYPE_WORD_ALT, COLOR_LETTERS, DEVOTION, devotion_selector
from ..characteristic_phrase import KEYWORD_WORDS, parse_object_phrase, parse_stat_relation
from ..history_phrase import parse_history_condition
from ..referent_condition import parse_referent_condition
from ..subtype_vocabulary import SUBTYPES
from .anthem_patterns import CARD_TYPE_WORDS, CONDITION_SUBTYPE_WORDS
from .object_scope import (
    defending_controls_condition,
    object_filter,
    parse_scope,
    parse_scope_params,
)
from .combat_restrictions import ATTACHED_SUBJECT_PATTERN, combat_restriction_affects
from .keyword_flags import flag_keywords

#: "unless <condition>" rows that only make sense *in combat* (they name the defending/attacking
#: player, which the shared static vocabulary has no subject for) → a `GameEngine._combat_condition_met`
#: condition dict. Every other "unless" condition (board counts, hand/graveyard size, creature-died
#: history) is read through `static_condition`, the shared condition vocabulary, and evaluated by
#: `static_conditions.condition_holds` (PAR-282); anything unlisted fails closed (the clause stays unclaimed).
_CONDITION_RES: list[tuple[re.Pattern[str], Callable[["re.Match[str]"], Optional[dict]]]] = [
    (
        re.compile(r"defending player controls (?P<what>.+)", re.I),
        lambda m: defending_controls_condition(m.group("what")),
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
]

_SPELLED_NUMBER = re.compile(rf"\b(?!\d){NUMBER_WORD_PATTERN}\b", re.I)


def _fold_number_words(text: str) -> str:
    """Spelled-out counts → digits ("three or more creatures" → "3 or more
    creatures"), so one numeric grammar covers both spellings."""
    # The shared count grammar's spelled-out numbers (one..ten), not a private 1-7 table (PAR-282).
    return _SPELLED_NUMBER.sub(lambda m: str(number_value(m.group(0).lower())), text)


def parse_combat_condition(text: str) -> Optional[dict]:
    """An "unless <text>" clause → a condition dict, or ``None`` (fail-closed)."""
    text = _fold_number_words(text.strip().rstrip(".").strip())
    for pattern, build in _CONDITION_RES:
        m = pattern.fullmatch(text)
        if m is not None:
            return build(m)
    return static_condition(text)


#: The subject of a qualified restriction — the same self/attached vocabulary
#: the plain flags use, plus a "you control"-style *group* scope so
#: "Each creature you control with a +1/+1 counter on it …"-free group forms
#: ("Creatures you control can't be blocked by Walls") land too. The group
#: branch reuses the anthem family's `parse_scope`/`parse_scope_params`, hence the
#: ``scope``/``yours`` group names those two expect. The trailing ``qkind``/
#: ``qn``/``qdir`` group is a per-object power/toughness qualifier on the
#: scope itself ("Each creature you control **with power 4 or greater**
#: can't be blocked by more than one creature." — Challenger Troll/
#: Flopsie-shaped) — distinct from the restriction *tail*'s own filter
#: (which describes the *other* creature in the interaction, e.g. the
#: blocker), so it gets its own group rather than reusing `object_filter`.
_QUALIFIED_SUBJECT = (
    rf"(?P<subject>~|{ATTACHED_SUBJECT_PATTERN})"
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
        re.compile(r"can'?t block or be blocked by (?P<filter>.+)", re.I),
        lambda m: _filter_restriction(m, "cant_block_filtered", "cant_be_blocked_by"),
    ),
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
#: existing `ATTACHED_GRANT_RE` family (whose `fullmatch` the tail defeats)
#: unchanged.
_QUALIFIED_CLAUSE_RE = re.compile(
    rf"(?:{_QUALIFIED_SUBJECT})"
    r"(?: (?:has|have) (?P<kw>[a-z, ]+?) and)?"
    # Every tail is a "can't …" except the one *permitted*-set phrasing,
    # "can block only <filter>" (RULE 509.1a, Wall of Air-shaped).
    r" (?P<tail>can'?t .+|can block only .+)",
    re.IGNORECASE,
)


def _filter_restriction(m: "re.Match[str]", *kinds: str) -> Optional[list[dict]]:
    filt = object_filter(m.group("filter"))
    return None if filt is None else [{"kind": kind, "filter": filt} for kind in kinds]


def _condition_restriction(m: "re.Match[str]", *kinds: str) -> Optional[list[dict]]:
    condition = parse_combat_condition(m.group("cond"))
    return None if condition is None else [{"kind": k, "condition": condition} for k in kinds]


def _qualified_affects(m: "re.Match[str]") -> Optional[dict]:
    """The ``affects``(+selector) params for a `_QUALIFIED_SUBJECT` match, or
    ``None`` for a group scope outside `parse_scope`'s vocabulary (fail-closed)."""
    subject = m.groupdict().get("subject")
    if subject:
        return {"affects": combat_restriction_affects(subject)}
    scope = parse_scope(m.group("body") or "")
    if scope is None:
        return None
    params = parse_scope_params(scope, m)
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


def qualified_combat_restriction_specs(text: str) -> Optional[list[EffectSpec]]:
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
            keywords = flag_keywords(m.group("kw"))
            if keywords is None:
                return None
            specs.insert(0, EffectSpec("grant_keyword", {"keywords": keywords, **affects}))
        return specs
    return None


#: PAR-283: the subject of a past- or present-tense characteristic test on a referent an earlier clause or the trigger
#: named — "it", or "that <noun>". The nouns are the object kinds a resolving clause can have picked (RULE 608.2b/h).
_REFERENT_NOUNS = "creature|permanent|card|spell|land|artifact"
#: "if a Saproling was sacrificed this way" after a sacrifice *cost* (Thallid Omnivore): the same record, spelled from the
#: other end. An effect's own sacrifice is read by the `this_way_pool` grammar first; what reaches here has no pool.
_COST_SACRIFICED_THIS_WAY_RE = re.compile(r"an? (?P<words>[a-z]+(?: [a-z]+){0,2}?)(?: card)? (?:was|is) sacrificed this way", re.I)
_COST_OBJECT_TYPE_RE = re.compile(
    rf"the (?P<verb>sacrificed|discarded) (?:{_REFERENT_NOUNS}) (?P<neg>wasn'?t|was not|was) (?:an? )?"
    r"(?P<words>[a-z]+(?: [a-z]+){0,3})",
    re.I,
)
_REFERENT_TYPE_RE = re.compile(
    rf"(?:it|that (?:{_REFERENT_NOUNS}))(?:'s| (?P<neg>wasn'?t|isn'?t|was not|is not)| was| is)? "
    r"an? (?P<words>[a-z]+(?: [a-z]+){0,3})",
    re.I,
)
#: The condition sub-grammar: (regex over the condition text, builder). Only
#: shapes whose `static_conditions` kind exists — anything else leaves the
#: whole clause unclaimed (fail-closed), which is why this list is ordered
#: most-specific-first.
_STATIC_CONDITION_RES: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(r"(?:~'s|its|this spell's) emerge cost was paid", re.I),
     lambda m: {'kind': 'flag', 'flag': 'emerge_cost_paid'}),
    # RULE 732.1: shared by conditional effect bodies and standing abilities.
    (re.compile(r"it(?:'s| is) (?P<designation>day|night)", re.I),
     lambda m: {"kind": "day_night", "designation": m.group("designation").lower()}),
    # PAR-124 (Spellchain Scatter): "if this spell wasn't/was kicked, …" —
    # `static_conditions.py`'s own ``"kicked"`` kind (RULE 702.33b) already
    # reads `GameObject.kicker_count`, built for the amount-override family
    # (`amount_if_kicked`); only the oracle-text *condition-phrase*
    # recognition (as opposed to an inline "…instead" override) was missing.
    (re.compile(r"this spell wasn'?t kicked", re.I),
     lambda m: {"kind": "kicked", "max": 0}),
    (re.compile(r"this spell was kicked", re.I),
     lambda m: {"kind": "kicked", "min": 1}),
    # PAR-283 / RULE 107.3c: "if X is 5 or more" / "if X was 7 or greater" / "if X is 3" -- the X announced for the
    # spell (or the permanent's ETB) is `GameObject.x_paid`, the value the `x_paid` kind compares against
    # ``min``/``max``. A bare "X is N" is both bounds.
    (re.compile(r"x (?:is|was) (?P<n>\d+)(?: or (?P<dir>more|greater|less|fewer))?", re.I),
     lambda m: _x_condition(m)),
    # PAR-283 / RULE 702.33b: the cast-time record of the *triggering* spell ("whenever you cast a spell, if that spell
    # was kicked, …", Bloodstone Goblin/Hallar) and the negated source spelling ("if ~ wasn't kicked", Skizzik). The
    # subject is left off: the caller scopes it to the trigger's subject / the source.
    (re.compile(r"that spell was kicked", re.I),
     lambda m: {"kind": "kicked", "min": 1, "of": "trigger_subject"}),
    # PAR-283 / RULE 202.3: "if that spell's mana value was 3 or less" after a counter clause (Reject Imperfection, Sound the
    # Trumpets) or under a cast trigger (Prismari Apprentice) -- the printed mana value, the same in every zone.
    (re.compile(r"that spell'?s mana value (?:was|is) (?P<n>\d+) or (?P<dir>more|greater|less|fewer)", re.I),
     lambda m: {"kind": "mana_value", "of": "previous_target",
                ("min" if m.group("dir").lower() in ("more", "greater") else "max"): int(m.group("n"))}),
    (re.compile(r"(?:~|it) wasn'?t kicked", re.I),
     lambda m: {"kind": "kicked", "max": 0}),
    # PAR-283 / RULE 113.6 + 400.7: "if ~ is in your graveyard" -- a graveyard-zone ability's intervening-if (Arden Angel,
    # Firemane Angel, Bridge from Below, Vengeful Pharaoh, Moss-Pit Skeleton) asks where its own source is.
    (re.compile(r"(?:~|this card) is in your graveyard", re.I),
     lambda m: {"kind": "source_in_graveyard"}),
    # PAR-283 / RULE 508.1: "if ~ didn't attack this turn" -- the negation of Boast's per-object declaration flag.
    (re.compile(r"(?:~|it) (?:didn'?t|did not) attack this turn", re.I),
     lambda m: {"kind": "not", "condition": {"kind": "source_attacked_this_turn"}}),
    # PAR-283 (Pestilence, Call to the Grave): the board-wide emptiness check `no_creatures_on_battlefield` reads.
    (re.compile(r"no creatures are on the battlefield", re.I),
     lambda m: {"kind": "no_creatures_on_battlefield"}),
    # PAR-283 / RULE 402: "if you have more cards in hand than each opponent" (Akuta, Death of a Thousand Stings, Exile
    # into Darkness) -- strictly more than every other living player, the hand-size sibling of `you_have_most`.
    (re.compile(r"you have more cards in hand than each opponent", re.I),
     lambda m: {"kind": "you_have_most_cards_in_hand"}),
    # The hybrid cycle's "if {w} was spent to cast this spell" (Repel Intruders, Boros Fury-Shield, Firespout's halves):
    # at least one mana of that colour paid for the spell (`GameObject.mana_by_color_spent_to_cast`, Adamant's fact).
    (re.compile(r"\{(?P<c>[wubrg])\} was spent to cast (?:this spell|it)", re.I),
     lambda m: {"kind": "mana_color_spent_to_cast_at_least", "color": m.group("c").upper(), "amount": 1}),
    # MEC-106 / RULE 702.174k: "the gift was[n't] promised" — `GameObject.gift_promised`,
    # stamped when the spell was cast, read by a resolving spell and by a permanent's
    # intervening-if alike (the flag lives on the source either way).
    (re.compile(r"the gift wasn'?t promised", re.I),
     lambda m: {"kind": "not", "condition": {"kind": "flag", "flag": "gift_promised"}}),
    (re.compile(r"the gift was promised", re.I),
     lambda m: {"kind": "flag", "flag": "gift_promised"}),
    # PAR-190 / RULE 702.104b: "if tribute wasn't paid" — `GameObject.tribute_paid`, stamped by the opponent's
    # as-enters Tribute choice (`RulesEngine._offer_tribute`).
    (re.compile(r"tribute wasn'?t paid", re.I),
     lambda m: {"kind": "not", "condition": {"kind": "flag", "flag": "tribute_paid"}}),
    (re.compile(r"tribute was paid", re.I),
     lambda m: {"kind": "flag", "flag": "tribute_paid"}),
    # PAR-139 / RULE 702.35: "(if) its / this spell's madness cost was paid" — `GameObject.madness_cost_paid`.
    (re.compile(r"(?:its|this spell'?s) madness cost was paid", re.I),
     lambda m: {"kind": "flag", "flag": "madness_cost_paid"}),
    # RULE 702.117: "(if) its / this spell's surge cost was paid" — `GameObject.surge_cost_paid`.
    (re.compile(r"(?:its|this spell'?s) surge cost was paid", re.I),
     lambda m: {"kind": "flag", "flag": "surge_cost_paid"}),
    (re.compile(r"you control a legendary (?P<subtype>[a-z]+)", re.I),
     lambda m: {"kind": "control_legendary_subtype", "subtype": m.group("subtype").lower()}),
    # PAR-98: reused by conditional activation-cost reductions as well as
    # ordinary "as long as" clauses.
    (re.compile(r"you control a legendary creature", re.I),
     lambda m: {"kind": "control_count", "selector": "legendary_creatures_you_control", "min": 1}),
    (re.compile(r"evidence was collected", re.I),
     lambda m: {"kind": "flag", "flag": "additional_cost_paid"}),
    (re.compile(r"~ is suspected", re.I),
     lambda m: {"kind": "flag", "flag": "is_suspected", "of": "source"}),
    (re.compile(r"it'?s not suspected", re.I),
     lambda m: {"kind": "not", "condition": {"kind": "flag", "flag": "is_suspected", "of": "source"}}),
    (re.compile(r"you'?ve cast another (?P<color>white|blue|black|red|green) spell this turn", re.I),
     lambda m: {"kind": "another_spell_cast_this_turn",
                "color": {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[m.group("color").lower()]}),
    (re.compile(r"you'?ve cast another instant or sorcery spell this turn", re.I),
     lambda m: {"kind": "another_spell_cast_this_turn", "spell_type": "instant_or_sorcery"}),
    # "as long as you control a Swamp" (Sedge Sliver) — a live basic-land
    # subtype count, using the same selector vocabulary the layer engine
    # already consults for land-count thresholds.
    (
        re.compile(r"you control an? (?P<land>island|swamp|mountain|forest|plains)", re.I),
        lambda m: {"kind": "control_count", "selector": f"lands_you_control_of_type_{m.group('land').lower()}", "min": 1},
    ),
    # "as long as you control a permanent of each color" (Spirit of
    # Resistance, PAR-78) — a devotion-shaped five-colour check, not a
    # single count, so it's its own `static_conditions.py` kind rather than
    # `control_count`'s min/max-on-one-selector shape.
    (
        re.compile(r"you control an? permanent of each color", re.I),
        lambda m: {"kind": "control_permanent_of_each_color"},
    ),
    # -- PAR-62: the four highest-frequency `if <cond>` phrases whose engine
    # kind already existed but had no parser-side row. Measured over every
    # unclaimed clause in the cache; adding them here widens the RULE 603.4
    # effect gate and the RULE 613.6 "as long as" statics at once, because
    # both read this one whitelist.
    # "if a creature died this turn" (62 occurrences).
    (re.compile(r"(?:a|another) creature died this turn", re.I),
     lambda m: {"kind": "creatures_died_this_turn", "min": 1}),
    # MEC-84 (Revolt / Disappear ability words, already stripped by
    # `normalize`): "if a permanent left the battlefield under your control
    # this turn" (~25). The `creature` variant is the RULE 700.4-narrowed
    # sibling (Tale of Momo, That's Rough Buddy). Both feed the shared
    # whitelist, so the RULE 603.4 effect gate and any "as long as" static
    # (Aether Revolt) pick them up at once.
    # Void: one shared condition for the entire game, not controller-scoped.
    (re.compile(r"a nonland permanent left the battlefield this turn or a spell was warped this turn", re.I),
     lambda m: {"kind": "void_this_turn"}),
    (re.compile(r"an? permanent left the battlefield under your control this turn", re.I),
     lambda m: {"kind": "permanent_left_battlefield_this_turn", "min": 1}),
    (re.compile(r"an? creature left the battlefield under your control this turn", re.I),
     lambda m: {"kind": "creature_left_battlefield_this_turn", "min": 1}),
    # "if you gained life this turn" (31).
    (re.compile(r"you(?:'ve| have)? gained life this turn", re.I),
     lambda m: {"kind": "gained_life_this_turn"}),
    # "if you gained 7 or more life this turn" (Aerith, Last Ancient).
    (re.compile(rf"you(?:'ve| have)? gained (?P<n>{NUMBER_WORD_PATTERN}) or more life this turn", re.I),
     lambda m: {"kind": "gained_life_this_turn", "amount": number_value(m.group("n").lower())}),
    # RULE 700.17 "if you faced a dilemma this turn" (The Caretaker) — `GameState.dilemmas_faced_this_turn`.
    (re.compile(r"you(?:'ve| have)? faced a dilemma this turn", re.I),
     lambda m: {"kind": "faced_dilemma_this_turn"}),
    # "if you descended this turn" (Lost Caverns of Ixalan) — a permanent card was put into
    # your graveyard from anywhere.
    (re.compile(r"you(?:'ve| have)? descended this turn", re.I),
     lambda m: {"kind": "descended_this_turn"}),
    # "if an opponent lost life this turn" (18) — "any one opponent", the
    # reading the kind itself documents.
    (re.compile(r"an opponent lost life this turn", re.I),
     lambda m: {"kind": "opponent_lost_life_this_turn", "min": 1}),
    (re.compile(r"a player lost (?P<n>\d+) or more life this turn", re.I),
     lambda m: {"kind": "life_lost_this_turn", "scope": "any", "min": int(m.group("n"))}),
    (re.compile(r"you(?:'ve| have)? lost (?P<n>\d+) or more life this turn", re.I),
     lambda m: {"kind": "life_lost_this_turn", "scope": "you", "min": int(m.group("n"))}),
    (re.compile(r"you lost life last turn", re.I),
     lambda m: {"kind": "life_lost_last_turn", "scope": "you", "min": 1}),
    (re.compile(r"an opponent lost life last turn", re.I),
     lambda m: {"kind": "life_lost_last_turn", "scope": "opponents", "min": 1}),
    (re.compile(r"~ dealt damage to an opponent this turn", re.I),
     lambda m: {"kind": "source_dealt_damage_to_opponent_this_turn"}),
    (re.compile(r"(?P<n>\d+) or more damage was dealt to it this turn", re.I),
     lambda m: {"kind": "source_damage_received_this_turn", "min": int(m.group("n"))}),
    (re.compile(r"(?:a card|(?:one|1) or more cards) left your graveyard this turn", re.I),
     lambda m: {"kind": "card_left_graveyard_this_turn"}),
    (re.compile(rf"an opponent has (?P<n>{NUMBER_WORD_PATTERN}) or more poison counters", re.I),
     lambda m: {"kind": "opponent_poison_at_least", "amount": number_value(m.group("n").lower())}),
    # PAR-226 (Graveyard Shift): "there are 5 or more mana values among cards in your graveyard" -- Delirium-style
    # distinct-mana-value count (RULE 202.3), the predicate Sewer Crocodile's activation discount already reads.
    (re.compile(rf"there are (?P<n>{NUMBER_WORD_PATTERN}|\d+) or more mana values among cards in your graveyard", re.I),
     lambda m: {"kind": "distinct_mana_values_in_graveyard_at_least",
                "min": int(m.group("n")) if m.group("n").isdigit() else number_value(m.group("n").lower())}),
    # PAR-226 (Captain Mar-Vell): "an opponent has cast a spell this turn" -- any opponent's per-turn cast count.
    (re.compile(r"an opponent has cast a spell this turn", re.I),
     lambda m: {"kind": "opponent_cast_spell_this_turn"}),
    # PAR-226 (Kianne): "~'s power is even/odd" -- parity of the source's derived power (RULE 613 layers).
    (re.compile(r"~'s power is (?P<parity>even|odd)", re.I),
     lambda m: {"kind": "power_parity", "parity": m.group("parity").lower()}),
    (re.compile(r"mana from a treasure was spent to cast (?:it|this spell)", re.I),
     lambda m: {"kind": "treasure_mana_spent_to_cast"}),
    (re.compile(r"mana from a treasure was spent to activate this ability", re.I),
     lambda m: {"kind": "treasure_mana_spent_to_activate"}),
    # "if ~ is an enchantment" (22) — a live card-type read of the source,
    # which matters for the Cases/Sagas that change type mid-game. The five
    # alternatives are exactly the printed card types (`subgrammars.
    # CARD_TYPE_WORD_ALT`, shared with the N-way permanent target row) — the
    # abstract "permanent"/"nonland permanent" readings are excluded on
    # purpose: neither is a card type, so `is_card_type` on one can never hold.
    (re.compile(rf"(?:~|it)(?:'s| is) an? (?P<ct>{CARD_TYPE_WORD_ALT})", re.I),
     lambda m: {"kind": "is_card_type", "card_type": m.group("ct").lower()}),
    # PAR-141: "if ~ isn't a creature" (Emergent Haunting, Answered Prayers) — the ENG-36 `not` combinator
    # over the same live card-type read, true again once a type-change effect has made it one.
    (re.compile(rf"(?:~|it)(?: isn't|'s not| is not) an? (?P<ct>{CARD_TYPE_WORD_ALT})", re.I),
     lambda m: {"kind": "not", "condition": {"kind": "is_card_type", "card_type": m.group("ct").lower()}}),
    # PAR-242 (Sphinx of False Conclusions, Progenitor Mimic): "if ~ isn't a token" -- RULE 111.1 token status of the
    # source, the ``not`` combinator over the live `is_token` read.
    (re.compile(r"(?:~|it)(?: isn't|'s not| is not) a token", re.I),
     lambda m: {"kind": "not", "condition": {"kind": "is_token"}}),
    # "if you attacked this turn" (Raid; 47 occurrences in PAR-62's
    # residual scan). This asks whether the ability controller declared any
    # attacker; it is deliberately not the source-only Boast condition.
    (re.compile(r"you attacked this turn", re.I),
     lambda m: {"kind": "you_attacked_this_turn"}),
    # PAR-152 (Nemesis Phoenix): "you're attacking two or more opponents" — normalize has already made the number a digit.
    (re.compile(r"you(?:'re| are) attacking (?P<n>\d+) or more opponents", re.I),
     lambda m: {"kind": "attacking_opponents_at_least", "min": int(m.group("n"))}),
    # "it's the declare attackers step" (a step window, Nemesis Phoenix's activation timing).
    (re.compile(r"it'?s the (?P<step>declare attackers|beginning of combat|end) step", re.I),
     lambda m: {"kind": "during_step", "step": m.group("step").lower().replace(" ", "_")}),
    # PAR-64: "~ has indestructible as long as it attacked this turn." uses
    # the object's own declaration flag (Boast's existing engine predicate),
    # not Raid's controller-scoped history.
    (re.compile(r"(?:~|it) attacked this turn", re.I),
     lambda m: {"kind": "source_attacked_this_turn"}),
    # -- The source's own state. "it"/"~" both appear; after `normalize` the
    # card's own name is already `~`, and a leading "it" in this position can
    # only mean the source (the condition precedes any target).
    (re.compile(r"(?:~|it)(?:'s| is| remains) untapped", re.I),
     lambda m: {"kind": "source_untapped"}),
    (re.compile(r"(?:~|it)(?:'s| is| remains) tapped", re.I),
     lambda m: {"kind": "source_tapped"}),
    (re.compile(r"(?:~|it)(?:'s| is) monstrous", re.I),
     lambda m: {"kind": "source_monstrous"}),
    # MEC-79 / RULE 701.64b — the Marvel Infinity Stones' `∞` ability is
    # active "once harnessed"; `normalize` rewrites the `∞ —` marker line into
    # an ordinary phase trigger with a leading "if ~ is harnessed," so this
    # row backs both that RULE 603.4 gate and any "as long as ~ is harnessed"
    # static a future Stone prints.
    (re.compile(r"(?:~|it)(?:'s| is) harnessed", re.I),
     lambda m: {"kind": "source_harnessed"}),
    # PAR-252 (Joined Researchers): the controller-versus-opponents hand-size comparison.
    (re.compile(r"an opponent has more cards in hand than you", re.I),
     lambda m: {"kind": "opponent_has_more_cards_in_hand"}),
    # PAR-252 / RULE 723.3a: the "prepared" designation, and its negation "if ~ isn't prepared" (Paradox Shaper,
    # Stingerquill Voxmancer, Woodwork Prodigy) as the `not` combinator over the same read.
    (re.compile(r"(?:~|it)(?:'s| is) prepared", re.I),
     lambda m: {"kind": "source_prepared"}),
    (re.compile(r"(?:~|it)(?: isn't|'s not| is not) prepared", re.I),
     lambda m: {"kind": "not", "condition": {"kind": "source_prepared"}}),
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
    # PAR-135: the kindless spellings — "as long as ~ has four or more counters on it" (Gavel of the Righteous,
    # Warden of the Inner Sky) counts counters of any kind, like the kindless "has no counters on it" below. They
    # used to be claimed by the row after next reading "or more" as a *counter kind* (a condition that never held).
    (re.compile(r"(?:~|it) has (?P<n>a|an|\d+) or more counters on it", re.I),
     lambda m: {"kind": "source_counters", "min": _count_word(m.group("n"))}),
    (re.compile(r"(?:~|it) has (?P<n>\d+) or fewer counters on it", re.I),
     lambda m: {"kind": "source_counters", "max": _count_word(m.group("n"))}),
    # "~ has three or more +1/+1 counters on it" / "…a +1/+1 counter on it"
    (re.compile(r"(?:~|it) has (?P<n>a|an|\d+) or more (?P<kind>[+\-]\d/[+\-]\d|[a-z ]+?) counters? on it", re.I),
     lambda m: {"kind": "source_counters", "counter": _counter_kind(m.group("kind")),
                "min": _count_word(m.group("n"))}),
    # PAR-147: the "there are" spelling — "then if there are 100 or more luck counters on ~, you win the game"
    # (As Luck Would Have It) is the same count of the source's own counters as "~ has N or more … counters on it".
    (re.compile(r"there are (?P<n>a|an|\d+) or more (?P<kind>[+\-]\d/[+\-]\d|[a-z ]+?) counters? on (?:~|it)", re.I),
     lambda m: {"kind": "source_counters", "counter": _counter_kind(m.group("kind")),
                "min": _count_word(m.group("n"))}),
    # PAR-135: "…has two **or fewer** judgment counters on it" (Faithbound Judge) is an upper bound — without its
    # own row the next one read "or fewer judgment" as the counter's name and a lower bound of 2, silently.
    (re.compile(r"(?:~|it) has (?P<n>\d+) or fewer (?P<kind>[+\-]\d/[+\-]\d|[a-z ]+?) counters? on it", re.I),
     lambda m: {"kind": "source_counters", "counter": _counter_kind(m.group("kind")),
                "max": _count_word(m.group("n"))}),
    # "has an even/odd number of counters on it" is a parity of the count, not a counter *named* "even number of"
    # (it must fail closed until a parity condition reads it; Sab-Sunen, Luxa Embodied).
    (re.compile(r"(?:~|it) has (?P<n>a|an|\d+) (?!(?:or|even number|odd number) )"
                r"(?P<kind>[+\-]\d/[+\-]\d|[a-z ]+?) counters? on it", re.I),
     lambda m: {"kind": "source_counters", "counter": _counter_kind(m.group("kind")),
                "min": _count_word(m.group("n"))}),
    # PAR-140: the negations — "if ~ doesn't have a flying counter on it" (Inventive Wingsmith,
    # Risona) / "…has no +1/+1 counters on it" / "…no counters on it": RULE 122 presence, `max: 0`.
    (re.compile(
        r"(?:~|it) (?:doesn't|does not) have (?:a|an) (?P<kind>[+\-]\d/[+\-]\d|[a-z ]+?) counter on it", re.I),
     lambda m: {"kind": "source_counters", "counter": _counter_kind(m.group("kind")), "max": 0}),
    (re.compile(r"(?:~|it) has no (?P<kind>(?:[+\-]\d/[+\-]\d|[a-z ]+?) )?counters on it", re.I),
     lambda m: {"kind": "source_counters", "max": 0,
                **({"counter": _counter_kind(m.group("kind").strip())} if m.group("kind") else {})}),
    # -- The *attached permanent*'s characteristics, not the source's
    # ("as long as enchanted permanent is a creature"/"…is red"/"…is a
    # Human"). Same kinds as any other subject; the ``of`` key is what aims
    # them at the Aura/Equipment's host (RULE 303.4a/301.5c).
    (re.compile(rf"(?:{ATTACHED_SUBJECT_PATTERN}) is an? (?P<what>[a-z]+)", re.I),
     lambda m: _attached_characteristic(m.group("what"))),
    (re.compile(rf"(?:{ATTACHED_SUBJECT_PATTERN}) is (?P<what>[a-z]+)", re.I),
     lambda m: _attached_characteristic(m.group("what"))),
    # -- Whose turn it is.
    (re.compile(r"it's your turn", re.I), lambda m: {"kind": "your_turn"}),
    (re.compile(r"it's not your turn", re.I), lambda m: {"kind": "not_your_turn"}),
    # -- The controller's designations (RULE 726/727/702.131c) — MEC-12.
    (re.compile(r"you'?re the monarch", re.I), lambda m: {"kind": "is_monarch"}),
    # RULE 726.1: the negation reads the same designation ("if you're not the monarch", Court of Vantress).
    (re.compile(r"you'?re not the monarch", re.I), lambda m: {"kind": "not", "condition": {"kind": "is_monarch"}}),
    (re.compile(r"you have the initiative", re.I), lambda m: {"kind": "has_initiative"}),
    (re.compile(r"you have the city'?s blessing", re.I), lambda m: {"kind": "has_city_blessing"}),
    # RULE 702.195b (PAR-51) — Storied's own designation, same shape as the
    # city's blessing row just above.
    (re.compile(r"you have an enduring story", re.I), lambda m: {"kind": "has_enduring_story"}),
    # RULE 702.194b (PAR-56) — "this spell"/"it was cast using teamwork" as a
    # generic resolve-time condition (the trailing "…if/unless `<cond>`"
    # gates in `segmenter._GENERIC_IF_SUFFIX_RE`/`_GENERIC_UNLESS_SUFFIX_RE`
    # already route any whitelisted phrase here) — `GameObject.
    # teamwork_paid`, the same cast-time flag `_KICKED_CONDITION_RE`'s
    # leading-"if" sibling reads via `SUBJECT_FLAGS`.
    (re.compile(r"(?:this spell|it) was cast using teamwork", re.I),
     lambda m: {"kind": "flag", "flag": "teamwork_paid"}),
    # RULE 700.8/702.129 (PAR-53) — "full party" is exactly 4 (one each of
    # Cleric/Rogue/Warrior/Wizard), the cap `creatures_in_your_party`'s own
    # RULE 700.8 bipartite matcher can ever return — so this is the ordinary
    # `control_count` predicate at that literal threshold, not a new kind.
    (re.compile(r"you have a full party", re.I),
     lambda m: {"kind": "control_count", "selector": "creatures_in_your_party", "min": 4}),
    # -- Board counts, over `continuous.count_selector`'s own vocabulary.
    # PAR-120: "you control `<n>` or more `<X>`"/"you control a/an `<X>`"
    # (both the plain existence check and the "N or more" threshold) no
    # longer need a row here at all — `parse_count_condition` (tried below,
    # once every named row above has declined) already reaches both shapes
    # generically through the shared noun-phrase grammar, proven equivalent
    # to the old `_CONTROL_COUNT_SELECTORS` table for all six of its
    # entries (`test_par120_count_phrase.py`).
    #
    # "you control a creature with power N or greater" (Bolt Bend and 50+
    # other cache cards' cost-reduction/activation-condition gates) stays
    # its own row — a per-object power qualifier the plain existence count
    # doesn't carry.
    (re.compile(r"you control a creature with power (?P<n>\d+) or greater", re.I),
     lambda m: {"kind": "control_count", "selector": "creatures_you_control",
                "min": 1, "min_power": int(m.group("n"))}),
    # PAR-120: "creatures you control have total power `<n>` or greater/
    # less" (RULE 508.4/508.5-adjacent Ferocious-style threshold — Atarka
    # Beastbreaker's activation gate, Owlbear Shepherd/Gimli's Reckless
    # Might's leading "if", Kirk/La'An's trigger "while" tail — all three
    # surfaces already hand their condition text to this same function).
    # `total_power_creatures_you_control` is `continuous.count_selector`'s
    # own already-shipped sum-of-power reading (PAR-60, Volcanic Salvo's
    # cost reduction), reached here through the *same* generic
    # `control_count` kind an object-existence check uses — a `min`/`max`
    # threshold on a sum needs no different condition kind than one on a
    # count, since `count_selector` is what actually supplies the number
    # either way.
    (re.compile(
        r"creatures you control have total power (?P<n>\d+) or (?P<cmp>greater|less)", re.I,
    ), lambda m: {
        "kind": "control_count", "selector": "total_power_creatures_you_control",
        ("min" if m.group("cmp") == "greater" else "max"): int(m.group("n")),
    }),
    # PAR-120: "you attacked with creatures with total power `<n>` or
    # greater[ this combat]" (the Onslaught-block "Pack tactics" cluster —
    # Gnoll Hunter and five siblings' attack-trigger leading "if") — the
    # combat-scoped sibling of the row above, same `control_count` kind,
    # `continuous.count_selector`'s new `total_power_attacking_creatures_
    # you_control` branch supplying the sum.
    (re.compile(
        r"you attacked with creatures with total power (?P<n>\d+) or greater(?: this combat)?", re.I,
    ), lambda m: {
        "kind": "control_count", "selector": "total_power_attacking_creatures_you_control",
        "min": int(m.group("n")),
    }),
    # PAR-120: "if `<mana symbols>` was spent to cast it/this spell" — the
    # printed-mana-symbol sibling of Adamant's own word-form "if at least N
    # `<color>` mana was spent to cast it" (`_ADAMANT_MANA_SPENT_IF_RE`,
    # peeled before `match_clause` runs). One or two repeated pips of the
    # *same* colour/colourless symbol (the backreference `(?P=sym)` enforces
    # that — a mixed pair like "{w}{u}" is a different, unclaimed shape),
    # reading the exact same `mana_color_spent_to_cast_at_least` kind and
    # `GameObject.mana_by_color_spent_to_cast` dict Adamant already built
    # (PAR-95) — no new engine primitive, just a second spelling of the same
    # condition (Catharsis, Deceit, Emptiness, Drowner of Truth, Gruul
    # Scrapper, Ogre Savant, Revenant Patriarch, Shrieking Grotesque,
    # Steamcore Weird, Tin Street Hooligan).
    (re.compile(
        r"\{(?P<sym>[wubrgc])\}(?P<sym2>\{(?P=sym)\})? was spent to cast (?:it|this spell)", re.I,
    ), lambda m: {
        "kind": "mana_color_spent_to_cast_at_least",
        "color": m.group("sym").upper(),
        "amount": 2 if m.group("sym2") else 1,
    }),
    # PAR-120: "you control your commander" (RULE 903.4 — the "Loyal"
    # Commander-legends cycle's own gate, both as a standing "as long as"
    # condition and an attack/combat-trigger leading "if"). RULE 108.4:
    # control only applies to a battlefield permanent, so this is a plain
    # existence check over the new `commanders_you_control` selector, the
    # same `control_count` kind an object-existence check always uses.
    (re.compile(r"you control your commander", re.I),
     lambda m: {"kind": "control_count", "selector": "commanders_you_control", "min": 1}),
    (re.compile(r"there are (?P<n>\d+) or more cards in your graveyard", re.I),
     lambda m: {"kind": "control_count", "selector": "cards_in_your_graveyard",
                "min": int(m.group("n"))}),
    (re.compile(r"there are (?P<n>\d+) or more instant and/or sorcery cards in your graveyard", re.I),
     lambda m: {"kind": "graveyard_card_type_count_at_least",
                "types": ["instant", "sorcery"], "amount": int(m.group("n"))}),
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
    # leaving the bare "as long as" clause `conditional_static_specs`
    # already routes here).
    (re.compile(r"there are (?P<n>\d+) or more card types among cards in your graveyard", re.I),
     lambda m: {"kind": "card_types_in_graveyard_at_least", "amount": int(m.group("n"))}),
    # PAR-30: "as long as there's a `<subtype>` card in your graveyard" (the
    # Avatar: TLA "Lesson" cards). Bounded to a single subtype word so it
    # can't swallow a longer "N or more <x> cards" phrasing (handled above).
    (re.compile(r"there(?:'s| is| are) an? (?P<sub>[a-z][a-z-]+) card in your graveyard", re.I),
     lambda m: {"kind": "subtype_in_graveyard", "subtype": m.group("sub").lower()}),
    # -- The controller's own resources.
    # PAR-208 (Pulse of the Fields, Survival Cache): comparisons of life totals with some one opponent (RULE 119.1).
    (re.compile(r"an opponent has more life than you", re.I),
     lambda m: {"kind": "opponent_has_more", "selector": "your_life_total"}),
    (re.compile(r"you have more life than an opponent", re.I),
     lambda m: {"kind": "opponent_has_fewer", "selector": "your_life_total"}),
    (re.compile(r"you have (?P<n>\d+) or more life", re.I),
     lambda m: {"kind": "life_at_least", "amount": int(m.group("n"))}),
    (re.compile(r"you have (?P<n>\d+) or less life", re.I),
     lambda m: {"kind": "life_at_most", "amount": int(m.group("n"))}),
    (re.compile(r"you have (?P<n>\d+) or more cards in (?:your )?hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_least", "amount": int(m.group("n"))}),
    (re.compile(r"you have (?P<n>\d+) or fewer cards in (?:your )?hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_most", "amount": int(m.group("n"))}),
    # PAR-176 (Library of Alexandria, Magus of the Library): "exactly N" is the two bounds together.
    (re.compile(r"you have exactly (?P<n>\d+) cards in (?:your )?hand", re.I),
     lambda m: {"kind": "all", "conditions": [
         {"kind": "cards_in_hand_at_least", "amount": int(m.group("n"))},
         {"kind": "cards_in_hand_at_most", "amount": int(m.group("n"))}]}),
    # PAR-176 (Ayli, Eternal Pilgrim): Righteous Valkyrie's starting-life-total reading, spelled "at least N life more".
    (re.compile(r"you have at least (?P<n>\d+) life more than your starting life total", re.I),
     lambda m: {"kind": "life_over_starting_at_least", "amount": int(m.group("n"))}),
    # PAR-176: the source's own derived power (RULE 613) -- "Activate only if this creature's power is 4 or greater".
    (re.compile(r"(?:~|this creature)'s power is (?P<n>\d+) or greater", re.I),
     lambda m: {"kind": "power", "min": int(m.group("n"))}),
    # PAR-176 (Fungus Elemental): `entered_this_turn` reads the source's own entry turn.
    (re.compile(r"(?:~|this creature) entered (?:the battlefield )?this turn", re.I),
     lambda m: {"kind": "entered_this_turn"}),
    # PAR-176 (Skarrgan Firebird): RULE 120.3 damage dealt to any opponent this turn.
    (re.compile(r"an opponent was dealt damage this turn", re.I),
     lambda m: {"kind": "opponent_was_dealt_damage_this_turn"}),
    # PAR-176 (Tectonic Edge): a per-opponent land count.
    (re.compile(r"an opponent controls (?P<n>\d+) or more lands", re.I),
     lambda m: {"kind": "opponent_controls_at_least", "min": int(m.group("n")), "filter": {"card_type": "land"}}),
    # PAR-176 (Isolated Watchtower): `opponent_controls_more_lands` with the required margin.
    (re.compile(r"an opponent controls at least (?P<n>\d+) more lands than you", re.I),
     lambda m: {"kind": "opponent_controls_more_lands", "margin": int(m.group("n"))}),
    # PAR-176 (Zhalfirin Decoy, Cleaving Reaper): "you had X enter the battlefield under your control this turn" is
    # the past-tense history "X entered the battlefield under your control this turn" (RULE 603.4-style event log).
    (re.compile(r"you had (?P<what>.+?) enter the battlefield under your control this turn", re.I),
     lambda m: static_condition(f"{m.group('what')} entered the battlefield under your control this turn")),
    # PAR-176 (Sawback Manticore): the source is in combat as an attacker or blocker.
    (re.compile(r"(?:~|this creature) is attacking or blocking", re.I),
     lambda m: {"kind": "any", "conditions": [{"kind": "source_attacking"}, {"kind": "source_blocking"}]}),
    # PAR-176 (Grizzled Wolverine): RULE 509.1a -- some creature is currently declared as blocking the source.
    (re.compile(r"at least (?:one|1) creature is blocking (?:~|this creature)", re.I),
     lambda m: {"kind": "source_has_blockers"}),
    (re.compile(r"you have no cards in hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_most", "amount": 0}),
    # "as long as you've drawn two or more cards this turn" — read off
    # `GameState.cards_drawn_this_turn`, which already exists for the
    # draw-limit permission.
    (re.compile(rf"you'?ve drawn (?P<n>{NUMBER_WORD_PATTERN}) or more cards this turn", re.I),
     lambda m: {"kind": "drawn_cards_at_least", "amount": number_value(m.group("n").lower())}),
    (re.compile(rf"an opponent has drawn (?P<n>{NUMBER_WORD_PATTERN}) or more cards this turn", re.I),
     lambda m: {"kind": "drawn_cards_at_least", "scope": "opponents",
                "amount": number_value(m.group("n").lower())}),
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
    # -- PAR-117 (conditional-wrapper residue): "if <effect>. if that
    # creature `<predicate>`, its controller `<verb>`." — "that creature" is
    # RULE 608.2h's own referent, the same `previous_target` `_ITS_
    # CONTROLLER_*` (`catalogue/handlers.py`) already reads for the paired
    # effect body; unambiguous here because a RULE 613.6 "as long as" static
    # has no earlier clause to refer back to, so this phrase can only ever
    # mean the resolving-effect referent.
    (re.compile(r"that creature is legendary", re.I),
     lambda m: {"kind": "is_legendary", "of": "previous_target"}),
    (re.compile(
        rf"that creature (?:was|is) (?P<c1>{'|'.join(COLOR_LETTERS)})"
        rf"(?: or (?P<c2>{'|'.join(COLOR_LETTERS)}))?",
        re.I,
    ), lambda m: _previous_target_color_condition(m)),
    # "if that creature wasn't dealt damage this turn" (Faller's Faithful).
    (re.compile(r"that creature wasn'?t dealt damage this turn", re.I),
     lambda m: {
         "kind": "not",
         "condition": {"kind": "was_dealt_damage_this_turn", "of": "previous_target"},
     }),
    # "if a/an `<type>` is destroyed this way" (Acolyte Hybrid) — the
    # already-shipped RULE 608.2 resolution tally (`GameContext.permanents_
    # destroyed_this_way`, ENG-37's `this_way` amount kind via `amount_
    # compare`) rather than re-reading `previous_target`: a "destroy up to
    # N" clause that chose zero targets leaves no referent to filter by card
    # type, but "this way" already means exactly "did the destroy happen".
    (re.compile(r"an? [a-z]+ is destroyed this way", re.I),
     lambda m: {
         "kind": "amount_compare",
         "left": {"kind": "this_way", "tally": "permanents_destroyed_this_way"},
         "right": {"kind": "fixed", "amount": 1},
         "op": "ge",
     }),
    # RULE 120.4a / 608.2: "if excess damage was dealt [to a permanent / that creature] this way" (Orbital Plunge,
    # Contest of Claws) -- this resolution's `excess_damage_this_way` tally is above 0. A qualifier names the damaged
    # object, which the tally already scopes (the clause before dealt damage to exactly that recipient).
    (re.compile(r"excess damage was dealt(?: to (?:a|that) (?:creature|permanent))? this way", re.I),
     lambda m: {
         "kind": "amount_compare",
         "left": {"kind": "this_way", "tally": "excess_damage_this_way"},
         "right": {"kind": "fixed", "amount": 1},
         "op": "ge",
     }),
    # PAR-120: "if you cast it[ from your hand]" — the "when ~ enters, if you
    # cast it, …" cluster (Crystalline Entity, Coal Stoker, …): "it" is the
    # trigger's own source (the entering permanent *is* "~" for this shape),
    # so the default ``of: "source"`` needs no operand. The "from your hand"
    # form is checked first so the plainer row below can't swallow it and
    # drop the stricter reading.
    (re.compile(r"you cast it from your hand", re.I),
     lambda m: {"kind": "flag", "flag": "was_cast_from_hand"}),
    # Addendum — the spell's own cast-time stamp (RULE 505.1).
    (re.compile(r"you cast this spell during your main phase", re.I),
     lambda m: {"kind": "flag", "flag": "cast_during_your_main_phase"}),
    (re.compile(r"you cast it", re.I),
     lambda m: {"kind": "flag", "flag": "was_cast"}),
    # PAR-283 / RULE 608.2h: "if the sacrificed creature was a Human" / "if the discarded card was a Zombie card" -- what a
    # *cost* sacrificed or discarded, as it was before it moved (`sacrificed_cost_is` / `discarded_cost_is`).
    (_COST_OBJECT_TYPE_RE, lambda m: _cost_object_condition(m)),
    (_COST_SACRIFICED_THIS_WAY_RE, lambda m: _cost_object_condition(m, verb="sacrificed", negated=False)),
    # PAR-120: "if it was/wasn't a `<type>`[ card]" — RULE 400.7 referent
    # state read off `previous_target` (an exiled/returned/destroyed card
    # this same resolution already named: Scavenging Ooze's exiled
    # graveyard card, Enduring Courage's own dying self, …). `is_card_type`/
    # `is_subtype` already read straight off the immutable `Card` reference
    # (`continuous._has_card_type`/`_has_subtype`), so this is safe even
    # once the object has left its original zone.
    # PAR-283 widened the one phrase to every characteristic word a referent may be asked about (`_referent_type_condition`):
    # a card type, supertype, token status or *any* creature/planeswalker subtype, in conjunction ("an artifact
    # creature", "a legendary enchantment") or disjunction ("a creature or planeswalker card"), for "it" and for
    # "that creature/permanent/card/spell/land/artifact".
    (_REFERENT_TYPE_RE, lambda m: _referent_type_condition(m)),
]


def _cost_object_condition(m: "re.Match[str]", verb: Optional[str] = None, negated: Optional[bool] = None) -> Optional[dict]:
    """"the sacrificed permanent was a Vehicle" → ``sacrificed_cost_is`` over the words (conjunction; "or" splits
    alternatives). A word outside the characteristic vocabulary fails the whole phrase closed."""
    kind = "sacrificed_cost_is" if (verb or m.group("verb")).lower() == "sacrificed" else "discarded_cost_is"
    alternatives: list[dict] = []
    for part in re.split(r" or ", m.group("words").lower()):
        words = [w for w in part.split() if w not in _TYPE_PHRASE_FILLER]
        if not words or any(w == "permanent" or _referent_word_condition(w) is None for w in words):
            return None
        alternatives.append({"kind": kind, "words": words})
    condition = alternatives[0] if len(alternatives) == 1 else {"kind": "any", "conditions": alternatives}
    if negated is None:
        negated = m.group("neg").lower() != "was"
    return {"kind": "not", "condition": condition} if negated else condition


def _x_condition(m: "re.Match[str]") -> dict:
    """"X is 5 or more" → ``x_paid`` with the matching bound (RULE 107.3c)."""
    n, direction = int(m.group("n")), (m.group("dir") or "").lower()
    if direction in ("more", "greater"):
        return {"kind": "x_paid", "min": n}
    if direction in ("less", "fewer"):
        return {"kind": "x_paid", "max": n}
    return {"kind": "x_paid", "min": n, "max": n}


#: The card types a referent test may name. "permanent" is not one: a "permanent card" is any card that is neither an
#: instant nor a sorcery (RULE 110.1), spelled out in `_referent_word_condition`.
_REFERENT_CARD_TYPES = frozenset({"artifact", "creature", "enchantment", "land", "planeswalker", "instant", "sorcery", "battle"})
#: Words that end a type phrase but name no characteristic ("a creature **card**", "a legendary **spell**").
_TYPE_PHRASE_FILLER = frozenset({"card", "spell"})


def _referent_word_condition(word: str) -> Optional[dict]:
    """One characteristic word of a referent test → its condition (``of`` left to the caller)."""
    if word in _REFERENT_CARD_TYPES:
        return {"kind": "is_card_type", "of": "previous_target", "card_type": word}
    if word == "permanent":
        # RULE 110.1: `is_card_type` "permanent" matches everything, so the card-only reading is the negation of the
        # two non-permanent types.
        return {"kind": "not", "condition": {"kind": "any", "conditions": [
            {"kind": "is_card_type", "of": "previous_target", "card_type": spell_type}
            for spell_type in ("instant", "sorcery")]}}
    if word == "legendary":
        return {"kind": "is_legendary", "of": "previous_target"}
    if word == "token":
        return {"kind": "is_token", "of": "previous_target"}
    if word in SUBTYPES:
        return {"kind": "is_subtype", "of": "previous_target", "subtype": word}
    return None


def _referent_type_condition(m: "re.Match[str]") -> Optional[dict]:
    """"it's an artifact creature" / "that creature was a Human" / "it was a creature or planeswalker card" →
    ``is_card_type`` / ``is_legendary`` / ``is_token`` / ``is_subtype`` over ``previous_target`` (RULE 205 / 608.2h).

    Words conjoin ("artifact creature" is both); "or" splits alternatives. Any word outside the vocabulary fails the
    whole phrase closed (``None``): a guessed filter that never matches is worse than an unclaimed clause."""
    if m.group(0).lower().startswith("it's ") and m.group("words").lower().split()[-1] in _TYPE_PHRASE_FILLER:
        # "it's a creature card" after a reveal/exile-the-top clause names the *library* card (BUG-68's `revealed` /
        # `created` referent), which the contraction-free rows above do not; leave it to that route.
        return None
    alternatives: list[dict] = []
    for part in re.split(r" or ", m.group("words").lower()):
        words = [w for w in part.split() if w not in _TYPE_PHRASE_FILLER]
        if not words:
            return None
        built = [_referent_word_condition(w) for w in words]
        if any(b is None for b in built):
            return None
        alternatives.append(built[0] if len(built) == 1 else {"kind": "all", "conditions": built})
    condition = alternatives[0] if len(alternatives) == 1 else {"kind": "any", "conditions": alternatives}
    if m.group(0).lower().startswith("it's "):
        # The present-tense contraction names the ability's own source in a standing clause ("as long as it's a Wall",
        # Mistform Wall) and is aimed at the earlier clause's pick by the caller where one exists ("target creature
        # gets +2/+2. If it's an artifact creature, …"): leave ``of`` off so both readings stay possible.
        condition = _without_referent(condition)
    return {"kind": "not", "condition": condition} if m.group("neg") else condition


def _without_referent(condition: dict) -> dict:
    """``condition`` with the explicit ``of: previous_target`` dropped, through the combinators."""
    if condition["kind"] in ("all", "any"):
        return {**condition, "conditions": [_without_referent(sub) for sub in condition["conditions"]]}
    if condition["kind"] == "not":
        return {**condition, "condition": _without_referent(condition["condition"])}
    return {key: value for key, value in condition.items() if key != "of"}


def _previous_target_color_condition(m: "re.Match[str]") -> dict:
    """"that creature was/is `<color>`[ or `<color2>`]" → `is_color`(s) of
    `previous_target`, OR-combined via the `any` combinator when a second
    colour is printed (Gloomlance's "green or white")."""
    colors = [_COLOR_CONDITION_WORDS[m.group("c1").lower()]]
    c2 = (m.groupdict().get("c2") or "").lower()
    if c2:
        colors.append(_COLOR_CONDITION_WORDS[c2])
    if len(colors) == 1:
        return {"kind": "is_color", "color": colors[0], "of": "previous_target"}
    return {
        "kind": "any",
        "conditions": [
            {"kind": "is_color", "color": c, "of": "previous_target"} for c in colors
        ],
    }

#: The characteristic words an "as long as `<attached subject>` is `<word>`"
#: condition may name — a card type, a colour, or a creature subtype, in that
#: precedence order. Deliberately closed: a word that is none of the three
#: (an ability word, a supertype) fails the whole clause closed rather than
#: becoming a subtype filter that silently never matches.
#: PAR-122: the combat/tap *states* an "as long as enchanted creature is `<state>`" condition
#: may name — RULE 508.1/509.1 designations and RULE 302.6 tapped-ness, read off the host.
#: Only the RULE 613.6 "as long as" wrapper reads these (`attached_state_condition`): its
#: pronoun rewrite ("it has …" → "enchanted creature has …") is what points the inner clause at
#: the host. A bare "tap it"/"untap it" under an intervening "if" would still act on the Aura.
_ATTACHED_STATE_KINDS: dict[str, str] = {
    "attacking": "source_attacking",
    "blocking": "source_blocking",
    "tapped": "source_tapped",
    "untapped": "source_untapped",
}
_ATTACHED_STATE_CONDITION_RE = re.compile(
    rf"(?:{ATTACHED_SUBJECT_PATTERN}) is (?P<state>{'|'.join(_ATTACHED_STATE_KINDS)})", re.I
)


def attached_state_condition(text: str) -> Optional[dict]:
    """"enchanted creature is attacking" → its ``active_if`` dict (`_ATTACHED_STATE_KINDS`)."""
    relation = re.fullmatch(rf"(?:{ATTACHED_SUBJECT_PATTERN})'s (?P<relation>.+)", text.strip().rstrip('.'))
    if relation and (comparison := parse_stat_relation(relation['relation'])):
        return {'kind': 'stat_relation', 'name': comparison, 'of': 'attached'}
    m = _ATTACHED_STATE_CONDITION_RE.fullmatch(text.strip().rstrip("."))
    if m is None:
        return None
    return {"kind": _ATTACHED_STATE_KINDS[m.group("state").lower()], "of": "attached"}


_PRONOUN_STATE_RE = re.compile(
    rf"it(?:'s| is) (?P<state>{'|'.join(_ATTACHED_STATE_KINDS)})", re.I
)


def pronoun_attached_condition(cond: str, subject: str) -> Optional[dict]:
    """"it's blocking [and `<more>`]" where "it" is the *attached* permanent (PAR-141).

    The grant clause ("enchanted creature has first strike as long as it's blocking and you control a
    snow land", Snow Devil) names the host, so a pronoun state in its condition reads the host, not the
    Aura — `static_condition` alone would read it off the source. Each "and" half resolves on its own;
    ``None`` (fail closed) unless at least one half is such a pronoun state.
    """
    halves = cond.strip().rstrip(".").split(" and ", 1)
    built: list[dict] = []
    pronoun = False
    for half in halves:
        m = _PRONOUN_STATE_RE.fullmatch(half.strip())
        if m is not None:
            pronoun = True
            part = attached_state_condition(f"{subject} is {m.group('state')}")
        else:
            part = static_condition(half)
        if part is None:
            return None
        built.append(part)
    if not pronoun:
        return None
    return built[0] if len(built) == 1 else {"kind": "all", "conditions": built}


def activation_attached_condition(text: str) -> Optional[dict]:
    """"enchanted creature is white and untapped" (Nature's Chosen, Earthlore) -> an activation gate over the host.

    PAR-176.  Only the *activation-condition* surface reads the host's tapped/attacking states: there the subject is
    spelled out, and the effect that follows never has a bare "it" that could be mistaken for the Aura.  The generic
    intervening-"if" surface must not (`_ATTACHED_STATE_KINDS`: "tap it" would tap the Aura, Narcolepsy).
    """
    m = re.fullmatch(rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}) is (?P<words>[a-z]+(?: and [a-z]+)?)",
                     text.strip().rstrip("."), re.I)
    if m is None:
        return None
    parts = []
    for word in m.group("words").split(" and "):
        reading = _attached_characteristic(word) or attached_state_condition(f"{m.group('subject')} is {word}")
        if reading is None:
            return None
        parts.append(reading)
    return parts[0] if len(parts) == 1 else {"kind": "all", "conditions": parts}


def _attached_characteristic(word: str) -> Optional[dict]:
    word = word.strip().lower()
    if word in CARD_TYPE_WORDS:
        return {"kind": "is_card_type", "card_type": word, "of": "attached"}
    if word in _COLOR_CONDITION_WORDS:
        return {"kind": "is_color", "color": _COLOR_CONDITION_WORDS[word], "of": "attached"}
    if word in CONDITION_SUBTYPE_WORDS:
        return {"kind": "is_subtype", "subtype": word, "of": "attached"}
    return None


#: RULE 105.1's five colours as an "…is red" condition would print them.
#: PAR-63: the shared map.
_COLOR_CONDITION_WORDS = COLOR_LETTERS

def _opponent_control_condition(what: str) -> Optional[dict]:
    """"An opponent controls a/an `<filter>`." (Ghostfire Slice's own
    `active_if`) — `opponent_count`'s sibling to the plain "you control
    a/an `<X>`" existence check, always ``min=1`` (a plain "controls a" has
    no count of its own to carry, unlike "controls N or more `<x>`").

    PAR-120: routes through the same shared `count_phrase` grammar as every
    other retired duplicate table — suffixing ``what`` with "you control"
    rather than leaving it bare matters here: `opponent_count`'s own
    evaluator (`static_conditions.py`) re-dispatches the selector once per
    opponent with *that opponent's* id as the controller, so the selector
    itself must read ``"of": "you"`` (resolved relative to whichever
    controller_id the caller passes) rather than the bare noun phrase's
    default ``"of": "any"`` (every player, unscoped) — the two only differ
    once there's more than one opponent at the table.
    """

    selector = parse_count_phrase(f"{what.strip()} you control")
    return None if selector is None else {
        "kind": "opponent_count", "selector": selector, "min": 1
    }


def _counter_kind(text: str) -> str:
    """A counter name as printed → the engine's own kind string."""
    text = text.strip().lower()
    return "+1/+1" if text in ("+1/+1", "+1/+1 ") else text


def _count_word(text: str) -> int:
    return 1 if text.strip().lower() in ("a", "an") else int(text)


#: "you control `<an X>` and `<an Y>`" — two single-object control counts.
_CONTROL_BOTH_RE = re.compile(
    r"you control (?P<left>an? [a-z ]+?) and (?P<right>an? [a-z ]+)", re.IGNORECASE
)


def static_condition(text: str) -> Optional[dict]:
    """A condition phrase ("~ is monstrous") → an ``active_if`` dict.

    ``None`` for anything outside the whitelist, which fails the *whole*
    clause closed rather than dropping the condition and applying the static
    unconditionally — a static that should be gated but isn't is strictly
    worse than an unmodeled card.
    """
    stripped = text.strip().rstrip(".").strip()
    # PAR-283 / RULE 102.1: outside a team game (RULE 810 two-headed play is a non-goal, `DEFERRED.md`) "your team" is
    # the controller alone, so "your team controls another Warrior" (Aurora Champion) reads as "you control …".
    stripped = re.sub(r"^your team controls\b", "you control", stripped)
    stripped = re.sub(r"^your team (gained|lost)\b", r"you \1", stripped)
    host_keyword = re.fullmatch(rf"(?:{ATTACHED_SUBJECT_PATTERN}) has (?P<keyword>.+)", stripped)
    if host_keyword and host_keyword['keyword'] in KEYWORD_WORDS:
        return {'kind': 'has_keyword', 'keyword': KEYWORD_WORDS[host_keyword['keyword']], 'of': 'attached'}
    relation = re.fullmatch(rf"(?P<who>~|{ATTACHED_SUBJECT_PATTERN})'s (?P<relation>.+)", stripped)
    if relation:
        comparison = parse_stat_relation(relation['relation'])
        if comparison:
            return {'kind': 'stat_relation', 'name': comparison,
                    'of': 'source' if relation['who'] == '~' else 'attached'}
    crew = re.fullmatch(r"an? (?P<quality>[a-z ]+) crewed (?:it|~) this turn", stripped)
    if crew is not None:
        parsed = parse_object_phrase(crew['quality'])
        if parsed is None or parsed[1] is not None or not parsed[0] or set(parsed[0]) - {'subtype', 'subtype_any'}:
            return None
        return {'kind': 'crewed_by_filter', 'selector': {'filter': parsed[0]}}
    for pattern, build in _STATIC_CONDITION_RES:
        if pattern.fullmatch(stripped):
            built = build(pattern.fullmatch(stripped))
            if built is not None:
                return built
            break  # the row matched but its table has no reading — no other row may claim it
    # PAR-120: a count comparison over the shared noun-phrase grammar ("you control
    # three or more gates", "there are seven or more creature cards in your
    # graveyard", "an opponent controls more lands than you"), tried only after the
    # named rows above declined.

    if stripped.startswith('~ ') and not re.search(r'\b(?:was|had)\b', stripped):
        source_condition = parse_referent_condition('it ' + stripped[2:])
        if source_condition is not None:
            return source_condition
    counted = parse_count_condition(stripped)
    if counted is not None:
        return counted
    # ENG-47: "… this turn" — a trigger head in the past tense, asked over the
    # turn-stamped event log (`event_this_turn`) instead of a tracker per phrase.

    single = parse_history_condition(stripped)
    if single is not None:
        return single
    # PAR-120: "`<condition A>` or `<condition B>`" (Desert's Hold and the
    # rest of the Amonkhet Desert-payoff cluster's "you control a desert or
    # there is a desert card in your graveyard") — tried only once every
    # single-condition reading above has declined, and only if BOTH halves
    # independently resolve through this same function: a non-disjunctive
    # "or" inside an already-claimed phrase ("total power 8 **or** greater")
    # never reaches here at all (a row above always claims the whole string
    # first), and a genuine non-disjunctive miss (an "or" that isn't a
    # condition-vocabulary split, e.g. inside an unrelated unmodeled phrase)
    # fails closed the same way a single unrecognized condition always has —
    # neither half resolves, so nothing is built. Splits on the *first* " or
    # " only: every cached instance of this shape is a two-way compound, and
    # a naive `str.split(" or ")` would wrongly fragment a right-hand
    # condition that itself contains the word (none does today, but the
    # narrower split costs nothing).
    # PAR-120: "you control an artifact and an enchantment" (Kami of Terrible
    # Secrets, Naomi, Okiba Salvage) — "you control" distributes over both
    # objects, so each half is its own control count and both must hold.
    both = _CONTROL_BOTH_RE.fullmatch(stripped)
    if both is not None:
        left_cond = parse_count_condition(f"you control {both.group('left')}")
        right_cond = parse_count_condition(f"you control {both.group('right')}")
        if left_cond is not None and right_cond is not None:
            return {"kind": "all", "conditions": [left_cond, right_cond]}
    if " or " in stripped:
        left, right = stripped.split(" or ", 1)
        left_cond = static_condition(left)
        right_cond = static_condition(right)
        if left_cond is not None and right_cond is not None:
            return {"kind": "any", "conditions": [left_cond, right_cond]}
    # PAR-141: "`<condition A>` and `<condition B>`" ("if you haven't cast a spell from your hand this
    # turn and ~ doesn't have a flying counter on it", Inventive Wingsmith) — the AND sibling of the
    # "or" split above, same discipline: only when BOTH halves independently resolve (an "and" inside a
    # phrase a named row already claims never reaches here), split on the first " and " only.
    if " and " in stripped:
        left, right = stripped.split(" and ", 1)
        left_cond = static_condition(left)
        # "you control no permanents other than ~ **and have** no cards in hand" (The Cheese Stands Alone, RULE 603.8): the
        # shared subject "you" is elided before the second verb.
        if right.startswith("have ") and left.startswith("you "):
            right = "you " + right
        right_cond = static_condition(right)
        if left_cond is not None and right_cond is not None:
            return {"kind": "all", "conditions": [left_cond, right_cond]}
    return None


#: "As long as <cond>, <static>." and "<static> as long as <cond>." The inner
#: clause is bounded away from a second "as long as" so a doubly-conditional
#: line fails closed instead of silently binding only the outer gate.
AS_LONG_AS_LEADING_RE = re.compile(
    r"(?:for )?as long as (?P<cond>[^,]+), (?P<inner>.+)", re.I
)
AS_LONG_AS_TRAILING_RE = re.compile(
    r"(?P<inner>.+?) (?:for )?as long as (?P<cond>(?!.*\bas long as\b)[^,]+)", re.I
)
