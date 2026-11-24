"""Eriette's mana-value comparison and Aura-bound control duration."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, cast
from tests.support.star_trek import advance_to


def _board(kind='Creature', mv=3, aura_mv=3, host_player='p2', aura_player='p1'):
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    eriette=card(engine,'Eriette, the Beguiler')
    host=filler(engine,'Host',type_line=kind,player=host_player,mv=mv,
        power=2 if 'Creature' in kind else None,toughness=3 if 'Creature' in kind else None)
    if kind=='Planeswalker':
        host.counters['loyalty']=3
    aura=filler(engine,'Aura',type_line='Enchantment — Aura',player=aura_player,mv=aura_mv,oracle_text='Enchant permanent')
    return engine,eriette,host,aura


def _attach(engine,aura,host,resolve=True):
    assert engine.rules.attach_to_target(aura,host,check_control=False)
    engine.rules.put_triggers_on_stack()
    if resolve:
        engine.resolve_until_stable()


def test_specs_fresh_binding_and_lifelink():
    engine,eriette,host,aura=_board()
    a,b=specs_for(eriette.card),specs_for(eriette.card)
    assert len(a)==2 and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(eriette.triggered_abilities)==1 and combat.has(eriette,'lifelink')
    _attach(engine,aura,host)
    engine.rules.deal_damage(engine.state.players[1],2,source=eriette)
    assert engine.state.players[0].life==22


@pytest.mark.parametrize('kind',['Creature','Artifact','Enchantment','Planeswalker'])
@pytest.mark.parametrize('mv,expected',[(0,'p1'),(2,'p1'),(3,'p1'),(4,'p2')])
def test_nonland_host_mana_value_comparison(kind,mv,expected):
    engine,eriette,host,aura=_board(kind=kind,mv=mv)
    host.tapped=True
    _attach(engine,aura,host)
    assert host.controller_id==expected
    assert host.tapped and not combat.has(host,'haste')


@pytest.mark.parametrize('kind,host_player,aura_player',[('Land','p2','p1'),('Creature','p1','p1'),('Creature','p2','p3')])
def test_land_own_permanent_or_opponents_aura_does_not_trigger(kind,host_player,aura_player):
    engine,eriette,host,aura=_board(kind=kind,host_player=host_player,aura_player=aura_player)
    _attach(engine,aura,host)
    assert host.controller_id==host_player


@pytest.mark.parametrize('change',['eriette_leaves','eriette_stolen','aura_stolen','clone'])
def test_duration_survives_eriette_departure_or_control_changes(change):
    engine,eriette,host,aura=_board()
    _attach(engine,aura,host)
    if change=='eriette_leaves':
        engine.rules.exile(eriette)
    elif change=='eriette_stolen':
        eriette.controller_id='p3'
    elif change=='aura_stolen':
        aura.controller_id='p3'
    else:
        engine=GameEngine(engine.state.clone())
        host=engine.state.find_object(host.instance_id)
    engine.recompute_continuous_effects()
    assert host.controller_id=='p1'


@pytest.mark.parametrize('change',['detach','reattach','aura_leaves','aura_returns','host_leaves'])
def test_control_ends_when_original_attachment_ends(change):
    engine,eriette,host,aura=_board()
    _attach(engine,aura,host)
    if change=='detach':
        aura.attached_to=None
        aura.attachment_generation+=1
    elif change=='reattach':
        other=filler(engine,'Other',player='p3',power=1,toughness=1,mv=6)
        engine.rules.attach_to_target(aura,other,check_control=False)
    elif change in ('aura_leaves','aura_returns'):
        engine.rules.exile(aura)
        if change=='aura_returns':
            engine.rules.return_from_graveyard(aura,'battlefield')
            aura.attached_to=host.instance_id
    else:
        engine.rules.exile(host)
        engine.rules.return_from_graveyard(host,'battlefield')
    engine.recompute_continuous_effects()
    assert host.controller_id=='p2'


@pytest.mark.parametrize('change',['aura_leaves','host_leaves','detach_return','eriette_leaves','eriette_stolen','aura_stolen','host_stolen'])
def test_pending_trigger_uses_original_visits_and_captured_controller(change):
    engine,eriette,host,aura=_board()
    _attach(engine,aura,host,resolve=False)
    if change=='aura_leaves':
        engine.rules.exile(aura)
    elif change=='host_leaves':
        engine.rules.exile(host)
        engine.rules.return_from_graveyard(host,'battlefield')
    elif change=='detach_return':
        aura.attached_to=None
        aura.attachment_generation+=1
        aura.attached_to=host.instance_id
    elif change=='eriette_leaves':
        engine.rules.exile(eriette)
    elif change=='eriette_stolen':
        eriette.controller_id='p3'
    elif change=='aura_stolen':
        aura.controller_id='p3'
    else:
        host.controller_id='p3'
    engine.resolve_until_stable()
    assert host.controller_id==('p2' if change in ('aura_leaves','host_leaves','detach_return') else 'p1')


def test_same_attachment_does_not_trigger_twice():
    engine,eriette,host,aura=_board()
    _attach(engine,aura,host)
    engine.rules.attach_to_target(aura,host)
    engine.rules.put_triggers_on_stack()
    assert not engine.state.stack


def test_real_aura_cast_triggers_control_change():
    engine,eriette,host,aura=_board()
    # The fixture Aura is not needed for this cast.
    engine.rules.exile(aura)
    spell=card(engine,'Pacifism',zone=Zone.HAND)
    host.card.converted_mana_cost=2
    cast(engine,spell,targets=[host])
    assert spell.attached_to==host.instance_id and host.controller_id=='p1'


@pytest.mark.parametrize('change',['aura_mv','host_mv'])
def test_mana_value_comparison_is_not_rechecked_at_resolution(change):
    engine,eriette,host,aura=_board()
    _attach(engine,aura,host,resolve=False)
    if change=='aura_mv':
        aura.card.converted_mana_cost=0
    else:
        host.card.converted_mana_cost=9
    engine.resolve_until_stable()
    assert host.controller_id=='p1'


def test_cloned_control_clock_ends_when_aura_moves():
    engine,eriette,host,aura=_board()
    _attach(engine,aura,host)
    engine=GameEngine(engine.state.clone())
    host=engine.state.find_object(host.instance_id)
    aura=engine.state.find_object(aura.instance_id)
    aura.attached_to=None
    aura.attachment_generation+=1
    engine.recompute_continuous_effects()
    assert host.controller_id=='p2'


def test_phasing_out_aura_ends_for_as_long_as_duration():
    engine,eriette,host,aura=_board()
    _attach(engine,aura,host)
    # RULE 702.26f: a for-as-long-as duration can no longer see the phased-out Aura.
    aura.phased_out=True
    engine.recompute_continuous_effects()
    assert host.controller_id=='p2'
    aura.phased_out=False
    engine.recompute_continuous_effects()
    assert host.controller_id=='p2'


def test_equipment_attachment_does_not_trigger():
    engine,eriette,host,aura=_board(mv=0)
    engine.rules.exile(aura)
    equipment=card(engine,'Swiftfoot Boots')
    _attach(engine,equipment,host)
    assert host.controller_id=='p2'
