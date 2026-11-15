"""Concerted Effort shares a resolution-time snapshot, including qualified abilities."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, step
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    effort=card(engine,'Concerted Effort')
    recipient=filler(engine,'Recipient',power=2,toughness=2)
    enemy=filler(engine,'Enemy',player='p2',power=2,toughness=2)
    return engine,effort,recipient,enemy


def donor(engine,text,keywords=None):
    return filler(engine,'Donor '+text,power=2,toughness=2,oracle_text=text,keywords=keywords or [])


def upkeep(engine,actor='p2'):
    step(engine,'upkeep',player=actor)


def test_fresh_specs_and_binding():
    engine,effort,recipient,enemy=board()
    a,b=specs_for(effort.card),specs_for(effort.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(effort.triggered_abilities)==1


@pytest.mark.parametrize('keyword,slug',[('Flying','flying'),('Fear','fear'),('First strike','first_strike'),
    ('Double strike','double_strike'),('Trample','trample'),('Vigilance','vigilance')])
def test_named_keywords_are_shared_only_with_own_current_creatures(keyword,slug):
    engine,effort,recipient,enemy=board(); donor(engine,keyword,[keyword])
    upkeep(engine)
    assert combat.has(recipient,slug) and not combat.has(enemy,slug)
    later=filler(engine,'Later',power=2,toughness=2)
    assert not combat.has(later,slug)


def test_unlisted_keywords_are_not_shared():
    engine,effort,recipient,enemy=board(); donor(engine,'Flying, lifelink, deathtouch',['Flying','Lifelink','Deathtouch'])
    upkeep(engine)
    assert combat.has(recipient,'flying')
    assert not combat.has(recipient,'lifelink') and not combat.has(recipient,'deathtouch')


def test_exact_multiple_protection_qualities_are_shared():
    engine,effort,recipient,enemy=board()
    donor(engine,'Protection from red and from artifacts')
    gifted=donor(engine,''); gifted.temp_protections.add('U')
    upkeep(engine)
    red=filler(engine,'Red',power=2,toughness=2,color_identity=['R'])
    blue=filler(engine,'Blue',power=2,toughness=2,color_identity=['U'])
    green=filler(engine,'Green',power=2,toughness=2,color_identity=['G'])
    artifact=filler(engine,'Artifact',type_line='Artifact')
    assert all(combat.is_protected_from(recipient,obj) for obj in [red,blue,artifact])
    assert not combat.is_protected_from(recipient,green)


@pytest.mark.parametrize('ability,land_name,blocked',[
    ('Islandwalk','Island',True),('Islandwalk','Forest',False),
    ('Nonbasic landwalk','Command Tower',True),('Nonbasic landwalk','Forest',False),
    ('Legendary landwalk','Eiganjo, Seat of the Empire',True),
    ('Snow landwalk','Snow-Covered Forest',True),
])
def test_landwalk_qualities_are_copied_and_govern_blocking(ability,land_name,blocked):
    engine,effort,recipient,enemy=board(); donor(engine,ability,['Landwalk'])
    land=card(engine,land_name,player='p2')
    upkeep(engine)
    assert combat.unblockable_by_landwalk(recipient,[land])==blocked


def test_abilities_are_read_at_resolution_not_trigger_time():
    from mtg_analyzer.models.game.events import EventType,GameEvent
    engine,effort,recipient,enemy=board()
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep',player_id='p2',controller_id='p2'))
    donor(engine,'Flying',['Flying'])
    engine.resolve_until_stable()
    assert combat.has(recipient,'flying')


def test_lost_donor_abilities_are_not_copied():
    engine,effort,recipient,enemy=board(); gifted=donor(engine,'Flying\nProtection from red',['Flying'])
    aura=card(engine,'Darksteel Mutation'); aura.attached_to=gifted.instance_id
    engine.recompute_continuous_effects(); upkeep(engine)
    assert not combat.has(recipient,'flying') and not recipient.granted_protections


def test_source_and_donor_departure_do_not_end_resolved_grants():
    engine,effort,recipient,enemy=board(); gifted=donor(engine,'Flying',['Flying'])
    upkeep(engine); engine.rules.exile(effort); engine.rules.exile(gifted)
    engine.recompute_continuous_effects()
    assert combat.has(recipient,'flying')
    advance_to(engine,'cleanup'); engine.recompute_continuous_effects()
    assert not combat.has(recipient,'flying')


def test_clone_keeps_shared_protection_and_landwalk_until_cleanup():
    engine,effort,recipient,enemy=board(); donor(engine,'Islandwalk\nProtection from red',['Landwalk'])
    upkeep(engine)
    clone=GameEngine(engine.state.clone()); clone.recompute_continuous_effects()
    copied=clone.state.find_object(recipient.instance_id)
    assert 'R' in copied.granted_protections and 'islandwalk' in copied.granted_keywords


def test_shared_abilities_remain_on_a_creature_after_control_changes():
    engine,effort,recipient,enemy=board(); donor(engine,'Flying',['Flying'])
    upkeep(engine); recipient.controller_id='p2'; engine.recompute_continuous_effects()
    assert combat.has(recipient,'flying')


def test_canonical_named_and_blanket_protection_qualities_are_preserved():
    engine,effort,recipient,enemy=board(); gifted=donor(engine,'')
    gifted.temp_protections.update({'name:Named source','all_colors'})
    upkeep(engine)
    named=filler(engine,'Named source',type_line='Artifact')
    colored=filler(engine,'Green source',power=2,toughness=2,color_identity=['G'])
    unrelated=filler(engine,'Unrelated',type_line='Artifact')
    assert combat.is_protected_from(recipient,named) and combat.is_protected_from(recipient,colored)
    assert not combat.is_protected_from(recipient,unrelated)


def test_countered_upkeep_trigger_grants_nothing():
    from mtg_analyzer.models.game.events import EventType,GameEvent
    engine,effort,recipient,enemy=board(); donor(engine,'Flying',['Flying'])
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep',player_id='p2',controller_id='p2'))
    engine.rules.put_triggers_on_stack(); engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert not combat.has(recipient,'flying')
