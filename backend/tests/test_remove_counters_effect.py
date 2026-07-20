"""Tests for `RemoveCountersEffect` (RULE 122) — "remove all counters from
target permanent" (Vampire Hexmage-shaped) and "remove all counters from all
permanents" (Oblivion Stone/Aether Snap/Thief of Blood-shaped).

The interactive-quantity "remove up to N counters" shape (Glissa Sunslayer/
Heartless Act/Render Inert-shaped) is covered separately in
`test_remove_counters_choice.py`.
"""

from __future__ import annotations

from mtg_analyzer.game.effects import GameContext, RemoveCountersEffect
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


def test_remove_all_counters_from_all_permanents_recognized():
    (spec,) = parse_effect_body("remove all counters from all permanents")
    assert spec == EffectSpec("remove_counters", {})


def test_remove_all_counters_from_target_permanent_recognized():
    (spec,) = parse_effect_body("remove all counters from target permanent")
    assert spec == EffectSpec("remove_counters", {"target_kind": "permanent"})


def test_remove_up_to_n_counters_is_recognized_as_a_different_shape():
    # A chosen-quantity effect, not "all" — see test_remove_counters_choice.py.
    (spec,) = parse_effect_body("remove up to 3 counters from target permanent")
    assert spec == EffectSpec("remove_counters", {"target_kind": "permanent", "max_count": 3})


# ---------------------------------------------------------------------------
# EFFECT CLASS: resolution
# ---------------------------------------------------------------------------


def test_remove_counters_from_target_strips_every_kind_from_that_object_only():
    engine, state, p1, p2 = _rules()
    victim = _bf(state, _creature("Vampire's Target"))
    victim.counters["+1/+1"] = 3
    victim.counters["stun"] = 2
    bystander = _bf(state, _creature("Untouched"))
    bystander.counters["+1/+1"] = 1
    ctx = GameContext(state, engine)

    RemoveCountersEffect(target_kind="permanent").apply(ctx, targets=[victim])

    assert victim.counters.get("+1/+1", 0) == 0
    assert victim.counters.get("stun", 0) == 0
    assert "+1/+1" not in victim.counters
    assert bystander.counters.get("+1/+1", 0) == 1


def test_remove_counters_untargeted_strips_every_permanent_on_the_battlefield():
    engine, state, p1, p2 = _rules()
    a = _bf(state, _creature("A"))
    a.counters["+1/+1"] = 2
    b = _bf(state, _creature("B"))
    b.counters["fate"] = 1
    b.counters["-1/-1"] = 1
    ctx = GameContext(state, engine)

    RemoveCountersEffect().apply(ctx)

    assert a.counters == {}
    assert b.counters == {}


def test_remove_counters_is_a_no_op_on_a_permanent_with_no_counters():
    engine, state, p1, p2 = _rules()
    clean = _bf(state, _creature("Clean"))
    ctx = GameContext(state, engine)

    RemoveCountersEffect().apply(ctx)

    assert clean.counters == {}


# ---------------------------------------------------------------------------
# END-TO-END: real card oracle text -> parse -> resolve
# ---------------------------------------------------------------------------


def test_vampire_hexmage_shaped_end_to_end():
    card = _card(
        "Sac and Strip", "Sacrifice this creature: Remove all counters from target permanent.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_aether_snap_shaped_end_to_end():
    card = _card("Snap Away", "Remove all counters from all permanents.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []
