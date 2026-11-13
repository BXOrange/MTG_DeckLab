"""Pharika's Spawn uses escaped entry counters and opponent-owned sacrifice choices."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for, entry_counters
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, cast
from tests.support.star_trek import advance_to


def _board(zone=Zone.GRAVEYARD):
    engine=game(players=4,library=20)
    advance_to(engine,'main1')
    source=card(engine,"Pharika's Spawn",zone=zone)
    return engine,source


def _creature(engine,name,player='p2',subtype='Human'):
    return filler(engine,name,type_line=f'Creature — {subtype}',player=player,power=2,toughness=2)


def _escape(engine,source,resolve=True):
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(3)]
    if resolve:
        cast(engine,source,pool={'B':1,'C':5},graveyard_exile_choices=[o.instance_id for o in fuel])
    else:
        player=engine.state.players[0]
        player.mana_pool.add_many({'B':1,'C':5})
        engine.cast_spell(player,source,graveyard_exile_choices=[o.instance_id for o in fuel])
        engine.rules.resolve_top_of_stack()
        engine.rules.put_triggers_on_stack()
    assert all(o.zone==Zone.EXILE for o in fuel)
    assert source.counters.get('+1/+1')==2
    return fuel


def _pick(engine,obj):
    choice=engine.state.pending_choice
    option=next(o for o in choice['options'] if o.get('instance_id')==obj.instance_id)
    engine.resolve_pending_choice(option['id'])
    engine.resolve_until_stable()


def test_fresh_specs_and_entry_metadata():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    a,b=entry_counters(source.card),entry_counters(source.card)
    assert a==b and a is not b and a['escape_gate'] and a['count']==2


def test_normal_cast_has_no_counters_or_sacrifice():
    engine,source=_board(Zone.HAND)
    victim=_creature(engine,'Victim')
    cast(engine,source,pool={'B':1,'C':3})
    assert source.zone==Zone.BATTLEFIELD and not source.counters
    assert victim.zone==Zone.BATTLEFIELD and engine.state.pending_choice is None


def test_escape_pays_six_mana_and_each_opponent_sacrifices_non_gorgon():
    engine,source=_board()
    own=_creature(engine,'Own',player='p1')
    victims=[_creature(engine,f'Victim {i}',player=f'p{i}') for i in range(2,5)]
    gorgons=[_creature(engine,f'Gorgon {i}',player=f'p{i}',subtype='Gorgon') for i in range(2,5)]
    _escape(engine,source)
    assert all(o.zone==Zone.GRAVEYARD for o in victims)
    assert all(o.zone==Zone.BATTLEFIELD for o in gorgons+[own])
    assert engine.state.players[0].mana_pool.total()==0


def test_each_opponent_chooses_independently_and_clone_preserves_remaining_choices():
    engine,source=_board()
    choices={p:[_creature(engine,f'{p}-{i}',player=p) for i in range(2)] for p in ('p2','p3','p4')}
    _escape(engine,source)
    assert engine.state.pending_choice['player_id']=='p2'
    _pick(engine,choices['p2'][1])
    assert engine.state.pending_choice['player_id']=='p3'
    engine=GameEngine(engine.state.clone())
    for p in ('p3','p4'):
        _pick(engine,engine.state.find_object(choices[p][1].instance_id))
    for pair in choices.values():
        assert engine.state.find_object(pair[0].instance_id).zone==Zone.BATTLEFIELD
        assert engine.state.find_object(pair[1].instance_id).zone==Zone.GRAVEYARD


def test_gorgon_and_changeling_are_excluded_and_empty_players_skip():
    engine,source=_board()
    gorgon=_creature(engine,'Gorgon',subtype='Gorgon')
    changeling=card(engine,'Universal Automaton',player='p3')
    _escape(engine,source)
    assert engine.state.pending_choice is None
    assert gorgon.zone==Zone.BATTLEFIELD and changeling.zone==Zone.BATTLEFIELD


@pytest.mark.parametrize('change',['source_leaves','source_stolen','clone'])
def test_pending_sacrifice_keeps_original_controller(change):
    engine,source=_board()
    own=_creature(engine,'Own',player='p1')
    a,b=[_creature(engine,f'Choice {i}') for i in range(2)]
    other=_creature(engine,'Other',player='p3')
    _escape(engine,source)
    if change=='source_leaves':
        engine.rules.exile(source)
    elif change=='source_stolen':
        source.controller_id='p4'
    else:
        engine=GameEngine(engine.state.clone())
        a=engine.state.find_object(a.instance_id)
    _pick(engine,a)
    assert engine.state.find_object(own.instance_id).zone==Zone.BATTLEFIELD
    assert engine.state.find_object(other.instance_id).zone==Zone.GRAVEYARD


def test_later_return_without_cast_does_not_repeat_escape_effects():
    engine,source=_board()
    _escape(engine,source)
    engine.rules.exile(source)
    victim=_creature(engine,'New victim')
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert not source.counters and victim.zone==Zone.BATTLEFIELD


@pytest.mark.parametrize('change',['counter','steal','leave'])
def test_escape_trigger_on_stack_independent_of_source(change):
    engine,source=_board()
    own=_creature(engine,'Own',player='p1')
    victims=[_creature(engine,f'Victim {i}',player=f'p{i}') for i in range(2,5)]
    _escape(engine,source,resolve=False)
    if change=='counter':
        engine.rules.counter_ability(engine.state.stack[-1])
    elif change=='steal':
        source.controller_id='p4'
    else:
        engine.rules.exile(source)
    engine.resolve_until_stable()
    assert own.zone==Zone.BATTLEFIELD
    assert all(o.zone==(Zone.BATTLEFIELD if change=='counter' else Zone.GRAVEYARD) for o in victims)


@pytest.mark.parametrize('invalid',['too_few','self','duplicate'])
def test_escape_requires_three_other_distinct_cards(invalid):
    engine,source=_board()
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(3)]
    picks=fuel[:2] if invalid=='too_few' else [source]+fuel[:2] if invalid=='self' else [fuel[0]]*3
    player=engine.state.players[0]
    player.mana_pool.add_many({'B':1,'C':5})
    with pytest.raises(ValueError):
        engine.cast_spell(player,source,graveyard_exile_choices=[o.instance_id for o in picks])
    assert source.zone==Zone.GRAVEYARD and all(o.zone==Zone.GRAVEYARD for o in fuel)
    assert player.mana_pool.total()==6
