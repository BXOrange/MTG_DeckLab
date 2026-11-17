"""ENG-63: who tapped a permanent (RULE 701.26a).

`TAPPED` carries ``tapper_id``: the controller of the resolving effect that tapped the permanent, or the player
paying the cost that tapped it; ``None`` where no tapper is known.  "Whenever you tap an untapped creature an
opponent controls" fires only when the tapper is the trigger's controller and the permanent's controller is an
opponent; a ``None`` tapper never fires.  Real engine, real parsed cards.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

WATCH_ORACLE = "Whenever you tap an untapped creature an opponent controls, ~ gets +2/+1 until end of turn."
BASE_POWER = 1


def make_engine(players=2):
    roster = [(f"p{i + 1}", f"P{i + 1}", []) for i in range(players)]
    return GameEngine.new_game(roster, starting_life=20, starting_hand=0)


def creature(name, power=2, toughness=2, oracle=""):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=power, toughness=toughness, oracle_text=oracle)


def _ready_main_phase(eng):
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng.state.active_player


def _put(eng, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _in_hand(eng, card, controller):
    obj = GameObject(card, owner_id=controller)
    eng.state.player_by_id(controller).add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    return obj


def _tap_spell(oracle="Tap target creature."):
    return Card(id="Freeze", name="Freeze", type_line="Instant", is_instant=True,
                mana_cost_string="{U}", converted_mana_cost=1, oracle_text=oracle)


def _power(eng, obj):
    eng.recompute_continuous_effects()
    return obj.power


def _setup(players=2):
    eng = make_engine(players)
    p1 = _ready_main_phase(eng)
    watcher = _put(eng, creature("Watcher", BASE_POWER, 3, WATCH_ORACLE), "p1")
    return eng, p1, watcher


def _cast_tap(eng, caster_id, victim):
    caster = eng.state.player_by_id(caster_id)
    spell = _in_hand(eng, _tap_spell(), caster_id)
    caster.mana_pool.add_many({"U": 1})
    eng.cast_spell(caster, spell, targets=[victim])
    eng.resolve_until_stable()


def test_watcher_is_modeled_and_head_is_scoped():
    card = creature("Watcher", BASE_POWER, 3, WATCH_ORACLE)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    trigger = result.specs[0].trigger
    assert trigger["event"] == "TAPPED" and trigger["tapper_is_you"] is True
    assert trigger["condition"]["controller"] == "not_you"


def test_tap_effect_on_an_opponents_creature_fires_and_records_the_tapper():
    eng, p1, watcher = _setup()
    victim = _put(eng, creature("Victim"), "p2")
    _cast_tap(eng, "p1", victim)
    assert victim.tapped
    taps = [e for e in eng.state.event_log if e.type == EventType.TAPPED and e.get("instance_id") == victim.instance_id]
    assert [e.get("tapper_id") for e in taps] == ["p1"]
    assert _power(eng, watcher) == BASE_POWER + 2


def test_tapping_your_own_creature_does_not_fire():
    eng, p1, watcher = _setup()
    mine = _put(eng, creature("Mine"), "p1")
    _cast_tap(eng, "p1", mine)
    assert mine.tapped
    assert _power(eng, watcher) == BASE_POWER


def test_an_opponent_tapping_their_own_or_a_third_players_creature_does_not_fire():
    eng, p1, watcher = _setup(players=3)
    theirs = _put(eng, creature("Theirs"), "p2")
    third = _put(eng, creature("Third"), "p3")
    _cast_tap(eng, "p2", theirs)   # Tangle Wire-style: the opponent taps their own creature
    _cast_tap(eng, "p2", third)    # an opponent taps another opponent's creature: the tapper is not you
    assert theirs.tapped and third.tapped
    assert _power(eng, watcher) == BASE_POWER


def test_a_cost_tap_of_your_own_creature_does_not_fire():
    eng, p1, watcher = _setup()
    watcher.tapped = True  # only the helper can convoke
    helper = _put(eng, creature("Helper"), "p1")
    convoke = Card(id="Rally", name="Rally", type_line="Sorcery", is_sorcery=True, mana_cost_string="{1}",
                   converted_mana_cost=1, keywords=["Convoke"], oracle_text="Convoke\nYou gain 1 life.")
    spell = _in_hand(eng, convoke, "p1")
    eng.cast_spell(p1, spell, help_pay=True)
    assert helper.tapped
    taps = [e for e in eng.state.event_log if e.type == EventType.TAPPED and e.get("instance_id") == helper.instance_id]
    assert [e.get("tapper_id") for e in taps] == ["p1"]  # the payer is recorded
    assert _power(eng, watcher) == BASE_POWER


def test_an_already_tapped_creature_does_not_fire():
    eng, p1, watcher = _setup()
    victim = _put(eng, creature("Victim"), "p2")
    victim.tapped = True
    _cast_tap(eng, "p1", victim)
    assert _power(eng, watcher) == BASE_POWER


def test_a_tap_with_no_known_tapper_never_fires():
    eng, p1, watcher = _setup()
    victim = _put(eng, creature("Victim"), "p2")
    eng.rules.set_tapped(victim, True)  # e.g. a tap by a rule: no tapper recorded
    eng.resolve_until_stable()
    assert victim.tapped
    assert _power(eng, watcher) == BASE_POWER
