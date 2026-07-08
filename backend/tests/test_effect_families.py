"""End-to-end tests for the newer effect families (docs/09): pump ("+N/+N
until end of turn"), a temporary keyword grant, -1/-1 counters, and scry.

Each drives an oracle spec through the binder → the real engine, so it exercises
the whole path a `MODELED` card follows, not just the regex handler.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.effect_binder import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec


def _bear(name="Bear", power=2, toughness=2, controller="p1"):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def _spell(name, oracle, effects, target=None):
    card = Card(id=name, name=name, type_line="Instant", is_instant=True,
                oracle_text=oracle)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, [AbilitySpec(
        ability_kind="spell_effect", effects=effects, target=target,
        raw_text=oracle,
    )])
    return obj


def _rules_with_creature():
    caster = Player(id="p1", life=20)
    opponent = Player(id="p2", life=20)
    state = GameState(players=[caster, opponent])
    engine = RulesEngine(state)
    bear = GameObject(_bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    state.add_to_battlefield(bear)
    engine.check_state_based_actions()  # stamp derived P/T
    return engine, state, caster, bear


# -- pump --------------------------------------------------------------------


def test_giant_growth_pumps_until_end_of_turn():
    engine, state, caster, bear = _rules_with_creature()
    growth = _spell(
        "Giant Growth", "Target creature gets +3/+3 until end of turn.",
        [EffectSpec("pump", {"power": 3, "toughness": 3, "target_kind": "creature"})],
        target={"kind": "creature"},
    )
    caster.hand.append(growth)
    engine.cast_spell(caster, growth, targets=[bear])
    engine.resolve_top_of_stack()
    engine.check_state_based_actions()
    assert (bear.power, bear.toughness) == (5, 5)
    assert bear.temp_power == 3 and bear.temp_toughness == 3


def test_pump_can_grant_a_keyword():
    engine, state, caster, bear = _rules_with_creature()
    trick = _spell(
        "Combat Trick", "Target creature gets +1/+1 and gains trample until end of turn.",
        [EffectSpec("pump", {"power": 1, "toughness": 1, "keywords": ["trample"],
                             "target_kind": "creature"})],
        target={"kind": "creature"},
    )
    caster.hand.append(trick)
    engine.cast_spell(caster, trick, targets=[bear])
    engine.resolve_top_of_stack()
    engine.check_state_based_actions()
    assert (bear.power, bear.toughness) == (3, 3)
    assert "trample" in bear.granted_keywords


def test_negative_pump_to_zero_toughness_destroys_via_sba():
    engine, state, caster, bear = _rules_with_creature()
    shrink = _spell(
        "Shrink", "Target creature gets -0/-2 until end of turn.",
        [EffectSpec("pump", {"power": 0, "toughness": -2, "target_kind": "creature"})],
        target={"kind": "creature"},
    )
    caster.hand.append(shrink)
    engine.cast_spell(caster, shrink, targets=[bear])
    engine.resolve_top_of_stack()
    engine.check_state_based_actions()  # 0-toughness SBA (RULE 704.5f)
    assert bear.zone == Zone.GRAVEYARD


def test_cleanup_ends_the_until_end_of_turn_pump():
    eng = GameEngine.new_game(
        [("p1", "Alice", [_bear()]), ("p2", "Bob", [_bear()])],
        starting_life=20, starting_hand=0,
    )
    bear = GameObject(_bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    eng.state.add_to_battlefield(bear)
    bear.temp_power, bear.temp_toughness = 3, 3
    bear.temp_keywords.add("flying")
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (5, 5)

    eng._step_cleanup()  # RULE 514.2
    assert (bear.power, bear.toughness) == (2, 2)
    assert bear.temp_power == 0 and not bear.temp_keywords
    assert "flying" not in bear.granted_keywords


# -- -1/-1 counters ----------------------------------------------------------


def test_minus_counters_shrink_and_persist():
    engine, state, caster, bear = _rules_with_creature()
    wither = _spell(
        "Wither", "Put two -1/-1 counters on target creature.",
        [EffectSpec("add_counters", {"count": 2, "kind": "-1/-1", "target_kind": "creature"})],
        target={"kind": "creature"},
    )
    caster.hand.append(wither)
    engine.cast_spell(caster, wither, targets=[bear])
    engine.resolve_top_of_stack()
    engine.check_state_based_actions()
    assert bear.counters.get("-1/-1") == 2
    assert (bear.power, bear.toughness) == (0, 0)  # 2/2 minus two -1/-1


def test_minus_counters_annihilate_plus_counters():
    engine, state, caster, bear = _rules_with_creature()
    bear.add_counters("+1/+1", 3)
    engine.add_counters(bear, 1, kind="-1/-1")
    engine.check_state_based_actions()  # RULE 704.5q removes one of each pair
    assert bear.counters.get("+1/+1") == 2
    assert bear.counters.get("-1/-1", 0) == 0


# -- scry --------------------------------------------------------------------


def test_scry_fires_an_event_for_the_controller():
    engine, state, caster, bear = _rules_with_creature()
    for i in range(3):
        caster.library.append(GameObject(_bear(f"L{i}"), owner_id="p1", zone=Zone.LIBRARY))
    omen = _spell("Omen", "Scry 2.", [EffectSpec("scry", {"count": 2})])
    caster.hand.append(omen)
    engine.cast_spell(caster, omen, targets=[])
    engine.resolve_top_of_stack()
    scries = [e for e in state.event_log if e.type == EventType.SCRY]
    assert len(scries) == 1
    assert scries[0].get("count") == 2 and scries[0].get("player_id") == "p1"
