"""Archnemesis checks player attacks once per declaration, with resumable attachment."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=4,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Archnemesis')
    source.attached_to='p2'
    return engine,source


def _attack(engine,attacker='p1',defenders=('p2',),resolve=True):
    engine.state.active_player_index=int(attacker[1:])-1
    advance_to(engine,'declare_attackers')
    creatures=[filler(engine,f'Attacker {i}',player=attacker,power=2,toughness=2) for i in range(len(defenders))]
    assignments=[{'attacker':c,'defender':engine.state.player_by_id(d) if isinstance(d,str) else d} for c,d in zip(creatures,defenders)]
    engine.declare_attackers(engine.state.player_by_id(attacker),assignments)
    engine.advance_step()
    if resolve:
        engine.resolve_until_stable()
    return creatures


def test_fresh_specs_and_bound_abilities():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert len(a)==3 and a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.triggered_abilities)==2


@pytest.mark.parametrize('defenders',[('p2',),('p2','p2'),('p3','p2'),('p2','p3')])
def test_own_attack_at_enchanted_player_triggers_once(defenders):
    engine,source=_board()
    before=len(engine.state.players[0].hand)
    _attack(engine,defenders=defenders)
    assert [p.life for p in engine.state.players]==[22,18,20,20]
    assert len(engine.state.players[0].hand)==before+1
    assert source.attached_to=='p2'


@pytest.mark.parametrize('attacker,defender',[('p1','p3'),('p3','p2')])
def test_other_attack_does_not_grant_rewards(attacker,defender):
    engine,source=_board()
    before=len(engine.state.players[0].hand)
    _attack(engine,attacker,(defender,))
    assert [p.life for p in engine.state.players]==[20]*4
    assert len(engine.state.players[0].hand)==before
    assert engine.state.pending_choice is None


@pytest.mark.parametrize('accept',[True,False])
@pytest.mark.parametrize('count',[1,2])
def test_attacked_controller_can_move_aura_to_attacker(accept,count):
    engine,source=_board()
    _attack(engine,'p3',('p1',)*count)
    choice=engine.state.pending_choice
    assert choice['kind']=='composite_optional' and choice['player_id']=='p1'
    engine.resolve_pending_choice('yes' if accept else 'decline')
    engine.resolve_until_stable()
    assert source.attached_to==('p3' if accept else 'p2')
    assert source.controller_id=='p1' and engine.state.pending_choice is None


@pytest.mark.parametrize('change',['reattach','leave','steal','clone'])
def test_reward_keeps_attacked_player_and_trigger_controller(change):
    engine,source=_board()
    before=len(engine.state.players[0].hand)
    _attack(engine,resolve=False)
    engine.rules.put_triggers_on_stack()
    if change=='reattach':
        source.attached_to='p3'
    elif change=='leave':
        engine.rules.exile(source)
    elif change=='steal':
        source.controller_id='p4'
    else:
        engine=GameEngine(engine.state.clone())
    engine.resolve_until_stable()
    assert [p.life for p in engine.state.players]==[22,18,20,20]
    assert len(engine.state.players[0].hand)==before+1


@pytest.mark.parametrize('change',['leave','return','clone'])
def test_attachment_question_preserves_original_aura_visit(change):
    engine,source=_board()
    _attack(engine,'p3',('p1',))
    if change in ('leave','return'):
        engine.rules.exile(source)
        if change=='return':
            engine.rules.return_from_graveyard(source,'battlefield')
            source.attached_to='p4'
    else:
        engine=GameEngine(engine.state.clone())
        source=engine.state.find_object(source.instance_id)
    engine.resolve_pending_choice('yes')
    engine.resolve_until_stable()
    if change=='leave':
        assert source.zone==Zone.EXILE and source.attached_to!='p3'
    else:
        assert source.attached_to==('p3' if change=='clone' else 'p4')


def test_real_cast_enchants_opponent():
    engine=game(players=3)
    advance_to(engine,'main1')
    source=card(engine,'Archnemesis',zone=Zone.HAND)
    cast(engine,source,targets=[engine.state.players[1]])
    assert source.zone==Zone.BATTLEFIELD and source.attached_to=='p2'


@pytest.mark.parametrize('attacker,walker_owner',[('p1','p2'),('p3','p1')])
def test_attack_at_planeswalker_does_not_count_as_attacking_player(attacker,walker_owner):
    engine,source=_board()
    walker=card(engine,'Jace Beleren',player=walker_owner)
    walker.counters['loyalty']=3
    _attack(engine,attacker,(walker,))
    assert engine.state.pending_choice is None
    assert [p.life for p in engine.state.players]==[20]*4


def test_entering_attacking_does_not_trigger():
    engine,source=_board()
    advance_to(engine,'declare_attackers')
    body=filler(engine,'Already attacking',power=2,toughness=2)
    engine.rules.put_onto_battlefield_attacking(body,defender={'kind':'player','id':'p2'})
    engine.resolve_until_stable()
    assert [p.life for p in engine.state.players]==[20]*4


def test_self_is_not_a_legal_aura_spell_target():
    engine=game()
    advance_to(engine,'main1')
    source=card(engine,'Archnemesis',zone=Zone.HAND)
    engine.state._physical_cast_validation=True
    with pytest.raises(ValueError,match='illegal targets'):
        cast(engine,source,targets=[engine.state.players[0]])
    assert source.zone==Zone.HAND and source.attached_to is None
