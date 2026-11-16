"""Nivmagus pays a controlled stack spell, then gets counters on resolution."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,cast,filler,game,main_phase,RICH


def board():
    engine=game(players=3,library=30)
    source=card(engine,'Nivmagus Elemental')
    main_phase(engine)
    return engine,source,engine.state.players[0]


def spell(engine,name='Spell',kind='Instant',player='p1'):
    obj=filler(engine,name,type_line=kind,player=player,zone=Zone.HAND,
               oracle_text='Draw a card.' if kind in ('Instant','Sorcery') else '')
    caster=engine.state.player_by_id(player)
    caster.mana_pool.add_many(RICH)
    if player!='p1':
        engine.state.active_player_index=1
    engine.cast_spell(caster,obj)
    if player!='p1':
        engine.state.active_player_index=0
    return obj


def activate(engine,source,objects=None):
    engine.activate_ability(engine.state.players[0],source,0,
                            tap_choices=None if objects is None else [obj.instance_id for obj in objects])


def test_fresh_specs_bind():
    engine,source,player=board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.activated_abilities)==1


@pytest.mark.parametrize('kind',['Instant','Sorcery'])
def test_exile_cost_precedes_counters_and_spell_does_not_resolve(kind):
    engine,source,player=board()
    obj=spell(engine,kind=kind)
    activate(engine,source,[obj])
    assert obj.zone==Zone.EXILE and obj in player.exile
    assert not source.counters.get('+1/+1')
    assert all(item.obj is not obj for item in engine.state.stack)
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1')==2 and not player.hand
    assert not any(e.type==EventType.SPELL_COUNTERED for e in engine.state.events_this_turn())


def test_automatic_cost_uses_an_eligible_spell():
    engine,source,player=board()
    obj=spell(engine)
    activate(engine,source)
    assert obj.zone==Zone.EXILE


def test_opponents_spell_cannot_pay():
    engine,source,player=board()
    obj=spell(engine,player='p2')
    with pytest.raises(ValueError):activate(engine,source,[obj])
    assert obj.zone==Zone.STACK


def test_permanent_spell_cannot_pay():
    engine,source,player=board()
    obj=spell(engine,kind='Artifact')
    with pytest.raises(ValueError):activate(engine,source,[obj])
    assert obj.zone==Zone.STACK


@pytest.mark.parametrize('indices',[[],[0,0],[0,1]])
def test_exactly_one_spell_is_paid(indices):
    engine,source,player=board()
    spells=[spell(engine,f'Spell {i}') for i in range(2)]
    with pytest.raises(ValueError):activate(engine,source,[spells[i] for i in indices])
    assert all(obj.zone==Zone.STACK for obj in spells)


def test_tapped_summoning_sick_source_can_activate():
    engine,source,player=board()
    obj=spell(engine)
    source.tapped=source.summoning_sick=True
    activate(engine,source,[obj])
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1')==2


def test_countered_ability_does_not_refund_exiled_spell():
    engine,source,player=board()
    obj=spell(engine)
    activate(engine,source,[obj])
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert obj.zone==Zone.EXILE and not source.counters.get('+1/+1')


def test_spell_copy_can_pay_without_consuming_original():
    engine,source,player=board()
    obj=spell(engine)
    copied,=engine.rules.copy_spell(engine.rules._stack_item_for(obj),'p1')
    activate(engine,source,[copied.obj])
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1')==2 and obj.zone==Zone.GRAVEYARD
    assert len(player.hand)==1
    assert copied.obj not in player.exile


def test_clone_preserves_pending_counters_and_paid_cost():
    engine,source,player=board()
    obj=spell(engine)
    activate(engine,source,[obj])
    restored=GameEngine(engine.state.clone())
    restored.resolve_until_stable()
    assert restored.state.find_object(source.instance_id).counters.get('+1/+1')==2
    assert not source.counters.get('+1/+1')


def test_no_eligible_spell_means_no_offer():
    engine,source,player=board()
    assert not any(a['type']=='activate_ability' and a['instance_id']==source.instance_id for a in engine.legal_actions(player))


def test_exiling_the_spell_records_an_exile_event():
    engine,source,player=board()
    obj=spell(engine)
    activate(engine,source,[obj])
    assert any(e.type==EventType.EXILE and e.get('instance_id')==obj.instance_id
               and e.get('from_zone')=='stack' for e in engine.state.events_this_turn())


def test_control_rather_than_ownership_determines_cost_eligibility():
    engine,source,player=board()
    obj=spell(engine,player='p2')
    engine.rules._stack_item_for(obj).controller_id='p1'
    obj.controller_id='p1'
    activate(engine,source,[obj])
    engine.resolve_until_stable()
    assert obj in engine.state.players[1].exile and source.counters.get('+1/+1')==2


def test_actual_cast_then_exile_a_spell_for_counters():
    engine=game(library=30)
    source=card(engine,'Nivmagus Elemental',zone=Zone.HAND)
    cast(engine,source)
    obj=spell(engine)
    activate(engine,source,[obj])
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1')==2


def test_source_departure_does_not_put_counters_on_exiled_card():
    engine,source,player=board()
    obj=spell(engine)
    activate(engine,source,[obj])
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert not source.counters.get('+1/+1')


def test_stack_spell_cost_is_not_a_target_requirement():
    engine,source,player=board()
    obj=spell(engine)
    action=next(a for a in engine.legal_actions(player) if a['type']=='activate_ability' and a['instance_id']==source.instance_id)
    assert not action.get('requires_target')
    assert action['exile_cost']['spell'] and action['exile_cost']['count']==1
    assert action['exile_cost']['options']==[{'instance_id':obj.instance_id,'name':obj.name}]


def test_spell_that_already_left_stack_cannot_pay():
    engine,source,player=board()
    obj=spell(engine)
    engine.rules.move_spell_off_stack(obj,'exile')
    with pytest.raises(ValueError):activate(engine,source,[obj])
    assert not source.counters.get('+1/+1')


def test_returned_source_is_not_the_old_abilitys_creature():
    engine,source,player=board()
    obj=spell(engine)
    activate(engine,source,[obj])
    engine.rules.put_into_graveyard(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD and not source.counters.get('+1/+1')
