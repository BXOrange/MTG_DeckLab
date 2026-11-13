"""Savage Summoning binds its one-shot riders to the next creature cast."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, cast, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    return engine


def _summon(engine):
    spell=card(engine,'Savage Summoning',zone=Zone.HAND)
    cast(engine,spell)
    return spell


def _creature(engine,name='Grizzly Bears',player='p1',resolve=True):
    obj=card(engine,name,player=player,zone=Zone.HAND)
    p=engine.state.player_by_id(player)
    p.mana_pool.add_many(RICH)
    engine.cast_spell(p,obj)
    if resolve:
        engine.resolve_until_stable()
    return obj


def test_fresh_specs_and_summoning_itself_cannot_be_countered():
    engine=_board()
    spell=card(engine,'Savage Summoning',zone=Zone.HAND)
    a,b=specs_for(spell.card),specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[1] is not b[0].effects[1]
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    engine.cast_spell(p,spell)
    assert engine.rules._is_cant_be_countered(spell)
    engine.rules.counter_spell(spell)
    assert spell.zone==Zone.STACK
    engine.resolve_until_stable()
    assert len(engine.state.next_spell_flash_grants)==1


def test_only_next_creature_gets_counter_and_protection():
    engine=_board()
    _summon(engine)
    first=_creature(engine,resolve=False)
    assert first.entry_bonus_counters=={'+1/+1':1}
    assert engine.rules._is_cant_be_countered(first)
    engine.rules.counter_spell(first)
    assert first.zone==Zone.STACK
    engine.resolve_until_stable()
    assert first.zone==Zone.BATTLEFIELD and first.counters=={'+1/+1':1}
    second=_creature(engine)
    assert second.counters=={} and not engine.rules._is_cant_be_countered(second)


def test_next_creature_can_be_cast_during_opponents_turn():
    engine=_board()
    _summon(engine)
    advance_to(engine,'untap')
    # The grant expires next turn, so use an opponent's turn from the start.
    engine=_board()
    engine.state.active_player_index=1
    _summon(engine)
    engine.state.active_player_index=1
    engine.state.current_step='end'
    obj=card(engine,'Grizzly Bears',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert engine.can_cast(p,obj)
    engine.cast_spell(p,obj)
    engine.resolve_until_stable()
    assert obj.zone==Zone.BATTLEFIELD and obj.counters=={'+1/+1':1}
    another=card(engine,'Grizzly Bears',zone=Zone.HAND)
    assert not engine.can_cast(p,another)


def test_noncreature_and_opponents_creature_do_not_consume_grant():
    engine=_board()
    _summon(engine)
    cast(engine,card(engine,'Short Sword',zone=Zone.HAND))
    opponent=_creature(engine,player='p2')
    assert opponent.counters=={}
    assert len(engine.state.next_spell_flash_grants)==1
    own=_creature(engine)
    assert own.counters=={'+1/+1':1}


def test_multiple_summonings_stack_on_same_next_creature():
    engine=_board()
    _summon(engine)
    _summon(engine)
    obj=_creature(engine)
    assert obj.counters=={'+1/+1':2}
    assert not engine.state.next_spell_flash_grants


def test_grant_expires_at_end_of_turn_if_unused():
    engine=_board()
    _summon(engine)
    advance_to(engine,'untap')
    assert not engine.state.next_spell_flash_grants
    advance_to(engine,'main1')
    obj=_creature(engine)
    assert obj.counters=={} and not obj.cast_uncounterable


def test_native_entry_counters_add_to_summoning_counter():
    engine=_board()
    _summon(engine)
    obj=_creature(engine,'Walking Ballista')
    assert obj.zone==Zone.BATTLEFIELD and obj.counters=={'+1/+1':1}


def test_counter_rider_does_not_survive_later_zone_visit():
    engine=_board()
    _summon(engine)
    obj=_creature(engine,resolve=False)
    engine.rules.exile(obj)
    engine.resolve_until_stable()
    engine.rules.return_to_hand(obj)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    engine.cast_spell(p,obj)
    engine.resolve_until_stable()
    assert obj.counters=={} and not obj.cast_uncounterable


@pytest.mark.parametrize('when',['before_cast','on_stack'])
def test_clone_preserves_unconsumed_or_bound_riders(when):
    engine=_board()
    _summon(engine)
    obj=_creature(engine,resolve=False) if when=='on_stack' else None
    clone=GameEngine(engine.state.clone())
    if obj is None:
        target=_creature(clone)
    else:
        target=clone.state.find_object(obj.instance_id)
        clone.resolve_until_stable()
    assert target.counters=={'+1/+1':1}


def test_control_change_keeps_both_spell_bound_riders():
    engine=_board()
    _summon(engine)
    obj=_creature(engine,resolve=False)
    item=next(i for i in engine.state.stack if i.obj is obj)
    obj.controller_id=item.controller_id='p2'
    assert engine.rules._is_cant_be_countered(obj)
    engine.resolve_until_stable()
    assert obj.controller_id=='p2' and obj.counters=={'+1/+1':1}
