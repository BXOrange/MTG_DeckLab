"""Queen's Diamond is an immediate one-color commander-only mana source."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for, restriction_predicate_for_cast
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def board(charge=3):
    engine=game(players=3,library=20); advance_to(engine,'main1')
    diamond=card(engine,"Queen's Diamond")
    if charge:
        engine.rules.add_counters(diamond,charge,'charge')
    engine.recompute_continuous_effects()
    return engine,diamond,engine.state.player_by_id('p1')


def test_fresh_specs_and_exactly_one_mana_ability():
    engine,diamond,player=board()
    a,b=specs_for(diamond.card),specs_for(diamond.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    abilities=mana_abilities_for(diamond,engine.state)
    assert len(abilities)==1 and len(abilities[0].options)==5


@pytest.mark.parametrize('index,color',list(enumerate(['W','U','B','R','G'])))
def test_chosen_color_produces_charge_count_without_stack(index,color):
    engine,diamond,player=board()
    before=list(engine.state.stack)
    produced=engine.tap_for_mana(player,diamond,option_index=index)
    assert produced=={color:3} and diamond.tapped
    assert engine.state.stack==before and engine.state.pending_choice is None
    assert player.mana_pool.restricted[0]['amounts']=={color:3}
    assert player.mana_pool.restricted[0]['restriction']['owner_id']=='p1'


def test_zero_charge_still_can_tap_but_produces_no_mana():
    engine,diamond,player=board(0)
    produced=engine.tap_for_mana(player,diamond)
    assert sum(produced.values())==0 and diamond.tapped


def test_pool_can_cast_own_commander_but_not_other_spell():
    engine,diamond,player=board()
    engine.tap_for_mana(player,diamond)
    commander=filler(engine,'Commander',mv=3,power=2,toughness=2,zone=Zone.HAND)
    commander.is_commander=True
    other=filler(engine,'Other',mv=3,power=2,toughness=2,zone=Zone.HAND)
    assert engine.can_cast(player,commander) and not engine.can_cast(player,other)
    engine.cast_spell(player,commander); engine.resolve_until_stable()
    assert commander.zone==Zone.BATTLEFIELD


def test_your_commander_restriction_does_not_authorize_opponents_commander():
    engine,diamond,player=board()
    enemy=filler(engine,'Enemy commander',player='p2',zone=Zone.HAND,power=2,toughness=2)
    enemy.is_commander=True
    engine.tap_for_mana(player,diamond)
    restriction=player.mana_pool.restricted[0]['restriction']
    assert not restriction_predicate_for_cast(enemy)(restriction)


def test_pool_cannot_pay_activated_ability_even_on_commander():
    engine,diamond,player=board()
    engine.tap_for_mana(player,diamond)
    source=filler(engine,'Commander ability',power=2,toughness=2,oracle_text='{1}: Draw a card.')
    source.is_commander=True
    assert not engine.can_activate(player,source,source.activated_abilities[0])


def test_station_and_eight_charge_form():
    engine,diamond,player=board(0)
    worker=filler(engine,'Worker',power=8,toughness=8)
    engine.activate_ability(player,diamond,0,tap_choices=[worker.instance_id]); engine.resolve_until_stable()
    assert worker.tapped and diamond.counters.get('charge')==8
    assert diamond.is_creature and (diamond.power,diamond.toughness)==(5,5)
    assert all(combat.has(diamond,kw) for kw in ['flying','vigilance','haste'])
    assert engine.tap_for_mana(player,diamond,option_index=1)=={'U':8}


def test_options_recompute_from_current_charge_count():
    engine,diamond,player=board(2)
    assert mana_abilities_for(diamond,engine.state)[0].options[0]=={'W':2}
    engine.rules.add_counters(diamond,3,'charge')
    assert engine.tap_for_mana(player,diamond)=={'W':5}


def test_clone_preserves_restriction_and_dynamic_amount():
    engine,diamond,player=board()
    clone=GameEngine(engine.state.clone()); clone.recompute_continuous_effects()
    copied=clone.state.find_object(diamond.instance_id)
    assert clone.tap_for_mana(clone.state.player_by_id('p1'),copied,option_index=4)=={'G':3}
    assert not diamond.tapped
