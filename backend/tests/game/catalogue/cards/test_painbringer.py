"""Painbringer pays exact chosen graveyard cards and freezes their count as X."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,cast,filler,game


def board(count=3):
    engine=game(players=3,library=30)
    source=card(engine,'Painbringer')
    cards=[filler(engine,f'Cost {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(count)]
    target=filler(engine,'Victim',type_line='Creature',player='p2',power=6,toughness=7)
    return engine,source,cards,target


def activate(engine,source,target,x,cards=None):
    engine.activate_ability(engine.state.players[0],source,0,x=x,targets=[target],
                            hand_card_choices=None if cards is None else [obj.instance_id for obj in cards])


def test_fresh_specs_and_binding():
    engine,source,cards,target=board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.activated_abilities)==1


def test_actual_cast_then_choose_two_cards_before_debuff():
    engine=game(library=30)
    source=card(engine,'Painbringer',zone=Zone.HAND)
    cast(engine,source)
    source.summoning_sick=False
    cards=[filler(engine,f'Cost {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(3)]
    target=filler(engine,'Victim',type_line='Creature',player='p2',power=6,toughness=7)
    activate(engine,source,target,2,[cards[0],cards[2]])
    assert source.tapped and cards[0].zone==cards[2].zone==Zone.EXILE and cards[1].zone==Zone.GRAVEYARD
    assert (target.power,target.toughness)==(6,7)
    engine.resolve_until_stable()
    assert (target.power,target.toughness)==(4,5)


def test_zero_is_legal_with_an_empty_graveyard():
    engine,source,cards,target=board(0)
    activate(engine,source,target,0,[])
    engine.resolve_until_stable()
    assert source.tapped and (target.power,target.toughness)==(6,7)


@pytest.mark.parametrize('x,indices',[(0,[0]),(1,[]),(1,[0,1]),(2,[0,0]),(4,[0,1,2])])
def test_wrong_count_or_repeated_card_pays_nothing(x,indices):
    engine,source,cards,target=board()
    with pytest.raises(ValueError):activate(engine,source,target,x,[cards[i] for i in indices])
    assert not source.tapped and all(obj.zone==Zone.GRAVEYARD for obj in cards)


def test_opponents_graveyard_card_cannot_pay():
    engine,source,cards,target=board()
    foreign=filler(engine,'Foreign',type_line='Instant',player='p2',zone=Zone.GRAVEYARD)
    with pytest.raises(ValueError):activate(engine,source,target,1,[foreign])
    assert not source.tapped and foreign.zone==Zone.GRAVEYARD


def test_hand_card_cannot_pay():
    engine,source,cards,target=board()
    hand=filler(engine,'Hand',type_line='Instant',zone=Zone.HAND)
    with pytest.raises(ValueError):activate(engine,source,target,1,[hand])
    assert not source.tapped


def test_offer_bounds_x_and_exposes_every_own_graveyard_card():
    engine,source,cards,target=board()
    action=next(a for a in engine.legal_actions(engine.state.players[0]) if a['type']=='activate_ability' and a['instance_id']==source.instance_id)
    assert action['has_x'] and action['min_x']==0 and action['max_x']==3
    assert action['graveyard_exile_cost']['count']=='x'
    assert {o['instance_id'] for o in action['graveyard_exile_cost']['options']}=={obj.instance_id for obj in cards}


def test_countering_keeps_exile_cost_paid_without_debuff():
    engine,source,cards,target=board()
    activate(engine,source,target,2,cards[:2])
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert all(obj.zone==Zone.EXILE for obj in cards[:2])
    assert (target.power,target.toughness)==(6,7)


def test_source_departure_does_not_change_paid_x():
    engine,source,cards,target=board()
    activate(engine,source,target,2,cards[:2])
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert (target.power,target.toughness)==(4,5)


def test_clone_preserves_pending_debuff_and_chosen_cost():
    engine,source,cards,target=board()
    activate(engine,source,target,2,cards[:2])
    restored=GameEngine(engine.state.clone())
    restored.resolve_until_stable()
    copied=restored.state.find_object(target.instance_id)
    assert (copied.power,copied.toughness)==(4,5) and (target.power,target.toughness)==(6,7)


def test_separate_activations_keep_their_own_paid_counts():
    engine,source,cards,target=board()
    activate(engine,source,target,2,cards[:2])
    source.tapped=False
    activate(engine,source,target,1,cards[2:])
    engine.resolve_until_stable()
    assert (target.power,target.toughness)==(3,4)


def test_zero_activation_clears_previous_exile_receipt():
    engine,source,cards,target=board()
    activate(engine,source,target,1,cards[:1])
    source.tapped=False
    activate(engine,source,target,0,[])
    assert source.last_cost_exiled_ids==[]
    engine.resolve_until_stable()
    assert (target.power,target.toughness)==(5,6)


@pytest.mark.parametrize('tapped,sick',[(True,False),(False,True)])
def test_symbol_tap_restrictions_are_enforced(tapped,sick):
    engine,source,cards,target=board()
    source.tapped,source.summoning_sick=tapped,sick
    with pytest.raises(ValueError):activate(engine,source,target,1,cards[:1])
    assert cards[0].zone==Zone.GRAVEYARD


def test_automatic_payment_takes_exactly_x_cards():
    engine,source,cards,target=board()
    activate(engine,source,target,2)
    assert cards[0].zone==cards[1].zone==Zone.EXILE and cards[2].zone==Zone.GRAVEYARD


def test_debuff_ends_at_cleanup():
    engine,source,cards,target=board()
    activate(engine,source,target,2,cards[:2])
    engine.resolve_until_stable()
    assert (target.power,target.toughness)==(4,5)
    engine.state.current_step='cleanup'
    engine._step_cleanup()
    engine.recompute_continuous_effects()
    assert (target.power,target.toughness)==(6,7)


def test_invalid_noncreature_target_does_not_pay_cost():
    engine,source,cards,target=board()
    wrong=filler(engine,'Artifact',type_line='Artifact')
    with pytest.raises(ValueError):activate(engine,source,wrong,2,cards[:2])
    assert not source.tapped and all(obj.zone==Zone.GRAVEYARD for obj in cards)


def test_returned_target_is_not_affected_but_cost_stays_paid():
    engine,source,cards,target=board()
    activate(engine,source,target,2,cards[:2])
    engine.rules.put_into_graveyard(target)
    engine.rules.return_from_graveyard(target,'battlefield')
    engine.resolve_until_stable()
    assert (target.power,target.toughness)==(6,7)
    assert all(obj.zone==Zone.EXILE for obj in cards[:2])
