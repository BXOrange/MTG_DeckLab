"""Sulu multiplies his contribution, not his power, for Crew and Station."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.core import EffectRegistry
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=20); advance_to(engine,'main1')
    sulu=card(engine,'Sulu, Heroic Helmsman')
    vehicle=card(engine,'Consulate Dreadnought')
    ship=card(engine,'H.M.S. Bounty, Unlikely Timeship')
    return engine,sulu,vehicle,ship,engine.state.player_by_id('p1')


def test_fresh_specs_binding_and_unchanged_real_power():
    engine,sulu,vehicle,ship,player=board()
    a,b=specs_for(sulu.card),specs_for(sulu.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert sulu.power==sulu.card.power
    assert engine._crew_power_of(sulu)==3*sulu.power
    assert engine._crew_power_of(sulu,crewing=False)==sulu.power


def test_sulu_alone_crews_crew_six_vehicle():
    engine,sulu,vehicle,ship,player=board()
    before=sulu.power
    assert engine.can_activate(player,vehicle,vehicle.activated_abilities[0],tap_choices=[sulu.instance_id])
    engine.activate_ability(player,vehicle,0,tap_choices=[sulu.instance_id]); engine.resolve_until_stable()
    assert sulu.tapped and vehicle.is_creature and sulu.power==before


def test_ordinary_two_power_creature_cannot_pay_crew_six():
    engine,sulu,vehicle,ship,player=board()
    ordinary=filler(engine,'Ordinary',power=2,toughness=2)
    with pytest.raises(ValueError):
        engine.activate_ability(player,vehicle,0,tap_choices=[ordinary.instance_id])
    assert not ordinary.tapped


def test_station_uses_tripled_power_and_taps_sulu():
    engine,sulu,vehicle,ship,player=board(); before=sulu.power
    engine.activate_ability(player,ship,0,tap_choices=[sulu.instance_id]); engine.resolve_until_stable()
    assert sulu.tapped and ship.counters.get('charge')==3*before and sulu.power==before


def test_cost_choice_previews_use_same_contribution_as_payment():
    engine,sulu,vehicle,ship,player=board()
    crew=engine._crew_cost_choice(player,vehicle,vehicle.activated_abilities[0].cost)
    station=engine._station_cost_choice(player,ship,ship.activated_abilities[0].cost)
    for choice in [crew,station]:
        option=next(o for o in choice['options'] if o['instance_id']==sulu.instance_id)
        assert option['power']==3*sulu.power


def test_current_power_buffs_are_tripled():
    engine,sulu,vehicle,ship,player=board()
    EffectRegistry.create('pump',{'power':1,'toughness':1,'target_kind':'creature'}).apply(engine.rules.context,[sulu])
    engine.recompute_continuous_effects(); before=sulu.power
    engine.activate_ability(player,ship,0,tap_choices=[sulu.instance_id]); engine.resolve_until_stable()
    assert ship.counters.get('charge')==before*3 and sulu.power==before


def test_summoning_sick_sulu_can_station_another_permanent():
    engine,sulu,vehicle,ship,player=board(); sulu.summoning_sick=True
    engine.activate_ability(player,ship,0,tap_choices=[sulu.instance_id]); engine.resolve_until_stable()
    assert sulu.tapped and ship.counters.get('charge')==3*sulu.power


def test_negative_power_station_places_no_counters():
    engine,sulu,vehicle,ship,player=board()
    sulu.temp_power=-(sulu.power+2); engine.recompute_continuous_effects()
    assert sulu.power==-2
    engine.activate_ability(player,ship,0,tap_choices=[sulu.instance_id]); engine.resolve_until_stable()
    assert sulu.tapped and not ship.counters.get('charge',0)


def test_ability_loss_removes_multiplier():
    engine,sulu,vehicle,ship,player=board()
    card(engine,'Dress Down'); engine.recompute_continuous_effects()
    assert engine._crew_power_of(sulu)==sulu.power
    engine.activate_ability(player,ship,0,tap_choices=[sulu.instance_id]); engine.resolve_until_stable()
    assert ship.counters.get('charge')==sulu.power


def test_clone_preserves_station_activation_and_source_power_snapshot():
    engine,sulu,vehicle,ship,player=board(); before=sulu.power
    engine.activate_ability(player,ship,0,tap_choices=[sulu.instance_id])
    clone=GameEngine(engine.state.clone())
    clone.rules.exile(clone.state.find_object(sulu.instance_id)); clone.resolve_until_stable()
    assert clone.state.find_object(ship.instance_id).counters.get('charge')==before*3
    assert not ship.counters.get('charge',0)
