"""Krovikan Sorcerer's color costs and restricted just-drawn discard."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game


def board():
    engine = game(players=3, library=40)
    source = card(engine,'Krovikan Sorcerer')
    return engine,source,engine.state.players[0]


def hand(engine,name,cost='',**kwargs):
    return filler(engine,name,type_line='Instant',mana_cost_string=cost,zone=Zone.HAND,**kwargs)


def activate(engine,source,index,obj):
    engine.activate_ability(engine.state.players[0],source,index,discard_choices=[obj.instance_id])


def test_fresh_specs_bind_two_tap_abilities():
    engine,source,player = board()
    a,b = specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.activated_abilities)==2
    assert all(ability.cost.taps_self for ability in source.activated_abilities)


def test_actual_cast_nonblack_discards_then_draws_one():
    engine = game(library=40)
    source = card(engine,'Krovikan Sorcerer',zone=Zone.HAND)
    cast(engine,source)
    source.summoning_sick=False
    obj=hand(engine,'Blue','{U}')
    activate(engine,source,0,obj)
    assert source.tapped and obj.zone==Zone.GRAVEYARD and not engine.state.players[0].hand
    engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==1


@pytest.mark.parametrize('cost,kwargs,branch',[
    ('{B}',{},1),('{U}{B}',{},1),('{U}',{},0),('{1}',{'color_identity':{'B'}},0),
    ('{B}',{'keywords':['Devoid']},0),
])
def test_actual_colors_determine_cost_pool(cost,kwargs,branch):
    engine,source,player=board()
    obj=hand(engine,'Color case',cost,**kwargs)
    actions=[a for a in engine.legal_actions(player) if a['type']=='activate_ability' and a['instance_id']==source.instance_id]
    assert {a['ability_index'] for a in actions}=={branch}
    assert actions[0]['discard_cost']['options'][0]['instance_id']==obj.instance_id
    activate(engine,source,branch,obj)
    assert obj.zone==Zone.GRAVEYARD and source.tapped


@pytest.mark.parametrize('branch,cost',[(0,'{B}'),(1,'{U}')])
def test_wrong_color_cannot_pay_or_tap(branch,cost):
    engine,source,player=board()
    obj=hand(engine,'Wrong',cost)
    with pytest.raises(ValueError): activate(engine,source,branch,obj)
    assert not source.tapped and obj.zone==Zone.HAND


def test_black_branch_offers_only_the_two_new_draws():
    engine,source,player=board()
    old=hand(engine,'Old card','{U}')
    paid=hand(engine,'Paid black','{B}')
    activate(engine,source,1,paid)
    engine.resolve_until_stable()
    choice=engine.state.pending_choice
    assert choice is not None
    offered={option['instance_id'] for option in choice['options']}
    drawn=[obj for obj in player.hand if obj is not old]
    assert offered=={obj.instance_id for obj in drawn} and len(drawn)==2
    assert old.instance_id not in offered
    engine.resolve_pending_choice(str(drawn[1].instance_id))
    engine.resolve_until_stable()
    assert drawn[1].zone==Zone.GRAVEYARD and old.zone==Zone.HAND
    assert len(player.hand)==2


def test_old_hand_card_is_rejected_by_resolution_discard_choice():
    engine,source,player=board()
    old=hand(engine,'Old','{U}')
    paid=hand(engine,'Paid','{B}')
    activate(engine,source,1,paid)
    engine.resolve_until_stable()
    with pytest.raises(ValueError): engine.resolve_pending_choice(str(old.instance_id))
    assert old.zone==Zone.HAND


def test_single_actual_draw_is_forced_to_be_discarded():
    engine,source,player=board()
    old=hand(engine,'Old','{U}')
    paid=hand(engine,'Paid','{B}')
    for obj in list(player.library)[:-1]: engine.rules.exile(obj)
    from mtg_analyzer.game.effects.core import ReplacementEffect
    from mtg_analyzer.models.game.events import EventType
    source.replacement_effects.append(ReplacementEffect(EventType.DRAW, lambda e,c: None,
        condition=lambda e,c: not player.library, source=source))
    activate(engine,source,1,paid)
    engine.resolve_until_stable()
    assert old.zone==Zone.HAND and len(player.hand)==1
    assert len(player.graveyard)==2


def test_countered_black_ability_keeps_cost_paid_without_draw_or_later_discard():
    engine,source,player=board()
    old=hand(engine,'Old','{U}')
    paid=hand(engine,'Paid','{B}')
    activate(engine,source,1,paid)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert source.tapped and player.hand==[old]


def test_source_departure_keeps_draw_and_restricted_discard():
    engine,source,player=board()
    paid=hand(engine,'Paid','{B}')
    activate(engine,source,1,paid)
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert engine.state.pending_choice and len(player.hand)==2
    engine.resolve_pending_choice(str(player.hand[-1].instance_id))
    engine.resolve_until_stable()
    assert len(player.hand)==1


def test_clone_pending_discard_preserves_eligible_new_draws():
    engine,source,player=board()
    old=hand(engine,'Old','{U}')
    paid=hand(engine,'Paid','{B}')
    activate(engine,source,1,paid)
    engine.resolve_until_stable()
    restored=GameEngine(engine.state.clone())
    chosen=next(obj for obj in restored.state.players[0].hand if obj.instance_id!=old.instance_id)
    restored.resolve_pending_choice(str(chosen.instance_id))
    restored.resolve_until_stable()
    assert len(restored.state.players[0].hand)==2 and len(player.hand)==3


@pytest.mark.parametrize('tapped,sick',[(True,False),(False,True)])
def test_tap_and_summoning_sickness_are_enforced(tapped,sick):
    engine,source,player=board()
    paid=hand(engine,'Paid','{U}')
    source.tapped,source.summoning_sick=tapped,sick
    with pytest.raises(ValueError): activate(engine,source,0,paid)
    assert paid.zone==Zone.HAND


def test_no_hand_card_means_neither_ability_is_offered():
    engine,source,player=board()
    assert not any(a['type']=='activate_ability' and a['instance_id']==source.instance_id for a in engine.legal_actions(player))


def test_interrupted_draw_and_clone_discard_only_actual_draw_not_replacement_card():
    engine,source,player=board()
    old=hand(engine,'Old','{U}')
    paid=hand(engine,'Paid','{B}')
    dredger=filler(engine,'Replacement card',type_line='Creature',zone=Zone.GRAVEYARD)
    dredger.parametric_keywords['dredge']={'n':1}
    activate(engine,source,1,paid)
    engine.resolve_until_stable()
    assert engine.state.pending_choice['kind']=='dredge'
    restored=GameEngine(engine.state.clone())
    restored.resolve_pending_choice(str(dredger.instance_id))
    restored.resolve_until_stable()
    p=restored.state.players[0]
    assert {obj.instance_id for obj in p.hand}=={old.instance_id,dredger.instance_id}
    assert len(p.graveyard)==3  # paid cost, milled card, only actual draw
    assert engine.state.pending_choice['kind']=='dredge' and dredger.zone==Zone.GRAVEYARD


def test_two_replaced_draws_do_not_discard_an_older_hand_card():
    engine,source,player=board()
    engine.rules.draw(player,1)
    old=player.hand[-1]
    paid=hand(engine,'Paid','{B}')
    dredgers=[filler(engine,f'Replacement {i}',type_line='Creature',zone=Zone.GRAVEYARD) for i in range(2)]
    for obj in dredgers: obj.parametric_keywords['dredge']={'n':1}
    activate(engine,source,1,paid)
    engine.resolve_until_stable()
    for obj in dredgers:
        assert engine.state.pending_choice['kind']=='dredge'
        engine.resolve_pending_choice(str(obj.instance_id))
        engine.resolve_until_stable()
    assert set(obj.instance_id for obj in player.hand)=={old.instance_id,*[obj.instance_id for obj in dredgers]}
    assert engine.state.pending_choice is None
