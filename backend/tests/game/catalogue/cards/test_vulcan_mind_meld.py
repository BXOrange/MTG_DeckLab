"""Private reciprocal exile grants each exiler their own lasting play permissions."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.game_session import GameSession
from tests.support.deck_batch import card, game, cast, RICH
from tests.support.star_trek import advance_to


def board(opponent='p2',own_top='Opt',other_tops=('Lightning Bolt','Sol Ring')):
    engine=game(players=3,library=30); advance_to(engine,'main1')
    own=card(engine,own_top,zone=Zone.LIBRARY)
    others=[card(engine,name,player=opponent,zone=Zone.LIBRARY) for name in other_tops]
    spell=card(engine,'Vulcan Mind-Meld',zone=Zone.HAND)
    return engine,spell,own,others


def meld(engine,spell,opponent='p2'):
    cast(engine,spell,targets=[engine.state.player_by_id(opponent)])


def view_object(engine,obj,perspective):
    session=GameSession(engine,mode='replay',starting_hand=0)
    view=session.observer_view() if perspective is None else session.view(perspective)
    return next(o for p in view['state']['players'] for o in p['exile']
                if o['instance_id']==obj.instance_id)


def test_fresh_specs_and_bound_target():
    engine,spell,*_=board(); a,b=specs_for(spell.card),specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(spell.spell_effects)==1 and spell.spell_effects[0].target_spec.kind=='opponent'


@pytest.mark.parametrize('opponent',['p2','p3'])
def test_exiles_one_own_and_two_opposing_cards_and_grants_to_each_exiler(opponent):
    engine,spell,own,others=board(opponent); meld(engine,spell,opponent)
    state=engine.state
    assert own in state.player_by_id('p1').exile
    assert all(o in state.player_by_id(opponent).exile for o in others)
    assert state.temp_play_permission_player[own.instance_id]==opponent
    assert all(state.temp_play_permission_player[o.instance_id]=='p1' for o in others)
    assert all(o.face_down_in_exile and o.face_down_exile_viewers_explicit for o in [own,*others])
    assert own.face_down_exile_viewers=={opponent}
    assert all(o.face_down_exile_viewers=={'p1'} for o in others)
    assert all(o.instance_id in state.temp_play_permission_standing for o in [own,*others])
    assert all(state.mana_wildcard_permission[o.instance_id]=='type' for o in [own,*others])


@pytest.mark.parametrize('perspective',['p1','p2','p3',None])
def test_only_the_exiler_can_look_at_each_face_down_card(perspective):
    engine,spell,own,others=board(); meld(engine,spell)
    assert (view_object(engine,own,perspective)['name']=='Opt')==(perspective=='p2')
    for obj in others:
        assert (view_object(engine,obj,perspective)['name']==obj.name)==(perspective=='p1')


def test_public_and_other_seat_views_do_not_leak_hidden_names():
    import json
    engine,spell,own,others=board(); meld(engine,spell)
    session=GameSession(engine,mode='replay',starting_hand=0)
    for perspective in ['p1','p2','p3',None]:
        view=session.observer_view() if perspective is None else session.view(perspective)
        raw=json.dumps(view)
        if perspective!='p2': assert 'Opt' not in raw
        if perspective!='p1':
            assert 'Lightning Bolt' not in raw and 'Sol Ring' not in raw


def test_mana_of_any_type_pays_colored_cost_for_both_exilers():
    engine,spell,own,others=board(own_top='Llanowar Elves',other_tops=('Llanowar Elves','Sol Ring'))
    meld(engine,spell); p1,p2=engine.state.players[:2]
    p1.mana_pool=type(p1.mana_pool)(); p1.mana_pool.add('C',1)
    engine.cast_spell(p1,others[0]); engine.resolve_until_stable()
    assert others[0].zone==Zone.BATTLEFIELD and others[0].controller_id=='p1'
    assert not others[0].face_down_in_exile
    engine.state.active_player_index=1
    p2.mana_pool.add('C',1); engine.cast_spell(p2,own); engine.resolve_until_stable()
    assert own.zone==Zone.BATTLEFIELD and own.controller_id=='p2' and not own.face_down_in_exile


def test_permission_does_not_make_spells_free():
    engine,spell,own,others=board(); meld(engine,spell)
    player=engine.state.player_by_id('p1'); player.mana_pool=type(player.mana_pool)()
    assert not engine.can_cast(player,others[1])


def test_colored_mana_can_pay_an_explicit_colorless_requirement():
    engine,spell,own,others=board(other_tops=('Matter Reshaper','Sol Ring')); meld(engine,spell)
    player=engine.state.players[0]; player.mana_pool=type(player.mana_pool)()
    player.mana_pool.add('W',3)
    engine.cast_spell(player,others[0]); engine.resolve_until_stable()
    assert others[0].zone==Zone.BATTLEFIELD and player.mana_pool.total()==0


def test_owners_and_uninvolved_player_cannot_use_the_other_players_permissions():
    engine,spell,own,others=board(); meld(engine,spell)
    for player in engine.state.players: player.mana_pool.add_many(RICH)
    assert not engine.can_cast(engine.state.players[0],own)
    assert not engine.can_cast(engine.state.players[1],others[0],targets=[engine.state.players[0]])
    assert not engine.can_cast(engine.state.players[2],own)
    assert not engine.can_cast(engine.state.players[2],others[1])


def test_normal_timing_and_land_drop_limits_still_apply():
    engine,spell,own,others=board(other_tops=('Island','Mountain')); meld(engine,spell)
    p1=engine.state.players[0]
    engine.play_land(p1,others[0])
    assert others[0].zone==Zone.BATTLEFIELD and others[0].controller_id=='p1'
    assert not others[0].face_down_in_exile
    assert not engine.can_play_land(p1,others[1])
    engine.state.current_step='begin_combat'; engine.state.current_phase='combat'
    assert not engine.can_play_land(p1,others[1])


def test_sorcery_speed_card_cannot_be_cast_on_an_opponents_turn():
    engine,spell,own,others=board(own_top='Sol Ring'); meld(engine,spell)
    opponent=engine.state.players[1]; opponent.mana_pool.add_many(RICH)
    assert not engine.can_cast(opponent,own)


def test_permissions_survive_cleanup_and_subsequent_turns():
    engine,spell,own,others=board(); meld(engine,spell)
    for _ in range(2):
        advance_to(engine,'cleanup'); engine.advance_step(); advance_to(engine,'main1')
    for obj in [own,*others]:
        holder=engine.state.player_by_id(engine.state.temp_play_permission_player[obj.instance_id])
        assert engine._has_temp_play_permission(obj,holder)
        assert obj.face_down_in_exile


def test_leaving_exile_and_returning_does_not_restore_permission_or_viewers():
    engine,spell,own,others=board(); meld(engine,spell); target=others[1]
    engine.rules.return_to_hand(target); engine.rules.exile(target,face_down=True)
    p1=engine.state.players[0]; p1.mana_pool.add_many(RICH)
    assert not engine._has_temp_play_permission(target,p1)
    assert not engine.can_cast(p1,target)
    assert not target.face_down_exile_viewers


@pytest.mark.parametrize('own_size,other_size',[(0,0),(0,1),(1,0),(1,1)])
def test_short_libraries_exile_only_available_cards_without_losing(own_size,other_size):
    engine,spell,own,others=board()
    engine.state.players[0].library[:]=[own] if own_size else []
    engine.state.players[1].library[:]=others[:other_size]
    meld(engine,spell)
    assert len(engine.state.players[0].exile)==own_size
    assert len(engine.state.players[1].exile)==other_size
    assert all(not player.has_lost for player in engine.state.players)


def test_self_is_not_a_legal_target():
    from mtg_analyzer.game.targeting import legal_targets
    engine,spell,*_=board(); player=engine.state.players[0]; player.mana_pool.add_many(RICH)
    offered=legal_targets(engine.state,'p1',spell.spell_effects[0].target_spec,spell)
    assert {o['player_id'] for o in offered}=={'p2','p3'}
    cast(engine,spell,targets=[player])
    assert all(not p.exile for p in engine.state.players)


def test_clone_preserves_private_cards_and_permissions():
    engine,spell,own,others=board(); meld(engine,spell)
    clone=GameEngine(engine.state.clone()); moved=clone.state.find_object(others[1].instance_id)
    assert view_object(clone,moved,'p1')['name']=='Sol Ring'
    assert view_object(clone,moved,'p2')['name']!='Sol Ring'
    clone.state.players[0].mana_pool.add('C',1)
    clone.cast_spell(clone.state.players[0],moved); clone.resolve_until_stable()
    assert moved.zone==Zone.BATTLEFIELD and others[1].zone==Zone.EXILE


def test_countered_spell_does_not_exile_or_grant_any_cards():
    engine,spell,own,others=board(); player=engine.state.players[0]
    player.mana_pool.add('U',1)
    engine.cast_spell(player,spell,targets=[engine.state.players[1]])
    engine.rules.counter_spell(spell); engine.resolve_until_stable()
    assert own.zone==Zone.LIBRARY and all(obj.zone==Zone.LIBRARY for obj in others)
    assert not engine.state.temp_play_permissions


def test_clone_of_pending_spell_resolves_with_the_original_target():
    engine,spell,own,others=board(opponent='p3'); player=engine.state.players[0]
    player.mana_pool.add('U',1)
    engine.cast_spell(player,spell,targets=[engine.state.players[2]])
    clone=GameEngine(engine.state.clone()); clone.resolve_until_stable()
    assert clone.state.temp_play_permission_player[own.instance_id]=='p3'
    assert clone.state.temp_play_permission_player[others[0].instance_id]=='p1'
    assert own.zone==Zone.LIBRARY and not engine.state.temp_play_permissions
