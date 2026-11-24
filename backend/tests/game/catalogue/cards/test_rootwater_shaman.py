"""Rootwater Shaman checks the exact enchant ability and proposed Bestow form."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    shaman=card(engine,'Rootwater Shaman')
    host=filler(engine,'Host',power=2,toughness=4)
    engine.state.active_player_index=1
    engine.state.current_step='end'
    engine.state.player_by_id('p1').mana_pool.add_many(RICH)
    return engine,shaman,host


def test_fresh_specs_and_binding():
    engine,shaman,host=_board()
    a,b=specs_for(shaman.card),specs_for(shaman.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(shaman.static_effects)==1


@pytest.mark.parametrize('name,allowed',[
    ('Pacifism',True),('Rancor',True),('Wild Growth',False),
    ('Curse of Opulence',False),('Twisted Embrace',False),
    ('One With the Stars',False),('Hyena Umbra',True),('Cartouche of Solidarity',False),
    ('Grizzly Bears',False),('Glorious Anthem',False),
])
def test_exact_enchant_creature_requirement(name,allowed):
    engine,shaman,host=_board()
    obj=card(engine,name,zone=Zone.HAND)
    assert engine.can_cast(engine.state.player_by_id('p1'),obj)==allowed


def test_aura_cast_off_turn_resolves_attached():
    engine,shaman,host=_board()
    aura=card(engine,'Pacifism',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    engine.cast_spell(p,aura,targets=[host])
    engine.resolve_until_stable()
    assert aura.zone==Zone.BATTLEFIELD and aura.attached_to==host.instance_id


@pytest.mark.parametrize('change',['leaves','control','loses_abilities','clone'])
def test_permission_tracks_current_source_state(change):
    engine,shaman,host=_board()
    aura=card(engine,'Pacifism',zone=Zone.HAND)
    if change=='leaves':
        engine.rules.exile(shaman)
    elif change=='control':
        shaman.controller_id='p2'
    elif change=='loses_abilities':
        card(engine,'Dress Down')
    else:
        engine=GameEngine(engine.state.clone())
        aura=engine.state.find_object(aura.instance_id)
    engine.recompute_continuous_effects()
    assert engine.can_cast(engine.state.player_by_id('p1'),aura)==(change=='clone')


def test_bestow_choice_qualifies_but_creature_form_does_not():
    engine,shaman,host=_board()
    obj=card(engine,'Nimbus Naiad',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    assert not engine.can_cast(p,obj)
    assert engine.can_cast(p,obj,face='bestow')
    engine.cast_spell(p,obj,face='bestow',targets=[host])
    engine.resolve_until_stable()
    assert obj.zone==Zone.BATTLEFIELD and obj.bestowed and obj.attached_to==host.instance_id


def test_permission_is_not_granted_to_opponents():
    engine,shaman,host=_board()
    engine.state.active_player_index=2
    obj=card(engine,'Pacifism',player='p2',zone=Zone.HAND)
    p=engine.state.player_by_id('p2')
    p.mana_pool.add_many(RICH)
    assert not engine.can_cast(p,obj)
