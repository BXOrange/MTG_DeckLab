"""BUG-23: RULE 120.3f/702.2b/702.15b -- lifelink and deathtouch apply to noncombat damage too.

The shared successful-damage path (`_finish_damage` over BUG-22's receipts) settles them for every
damage event; prevented damage is not dealt (RULE 615.1), so it neither gains life nor is lethal.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import FightEffect, GameContext
from mtg_analyzer.game.effects.damage_draw import DealDamageEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player

START_LIFE = 20
PING = 3
BIG = 4


def _creature(name, power, toughness, *keywords):
    return Card(id=name, name=name, type_line="Creature — Test", is_creature=True, power=power,
                toughness=toughness, keywords=list(keywords), mana_cost_string="{1}",
                converted_mana_cost=1)


def _engine():
    state = GameState(players=[Player(id="p1", life=START_LIFE), Player(id="p2", life=START_LIFE)])
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine


def _put(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _life(engine, pid):
    return engine.state.player_by_id(pid).life


def _gains(engine):
    return [e for e in engine.state.event_log if e.type == EventType.LIFE_GAINED]


def test_lifelink_source_gains_life_from_noncombat_damage_to_player():
    eng = _engine()
    src = _put(eng, _creature("Vamp", 1, 1, "Lifelink"))
    eng.rules.deal_damage(eng.state.player_by_id("p2"), PING, source=src)
    assert _life(eng, "p2") == START_LIFE - PING
    assert _life(eng, "p1") == START_LIFE + PING


def test_lifelink_gains_from_noncombat_damage_to_creature():
    eng = _engine()
    src = _put(eng, _creature("Vamp", 1, 1, "Lifelink"))
    wall = _put(eng, _creature("Wall", 0, BIG), "p2")
    eng.rules.deal_damage(wall, PING, source=src)
    assert _life(eng, "p1") == START_LIFE + PING


def test_deathtouch_one_damage_kills_big_creature():
    eng = _engine()
    src = _put(eng, _creature("Snake", 1, 1, "Deathtouch"))
    big = _put(eng, _creature("Wall", 0, BIG), "p2")
    eng.rules.deal_damage(big, 1, source=src)
    eng.rules.check_state_based_actions()
    assert big not in eng.state.battlefield


def test_prevented_noncombat_damage_gives_no_life_and_no_deathtouch():
    eng = _engine()
    src = _put(eng, _creature("Nighthawk", 2, 3, "Deathtouch", "Lifelink"))
    big = _put(eng, _creature("Wall", 0, BIG), "p2")
    eng.rules.prevent_damage_from_source(src)
    eng.rules.deal_damage(big, PING, source=src)
    eng.rules.check_state_based_actions()
    assert big in eng.state.battlefield
    assert not big.dealt_deathtouch_damage
    assert _life(eng, "p1") == START_LIFE
    eng.rules.prevent_damage_to_player(eng.state.player_by_id("p2"), PING)
    eng.rules.deal_damage(eng.state.player_by_id("p2"), PING, source=src)
    assert _life(eng, "p1") == START_LIFE


def test_partial_prevention_gains_only_what_was_dealt():
    eng = _engine()
    src = _put(eng, _creature("Vamp", 1, 1, "Lifelink"))
    eng.rules.prevent_damage_to_player(eng.state.player_by_id("p2"), 2)
    eng.rules.deal_damage(eng.state.player_by_id("p2"), PING, source=src)
    assert _life(eng, "p1") == START_LIFE + 1


def test_effect_damage_to_each_creature_and_player_gains_once_for_summed_amount():
    eng = _engine()
    src = _put(eng, _creature("Vamp", 1, 5, "Lifelink"))
    _put(eng, _creature("Bear", 2, 2), "p2")
    DealDamageEffect(1, selector="each_creature_and_player", source=src).apply(
        GameContext(eng.state, eng.rules))
    # two creatures + two players, one damage each: a single gain event of 4
    assert _life(eng, "p1") == START_LIFE - 1 + 4
    assert [e.get("amount") for e in _gains(eng)] == [4]


def test_fight_with_deathtouch_lifelinker_gains_once_and_kills():
    eng = _engine()
    mine = _put(eng, _creature("Vamp", PING, 4, "Deathtouch", "Lifelink"))
    big = _put(eng, _creature("Wall", 1, 9), "p2")
    FightEffect(fighter_kind="creature_you_control", other_kind="creature_you_dont_control").apply(
        GameContext(eng.state, eng.rules), [mine, big])
    eng.rules.check_state_based_actions()
    assert big not in eng.state.battlefield
    assert _life(eng, "p1") == START_LIFE + PING
    assert [e.get("amount") for e in _gains(eng)] == [PING]


def test_lifelink_source_that_left_still_gains_from_its_last_damage():
    eng = _engine()
    src = _put(eng, _creature("Vamp", 2, 2, "Lifelink"))
    eng.rules.deal_damage(eng.state.player_by_id("p2"), PING, source=src)
    eng.rules.destroy(src)
    assert _life(eng, "p1") == START_LIFE + PING
