"""Shadow's death filter and artifact-mana-dependent static split second."""
import pytest
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Shadow the Hedgehog')
    return engine,source


def _cast(engine,kind='artifact',player='p1',name='Giant Growth'):
    obj=card(engine,name,player=player,zone=Zone.HAND)
    p=engine.state.player_by_id(player)
    p.mana_pool.add('G',1,source_kind=kind)
    engine.cast_spell(p,obj,targets=[next(o for o in engine.state.permanents() if o.is_creature)])
    return obj


def test_fresh_specs_binding_and_haste():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.triggered_abilities)==1 and len(source.static_effects)==1
    assert combat.has(source,'haste')


@pytest.mark.parametrize('kind',['artifact','treasure','artifact_creature','basic_land','creature',None])
def test_only_artifact_mana_actually_spent_grants_split_second(kind):
    engine,source=_board()
    spell=_cast(engine,kind)
    expected=kind in {'artifact','treasure','artifact_creature'}
    engine.recompute_continuous_effects()
    assert spell.mana_spent_to_cast_artifact==int(expected)
    assert combat.has(spell,'split_second')==expected
    assert continuous.split_second_active(engine.state)==expected


def test_unused_artifact_mana_does_not_grant_keyword():
    engine,source=_board()
    engine.state.player_by_id('p1').mana_pool.add('C',1,source_kind='artifact')
    spell=_cast(engine,'basic_land')
    engine.recompute_continuous_effects()
    assert not combat.has(spell,'split_second')


def test_opponents_spell_does_not_receive_keyword():
    engine,source=_board()
    spell=_cast(engine,player='p2')
    engine.recompute_continuous_effects()
    assert not combat.has(spell,'split_second')


@pytest.mark.parametrize('change',['leaves','control','loses_abilities','clone'])
def test_static_grant_tracks_source_state(change):
    engine,source=_board()
    spell=_cast(engine)
    engine.recompute_continuous_effects()
    assert combat.has(spell,'split_second')
    if change=='leaves':
        engine.rules.exile(source)
    elif change=='control':
        source.controller_id='p2'
    elif change=='loses_abilities':
        card(engine,'Dress Down')
    else:
        engine=GameEngine(engine.state.clone())
        spell=engine.state.find_object(spell.instance_id)
    engine.recompute_continuous_effects()
    assert combat.has(spell,'split_second')==(change=='clone')


def test_split_second_blocks_spells_and_nonmana_abilities_but_allows_mana():
    engine,source=_board()
    p=engine.state.player_by_id('p1')
    ability=card(engine,'Prodigal Pyromancer')
    forest=card(engine,'Forest')
    response=card(engine,'Giant Growth',zone=Zone.HAND)
    _cast(engine)
    engine.recompute_continuous_effects()
    p.mana_pool.add_many(RICH)
    assert not engine.can_cast(p,response)
    assert not engine.can_activate(p,ability,0)
    engine.tap_for_mana(p,forest)
    assert forest.tapped
    engine.resolve_until_stable()
    assert engine.can_cast(p,response)


@pytest.mark.parametrize('kind',['self','flash','haste','both','plain','opponent'])
def test_death_trigger_draws_once_only_for_qualifying_creature(kind):
    engine,source=_board()
    victim=source if kind=='self' else filler(engine,'Victim',player='p2' if kind=='opponent' else 'p1',power=2,toughness=2)
    if kind in {'flash','both'}:
        victim.temp_keywords.add('flash')
    if kind in {'haste','both','opponent'}:
        victim.temp_keywords.add('haste')
    engine.recompute_continuous_effects()
    before=len(engine.state.player_by_id('p1').hand)
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert len(engine.state.player_by_id('p1').hand)==before+int(kind not in {'plain','opponent'})


def test_grant_is_present_before_any_response_is_attempted():
    engine,source=_board()
    spell=_cast(engine)
    assert combat.has(spell,'split_second')


def test_real_artifact_mana_production_is_counted():
    engine,source=_board()
    p=engine.state.player_by_id('p1')
    artifact=card(engine,'Manalith')
    # Manalith's native any-colour ability offers W/U/B/R/G in order.
    engine.tap_for_mana(p,artifact,option_index=4)
    spell=card(engine,'Giant Growth',zone=Zone.HAND)
    engine.cast_spell(p,spell,targets=[source])
    assert spell.mana_spent_to_cast_artifact==1
    assert combat.has(spell,'split_second')


def test_spell_control_change_does_not_change_who_cast_it():
    engine,source=_board()
    spell=_cast(engine)
    item=next(i for i in engine.state.stack if i.obj is spell)
    item.controller_id=spell.controller_id='p2'
    engine.recompute_continuous_effects()
    assert combat.has(spell,'split_second')
