"""Grievous Wound: live attachment prohibition and damage recipient halving."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game
from tests.support.star_trek import advance_to


def _board(host='p2'):
    engine = game(players=4, library=20)
    advance_to(engine, 'main1')
    source = card(engine, 'Grievous Wound')
    source.attached_to=host
    dealer=filler(engine, 'Dealer', power=2, toughness=2)
    return engine, source, dealer


def test_specs_fresh_and_bound():
    engine,source,_=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert len(a)==3 and a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.static_effects)==1 and len(source.triggered_abilities)==1


@pytest.mark.parametrize('host',['p1','p2','p3','p4'])
def test_only_enchanted_player_cannot_gain_life(host):
    engine,source,_=_board(host)
    for player in engine.state.players:
        engine.rules.gain_life(player,5)
    assert [p.life for p in engine.state.players]==[20 if p.id==host else 25 for p in engine.state.players]


@pytest.mark.parametrize('change',['reattach','leave','phase','steal'])
def test_prohibition_tracks_live_attachment_and_source(change):
    engine,source,_=_board()
    if change=='reattach':
        source.attached_to='p3'
    elif change=='leave':
        engine.rules.exile(source)
    elif change=='phase':
        source.phased_out=True
    else:
        source.controller_id='p2'
    engine.recompute_continuous_effects()
    for player in engine.state.players:
        engine.rules.gain_life(player,5)
    blocked='p3' if change=='reattach' else 'p2' if change=='steal' else None
    assert [p.life for p in engine.state.players]==[20 if p.id==blocked else 25 for p in engine.state.players]


@pytest.mark.parametrize('life,damage,expected',[(20,2,9),(20,3,8),(21,2,9),(3,1,1)])
@pytest.mark.parametrize('combat',[False,True])
def test_damage_then_lose_half_remaining_life_rounded_up(life,damage,expected,combat):
    engine,source,dealer=_board()
    player=engine.state.players[1]
    player.life=life
    engine.rules.deal_damage(player,damage,source=dealer,combat=combat)
    engine.resolve_until_stable()
    assert player.life==expected
    assert all(p.life==20 for p in engine.state.players if p.id!='p2')


@pytest.mark.parametrize('kind',['other_player','creature','zero','life_loss'])
def test_only_actual_damage_to_enchanted_player_triggers(kind):
    engine,source,dealer=_board()
    player=engine.state.players[1]
    if kind=='life_loss':
        engine.rules.lose_life(player,2)
    else:
        target=engine.state.players[2] if kind=='other_player' else dealer if kind=='creature' else player
        engine.rules.deal_damage(target,0 if kind=='zero' else 1,source=dealer)
    engine.resolve_until_stable()
    assert player.life==(18 if kind=='life_loss' else 20)


@pytest.mark.parametrize('change',['reattach','leave','steal','clone'])
def test_trigger_keeps_original_recipient_and_reads_life_at_resolution(change):
    engine,source,dealer=_board()
    player=engine.state.players[1]
    engine.rules.deal_damage(player,2,source=dealer)
    engine.rules.put_triggers_on_stack()
    if change=='reattach':
        source.attached_to='p3'
    elif change=='leave':
        engine.rules.exile(source)
    elif change=='steal':
        source.controller_id='p4'
    else:
        engine=GameEngine(engine.state.clone())
        player=engine.state.players[1]
    engine.rules.lose_life(player,3)
    engine.resolve_until_stable()
    assert player.life==7 and engine.state.players[2].life==20


def test_real_aura_cast_attaches_and_prevents_gain():
    engine=game()
    advance_to(engine,'main1')
    source=card(engine,'Grievous Wound',zone=Zone.HAND)
    cast(engine,source,targets=[engine.state.players[1]])
    assert source.attached_to=='p2'
    engine.rules.gain_life(engine.state.players[1],5)
    assert engine.state.players[1].life==20


def test_prevented_combat_damage_does_not_trigger():
    engine,source,dealer=_board()
    engine.rules.prevent_all_combat_damage_this_turn(engine.state.players[0])
    engine.rules.deal_damage(engine.state.players[1],3,source=dealer,combat=True)
    engine.resolve_until_stable()
    assert engine.state.players[1].life==20


def test_life_gain_from_real_spell_is_prohibited():
    engine,source,dealer=_board()
    victim=filler(engine,'Exile victim',player='p2',power=6,toughness=6)
    spell=card(engine,'Swords to Plowshares',zone=Zone.HAND)
    cast(engine,spell,targets=[victim])
    assert victim.zone==Zone.EXILE and engine.state.players[1].life==20


def test_two_damage_events_each_halve_life_when_their_trigger_resolves():
    engine,source,dealer=_board()
    player=engine.state.players[1]
    engine.rules.deal_damage(player,1,source=dealer)
    engine.rules.put_triggers_on_stack()
    engine.rules.deal_damage(player,1,source=dealer)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert player.life==4
