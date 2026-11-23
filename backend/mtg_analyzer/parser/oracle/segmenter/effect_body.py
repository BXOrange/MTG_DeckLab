"""Segmenter: effect body (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from ..catalogue.combat_phrase import combat_tail
from ..catalogue.clause_reading import (
    COUNTERED,
    CREATED,
    ClauseReading,
    EXILE_POOL,
    PLAYER,
    MILLED,
    REVEALED,
    SELECTOR,
    STANDALONE,
    TARGET,
)
from dataclasses import replace
from ..catalogue.effect_rows.costs_mana_limits import MAY_COST_THEN_CLAUSE
from typing import Any, Optional
from ..catalogue.count_phrase import parse_amount_phrase
from ..catalogue.clause_primitives import (
    PLACEMENT_WITH_RIDERS,
    announces_creature_target,
    stamp_counters_on_referent,
)
from ..catalogue.flicker_sequences import (
    flicker_sequence_specs,
    linked_pool_return_specs,
    source_return_specs,
)
from ..catalogue.dying_hosts import dying_host_return_specs
from ..catalogue.amount_payments import amount_payment_specs
from ..catalogue.per_creature_payment import per_creature_payment_specs
from ..catalogue.physical_properties import physical_fight_specs
from ..catalogue.named_choice import named_choice_specs
from ..catalogue.target_groups import target_group_specs
from ..catalogue.quantifier_scope import PLAYER_SETS, per_member_amount_specs
from ..catalogue.object_phrase import conditional_object_specs
from ..catalogue import inspection as _inspection
from ..catalogue.name_reference import same_name_specs
from ..catalogue.zone_ability_sequences import exile_grant_specs
from ..catalogue.effect_rows.shared import ANY_NUMBER_TARGET_CAP
from ..catalogue.handlers import match_clause
from ..catalogue.static_handlers import static_condition
from ..catalogue.subgrammars import OTHER_TARGET_PART_RE
from ..spec import EffectSpec, ParserProvenance, TARGET_CHOOSER_OPPONENT
from .optional_peel import (
    MAY_HAVE_TARGET_GET_RE,
    MID_BODY_ITS_CONTROLLER_MAY_RE,
    MID_BODY_OPTIONAL_RE,
    PAY_ENERGY_THEN_PEEL_GUARD_RE,
    REFLEXIVE_TRIGGER_RE,
)
from .overrides_and_amounts import (
    DOUBLE_COUNTERS_RE,
    WINDOWED_POOLS,
    any_number_this_way_specs,
    created_tokens_have_ability_specs,
    created_tokens_have_cda_specs,
    destroy_target_counter_token_specs,
    for_each_specs,
    if_else_specs,
    instead_override_specs,
    led_instead_override_specs,
    this_way_sequences,
)
from .where_x import (
    PLAYER_SCOPE_SUBJECT_RE,
    WHERE_X_AMOUNT_RE,
    WHERE_X_CHARACTERISTIC_RE,
    WHERE_X_DIE_RE,
    WHERE_X_HALF_COUNT_RE,
    WHERE_X_RE,
    where_x_threshold_body,
    leading_for_each_flip_specs,
    leading_for_each_object_specs,
    per_member_attachment_specs,
    mana_value_count_bound_specs,
    multi_copy_tail,
    player_action_outcome_specs,
    player_scope_specs,
    referent_characteristic_specs,
    where_x_specs,
)
from .activation_clauses import (
    AND_CONNECTOR,
    CONNECTORS,
    ELIDED_AMOUNT_VERBS,
    ELIDED_PLAYER_VERB_RE,
    ELIDED_TARGET_LOSS_RE,
    MAX_SENTENCE_WINDOW,
    PRONOUN_COMMA_CONNECTOR,
    REFERENT_TRANSPARENT_TYPES,
    SENTENCE_CONNECTORS,
    SERIES_COMMA_CONNECTOR,
    elides_player_subject,
    split_effect_connector,
    splits_inside_gated_sentence,
    stamp_distinct_from_others,
    stamp_distinct_target_player,
    ANOTHER_TARGET_PLAYER_RE,
    stamp_previous_player,
)
from .condition_riders import (
    ANY_OPPONENT_MAY_HAVE_YOU_RE,
    CHOOSE_TARGET_IF_SUSPECTED_RE,
    CLASH_BOUNCE_OR_LIBRARY_RE,
    CLASH_REPEAT_PROCESS_RE,
    CREATED_ENTERS_ATTACKING_RE,
    DEFENDING_PLAYER_MAY_PAY_RE,
    defending_player_may_pay,
    DIE_TO_EXILE_SENTENCE_RE,
    GAIN_CONTROL_BARE_HASTE_RE,
    GAIN_CONTROL_HASTE_TAIL_RE,
    GIVE_CONTROL_IF_THEY_DO_RE,
    KEEP_MANA_SENTENCE_RE,
    KEEP_MANA_UNTIL,
    KICKED_MAGNITUDE_OVERRIDE_RE,
    LOOK_TOP_HIT_GRANT_KEYWORDS,
    LOOK_TOP_PUT_ATTACKING_RE,
    LOOK_TOP_SELECT_DESTINATIONS,
    LOOK_TOP_SELECT_RE,
    NO_REGEN_PLURAL_RE,
    NO_REGEN_SENTENCE_RE,
    NO_REGEN_THIS_WAY_RE,
    OPPONENT_MAY_HAVE_YOU_RE,
    OTHERWISE_RE,
    REGEN_EXILE_RIDER_RE,
    SPEND_MANA_SENTENCE_RE,
    any_opponent_may_have_you,
    count_destroys,
    last_destroy_denying_regeneration,
    otherwise_specs,
    punisher_choice,
    spend_mana_restriction,
)
from .cost_line_patterns import (
    ACTION_THEN_WHEN_YOU_DO_RE,
    CERTAIN_ANTECEDENT_ROWS,
    COUNTER_THEN_WHEN_YOU_DO_RE,
    EXILE_SELF_THEN_DELAYED_RETURN_RE,
    EXILE_THEN_COPY_SENTENCE_RE,
    EXILE_X_GY_FOR_EACH_CREATE_RE,
    FROM_AMONG_THEM_RE,
    GAIN_CONTROL_THEN_FORMER_DRAWS_RE,
    EXILE_SELF_THEN_WHEN_YOU_DO_RE,
    MAY_EXILE_SELF_THEN_WHEN_YOU_DO_RE,
    MILL_CHOOSE_FROM_MILLED_RE,
    MILL_LAND_THIS_WAY_RE,
    PREFIXED_DELAYED_SAC_EXILE_RE,
    PREFIXED_DELAYED_TAIL_RE,
    ROLL_DIE_THEN_WHEN_YOU_DO_RE,
    TAP_THEN_WHEN_YOU_DO_RE,
)
from .keyword_and_trigger_conditions import TURN_TRIGGER_RE
from .referents import (
    created_noun_to_pronoun,
    fold_counter_destination,
    for_as_long_as_counter_specs,
    produces,
    animates_source,
    puts_counter_on_source,
    referents_from,
    rewrite_optional_referent_actor,
    sequel_reading,
    stamp_created_pronouns,
)
from .pronoun_stamping import EVENT_READS, bind_attack_count
from .conditions import (
    CONDITION_PREFIXES,
    CONDITION_SUFFIXES,
    GATED_REST_REFERENT_KINDS,
    GENERIC_CONDITION_ROWS,
    GENERIC_IF_PREFIX_RE,
    ONE_TARGET_EFFECT_TYPES,
    OWN_GRAVEYARD_EXILE_RE,
    TARGET_WORD_RE,
    action_then_when_you_do,
    lift_opponent_choice,
    opens_reflexive_trigger,
    peel_condition,
    with_after_tail,
)
from .late import turn_trigger_segment
from .late import register


#: PAR-287: a conditional "you may <cost>" sentence ("If you control a Raccoon, you may discard a card.") and the
#: "If you do, <effect>" sentence that follows it (`effect_body`'s sentence loop pairs them).
GATED_MAY_PAY_RE = re.compile(r"^if [^,.]+, you may ", re.IGNORECASE)
IF_YOU_DO_SENTENCE_RE = re.compile(r"^if you do,", re.IGNORECASE)


def _adds_mana(spec: EffectSpec) -> bool:
    """Whether ``spec`` is an `add_mana` or a `bind` scaling one ("add {C} for each {S} spent", PAR-284)."""
    return spec.type == "add_mana" or (
        spec.type == "bind" and any(effect.get("type") == "add_mana" for effect in spec.params.get("effects", ()))
    )


def _tag_added_mana(spec: EffectSpec, key: str, value: Any) -> EffectSpec:
    """``spec`` with the property sentence's ``key`` set on the mana it adds (a `bind` carries it in its body)."""
    if spec.type == "add_mana":
        return EffectSpec(spec.type, {**spec.params, key: value}, condition=spec.condition)
    if spec.type == "bind" and _adds_mana(spec):
        effects = [
            {**effect, "params": {**effect["params"], key: value}} if effect.get("type") == "add_mana" else effect
            for effect in spec.params["effects"]
        ]
        return EffectSpec(spec.type, {**spec.params, "effects": effects}, condition=spec.condition)
    return spec

def _defender_after_choice(node: Any) -> Any:
    """``node`` (a spec dict tree) with every event-read defending player re-read off the attacker (RULE 506.4)."""
    if isinstance(node, dict):
        out = {k: _defender_after_choice(v) for k, v in node.items()}
        player = out.get("player")
        if isinstance(player, dict) and player.get("of") == "trigger_player" and "event_player_events" in node:
            out["player"] = {**player, "of": "defending_player"}
        return out
    if isinstance(node, list):
        return [_defender_after_choice(v) for v in node]
    return node


#: RULE 608.2h: "draw cards equal to the sacrificed creature's toughness, then discard cards equal to its power"
#: (Felothar the Steadfast) -- once a sentence has named "the sacrificed <noun>'s <stat>", a later "equal to its <stat>"
#: in the same body is that same sacrificed object's last-known information, not the ability source's own stat.
_SACRIFICED_NOUN_RE = re.compile(r"\bthe sacrificed (?P<noun>creature|permanent|artifact|land)'?s (?:power|toughness|mana value)")
_EQUAL_TO_ITS_STAT_RE = re.compile(r"\bequal to its (?P<stat>power|toughness|mana value)\b")


def name_sacrificed_object_pronoun(body: str) -> str:
    """Rewrite "equal to its <stat>" after an earlier "the sacrificed <noun>'s <stat>" to name the sacrificed object."""
    first = _SACRIFICED_NOUN_RE.search(body)
    if first is None:
        return body
    tail = _EQUAL_TO_ITS_STAT_RE.sub(
        lambda m: f"equal to the sacrificed {first.group('noun')}'s {m.group('stat')}", body[first.end():]
    )
    return body[: first.end()] + tail


def parse_effect_body(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """`_parse_effect_body_stamped`, then the "this way" window pass (`open_this_way_window`)."""
    specs = _parse_effect_body_stamped(body, reading=reading)
    return open_this_way_window(respell_effect_produced_referents(specs)) if specs else specs


def _parse_effect_body_stamped(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """`_parse_effect_body_unstamped`, then PAR-175's created-pronoun pass over the finished spec list (so a row that
    emits a whole multi-sentence sequence is covered exactly like the sentence-by-sentence loop)."""
    body = name_sacrificed_object_pronoun(body)
    payment = amount_payment_specs(body, lambda clause: match_clause(clause, reading=reading))
    if payment is not None:
        return payment
    threshold_matched, specs = where_x_threshold_body(body, reading=reading.unattached())
    if specs is None and threshold_matched:
        return None  # a "where X is …" threshold the whole-body row declined: X is not the announced X
    if specs is None:
        specs = _parse_effect_body_unstamped(body, reading=reading)
    def has_inspection(node):
        if isinstance(node, dict):
            return node.get("type") == "inspect_cards" or any(has_inspection(v) for v in node.values())
        if isinstance(node, list):
            return any(has_inspection(v) for v in node)
        return False
    if specs is None or has_inspection([e.to_dict() for e in specs]):
        inspection = _inspection.parse_inspection(body, lambda text: parse_effect_body(text, reading=reading))
        if inspection is not None or (_inspection.starts_inspection(body) and not _inspection.reads_revealed_amount(body)):
            specs = inspection
    if not specs:
        return specs
    return _bind_local_object_quantities(body, stamp_created_pronouns(specs))


#: MEC-145 / RULE 608.2c, 608.2h: "the discarded card's mana value" / "the power of the card you exiled" names what an
#: *earlier instruction of this same effect* moved when one is in the list (Spellbound Dragon's "draw a card, then discard
#: a card", Flesh // Blood's "exile target creature card from a graveyard"), and what the ability's *cost* moved otherwise.
#: The amount grammar reads both as a ``cost_referent_<kind>_<stat>`` selector; this pass respells the first reading as
#: the "<verb>ed this way" pool handle (`effect_amounts.this_way_sum`) that the effect itself fills, which
#: `open_this_way_window` then brackets. The cost reading stays for `gate._cost_referents_ok` to check against the cost.
_REFERENT_SELECTOR_RE = re.compile(r"^cost_referent_(?P<kind>discarded|exiled)_(?P<stat>mana_value|power|toughness)$")
_REFERENT_PRODUCERS: dict[str, str] = {"discard": "discarded", "exile": "exiled"}


def _respell_referent_amounts(node: Any, produced: set[str]) -> Any:
    if isinstance(node, dict):
        selector = node.get("selector")
        found = _REFERENT_SELECTOR_RE.match(selector) if node.get("kind") == "count_selector" and isinstance(selector, str) else None
        if found is not None and found.group("kind") in produced:
            return {"kind": "this_way_sum", "pool": found.group("kind"), "characteristic": found.group("stat")}
        return {key: _respell_referent_amounts(value, produced) for key, value in node.items()}
    if isinstance(node, list):
        return [_respell_referent_amounts(value, produced) for value in node]
    return node


def respell_effect_produced_referents(specs: "Optional[list[EffectSpec]]") -> "Optional[list[EffectSpec]]":
    """``specs`` with each referent amount that follows an instruction producing its object bound to the "this way" pool."""
    if not specs:
        return specs
    produced: set[str] = set()
    out: list[EffectSpec] = []
    for spec in specs:
        params = _respell_referent_amounts(spec.params, produced) if produced else spec.params
        out.append(EffectSpec(spec.type, params, spec.condition) if params is not spec.params else spec)
        for effect_type, verb in _REFERENT_PRODUCERS.items():
            if _contains_type(spec.to_dict(), effect_type):
                produced.add(verb)
    return out


#: PAR-284 (RULE 608.2c): the effect type that performs each windowed "<verb>ed this way" pool's instruction.
_WINDOW_PRODUCER_TYPES: dict[str, str] = {"discarded": "discard", "sacrificed": "sacrifice", "countered": "add_counters"}
_WINDOW_AMOUNT_KINDS = frozenset({"this_way_count", "this_way_sum", "this_way_max"})
#: PAR-287: the amount kind that measures the "countered" pool ("each of those creatures" after a counter-putting step).
_COUNTER_RECIPIENTS_KIND = "counter_recipients_since_mark"


def _windowed_pools(node: Any) -> set[str]:
    """The discard / sacrifice "this way" pools a spec dict tree measures (read from the `mark_event_log` window)."""
    if isinstance(node, dict):
        found = {node["pool"]} if node.get("kind") in _WINDOW_AMOUNT_KINDS and node.get("pool") in WINDOWED_POOLS else set()
        if node.get("kind") == _COUNTER_RECIPIENTS_KIND:
            found = {"countered"}
        return found.union(*(_windowed_pools(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(_windowed_pools(v) for v in node))
    return set()


def _contains_type(node: Any, effect_type: str) -> bool:
    """Whether a spec dict tree holds a (nested) spec of ``effect_type``."""
    if isinstance(node, dict):
        return node.get("type") == effect_type or any(_contains_type(v, effect_type) for v in node.values())
    if isinstance(node, list):
        return any(_contains_type(v, effect_type) for v in node)
    return False


def _performs_instruction(spec_dict: dict, pool: str) -> bool:
    """Whether the spec is, or (under "you may" / a "for each player" loop) wraps, the ``pool`` verb's instruction; a
    sacrifice never answers a "discarded this way" amount and vice versa."""
    return _contains_type(spec_dict, _WINDOW_PRODUCER_TYPES[pool])


def _pays_cost_of(spec: EffectSpec, pool: str) -> bool:
    """Whether ``spec`` is a "you may <discard / sacrifice>. If you do, ..." whose payment is the ``pool`` instruction."""
    cost = spec.params.get("cost")
    return spec.type == "pay_cost_then" and isinstance(cost, str) and cost.startswith(_WINDOW_PRODUCER_TYPES[pool])


def open_this_way_window(specs: list[EffectSpec]) -> list[EffectSpec]:
    """``specs`` with a `mark_event_log` in front of the first discard / sacrifice that precedes (or, for a paid
    "discard ... if you do", is) the effect measuring "<verb>ed this way" -- the amount reads the events logged since
    that mark. A measuring effect with no such instruction in the list is left as it is: the gate
    (`gate._this_way_window_ok`) refuses an ability that reads a window nothing opened."""
    dicts = [spec.to_dict() for spec in specs]
    pools_by_spec = [_windowed_pools(d) for d in dicts]
    if not any(pools_by_spec):
        return specs  # the common case: nothing measures a "this way" pool
    if _contains_type(dicts, "mark_event_log"):
        return specs  # a window is already open (here or inside a nested body's own pass)
    for at, spec in enumerate(specs):
        pools = sorted(pools_by_spec[at])
        if not pools:
            continue
        # The measured verb must be one the body itself performs ("sacrificed this way" after a discard is not).
        producers = [next((i for i in range(at) if _performs_instruction(dicts[i], pool)), at if _pays_cost_of(spec, pool) else None)
                     for pool in pools]
        if None in producers:
            return specs
        first = min(producers)
        return [*specs[:first], EffectSpec("mark_event_log", {}), *specs[first:]]
    return specs


def _bind_local_object_quantities(body: str, specs: list[EffectSpec]) -> list[EffectSpec]:
    """An object-list sacrifice supplies its own following 'that many', independently of a trigger."""
    if not re.search(r"\bthat (?:many|much)\b", body, re.I):
        return specs
    out: list[EffectSpec] = []
    producer = None
    for spec in specs:
        children = spec.params.get("effects", []) if spec.type == "for_each" else []
        if children and all(child.get("type") == "sacrifice_target" for child in children):
            producer = len(out)
        elif producer is not None and any(spec.params.get(key) == "amount" for key in EVENT_READS):
            bound = bind_attack_count([spec], {"kind": "this_way_count", "pool": "sacrificed"})
            if bound is not None:
                out.insert(producer, EffectSpec("mark_event_log", {}))
                out.extend(bound)
                producer = None
                continue
        out.append(spec)
    return out


def _parse_effect_body_unstamped(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """`_parse_effect_body_inner`, plus MEC-118's "target `<X>` of an opponent's choice": the phrase is lifted out,
    the plain clause parsed, and ``target_chooser`` stamped on the spec whose target it described (fail closed when
    the targets cannot be matched to specs one to one)."""
    named = same_name_specs(body.strip(), reading)
    if named is not None:
        return named
    designation = re.fullmatch(r"it becomes (?P<designation>day|night)\.?", body.strip())
    if designation is not None:
        return [EffectSpec("set_day_night", {"designation": designation.group("designation")})]
    flicker_sequence = flicker_sequence_specs(body, reading=ClauseReading(self_subject=reading.self_subject)) or linked_pool_return_specs(body) or source_return_specs(body)
    if flicker_sequence is not None:
        return flicker_sequence
    exile_grant = exile_grant_specs(body)
    if exile_grant is not None:
        return exile_grant
    physical_fight = physical_fight_specs(body)
    if physical_fight is not None:
        return physical_fight
    # MEC-131: "choose X target attacking creatures. For each of those creatures, its controller may pay {1} or {2}. ..."
    per_creature_payment = per_creature_payment_specs(body)
    if per_creature_payment is not None:
        return per_creature_payment
    # PAR-203: "choose a creature type/color/card name. <clauses naming the choice>" (RULE 608.2d).
    named_choice = named_choice_specs(body, lambda text: parse_effect_body(text, reading=reading))
    if named_choice is not None:
        return named_choice
    target_group = target_group_specs(body, lambda text: parse_effect_body(
        text, reading=reading.unattached(),
    ))
    if target_group is not None:
        return target_group
    # (PAR-175 M4b: the body-level `fight_sequence_specs` / `source_counter_fight_specs` call was retired -- the clause-level
    # call in `catalogue/handlers.match_clause` claims every one of those bodies, with the identical specs, for the whole
    # cache.)
    if reading.attached_subject:
        # RULE 400.7e: keep a dying host's conditional return riders atomic
        # before sentence/connector splitting can lose their shared referent.
        host_return = dying_host_return_specs(body)
        if host_return is not None:
            return host_return
    as_printed = _parse_effect_body_inner(
        body, reading=reading,
    )
    lifted = lift_opponent_choice(body)
    if as_printed is not None or lifted is None:
        # Resolve-time "of an opponent's choice" wordings ("a nonland card of an opponent's choice", Tasigur) are
        # claimed by their own rows and keep their meaning; only a body nothing else claims is lifted.
        return _fold_placement_tails(as_printed)
    plain, choosers = lifted
    specs = _parse_effect_body_inner(
        plain, reading=reading,
    )
    if specs is None:
        return None
    mentions = len(TARGET_WORD_RE.findall(plain))
    # One entry per announced target, in printed order: (carrier spec, that target's slot within the spec).
    slots: list[tuple[EffectSpec, int]] = []
    for spec in specs:
        if spec.type in ONE_TARGET_EFFECT_TYPES:
            if spec.params.get("count", 1) != 1:
                return None
            slots.append((spec, 0))
        elif spec.type == "fight" and spec.params.get("fighter_kind") and spec.params.get("other_kind"):
            slots.extend([(spec, 0), (spec, 1)])
    if len(slots) != mentions:
        return None
    stamped = list(specs)
    for ordinal, controls in choosers:
        carrier, slot = slots[ordinal]
        index = next(i for i, spec in enumerate(stamped) if spec is carrier)
        params = dict(stamped[index].params)
        params["target_chooser"] = TARGET_CHOOSER_OPPONENT
        if slot or carrier.type == "fight":
            params["target_chooser_slots"] = sorted({*params.get("target_chooser_slots", []), slot})
        if controls:
            params["target_chooser_controls"] = True
        stamped[index] = replace(stamped[index], params=params)
    return _fold_placement_tails(stamped)


#: PAR-152: a placement that waits on its controller's pick ("you may put a creature card from your hand onto the
#: battlefield tapped and attacking") parks the rest of the body until the pick is answered, so a following
#: "it"/"that creature" clause would resolve with no referent (and a delayed trigger would capture the source).
#: These specs about the placed card are carried *inside* the placement instead, as `placed_effects`, run once a
#: card was placed with that card as their referent. `{type: [params that make the spec a placed-card rider]}`.
_PLACED_CARD_RIDERS: dict[str, tuple[tuple[str, tuple[object, ...]], ...]] = {
    "pump": (("previous_subject", (True,)),),
    "add_counters": (("previous_subject", (True,)),),
    "grant_until": (("previous_subject", (True,)),),
    # ``self``: "if you do, convert ~ at end of combat" (Ultra Magnus) only happens when a card was placed.
    "create_delayed_trigger": (("capture", ("previous_or_self", "self")),),
}


#: The exact params of the untargeted "it gains haste until end of turn" pump that follows a linked move onto the battlefield.
_LINKED_MOVE_HASTE_RIDER_PARAMS = {"keywords": ["haste"]}


def _fold_rider_dicts(effects: list[dict]) -> list[dict]:
    """`_fold_placement_tails` over serialized ``{"type", "params"}`` effects (an ``optional`` wrapper's body)."""
    folded: list[dict] = []
    index = 0
    while index < len(effects):
        effect = effects[index]
        riders: list[dict] = []
        if (effect.get("type") == "linked_exile_move" and index + 1 < len(effects)
                and (effect.get("params") or {}).get("destination") == "battlefield"
                and effects[index + 1].get("type") == "pump"
                and effects[index + 1].get("params") == _LINKED_MOVE_HASTE_RIDER_PARAMS):
            # "Put a creature card exiled with ~ onto the battlefield … It gains haste until end of turn." (Yggdrasil,
            # Rebirth Engine): the bare haste pump's "it" is the card just moved (RULE 608.2c), not the ability's
            # source, so the haste rides the move and is granted to the entered card.
            folded.append({**effect, "params": {**effect["params"], "haste": True}})
            index += 2
            continue
        if effect.get("type") in PLACEMENT_WITH_RIDERS:
            for later in effects[index + 1:]:
                needs = _PLACED_CARD_RIDERS.get(later.get("type"))
                params = later.get("params") or {}
                if needs is None or not all(params.get(key) in values for key, values in needs):
                    break
                if effect.get("type") == "reveal_until" and later.get("type") == "create_delayed_trigger":
                    later = {**later, "params": {**params, "effects": [
                        {**child, "params": {**child.get("params", {}), "controlled_only": True}}
                        if child.get("type") == "sacrifice_specific" else child
                        for child in params.get("effects", [])]}}
                riders.append(later)
        if riders:
            params = dict(effect.get("params") or {})
            params["placed_effects"] = [*params.get("placed_effects", []), *riders]
            folded.append({**effect, "params": params})
            index += 1 + len(riders)
        else:
            folded.append(effect)
            index += 1
    return folded


def _fold_placement_tails(specs: Optional[list[EffectSpec]]) -> Optional[list[EffectSpec]]:
    if not specs:
        return specs
    as_dicts = [spec.to_dict() for spec in specs]
    # "You may put …. If you do, convert ~ at end of combat." is one ``optional`` whose body carries both.
    folded_dicts = []
    for d in _fold_rider_dicts(as_dicts):
        if d["type"] == "optional" and isinstance(d["params"].get("effects"), list):
            inner = _fold_rider_dicts(d["params"]["effects"])
            # The pick is itself optional (the player may place nothing), so a lone placement needs no second
            # "do you want to?" wrapper; "if you do" is carried by its ``placed_effects``.
            d = inner[0] if len(inner) == 1 and inner[0]["type"] in PLACEMENT_WITH_RIDERS else {
                **d, "params": {**d["params"], "effects": inner},
            }
        folded_dicts.append(d)
    if folded_dicts == as_dicts:
        return specs
    return [EffectSpec.from_dict(d) for d in folded_dicts]


def _parse_effect_body_inner(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """A normalised effect ``body`` → its `EffectSpec`s, or ``None`` if unclaimed.

    Tries the whole body as one clause first (so a target phrase containing
    "or"/"and" isn't split), then falls back to splitting on effect connectors
    and parsing each part. Any unclaimed part fails the whole body (fail-closed:
    a partially-modeled ability is never emitted).

    ``self_subject`` says a bare "it" in ``body`` means the ability's own
    source — true of a trigger whose *subject* is the source ("when ~ enters,
    it fights …"), which is what unlocks `effect_rows.shared.EffectHandler.
    self_subject_only` rows. It is deliberately **not** passed down into the
    connector-split parse below: once a body chains clauses, an earlier one
    may have introduced a new referent ("put a +1/+1 counter on target
    creature you control, then it fights …") — that reading is
    ``previous_subject``'s job instead, handed to each split part whose
    predecessor actually chose a creature (`announces_creature_target`), and
    unlocking `effect_rows.shared.EffectHandler.previous_subject_only` rows. The two
    flags are therefore never both set: a pronoun means the source or the
    last pick, never either-or.

    ``group_subject`` (MEC-28) says "it"/"that creature" means whichever
    object matched this ability's own RULE 603.1 group-subject trigger
    condition ("whenever a creature you control attacks alone, … untap
    **that creature**.") — unlocking `effect_rows.shared.EffectHandler.
    group_subject_only` rows. Unlike ``self_subject``, it *is* carried into
    every recursive call, including the connector-split parse below: the
    trigger's own subject scope is a fact about the whole ability, not a
    local referent that shifts clause to clause, so there's no equivalent
    of ``previous_subject`` recomputing it.

    A mass *selector* clause ("untap all attacking creatures") introduces a
    different kind of referent — "they" in a following clause ("**They**
    gain first strike until end of turn.", unlocking `handlers.
    EffectHandler.previous_selector_only` rows) — tracked by the
    connector-split loop below the same way ``previous_subject`` is
    (`_announces_group_selector`, resolved at runtime off `effects.
    GameContext.previous_selector` rather than a specific object list).

    ``attached_subject`` (PAR-117) says "its" means RULE 303.4/301.5's
    attached host — this ability's own trigger condition is ``{"subject":
    "attached_permanent"}`` ("whenever enchanted creature attacks or
    blocks, its controller loses N life."), unlocking `handlers.
    EffectHandler.attached_subject_only` rows. Like ``self_subject``, and for
    the same reason, it is **not** carried into the connector-split parse
    below: every cached card printing this shape is a single clause, so
    there is nothing yet to say what the pronoun should mean two clauses
    into a split body — left narrow rather than guessed.
    """
    body = body.strip().rstrip(".").strip()
    if not body:
        return []
    # RULE 701.20 / 121.2c: reveal as a group, measure the pool once,
    # then use normal APNAP draws and their resumable replacements.
    reveal_draw = re.fullmatch(
        r"each player reveals the top card of their library, then draws a card(?:\. (?P<after>.+))?", body,
    )
    if reveal_draw:
        draws = {"type": "for_each", "params": {"over": {"players": "each_player"},
                 "effects": [{"type": "draw", "params": {"count": 1, "target_kind": "player"}}]}}
        reveal = EffectSpec("reveal_top", {"whose": "each_player"})
        after = reveal_draw.group("after")
        if not after:
            return [reveal, EffectSpec(draws["type"], draws["params"])]
        payoff = parse_effect_body(after, reading=reading)
        if not payoff or len(payoff) != 1 or payoff[0].type != "bind":
            return None
        bound = payoff[0]
        if bound.params.get("amount", {}).get("pool") != "revealed":
            return None
        bound.params["effects"] = [draws, *bound.params["effects"]]
        return [reveal, bound]
    outcome = player_action_outcome_specs(body, reading)
    if outcome is not None:
        return outcome
    # RULE 608.2c: a coordinated permission inherits the source subject.
    permission_tail = re.fullmatch(
        r"(?P<before>~ [^.]+) and (?P<permission>can attack this turn as though it didn't have defender)", body,
    )
    if permission_tail is not None:
        before = parse_effect_body(permission_tail.group("before"), reading=reading)
        after = parse_effect_body("~ " + permission_tail.group("permission"), reading=reading)
        return before + after if before and after else None
    # RULE 608.2c: choosing the antecedent also chooses its combat-assignment rider.
    # Parse both operands with the same referent reading; targets belong to the
    # ability announcement even though applying the antecedent is optional.
    combat_rider = re.fullmatch(
        r"you may (?P<before>.+)\.\s*if you do, (?P<after>.+assigns no combat damage this turn)",
        body, re.I | re.S,
    )
    if combat_rider is not None and re.fullmatch(MAY_COST_THEN_CLAUSE, combat_rider.group("before")) is not None:
        # RULE 118.3 / 608.2c: a paid cost ("you may pay {R}. If you do, ...") is `pay_cost_then`'s antecedent, and its
        # payoff (with the trailing no-combat-damage rider) is parsed there, only once the cost has been paid.
        combat_rider = None
    if combat_rider is not None:
        after = parse_effect_body(combat_rider.group("after"), reading=reading)
        if not after or after[-1].type != "assign_no_combat_damage" or any(
                spec.type == "assign_no_combat_damage" for spec in after[:-1]):
            return None  # PAR-316: the payoff may carry its own effects ahead of the rider (Rysorian Badger's life)
        before_text = re.sub(r"^(?:choose to )?have (?=(?:it|~) deals? )", "", combat_rider.group("before"))
        before = parse_effect_body(before_text, reading=reading)
        if not before:
            return match_clause(body, reading=reading)
        return [EffectSpec("optional", {"effects": [s.to_dict() for s in before + after]})]
    # RULE 608.2c / 510.1e: "<effect> and ~ assigns no combat damage this turn" (Goblin Vandal, Rysorian Badger): the
    # trailing rider is the same self-subject clause the "you may X. If you do, ~ assigns no combat damage" form reads.
    # Both operands parse under the same reading; either failing leaves the clause unclaimed.
    assign_tail = re.fullmatch(r"(?P<before>[^.]+?) and (?P<after>(?:~|it) assigns no combat damage this turn)\.?", body, re.I | re.S)
    if assign_tail is not None:
        after = parse_effect_body(assign_tail.group("after"), reading=reading)
        if after is None or len(after) != 1 or after[0].type != "assign_no_combat_damage":
            return None
        before = parse_effect_body(assign_tail.group("before"), reading=reading)
        return before + after if before else None
    # RULE 608.2c / 510.1e: "you may have it assign no combat damage this turn. If you do, <effect>" (Cloak of
    # Confusion): the rider is the optional action itself, so choosing it and its payoff are one optional unit.
    rider_first = re.fullmatch(
        r"you may have (?P<who>it|~) assign no combat damage this turn\.\s*"
        r"if you do, (?P<after>.+)", body, re.I | re.S,
    )
    if rider_first is not None:
        rider = parse_effect_body(f"{rider_first.group('who')} assigns no combat damage this turn", reading=reading)
        payoff = parse_effect_body(rider_first.group("after"), reading=reading)
        if not rider or len(rider) != 1 or rider[0].type != "assign_no_combat_damage" or not payoff:
            return None
        # The payoff runs after the optional choice, when the combat event is no longer live: "defending player" then
        # reads the attacker's own combat_defender (`defending_player`) instead of the event's (`trigger_player`).
        return [EffectSpec("optional", {"effects": [_defender_after_choice(s.to_dict()) for s in rider + payoff]})]
    # Preserve the existing hand-cheat package before placement-tail folding.
    # Its choice already owns haste and the delayed sacrifice (MEC-73).
    if "that creature gains haste until end of turn" in body:
        packaged = match_clause(body, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER)), )
        if packaged and len(packaged) == 1 and packaged[0].type == "cheat_creature_from_hand":
            return packaged
    # "you may **have** target creature get -2/-2 until end of turn" (Blightcaster, Battle-Rattle Shaman, the
    # cycling trio, Painsmith, …): "have … get" is only how the optional wording carries the verb — the effect is
    # "target creature gets -2/-2", which every pump / keyword-grant row already reads.
    body = MAY_HAVE_TARGET_GET_RE.sub(r"\g<1>\g<2> \g<3>s ", body)
    # Choosing explicit targets here is the announcement's ordinary group;
    # the counter placement acts on every member (RULE 115.1a).
    body = re.sub(
        r"choose (?P<targets>any number of target [^.]+?) and put (?P<counter>an? [a-z]+ counter) on each of them",
        r"put \g<counter> on each of \g<targets>", body, flags=re.I,
    )
    # RULE 608.2c: optional causative animation uses the same subject and
    # verb as ordinary animation; leave "you may" for the optional wrapper.
    body = re.sub(
        r"\b(you may )?have (it|target land(?: you control)?) become (?=an? \d+/\d+ )",
        r"\1\2 becomes ", body, flags=re.IGNORECASE,
    )

    # "destroy target nonbasic land you don't control and target nonbasic land you don't control." (Volcanic Offering):
    # one verb over two target phrases is two destroy instructions, in printed order (RULE 115.1).  One sentence only:
    # a rider after it ("They can't be regenerated.", Plague Spores) would attach to just the second instruction.
    destroy_pair = re.fullmatch(r"destroy (?P<a>target [^.]+?) and (?P<b>target [^.]+)", body, re.IGNORECASE)
    if destroy_pair is not None:
        first = parse_effect_body(f"destroy {destroy_pair.group('a')}")
        second = parse_effect_body(f"destroy {destroy_pair.group('b')}")
        if first and second and len(first) == len(second) == 1:
            return first + second
        return None

    # PAR-285 (RULE 115.3, 109.5): "destroy target artifact or enchantment and up to 1 other target artifact or
    # enchantment." (Relic Crush) -- the one verb carries a second requirement that must be a different object than the
    # first. Each half parses as its own single-target instruction; the second is stamped `distinct_from_others`
    # (ENG-52) so the engine drops what the first requirement chose. One sentence only, like the pair above.
    verb_other_pair = re.fullmatch(
        r"(?P<verb>destroy|exile|tap|untap) (?P<a>target [^.]+?) and "
        r"(?P<b>(?:up to (?:one|1|two|2) )?(?:another|other) target [^.]+)",
        body, re.IGNORECASE,
    )
    if verb_other_pair is not None:
        verb = verb_other_pair.group("verb")
        first = parse_effect_body(f"{verb} {verb_other_pair.group('a')}")
        second = parse_effect_body(f"{verb} {verb_other_pair.group('b')}")
        if first and second and len(first) == len(second) == 1:
            second, distinct = stamp_distinct_from_others(second)
            if distinct:
                return first + second
        return None

    # PAR-130: a per-player target announcement followed by the clause(s)
    # acting on "that/those/the chosen" objects. The generic connector split
    # cannot discover the first half because the per-player wrapper used to
    # expect the whole body to be one effect; split this printed boundary,
    # retain the announced targets as the following clause's referent, and
    # fail closed unless both halves independently parse.
    per_player_choose = re.fullmatch(
        r"(?P<choose>for each (?:opponent|player), choose (?:up to 1 )?"
        r"(?:another |other )?target .+? that player controls)"
        r"(?:\.|,\s*then)\s*(?P<after>.+)",
        body, re.IGNORECASE | re.DOTALL,
    )
    if per_player_choose is not None:
        before_specs = parse_effect_body(per_player_choose.group("choose"))
        if not before_specs or not all(spec.type == "choose_targets" for spec in before_specs):
            return None
        after_specs = parse_effect_body(
            per_player_choose.group("after"), reading=ClauseReading(previous_subject=True, group_subject=reading.group_subject),
        )
        if after_specs is None:
            return None
        return before_specs + after_specs

    # "…, whenever `<event>` this turn, `<effect>`" as one sentence of a larger body — after an
    # "if C," gate or a first sentence — creates the same turn-long trigger a whole line does.
    if TURN_TRIGGER_RE.match(body):
        turn_trigger = turn_trigger_segment(
            body, provenance=ParserProvenance(), reading=ClauseReading(referents=reading.referents_of(TARGET, PLAYER)),
        )
        if turn_trigger is not None and turn_trigger.claimed and turn_trigger.spec is not None:
            return list(turn_trigger.spec.effects)

    return_then = re.fullmatch(r"(?P<before>return .+?)\. if you do, (?P<after>.+)", body, re.I | re.S)
    if return_then is not None:
        before_specs = parse_effect_body(return_then.group("before"), reading=ClauseReading(self_subject=reading.self_subject))
        after_specs = parse_effect_body(return_then.group("after"), reading=ClauseReading(self_subject=reading.self_subject))
        if (before_specs is None or after_specs is None or len(before_specs) != 1
                or before_specs[0].type != "return_to_hand"):
            return None
        params = dict(before_specs[0].params)
        params["then_specs"] = [spec.to_dict() for spec in after_specs]
        return [EffectSpec("return_to_hand", params)]

    # An activated ability's sacrifice cost is paid before its effects resolve
    # (RULE 602.2b).  Keep both mutually-exclusive draw counts explicit: the
    # card does not draw one and then a further two when the sacrificed
    # creature was suspected.
    if re.fullmatch(
        r"draw a card\. if the sacrificed creature was suspected, draw 2 cards instead",
        body,
        re.IGNORECASE,
    ):
        return [
            EffectSpec("draw", {"count": 1}, condition={"sacrificed_cost_was_suspected": False}),
            EffectSpec("draw", {"count": 2}, condition={"sacrificed_cost_was_suspected": True}),
        ]

    # Lamplight Phoenix — the whole optional reflexive sequence is one
    # atomic action.  It cannot be split at "and"/"if you do": exile and
    # collect evidence must both happen before the card returns.
    lamplight = re.fullmatch(
        r"exile (?:it|~) and collect evidence (?P<n>\d+)\. if you do, "
        r"return this card to the battlefield(?P<tapped> tapped)?",
        body,
        re.IGNORECASE,
    )
    if lamplight is not None:
        return [EffectSpec("exile_self_collect_evidence_return", {
            "amount": int(lamplight.group("n")), "tapped": bool(lamplight.group("tapped")),
        })]

    # Primetime Suspect — both branches are the same optional library search,
    # but the Aura host's suspected state changes its cardinality.  This is
    # deliberately kept to the complete printed search sentence; a general
    # "instead" rewrite would be unsafe around asynchronous searches.
    if re.fullmatch(
        r"search your library for a land card, put that card onto the battlefield tapped, "
        r"then shuffle\. if enchanted creature is suspected, you search for 2 lands instead",
        body,
        re.IGNORECASE,
    ):
        return [
            EffectSpec(
                "search", {"criteria": {"type": "land"}, "destination": "battlefield_tapped"},
                condition={"attached_is_suspected": False},
            ),
            EffectSpec(
                "search", {"criteria": {"type": "land"}, "destination": "battlefield_tapped", "count": 2},
                condition={"attached_is_suspected": True},
            ),
        ]

    # RULE 603.4 intervening-ifs, and RULE 601.2b's optional-additional-cost
    # gates: one rule over `CONDITION_PREFIXES` (ENG-36), where each of these
    # was its own ten-line block. They run before `match_clause` / the
    # connector split so a base `<effect>` handler can never claim the clause
    # *without* its gate — a wrong-but-modeled unconditional card is worse
    # than an unclaimed one.
    conditional_object = conditional_object_specs(body, reading, parse_effect_body)
    if conditional_object is not None:
        return conditional_object
    matched, peeled = peel_condition(
        body, CONDITION_PREFIXES, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(*GATED_REST_REFERENT_KINDS), group_subject=reading.group_subject, attached_subject=reading.attached_subject),
    )
    if matched:
        return peeled

    clash_repeat = CLASH_REPEAT_PROCESS_RE.match(body)
    if clash_repeat is not None:
        process = parse_effect_body(clash_repeat.group("process"), reading=ClauseReading(self_subject=reading.self_subject))
        if process is None:
            return None
        inner = [e.to_dict() for e in process] + [{"type": "clash", "params": {}}]
        return [EffectSpec("repeat_process", {"effects": inner, "repeat_while": "clash_won"})]

    clash_bounce_lib = CLASH_BOUNCE_OR_LIBRARY_RE.match(body)
    if clash_bounce_lib is not None:
        return [
            EffectSpec("clash", {}),
            EffectSpec("return_to_hand", {
                "target_kind": "creature", "to_library_top_if_clash_won": True,
            }),
        ]

    if CHOOSE_TARGET_IF_SUSPECTED_RE.match(body) is not None:
        # PAR-30 (Agrus Kos, Spirit of Justice) — RULE 701.60c if/else over
        # the chosen creature's suspected state. The exile branch carries the
        # RULE 115 target; the "otherwise" branch reads it back as the
        # previous subject (`effects.ConditionalEffect._condition_holds`'s
        # ``previous_target_is_suspected`` key). Exile leaves ``is_suspected``
        # set on the old object reference (RULE 400.7), so the complementary
        # branch still evaluates `True` and stays skipped.
        return [
            EffectSpec(
                "exile", {"target_kind": "creature", "count": 1, "optional": True},
                condition={"previous_target_is_suspected": True},
            ),
            EffectSpec(
                "suspect", {"previous_subject": True},
                condition={"previous_target_is_suspected": False},
            ),
        ]

    look_top_select = LOOK_TOP_SELECT_RE.match(body)
    if look_top_select is not None:
        if (look_top_select.group("removed") or look_top_select.group("measured")) and look_top_select.group("n") != "x":
            return None
        measured = None
        if look_top_select.group("measured"):
            selector = parse_amount_phrase(look_top_select.group("measured"))
            if selector is None:
                return None
            measured = {"kind": "count_selector", "selector": selector}
        rest_destination, rest_order = LOOK_TOP_SELECT_DESTINATIONS[
            look_top_select.group("dest").lower()
        ]
        spec = EffectSpec(
            "look_top_select",
            {
                "count": ({"kind": "counters_removed_as_cost", "of": "source", "counter": look_top_select.group("removed")}
                          if look_top_select.group("removed") else
                          measured if measured is not None else
                          "x" if look_top_select.group("n") == "x" else int(look_top_select.group("n"))),
                "select_count": int(look_top_select.group("m")),
                "rest_destination": rest_destination,
                "rest_order": rest_order,
            },
        )
        return with_after_tail([spec], look_top_select.group("after"), reading=ClauseReading(group_subject=reading.group_subject))

    look_put_atk = LOOK_TOP_PUT_ATTACKING_RE.match(body)
    if look_put_atk is not None:
        words = look_put_atk.group("filter").split()
        criteria: Optional[dict] = None
        if words == ["creature"]:
            criteria = {"type": "creature"}
        elif len(words) == 2 and words[1] == "creature":
            # "human creature card" / "cat creature card" — a creature
            # subtype filter (a substring match on the type line).
            criteria = {"type": words[0]}
        if criteria is not None:
            params: dict[str, Any] = {
                "count": int(look_put_atk.group("n")),
                "criteria": criteria,
                "hit_destination": "battlefield_attacking",
                "miss_destination": "library_bottom_random",
                "optional": True,
            }
            hitkw_raw = (look_put_atk.group("hitkw") or "").strip()
            if hitkw_raw:
                slugs: list[str] = []
                for tok in re.split(r",|\band\b", hitkw_raw):
                    tok = tok.strip()
                    if not tok:
                        continue
                    if tok not in LOOK_TOP_HIT_GRANT_KEYWORDS:
                        return None  # unknown keyword — fail closed
                    slugs.append(LOOK_TOP_HIT_GRANT_KEYWORDS[tok])
                if not slugs:
                    return None
                params["hit_grant_keywords"] = slugs
            elsebody = (look_put_atk.group("elsebody") or "").strip()
            if elsebody:
                else_specs = parse_effect_body(elsebody)
                if else_specs is None:
                    return None  # else-branch didn't parse — fail closed
                params["miss_effect_specs"] = [s.to_dict() for s in else_specs]
            spec = EffectSpec("impulsive_look", params)
            return with_after_tail(
                [spec], look_put_atk.group("after"), reading=ClauseReading(group_subject=reading.group_subject)
            )

    enters_atk = CREATED_ENTERS_ATTACKING_RE.match(body)
    if enters_atk is not None:
        before_specs = parse_effect_body(
            enters_atk.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        name_subj = (enters_atk.group("name_subj") or "").strip().lower()
        # ``create_named_legendary_token`` emits a plain ``create_token``
        # spec (with ``token_name``/``legendary``), so it's covered here too.
        _STAMPABLE = ("create_token", "copy_permanent", "populate")
        if before_specs is not None:
            for i in range(len(before_specs) - 1, -1, -1):
                if before_specs[i].type not in _STAMPABLE:
                    continue
                # A bare-name subject only binds the spec that actually made
                # a token by that name (RULE 700 — no other referent). A
                # pronoun subject binds the last token-maker, as before.
                if name_subj:
                    tok_name = str(before_specs[i].params.get("token_name") or "").lower()
                    if tok_name != name_subj:
                        continue
                flagged = dict(before_specs[i].params)
                flagged["tapped"] = True
                flagged["attacking"] = True
                before_specs[i] = EffectSpec(
                    before_specs[i].type, flagged, condition=before_specs[i].condition
                )
                return with_after_tail(
                    before_specs, enters_atk.group("after"), reading=ClauseReading(group_subject=reading.group_subject)
                )
        # regex matched but nothing stampable — fall through, fail closed

    spend_mana = SPEND_MANA_SENTENCE_RE.match(body)
    if spend_mana is not None:
        restriction = spend_mana_restriction(spend_mana.group("what"))
        before_specs = parse_effect_body(
            spend_mana.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        ) if restriction is not None else None
        if before_specs is None or not any(_adds_mana(spec) for spec in before_specs):
            return None
        before_specs = [_tag_added_mana(spec, "restriction", dict(restriction)) for spec in before_specs]
        return with_after_tail(
            before_specs, spend_mana.group("after"), reading=ClauseReading(referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )

    keep_mana = KEEP_MANA_SENTENCE_RE.match(body)
    if keep_mana is not None:
        before_specs = parse_effect_body(
            keep_mana.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        if before_specs is None or not any(_adds_mana(spec) for spec in before_specs):
            return None
        keep = KEEP_MANA_UNTIL[keep_mana.group("until").lower()]
        before_specs = [_tag_added_mana(spec, "keep_until", keep) for spec in before_specs]
        return with_after_tail(
            before_specs, keep_mana.group("after"), reading=ClauseReading(referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )

    no_regen = NO_REGEN_SENTENCE_RE.match(body)
    if no_regen is not None:
        # RULE 701.19c: the rider qualifies only the immediately preceding destruction,
        # never an earlier independent sentence or a later destruction this turn.
        before_text = no_regen.group("before")
        if '"' in before_text:
            return None
        boundary = before_text.rfind(". ")
        prefix = before_text[:boundary] if boundary >= 0 else ""
        immediate = before_text[boundary + 2:] if boundary >= 0 else before_text
        for certain_re, _antecedent in CERTAIN_ANTECEDENT_ROWS:
            # RULE 608.2c: "sacrifice it. If you do, destroy target creature. It can't be regenerated." (Necrite) --
            # the certain antecedent's "if you do" is only the sequence's connective, so the destruction the rider
            # qualifies is the payoff sentence itself.
            certain = certain_re.match(before_text)
            if certain is not None:
                immediate = certain.group("after")
                break
        before_specs = parse_effect_body(before_text, reading=reading)
        if not before_specs:
            return None
        immediate_specs = parse_effect_body(immediate, reading=reading)
        if immediate_specs is None:
            return None  # A trailing conditional may require the earlier cost's antecedent.
        def _is_destroy(spec: EffectSpec) -> bool:
            # A group trigger's "destroy it" sits in the firing-object wrapper's body; a composed target or group
            # operand ("destroy target Wall") ends in its destroy inside seq / for_each wrappers.
            return last_destroy_denying_regeneration(spec.to_dict()) is not None

        def _is_marker(spec: EffectSpec) -> bool:
            # The bare firing-object marker a group trigger puts before "destroy it".
            return spec.type == "trigger_subject_referent" and not spec.params.get("effects")

        immediate_specs = [spec for spec in immediate_specs if not _is_marker(spec)]
        if not immediate_specs or not all(_is_destroy(spec) for spec in immediate_specs):
            return None
        # A shared verb over several objects produces several adjacent destroy nodes.
        # Reject any intervening effect instead of searching backwards across it.
        end = len(before_specs)
        start = end
        while start > end - len(immediate_specs) and _is_destroy(before_specs[start - 1]):
            start -= 1
        if start == end:
            return None
        who = no_regen.group("who")
        if not NO_REGEN_PLURAL_RE.match(who):
            start = end - 1
        if NO_REGEN_THIS_WAY_RE.search(who) and count_destroys([s.to_dict() for s in before_specs]) != count_destroys(
                [s.to_dict() for s in before_specs[start:]]):
            return None  # "destroyed this way" names the one destruction of this resolution; two would be ambiguous

        def _deny_regeneration(spec: EffectSpec) -> EffectSpec:
            flagged = last_destroy_denying_regeneration(spec.to_dict())
            return EffectSpec(spec.type, flagged["params"], condition=spec.condition)

        before_specs = [_deny_regeneration(spec) if i >= start else spec for i, spec in enumerate(before_specs)]
        return with_after_tail(
            before_specs, no_regen.group("after"),
            reading=reading.but(previous_subject=announces_creature_target(before_specs)),
        )

    regen_exile = REGEN_EXILE_RIDER_RE.match(body.strip())
    if regen_exile is not None:
        before_specs = parse_effect_body(
            regen_exile.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        if not before_specs or not any(spec.type == "damage" for spec in before_specs):
            return None
        creature_gate = regen_exile.group("gate").lower().startswith("it")
        gate = None if creature_gate else static_condition(regen_exile.group("gate"))
        if not creature_gate and gate is None:
            return None
        riders = [
            EffectSpec("cant_be_regenerated", {"damaged_this_way": True}, condition=gate),
            EffectSpec("grant_die_to_exile_this_turn", {
                "damaged_this_way": True, "creature_only": True,
            }, condition=gate),
        ]
        return before_specs + riders
    die_to_exile = DIE_TO_EXILE_SENTENCE_RE.match(body)
    if die_to_exile is not None:
        before_specs = parse_effect_body(
            die_to_exile.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        if before_specs is None:
            return None
        # MEC-81: a "before" clause that *dealt damage* — single target, "any
        # target", or mass ("to each creature") — arms the rider on the
        # actual hit set (`GameContext.damaged_this_way`), the referent that
        # covers the mass/multi-hit case `previous_subject` could not name.
        # Otherwise the rider only qualifies a creature/permanent the "before"
        # clause already *targeted* (Bleed Dry's "-13/-13", the fight forms) —
        # `previous_subject` off `previous_targets`; anything else fails closed.
        # MEC-145: a measured "where X is ..." damage clause wraps its damage in a `bind`; it still deals the damage.
        if any(s.type == "damage" or (s.type == "bind" and _contains_type(s.to_dict(), "damage")) for s in before_specs):
            rider = EffectSpec("grant_die_to_exile_this_turn", {"damaged_this_way": True})
        elif announces_creature_target(before_specs):
            rider = EffectSpec("grant_die_to_exile_this_turn", {"previous_subject": True})
        else:
            return None
        return with_after_tail(
            before_specs + [rider],
            die_to_exile.group("after"),
            reading=ClauseReading(previous_subject=announces_creature_target(before_specs), group_subject=reading.group_subject),
        )

    kicked_mag = KICKED_MAGNITUDE_OVERRIDE_RE.match(body)
    if kicked_mag is not None:
        before_specs = parse_effect_body(
            kicked_mag.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        if before_specs is None:
            return None
        bargained = kicked_mag.group("cost").lower() == "bargained"
        key_p = "power_if_bargained" if bargained else "power_if_kicked"
        key_t = "toughness_if_bargained" if bargained else "toughness_if_kicked"
        p2, t2 = int(kicked_mag.group("p")), int(kicked_mag.group("t"))
        for i in range(len(before_specs) - 1, -1, -1):
            spec = before_specs[i]
            if spec.type == "pump" and ("power" in spec.params or "toughness" in spec.params):
                flagged = dict(spec.params)
                flagged[key_p] = p2
                flagged[key_t] = t2
                before_specs[i] = EffectSpec("pump", flagged, condition=spec.condition)
                return before_specs
        return None  # no pump magnitude to override — fail closed

    give_if_they_do = GIVE_CONTROL_IF_THEY_DO_RE.match(body)
    if give_if_they_do is not None:
        give_specs = parse_effect_body(give_if_they_do.group("give"), reading=ClauseReading(self_subject=reading.self_subject))
        rider_specs = parse_effect_body(
            give_if_they_do.group("rider"), reading=ClauseReading(self_subject=reading.self_subject),
        )
        if (not give_specs or [spec.type for spec in give_specs] != ["give_control"] or not rider_specs
                or re.search(r"\btarget\b", give_if_they_do.group("rider"))  # a gated rider would announce up front
                or any(spec.condition is not None for spec in rider_specs)):
            return None  # fail closed: only a lone donation can be the antecedent, and a rider keeps one gate
        return give_specs + [
            EffectSpec(spec.type, dict(spec.params), condition={"kind": "control_changed_this_way"})
            for spec in rider_specs
        ]

    punisher = OPPONENT_MAY_HAVE_YOU_RE.match(body)
    if punisher is not None:
        return punisher_choice(punisher, reading)

    defender_pays = DEFENDING_PLAYER_MAY_PAY_RE.match(body)
    if defender_pays is not None:
        return defending_player_may_pay(defender_pays, reading)

    any_opponent = ANY_OPPONENT_MAY_HAVE_YOU_RE.match(body)
    if any_opponent is not None:
        return any_opponent_may_have_you(any_opponent)

    gain_then_former_draws = GAIN_CONTROL_THEN_FORMER_DRAWS_RE.match(body)
    if gain_then_former_draws is not None:
        gain_specs = parse_effect_body(gain_then_former_draws.group("before"), reading=ClauseReading())
        if (not gain_specs or [spec.type for spec in gain_specs] != ["gain_control_until_eot"]
                or gain_specs[0].params.get("duration") != "permanent" or gain_specs[0].condition is not None):
            return None  # only the indefinite steal has a former controller who stays that way
        count = 1 if gain_then_former_draws.group("count").lower() == "a" else int(gain_then_former_draws.group("count"))
        return gain_specs + [EffectSpec(
            "draw", {"count": count, "player": {"of": "former_controller"}},
            condition={"kind": "control_changed_this_way"},
        )]

    gain_control_tail = GAIN_CONTROL_HASTE_TAIL_RE.match(body)
    if gain_control_tail is not None:
        # Preserve a whole-clause handler's existing target-count semantics
        # before decomposing a richer rider through the shared grammar.
        whole = match_clause(body, reading=reading)
        if whole is not None:
            return whole
        before_specs = parse_effect_body(
            gain_control_tail.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        if before_specs is None or not any(
            spec.type == "gain_control_until_eot"
            # PAR-324: the pronoun form ("gain control of that creature ...") reads the earlier object through a
            # previous-subject referent wrapper around the same effect.
            or (spec.type == "trigger_subject_referent" and spec.params.get("referent") == "previous_subject"
                and any(e.get("type") == "gain_control_until_eot" for e in spec.params.get("effects") or []))
            for spec in before_specs
        ):
            return None  # fail closed — the tail only makes sense after that clause
        prev = announces_creature_target(before_specs)
        grant_text = (gain_control_tail.group("grant") or "").strip()
        grant_specs: list[EffectSpec] = []
        if grant_text and not GAIN_CONTROL_BARE_HASTE_RE.match(grant_text):
            # A *richer* restatement than bare haste ("it gains trample and
            # haste until end of turn") — model the extra grant against the
            # just-controlled creature (`previous_subject`), fail closed if
            # it isn't something we can represent.
            grant_specs = parse_effect_body(grant_text, reading=ClauseReading(previous_subject=prev)) or []
            if not grant_specs:
                return None
        return with_after_tail(
            before_specs + grant_specs, gain_control_tail.group("after"),
            reading=ClauseReading(previous_subject=prev, group_subject=reading.group_subject),
        )

    for certain_re, antecedent_type in CERTAIN_ANTECEDENT_ROWS:
        certain = certain_re.match(body)
        if certain is None:
            continue
        before_specs = parse_effect_body(
            certain.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        if before_specs is None or not any(spec.type == antecedent_type for spec in before_specs):
            return None  # fail closed — only a certain, unconditional antecedent collapses
        return with_after_tail(before_specs, certain.group("after"), reading=ClauseReading(group_subject=reading.group_subject))

    exile_self_then = EXILE_SELF_THEN_WHEN_YOU_DO_RE.match(body)
    if exile_self_then is not None:
        if not reading.self_subject:
            return None  # "it" is the source only when the body's subject is ~ (a dies trigger)
        after_specs = parse_effect_body(exile_self_then.group("after"), reading=ClauseReading(self_subject=reading.self_subject))
        if not after_specs:
            return None
        return [EffectSpec("may_exile_source_then", {"then_trigger": [s.to_dict() for s in after_specs], "required": True})]

    exile_self_delayed_return = EXILE_SELF_THEN_DELAYED_RETURN_RE.match(body)
    if exile_self_delayed_return is not None:
        before_specs = parse_effect_body(
            exile_self_delayed_return.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        if before_specs is None or not any(spec.type == "exile" for spec in before_specs):
            return None  # fail closed — only a certain, unconditional antecedent collapses
        return [
            EffectSpec("exile", {**before_specs[0].params, "remember": True}),
            EffectSpec("create_delayed_trigger", {
                "step": "end", "scope": "any",
                "effects": [{"type": "return_linked_exile", "params": {"destination": "battlefield"}}],
            }),
        ]

    action_then = ACTION_THEN_WHEN_YOU_DO_RE.match(body)
    if action_then is not None:
        before_text = action_then.group("before")
        if before_text.startswith("exile ") and not re.search(r"\btarget\b", before_text):
            before_specs = parse_effect_body(
                before_text, reading=ClauseReading(self_subject=reading.self_subject),
            )
            if not before_specs or (
                before_specs[0].type == "exile" and not OWN_GRAVEYARD_EXILE_RE.fullmatch(before_text)
            ):
                return None  # nontargeted exile choices must be made during resolution
            # PAR-207: another action ("exile 2 cards from your graveyard", "exile a creature card from your
            # graveyard" -- the player's own pick) is the general reflexive row's.
        else:
            claimed = action_then_when_you_do(action_then, reading)
            if claimed is not None:
                return claimed
            # PAR-207: whatever this exile/token-only row declines falls through to the general reflexive row
            # (`effect_rows.costs_mana_limits._action_when_you_do`) instead of failing the whole body closed.

    may_exile_self_then = MAY_EXILE_SELF_THEN_WHEN_YOU_DO_RE.match(body)
    if may_exile_self_then is not None:
        if not reading.self_subject:
            return None  # "it" is the source only when the body's subject is ~ (a dies trigger)
        after_specs = parse_effect_body(may_exile_self_then.group("after"), reading=ClauseReading(self_subject=reading.self_subject))
        if not after_specs:
            return None
        return [EffectSpec("may_exile_source_then", {"then_trigger": [s.to_dict() for s in after_specs]})]

    roll_when_you_do = ROLL_DIE_THEN_WHEN_YOU_DO_RE.match(body)
    if roll_when_you_do is not None:
        before_specs = parse_effect_body(
            roll_when_you_do.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        after_specs = parse_effect_body(
            roll_when_you_do.group("after"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        if (before_specs is None or len(before_specs) != 1
                or before_specs[0].type != "roll_die" or after_specs is None):
            return None
        params = dict(before_specs[0].params)
        params["then_trigger"] = [spec.to_dict() for spec in after_specs]
        return [EffectSpec("roll_die", params)]

    # PAR-79 eighth increment: a delayed sacrifice/exile/return clause
    # (`effect_rows.pump_stats._DELAYED_SAC_EXILE_WHEN_FIRST_RE`) preceded by an unrelated
    # earlier sentence of the *same* ability — the Alora, Cheerful `<X>`
    # cycle's own "whenever you attack, up to 1 target attacking creature
    # can't be blocked this turn. at the beginning of the next end step,
    # return that creature to its owner's hand[. if you do, `<effect>`]."
    # Every existing "certain antecedent" collapse above (`_SACRIFICE_THEN_
    # WHEN_YOU_DO_RE` et al.) is anchored at the *start* of ``body`` because
    # every real card using those shapes prints the collapse as the whole
    # ability body — Alora's own first sentence (an ordinary RULE 115
    # target pick, already claimed fine by `unblockable`) breaks that
    # assumption, so this dispatch instead finds the delayed clause
    # wherever it sits and recursively parses the leading sentence(s) in
    # front of it, rather than widening any of the anchored checks above to
    # a shape they were never meant to match.
    prefixed_delayed = PREFIXED_DELAYED_SAC_EXILE_RE.match(body)
    if prefixed_delayed is not None:
        before_specs = parse_effect_body(
            prefixed_delayed.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        if before_specs is None:
            return None
        delayed_specs = match_clause(prefixed_delayed.group("delayed"))
        if delayed_specs is None:
            return None
        if any(opens_reflexive_trigger(spec) for spec in before_specs):
            return None  # PAR-207: "it" would be the reflexive trigger's object, which this chain cannot name
        return before_specs + delayed_specs

    prefixed_delayed_tail = PREFIXED_DELAYED_TAIL_RE.match(body)
    if prefixed_delayed_tail is not None:
        before_specs = parse_effect_body(
            prefixed_delayed_tail.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        delayed_specs = match_clause(prefixed_delayed_tail.group("delayed"))
        # Fall through (rather than fail closed) when this split doesn't
        # parse: the shape is loose enough to catch a multi-sentence body
        # another row owns whole (Incandescent Soulstoke's "…onto the
        # battlefield. That creature gains haste until end of turn. Sacrifice
        # it at the beginning of the next end step.").
        if before_specs is not None and delayed_specs is not None:
            if any(opens_reflexive_trigger(spec) for spec in before_specs):
                return None  # PAR-207: as above -- the delayed "it" is the reflexive trigger's object
            return before_specs + delayed_specs

    mill_land_this_way = MILL_LAND_THIS_WAY_RE.match(body)
    if mill_land_this_way is not None:
        before_specs = parse_effect_body(mill_land_this_way.group("before"))
        branches = re.split(r"\.\s*otherwise,?\s+", mill_land_this_way.group("after"), maxsplit=1)
        after_specs = parse_effect_body(branches[0], reading=ClauseReading(self_subject=reading.self_subject))
        if before_specs is None or after_specs is None or not any(s.type == "mill" for s in before_specs):
            return None
        if len(branches) > 1:
            otherwise = parse_effect_body(branches[1], reading=ClauseReading(self_subject=reading.self_subject))
            if otherwise is None:
                return None
            return before_specs + [EffectSpec("if_else", {
                "condition": {"kind": "milled_land_this_way"},
                "then": [s.to_dict() for s in after_specs],
                "else": [s.to_dict() for s in otherwise],
            })]
        return before_specs + [
            EffectSpec(s.type, dict(s.params), condition={"kind": "milled_land_this_way"})
            for s in after_specs
        ]

    mill_choose = MILL_CHOOSE_FROM_MILLED_RE.match(body)
    if mill_choose is not None:
        before_specs = parse_effect_body(mill_choose.group("before"))
        choice_specs = parse_effect_body(mill_choose.group("choice"))
        # "if you do" may name the picked card ("that card"); "if you don't" has no pick to name.
        after_specs = parse_effect_body(mill_choose.group("after"), reading=ClauseReading(
            self_subject=reading.self_subject, previous_subject=mill_choose.group("branch").lower() == "do",
        ))
        if before_specs is None or choice_specs is None or after_specs is None:
            return None
        loop_body = before_specs[0].params.get("effects") if before_specs[0].type == "for_each" else None
        if len(before_specs) != 1 or not (
            before_specs[0].type == "mill"
            or (loop_body and all(e.get("type") == "mill" for e in loop_body))
        ):
            return None
        if len(choice_specs) != 1 or choice_specs[0].type != "choose_objects" or (
            choice_specs[0].params.get("pool_zone") != "milled"
        ):
            return None
        pick = choice_specs[0]
        after_dicts = [s.to_dict() for s in after_specs]
        if mill_choose.group("branch").lower() == "do":
            pick.params["then"] = list(pick.params.get("then") or []) + after_dicts
        else:
            pick.params["else_effects"] = after_dicts
        return before_specs + [pick]

    counter_when_you_do = COUNTER_THEN_WHEN_YOU_DO_RE.match(body)
    if counter_when_you_do is not None:
        before_specs = parse_effect_body(counter_when_you_do.group("before"), reading=ClauseReading(self_subject=True))
        after_specs = parse_effect_body(counter_when_you_do.group("after"), reading=ClauseReading(self_subject=True))
        if before_specs is None or after_specs is None:
            return None
        return before_specs + after_specs

    tap_when_you_do = TAP_THEN_WHEN_YOU_DO_RE.match(body)
    if tap_when_you_do is not None:
        before_specs = parse_effect_body(tap_when_you_do.group("before"))
        after_specs = parse_effect_body(tap_when_you_do.group("after"))
        if before_specs is None or after_specs is None:
            return None
        # RULE 603.12: "When you do" is a *reflexive trigger* — it exists only
        # if the tap actually happened, and its graveyard target is chosen when
        # it goes on the stack. `choose_objects`' ``then`` runs only once a pick
        # was made, so the trigger rides there instead of following the tap as
        # an unconditional sibling effect.
        if len(before_specs) != 1 or before_specs[0].type != "choose_objects":
            return None
        return [EffectSpec("choose_objects", {
            **before_specs[0].params,
            "then": [EffectSpec("reflexive_trigger", {
                "then_trigger": [s.to_dict() for s in after_specs],
            }).to_dict()],
        })]

    # RULE 608.2h / 707.2: recipients and copiable values are captured
    # before the exile instruction changes the target's zone identity.
    shared_copy = re.fullmatch(
        r"(?P<exile>exile target [^.]+)\. each player other than its controller "
        r"creates a token that's a copy of it\.?", body, re.I)
    if shared_copy:
        specs = parse_effect_body(shared_copy.group("exile"), reading=reading)
        if specs is None or len(specs) != 1 or specs[0].type != "exile":
            return None
        return [EffectSpec("exile", {**specs[0].params, "copy_for_other_players": True})]

    multi_copy = re.fullmatch(
        r"choose (?P<count>x|\d+|any number of) target (?P<group>creatures(?: (?:you control|your opponents control))?)\. "
        r"for each of them, (?P<copy>create a token that's a copy of that creature(?:, except [^.]+)?)"
        r"(?P<after>\..*)?", body, re.I)
    if multi_copy:
        kinds = {"creatures": "creature", "creatures you control": "creature_you_control",
                 "creatures your opponents control": "creature_you_dont_control"}
        copies = parse_effect_body(multi_copy.group("copy"), reading=ClauseReading(previous_subject=True))
        if not copies or len(copies) != 1 or copies[0].type != "copy_permanent":
            return None
        count = multi_copy.group("count")
        params = {**copies[0].params, "target_kind": kinds[multi_copy.group("group")],
                  "target_count": ANY_NUMBER_TARGET_CAP if count in ("x", "any number of") else int(count)}
        params.pop("referent", None)
        if count == "x":
            params["target_count_selector"] = "source_x_paid"
        if count == "any number of":
            params["target_optional"] = True
        specs = [EffectSpec("copy_permanent", params)]
        after = (multi_copy.group("after") or "").lstrip(". ")
        if after:
            return multi_copy_tail(specs, after)
        return specs

    exile_then_copy = EXILE_THEN_COPY_SENTENCE_RE.match(body)
    if exile_then_copy is not None:
        before_text = exile_then_copy.group("before").strip()
        # "You may exile …" (God-Pharaoh's Gift, Séance) — the optionality
        # lives on the exile; peel it and re-fold it as ``optional`` so the
        # inner clause reaches `_exile_from_graveyard` (which has no "you
        # may" grammar of its own).
        optional_exile = bool(re.match(r"(?i)^you may ", before_text))
        if optional_exile:
            before_text = before_text[len("you may "):]
        before_specs = parse_effect_body(
            before_text, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
        )
        if before_specs is not None and optional_exile:
            before_specs = [
                EffectSpec(s.type, {**s.params, "optional": True}, condition=s.condition)
                for s in before_specs
            ]
        # Fail closed unless the "before" half genuinely chose a graveyard
        # card (`announces_creature_target` recognises the `graveyard_*`
        # target-kind prefix) — that pick is the pronoun `CopyPermanentEffect
        # (referent="previous")` reads back (RULE 608.2).
        if before_specs is None or not announces_creature_target(before_specs):
            return None
        after_specs = parse_effect_body(
            exile_then_copy.group("after"), reading=ClauseReading(previous_subject=True, group_subject=reading.group_subject),
        )
        if after_specs is None or not any(s.type == "copy_permanent" for s in after_specs):
            return None
        return before_specs + after_specs

    pooled_this_way = this_way_sequences(
        body, verbs=frozenset({"exiled", "destroyed", "milled"}),
        reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject),
    )
    if pooled_this_way is not None:
        return pooled_this_way

    any_number_this_way = any_number_this_way_specs(body, reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject), )
    if any_number_this_way is not None:
        return any_number_this_way

    windowed_this_way = this_way_sequences(
        body, verbs=frozenset({"discarded", "sacrificed"}),
        reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject),
    )
    if windowed_this_way is not None:
        return windowed_this_way

    exile_x_for_each = EXILE_X_GY_FOR_EACH_CREATE_RE.match(body)
    if exile_x_for_each is not None:
        create_specs = parse_effect_body(
            exile_x_for_each.group("create"), reading=ClauseReading(previous_subject=True, group_subject=reading.group_subject),
        )
        if not create_specs or len(create_specs) != 1:
            return None
        follow = create_specs[0]
        if follow.type == "copy_permanent":
            # "…create a token that's a copy of that card…" (Hour of Eternity)
            # — one copy of *each* exiled card, RULE 608.2 `previous_targets`.
            follow = EffectSpec(
                "copy_permanent", {**follow.params, "referent": "previous_each"},
            )
        elif follow.type == "create_token":
            # "…create a 2/2 black Zombie creature token." (Midnight Ritual) —
            # N inline tokens, N = how many cards this resolution exiled.
            follow = EffectSpec(
                "create_token",
                {**follow.params, "count_from_context": "objects_exiled_this_way"},
            )
        else:
            return None  # fail closed — only the two known follow-up shapes
        return [
            EffectSpec("exile", {
                "target_kind": "graveyard_creature", "count_selector": "source_x_paid",
            }),
            follow,
        ]

    quoted_token_ability = created_tokens_have_ability_specs(body)
    if quoted_token_ability is not None:
        return quoted_token_ability

    distributed_cda = created_tokens_have_cda_specs(body)
    if distributed_cda is not None:
        return distributed_cda

    destroyed_counter_token = destroy_target_counter_token_specs(body)
    if destroyed_counter_token is not None:
        return destroyed_counter_token

    direct = match_clause(
        body, reading=reading,
    )
    if direct is not None:
        return direct

    if re.match(r"you may pay (?:\{e\})+\.\s*(?:if|when) you do\b", body, re.I):
        # RULE 608.2/603.12: the payment and its continuation are atomic.
        # A declined wrapper must not fall through to splitting ", then"
        # and turn an unsupported paid/reflexive payoff into a free effect.
        return None

    timed = for_as_long_as_counter_specs(body, reading=ClauseReading(referents=reading.referents_of(TARGET, PLAYER)))
    if timed is not None:
        return timed

    both_counters = DOUBLE_COUNTERS_RE.match(body)
    if both_counters is not None:
        # "put a +1/+1 counter on that creature and a +1/+1 counter on ~" — two placements in one
        # sentence, each read on its own (the second half has no verb of its own to split on).
        halves = [
            parse_effect_body(
                f"put {both_counters.group(part)}", reading=reading,
            )
            for part in ("first", "second")
        ]
        if all(halves):
            return [spec for half in halves for spec in half]
        return None

    # PAR-62: "if `<cond>`, `<A>`. otherwise, `<B>`." must be claimed as one
    # `if_else` *before* the connector split, not after it. The split hands
    # "otherwise, `<B>`" over as its own part, and a standing
    # `CONDITION_PREFIXES` row reads a bare leading "otherwise," as RULE
    # 701.30d's **clash** "otherwise" — the only place that word had a
    # modeled meaning before this. That gate is right for a clash card and
    # unrelated here, so leaving the split to win would attach
    # "you didn't win the clash" to this card's else branch: a wrong reading,
    # and one this ticket's own `if` gate would newly expose by making the
    # *then* half parse. Anchored on a leading "if", so a real clash body
    # ("clash with an opponent. if you win, …") never reaches this and keeps
    # its own grammar.
    if_else = if_else_specs(
        body, reading=reading.unattached(),
    )
    if if_else is not None:
        return if_else

    override = instead_override_specs(body, reading=reading.unattached())
    if override is not None:
        return override

    # PAR-261, RULE 608.2c: instructions are read in order, so a leading sentence ("put a quest counter on ~.")
    # resolves first and the "… instead" override reads the board it left (the threshold is checked after the counter).
    led_override = led_instead_override_specs(body, reading=reading)
    if led_override is not None:
        return led_override

    # "If `<cond>`, `<A>` and|, then `<B>`." — one sentence, one gate over *both* effects. The
    # connector split below would hand `<B>` over on its own, ungated (Unholy Annex: "If you
    # control a Demon, each opponent loses 2 life and you gain 2 life" gained the life
    # whether or not you did). A body with a period is several sentences and keeps its
    # per-clause gating.
    one_gate = GENERIC_IF_PREFIX_RE.match(body)
    if one_gate is not None and "." not in one_gate.group("rest") and re.search(
        r"\s+and\s+|,?\s+then\s+", one_gate.group("rest")
    ):
        gate = static_condition(one_gate.group("cond"))
        gated_inner = (
            parse_effect_body(
                one_gate.group("rest"), reading=reading.unattached(),
            )
            if gate is not None else None
        )
        if gated_inner and all(spec.condition is None for spec in gated_inner):
            return [EffectSpec(spec.type, dict(spec.params), condition=gate) for spec in gated_inner]

    # "`<A>` and `<B>`, where X is the number of …" — one X for the whole sentence. The
    # connector split below would hand the tail to `<B>` alone and leave `<A>`'s X as
    # the (unpaid) spell X (Tendrils of Corruption dealt 0 damage and gained the life).
    one_x_text = body.strip().rstrip(".").strip()
    # RULE 608.2h: a pronoun-defined X scopes all of this sentence, before
    # splitting a drain into separate life-loss and life-gain instructions.
    contextual_x = WHERE_X_CHARACTERISTIC_RE.match(one_x_text)
    if contextual_x is not None and "." not in contextual_x.group("rest"):
        shared_characteristic = referent_characteristic_specs(body, reading=reading)
        if shared_characteristic is not None:
            return shared_characteristic
    one_x = (WHERE_X_RE.match(one_x_text) or WHERE_X_AMOUNT_RE.match(one_x_text)
             or WHERE_X_DIE_RE.match(one_x_text) or WHERE_X_HALF_COUNT_RE.match(one_x_text))
    if one_x is not None and "." not in one_x.group("rest") and re.search(
        r"\s+and\s+|,?\s+then\s+", one_x.group("rest")
    ):
        shared_x = where_x_specs(
            body, reading=reading.unattached(),
            several=True,
        )
        if shared_x is not None:
            return shared_x

    for sep in CONNECTORS:
        # PAR-141: the pronoun comma is only a boundary *within* a gated body's own effect text. Split
        # across "…, if you do, X, it gains …" it would leave the later clauses outside the gate.
        if sep is PRONOUN_COMMA_CONNECTOR and re.search(r"\b(?:if|when) you (?:do|don't),", body, re.I):
            continue
        if sep not in SENTENCE_CONNECTORS and splits_inside_gated_sentence(body, sep):
            # BUG-68, RULE 608.2c: "If C, A and B." is one conditional sentence -- C gates both instructions. A
            # split below a sentence would hand "If C, A" its gate and leave "B" outside it, so such a sentence is
            # only ever split at sentence boundaries (the gate rows peel it whole, or it stays unclaimed).
            continue
        parts = split_effect_connector(body, sep)
        if len(parts) > 1:
            collected: list[EffectSpec] = []
            ok = True
            # Seed the pronoun chain from the caller: a two-sentence wrapper
            # (`EXILE_THEN_COPY_SENTENCE_RE`, `with_after_tail`) passes
            # ``previous_subject=True`` for a span it already knows opens
            # with a referent ("create a token that's a copy of that card.
            # It gains haste …") — the *first* sub-part must inherit that,
            # not restart from nothing. ``self_subject`` still isn't passed
            # down (see this function's docstring).
            referents = reading.referents
            referent = any(r.kind == TARGET for r in referents)
            referent_selector = any(r.kind == SELECTOR for r in referents)
            # PAR-32: a self-subject trigger body ("whenever ~ attacks, put a
            # +1/+1 counter on ~. it gains deathtouch until end of turn." —
            # Agent of the Shadow Thieves) — "it" in every sub-clause still
            # means the source, until a clause introduces a *different*
            # targeted creature (`announces_creature_target` flips
            # ``carry_self`` off). Unlike the source-less `previous_subject`
            # chain, this survives a clause that only re-references the
            # source (a counter on "~").
            carry_self = reading.self_subject
            last_len = 0
            # "Otherwise, you may pay {X}. When you do, …" (Rose Room
            # Treasurer): the reflexive sentence belongs to the else branch
            # (RULE 603.12), not to the clauses after the if_else.
            merged: list[str] = []
            for part in parts:
                if (merged and OTHERWISE_RE.match(merged[-1].strip())
                        and re.match(r"^\s*(?:when|if) you do,", part, re.I)):
                    merged[-1] = f"{merged[-1].rstrip()}. {part.strip()}"
                else:
                    merged.append(part)
            parts = merged
            skip_until = 0
            conjunct_player_scope = None
            reflexive_open = False
            for idx, part in enumerate(parts):
                if idx < skip_until:
                    continue  # consumed by a multi-sentence window
                if reflexive_open:
                    # PAR-207 (RULE 603.12): a sentence after "When you do, <effect>." belongs to that reflexive
                    # trigger. It could not be absorbed into the payoff above (it did not parse there), and read on
                    # its own its "it" would silently mean this ability's source -- fail closed instead.
                    ok = False
                    break
                if collected and _inspection.leaves_dangling_reference(collected, part):
                    ok = False  # PAR-213: "it" after a bare reveal/look lead must not fall back to the source
                    break
                # A period split retains the leading "then" from a printed
                # "… . Then <effect>" sentence, unlike the explicit
                # `, then` connector. It is sequencing, not effect grammar.
                part = re.sub(r"^then\s+", "", part.strip(), flags=re.IGNORECASE)
                part = created_noun_to_pronoun(part, referents)
                another_player = collected and ANOTHER_TARGET_PLAYER_RE.match(part) is not None
                if another_player:
                    part = ANOTHER_TARGET_PLAYER_RE.sub("", part, count=1)  # parsed as "target player ..."; stamped below
                if collected and collected[-1].type == "mill":
                    # RULE 701.17: after a mill, "from among them" names the cards that mill put into the graveyard.
                    part = FROM_AMONG_THEM_RE.sub("from among the cards milled this way", part)
                if sep in (AND_CONNECTOR, SERIES_COMMA_CONNECTOR, CONNECTORS[2]):
                    part = part.rstrip(",").strip()  # "…if {g} was spent to cast this spell**,** and …"
                    # A repeated third-person verb keeps the current group
                    # subject: "each opponent sacrifices ... and loses ...".
                    # A newly stated subject ends that inheritance.
                    player_head = PLAYER_SCOPE_SUBJECT_RE.match(part)
                    if player_head is not None:
                        who = player_head['who'].lower()
                        conjunct_player_scope = (
                            "that player" if who.startswith("target ")
                            else who if who in PLAYER_SETS or who == "that player" else None
                        )
                    elif conjunct_player_scope and ELIDED_PLAYER_VERB_RE.match(part):
                        part = f"{conjunct_player_scope} {part}"
                    else:
                        conjunct_player_scope = None
                otherwise = OTHERWISE_RE.match(part)
                if otherwise is not None:
                    sub = otherwise_specs(
                        otherwise.group("rest"), collected[len(collected) - last_len:] if last_len else [],
                        reading=sequel_reading(reading, carry_self, referents),
                    )
                    if sub is not None:
                        del collected[len(collected) - last_len:]  # the if_else replaces them
                else:
                    sub = None
                    if sep == CONNECTORS[0]:
                        # A row written for several consecutive sentences (`MAX_SENTENCE_WINDOW`),
                        # longest first, before the sentence alone: splitting would hand it only
                        # its first sentence.
                        for end in range(min(len(parts), idx + MAX_SENTENCE_WINDOW), idx + 1, -1):
                            window = re.sub(r"^then\s+", "", ". ".join(p.strip() for p in parts[idx:end]), flags=re.I)
                            sub = match_clause(
                                window, reading=sequel_reading(reading, carry_self, referents),
                            )
                            if (sub is None and (idx > 0 or end < len(parts))
                                    and 'search your library' in window
                                    and 'if you search' in window):
                                # RULE 608.2c: keep an optional search and its conditional
                                # shuffle tail together inside a larger sequence.
                                sub = parse_effect_body(window, reading=sequel_reading(reading, carry_self, referents))
                            if sub is not None:
                                skip_until = end
                                break
                    if (sub is None and idx + 1 < len(parts) and (idx > 0 or len(parts) > 2)
                            and GATED_MAY_PAY_RE.match(part)
                            and IF_YOU_DO_SENTENCE_RE.match(parts[idx + 1].strip())):
                        # RULE 608.2c / 117.3: "If C, you may discard a card. If you do, draw a card." -- the second
                        # sentence's antecedent is the gated optional payment, so the pair is one gated
                        # `pay_cost_then` (the gate belongs to the payment, the payoff only follows a paid cost).
                        sub = parse_effect_body(
                            f"{part.strip()}. {parts[idx + 1].strip()}",
                            reading=sequel_reading(reading, carry_self, referents),
                        )
                        if sub is not None:
                            skip_until = idx + 2
                    if sub is None:
                        sub = parse_effect_body(
                            part,
                            reading=sequel_reading(reading, carry_self, referents),
                        )
                if sub is None and sep == AND_CONNECTOR and idx and combat_tail(part, temporary=True):
                    # RULE 608.2c: "it gets +2/+2 ... and can block an additional creature this turn".
                    # The elided combat predicate keeps the established object, never invents a target.
                    sequel = sequel_reading(reading, carry_self, referents)
                    plural = any(r.group for r in referents if r.kind in (TARGET, CREATED)) or referent_selector
                    sub = parse_effect_body(('they ' if plural else 'it ') + part, reading=sequel)
                if sub is None and sep == AND_CONNECTOR and idx:
                    # "~ deals 3 damage to X if … **and 3 damage to Y** if …" / "you gain X life if … **and X life**
                    # if …": the second conjunct repeats only the amount noun, the verb is the first one's.
                    for verb_head, elided in ELIDED_AMOUNT_VERBS:
                        if (
                            parts[idx - 1].lstrip().lower().startswith(verb_head) and elided.match(part)
                        ):
                            sub = parse_effect_body(
                                f"{verb_head}{part}", reading=sequel_reading(reading, carry_self, referents),
                            )
                            # "any other target" / "another …" is only kept distinct by the stamp (ENG-52); an
                            # effect that cannot carry it leaves the compound unclaimed.
                            if sub is not None and ELIDED_TARGET_LOSS_RE.search(part):
                                sub, distinct = stamp_distinct_from_others(sub)
                                if not distinct:
                                    sub = None
                            break
                if sub is not None and another_player:
                    sub = stamp_distinct_target_player(sub)
                if sub is None:
                    ok = False
                    break
                if sep in (AND_CONNECTOR, SERIES_COMMA_CONNECTOR) and idx and elides_player_subject(parts[0], part):
                    # "target player draws a card **and loses 2 life**": the second verb has no subject of
                    # its own, so it acts on the player the first clause chose, not on the controller.
                    sub = stamp_previous_player(sub)
                    if sub is None:
                        ok = False
                        break
                if referent:
                    sub = stamp_counters_on_referent(part, sub)
                if collected and OTHER_TARGET_PART_RE.search(part):
                    # ENG-52: "…. ~ deals 2 damage to any other target": not the target an earlier clause chose.
                    sub, _ = stamp_distinct_from_others(sub)
                sub = fold_counter_destination(sub, collected)
                if sub is None:
                    ok = False
                    break
                last_len = len(sub)
                collected.extend(sub)
                reflexive_open = any(opens_reflexive_trigger(spec) for spec in sub)
                prev_referent, prev_referent_selector = referent, referent_selector
                prev_referents = referents
                # RULE 601.2c: what the clause just parsed *chose* is what
                # the next one's "it"/"that creature"/"those creatures" can
                # point at (`effect_rows.shared.EffectHandler.previous_subject_only`,
                # `effects.GameContext.previous_targets`). A clause that
                # chose no creature leaves the pronoun unbound — and so
                # unclaimed — rather than letting it drift onto some earlier
                # clause's pick, which is the ambiguity this gate exists for.
                referent = TARGET in {r.kind for r in produces(sub)}
                # PAR-32: once a clause picks a *different* targeted creature,
                # the self-subject carry is broken (a later "it" now means
                # that pick, via ``referent``, not the source).
                if referent:
                    carry_self = False
                if any(r.kind == PLAYER for r in produces(sub)):
                    carry_self = False
                # PAR-30: "clash with an opponent" is a *referent-transparent*
                # interstitial — it neither targets nor creates, so a card
                # like Gilt-Leaf Ambush ("create 2 tokens. clash with an
                # opponent. if you win, those creatures gain deathtouch …")
                # must carry the pronoun chain across the clash sentence
                # rather than have it cleared here.
                if not referent and sub and all(s.type in REFERENT_TRANSPARENT_TYPES for s in sub):
                    referent, referent_selector = prev_referent, prev_referent_selector
                # PAR-324 / RULE 608.2c: "exile it at the beginning of the next end step" restates the
                # earlier object (a delayed trigger capturing `previous_or_self`) and chooses nothing, so a
                # later "that creature" still names the object the clause before it made or targeted
                # ("Create a 7/1 ... token. Exile it at the beginning of the next end step. If this spell was
                # kicked, that creature gets +7/+0 until end of turn.").
                delayed_restatement = bool(sub) and all(
                    s.type == "create_delayed_trigger" and s.params.get("capture") == "previous_or_self" for s in sub
                )
                if not referent and delayed_restatement:
                    referent, referent_selector = prev_referent, prev_referent_selector
                # PAR-141: "put a +1/+1 counter on ~. It becomes a Spirit in addition to …" — a
                # counter put on the source leaves "it" meaning the source (a counter spec with no
                # target of its own is the ability's own permanent), so the next clause may read
                # the pronoun as `self_subject` even outside a self-subject trigger.
                if not referent and sub and (puts_counter_on_source(sub[-1]) or animates_source(sub[-1])):
                    carry_self = True
                # PAR-30: a clause that itself *consumed* the pronoun ("untap
                # that creature", "it gains haste until end of turn") keeps the
                # referent chain alive for the clause after it rather than
                # clearing it — real cards run several such restatement clauses
                # in series off one "gain control of target creature" antecedent
                # (the threaten family; RULE 701.30d clash "if you win, …"
                # payoffs). Only extends an existing chain, never starts one.
                # PAR-123: the *input* referent had to exist. A clause a group trigger's own
                # firing object satisfied (`match_clause`'s group fallback) consumes a previous
                # -subject row without any earlier clause having chosen anything, and must not
                # turn that into a chain a later "it" would read as a real target.
                if not referent and prev_referent and any(
                    s.params.get("previous_subject") or s.params.get("bake_previous_objects") for s in sub
                ):
                    referent = True
                # MEC-28: the mass-selector sibling — "untap all attacking
                # creatures. They gain …" — tracked independently since a
                # selector clause never sets ``referent`` above (it targets
                # nothing at all, RULE 601.2c).
                referent_selector = SELECTOR in {r.kind for r in produces(sub)}
                # What was just *made* stays the referent while later clauses keep consuming it ("... It has "...".
                # It gains haste ..."), and only then.
                made = tuple(r for r in produces(sub) if r.kind in (CREATED, COUNTERED)) or (
                    tuple(r for r in prev_referents if r.kind == CREATED)
                    if delayed_restatement or any(s.params.get("referent") == CREATED for s in sub) else ()
                )
                target_refs = tuple(r for r in produces(sub) if r.kind == TARGET) or tuple(
                    r for r in prev_referents if r.kind == TARGET)
                player_refs = tuple(r for r in produces(sub) if r.kind == PLAYER) or (
                    tuple(r for r in prev_referents if r.kind == PLAYER) if "that player" in part else ())
                # A revealed / exiled library card stays nameable until another clause replaces it (RULE 701.20).
                revealed_refs = tuple(r for r in produces(sub) if r.kind == REVEALED) or tuple(
                    r for r in prev_referents if r.kind == REVEALED)
                # PAR-284 (RULE 701.17): "the milled card" names only the clause right after the mill.
                milled_refs = tuple(r for r in produces(sub) if r.kind == MILLED)
                pool_refs = tuple(r for r in produces(sub) if r.kind == EXILE_POOL)
                if not pool_refs and all(s.type in {'gain_life', 'lose_life', 'add_mana'} for s in sub):
                    pool_refs = tuple(r for r in prev_referents if r.kind == EXILE_POOL)
                referents = (referents_from(referent, referent_selector, made, target_refs)
                             + player_refs + revealed_refs + milled_refs + pool_refs)
            if ok:
                return collected

    # The same rule again, at the *other* end of the pipeline: these gates
    # are checked **after** the connector split so each binds to only its own
    # clause. In "draw a card, then discard a card unless her additional cost
    # was paid" the split hands this just "discard a card unless …", where a
    # pre-split peel would have gated the draw too. Two call sites, not two
    # implementations — where in the pipeline a gate binds is a real property
    # of the gate, and the only thing that separates the two tables.
    matched, peeled = peel_condition(
        body, CONDITION_SUFFIXES, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(*GATED_REST_REFERENT_KINDS), group_subject=reading.group_subject, attached_subject=reading.attached_subject),
    )
    if matched and peeled is not None:
        return peeled

    # PAR-62 (`14_` S4), the first connective routed to an ENG-37 composition
    # node rather than to a fused effect type or a per-effect ``optional``
    # boolean: RULE 601.2b's "you may `<effect>`" appearing **mid-body**.
    #
    # `peel_optional` handles only a *leading* "you may", at the whole-ability
    # level (`segment_line`), which is why "…, then you may `<effect>`" — the
    # connector split hands this function "you may `<effect>`" as its own
    # part — had no reading at all. A named standing gap in `09_`.
    #
    # Deliberately placed **after** everything above, including the connector
    # cascade: `CONNECTORS` returns on the first separator that yields a
    # *complete* parse, so a body with a reading today keeps it and this can
    # only fire where the pipeline already returned ``None``. That is what
    # makes S4 landable in increments instead of as one re-derivation of every
    # MODELED card.
    for_each = for_each_specs(
        body, reading=reading.unattached(),
    )
    if for_each is not None:
        return for_each

    where_x = where_x_specs(
        body, reading=reading.unattached(),
    )
    if where_x is not None:
        return where_x

    referent_x = referent_characteristic_specs(
        body, reading=reading,
    )
    if referent_x is not None:
        return referent_x

    count_bound = mana_value_count_bound_specs(body, reading=reading)
    if count_bound is not None:
        return count_bound

    per_member = per_member_amount_specs(body, lambda text: parse_effect_body(text, reading=reading))
    if per_member is not None:
        return per_member

    player_scope = player_scope_specs(
        body, reading=reading.unattached(),
    )
    if player_scope is not None:
        return player_scope

    each_flip = leading_for_each_flip_specs(
        body, reading=reading.unattached(),
    )
    if each_flip is not None:
        return each_flip

    each_object = leading_for_each_object_specs(body, reading=reading)
    if each_object is not None:
        return each_object

    per_member_attachments = per_member_attachment_specs(body, reading=reading)
    if per_member_attachments is not None:
        return per_member_attachments

    matched, peeled = peel_condition(
        body, GENERIC_CONDITION_ROWS, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(*GATED_REST_REFERENT_KINDS), group_subject=reading.group_subject, attached_subject=reading.attached_subject),
    )
    if matched and peeled is not None:
        return peeled

    optional_body = MID_BODY_OPTIONAL_RE.match(body)
    if optional_body is not None and not PAY_ENERGY_THEN_PEEL_GUARD_RE.match(body):
        rest = optional_body.group("rest").strip()
        # One "you may" per node. A second one inside ``rest`` would make the
        # outer node wrap clauses the card never made optional (the printed
        # "you may A. you may B" is two independent choices, not one), so it
        # fails closed here rather than guessing a nesting.
        #
        # The same refusal for RULE 603.3's *reflexive* trigger, "you may A.
        # when you do, B." / "…if you do, B." — B is a separate triggered
        # ability that fires because A happened and uses the stack, not a
        # second half of one choice. Wrapping both in this node would collapse
        # the trigger into a plain sequence, which is a wrong reading rather
        # than a missing one; those shapes have their own grammar above
        # (`_EARTHBEND_THEN_WHEN_YOU_DO_RE` and its siblings) and must reach
        # it. Pinned by `tests/test_par30_earthbend_when_you_do.py`.
        if not MID_BODY_OPTIONAL_RE.match(rest) and not REFLEXIVE_TRIGGER_RE.search(rest):
            inner = parse_effect_body(
                rest, reading=reading.unattached(),
            )
            if inner:
                return [EffectSpec("optional", {
                    "effects": [spec.to_dict() for spec in inner],
                })]

    # PAR-117: "its controller may `<effect>`" — same composition as
    # `MID_BODY_OPTIONAL_RE` just above, but the chooser is a referent
    # rather than "you". Only meaningful under exactly one of the three
    # pronoun-referent modes `parse_effect_body`'s own docstring documents
    # (never `self_subject`: "its controller" when the subject already *is*
    # the source would just mean "you", which the plain "you may" row above
    # already claims) — resolved to the identical `{"of": …, "as":
    # "controller"}` dict `_its_controller_*`/`_group_its_controller_*`/
    # `_attached_its_controller_*` already read via `_operand_player`.
    its_controller_may = MID_BODY_ITS_CONTROLLER_MAY_RE.match(body)
    if its_controller_may is not None:
        referent = (
            {"of": "previous_target", "as": "controller"} if reading.previous_subject
            else {"of": "entering", "as": "controller"} if reading.group_subject
            else {"of": "attached", "as": "controller"} if reading.attached_subject
            else None
        )
        if referent is not None:
            rest = its_controller_may.group("rest").strip()
            if not MID_BODY_OPTIONAL_RE.match(rest) and not REFLEXIVE_TRIGGER_RE.search(rest):
                inner = parse_effect_body(
                    rest, reading=ClauseReading(group_subject=reading.group_subject, referents=reading.referents),
                )
                if inner:
                    inner_dicts = [
                        rewrite_optional_referent_actor(spec.to_dict(), referent)
                        for spec in inner
                    ]
                    return [EffectSpec("optional", {
                        "effects": inner_dicts,
                        "player": referent,
                    })]
    return None


# Late-bound entry points other modules of this package call before this one is defined (see `late`).
register(parse_effect_body=parse_effect_body)
