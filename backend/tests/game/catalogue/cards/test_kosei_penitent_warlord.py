"""Kosei's three concurrent requirements and granted damage trigger."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def _board(aura=True, equipment=True, counter=True):
    engine = game(players=4, library=30)
    advance_to(engine, 'main1')
    source = card(engine, 'Kosei, Penitent Warlord')
    enchantment = filler(engine, 'Aura', type_line='Enchantment — Aura', oracle_text='Enchant creature')
    gear = card(engine, 'Swiftfoot Boots')
    if aura:
        enchantment.attached_to = source.instance_id
    if equipment:
        gear.attached_to = source.instance_id
    if counter:
        source.counters['quest'] = 1
    engine.recompute_continuous_effects()
    return engine, source, enchantment, gear


def _hit(engine, source, target='p2', amount=2, combat=True):
    engine.rules.deal_damage(engine.state.player_by_id(target),amount,source=source,combat=combat)
    engine.resolve_until_stable()


def _life(engine):
    return [p.life for p in engine.state.players]


def test_fresh_specs_and_live_granted_ability():
    engine, source, _, _ = _board()
    a,b = specs_for(source.card),specs_for(source.card)
    assert len(a)==1 and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source._granted_triggered_abilities)==1


@pytest.mark.parametrize('aura,equipment,counter',[(a,e,c) for a in (False,True) for e in (False,True) for c in (False,True)])
def test_all_three_requirements(aura,equipment,counter):
    engine,source,_,_ = _board(aura,equipment,counter)
    player=engine.state.player_by_id('p1')
    before=len(player.hand)
    _hit(engine,source)
    enabled=aura and equipment and counter
    assert len(player.hand)==before+(2 if enabled else 0)
    assert _life(engine)==([20,18,18,18] if enabled else [20,18,20,20])


@pytest.mark.parametrize('kind',['noncombat','self','other_source','creature','zero'])
def test_wrong_damage_does_not_trigger(kind):
    engine,source,_,_= _board()
    player=engine.state.player_by_id('p1')
    before=len(player.hand)
    if kind=='creature':
        target=filler(engine,'Blocker',player='p2',power=1,toughness=5)
        engine.rules.deal_damage(target,2,source=source,combat=True)
        engine.resolve_until_stable()
    else:
        dealer=filler(engine,'Other',power=2,toughness=2) if kind=='other_source' else source
        _hit(engine,dealer,target='p1' if kind=='self' else 'p2',amount=0 if kind=='zero' else 2,combat=kind!='noncombat')
    assert len(player.hand)==before
    assert engine.state.player_by_id('p3').life==20


@pytest.mark.parametrize('lost',['aura','equipment','counter'])
def test_losing_condition_after_trigger_does_not_cancel_it(lost):
    engine,source,aura,gear=_board()
    engine.rules.deal_damage(engine.state.player_by_id('p2'),2,source=source,combat=True)
    engine.rules.put_triggers_on_stack()
    if lost=='counter':
        source.counters.clear()
    else:
        (aura if lost=='aura' else gear).attached_to=None
    engine.recompute_continuous_effects()
    assert not source._granted_triggered_abilities
    engine.resolve_until_stable()
    assert len(engine.state.player_by_id('p1').hand)==3
    assert _life(engine)==[20,18,18,18]
    _hit(engine,source)
    assert _life(engine)==[20,16,18,18]


def test_trigger_survives_source_departure_and_clone():
    engine,source,_,_=_board()
    engine.rules.deal_damage(engine.state.player_by_id('p2'),2,source=source,combat=True)
    engine.rules.put_triggers_on_stack()
    engine.rules.exile(source)
    clone=GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert _life(clone)==[20,18,18,18]
    assert len(clone.state.player_by_id('p1').hand)==3


def test_ability_returns_when_last_requirement_is_restored():
    engine,source,aura,_=_board(aura=False)
    assert not source._granted_triggered_abilities
    aura.attached_to=source.instance_id
    engine.recompute_continuous_effects()
    _hit(engine,source)
    _hit(engine,source,target='p3',amount=1)
    assert _life(engine)==[20,17,17,17]
    assert len(engine.state.player_by_id('p1').hand)==4


@pytest.mark.parametrize('counter',['+1/+1','shield','charge'])
def test_any_counter_kind_qualifies(counter):
    engine,source,_,_=_board(counter=False)
    engine.rules.add_counters(source,1,counter)
    engine.recompute_continuous_effects()
    _hit(engine,source)
    assert _life(engine)==[20,18,18,18]


@pytest.mark.parametrize('attachment_type,expected',[
    ('Artifact Enchantment — Aura',True),
    ('Artifact — Fortification',False),
    ('Artifact',False),
])
def test_aura_is_distinct_from_equipment(attachment_type,expected):
    engine,source,aura,_=_board()
    aura.attached_to=None
    alternate=filler(engine,'Alternate',type_line=attachment_type,oracle_text='Enchant creature' if expected else '')
    alternate.attached_to=source.instance_id
    engine.recompute_continuous_effects()
    _hit(engine,source)
    assert engine.state.player_by_id('p3').life==(18 if expected else 20)


def test_control_of_attachments_does_not_matter():
    engine,source,aura,gear=_board()
    aura.controller_id='p3'
    gear.controller_id='p4'
    engine.recompute_continuous_effects()
    _hit(engine,source)
    assert _life(engine)==[20,18,18,18]


def test_fortification_does_not_count_as_equipment():
    engine,source,_,gear=_board()
    gear.attached_to=None
    fort=filler(engine,'Fort',type_line='Artifact — Fortification')
    fort.attached_to=source.instance_id
    engine.recompute_continuous_effects()
    _hit(engine,source)
    assert _life(engine)==[20,18,20,20]


def test_queued_trigger_keeps_its_controller():
    engine,source,_,_=_board()
    engine.rules.deal_damage(engine.state.player_by_id('p2'),2,source=source,combat=True)
    engine.rules.put_triggers_on_stack()
    source.controller_id='p3'
    engine.recompute_continuous_effects()
    engine.resolve_until_stable()
    assert _life(engine)==[20,18,18,18]
    assert len(engine.state.player_by_id('p1').hand)==3
    assert not engine.state.player_by_id('p3').hand


def test_real_combat_damage_draws_and_hits_other_opponents():
    engine,source,_,_=_board(counter=False)
    engine.rules.add_counters(source,1,'+1/+1')
    engine.recompute_continuous_effects()
    advance_to(engine,'declare_attackers')
    engine.declare_attackers(engine.state.player_by_id('p1'),[
        {'attacker':source,'defender':engine.state.player_by_id('p2')}])
    advance_to(engine,'combat_damage')
    engine.resolve_until_stable()
    assert _life(engine)==[20,19,19,19]
    assert len(engine.state.player_by_id('p1').hand)==2
