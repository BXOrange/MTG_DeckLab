"""Tests for RULE 104.3d/122's poison-counter oracle-text family added
alongside Infect/Wither (RULE 702.90/91): `_add_rad_counters`/`_add_rad_
counters_selector` widened from a "rad"-only ``kind`` to a real alternation
(``rad|poison`` — `AddPlayerCountersEffect` was already kind-agnostic, only
the parser recognition was rad-specific), and `PumpEffect.
per_recipient_controller_counter` (Phyresis Outbreak-shaped: each recipient
in a selector group scales independently by *its own controller's* poison
count, unlike every other group-pump shape's one shared magnitude).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext, PumpEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


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
# Parse: "gets a poison counter" / "each opponent gets a poison counter"
# ---------------------------------------------------------------------------


def test_targeted_poison_counter_is_recognized():
    (spec,) = parse_effect_body("target player gets a poison counter")
    assert spec.type == "add_player_counters"
    assert spec.params == {"amount": 1, "kind": "poison", "target_kind": "player"}


def test_each_opponent_poison_counter_is_recognized():
    (spec,) = parse_effect_body("each opponent gets a poison counter")
    assert spec.type == "add_player_counters"
    assert spec.params == {"amount": 1, "kind": "poison", "selector": "each_opponent"}


def test_rad_counter_recognition_is_unaffected_by_the_widening():
    (spec,) = parse_effect_body("you get 2 rad counters")
    assert spec.type == "add_player_counters"
    assert spec.params == {"amount": 2, "kind": "rad"}


def test_infectious_bite_is_fully_modeled():
    card = Card(
        id="Infectious Bite", name="Infectious Bite", type_line="Sorcery",
        mana_cost_string="{2}{B}", converted_mana_cost=3, is_sorcery=True,
        oracle_text="Target creature you control deals damage equal to its power "
                     "to target creature you don't control. Each opponent gets a "
                     "poison counter.",
    )
    assert parse_oracle(card).coverage == MODELED


# ---------------------------------------------------------------------------
# Engine: `AddPlayerCountersEffect` with kind="poison" (mass selector)
# ---------------------------------------------------------------------------


def test_add_player_counters_each_opponent_poison():
    from mtg_analyzer.game.effects.core import AddPlayerCountersEffect

    engine, state, p1, p2 = _rules()
    source = _bf(state, Card(id="Src", name="Src", type_line="Creature", is_creature=True,
                              power=1, toughness=1), controller="p1")
    ctx = GameContext(state, engine)
    AddPlayerCountersEffect(amount=1, kind="poison", selector="each_opponent", source=source).apply(ctx)
    assert p2.poison == 1
    assert p1.poison == 0


# ---------------------------------------------------------------------------
# PumpEffect.per_recipient_controller_counter (Phyresis Outbreak)
# ---------------------------------------------------------------------------


def test_per_recipient_controller_counter_scales_independently_per_object():
    engine, state, p1, p2 = _rules()
    p2.poison = 3
    source = _bf(state, Card(id="Source", name="Source", type_line="Creature",
                              is_creature=True, power=1, toughness=1), controller="p1")
    opp_creature = _bf(state, Card(id="Opp Bear", name="Opp Bear", type_line="Creature",
                                    is_creature=True, power=4, toughness=4), controller="p2")
    own_creature = _bf(state, Card(id="Own Bear", name="Own Bear", type_line="Creature",
                                    is_creature=True, power=4, toughness=4), controller="p1")
    ctx = GameContext(state, engine)

    PumpEffect(
        power=-1, toughness=-1, selector="creatures_opponents_control",
        per_recipient_controller_counter="poison", source=source,
    ).apply(ctx)
    continuous.recompute(state)

    assert opp_creature.power == 1 and opp_creature.toughness == 1  # 4 - 3
    assert own_creature.power == 4 and own_creature.toughness == 4  # untouched


def test_per_recipient_controller_counter_with_zero_poison_is_a_no_op():
    engine, state, p1, p2 = _rules()
    source = _bf(state, Card(id="Source", name="Source", type_line="Creature",
                              is_creature=True, power=1, toughness=1), controller="p1")
    opp_creature = _bf(state, Card(id="Opp Bear", name="Opp Bear", type_line="Creature",
                                    is_creature=True, power=2, toughness=2), controller="p2")
    ctx = GameContext(state, engine)

    PumpEffect(
        power=-1, toughness=-1, selector="creatures_opponents_control",
        per_recipient_controller_counter="poison", source=source,
    ).apply(ctx)
    continuous.recompute(state)

    assert opp_creature.power == 2 and opp_creature.toughness == 2


def test_phyresis_outbreak_is_fully_modeled_and_resolves_end_to_end():
    card = Card(
        id="Phyresis Outbreak", name="Phyresis Outbreak", type_line="Sorcery",
        mana_cost_string="{3}{B}", converted_mana_cost=4, is_sorcery=True,
        oracle_text="Each opponent gets a poison counter. Then each creature your "
                     "opponents control gets -1/-1 until end of turn for each "
                     "poison counter its controller has.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED

    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    p2.poison = 2  # already-poisoned before this spell adds its own counter
    bear = GameObject(Card(id="Bear", name="Bear", type_line="Creature", is_creature=True,
                            power=3, toughness=3), owner_id="p2", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    eng.state.add_to_battlefield(bear)

    obj = GameObject(card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(obj)
    ctx = GameContext(eng.state, eng.rules)
    for effect in obj.spell_effects:
        effect.apply(ctx)
    eng.recompute_continuous_effects()

    assert p2.poison == 3  # 2 already + 1 from this spell
    assert bear.power == 0 and bear.toughness == 0  # 3 - 3
