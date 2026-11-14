"""Unification's real Saga chapters, owner-specific draw and optional choices."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    saga=card(engine,'Unification',zone=Zone.HAND)
    player=engine.state.player_by_id('p1'); player.mana_pool.add_many(RICH)
    return engine,saga,player


def start(engine,saga,player):
    engine.cast_spell(player,saga); engine.resolve_until_stable()


def pick_object(engine,obj):
    choice=engine.state.pending_choice
    assert any(o.get('instance_id')==obj.instance_id for o in choice['options']), choice
    option=next(o for o in choice['options'] if o.get('instance_id')==obj.instance_id)
    engine.resolve_pending_choice(str(option['id']))


def next_chapter(engine,saga):
    engine.rules.add_counters(saga,1,'lore'); engine.resolve_until_stable()


def decline_first(engine,saga,player):
    start(engine,saga,player)
    if engine.state.pending_choice:
        engine.resolve_pending_choice('decline')


def test_fresh_specs_and_saga_binding():
    engine,saga,player=board()
    a,b=specs_for(saga.card),specs_for(saga.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(saga.triggered_abilities)==3


@pytest.mark.parametrize('owner',['p1','p2','p3'])
def test_first_chapter_draws_for_owner_then_shuffles_creature(owner):
    engine,saga,player=board()
    creature=filler(engine,'Creature',player=owner,power=3,toughness=3)
    creature.controller_id='p2' if owner=='p1' else 'p1'
    hands={p.id:len(p.hand) for p in engine.state.players}
    start(engine,saga,player); pick_object(engine,creature)
    assert creature.zone==Zone.LIBRARY
    assert creature in engine.state.player_by_id(owner).library
    for p in engine.state.players:
        assert len(p.hand)==hands[p.id]-(p.id=='p1')+2*(p.id==owner)
    assert saga.counters.get('lore')==1


def test_declining_first_chapter_draws_nothing():
    engine,saga,player=board()
    creature=filler(engine,'Creature',power=3,toughness=3)
    before=len(player.hand)
    decline_first(engine,saga,player)
    assert len(player.hand)==before-1 and creature.zone==Zone.BATTLEFIELD


@pytest.mark.parametrize('zone',[Zone.HAND,Zone.GRAVEYARD])
def test_second_chapter_puts_spacecraft_from_hand_or_graveyard(zone):
    engine,saga,player=board()
    ship=filler(engine,'Ship',type_line='Artifact — Spacecraft',zone=zone)
    decline_first(engine,saga,player)
    next_chapter(engine,saga)
    if any(o['id']=='do' for o in engine.state.pending_choice['options']):
        engine.resolve_pending_choice('do')
    pick_object(engine,ship)
    assert ship.zone==Zone.BATTLEFIELD and not ship.tapped


def test_second_chapter_can_decline_and_excludes_other_creatures():
    engine,saga,player=board()
    ship=filler(engine,'Ship',type_line='Artifact — Spacecraft',zone=Zone.HAND)
    creature=card(engine,'Serra Angel',zone=Zone.HAND)
    decline_first(engine,saga,player); next_chapter(engine,saga)
    if any(o['id']=='do' for o in engine.state.pending_choice['options']):
        engine.resolve_pending_choice('do')
    assert creature.instance_id not in {o.get('instance_id') for o in engine.state.pending_choice['options']}
    engine.resolve_pending_choice('decline')
    assert ship.zone==Zone.HAND


def test_third_chapter_draws_for_you_and_chosen_opponent_then_sacrifices_saga():
    engine,saga,player=board()
    decline_first(engine,saga,player); next_chapter(engine,saga)
    if engine.state.pending_choice:
        engine.resolve_pending_choice('decline')
    hands={p.id:len(p.hand) for p in engine.state.players}
    next_chapter(engine,saga)
    choice=engine.state.pending_choice
    assert any(o.get('id')=='p3' for o in choice['options']), choice
    option=next(o for o in choice['options'] if o.get('id')=='p3')
    engine.resolve_pending_choice(str(option['id']))
    assert saga.zone==Zone.GRAVEYARD
    assert len(player.hand)==hands['p1']+2
    assert len(engine.state.player_by_id('p3').hand)==hands['p3']+2
    assert len(engine.state.player_by_id('p2').hand)==hands['p2']


def test_clone_retains_first_chapter_target_choice():
    engine,saga,player=board()
    creature=filler(engine,'Creature',player='p2',power=3,toughness=3)
    start(engine,saga,player)
    clone=GameEngine(engine.state.clone())
    pick_object(clone,clone.state.find_object(creature.instance_id))
    assert clone.state.find_object(creature.instance_id).zone==Zone.LIBRARY
    assert creature.zone==Zone.BATTLEFIELD


def test_draw_replacement_choice_defers_shuffle_and_survives_clone():
    engine,saga,player=board()
    creature=filler(engine,'Creature',player='p2',power=3,toughness=3)
    card(engine,'Golgari Brownscale',player='p2',zone=Zone.GRAVEYARD)
    start(engine,saga,player); pick_object(engine,creature)
    assert engine.state.pending_choice['kind']=='dredge'
    assert creature.zone==Zone.BATTLEFIELD
    clone=GameEngine(engine.state.clone())
    while clone.state.pending_choice:
        clone.resolve_pending_choice('decline')
    assert clone.state.find_object(creature.instance_id).zone==Zone.LIBRARY
    assert creature.zone==Zone.BATTLEFIELD


def test_draws_are_taken_before_creature_is_shuffled_in():
    engine,saga,player=board()
    creature=filler(engine,'Creature',player='p2',power=3,toughness=3)
    owner=engine.state.player_by_id('p2')
    top_ids={o.instance_id for o in owner.library[-2:]}
    start(engine,saga,player); pick_object(engine,creature)
    assert top_ids.issubset({o.instance_id for o in owner.hand})
    assert creature.zone==Zone.LIBRARY


def test_leaving_target_before_chapter_resolution_draws_nothing():
    engine,saga,player=board()
    creature=filler(engine,'Creature',player='p2',power=3,toughness=3)
    start(engine,saga,player)
    option=next(o for o in engine.state.pending_choice['options'] if o.get('instance_id')==creature.instance_id)
    engine.rules.resolve_choice(str(option['id']))
    engine.rules.exile(creature)
    engine.resolve_until_stable()
    assert not engine.state.player_by_id('p2').hand and creature.zone==Zone.EXILE
