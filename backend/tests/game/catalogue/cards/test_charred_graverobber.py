"""Charred Graverobber: outlaw targets and real Escape casting costs/entry."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, cast, enter
from tests.support.star_trek import advance_to


def _board(zone=Zone.BATTLEFIELD):
    engine=game(players=2,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Charred Graverobber',zone=zone)
    return engine,source


def _outlaw(engine,subtype='Rogue',player='p1'):
    return filler(engine,subtype,type_line=f'Creature — {subtype}',player=player,
        power=2,toughness=2,zone=Zone.GRAVEYARD)


def _answer(engine,target):
    choice=engine.state.pending_choice
    assert choice is not None
    option=next(o for o in choice['options'] if o.get('instance_id')==target.instance_id)
    engine.resolve_pending_choice(option['id'])
    engine.resolve_until_stable()


def test_specs_fresh_binding_escape_and_entry_metadata():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==1
    assert engine._graveyard_cast_keyword(source)=='escape'


@pytest.mark.parametrize('subtype',['Assassin','Mercenary','Pirate','Rogue','Warlock'])
def test_each_outlaw_type_is_a_legal_target(subtype):
    engine,source=_board()
    target=_outlaw(engine,subtype)
    enter(engine,source)
    engine.resolve_until_stable()
    _answer(engine,target)
    assert target.zone==Zone.HAND and not source.counters


def test_kindred_outlaw_card_is_legal_without_being_a_creature():
    engine,source=_board()
    target=filler(engine,'Kindred',type_line='Kindred Sorcery — Rogue',zone=Zone.GRAVEYARD)
    enter(engine,source)
    engine.resolve_until_stable()
    _answer(engine,target)
    assert target.zone==Zone.HAND


def test_target_selection_excludes_non_outlaws_and_other_graveyards():
    engine,source=_board()
    own=_outlaw(engine)
    _outlaw(engine,player='p2')
    filler(engine,'Wizard',type_line='Creature — Wizard',power=1,toughness=1,zone=Zone.GRAVEYARD)
    specs=source.triggered_abilities[0].effects[0].target_specs
    options=legal_targets(engine.state,'p1',specs[0],source)
    assert {o['instance_id'] for o in options}=={own.instance_id}


def test_real_normal_cast_returns_outlaw_without_escape_counter():
    engine,source=_board(Zone.HAND)
    target=_outlaw(engine)
    cast(engine,source,pool={'B':1,'C':2})
    _answer(engine,target)
    assert target.zone==Zone.HAND and source.zone==Zone.BATTLEFIELD
    assert not source.counters and engine.state.players[0].mana_pool.total()==0


def test_real_escape_exiles_four_other_cards_and_enters_with_counter():
    engine,source=_board(Zone.GRAVEYARD)
    target=_outlaw(engine)
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(4)]
    cast(engine,source,pool={'B':2,'C':3},graveyard_exile_choices=[o.instance_id for o in fuel])
    assert source.zone==Zone.BATTLEFIELD and source.counters.get('+1/+1')==1
    assert all(o.zone==Zone.EXILE for o in fuel)
    _answer(engine,target)
    assert target.zone==Zone.HAND and engine.state.players[0].mana_pool.total()==0


@pytest.mark.parametrize('invalid',['too_few','self','duplicate'])
def test_invalid_escape_exile_cost_is_rejected_atomically(invalid):
    engine,source=_board(Zone.GRAVEYARD)
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(4)]
    picks=fuel[:3] if invalid=='too_few' else [source]+fuel[:3] if invalid=='self' else [fuel[0]]*4
    player=engine.state.players[0]
    player.mana_pool.add_many({'B':2,'C':3})
    with pytest.raises(ValueError):
        engine.cast_spell(player,source,graveyard_exile_choices=[o.instance_id for o in picks])
    assert source.zone==Zone.GRAVEYARD and all(o.zone==Zone.GRAVEYARD for o in fuel)
    assert player.mana_pool.total()==5


def test_target_choice_survives_clone_and_source_departure():
    engine,source=_board()
    target=_outlaw(engine)
    enter(engine,source)
    engine.resolve_until_stable()
    engine.rules.exile(source)
    engine=GameEngine(engine.state.clone())
    target=engine.state.find_object(target.instance_id)
    _answer(engine,target)
    assert target.zone==Zone.HAND


def test_changeling_card_is_an_outlaw_in_graveyard():
    engine,source=_board()
    target=card(engine,'Universal Automaton',zone=Zone.GRAVEYARD)
    enter(engine,source)
    engine.resolve_until_stable()
    _answer(engine,target)
    assert target.zone==Zone.HAND


def test_exiled_outlaw_used_as_escape_fuel_is_not_returned():
    engine,source=_board(Zone.GRAVEYARD)
    target=_outlaw(engine)
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(3)]
    cast(engine,source,pool={'B':2,'C':3},graveyard_exile_choices=[target.instance_id]+[o.instance_id for o in fuel])
    assert engine.state.pending_choice is None
    assert target.zone==Zone.EXILE and source.counters.get('+1/+1')==1


def test_later_noncast_entry_does_not_keep_escape_counter():
    engine,source=_board(Zone.GRAVEYARD)
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(4)]
    cast(engine,source,pool={'B':2,'C':3},graveyard_exile_choices=[o.instance_id for o in fuel])
    assert source.counters.get('+1/+1')==1
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1',0)==0
