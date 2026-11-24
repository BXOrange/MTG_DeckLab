"""Last Laugh damage cascades and its independent no-creatures state trigger."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def _board(creature=True):
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Last Laugh')
    body=filler(engine,'Body',power=2,toughness=5) if creature else None
    return engine,source,body


def _queue_state(engine):
    engine.rules.check_state_based_actions()
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack)==1


def test_fresh_specs_binding():
    engine,source,body=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.triggered_abilities)==2


@pytest.mark.parametrize('type_line',['Creature','Artifact','Enchantment','Land','Planeswalker'])
def test_any_other_permanent_dying_deals_damage_to_all_creatures_and_players(type_line):
    engine,source,body=_board()
    opponent=filler(engine,'Opponent',player='p2',power=2,toughness=5)
    victim=filler(engine,'Victim',type_line=type_line,
                  **({'power':1,'toughness':1} if type_line=='Creature' else {}))
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert victim.zone==Zone.GRAVEYARD and source.zone==Zone.BATTLEFIELD
    assert body.damage_marked==opponent.damage_marked==1
    assert [p.life for p in engine.state.players]==[19,19,19]


def test_no_creatures_sacrifices_without_damaging_players_for_itself():
    engine,source,body=_board(False)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD
    assert [p.life for p in engine.state.players]==[20,20,20]


def test_opponents_creature_is_enough_to_keep_last_laugh():
    engine,source,body=_board(False)
    filler(engine,'Opponent',player='p2',power=1,toughness=1)
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD


def test_damage_cascades_through_creature_deaths():
    engine,source,body=_board()
    first=filler(engine,'First',power=1,toughness=1)
    second=filler(engine,'Second',player='p2',power=1,toughness=1)
    seed=card(engine,'Short Sword')
    engine.rules.destroy(seed)
    engine.resolve_until_stable()
    assert first.zone==second.zone==Zone.GRAVEYARD
    assert body.damage_marked==3
    assert [p.life for p in engine.state.players]==[17,17,17]


def test_last_creature_death_leaves_damage_trigger_after_sacrifice():
    engine,source,body=_board()
    engine.rules.destroy(body)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD
    assert [p.life for p in engine.state.players]==[19,19,19]


@pytest.mark.parametrize('change',['creature_enters','clone','new_visit'])
def test_pending_state_trigger_is_independent_of_later_condition_and_exact_visit(change):
    engine,source,body=_board(False)
    _queue_state(engine)
    if change=='creature_enters':
        filler(engine,'New',power=2,toughness=2)
    elif change=='clone':
        engine=GameEngine(engine.state.clone())
        source=engine.state.find_object(source.instance_id)
    else:
        engine.rules.exile(source)
        filler(engine,'New',power=2,toughness=2)
        engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert source.zone==(Zone.BATTLEFIELD if change=='new_visit' else Zone.GRAVEYARD)


def test_pending_state_trigger_does_not_duplicate_and_countering_retriggers():
    engine,source,body=_board(False)
    _queue_state(engine)
    for _ in range(3):
        engine.rules.check_state_based_actions()
        engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack)==1
    engine.rules.counter_ability(engine.state.stack[-1])
    _queue_state(engine)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD


def test_exile_and_discard_do_not_count_as_permanent_deaths():
    engine,source,body=_board()
    victim=card(engine,'Short Sword')
    engine.rules.exile(victim)
    hand=card(engine,'Short Sword',zone=Zone.HAND)
    engine.rules.discard(engine.state.player_by_id('p1'),1)
    engine.resolve_until_stable()
    assert body.damage_marked==0 and all(p.life==20 for p in engine.state.players)


def test_old_controller_cannot_sacrifice_stolen_source():
    engine,source,body=_board(False)
    _queue_state(engine)
    source.controller_id='p2'
    filler(engine,'New',power=2,toughness=2)
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD


def test_waiting_damage_resolves_after_source_is_exiled():
    engine,source,body=_board()
    victim=card(engine,'Short Sword')
    engine.rules.destroy(victim)
    engine.rules.put_triggers_on_stack()
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert body.damage_marked==1 and all(p.life==19 for p in engine.state.players)


def test_source_going_to_graveyard_does_not_trigger_its_own_damage():
    engine,source,body=_board()
    engine.rules.destroy(source)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD
    assert body.damage_marked==0 and all(p.life==20 for p in engine.state.players)
