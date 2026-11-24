"""Keeper checks this printing, not another printing of the same card name."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Keeper of the Secret Lair')
    engine.state.active_player_index=1
    engine.state.current_step='end'
    return engine,source


def _spell(engine,code='sld',player='p1',type_line='Creature'):
    return filler(engine,'Same card name',type_line=type_line,player=player,mv=3,
                  **({'power':2,'toughness':3} if type_line=='Creature' else {}),
                  mana_cost_string='{2}{G}',set_code=code,zone=Zone.HAND)


def _generic(engine,obj,player='p1'):
    cost=engine.effective_cast_cost(engine.state.player_by_id(player),obj)
    return sum(s.amount for s in cost.symbols if s.kind=='generic')


def test_fresh_specs_binding_and_native_flash():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert a[0].effects[0].params['set_codes'] is not b[0].effects[0].params['set_codes']
    assert len(source.static_effects)==2 and combat.has(source,'flash')


@pytest.mark.parametrize('code,allowed',[
    ('sld',True),('SLD',True),('slp',True),('slu',True),('slc',True),('slz',True),
    ('slx',False),('ltr',False),('',False),('sld-extra',False),
])
def test_both_benefits_follow_the_specific_printing(code,allowed):
    engine,source=_board()
    obj=_spell(engine,code)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert engine.can_cast(p,obj)==allowed
    assert _generic(engine,obj)==(1 if allowed else 2)


@pytest.mark.parametrize('type_line',['Creature','Artifact','Enchantment','Sorcery'])
def test_all_secret_lair_spell_types_receive_both_benefits(type_line):
    engine,source=_board()
    obj=_spell(engine,type_line=type_line)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add('G',1)
    p.mana_pool.add('C',1)
    assert engine.can_cast(p,obj) and _generic(engine,obj)==1
    engine.cast_spell(p,obj)
    engine.resolve_until_stable()
    assert obj.zone==(Zone.GRAVEYARD if type_line=='Sorcery' else Zone.BATTLEFIELD)
    assert p.mana_pool.total()==0


@pytest.mark.parametrize('change',['leaves','control','loses_abilities','clone'])
def test_source_changes_affect_both_statics(change):
    engine,source=_board()
    obj=_spell(engine)
    if change=='leaves':
        engine.rules.exile(source)
    elif change=='control':
        source.controller_id='p2'
    elif change=='loses_abilities':
        card(engine,'Dress Down')
    else:
        engine=GameEngine(engine.state.clone())
        obj=engine.state.find_object(obj.instance_id)
    engine.recompute_continuous_effects()
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert engine.can_cast(p,obj)==(change=='clone')
    assert _generic(engine,obj)==(1 if change=='clone' else 2)


def test_opponents_do_not_receive_benefits():
    engine,source=_board()
    engine.state.active_player_index=2
    obj=_spell(engine,player='p2')
    p=engine.state.player_by_id('p2')
    p.mana_pool.add_many(RICH)
    assert not engine.can_cast(p,obj) and _generic(engine,obj,player='p2')==2


def test_regular_print_of_same_card_is_not_secret_lair():
    engine,source=_board()
    special=_spell(engine,'sld')
    ordinary=_spell(engine,'m21')
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert special.name==ordinary.name
    assert engine.can_cast(p,special) and not engine.can_cast(p,ordinary)
    assert _generic(engine,special)==1 and _generic(engine,ordinary)==2


def test_real_cached_secret_lair_printing_receives_both_benefits():
    engine,source=_board()
    obj=card(engine,'The Ghoul, Gunslinger',zone=Zone.HAND)
    assert obj.card.set_code.lower()=='sld'
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    discounted=_generic(engine,obj)
    assert engine.can_cast(p,obj)
    engine.rules.exile(source)
    engine.recompute_continuous_effects()
    assert _generic(engine,obj)==discounted+1 and not engine.can_cast(p,obj)


def test_reduction_never_replaces_colored_mana():
    engine,source=_board()
    obj=filler(engine,'Green only',type_line='Creature',mv=1,power=1,toughness=1,
               mana_cost_string='{G}',set_code='sld',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add('C',2)
    assert not engine.can_cast(p,obj)
    p.mana_pool.add('G',1)
    assert engine.can_cast(p,obj) and _generic(engine,obj)==0
