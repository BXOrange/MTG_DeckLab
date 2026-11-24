"""Student's state trigger and Tobita's continuous own-creature flying grant."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Student of Elements')
    own=filler(engine,'Own',power=2,toughness=2)
    other=filler(engine,'Other',player='p2',power=2,toughness=2)
    return engine,source,own,other


def _queue(engine,source):
    source.temp_keywords.add('flying')
    engine.recompute_continuous_effects()
    engine.rules.check_state_based_actions()
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack)==1 and not source.flipped


def test_fresh_specs_and_no_flying_by_default():
    engine,source,own,other=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    engine.resolve_until_stable()
    assert not source.flipped and not combat.has(source,'flying')


@pytest.mark.parametrize('kind',['temporary','counter','anthem'])
def test_flying_from_different_sources_triggers_flip(kind):
    engine,source,own,other=_board()
    if kind=='temporary':
        source.temp_keywords.add('flying')
    elif kind=='counter':
        source.counters['flying']=1
    else:
        card(engine,'Levitation')
    engine.recompute_continuous_effects()
    engine.resolve_until_stable()
    assert source.flipped and source.name=='Tobita, Master of Winds' and source.is_legendary
    assert combat.has(own,'flying') and combat.has(source,'flying')
    assert not combat.has(other,'flying')
    assert not source.triggered_abilities


def test_losing_flying_after_trigger_does_not_cancel_flip():
    engine,source,own,other=_board()
    _queue(engine,source)
    source.temp_keywords.clear()
    engine.recompute_continuous_effects()
    assert not combat.has(source,'flying')
    engine.resolve_until_stable()
    assert source.flipped and combat.has(own,'flying')


def test_state_trigger_does_not_duplicate_while_pending():
    engine,source,own,other=_board()
    _queue(engine,source)
    for _ in range(3):
        engine.rules.check_state_based_actions()
        engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack)==1
    engine.resolve_until_stable()
    assert source.flipped


def test_countering_state_trigger_allows_it_to_trigger_again():
    engine,source,own,other=_board()
    _queue(engine,source)
    engine.rules.counter_ability(engine.state.stack[-1])
    assert not source.flipped
    engine.rules.check_state_based_actions()
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack)==1
    engine.resolve_until_stable()
    assert source.flipped


@pytest.mark.parametrize('change',['clone','new_visit','stolen'])
def test_pending_flip_follows_its_original_source_visit(change):
    engine,source,own,other=_board()
    _queue(engine,source)
    if change=='clone':
        engine=GameEngine(engine.state.clone())
        source=engine.state.find_object(source.instance_id)
    elif change=='new_visit':
        engine.rules.exile(source)
        engine.rules.return_from_graveyard(source,'battlefield')
    else:
        source.controller_id='p2'
    engine.resolve_until_stable()
    assert source.flipped==(change!='new_visit')
    if change=='stolen':
        assert combat.has(other,'flying') and not combat.has(own,'flying')


def test_new_creatures_gain_flying_and_leaving_tobita_removes_it():
    engine,source,own,other=_board()
    _queue(engine,source)
    engine.resolve_until_stable()
    later=filler(engine,'Later',power=1,toughness=1)
    assert combat.has(later,'flying')
    engine.rules.exile(source)
    engine.recompute_continuous_effects()
    assert not combat.has(own,'flying') and not combat.has(later,'flying')


def test_returning_later_uses_front_without_automatic_flip():
    engine,source,own,other=_board()
    _queue(engine,source)
    engine.resolve_until_stable()
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert not source.flipped and not combat.has(source,'flying')


def test_back_specs_are_fresh():
    engine,source,own,other=_board()
    _queue(engine,source)
    engine.resolve_until_stable()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
