"""Visitor's owned-card type extension, hybrid resolution and optional loot."""
import pytest
from mtg_analyzer.game import continuous
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Visitor from Planet Q')
    return engine,source


def _answer(engine,accept=True):
    for _ in range(10):
        choice=engine.state.pending_choice
        if choice is None:
            return
        options=choice['options']
        ids={o['id'] for o in options}
        candidates=('yes','accept') if accept else ('no','decline','skip')
        pick=next((v for v in candidates if v in ids),options[0 if accept else -1]['id'])
        engine.resolve_pending_choice(pick)
        engine.resolve_until_stable()
    raise AssertionError('Unfinished loot')


def test_fresh_specs_binding():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.static_effects)==len(source.triggered_abilities)==1


@pytest.mark.parametrize('zone',[Zone.HAND,Zone.LIBRARY,Zone.GRAVEYARD,Zone.EXILE,Zone.COMMAND,Zone.BATTLEFIELD])
def test_flash_creature_cards_gain_instant_in_every_zone_without_changing_printing(zone):
    engine,source=_board()
    target=card(engine,'Ashcoat Bear',zone=zone)
    engine.recompute_continuous_effects()
    assert target.is_instant and 'instant' in continuous.card_types_of(target)
    assert target.characteristic_card().is_instant and not target.card.is_instant
    assert target.card.type_line=='Creature — Bear'
    engine.rules.exile(source)
    engine.recompute_continuous_effects()
    assert not target.is_instant and not target.characteristic_card().is_instant


@pytest.mark.parametrize('kind',['own_stolen','borrowed','plain','noncreature','token'])
def test_type_grant_uses_ownership_and_requires_creature_card_with_flash(kind):
    engine,source=_board()
    target=card(engine,'Ashcoat Bear',player='p2' if kind=='borrowed' else 'p1')
    if kind=='own_stolen':
        target.controller_id='p2'
    elif kind=='borrowed':
        target.controller_id='p1'
    elif kind=='plain':
        target=card(engine,'Grizzly Bears')
    elif kind=='noncreature':
        target=card(engine,'Leyline of Anticipation')
        target.temp_keywords.add('flash')
    else:
        target.is_token=True
    engine.recompute_continuous_effects()
    assert target.is_instant==(kind=='own_stolen')


def test_visitor_can_be_cast_at_instant_speed_and_resolves_as_creature():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Visitor from Planet Q',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    engine.state.active_player_index=1
    engine.state.current_step='end'
    assert engine.can_cast(p,source)
    engine.cast_spell(p,source)
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD and source.is_creature and source.is_instant
    assert engine.state.pending_choice is None  # Does not trigger for itself.


@pytest.mark.parametrize('kind',['flash','artifact','single','legendary','opponent'])
def test_loot_requires_another_own_spell_with_two_card_types(kind):
    engine,source=_board()
    name='Ashcoat Bear' if kind in {'flash','opponent'} else 'Ornithopter' if kind=='artifact' else 'Isamaru, Hound of Konda' if kind=='legendary' else 'Grizzly Bears'
    obj=card(engine,name,player='p2' if kind=='opponent' else 'p1',zone=Zone.HAND)
    p=engine.state.player_by_id(obj.controller_id)
    p.mana_pool.add_many(RICH)
    engine.cast_spell(p,obj)
    engine.resolve_until_stable()
    if kind in {'flash','artifact'}:
        assert engine.state.pending_choice is not None
        _answer(engine)
    else:
        assert engine.state.pending_choice is None
    assert obj.zone==Zone.BATTLEFIELD


def test_declining_optional_loot_neither_draws_nor_discards():
    engine,source=_board()
    obj=card(engine,'Ornithopter',zone=Zone.HAND)
    engine.cast_spell(engine.state.player_by_id('p1'),obj)
    before_library=len(engine.state.player_by_id('p1').library)
    before_hand=len(engine.state.player_by_id('p1').hand)
    engine.resolve_until_stable()
    _answer(engine,False)
    p=engine.state.player_by_id('p1')
    assert len(p.library)==before_library and len(p.hand)==before_hand


def test_clone_and_source_control_change_rederive_type_membership():
    engine,source=_board()
    own=card(engine,'Ashcoat Bear',zone=Zone.HAND)
    other=card(engine,'Ashcoat Bear',player='p2',zone=Zone.GRAVEYARD)
    engine.recompute_continuous_effects()
    clone=GameEngine(engine.state.clone())
    cloned_source=clone.state.find_object(source.instance_id)
    cloned_source.controller_id='p2'
    clone.recompute_continuous_effects()
    assert not clone.state.find_object(own.instance_id).is_instant
    assert clone.state.find_object(other.instance_id).is_instant
    assert own.is_instant and not other.is_instant


def test_granted_flash_and_its_removal_change_battlefield_type():
    engine,source=_board()
    target=card(engine,'Grizzly Bears')
    target.temp_keywords.add('flash')
    engine.recompute_continuous_effects()
    assert target.is_instant
    target.temp_keywords.clear()
    engine.recompute_continuous_effects()
    assert not target.is_instant


def test_graveyard_instant_target_filter_sees_derived_type():
    from mtg_analyzer.game.targeting import graveyard_card_matches
    engine,source=_board()
    target=card(engine,'Ashcoat Bear',zone=Zone.GRAVEYARD)
    engine.recompute_continuous_effects()
    assert graveyard_card_matches('graveyard_instant',target)
    engine.rules.exile(source)
    engine.recompute_continuous_effects()
    assert not graveyard_card_matches('graveyard_instant',target)


def test_losing_visitors_abilities_removes_off_battlefield_types():
    engine,source=_board()
    target=card(engine,'Ashcoat Bear',zone=Zone.HAND)
    engine.recompute_continuous_effects()
    assert target.is_instant
    card(engine,'Dress Down')
    engine.recompute_continuous_effects()
    assert not target.is_instant


def test_accepting_loot_draws_and_discards_once():
    engine,source=_board()
    obj=card(engine,'Ornithopter',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    before_library=len(p.library)
    before_graveyard=len(p.graveyard)
    engine.cast_spell(p,obj)
    engine.resolve_until_stable()
    _answer(engine)
    assert len(p.library)==before_library-1
    assert len(p.graveyard)==before_graveyard+1
