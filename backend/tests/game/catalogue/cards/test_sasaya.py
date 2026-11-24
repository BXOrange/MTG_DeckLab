"""Sasaya reveals as a cost and Essence multiplies same-name land taps off-stack."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, activate
from tests.support.star_trek import advance_to


def _board(lands=7):
    engine=game(players=2,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Sasaya, Orochi Ascendant')
    player=engine.state.players[0]
    for obj in list(player.hand):
        player.remove_from_zone(obj,Zone.HAND)
        player.add_to_zone(obj,Zone.LIBRARY)
    hand=[card(engine,'Forest',zone=Zone.HAND) for _ in range(lands)]
    return engine,source,hand


def _flip(engine,source):
    activate(engine,source)
    assert source.flipped and source.name=="Sasaya's Essence"


def test_fresh_specs_and_reveal_hand_is_a_real_cost():
    engine,source,hand=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    cost=source.activated_abilities[0].cost
    assert cost.reveal_hand and not cost.is_free and cost.to_dict()['reveal_hand']


@pytest.mark.parametrize('lands',[0,6,7,8])
def test_reveal_all_cards_even_below_land_threshold(lands):
    engine,source,hand=_board(lands)
    nonland=filler(engine,'Hidden spell',type_line='Instant',zone=Zone.HAND)
    activate(engine,source)
    assert source.flipped==(lands>=7)
    assert all(o.zone==Zone.HAND for o in hand+[nonland])
    revealed=[e.get('instance_id') for e in engine.state.events_this_turn() if e.type=='REVEAL']
    assert set(revealed)=={o.instance_id for o in hand+[nonland]}


def test_land_count_is_rechecked_on_resolution_after_reveal_cost():
    engine,source,hand=_board(7)
    engine.activate_ability(engine.state.players[0],source,0)
    engine.rules.discard_specific(hand[0])
    engine.resolve_until_stable()
    assert not source.flipped
    assert any(e.type=='REVEAL' and e.get('instance_id')==hand[0].instance_id for e in engine.state.events_this_turn())


def test_countered_activation_still_revealed_hand():
    engine,source,hand=_board()
    engine.activate_ability(engine.state.players[0],source,0)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert not source.flipped
    assert len([e for e in engine.state.events_this_turn() if e.type=='REVEAL'])==7


def test_three_forests_each_produce_three_mana_without_stack():
    engine,source,hand=_board()
    _flip(engine,source)
    lands=[card(engine,'Forest') for _ in range(3)]
    for land in lands:
        engine.tap_for_mana(engine.state.players[0],land)
    assert engine.state.players[0].mana_pool.total()==9
    assert not engine.state.stack and engine.state.pending_choice is None


@pytest.mark.parametrize('names,expected',[(['Forest'],1),(['Forest','Snow-Covered Forest'],1),(['Wastes','Wastes','Wastes'],3)])
def test_only_other_lands_with_exact_same_name_count(names,expected):
    engine,source,hand=_board()
    _flip(engine,source)
    lands=[card(engine,n) for n in names]
    card(engine,names[0],player='p2')
    engine.tap_for_mana(engine.state.players[0],lands[0])
    assert engine.state.players[0].mana_pool.total()==expected


def test_opponents_land_does_not_trigger_essence():
    engine,source,hand=_board()
    _flip(engine,source)
    other=card(engine,'Forest',player='p2')
    engine.tap_for_mana(engine.state.players[1],other)
    assert engine.state.players[1].mana_pool.total()==1
    assert engine.state.players[0].mana_pool.total()==0


def test_multi_type_land_extra_mana_can_be_split_and_clone_resumes():
    engine,source,hand=_board()
    _flip(engine,source)
    lands=[card(engine,'Gruul Turf') for _ in range(3)]
    engine.tap_for_mana(engine.state.players[0],lands[0])
    assert engine.state.pending_choice['kind']=='add_mana_any_color'
    assert {o['id'] for o in engine.state.pending_choice['options']}=={'R','G'}
    engine.resolve_pending_choice('R')
    engine=GameEngine(engine.state.clone())
    engine.resolve_pending_choice('G')
    assert engine.state.pending_choice is None
    pool=engine.state.players[0].mana_pool
    assert pool.total()==4
    assert pool.to_dict().get('R')==2 and pool.to_dict().get('G')==2


def test_control_change_uses_new_controllers_lands():
    engine,source,hand=_board()
    _flip(engine,source)
    source.controller_id='p2'
    engine.recompute_continuous_effects()
    lands=[card(engine,'Forest',player='p2') for _ in range(2)]
    engine.tap_for_mana(engine.state.players[1],lands[0])
    assert engine.state.players[1].mana_pool.total()==2


def test_leaving_and_returning_restores_front_and_removes_multiplier():
    engine,source,hand=_board()
    _flip(engine,source)
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    lands=[card(engine,'Forest') for _ in range(2)]
    engine.tap_for_mana(engine.state.players[0],lands[0])
    assert not source.flipped and engine.state.players[0].mana_pool.total()==1


def test_gaining_seventh_land_before_resolution_can_flip():
    engine,source,hand=_board(6)
    engine.activate_ability(engine.state.players[0],source,0)
    last=card(engine,'Forest',zone=Zone.HAND)
    engine.resolve_until_stable()
    assert source.flipped
    assert not any(e.type=='REVEAL' and e.get('instance_id')==last.instance_id for e in engine.state.events_this_turn())


def test_empty_hand_can_pay_reveal_hand_cost():
    engine,source,hand=_board(0)
    activate(engine,source)
    assert not source.flipped and not engine.state.stack


def test_plain_tap_does_not_add_mana():
    engine,source,hand=_board()
    _flip(engine,source)
    lands=[card(engine,'Forest') for _ in range(2)]
    engine.rules.set_tapped(lands[0],True)
    engine.resolve_until_stable()
    assert engine.state.players[0].mana_pool.total()==0


def test_front_and_back_cloned_specs_are_independent():
    engine,source,hand=_board()
    _flip(engine,source)
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    clone=GameEngine(engine.state.clone())
    lands=[card(clone,'Forest') for _ in range(2)]
    clone.tap_for_mana(clone.state.players[0],lands[0])
    assert clone.state.players[0].mana_pool.total()==2
    assert engine.state.players[0].mana_pool.total()==0
