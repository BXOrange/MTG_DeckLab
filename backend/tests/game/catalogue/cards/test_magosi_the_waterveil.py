"""Magosi pays its eon counter before returning itself, and skip effects consume actual next turns."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,game,main_phase


def board(eons=0):
    engine=game(players=3,library=40);source=card(engine,'Magosi, the Waterveil');source.tapped=False
    if eons:source.add_counters('eon',eons)
    return engine,source


def charge(engine,source,resolve=True,player='p1'):
    p=engine.state.player_by_id(player);p.mana_pool.add('U',1)
    engine.activate_ability(p,source,0)
    if resolve:engine.resolve_until_stable()


def spend(engine,source,resolve=True,player='p1'):
    engine.activate_ability(engine.state.player_by_id(player),source,1)
    if resolve:engine.resolve_until_stable()


def skips(player):
    return [effect for effect in player.player_effects if getattr(effect,'skips_step',lambda step:False)('turn')]


def test_fresh_specs_bind_both_activated_abilities_and_native_mana():
    engine,source=board();a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.activated_abilities)==2 and len(mana_abilities_for(source,engine.state))==1


def test_real_land_play_enters_tapped():
    engine=game(library=30);source=card(engine,'Magosi, the Waterveil',zone=Zone.HAND)
    main_phase(engine);engine.play_land(engine.state.players[0],source)
    assert source.zone==Zone.BATTLEFIELD and source.tapped


def test_mana_ability_produces_blue_immediately():
    engine,source=board();engine.tap_for_mana(engine.state.players[0],source)
    assert source.tapped and engine.state.players[0].mana_pool.to_dict()['U']==1 and not engine.state.stack


def test_charge_pays_blue_and_tap_before_counter_and_skip_resolve():
    engine,source=board();charge(engine,source,resolve=False)
    assert source.tapped and not source.counters and not skips(engine.state.players[0])
    assert engine.state.players[0].mana_pool.total()==0
    engine.resolve_until_stable()
    assert source.counters['eon']==1 and len(skips(engine.state.players[0]))==1


def test_charge_requires_blue_and_an_untapped_land():
    engine,source=board()
    with pytest.raises(ValueError):engine.activate_ability(engine.state.players[0],source,0)
    source.tapped=True
    with pytest.raises(ValueError):charge(engine,source)
    assert not source.counters and not skips(engine.state.players[0])


def test_countered_charge_creates_no_counter_or_skipped_turn():
    engine,source=board();charge(engine,source,resolve=False)
    engine.rules.counter_ability(engine.state.stack[-1]);engine.resolve_until_stable()
    assert source.tapped and not source.counters and not skips(engine.state.players[0])


def test_departed_charge_source_does_not_get_counter_but_turn_is_still_skipped():
    engine,source=board();charge(engine,source,resolve=False)
    engine.rules.return_to_hand(source);engine.resolve_until_stable()
    assert source.zone==Zone.HAND and not source.counters and len(skips(engine.state.players[0]))==1


def test_skip_waits_for_your_next_turn_then_is_consumed():
    engine,source=board();charge(engine,source)
    order=[]
    for _ in range(5):engine.begin_turn();order.append(engine.state.active_player.id)
    assert order==['p2','p3','p2','p3','p1']
    assert not skips(engine.state.players[0])


def test_spend_removes_one_counter_before_zone_change_and_grants_turn_on_resolution():
    engine,source=board(2);visit=source.zone_incarnation;spend(engine,source,resolve=False)
    assert source.zone==Zone.HAND and source in engine.state.players[0].hand and not source.counters
    assert engine.state.zone_visit_counters[(source.instance_id,visit)].get('eon')==1
    assert source.counters_removed_as_cost==1 and engine.state.extra_turns==[]
    engine.resolve_until_stable();assert engine.state.extra_turns==['p1']


def test_extra_turn_is_taken_before_normal_next_player():
    engine,source=board(1);spend(engine,source)
    engine.begin_turn();assert engine.state.active_player.id=='p1'
    engine.begin_turn();assert engine.state.active_player.id=='p2'


def test_missing_counter_does_not_pay_other_costs():
    engine,source=board()
    with pytest.raises(ValueError):spend(engine,source)
    assert source.zone==Zone.BATTLEFIELD and not source.tapped and not engine.state.extra_turns


def test_tapped_land_cannot_remove_counter_or_return_itself():
    engine,source=board(1);source.tapped=True
    with pytest.raises(ValueError):spend(engine,source)
    assert source.zone==Zone.BATTLEFIELD and source.counters['eon']==1


def test_countering_extra_turn_leaves_land_in_hand_and_counter_paid():
    engine,source=board(1);spend(engine,source,resolve=False)
    engine.rules.counter_ability(engine.state.stack[-1]);engine.resolve_until_stable()
    assert source.zone==Zone.HAND and not source.counters and not engine.state.extra_turns


def test_pending_skip_consumes_the_extra_turn_before_regular_rotation():
    engine,source=board();charge(engine,source);source.tapped=False;spend(engine,source)
    engine.begin_turn()
    assert engine.state.active_player.id=='p2' and not engine.state.extra_turns
    assert not skips(engine.state.players[0])


def test_two_charge_resolutions_skip_two_separate_turns():
    engine,source=board();charge(engine,source);source.tapped=False;charge(engine,source)
    order=[]
    for _ in range(7):engine.begin_turn();order.append(engine.state.active_player.id)
    assert order==['p2','p3','p2','p3','p2','p3','p1']


def test_stolen_land_returns_to_owner_but_extra_turn_goes_to_activator():
    engine=game(players=3,library=40);source=card(engine,'Magosi, the Waterveil',player='p2')
    source.controller_id='p1';source.tapped=False;source.add_counters('eon',1)
    spend(engine,source)
    assert source in engine.state.players[1].hand and source.owner_id=='p2'
    assert engine.state.extra_turns==['p1']


def test_pending_extra_turn_survives_clone_without_repaying_cost():
    engine,source=board(1);spend(engine,source,resolve=False)
    restored=GameEngine(engine.state.clone());restored.resolve_until_stable()
    assert restored.state.extra_turns==['p1'] and engine.state.extra_turns==[]
    assert restored.state.find_object(source.instance_id).zone==Zone.HAND


def test_copy_of_paid_extra_turn_ability_grants_another_turn_without_another_counter():
    engine,source=board(1);spend(engine,source,resolve=False)
    engine.rules.copy_ability(engine.state.stack[-1],'p1');engine.resolve_until_stable()
    assert engine.state.extra_turns==['p1','p1'] and source.zone==Zone.HAND


def test_old_charge_does_not_put_counter_on_returned_land():
    engine,source=board();charge(engine,source,resolve=False)
    engine.rules.put_into_graveyard(source);engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD and not source.counters
    assert len(skips(engine.state.players[0]))==1


def test_charge_control_change_keeps_skip_with_original_activator():
    engine,source=board();charge(engine,source,resolve=False)
    source.controller_id='p2';engine.resolve_until_stable()
    assert source.counters['eon']==1 and len(skips(engine.state.players[0]))==1
    assert not skips(engine.state.players[1])
