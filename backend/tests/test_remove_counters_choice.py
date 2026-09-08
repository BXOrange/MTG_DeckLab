"""Tests for `RemoveCountersEffect`'s interactive chosen-*amount* shape —
"remove up to N counters from target permanent/creature" (Glissa Sunslayer/
Heartless Act/Render Inert-shaped) — a genuinely different effect from the
unconditional "remove all counters" shape covered in
`test_remove_counters_effect.py`. Resolution opens a `pending_choice`
(`RulesEngine.request_remove_counters_choice`) asking how many, then — only
if 2+ counter kinds are present — which kind, one at a time.
"""

from __future__ import annotations

from mtg_analyzer.game.effects.core import GameContext, RemoveCountersEffect
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, oracle_text, type_line="Instant"):
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=oracle_text,
        is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
    )


def _creature(name, power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# PARSER RECOGNITION
# ---------------------------------------------------------------------------


def test_remove_up_to_n_counters_from_target_permanent_is_recognized():
    (spec,) = parse_effect_body("remove up to 3 counters from target permanent")
    assert spec == EffectSpec("remove_counters", {"target_kind": "permanent", "max_count": 3})


def test_remove_up_to_n_counters_from_target_creature_is_recognized():
    (spec,) = parse_effect_body("remove up to 3 counters from target creature")
    assert spec == EffectSpec("remove_counters", {"target_kind": "creature", "max_count": 3})


def test_glissa_sunslayer_shaped_end_to_end():
    card = _card("Bounty of the Blade", "Remove up to three counters from target permanent.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_heartless_act_shaped_end_to_end():
    card = _card("Ruthless Erasure", "Remove up to three counters from target creature.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


# ---------------------------------------------------------------------------
# EFFECT CLASS: the interactive amount → kind choice sequence
# ---------------------------------------------------------------------------


def test_target_with_no_counters_is_a_no_op_and_opens_no_choice():
    engine, state, p1, p2 = _rules()
    victim = _bf(state, _creature("Clean"))
    ctx = GameContext(state, engine)

    RemoveCountersEffect(target_kind="permanent", max_count=3).apply(ctx, targets=[victim])

    assert state.pending_choice is None


def test_single_counter_kind_needs_no_kind_choice():
    engine, state, p1, p2 = _rules()
    victim = _bf(state, _creature("Solo"))
    victim.counters["+1/+1"] = 3
    ctx = GameContext(state, engine)

    RemoveCountersEffect(target_kind="permanent", max_count=3).apply(ctx, targets=[victim])
    assert state.pending_choice["kind"] == "remove_counters_amount"

    engine.resolve_remove_counters_amount_choice("2")
    # Only one kind present — resolved directly, no follow-up choice.
    assert state.pending_choice is None
    assert victim.counters.get("+1/+1") == 1


def test_multiple_counter_kinds_ask_one_at_a_time():
    engine, state, p1, p2 = _rules()
    victim = _bf(state, _creature("Mixed"))
    victim.counters["+1/+1"] = 3
    victim.counters["stun"] = 2
    ctx = GameContext(state, engine)

    RemoveCountersEffect(target_kind="permanent", max_count=3).apply(ctx, targets=[victim])
    engine.resolve_remove_counters_amount_choice("3")

    choice = state.pending_choice
    assert choice["kind"] == "remove_counters_kind"
    ids = {o["id"] for o in choice["options"]}
    assert ids == {"+1/+1", "stun"}

    engine.resolve_remove_counters_kind_choice("stun")
    assert state.pending_choice["kind"] == "remove_counters_kind"
    assert victim.counters.get("stun") == 1

    engine.resolve_remove_counters_kind_choice("stun")
    # "stun" is now exhausted — only "+1/+1" remains, so the last removal
    # resolves directly with no further choice.
    assert state.pending_choice is None
    assert "stun" not in victim.counters
    assert victim.counters.get("+1/+1") == 2


def test_choosing_zero_removes_nothing():
    engine, state, p1, p2 = _rules()
    victim = _bf(state, _creature("Untouched"))
    victim.counters["+1/+1"] = 3
    ctx = GameContext(state, engine)

    RemoveCountersEffect(target_kind="permanent", max_count=3).apply(ctx, targets=[victim])
    engine.resolve_remove_counters_amount_choice("0")

    assert state.pending_choice is None
    assert victim.counters.get("+1/+1") == 3


def test_declining_the_amount_choice_removes_nothing():
    engine, state, p1, p2 = _rules()
    victim = _bf(state, _creature("Untouched"))
    victim.counters["+1/+1"] = 3
    ctx = GameContext(state, engine)

    RemoveCountersEffect(target_kind="permanent", max_count=3).apply(ctx, targets=[victim])
    engine.resolve_remove_counters_amount_choice(None)

    assert state.pending_choice is None
    assert victim.counters.get("+1/+1") == 3


def test_amount_is_capped_at_counters_actually_present():
    engine, state, p1, p2 = _rules()
    victim = _bf(state, _creature("Few"))
    victim.counters["+1/+1"] = 2
    ctx = GameContext(state, engine)

    # max_count=5 (Render Inert-shaped) but only 2 counters exist.
    RemoveCountersEffect(target_kind="permanent", max_count=5).apply(ctx, targets=[victim])
    assert state.pending_choice["max"] == 2

    engine.resolve_remove_counters_amount_choice("5")  # over-request, clamped to 2
    assert state.pending_choice is None
    assert "+1/+1" not in victim.counters


def test_out_of_range_answer_clamps_to_max():
    engine, state, p1, p2 = _rules()
    victim = _bf(state, _creature("Capped"))
    victim.counters["+1/+1"] = 3
    ctx = GameContext(state, engine)

    RemoveCountersEffect(target_kind="permanent", max_count=3).apply(ctx, targets=[victim])
    engine.resolve_remove_counters_amount_choice("999")

    assert state.pending_choice is None
    assert "+1/+1" not in victim.counters


def test_kind_choice_defaults_to_first_option_on_invalid_answer():
    engine, state, p1, p2 = _rules()
    victim = _bf(state, _creature("Mixed"))
    victim.counters["+1/+1"] = 1
    victim.counters["stun"] = 1
    ctx = GameContext(state, engine)

    RemoveCountersEffect(target_kind="permanent", max_count=2).apply(ctx, targets=[victim])
    engine.resolve_remove_counters_amount_choice("2")
    first_kind = state.pending_choice["options"][0]["id"]

    engine.resolve_remove_counters_kind_choice("not-a-real-kind")
    # Defaulted to the first offered kind — one counter removed from it.
    assert victim.counters.get(first_kind, 0) == 0


# ---------------------------------------------------------------------------
# PAR-2: the compound "target artifact, creature, planeswalker, or opponent"
# target (Price of Betrayal) — the same interactive amount/kind sequence
# above, but the target may be a Player, not just a permanent.
# ---------------------------------------------------------------------------


def test_price_of_betrayal_compound_target_is_recognized():
    (spec,) = parse_effect_body(
        "remove up to 5 counters from target artifact, creature, planeswalker, or opponent"
    )
    assert spec == EffectSpec(
        "remove_counters",
        {"target_kind": "artifact_creature_planeswalker_or_opponent", "max_count": 5},
    )


def test_price_of_betrayal_shaped_end_to_end():
    card = _card(
        "Debt Collector",
        "Remove up to five counters from target artifact, creature, planeswalker, or opponent.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_compound_target_legal_targets_include_artifacts_and_opponents_only():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    engine, state, p1, p2 = _rules()
    artifact = _bf(state, Card(id="Gizmo", name="Gizmo", type_line="Artifact"))
    creature = _bf(state, _creature("Beater"), controller="p2")
    land = _bf(state, Card(id="Plains", name="Plains", type_line="Land", is_land=True))

    spec = TargetSpec(kind="artifact_creature_planeswalker_or_opponent")
    options = legal_targets(state, "p1", spec)

    ids = {o.get("instance_id") for o in options if "instance_id" in o}
    assert ids == {artifact.instance_id, creature.instance_id}
    assert land.instance_id not in ids
    player_ids = {o.get("player_id") for o in options if "player_id" in o}
    assert player_ids == {"p2"}  # not the controller ("p1") themself


def test_removing_counters_from_a_targeted_opponent_removes_their_poison():
    engine, state, p1, p2 = _rules()
    p2.poison = 3
    ctx = GameContext(state, engine)

    RemoveCountersEffect(
        target_kind="artifact_creature_planeswalker_or_opponent", max_count=5,
    ).apply(ctx, targets=[p2])
    assert state.pending_choice["kind"] == "remove_counters_amount"

    engine.resolve_remove_counters_amount_choice("2")
    assert state.pending_choice is None
    assert p2.poison == 1


def test_removing_counters_from_a_targeted_opponent_offers_every_kind():
    engine, state, p1, p2 = _rules()
    p2.poison = 2
    p2.counters["energy"] = 3
    ctx = GameContext(state, engine)

    RemoveCountersEffect(
        target_kind="artifact_creature_planeswalker_or_opponent", max_count=4,
    ).apply(ctx, targets=[p2])
    engine.resolve_remove_counters_amount_choice("4")

    choice = state.pending_choice
    assert choice["kind"] == "remove_counters_kind"
    assert choice["player_id"] == p2.id  # a player makes their own choice
    assert {o["id"] for o in choice["options"]} == {"poison", "energy"}

    engine.resolve_remove_counters_kind_choice("poison")
    assert p2.poison == 1
    engine.resolve_remove_counters_kind_choice("poison")
    assert p2.poison == 0

    # "poison" is exhausted — only "energy" remains, resolved directly.
    assert state.pending_choice is None
    assert p2.counters.get("energy") == 1


def test_opponent_with_no_counters_is_a_no_op_and_opens_no_choice():
    engine, state, p1, p2 = _rules()
    ctx = GameContext(state, engine)

    RemoveCountersEffect(
        target_kind="artifact_creature_planeswalker_or_opponent", max_count=5,
    ).apply(ctx, targets=[p2])

    assert state.pending_choice is None
