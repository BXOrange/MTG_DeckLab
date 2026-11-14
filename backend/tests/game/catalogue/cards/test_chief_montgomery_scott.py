"""Chief Montgomery Scott puts cards in with type-dependent entry counters."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def board(lands=2):
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    scott=card(engine,'Chief Montgomery Scott')
    if lands:
        card(engine,'Forest'); card(engine,'Forest')
    if lands>1:
        card(engine,'Island')
    card(engine,'Swamp',player='p2')
    player=engine.state.player_by_id('p1'); player.mana_pool.add_many(RICH)
    return engine,scott,player


def start(engine,scott,player):
    engine.activate_ability(player,scott,0)
    engine.resolve_until_stable()
    return engine.state.pending_choice


def pick(engine,obj):
    choice=engine.state.pending_choice
    option=next(o for o in choice['options'] if o.get('instance_id')==obj.instance_id)
    engine.resolve_pending_choice(str(option['id']))


def test_fresh_specs_binding():
    engine,scott,player=board()
    a,b=specs_for(scott.card),specs_for(scott.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(scott.activated_abilities)==1


@pytest.mark.parametrize('type_line,expected', [
    ('Creature', {'+1/+1':2}), ('Artifact — Spacecraft',{'charge':2}),
    ('Artifact Creature — Spacecraft', {'+1/+1':2,'charge':2}),
])
def test_entry_counter_types(type_line,expected):
    engine,scott,player=board()
    obj=filler(engine,'Entrant',type_line=type_line,power=1 if 'Creature' in type_line else None,
               toughness=1 if 'Creature' in type_line else None,zone=Zone.HAND)
    choice=start(engine,scott,player)
    assert scott.tapped and obj.zone==Zone.HAND
    pick(engine,obj)
    assert obj.zone==Zone.BATTLEFIELD and obj.counters==expected
    assert not obj.tapped


def test_decline_keeps_hand_card_and_paid_cost():
    engine,scott,player=board()
    obj=card(engine,'Serra Angel',zone=Zone.HAND)
    start(engine,scott,player)
    engine.resolve_pending_choice('decline')
    assert obj.zone==Zone.HAND and scott.tapped


def test_only_creature_or_spacecraft_cards_are_offered():
    engine,scott,player=board()
    creature=card(engine,'Serra Angel',zone=Zone.HAND)
    land=card(engine,'Forest',zone=Zone.HAND)
    artifact=filler(engine,'Rock',type_line='Artifact',zone=Zone.HAND)
    choice=start(engine,scott,player)
    offered={o.get('instance_id') for o in choice['options']}
    assert creature.instance_id in offered
    assert land.instance_id not in offered and artifact.instance_id not in offered


def test_zero_lands_still_puts_creature_without_counters():
    engine,scott,player=board(0)
    obj=card(engine,'Serra Angel',zone=Zone.HAND)
    start(engine,scott,player); pick(engine,obj)
    assert obj.zone==Zone.BATTLEFIELD and not obj.counters


def test_native_entry_counters_are_additional():
    engine,scott,player=board()
    obj=card(engine,'Triskelion',zone=Zone.HAND)
    start(engine,scott,player); pick(engine,obj)
    assert obj.counters.get('+1/+1')==5


def test_pending_choice_survives_clone_and_source_departure():
    engine,scott,player=board()
    obj=card(engine,'Serra Angel',zone=Zone.HAND)
    start(engine,scott,player)
    clone=GameEngine(engine.state.clone())
    clone.rules.exile(clone.state.find_object(scott.instance_id))
    pick(clone,clone.state.find_object(obj.instance_id))
    entrant=clone.state.find_object(obj.instance_id)
    assert entrant.zone==Zone.BATTLEFIELD and entrant.counters.get('+1/+1')==2
    assert obj.zone==Zone.HAND


def test_no_eligible_hand_card_finishes_without_choice():
    engine,scott,player=board()
    start(engine,scott,player)
    assert engine.state.pending_choice is None and scott.tapped



def test_entry_trigger_sees_bonus_power():
    engine,scott,player=board()
    card(engine,'Elemental Bond')
    obj=filler(engine,'Entrant',power=1,toughness=1,zone=Zone.HAND)
    before=len(player.hand)
    start(engine,scott,player); pick(engine,obj)
    assert obj.power==3
    assert len(player.hand)==before  # one card entered and the Bond drew one


def test_lands_are_counted_at_resolution_not_activation():
    engine,scott,player=board()
    obj=card(engine,'Serra Angel',zone=Zone.HAND)
    engine.activate_ability(player,scott,0)
    card(engine,'Mountain')
    engine.resolve_until_stable(); pick(engine,obj)
    assert obj.counters.get('+1/+1')==3


def test_countered_ability_does_not_put_card_into_play():
    engine,scott,player=board()
    obj=card(engine,'Serra Angel',zone=Zone.HAND)
    engine.activate_ability(player,scott,0)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert obj.zone==Zone.HAND and scott.tapped and engine.state.pending_choice is None
