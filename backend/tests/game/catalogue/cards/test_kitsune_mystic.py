"""Kitsune's intervening-if flip and Autumn-Tail's untargeted host choice."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.events import EventType, GameEvent
from tests.support.deck_batch import card, filler, game, activate
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Kitsune Mystic')
    return engine,source


def _aura(engine,host,player='p1',name='Aura',quality='creature'):
    aura=filler(engine,name,type_line='Enchantment — Aura',player=player,oracle_text=f'Enchant {quality}')
    assert engine.rules.attach_to_target(aura,host,check_control=False)
    engine.recompute_continuous_effects()
    return aura


def _flip(engine,source):
    _aura(engine,source,name='First')
    _aura(engine,source,player='p2',name='Second')
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert source.flipped


def _move(engine,source,aura,resolve=True):
    engine.state.players[0].mana_pool.add_many({'C':1})
    engine.activate_ability(engine.state.players[0],source,0,targets=[aura])
    if resolve:
        engine.resolve_until_stable()


def _pick(engine,host):
    choice=engine.state.pending_choice
    assert choice['kind']=='autumn_tail_attach'
    engine.resolve_pending_choice(str(host.instance_id))
    engine.resolve_until_stable()


def test_fresh_specs_binding_and_default_not_flipped():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==1 and not source.flipped


@pytest.mark.parametrize('count',[0,1,2,3])
@pytest.mark.parametrize('active',[0,1])
def test_flip_requires_two_auras_on_any_players_end_step(count,active):
    engine,source=_board()
    for i in range(count):
        _aura(engine,source,name=f'Aura {i}',player='p2' if i%2 else 'p1')
    engine.state.active_player_index=active
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert source.flipped==(count>=2)
    if source.flipped:
        assert source.name=='Autumn-Tail, Kitsune Sage' and source.is_legendary
        assert source.power==4 and source.toughness==5


def test_equipment_does_not_count_as_second_aura():
    engine,source=_board()
    _aura(engine,source)
    gear=card(engine,'Swiftfoot Boots')
    engine.rules.attach_to_target(gear,source)
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert not source.flipped


def test_intervening_if_rechecked_when_trigger_resolves():
    engine,source=_board()
    _aura(engine,source,name='First')
    second=_aura(engine,source,name='Second')
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='end'))
    engine.rules.put_triggers_on_stack()
    assert not source.flipped
    engine.rules.exile(second)
    engine.resolve_until_stable()
    assert not source.flipped


def test_opponents_aura_can_move_to_opponents_hexproof_creature():
    engine,source=_board()
    _flip(engine,source)
    old=filler(engine,'Old',player='p2',power=1,toughness=1)
    aura=_aura(engine,old,player='p2')
    bogle=card(engine,'Slippery Bogle',player='p3')
    _move(engine,source,aura)
    assert engine.state.pending_choice['player_id']=='p1'
    assert old.instance_id not in {o['instance_id'] for o in engine.state.pending_choice['options']}
    _pick(engine,bogle)
    assert aura.attached_to==bogle.instance_id and aura.controller_id=='p2'


def test_new_host_must_satisfy_auras_enchant_restriction():
    engine,source=_board()
    _flip(engine,source)
    old=filler(engine,'Old',player='p2',power=1,toughness=1)
    valid=filler(engine,'Valid',player='p2',power=1,toughness=1)
    aura=_aura(engine,old,player='p2',quality='creature you control')
    _move(engine,source,aura)
    assert {o['instance_id'] for o in engine.state.pending_choice['options']}=={valid.instance_id}
    _pick(engine,valid)
    assert aura.attached_to==valid.instance_id


def test_only_aura_attached_to_creature_is_a_target():
    engine,source=_board()
    _flip(engine,source)
    equipment=card(engine,'Swiftfoot Boots')
    engine.rules.attach_to_target(equipment,source)
    player_aura=card(engine,'Curse of Echoes')
    player_aura.attached_to='p2'
    spec=source.activated_abilities[0].effects[0].target_spec
    options=legal_targets(engine.state,'p1',spec,source)
    offered={o['instance_id'] for o in options}
    assert equipment.instance_id not in offered and player_aura.instance_id not in offered
    assert len(offered)==2


@pytest.mark.parametrize('change',['source_leaves','source_stolen','clone'])
def test_pending_new_host_choice_survives_source_changes(change):
    engine,source=_board()
    _flip(engine,source)
    old=filler(engine,'Old host',power=1,toughness=1)
    aura=_aura(engine,old,name='Movable')
    new=filler(engine,'New',power=1,toughness=1)
    _move(engine,source,aura)
    if change=='source_leaves':
        engine.rules.exile(source)
    elif change=='source_stolen':
        source.controller_id='p3'
    else:
        engine=GameEngine(engine.state.clone())
        new=engine.state.find_object(new.instance_id)
        aura=engine.state.find_object(aura.instance_id)
    _pick(engine,new)
    assert aura.attached_to==new.instance_id


def test_target_aura_leaves_before_resolution_ability_does_nothing():
    engine,source=_board()
    _flip(engine,source)
    aura=next(o for o in engine.state.battlefield if o.name=='First')
    _move(engine,source,aura,resolve=False)
    engine.rules.exile(aura)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and aura.zone==Zone.EXILE


def test_second_aura_added_after_beginning_does_not_create_trigger():
    engine,source=_board()
    _aura(engine,source,name='First')
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='end'))
    engine.rules.put_triggers_on_stack()
    _aura(engine,source,name='Second')
    engine.resolve_until_stable()
    assert not source.flipped


def test_no_legal_different_host_leaves_aura_where_it_is():
    engine,source=_board()
    _flip(engine,source)
    old=filler(engine,'Only opponent creature',player='p2',power=1,toughness=1)
    aura=_aura(engine,old,player='p2',quality='creature you control')
    _move(engine,source,aura)
    assert engine.state.pending_choice is None and aura.attached_to==old.instance_id


def test_different_host_is_measured_at_resolution():
    engine,source=_board()
    _flip(engine,source)
    old=filler(engine,'Old',power=1,toughness=1)
    middle=filler(engine,'Middle',power=1,toughness=1)
    aura=_aura(engine,old)
    _move(engine,source,aura,resolve=False)
    engine.rules.attach_to_target(aura,middle,check_control=False)
    engine.resolve_until_stable()
    offered={o['instance_id'] for o in engine.state.pending_choice['options']}
    assert old.instance_id in offered and middle.instance_id not in offered
    _pick(engine,old)
    assert aura.attached_to==old.instance_id


def test_flipped_face_specs_are_fresh():
    engine,source=_board()
    _flip(engine,source)
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
