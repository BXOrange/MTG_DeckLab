"""Troi offers the active opponent a free cast and copies that exact spell."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game
from tests.support.star_trek import advance_to


def board(name='Grizzly Bears'):
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,'Cmdr. Troi, Outgoing Empath')
    engine.state.active_player_index=1
    spell=card(engine,name,player='p2',zone=Zone.HAND) if name else None
    return engine,source,spell


def offer(engine,source):
    engine.activate_ability(engine.state.players[0],source,0,targets=[engine.state.players[1]])
    engine.resolve_until_stable()


def test_fresh_specs_and_vigilance_and_active_opponent_target():
    engine,source,spell=board(); a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert combat.has(source,'vigilance')
    spec=source.activated_abilities[0].effects[0].target_spec
    assert {o['player_id'] for o in legal_targets(engine.state,'p1',spec,source)}=={'p2'}
    engine.state.active_player_index=0
    assert legal_targets(engine.state,'p1',spec,source)==[]


def test_declining_draws_one_for_trois_controller_and_spends_tap_cost():
    engine,source,spell=board(); p1,p2=engine.state.players[:2]; before=len(p1.hand)
    offer(engine,source)
    assert engine.state.pending_choice['player_id']=='p2' and source.tapped
    engine.resolve_pending_choice('decline')
    assert len(p1.hand)==before+1 and spell.zone==Zone.HAND
    assert not engine.state.free_cast_instance_ids


@pytest.mark.parametrize('name',[None,'Forest'])
def test_empty_or_land_only_hand_draws_without_an_empty_cast_window(name):
    engine,source,spell=board(name); before=len(engine.state.players[0].hand)
    offer(engine,source)
    assert engine.state.pending_choice is None and len(engine.state.players[0].hand)==before+1


def test_free_creature_cast_creates_permanent_copy_above_original_without_extra_draw():
    engine,source,spell=board(); before=len(engine.state.players[0].hand)
    offer(engine,source); engine.state.players[1].mana_pool.empty()
    engine.play_resolution_card(engine.state.players[1],spell)
    assert len(engine.state.stack)==2
    assert engine.state.stack[0].obj is spell and engine.state.stack[0].controller_id=='p2'
    copy=engine.state.stack[1].obj
    assert copy is not spell and copy.is_copy and copy.controller_id=='p1'
    engine.resolve_until_stable()
    assert spell.zone==copy.zone==Zone.BATTLEFIELD and copy.is_token and not spell.is_token
    assert len(engine.state.players[0].hand)==before
    assert engine.state.players[1].mana_pool.total()==0


def test_copied_instant_can_choose_new_targets_independently():
    engine,source,spell=board('Lightning Bolt'); offer(engine,source)
    engine.play_resolution_card(engine.state.players[1],spell,targets=[engine.state.players[2]])
    choice=engine.state.pending_choice
    assert choice['kind']=='copy_targets' and choice['player_id']=='p1'
    option=next(o for o in choice['options'] if o.get('player_id')=='p2')
    engine.resolve_pending_choice(str(option['id'])); engine.resolve_until_stable()
    assert engine.state.players[1].life==17 and engine.state.players[2].life==17


def test_copy_can_keep_original_targets():
    engine,source,spell=board('Lightning Bolt'); offer(engine,source)
    engine.play_resolution_card(engine.state.players[1],spell,targets=[engine.state.players[2]])
    engine.resolve_pending_choice('keep'); engine.resolve_until_stable()
    assert engine.state.players[2].life==14


def test_only_hand_cards_are_offered_and_land_play_is_not_permitted():
    engine,source,spell=board(); land=card(engine,'Forest',player='p2',zone=Zone.HAND)
    other=card(engine,'Ornithopter',player='p2',zone=Zone.GRAVEYARD)
    offer(engine,source)
    assert other.instance_id not in engine.state.resolution_play_choice['instance_ids']
    assert not engine.can_play_land(engine.state.players[1],land)
    with pytest.raises(ValueError): engine.play_resolution_card(engine.state.players[1],land)
    assert engine.state.pending_choice['kind']=='play_during_resolution'


def test_failed_free_cast_attempt_does_not_grant_a_copy_or_draw():
    engine,source,spell=board('Fireball'); before=len(engine.state.players[0].hand)
    offer(engine,source)
    with pytest.raises(ValueError):
        engine.play_resolution_card(engine.state.players[1],spell,x=1,targets=[engine.state.players[2]])
    assert engine.state.pending_choice['kind']=='play_during_resolution'
    assert spell.zone==Zone.HAND and len(engine.state.players[0].hand)==before


@pytest.mark.parametrize('change',['exile','control'])
def test_source_departure_or_control_change_does_not_change_copy_controller(change):
    engine,source,spell=board()
    engine.activate_ability(engine.state.players[0],source,0,targets=[engine.state.players[1]])
    if change=='exile': engine.rules.exile(source)
    else: source.controller_id='p3'; engine.recompute_continuous_effects()
    engine.resolve_until_stable(); engine.play_resolution_card(engine.state.players[1],spell)
    assert engine.state.stack[-1].controller_id=='p1'


def test_target_no_longer_active_at_resolution_fizzles_without_a_draw():
    engine,source,spell=board(); before=len(engine.state.players[0].hand)
    engine.activate_ability(engine.state.players[0],source,0,targets=[engine.state.players[1]])
    engine.state.active_player_index=2; engine.resolve_until_stable()
    assert engine.state.pending_choice is None and len(engine.state.players[0].hand)==before


def test_countering_activation_does_not_offer_a_spell_or_draw():
    engine,source,spell=board(); before=len(engine.state.players[0].hand)
    engine.activate_ability(engine.state.players[0],source,0,targets=[engine.state.players[1]])
    engine.rules.counter_ability(engine.state.stack[-1]); engine.resolve_until_stable()
    assert source.tapped and spell.zone==Zone.HAND and len(engine.state.players[0].hand)==before


def test_clone_keeps_opponents_cast_choice_and_original_copy_controller():
    engine,source,spell=board(); offer(engine,source)
    clone=GameEngine(engine.state.clone()); selected=clone.state.find_object(spell.instance_id)
    clone.play_resolution_card(clone.state.players[1],selected); clone.resolve_until_stable()
    copies=[o for o in clone.state.permanents() if o.name=='Grizzly Bears' and o.is_token]
    assert len(copies)==1 and copies[0].controller_id=='p1'
    assert spell.zone==Zone.HAND and engine.state.pending_choice['player_id']=='p2'


def test_additional_sacrifice_is_paid_once_and_copied_spell_keeps_paid_information():
    engine,source,spell=board('Fling'); victim=card(engine,'Grizzly Bears',player='p2')
    offer(engine,source)
    engine.play_resolution_card(engine.state.players[1],spell,targets=[engine.state.players[2]])
    assert victim.zone==Zone.GRAVEYARD
    engine.resolve_pending_choice('keep'); engine.resolve_until_stable()
    assert engine.state.players[2].life==16


def test_declining_draw_can_be_replaced_by_dredge_without_repeating_payoff():
    engine,source,spell=board(); dredger=card(engine,'Golgari Brownscale',zone=Zone.GRAVEYARD)
    before=len(engine.state.players[0].hand); offer(engine,source)
    engine.resolve_pending_choice('decline')
    assert engine.state.pending_choice['kind']=='dredge'
    option=next(o for o in engine.state.pending_choice['options'] if o['id']!='decline')
    engine.resolve_pending_choice(str(option['id']))
    assert dredger.zone==Zone.HAND and len(engine.state.players[0].hand)==before+1
    assert engine.state.pending_choice is None and engine.state.resolution_play_choice is None


def test_opponents_hand_is_not_revealed_to_trois_controller():
    import json
    from mtg_analyzer.services.game_session import GameSession
    engine,source,spell=board(); offer(engine,source)
    session=GameSession(engine,mode='replay',starting_hand=0)
    assert 'Grizzly Bears' not in json.dumps(session.view('p1'))
    assert 'Grizzly Bears' in json.dumps(session.view('p2'))
