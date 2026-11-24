"""Azula's opponent choices, exact exile links, and live bundled cast permission."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.linked_exile import linked_cards
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, enter, RICH
from tests.support.star_trek import advance_to


def _pick(engine,obj=None,player=None):
    choice=engine.state.pending_choice
    assert choice is not None
    option=next(o for o in choice['options'] if
        (obj is not None and o.get('instance_id')==obj.instance_id) or
        (player is not None and (o.get('player_id')==player or o['id']==player)))
    engine.resolve_pending_choice(option['id'])
    engine.resolve_until_stable()


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Azula, Cunning Usurper')
    first=card(engine,'Grizzly Bears',player='p2')
    card(engine,'Centaur Courser',player='p2')
    grave=card(engine,'Counterspell',player='p2',zone=Zone.GRAVEYARD)
    card(engine,'Short Sword',player='p2',zone=Zone.GRAVEYARD)
    land=card(engine,'Forest',player='p2',zone=Zone.GRAVEYARD)
    return engine,source,first,grave,land


def _exile_pair(engine,source,first,grave):
    enter(engine,source)
    engine.resolve_until_stable()
    _pick(engine,player='p2')
    assert engine.state.pending_choice['player_id']=='p2'
    _pick(engine,obj=first)
    assert first.zone==Zone.EXILE
    assert engine.state.pending_choice['player_id']=='p2'
    _pick(engine,obj=grave)
    assert grave.zone==Zone.EXILE


def test_fresh_specs_binding_and_native_firebending():
    engine,source,first,grave,land=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert source.parametric_keyword_value('firebending')==2
    assert len(source.static_effects)==1


def test_opponent_exiles_creature_then_nonland_graveyard_card():
    engine,source,first,grave,land=_board()
    _exile_pair(engine,source,first,grave)
    assert linked_cards(engine.state,source)==[first,grave]
    assert land.zone==Zone.GRAVEYARD


def test_linked_creature_casts_at_flash_timing_using_colorless_mana():
    engine,source,first,grave,land=_board()
    _exile_pair(engine,source,first,grave)
    engine.state.current_step='end'
    p=engine.state.player_by_id('p1')
    p.mana_pool.add('C',2)
    assert engine.can_cast(p,first)
    engine.cast_spell(p,first)
    engine.resolve_until_stable()
    assert first.zone==Zone.BATTLEFIELD and first.controller_id=='p1' and first.owner_id=='p2'
    assert p.mana_pool.total()==0


@pytest.mark.parametrize('change',['opponents_turn','source_leaves','source_new_visit','loses_abilities','card_new_visit','clone'])
def test_permission_tracks_live_source_and_exact_exile_visits(change):
    engine,source,first,grave,land=_board()
    _exile_pair(engine,source,first,grave)
    if change=='opponents_turn':
        engine.state.active_player_index=1
    elif change=='source_leaves':
        engine.rules.exile(source)
    elif change=='source_new_visit':
        engine.rules.exile(source)
        engine.rules.return_from_graveyard(source,'battlefield')
    elif change=='loses_abilities':
        card(engine,'Dress Down')
    elif change=='card_new_visit':
        engine.rules.return_from_graveyard(first,'battlefield')
        engine.rules.exile(first)
    else:
        engine=GameEngine(engine.state.clone())
        first=engine.state.find_object(first.instance_id)
    engine.recompute_continuous_effects()
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert engine.can_cast(p,first)==(change=='clone')


def test_control_change_moves_permission_to_new_controller_during_their_turn():
    engine,source,first,grave,land=_board()
    _exile_pair(engine,source,first,grave)
    source.controller_id='p3'
    engine.state.active_player_index=2
    p=engine.state.player_by_id('p3')
    p.mana_pool.add('C',2)
    assert engine.can_cast(p,first)
    assert not engine.can_cast(engine.state.player_by_id('p1'),first)


def test_empty_battlefield_pool_still_exiles_from_graveyard():
    engine,source,first,grave,land=_board()
    for obj in list(engine.state.permanents_controlled_by('p2')):
        engine.rules.exile(obj)
    enter(engine,source)
    engine.resolve_until_stable()
    _pick(engine,player='p2')
    _pick(engine,obj=grave)
    assert linked_cards(engine.state,source)==[grave]


def test_only_lands_in_graveyard_does_not_prevent_creature_exile():
    engine,source,first,grave,land=_board()
    for obj in list(engine.state.player_by_id('p2').graveyard):
        if not obj.is_land:
            engine.rules.exile(obj)
    enter(engine,source)
    engine.resolve_until_stable()
    _pick(engine,player='p2')
    _pick(engine,obj=first)
    assert engine.state.pending_choice is None and linked_cards(engine.state,source)==[first]


def test_clone_between_opponent_choices_preserves_order_and_links():
    engine,source,first,grave,land=_board()
    enter(engine,source)
    engine.resolve_until_stable()
    _pick(engine,player='p2')
    _pick(engine,obj=first)
    engine=GameEngine(engine.state.clone())
    source=engine.state.find_object(source.instance_id)
    grave=engine.state.find_object(grave.instance_id)
    _pick(engine,obj=grave)
    assert len(linked_cards(engine.state,source))==2


def test_mana_of_any_type_includes_paying_colorless_pips_with_colored_mana():
    engine,source,first,grave,land=_board()
    seer=card(engine,'Thought-Knot Seer',player='p2',zone=Zone.GRAVEYARD)
    _exile_pair(engine,source,first,seer)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add('G',4)
    assert engine.can_cast(p,seer)
    engine.cast_spell(p,seer)
    assert seer.zone==Zone.STACK and p.mana_pool.total()==0


def test_source_leaving_between_choices_preserves_original_links_without_permission():
    engine,source,first,grave,land=_board()
    original=source.zone_incarnation
    enter(engine,source)
    engine.resolve_until_stable()
    _pick(engine,player='p2')
    _pick(engine,obj=first)
    engine.rules.exile(source)
    _pick(engine,obj=grave)
    assert linked_cards(engine.state,source,original)==[first,grave]
    assert not linked_cards(engine.state,source)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert not engine.can_cast(p,first)


def test_tokens_are_not_offered_for_the_first_exile_choice():
    engine,source,first,grave,land=_board()
    token=card(engine,'Grizzly Bears',player='p2')
    token.is_token=True
    enter(engine,source)
    engine.resolve_until_stable()
    _pick(engine,player='p2')
    ids={o.get('instance_id') for o in engine.state.pending_choice['options']}
    assert first.instance_id in ids and token.instance_id not in ids


def test_native_firebending_produces_two_red_mana_on_attack():
    engine,source,first,grave,land=_board()
    advance_to(engine,'declare_attackers')
    p=engine.state.player_by_id('p1')
    engine.declare_attackers(p,[{'attacker':source,'defender':engine.state.player_by_id('p2')}])
    engine.resolve_until_stable()
    assert p.mana_pool.to_dict()['R']==2
