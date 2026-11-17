"""Segmenter: conditions (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import json
import re
from ..catalogue.clause_reading import ClauseReading, PLAYER, REVEALED, SELECTOR, STANDALONE, TARGET
from typing import Any, Optional
from ..catalogue.referent_condition import PRONOUN_NOUN_ALT, parse_referent_condition
from ..catalogue.static_handlers import static_condition
from ..catalogue.subgrammars import OTHER_TARGET_PART_RE
from ..spec import EffectSpec
from .trigger_heads import ADAMANT_MANA_SPENT_IF_RE, adamant_mana_spent_condition
from .activation_clauses import (
    ADDITIONAL_COST_NOT_PAID_SUFFIX_RE,
    ADDITIONAL_COST_PAID_CONDITION_RE,
    FIRST_SPELL_THIS_GAME_CONDITION_RE,
    GIFT_PROMISED_CONDITION_RE,
    KICKED_CONDITION_RE,
    LIFE_GAINED_THIS_TURN_CONDITION_RE,
    OPPONENT_LOST_LIFE_SUFFIX_RE,
    RESOLUTION_COUNT_PREFIX_RE,
    RESOLUTION_COUNT_SUFFIX_RE,
    TARGET_IS_CONTROLLER_RE,
    TEAMWORK_PAID_CONDITION_RE,
    stamp_distinct_from_others,
)
from .condition_riders import (
    COIN_FLIP_RESULT_RE,
    CONTROLS_NONE_OF_TYPE_CONDITION_RE,
    DIE_IF_RE,
    DIE_ON_A_RE,
    FIRST_COMBAT_PHASE_CONDITION_RE,
    GRAVEYARD_HAS_SUBTYPE_CONDITION_RE,
    IF_YOU_WIN_CLASH_RE,
    RING_BEARER_AND_TEMPTED_CONDITION_RE,
    RING_BEARER_OTHER_CONDITION_RE,
    WEREWOLF_NO_SPELLS_CONDITION_RE,
    WEREWOLF_TWO_SPELLS_CONDITION_RE,
    coin_flip_condition,
    die_result_condition,
    die_that_much_specs,
    resolution_count_condition,
)
from .keyword_and_trigger_conditions import ConditionPrefix, kicked_condition, rewrite_kicker_x
from .late import parse_effect_body

#: PAR-62 (`14_` S4): the generic RULE 603.4 gate. Every row above names one
#: printed phrasing; these two name the *shape* and hand the condition text to
#: `static_handlers.static_condition` — the same whitelisted recognizer the
#: RULE 613.6 "as long as" statics use, which returns a `game/static_
#: conditions.py` dict. One vocabulary for "is this true", read at both ends of
#: the pipeline, instead of a second table of effect-time conditions.
#:
#: A phrase outside that whitelist returns ``None`` and fails the body closed
#: (`peel_condition`), which is why these can sit last without over-claiming:
#: they only ever convert an *already-unclaimed* body into a gated one.
GENERIC_IF_PREFIX_RE = re.compile(
    r"^if (?P<cond>[^,]{2,160}),\s+(?P<rest>.+)$", re.IGNORECASE)
#: BUG-68, RULE 608.2c: a suffix gate qualifies only the clause it trails. The
#: lazy ``rest`` once swallowed whole earlier sentences ("A. If C, B." split at
#: the comma into "A. If C" + "B"), so C gated A and never B. ``rest`` therefore
#: may not contain a sentence boundary; a sentence that *starts* with "if" is
#: the prefix row's, gating its own clause.
_GENERIC_IF_SUFFIX_RE = re.compile(
    r"^(?P<rest>(?:(?!\.\s).)+?),?\s+if (?P<cond>[^,]{2,160})$", re.IGNORECASE)
#: "…unless `<x>`" is the same gate negated — ENG-36 added the ``not``
#: combinator to `static_conditions` for exactly this shape.
_GENERIC_UNLESS_PREFIX_RE = re.compile(
    r"^unless (?P<cond>[^,]{2,160}),\s+(?P<rest>.+)$", re.IGNORECASE)
_GENERIC_UNLESS_SUFFIX_RE = re.compile(
    r"^(?P<rest>.+?),?\s+unless (?P<cond>[^,]{2,160})$", re.IGNORECASE)


def _generic_condition(m: "re.Match[str]") -> "Optional[dict[str, Any]]":
    return static_condition(m.group("cond"))


def _generic_negated_condition(m: "re.Match[str]") -> "Optional[dict[str, Any]]":
    inner = static_condition(m.group("cond"))
    return None if inner is None else {"kind": "not", "condition": inner}


CONDITION_PREFIXES: tuple[ConditionPrefix, ...] = (
    # Adamant's spell-local payment fact is not a board-state phrase for the
    # generic condition grammar: it must be recognized before an effect body
    # can be claimed, so the rider never silently becomes unconditional.
    ConditionPrefix(ADAMANT_MANA_SPENT_IF_RE, adamant_mana_spent_condition),
    # "`<effect>` if an opponent lost N or more life this turn." (Davros,
    # Dalek Creator) — a suffix, but peeled here with the prefixes because it
    # gates the whole pre-split body.
    ConditionPrefix(
        OPPONENT_LOST_LIFE_SUFFIX_RE,
        lambda m: {"kind": "opponent_lost_life_this_turn", "min": int(m.group("n"))},
    ),
    ConditionPrefix(KICKED_CONDITION_RE, kicked_condition, rewrite_kicker_x),
    ConditionPrefix(
        ADDITIONAL_COST_PAID_CONDITION_RE,
        lambda m: {"kind": "flag", "flag": "additional_cost_paid"},
    ),
    ConditionPrefix(
        TEAMWORK_PAID_CONDITION_RE,
        lambda m: {"kind": "flag", "flag": "teamwork_paid"},
    ),
    ConditionPrefix(
        FIRST_SPELL_THIS_GAME_CONDITION_RE,
        lambda m: {"kind": "source_is_first_spell_cast_this_game"},
    ),
    ConditionPrefix(
        GIFT_PROMISED_CONDITION_RE,
        lambda m: (
            {"kind": "not", "condition": {"kind": "flag", "flag": "gift_promised"}}
            if m.group("neg").lower() != "was" else {"kind": "flag", "flag": "gift_promised"}
        ),
    ),
    # "If that player is[n't] you, `<effect>`." (The Ghoul, Gunslinger) — the
    # negative polarity is the ``not`` combinator, not a second predicate.
    ConditionPrefix(
        TARGET_IS_CONTROLLER_RE,
        lambda m: (
            {"kind": "not", "condition": {"kind": "is_you", "of": "target"}}
            if m.group("neg") else {"kind": "is_you", "of": "target"}
        ),
    ),
    # RULE 701.30d's two complementary clash branches.
    ConditionPrefix(IF_YOU_WIN_CLASH_RE, lambda m: {"kind": "clash_won"}),
    # RULE 705: the coin-flip counterpart.
    ConditionPrefix(COIN_FLIP_RESULT_RE, coin_flip_condition),
    # RULE 706: the die-roll counterpart (PAR-147).
    ConditionPrefix(DIE_IF_RE, die_result_condition, parse_rest=die_that_much_specs),
    ConditionPrefix(DIE_ON_A_RE, die_result_condition, parse_rest=die_that_much_specs),
    # RULE 119.3, Frodo, Adventurous Hobbit — carries a ``trailing`` group,
    # because "if A, effect1. Then if B, effect2." is two independently
    # gated sentences and the naive greedy read would gate both with A.
    ConditionPrefix(
        LIFE_GAINED_THIS_TURN_CONDITION_RE,
        lambda m: {"kind": "gained_life_this_turn", "amount": int(m.group("n"))},
    ),
    # "If you don't control a Food, …" (Butterbur, Bree Innkeeper).
    ConditionPrefix(
        CONTROLS_NONE_OF_TYPE_CONDITION_RE,
        lambda m: {
            "kind": "not",
            "condition": {
                "kind": "controls_subtype",
                "subtype": m.group("type").lower(),
                "min": 1,
            },
        },
    ),
    # "If there's a `<subtype>` card in your graveyard, …" (Walltop Sentries)
    # — the same predicate a static's ``active_if`` already used for the
    # standing version of this clause.
    ConditionPrefix(
        GRAVEYARD_HAS_SUBTYPE_CONDITION_RE,
        lambda m: {"kind": "subtype_in_graveyard", "subtype": m.group("sub").lower()},
    ),
    # The pre-daybound Innistrad werewolf day/night check — one quantity,
    # two bounds, where the flat vocabulary spelled two unrelated keys.
    ConditionPrefix(
        WEREWOLF_NO_SPELLS_CONDITION_RE,
        lambda m: {"kind": "spells_cast_last_turn", "max": 0},
    ),
    ConditionPrefix(
        WEREWOLF_TWO_SPELLS_CONDITION_RE,
        lambda m: {"kind": "spells_cast_last_turn", "min": 2},
    ),
    # RULE 603.4's textbook example, and every extra-combat grant's guard
    # against re-triggering itself in the phase it just made.
    ConditionPrefix(
        FIRST_COMBAT_PHASE_CONDITION_RE,
        lambda m: {"kind": "combats_this_turn", "max": 1},
    ),
    # RULE 701.52a's two printed Ring-bearer shapes: "a creature **other
    # than** ~" is the negation, and Frodo's compound "~ **is** your
    # Ring-bearer **and** the Ring has tempted you N or more times" is the
    # ``all`` combinator the flat form spelled as a two-key dict.
    ConditionPrefix(
        RING_BEARER_OTHER_CONDITION_RE,
        lambda m: {"kind": "not", "condition": {"kind": "is_ring_bearer"}},
    ),
    ConditionPrefix(
        RING_BEARER_AND_TEMPTED_CONDITION_RE,
        lambda m: {
            "kind": "all",
            "conditions": [
                {"kind": "is_ring_bearer"},
                {"kind": "ring_tempted", "min": int(m.group("n"))},
            ],
        },
    ),
)

#: Gates peeled **after** the connector split, so each binds to only its own
#: clause — see the call site for why that has to be a separate pass.
#: PAR-62's generic rows, kept in a table of their own because *where* they
#: run is the whole point. The specific `CONDITION_PREFIXES` rows are peeled
#: **before** `match_clause`, so a base handler can never claim a clause
#: without its gate. These cannot sit there: they match on shape rather than
#: on a printed phrase, so a body like "gain control of target creature …. if
#: that creature is a goat, it also gets +3/+0 …" (Goatnap) would be gated as
#: a whole on a condition outside the vocabulary and fail closed — losing the
#: connector split that used to claim it. Measured: 7 such cards regressed.
#:
#: Run last instead, after `match_clause` *and* the connector cascade, and
#: they are purely additive — the same placement rule the mid-body "you may"
#: node follows.
GENERIC_CONDITION_ROWS: tuple[ConditionPrefix, ...] = (
    ConditionPrefix(RESOLUTION_COUNT_PREFIX_RE, resolution_count_condition),
    ConditionPrefix(RESOLUTION_COUNT_SUFFIX_RE, resolution_count_condition),
    ConditionPrefix(GENERIC_IF_PREFIX_RE, _generic_condition),
    ConditionPrefix(_GENERIC_UNLESS_PREFIX_RE, _generic_negated_condition),
    ConditionPrefix(_GENERIC_IF_SUFFIX_RE, _generic_condition),
    ConditionPrefix(_GENERIC_UNLESS_SUFFIX_RE, _generic_negated_condition),
)


#: BUG-68: what a gated clause may still name -- the group ("untap those creatures") or library card
#: ("exile it") an earlier sentence produced, besides the picks/players the gate always carried.
GATED_REST_REFERENT_KINDS = (TARGET, PLAYER, SELECTOR, REVEALED)


CONDITION_SUFFIXES: tuple[ConditionPrefix, ...] = (
    # "`<effect>` unless `<its>` additional cost was paid." (Katara, Seeking
    # Revenge) — the negative of `ADDITIONAL_COST_PAID_CONDITION_RE`.
    ConditionPrefix(
        ADDITIONAL_COST_NOT_PAID_SUFFIX_RE,
        lambda m: {
            "kind": "not",
            "condition": {"kind": "flag", "flag": "additional_cost_paid"},
        },
    ),
)


#: A condition phrase whose subject is a bare pronoun — "**it** has flying", "**that creature**
#: was attacking", "**its** power is 3 or greater".
_PRONOUN_CONDITION_RE = re.compile(
    rf"^(?:it|its|that {PRONOUN_NOUN_ALT}|that spell(?:'s)?|you cast it)\b", re.IGNORECASE
)


def group_pronoun_condition(
    cond_text: str, condition: Optional[dict[str, Any]], *,
    reading: ClauseReading = STANDALONE,
) -> Optional[dict[str, Any]]:
    """PAR-123: a gate whose subject is "it" under a group trigger is a gate on the firing object.

    ``condition`` is what the shared vocabulary made of the phrase (or ``None``); a phrase it does
    not know is tried against the referent grammar (`parse_referent_condition`), and the result is
    scoped to the object that fired the trigger."""
    if condition is None and reading.self_subject and not reading.previous_subject and not reading.group_subject:
        if _PRONOUN_CONDITION_RE.match(cond_text) and not re.search(r'\b(?:was|had|were)\b', cond_text):
            return parse_referent_condition(cond_text)
    if (
        condition is None and reading.previous_subject and not reading.self_subject and not reading.group_subject
        and _PRONOUN_CONDITION_RE.match(cond_text) is not None
    ):
        # "destroy target … . If that permanent's mana value was 3 or less, …" (Carnivorous Canopy): the printed
        # mana value reads the same in any zone, so the gate survives the pick having just left the battlefield.
        # Power, toughness and keywords are last-known information (RULE 608.2h) the engine does not keep here.
        referent = parse_referent_condition(cond_text)
        if referent is not None and (referent.get('kind') == 'mana_value'
                or not re.search(r"\b(?:was|wasn't|had|didn't|were)\b", cond_text)):
            return referent
        return None
    library_card = next((r for r in reading.referents if r.kind == REVEALED), None)
    if (
        condition is None and library_card is not None and not reading.self_subject and not reading.previous_subject
        and not reading.group_subject and _PRONOUN_CONDITION_RE.match(cond_text) is not None
        and not re.search(r"\b(?:was|wasn't|had|didn't|were)\b", cond_text)
    ):
        # BUG-68, RULE 608.2c / 701.20: "exile the top card of target player's library. If it's a land card, ..."
        # -- "it" is the one library card the earlier sentence revealed or exiled, which `library_card.noun` names
        # as the engine referent (`revealed` / `created`), never the ability's source.
        referent = parse_referent_condition(cond_text)
        return None if referent is None else {**referent, "of": library_card.noun}
    if not reading.group_subject or reading.self_subject or reading.previous_subject or _PRONOUN_CONDITION_RE.match(cond_text) is None:
        return condition
    if condition is None:
        condition = parse_referent_condition(cond_text)
        if condition is not None and condition.get('kind') == 'source_counters' and re.search(r'\bhad\b', cond_text):
            return {**condition, 'kind': 'trigger_event_counters'}
    return None if condition is None else _rescope_to_trigger_subject(condition)

#: The condition kinds that talk about one object (the ``of`` referent), rather than the board or a
#: player — the ones "it"/"that creature" can be the subject of.
_SUBJECT_SCOPED_CONDITION_KINDS: frozenset[str] = frozenset({
    "source_tapped", "source_untapped", "source_attacking", "source_blocking", "source_counters",
    "source_attacked_this_turn", "is_card_type", "is_color", "is_subtype", "is_legendary", "is_basic", "is_token", "kicked",
    "was_dealt_damage_this_turn", "flag", "power", "toughness", "mana_value", "has_keyword",
    "source_monstrous", "source_equipped", "source_enchanted", "entered_this_turn", "source_prepared",
    "is_chosen_type", "crewed_by_filter",
})


def _rescope_to_trigger_subject(condition: dict[str, Any], of: str = "trigger_subject") -> dict[str, Any]:
    """PAR-123: a condition about "it" under a group trigger is about the object that fired it.

    The condition vocabulary reads the ability's own source unless told otherwise (or, for a few
    rows written for a pronoun after a targeting clause, ``previous_target``); under a group
    trigger that would be the Enchantment carrying the ability, not the creature that entered.
    ``trigger_subject`` is the firing object straight off the event, so a gate needs no seed.
    PAR-135: ``of="previous_target"`` is the same rescoping for "it" after a targeting clause
    ("choose target creature. If it's tapped, …" — Shackle Slinger), the pick an earlier clause made."""
    kind = condition.get("kind")
    if kind in ("all", "any"):
        return {**condition, "conditions": [
            _rescope_to_trigger_subject(sub, of) for sub in condition.get("conditions") or []
        ]}
    if kind == "not" and isinstance(condition.get("condition"), dict):
        return {**condition, "condition": _rescope_to_trigger_subject(condition["condition"], of)}
    if kind in _SUBJECT_SCOPED_CONDITION_KINDS and condition.get("of") in (None, "source", "previous_target"):
        return {**condition, "of": of}
    return condition


#: The pronoun-row condition kinds that have a source-scoped reading and a last-known (snapshot) one.
_SELF_PRONOUN_CHARACTERISTIC_KEYS: dict[str, str] = {
    "is_card_type": "card_type", "is_subtype": "subtype", "is_color": "color",
}


def _rescope_self_pronoun_condition(condition: dict[str, Any], *, past: bool) -> Optional[dict[str, Any]]:
    """A pronoun gate ("if it was a Demon") under a *self-subject* trigger → a condition that can hold.

    The shared rows build ``of: previous_target`` — right after a targeting clause, but a self trigger has no
    pick, so the gate never held and the card silently never acted (Weatherseed Totem, Infernal Vessel). Present
    tense ("if it's a creature") is the source itself; past tense ("if it was/wasn't …") asks what the source
    *was* — the death/leave event's last-known snapshot (`effect_conditions` ``trigger_event_object``, RULE
    603.10a). ``None`` (fail closed) for any other kind still naming ``previous_target``."""
    kind = condition.get("kind")
    if kind in ("all", "any"):
        subs = [_rescope_self_pronoun_condition(sub, past=past) for sub in condition.get("conditions") or []]
        return None if any(sub is None for sub in subs) else {**condition, "conditions": subs}
    if kind == "not" and isinstance(condition.get("condition"), dict):
        inner = _rescope_self_pronoun_condition(condition["condition"], past=past)
        return None if inner is None else {**condition, "condition": inner}
    if condition.get("of") != "previous_target":
        return condition
    key = _SELF_PRONOUN_CHARACTERISTIC_KEYS.get(str(kind))
    if key is None or key not in condition:
        return None
    if past:
        return {"kind": "trigger_event_object", key: condition[key]}
    return {k: v for k, v in condition.items() if k != "of"}


def peel_condition(
    body: str,
    table: tuple[ConditionPrefix, ...],
    *,
    reading: ClauseReading = STANDALONE,
) -> tuple[bool, Optional[list[EffectSpec]]]:
    """The one rule behind every row of ``table``.

    Returns ``(matched, specs)``. ``matched`` says a row claimed the body at
    all; ``specs`` is ``None`` when it did but the gated effect text came
    back unclaimed — which fails the whole body, because emitting the effect
    without its gate would be a *wrong* card rather than an unmodeled one.
    """
    for row in table:
        match = row.pattern.match(body)
        if match is None:
            continue
        inner = None
        # BUG-68, RULE 608.2c: in "A. If C, B." the gate C belongs to B alone, and B still reads what
        # A produced, so those referents ride along into the gated clause.
        rest_reading = ClauseReading(
            self_subject=reading.self_subject, referents=reading.referents_of(*GATED_REST_REFERENT_KINDS),
            group_subject=reading.group_subject)
        if row.parse_rest is not None:
            inner = row.parse_rest(match.group("rest"), reading=rest_reading)
        if inner is None:
            inner = parse_effect_body(match.group("rest"), reading=rest_reading)
        if inner is None:
            return True, None
        condition = row.build(match)
        condition = group_pronoun_condition(
            match.groupdict().get("cond") or "", condition, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(*GATED_REST_REFERENT_KINDS), group_subject=reading.group_subject),
        )
        if (
            condition is not None and reading.previous_subject and not reading.self_subject and not reading.group_subject
            and _PRONOUN_CONDITION_RE.match(match.groupdict().get("cond") or "") is not None
        ):
            # PAR-135: "it"/"that creature" after a clause that chose a target is that pick. The shared rows
            # read the ability's source unless they name a pick themselves, so "tap target creature. If it's
            # tapped, …" gated on the *source* being tapped — the wrong object, silently.
            condition = _rescope_to_trigger_subject(condition, "previous_target")
        if condition is not None and reading.self_subject and not reading.previous_subject and not reading.group_subject:
            # PAR-142: "when ~ dies, if it was a creature / wasn't a Demon, …" — "it" is the source, but these
            # pronoun rows read ``previous_target`` (a pick an earlier clause made), which no clause made here.
            condition = _rescope_self_pronoun_condition(
                condition, past=re.search(r"\b(?:was|wasn'?t|were|weren'?t)\b", match.groupdict().get("cond") or "") is not None,
            )
        if condition is None:
            # A row whose ``build`` couldn't resolve its condition phrase (the
            # generic rows below hand the phrase to the shared vocabulary, and
            # it isn't total). Claiming the body here would emit the effect
            # with no gate at all, which is the one outcome worse than leaving
            # the card unmodeled.
            return True, None
        gated: list[EffectSpec] = []
        for spec in inner:
            params = dict(spec.params)
            if (
                spec.type == "return_self_to_battlefield" and "target_kind" not in params
                and reading.previous_subject and not reading.self_subject and not reading.group_subject
            ):
                params["target_kind"] = "previous_target"  # "return it" after a clause that chose the pick
            if row.rewrite_params is not None:
                row.rewrite_params(params, match)
            # An inner spec that already carries a gate of its own ("if it was kicked, tap target artifact. If that
            # artifact is an Equipment, attach it to ~") keeps it: both must hold (RULE 608.2c), not the outer one alone.
            gated.append(EffectSpec(spec.type, params, condition=condition if spec.condition is None else {
                "kind": "all", "conditions": [condition, spec.condition]}))
        trailing = (match.groupdict().get("trailing") or "").strip().lstrip(". ").strip()
        if not trailing:
            return True, gated
        # A second sentence this match swallowed, with a gate of its own —
        # re-fold it through `parse_effect_body` so it gets that gate rather
        # than silently inheriting this one.
        more = parse_effect_body(
            trailing, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        return True, (gated + more if more is not None else None)
    return False, None


def with_after_tail(
    specs: list[EffectSpec], after_group: Optional[str], *,
    reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """The repeated tail shape across `parse_effect_body`'s two-sentence
    wrapper blocks below (look_top_select/no_regen/gain_control_tail/
    sac_when_you_do): a trailing "after" sentence, if any, recurses back
    into `parse_effect_body` and its specs are appended; with none, ``specs``
    is returned as-is. Fails closed (``None``) if the "after" sentence itself
    doesn't parse. ``group_subject`` carries forward unchanged (MEC-28) —
    unlike ``previous_subject``, the trigger's own group-subject scope
    doesn't shift between an ability's clauses."""
    after_text = (after_group or "").strip()
    if not after_text:
        return specs
    after_specs = parse_effect_body(
        after_text, reading=ClauseReading(referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
    )
    if after_specs is None:
        return None
    if specs and OTHER_TARGET_PART_RE.search(after_text):
        after_specs, _ = stamp_distinct_from_others(after_specs)  # ENG-52, as in the clause loop
    return specs + after_specs


#: MEC-118, RULE 115.1 / 601.2c: "target `<X>` **of an opponent's choice**" [+ "they control"].  The phrase only moves
#: *who picks* the target, so it is lifted out of the clause (the rest reads like the ordinary clause an existing row
#: already claims) and re-attached as ``target_chooser`` params on the specs that clause produced.
_OPPONENT_CHOICE_RE = re.compile(r" of an opponent's choice(?P<they> they control)?")
#: "target creature **of your choice**, then destroy target creature of an opponent's choice" (Diaochan): redundant
#: wording of the controller's own pick, dropped only next to an opponent's-choice phrase.
_OF_YOUR_CHOICE_RE = re.compile(r" of your choice(?=[,. ]|$)")
TARGET_WORD_RE = re.compile(r"\btarget\b")
#: Effect types that announce exactly one target per spec (the chooser phrase is matched to a spec by order of the
#: "target" words, so a type that may announce several -- or none -- would mis-assign it; anything else fails closed).
ONE_TARGET_EFFECT_TYPES = frozenset({"damage", "destroy", "gain_control_until_eot", "return_from_graveyard"})
#: The wording that replaces "they control" once the chooser phrase is lifted out (the opponent-controlled pool).
_OPPONENT_CONTROLS_TAIL = " an opponent controls"


def lift_opponent_choice(body: str) -> Optional[tuple[str, list[tuple[int, bool]]]]:
    """``body`` without its "of an opponent's choice" phrases, plus ``(target ordinal, they-control)`` for each.

    ``None`` when ``body`` has no such phrase.  The ordinal counts the "target" words before the phrase (0-based)."""
    if not _OPPONENT_CHOICE_RE.search(body):
        return None
    body = _OF_YOUR_CHOICE_RE.sub("", body)
    lifted: list[tuple[int, bool]] = []
    out: list[str] = []
    cursor = 0
    for match in _OPPONENT_CHOICE_RE.finditer(body):
        out.append(body[cursor:match.start()])
        ordinal = len(TARGET_WORD_RE.findall("".join(out))) - 1
        if ordinal < 0:
            return None
        lifted.append((ordinal, match.group("they") is not None))
        out.append(_OPPONENT_CONTROLS_TAIL if match.group("they") else "")
        cursor = match.end()
    out.append(body[cursor:])
    return "".join(out), lifted


#: Spec keys that hand the rest of the ability to a RULE 603.12 reflexive trigger: a payoff of its own with its own
#: targets (``then_trigger``), or the `reflexive_trigger` node.
_REFLEXIVE_MARKERS = ('"then_trigger"', '"reflexive_trigger"')


def opens_reflexive_trigger(spec: EffectSpec) -> bool:
    """Whether ``spec`` (a serialized effect, nested bodies included) puts a reflexive trigger on the stack."""
    return any(marker in json.dumps(spec.to_dict(), default=str) for marker in _REFLEXIVE_MARKERS)


#: "exile a creature card from your graveyard": a pick from the player's own graveyard, not a RULE 115 target.
OWN_GRAVEYARD_EXILE_RE = re.compile(
    r"exile (?:an?|\d+) (?:creature|artifact|enchantment|land|instant|sorcery|planeswalker) cards? from your graveyard"
)


def action_then_when_you_do(action_then: "re.Match[str]", reading: ClauseReading) -> Optional[list[EffectSpec]]:
    """"Exile target X. / Create a token. When you do, <effect>." -- the single exile/token antecedent whose own
    action carries the reflexive trigger (``then_trigger``); ``None`` when the clause is not that shape."""
    before_specs = parse_effect_body(
        action_then.group("before"),
        reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
    )
    after_text = action_then.group("after")
    condition = None
    if after_text.lower().startswith("if "):
        gate = GENERIC_IF_PREFIX_RE.match(after_text)
        condition = static_condition(gate.group("cond")) if gate else None
        if condition is None:
            return None
        after_text = gate.group("rest")
    after_specs = parse_effect_body(after_text)
    if not before_specs or len(before_specs) != 1 or before_specs[0].type not in {"exile", "create_token"} or not after_specs:
        return None
    params = dict(before_specs[0].params)
    # One action; multi-event/mass antecedents need
    # explicit batching semantics before exposing a reflexive body.
    if (params.get("count", 1) != 1 or params.get("count_selector")
            or params.get("selector") or params.get("group") or params.get("spell_or_permanent")
            or params.get("per_opponent") or params.get("creators", "you") not in {"you", "target"}):
        return None
    params["then_trigger"] = [spec.to_dict() for spec in after_specs]
    if condition is not None:
        params["then_trigger_condition"] = condition
    return [EffectSpec(before_specs[0].type, params)]
