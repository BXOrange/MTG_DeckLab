"""Boulder Jockey's {D} payments, land accounting and attacking token."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from tests.support.deck_batch import card, cast, game
from tests.support.star_trek import advance_to


def _board(zone=Zone.BATTLEFIELD,players=2):
    engine=game(players=players)
    advance_to(engine,'main1')
    obj=card(engine,'Boulder Jockey',zone=zone)
    return engine,obj,engine.state.player_by_id('p1')


def _attack(engine,obj,player):
    advance_to(engine,'declare_attackers')
    engine.declare_attackers(player,[{'attacker':obj,'defender':engine.state.player_by_id('p2')}])
    engine.resolve_until_stable()


def _pay(engine):
    assert engine.state.pending_choice['kind']=='pay_cost_then'
    engine.resolve_pending_choice('pay')
    engine.resolve_until_stable()


def _boulders(engine):
    return [o for o in engine.state.battlefield if o.name=='Boulder']


def test_fresh_specs_binding_and_mana_value():
    engine,obj,_=_board()
    a,b=specs_for(obj.card),specs_for(obj.card)
    assert len(a)==2 and a[0] is not b[0]
    assert len(obj.triggered_abilities)==1
    assert ManaCost.parse('{2}{R}{D}').converted_mana_cost==3
    assert obj.mana_value==3


def test_cast_pays_three_mana_and_one_land_drop():
    engine,obj,player=_board(Zone.HAND)
    cast(engine,obj,pool={'R':1,'C':2})
    assert obj.zone==Zone.BATTLEFIELD and player.mana_pool.total()==0
    assert player.land_drops_given_up_this_turn==1 and player.lands_played_this_turn==0
    land=card(engine,'Forest',zone=Zone.HAND)
    assert not engine.can_play_land(player,land)


@pytest.mark.parametrize('played,given',[(1,0),(0,1)])
def test_cast_is_illegal_without_remaining_drop(played,given):
    engine,obj,player=_board(Zone.HAND)
    player.lands_played_this_turn=played
    player.land_drops_given_up_this_turn=given
    player.mana_pool.add_many({'R':1,'C':2})
    assert not engine.can_cast(player,obj)
    with pytest.raises(ValueError):
        engine.cast_spell(player,obj)
    assert obj in player.hand and player.mana_pool.total()==3


def test_paid_attack_creates_correct_token_and_sacrifices_next_end():
    engine,obj,player=_board()
    _attack(engine,obj,player)
    _pay(engine)
    token,=_boulders(engine)
    assert player.land_drops_given_up_this_turn==1
    assert token.is_token and token.is_creature and token.is_artifact
    assert token.power==token.toughness==3 and token.has_subtype('construct')
    assert token.tapped and token.attacking and not token.attacked_this_turn
    assert not token.colors
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert not _boulders(engine)


@pytest.mark.parametrize('mode',['decline','used'])
def test_no_token_when_declined_or_land_drop_used(mode):
    engine,obj,player=_board()
    if mode=='used':
        player.lands_played_this_turn=1
    _attack(engine,obj,player)
    if mode=='decline':
        engine.resolve_pending_choice('decline')
        engine.resolve_until_stable()
    assert not _boulders(engine) and player.land_drops_given_up_this_turn==0


def test_extra_land_play_can_pay_after_an_actual_land_play():
    engine,obj,player=_board()
    land=card(engine,'Forest',zone=Zone.HAND)
    engine.play_land(player,land)
    player.extra_land_plays_this_turn=1
    _attack(engine,obj,player)
    _pay(engine)
    assert len(_boulders(engine))==1
    assert player.land_drops_given_up_this_turn==1 and player.lands_played_this_turn==1


def test_cast_and_attack_require_two_different_land_drops():
    engine,obj,player=_board(Zone.HAND)
    player.extra_land_plays_this_turn=1
    cast(engine,obj,pool={'R':1,'C':2})
    obj.summoning_sick=False
    _attack(engine,obj,player)
    _pay(engine)
    assert player.land_drops_given_up_this_turn==2 and len(_boulders(engine))==1


def test_payment_and_delayed_sacrifice_survive_clone():
    engine,obj,player=_board()
    _attack(engine,obj,player)
    clone=GameEngine(engine.state.clone())
    _pay(clone)
    clone=GameEngine(clone.state.clone())
    advance_to(clone,'end')
    clone.resolve_until_stable()
    assert not _boulders(clone)
    assert player.land_drops_given_up_this_turn==0


def test_other_players_turn_cannot_pay_land_drop_even_with_flash():
    engine,obj,player=_board(Zone.HAND)
    obj.temp_keywords.add('flash')
    engine.state.active_player_index=1
    player.mana_pool.add_many({'R':1,'C':2})
    assert not engine.can_cast(player,obj)


def test_given_up_drop_resets_on_next_own_turn():
    engine,obj,player=_board(Zone.HAND)
    cast(engine,obj,pool={'R':1,'C':2})
    assert player.land_drops_given_up_this_turn==1
    engine.begin_turn()
    assert player.land_drops_given_up_this_turn==1
    engine.begin_turn()
    assert player.land_drops_given_up_this_turn==0


def test_more_land_permission_can_restore_play_after_payment():
    engine,obj,player=_board(Zone.HAND)
    cast(engine,obj,pool={'R':1,'C':2})
    land=card(engine,'Forest',zone=Zone.HAND)
    assert not engine.can_play_land(player,land)
    player.extra_land_plays_this_turn=1
    assert engine.can_play_land(player,land)
    engine.play_land(player,land)
    assert player.lands_played_this_turn==1 and player.land_drops_given_up_this_turn==1


def test_multiplayer_defender_choice_preserves_delayed_sacrifice():
    engine,obj,player=_board(players=3)
    _attack(engine,obj,player)
    _pay(engine)
    assert engine.state.pending_choice['kind']=='reselect_attack'
    engine.resolve_pending_choice('player:p3')
    engine.resolve_until_stable()
    token,=_boulders(engine)
    assert token.combat_defender['id']=='p3'
    assert len(engine.state.delayed_triggers)==1
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert not _boulders(engine)


def test_payment_rechecks_available_land_drop_before_consuming():
    engine,obj,player=_board()
    _attack(engine,obj,player)
    player.lands_played_this_turn=1
    _pay(engine)
    assert not _boulders(engine) and player.land_drops_given_up_this_turn==0


def test_free_cast_still_pays_land_drop_cost():
    engine,obj,player=_board(Zone.HAND)
    engine.rules._request_resolution_play(player,[obj],free=True,zone='hand')
    engine.play_resolution_card(player,obj)
    engine.resolve_until_stable()
    assert obj.zone==Zone.BATTLEFIELD and player.land_drops_given_up_this_turn==1
    assert player.mana_pool.total()==0


def test_free_cast_cannot_bypass_used_land_drop():
    engine,obj,player=_board(Zone.HAND)
    player.lands_played_this_turn=1
    engine.rules._request_resolution_play(player,[obj],free=True,zone='hand')
    with pytest.raises(ValueError):
        engine.play_resolution_card(player,obj)
    assert obj in player.hand and player.land_drops_given_up_this_turn==0


def test_delayed_sacrifice_cannot_sacrifice_token_controlled_by_opponent():
    engine,obj,player=_board()
    _attack(engine,obj,player)
    _pay(engine)
    token,=_boulders(engine)
    token.controller_id='p2'
    engine.recompute_continuous_effects()
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert token in engine.state.battlefield


def test_source_departure_does_not_cancel_delayed_sacrifice():
    engine,obj,player=_board()
    _attack(engine,obj,player)
    _pay(engine)
    engine.rules.exile(obj)
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert not _boulders(engine)
