"""Radagast uses the same first-creature count for cost and timing."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, cast, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Radagast of Rhosgobel')
    return engine,source


def _off_turn(engine):
    engine.state.active_player_index=1
    engine.state.current_step='end'


def _generic_cost(engine,obj,player='p1'):
    cost=engine.effective_cast_cost(engine.state.player_by_id(player),obj)
    return sum(symbol.amount for symbol in cost.symbols if symbol.kind=='generic')


def test_fresh_specs_and_binding():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.static_effects)==2


def test_first_creature_gets_discount_and_flash_then_both_are_used():
    engine,source=_board()
    _off_turn(engine)
    first=card(engine,'Centaur Courser',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add('G',1)
    assert _generic_cost(engine,first)==0
    assert engine.can_cast(p,first)
    engine.cast_spell(p,first)
    second=card(engine,'Centaur Courser',zone=Zone.HAND)
    p.mana_pool.add_many(RICH)
    assert _generic_cost(engine,second)==2
    assert not engine.can_cast(p,second)
    engine.resolve_until_stable()
    assert first.zone==Zone.BATTLEFIELD


def test_noncreature_spell_does_not_consume_first_creature_benefits():
    engine,source=_board()
    cast(engine,card(engine,'Short Sword',zone=Zone.HAND))
    obj=card(engine,'Centaur Courser',zone=Zone.HAND)
    _off_turn(engine)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert _generic_cost(engine,obj)==0 and engine.can_cast(p,obj)


def test_countered_first_creature_still_consumes_benefits():
    engine,source=_board()
    first=card(engine,'Centaur Courser',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    engine.cast_spell(p,first)
    engine.rules.counter_spell(first)
    engine.resolve_until_stable()
    _off_turn(engine)
    second=card(engine,'Centaur Courser',zone=Zone.HAND)
    assert _generic_cost(engine,second)==2 and not engine.can_cast(p,second)


def test_creature_cast_before_radagast_entered_counts():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    cast(engine,card(engine,'Grizzly Bears',zone=Zone.HAND))
    card(engine,'Radagast of Rhosgobel')
    obj=card(engine,'Centaur Courser',zone=Zone.HAND)
    _off_turn(engine)
    assert _generic_cost(engine,obj)==2
    assert not engine.can_cast(engine.state.player_by_id('p1'),obj)


def test_casting_radagast_itself_uses_first_creature_for_that_turn():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    cast(engine,card(engine,'Radagast of Rhosgobel',zone=Zone.HAND))
    obj=card(engine,'Centaur Courser',zone=Zone.HAND)
    assert _generic_cost(engine,obj)==2


def test_only_generic_mana_is_reduced():
    engine,source=_board()
    obj=card(engine,'Leatherback Baloth',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add('G',2)
    assert not engine.can_cast(p,obj)
    p.mana_pool.add('G',1)
    assert engine.can_cast(p,obj)


def test_two_radagasts_stack_discounts_on_same_first_creature():
    engine,source=_board()
    # Avoid the legend rule by directly inspecting costs before the SBA.
    card(engine,'Radagast of Rhosgobel')
    obj=card(engine,'Colossal Dreadmaw',zone=Zone.HAND)
    assert _generic_cost(engine,obj)==0


@pytest.mark.parametrize('change',['leaves','control','loses_abilities','clone'])
def test_both_statics_follow_source_state(change):
    engine,source=_board()
    obj=card(engine,'Centaur Courser',zone=Zone.HAND)
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
    _off_turn(engine)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert _generic_cost(engine,obj)==(0 if change=='clone' else 2)
    assert engine.can_cast(p,obj)==(change=='clone')


def test_new_turn_resets_first_creature_even_during_opponents_turn():
    engine,source=_board()
    cast(engine,card(engine,'Centaur Courser',zone=Zone.HAND))
    advance_to(engine,'untap')
    advance_to(engine,'main1')
    obj=card(engine,'Centaur Courser',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert engine.state.active_player.id=='p2'
    assert _generic_cost(engine,obj)==0 and engine.can_cast(p,obj)


def test_opponents_creature_does_not_consume_own_first_cast():
    engine,source=_board()
    engine.state.active_player_index=1
    opponent=card(engine,'Centaur Courser',player='p2',zone=Zone.HAND)
    p2=engine.state.player_by_id('p2')
    p2.mana_pool.add_many(RICH)
    assert _generic_cost(engine,opponent,player='p2')==2
    engine.cast_spell(p2,opponent)
    engine.resolve_until_stable()
    own=card(engine,'Centaur Courser',zone=Zone.HAND)
    assert _generic_cost(engine,own)==0


def test_discount_floors_at_zero_without_providing_colored_mana():
    engine,source=_board()
    obj=card(engine,'Grizzly Bears',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    assert _generic_cost(engine,obj)==0
    assert not engine.can_cast(p,obj)
    p.mana_pool.add('G',1)
    assert engine.can_cast(p,obj)
    engine.cast_spell(p,obj)
    engine.resolve_until_stable()
    assert obj.zone==Zone.BATTLEFIELD and p.mana_pool.total()==0
