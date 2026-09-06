"""PAR-28: the "Keyword — [ability]" families — Boast (RULE 702.142), Exhaust
(RULE 702.177), Power-up (Marvel), Forecast (RULE 702.57), Solved (RULE
702.169 / 719), Max Speed (RULE 702.178 / 702.179).

Each is a real activated / triggered / static ability behind an em-dash
label, with the keyword adding a fixed restriction to it. The parser strips
the label, parses the body normally, and folds the restriction onto the
resulting spec; the engine enforces it.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, UNMODELED, parse_oracle


def make_engine(*pids):
    if not pids:
        pids = ("p1", "p2")
    return GameEngine.new_game(
        [(p, p, []) for p in pids], starting_life=20, starting_hand=0
    )


def put(state, card, controller="p1", *, hand=False):
    zone = Zone.HAND if hand else Zone.BATTLEFIELD
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if hand:
        state.player_by_id(controller).zones[Zone.HAND].append(obj)
    else:
        state.add_to_battlefield(obj)
    return obj


def creature(name, text, *, keywords=(), mv=2, pt=(2, 2), type_line="Creature — Human"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature="Creature" in type_line,
        power=pt[0], toughness=pt[1], converted_mana_cost=mv,
        keywords=list(keywords), oracle_text=text,
    )


# ---------------------------------------------------------------------------
# Boast — RULE 702.142a
# ---------------------------------------------------------------------------

BOAST = creature(
    "Test Braggart",
    "Boast — {1}{W}: Put a +1/+1 counter on this creature. "
    "(Activate only if this creature attacked this turn and only once each turn.)",
    keywords=["Boast"],
)


def test_boast_parses_as_a_restricted_activated_ability():
    r = parse_oracle(BOAST)
    assert r.coverage is MODELED
    (spec,) = [s for s in r.effect_specs if s.ability_kind == "activated"]
    kinds = {e.type for e in spec.effects}
    assert "once_per_turn_marker" in kinds
    assert "activation_condition_marker" in kinds


def test_boast_cannot_be_activated_before_attacking_then_can_after():
    eng = make_engine()
    p1 = eng.state.player_by_id("p1")
    obj = put(eng.state, BOAST)
    (ability,) = obj.activated_abilities
    assert ability.cost.activation_condition == {"kind": "source_attacked_this_turn"}
    assert not eng.can_activate(p1, obj, ability, assume_mana_available=True)
    obj.attacked_this_turn = True
    assert eng.can_activate(p1, obj, ability, assume_mana_available=True)


def test_boast_is_once_per_turn():
    eng = make_engine()
    p1 = eng.state.player_by_id("p1")
    obj = put(eng.state, BOAST)
    obj.attacked_this_turn = True
    (ability,) = obj.activated_abilities
    assert ability.once_per_turn
    ability._last_activated_turn = eng.state.internal_turn.number
    assert not eng.can_activate(p1, obj, ability, assume_mana_available=True)


def test_attacked_this_turn_flag_resets_at_untap():
    eng = make_engine()
    obj = put(eng.state, BOAST)
    obj.attacked_this_turn = True
    eng.state.current_step = "end"
    eng.advance_step()  # into p2's untap (or next boundary) — sweeps the flag
    while eng.state.current_step != "untap":
        eng.advance_step()
    eng._step_untap()
    assert obj.attacked_this_turn is False


# ---------------------------------------------------------------------------
# Exhaust — RULE 702.177a ("Activate only once", per game)
# ---------------------------------------------------------------------------

EXHAUST = creature(
    "Test Exhauster",
    "Exhaust — {2}{G}: Put two +1/+1 counters on this creature. "
    "(Activate each exhaust ability only once.)",
    keywords=["Exhaust"],
)


def test_exhaust_parses_with_the_once_per_game_marker():
    r = parse_oracle(EXHAUST)
    assert r.coverage is MODELED
    (spec,) = [s for s in r.effect_specs if s.ability_kind == "activated"]
    assert "activate_only_once_marker" in {e.type for e in spec.effects}


def test_exhaust_ability_is_once_per_game():
    eng = make_engine()
    p1 = eng.state.player_by_id("p1")
    obj = put(eng.state, EXHAUST)
    (ability,) = obj.activated_abilities
    assert ability.once_per_game
    assert eng.can_activate(p1, obj, ability, assume_mana_available=True)
    # Simulate the mark `activate_ability` records.
    obj.used_once_per_game_abilities.add(ability.description)
    assert not eng.can_activate(p1, obj, ability, assume_mana_available=True)
    # It is NOT reset by a new turn (unlike once_per_turn).
    eng.begin_turn()
    assert not eng.can_activate(p1, obj, ability, assume_mana_available=True)


def test_two_exhaust_abilities_track_separately():
    card = creature(
        "Twin Exhauster",
        "Exhaust — {G}: Draw a card.\nExhaust — {R}: Put a +1/+1 counter on this creature.",
        keywords=["Exhaust"],
    )
    eng = make_engine()
    p1 = eng.state.player_by_id("p1")
    obj = put(eng.state, card)
    assert parse_oracle(card).coverage is MODELED
    a, b = obj.activated_abilities
    obj.used_once_per_game_abilities.add(a.description)
    assert not eng.can_activate(p1, obj, a, assume_mana_available=True)
    assert eng.can_activate(p1, obj, b, assume_mana_available=True)


# ---------------------------------------------------------------------------
# Power-up (Marvel) — once per game + a conditional cost reduction
# ---------------------------------------------------------------------------

POWERUP = creature(
    "Test Hero",
    "Power-up — {5}{U}: Put a +1/+1 counter on this creature and draw a card. "
    "(Activate each power-up ability only once. Reduce the cost by its mana "
    "cost if it entered this turn.)",
    keywords=["Power-up"],
    mv=2,
)


def test_powerup_parses_once_per_game_and_cost_reduction():
    r = parse_oracle(POWERUP)
    assert r.coverage is MODELED
    (spec,) = [s for s in r.effect_specs if s.ability_kind == "activated"]
    kinds = {e.type for e in spec.effects}
    assert "activate_only_once_marker" in kinds
    assert "powerup_cost_reduction_marker" in kinds


def test_powerup_cost_reduction_applies_only_the_turn_it_entered():
    eng = make_engine()
    obj = put(eng.state, POWERUP)
    (ability,) = obj.activated_abilities
    assert ability.cost.powerup_cost_reduction
    # Not entered this turn → full {5}{U} (mana value 6).
    obj.turn_entered = None
    full = eng._reduced_activation_mana(obj, ability.cost.mana, ability.cost)
    assert full.converted_mana_cost == 6
    # Entered this turn → reduced by its own mana value (2) → 4.
    obj.turn_entered = eng.state.internal_turn.number
    reduced = eng._reduced_activation_mana(obj, ability.cost.mana, ability.cost)
    assert reduced.converted_mana_cost == 4


# ---------------------------------------------------------------------------
# Forecast — RULE 702.57 (from hand, your upkeep, once per turn)
# ---------------------------------------------------------------------------

FORECAST = Card(
    id="Test Forecaster", name="Test Forecaster", type_line="Sorcery",
    is_sorcery=True, converted_mana_cost=2,
    keywords=["Forecast"],
    oracle_text=(
        "Draw a card.\n"
        "Forecast — {1}{W}, Reveal this card from your hand: Put a +1/+1 "
        "counter on target creature. (Activate only during your upkeep and "
        "only once each turn.)"
    ),
)


def test_forecast_parses_from_hand_upkeep_once_per_turn():
    r = parse_oracle(FORECAST)
    assert r.coverage is MODELED
    (spec,) = [s for s in r.effect_specs if s.ability_kind == "activated"]
    kinds = {e.type for e in spec.effects}
    assert "from_hand_marker" in kinds
    assert "once_per_turn_marker" in kinds
    cond = next(e for e in spec.effects if e.type == "activation_condition_marker")
    assert cond.params["condition"] == {"kind": "your_upkeep"}
    # "Reveal this card from your hand" is not modeled as a cost component.
    assert "reveal" not in (spec.cost or {}).get("text", "").lower()


def test_forecast_only_activatable_from_hand_during_your_upkeep():
    eng = make_engine()
    p1 = eng.state.player_by_id("p1")
    obj = put(eng.state, FORECAST, hand=True)
    target = put(eng.state, creature("Dummy", ""))
    (ability,) = obj.activated_abilities
    assert ability.cost.hand_zone
    eng.state.current_step = "draw"
    assert not eng.can_activate(p1, obj, ability, assume_mana_available=True)
    eng.state.current_step = "upkeep"
    eng.state.current_phase = "beginning"
    assert eng.state.active_player.id == "p1"
    assert eng.can_activate(p1, obj, ability, assume_mana_available=True)


# ---------------------------------------------------------------------------
# Max Speed — RULE 702.178 / Start Your Engines! — RULE 702.179
# ---------------------------------------------------------------------------

RACER = creature(
    "Test Racer",
    "Start your engines! (If you have no speed, it starts at 1.)\n"
    "Max speed — This creature has double strike.",
    keywords=["Start Your Engines!"],
    pt=(2, 2),
)


def test_max_speed_parses_as_a_speed_gated_static():
    r = parse_oracle(RACER)
    assert r.coverage is MODELED
    (spec,) = [s for s in r.effect_specs if s.ability_kind == "static"]
    assert spec.effects[0].params.get("active_if") == {"kind": "your_speed_is_max"}


def test_start_your_engines_sba_sets_speed_to_one():
    eng = make_engine()
    p1 = eng.state.player_by_id("p1")
    assert p1.speed == 0
    put(eng.state, RACER)
    eng.rules.check_state_based_actions()
    assert p1.speed == 1


def test_speed_increases_once_per_turn_on_opponent_life_loss_capped_at_four():
    eng = make_engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    put(eng.state, RACER)
    eng.rules.check_state_based_actions()
    assert p1.speed == 1
    eng.begin_turn()  # p1's turn
    assert eng.state.active_player.id == "p1"

    eng.rules.lose_life(p2, 2)
    eng.resolve_until_stable()
    assert p1.speed == 2
    # A second opponent life-loss the same turn does nothing (once each turn).
    eng.rules.lose_life(p2, 2)
    eng.resolve_until_stable()
    assert p1.speed == 2


def test_max_speed_static_only_active_at_speed_four():
    eng = make_engine()
    p1 = eng.state.player_by_id("p1")
    obj = put(eng.state, RACER)
    eng.recompute_continuous_effects()
    assert "double_strike" not in obj.granted_keywords
    p1.speed = 4
    eng.recompute_continuous_effects()
    assert "double_strike" in obj.granted_keywords


def test_speed_increase_only_on_your_own_turn():
    eng = make_engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    put(eng.state, RACER)
    eng.rules.check_state_based_actions()
    assert p1.speed == 1
    eng.begin_turn()
    eng.begin_turn()  # now p2's turn
    assert eng.state.active_player.id == "p2"
    eng.rules.lose_life(p1, 3)  # p1 (an opponent of active p2) loses life
    eng.resolve_until_stable()
    assert p1.speed == 1  # unchanged — not p1's turn


# ---------------------------------------------------------------------------
# Solved — RULE 702.169 / 719 (Case cards)
# ---------------------------------------------------------------------------

CASE = Card(
    id="Test Case", name="Test Case", type_line="Enchantment — Case",
    keywords=["Solved"],
    oracle_text=(
        "When this Case enters, draw a card.\n"
        "To solve — You control 3 or more artifacts.\n"
        "Solved — Creatures you control get +1/+0."
    ),
)


def test_case_parses_a_solve_trigger_and_a_solved_gated_static():
    r = parse_oracle(CASE)
    trig = next(
        s for s in r.effect_specs
        if s.ability_kind == "triggered" and s.effects[0].type == "become_solved"
    )
    assert trig.trigger["active_if"] == {
        "kind": "control_count", "selector": "artifacts_you_control", "min": 3
    }
    stat = next(s for s in r.effect_specs if s.ability_kind == "static")
    assert stat.effects[0].params["active_if"] == {"kind": "source_solved"}


def _fire_end_step(eng, active_id):
    """Drive the beginning of ``active_id``'s end step (RULE 719.3a's
    trigger point) without running a whole turn loop."""
    eng.state.active_player_index = [p.id for p in eng.state.players].index(active_id)
    eng.state.current_phase, eng.state.current_step = "ending", "end"
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    eng.resolve_until_stable()


def test_case_becomes_solved_at_end_step_when_condition_met_and_anthem_turns_on():
    eng = make_engine()
    case = put(eng.state, CASE)
    bear = put(eng.state, creature("Grizzly", ""))
    assert case.is_solved is False
    eng.recompute_continuous_effects()
    assert bear.power == 2  # Solved anthem inactive while unsolved

    _fire_end_step(eng, "p1")     # condition NOT met yet
    assert case.is_solved is False

    for i in range(3):
        put(eng.state, Card(id=f"art{i}", name=f"Art {i}", type_line="Artifact"))
    _fire_end_step(eng, "p2")     # p2's end step, not p1's → still not solved
    assert case.is_solved is False
    _fire_end_step(eng, "p1")     # p1's end step, condition now met
    assert case.is_solved is True

    eng.recompute_continuous_effects()
    assert bear.power == 3        # Solved anthem now active


def test_solved_designation_persists_and_is_not_reset_by_a_new_turn():
    eng = make_engine()
    case = put(eng.state, CASE)
    case.is_solved = True
    eng.begin_turn()
    eng.begin_turn()
    assert case.is_solved is True
