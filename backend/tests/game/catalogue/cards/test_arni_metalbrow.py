"""Arni's optional payment and recursive attacking entries."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def _board(players=2):
    engine=game(players=players)
    advance_to(engine,'main1')
    arni=card(engine,'Arni Metalbrow')
    attacker=filler(engine,'Large',mv=6,power=4,toughness=4)
    return engine,arni,attacker,engine.state.player_by_id('p1')


def _attack(engine,attacker,player,pool=True):
    advance_to(engine,'declare_attackers')
    if pool:
        player.mana_pool.add_many({'R':4,'C':4})
    engine.declare_attackers(player,[{'attacker':attacker,'defender':engine.state.player_by_id('p2')}])
    engine.resolve_until_stable()


def _pay(engine):
    assert engine.state.pending_choice['kind']=='pay_cost_then'
    engine.resolve_pending_choice('pay')
    engine.resolve_until_stable()


def test_specs_and_binding():
    engine,arni,_,_=_board()
    a,b=specs_for(arni.card),specs_for(arni.card)
    assert len(a)==2 and a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(arni.triggered_abilities)==2


def test_hand_pick_strictly_less_creature_only_and_chain_retriggers():
    engine,arni,attacker,player=_board()
    small=filler(engine,'Small',mv=4,power=2,toughness=2,zone=Zone.HAND)
    tiny=filler(engine,'Tiny',mv=2,power=1,toughness=1,zone=Zone.HAND)
    equal=filler(engine,'Equal',mv=6,power=1,toughness=1,zone=Zone.HAND)
    noncreature=filler(engine,'Rock',type_line='Artifact',mv=1,zone=Zone.HAND)
    _attack(engine,attacker,player)
    _pay(engine)
    choice=engine.state.pending_choice
    assert choice['kind']=='arni_put_attacking'
    assert {o.get('instance_id') for o in choice['options'] if o['id']!='decline'}=={small.instance_id,tiny.instance_id}
    engine.resolve_pending_choice(str(small.instance_id))
    engine.resolve_until_stable()
    assert small.zone==Zone.BATTLEFIELD and small.tapped and small.attacking
    assert small.combat_defender['id']=='p2'
    assert not small.attacked_this_turn
    _pay(engine)
    assert {o.get('instance_id') for o in engine.state.pending_choice['options'] if o['id']!='decline'}=={tiny.instance_id}
    engine.resolve_pending_choice(str(tiny.instance_id))
    engine.resolve_until_stable()
    assert tiny.attacking and tiny.tapped
    engine.resolve_pending_choice('decline')
    engine.resolve_until_stable()
    assert equal in player.hand and noncreature in player.hand
    entries=[e for e in engine.state.event_log if e.type==EventType.ENTERS_ATTACKING]
    attacks=[e for e in engine.state.event_log if e.type==EventType.ATTACKS]
    assert len(entries)==2 and len(attacks)==1


@pytest.mark.parametrize('pay,pool',[(False,True),(True,False)])
def test_declined_or_unaffordable_payment(pay,pool):
    engine,_,attacker,player=_board()
    small=filler(engine,'Small',mv=2,power=1,toughness=1,zone=Zone.HAND)
    _attack(engine,attacker,player,pool=pool)
    if not pay:
        engine.resolve_pending_choice('decline')
        engine.resolve_until_stable()
    assert engine.state.pending_choice is None and small in player.hand


def test_may_decline_placement_after_paying():
    engine,_,attacker,player=_board()
    small=filler(engine,'Small',mv=2,power=1,toughness=1,zone=Zone.HAND)
    _attack(engine,attacker,player)
    before=player.mana_pool.total()
    _pay(engine)
    engine.resolve_pending_choice('decline')
    engine.resolve_until_stable()
    assert player.mana_pool.total()==before-2 and small in player.hand


def test_original_attacker_mana_value_uses_last_known_information():
    engine,_,attacker,player=_board()
    small=filler(engine,'Small',mv=5,power=2,toughness=2,zone=Zone.HAND)
    _attack(engine,attacker,player)
    engine.rules.exile(attacker)
    _pay(engine)
    assert str(small.instance_id) in {o['id'] for o in engine.state.pending_choice['options']}


def test_clone_preserves_payment_and_hand_placement():
    engine,_,attacker,player=_board()
    small=filler(engine,'Small',mv=2,power=1,toughness=1,zone=Zone.HAND)
    _attack(engine,attacker,player)
    clone=GameEngine(engine.state.clone())
    _pay(clone)
    clone=GameEngine(clone.state.clone())
    clone.resolve_pending_choice(str(small.instance_id))
    clone.resolve_until_stable()
    assert clone.state.find_object(small.instance_id).attacking
    assert small.zone==Zone.HAND


def test_arni_own_attack_is_included():
    engine,arni,_,player=_board()
    small=filler(engine,'Small',mv=2,power=1,toughness=1,zone=Zone.HAND)
    _attack(engine,arni,player)
    _pay(engine)
    assert str(small.instance_id) in {o['id'] for o in engine.state.pending_choice['options']}


def test_plain_entry_does_not_trigger():
    engine,_,_,_=_board()
    small=filler(engine,'Small',mv=2,power=1,toughness=1,zone=Zone.HAND)
    engine.state.player_by_id('p1').remove_from_zone(small,Zone.HAND)
    engine.rules._put_searched_card(engine.state.player_by_id('p1'),small,'battlefield')
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None


def test_entering_attacking_can_trigger_arni_itself_without_attacking_trigger():
    engine,arni,_,player=_board()
    engine.rules.exile(arni)
    advance_to(engine,'declare_attackers')
    player.mana_pool.add_many({'R':2,'C':2})
    player.remove_from_zone(arni,Zone.EXILE)
    engine.rules._put_searched_card(player,arni,'battlefield_attacking')
    engine.resolve_until_stable()
    assert arni.attacking and not arni.attacked_this_turn
    assert engine.state.pending_choice['kind']=='pay_cost_then'
    assert not [e for e in engine.state.event_log if e.type==EventType.ATTACKS]


def test_nonattacking_entry_outside_combat_does_not_trigger():
    engine,_,_,player=_board()
    small=filler(engine,'Small',mv=2,power=1,toughness=1,zone=Zone.HAND)
    player.remove_from_zone(small,Zone.HAND)
    engine.rules._put_searched_card(player,small,'battlefield_attacking')
    engine.resolve_until_stable()
    assert small.zone==Zone.BATTLEFIELD and small.tapped and not small.attacking
    assert engine.state.pending_choice is None


def test_entering_attacker_is_not_reported_twice():
    engine,_,attacker,player=_board()
    _attack(engine,attacker,player)
    engine.resolve_pending_choice('decline')
    small=filler(engine,'Entry',mv=4,power=2,toughness=2,zone=Zone.HAND)
    player.remove_from_zone(small,Zone.HAND)
    engine.rules._put_searched_card(player,small,'battlefield_attacking')
    engine.rules.put_onto_battlefield_attacking(small)
    engine.resolve_until_stable()
    entries=[e for e in engine.state.event_log if e.type==EventType.ENTERS_ATTACKING]
    assert len(entries)==1


def test_opponents_entering_attacker_does_not_trigger():
    engine,_,_,_=_board()
    engine.state.active_player_index=1
    advance_to(engine,'declare_attackers')
    opponent=engine.state.player_by_id('p2')
    opponent.mana_pool.add_many({'R':2,'C':2})
    small=filler(engine,'Opponent entry',player='p2',mv=4,power=2,toughness=2,zone=Zone.HAND)
    opponent.remove_from_zone(small,Zone.HAND)
    engine.rules._put_searched_card(opponent,small,'battlefield_attacking')
    engine.resolve_until_stable()
    assert small.attacking and engine.state.pending_choice is None


def test_multiplayer_placement_offers_defender_and_can_attack_different_opponent():
    engine,_,attacker,player=_board(players=3)
    small=filler(engine,'Entry',mv=4,power=2,toughness=2,zone=Zone.HAND)
    _attack(engine,attacker,player)
    _pay(engine)
    engine.resolve_pending_choice(str(small.instance_id))
    engine.resolve_until_stable()
    assert engine.state.pending_choice['kind']=='reselect_attack'
    engine.resolve_pending_choice('player:p3')
    engine.resolve_until_stable()
    assert small.combat_defender['id']=='p3'
    assert engine.state.pending_choice['kind']=='pay_cost_then'


def test_source_departure_after_attack_does_not_cancel_payment_or_placement():
    engine,arni,attacker,player=_board()
    small=filler(engine,'Entry',mv=4,power=2,toughness=2,zone=Zone.HAND)
    _attack(engine,attacker,player)
    engine.rules.exile(arni)
    _pay(engine)
    engine.resolve_pending_choice(str(small.instance_id))
    engine.resolve_until_stable()
    assert small.attacking and engine.state.pending_choice is None


@pytest.mark.parametrize('mana_value',[0,1])
def test_strict_mana_value_bound_at_zero(mana_value):
    engine,_,_,player=_board()
    attacker=filler(engine,'Low',mv=mana_value,power=1,toughness=1)
    zero=filler(engine,'Zero',mv=0,power=1,toughness=1,zone=Zone.HAND)
    _attack(engine,attacker,player)
    _pay(engine)
    if mana_value:
        assert str(zero.instance_id) in {o['id'] for o in engine.state.pending_choice['options']}
    else:
        assert engine.state.pending_choice is None
    assert zero in player.hand


def test_each_declared_attacker_triggers_independently():
    engine,arni,attacker,player=_board()
    advance_to(engine,'declare_attackers')
    player.mana_pool.add_many({'R':4,'C':4})
    opponent=engine.state.player_by_id('p2')
    engine.declare_attackers(player,[{'attacker':a,'defender':opponent} for a in (arni,attacker)])
    engine.resolve_until_stable()
    assert engine.state.pending_choice['kind']=='pay_cost_then'
    engine.resolve_pending_choice('decline')
    engine.resolve_until_stable()
    assert engine.state.pending_choice['kind']=='pay_cost_then'
    engine.resolve_pending_choice('decline')
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None


def test_payment_and_placement_keep_original_controller_after_control_change():
    engine,arni,attacker,player=_board()
    small=filler(engine,'Entry',mv=4,power=2,toughness=2,zone=Zone.HAND)
    _attack(engine,attacker,player)
    arni.controller_id='p2'
    engine.recompute_continuous_effects()
    _pay(engine)
    assert engine.state.pending_choice['player_id']=='p1'
    engine.resolve_pending_choice(str(small.instance_id))
    engine.resolve_until_stable()
    assert small.attacking and small.controller_id=='p1'
    assert engine.state.pending_choice is None


def test_later_visit_of_reference_creature_does_not_replace_lki():
    engine,_,attacker,player=_board()
    small=filler(engine,'Entry',mv=4,power=2,toughness=2,zone=Zone.HAND)
    _attack(engine,attacker,player)
    engine.rules.exile(attacker)
    engine.rules.return_from_graveyard(attacker,'battlefield')
    replacement=filler(engine,'New characteristics',mv=0,power=1,toughness=1)
    attacker.card=replacement.card
    engine.recompute_continuous_effects()
    _pay(engine)
    assert str(small.instance_id) in {o['id'] for o in engine.state.pending_choice['options']}
