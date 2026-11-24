"""Tizerus Charger chooses its escape counter before entry, with clone-safe resume."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, cast
from tests.support.star_trek import advance_to


def _board(zone=Zone.GRAVEYARD):
    engine=game(players=2,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Tizerus Charger',zone=zone)
    return engine,source


def _escape(engine,source):
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(5)]
    cast(engine,source,pool={'B':1,'C':4},graveyard_exile_choices=[o.instance_id for o in fuel])
    assert all(o.zone==Zone.EXILE for o in fuel)
    assert engine.state.players[0].mana_pool.total()==0
    assert engine.state.pending_choice['kind']=='choose_enter_counter'
    return fuel


def _choose(engine,option):
    engine.resolve_pending_choice(str(option))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def test_fresh_specs_and_entry_choice_binding():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.enter_choice_effects)==1 and source.enter_choice_effects[0].escape_only


def test_normal_cast_has_no_choice_counter_or_flying():
    engine,source=_board(Zone.HAND)
    cast(engine,source,pool={'B':1,'C':2})
    assert source.zone==Zone.BATTLEFIELD and engine.state.pending_choice is None
    assert not source.counters and not combat.has(source,'flying')


@pytest.mark.parametrize('option,kind,power',[(0,'+1/+1',4),(1,'flying',3)])
def test_escape_choice_precedes_entry_and_grants_selected_counter(option,kind,power):
    engine,source=_board()
    _escape(engine,source)
    assert source not in engine.state.battlefield and not source.counters
    _choose(engine,option)
    assert source.zone==Zone.BATTLEFIELD and source.counters=={kind:1}
    assert source.power==power and combat.has(source,'flying')==(kind=='flying')


@pytest.mark.parametrize('option',[0,1])
def test_pending_choice_survives_clone_without_mutating_original(option):
    engine,source=_board()
    _escape(engine,source)
    clone=GameEngine(engine.state.clone())
    copied=clone.state.find_object(source.instance_id)
    _choose(clone,option)
    assert copied.zone==Zone.BATTLEFIELD and copied.counters=={('+1/+1' if option==0 else 'flying'):1}
    assert source not in engine.state.battlefield and not source.counters
    assert engine.state.pending_choice['kind']=='choose_enter_counter'


@pytest.mark.parametrize('option',[0,1])
def test_later_noncast_entry_does_not_repeat_choice(option):
    engine,source=_board()
    _escape(engine,source)
    _choose(engine,option)
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD and engine.state.pending_choice is None
    assert not source.counters and not combat.has(source,'flying')


def test_second_escape_offers_fresh_choice():
    engine,source=_board()
    _escape(engine,source)
    _choose(engine,1)
    engine.rules.put_into_graveyard(source)
    _escape(engine,source)
    _choose(engine,0)
    assert source.counters=={'+1/+1':1} and not combat.has(source,'flying')


@pytest.mark.parametrize('invalid',['too_few','self','duplicate'])
def test_escape_requires_five_other_distinct_cards(invalid):
    engine,source=_board()
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(5)]
    picks=fuel[:4] if invalid=='too_few' else [source]+fuel[:4] if invalid=='self' else [fuel[0]]*5
    player=engine.state.players[0]
    player.mana_pool.add_many({'B':1,'C':4})
    with pytest.raises(ValueError):
        engine.cast_spell(player,source,graveyard_exile_choices=[o.instance_id for o in picks])
    assert source.zone==Zone.GRAVEYARD and all(o.zone==Zone.GRAVEYARD for o in fuel)
    assert player.mana_pool.total()==5


def test_removing_flying_counter_removes_flying():
    engine,source=_board()
    _escape(engine,source)
    _choose(engine,1)
    source.counters.clear()
    engine.recompute_continuous_effects()
    assert not combat.has(source,'flying')


def test_normal_cast_then_escape_restores_escape_only_instruction():
    engine,source=_board(Zone.HAND)
    cast(engine,source,pool={'B':1,'C':2})
    engine.rules.put_into_graveyard(source)
    _escape(engine,source)
    _choose(engine,1)
    assert source.counters=={'flying':1} and combat.has(source,'flying')


def test_countering_escape_spell_spends_cost_without_entry_choice():
    engine,source=_board()
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(5)]
    player=engine.state.players[0]
    player.mana_pool.add_many({'B':1,'C':4})
    engine.cast_spell(player,source,graveyard_exile_choices=[o.instance_id for o in fuel])
    engine.rules.counter_spell(source)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD and not source.counters
    assert all(o.zone==Zone.EXILE for o in fuel)
    assert engine.state.pending_choice is None
