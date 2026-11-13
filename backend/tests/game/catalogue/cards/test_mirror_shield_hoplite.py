"""Mirror-Shield Hoplite identifies backup abilities and copies their stack values."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, cast, enter, activate
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    hoplite=card(engine,'Mirror-Shield Hoplite')
    target=filler(engine,'Target',power=2,toughness=5)
    return engine,hoplite,target


def _backup(engine,target,player='p1',pause_before_copy=False):
    source=card(engine,'Bola Slinger',player=player)
    enter(engine,source)
    engine.resolve_until_stable()
    choice=engine.state.pending_choice
    assert choice is not None
    option=next(o for o in choice['options'] if o.get('instance_id')==target.instance_id)
    if pause_before_copy:
        engine.rules.resolve_choice(option['id'])
        engine.rules.put_triggers_on_stack()
    else:
        engine.resolve_pending_choice(option['id'])
        engine.resolve_until_stable()
    return source


def _finish_copy(engine,target=None):
    choice=engine.state.pending_choice
    assert choice['kind']=='copy_targets' and choice['player_id']=='p1'
    if target is None:
        engine.resolve_pending_choice('decline')
    else:
        option=next(o for o in choice['options'] if o.get('instance_id')==target.instance_id)
        engine.resolve_pending_choice(option['id'])
    engine.resolve_until_stable()


def test_fresh_specs_binding_and_vigilance():
    engine,hoplite,target=_board()
    a,b=specs_for(hoplite.card),specs_for(hoplite.card)
    assert len(a)==2 and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(hoplite.triggered_abilities)==1 and combat.has(hoplite,'vigilance')


@pytest.mark.parametrize('target_self',[False,True])
def test_backup_copy_keeps_original_target(target_self):
    engine,hoplite,target=_board()
    target=hoplite if target_self else target
    _backup(engine,target)
    _finish_copy(engine)
    assert target.counters.get('+1/+1')==2


def test_copy_can_choose_a_new_target():
    engine,hoplite,target=_board()
    _backup(engine,target)
    _finish_copy(engine,hoplite)
    assert target.counters.get('+1/+1')==1 and hoplite.counters.get('+1/+1')==1


def test_opponents_backup_targeting_your_creature_also_copies():
    engine,hoplite,target=_board()
    _backup(engine,target,player='p2')
    _finish_copy(engine)
    assert target.counters.get('+1/+1')==2


def test_backup_targeting_opponents_creature_does_not_spend_limit():
    engine,hoplite,target=_board()
    other=filler(engine,player='p2',power=2,toughness=2)
    _backup(engine,other)
    assert engine.state.pending_choice is None and other.counters.get('+1/+1')==1
    _backup(engine,target)
    _finish_copy(engine)
    assert target.counters.get('+1/+1')==2


def test_once_each_turn_and_clone_keep_spent_limit():
    engine,hoplite,target=_board()
    _backup(engine,target)
    _finish_copy(engine)
    engine=GameEngine(engine.state.clone())
    target=engine.state.find_object(target.instance_id)
    _backup(engine,target)
    assert engine.state.pending_choice is None and target.counters.get('+1/+1')==3
    engine.begin_turn()
    advance_to(engine,'main1')
    _backup(engine,target)
    _finish_copy(engine)
    assert target.counters.get('+1/+1')==5


@pytest.mark.parametrize('kind',['spell','activated'])
def test_other_targeted_spells_and_abilities_do_not_consume_limit(kind):
    engine,hoplite,target=_board()
    if kind=='spell':
        cast(engine,card(engine,'Defiant Strike',zone=Zone.HAND),targets=[target])
    else:
        pinger=card(engine,'Prodigal Pyromancer')
        activate(engine,pinger,targets=[target])
    assert engine.state.pending_choice is None
    _backup(engine,target)
    _finish_copy(engine)
    assert target.counters.get('+1/+1')==2


@pytest.mark.parametrize('change',['hoplite_leaves','hoplite_stolen','clone','backup_leaves','counter_original'])
def test_copy_target_choice_survives_source_changes(change):
    engine,hoplite,target=_board()
    backup=_backup(engine,target)
    if change=='hoplite_leaves':
        engine.rules.exile(hoplite)
    elif change=='hoplite_stolen':
        hoplite.controller_id='p3'
    elif change=='backup_leaves':
        engine.rules.exile(backup)
    elif change=='counter_original':
        original=next(i for i in engine.state.stack if i.source is backup)
        engine.rules.counter_ability(original)
    else:
        engine=GameEngine(engine.state.clone())
        target=engine.state.find_object(target.instance_id)
    _finish_copy(engine)
    assert target.counters.get('+1/+1')==(1 if change=='counter_original' else 2)



def test_original_countered_before_hoplite_resolves_still_has_copy_recipe():
    engine,hoplite,target=_board()
    backup=_backup(engine,target,pause_before_copy=True)
    original=next(i for i in engine.state.stack if i.source is backup)
    engine.rules.counter_ability(original)
    engine=GameEngine(engine.state.clone())
    target=engine.state.find_object(target.instance_id)
    engine.resolve_until_stable()
    _finish_copy(engine)
    assert target.counters.get('+1/+1')==1


def test_multiple_hoplites_each_copy_once_without_recursive_copies():
    engine,hoplite,target=_board()
    engine.rules.copy_permanent('p1',hoplite)
    _backup(engine,target)
    for _ in range(12):
        choice=engine.state.pending_choice
        if choice is None:
            break
        if choice['kind']=='copy_targets':
            engine.resolve_pending_choice('decline')
        else:
            # Order the two identical Hoplite triggers deterministically.
            engine.resolve_pending_choice(choice['options'][0]['id'])
        engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert target.counters.get('+1/+1')==3
