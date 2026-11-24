"""Mossbridge Troll uses actual total power and regenerates for every replaceable destruction."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,cast,filler,game


def board(*powers):
    engine=game(players=3,library=30);source=card(engine,'Mossbridge Troll')
    creatures=[filler(engine,f'Contributor {i}',power=p,toughness=20) for i,p in enumerate(powers)]
    return engine,source,creatures


def activate(engine,source,creatures=None):
    engine.activate_ability(engine.state.players[0],source,0,tap_choices=None if creatures is None else [obj.instance_id for obj in creatures])


def test_fresh_specs_bind_persistent_replacement_and_activation():
    engine,source,creatures=board(10);a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.replacement_effects)==len(source.activated_abilities)==1


def test_actual_cast_and_power_cost_then_temporary_boost():
    engine=game(library=30);source=card(engine,'Mossbridge Troll',zone=Zone.HAND);cast(engine,source)
    a=card(engine,'Colossal Dreadmaw');b=card(engine,'Colossal Dreadmaw')
    activate(engine,source,[a,b])
    assert a.tapped and b.tapped and source.power==5 and not source.tapped
    engine.resolve_until_stable();assert source.power==source.toughness==25
    engine._step_cleanup();engine.recompute_continuous_effects()
    assert source.power==source.toughness==5 and len(source.replacement_effects)==1


@pytest.mark.parametrize('powers',[(10,),(6,4),(6,6),(6,6,0,-2)])
def test_legal_subset_can_meet_or_exceed_ten_with_signed_power(powers):
    engine,source,creatures=board(*powers)
    for obj in creatures:obj.summoning_sick=True
    activate(engine,source,creatures);engine.resolve_until_stable()
    assert all(obj.tapped for obj in creatures) and source.power==25
    assert not getattr(source,'crewed_by_ids',[])


@pytest.mark.parametrize('powers',[(9,),(6,6,-3),(0,0)])
def test_insufficient_selected_power_pays_nothing(powers):
    engine,source,creatures=board(*powers)
    with pytest.raises(ValueError):activate(engine,source,creatures)
    assert not any(obj.tapped for obj in creatures) and not engine.state.stack


def test_source_cannot_contribute_its_own_power():
    engine,source,creatures=board(6)
    with pytest.raises(ValueError):activate(engine,source,[source,*creatures])
    assert not source.tapped and not creatures[0].tapped


def test_duplicate_tapped_and_opposing_contributors_are_rejected():
    engine,source,creatures=board(6,4)
    with pytest.raises(ValueError):activate(engine,source,[creatures[0],creatures[0]])
    creatures[1].tapped=True
    with pytest.raises(ValueError):activate(engine,source,creatures)
    creatures[1].tapped=False;creatures[1].controller_id='p2'
    with pytest.raises(ValueError):activate(engine,source,creatures)
    assert not creatures[0].tapped


def test_automatic_choice_uses_enough_high_power_creatures():
    engine,source,creatures=board(2,6,4,-3)
    activate(engine,source)
    assert [obj.tapped for obj in creatures]==[False,True,True,False]


def test_picker_reports_current_plain_power_and_excludes_source():
    engine,source,creatures=board(6,4,-2)
    creatures[0].add_counters('+1/+1',1);engine.recompute_continuous_effects()
    action=next(a for a in engine.legal_actions(engine.state.players[0]) if a['type']=='activate_ability' and a['instance_id']==source.instance_id)
    assert action['power_tap_cost']['power_required']==10
    assert [o['power'] for o in action['power_tap_cost']['options']]==[7,4,-2]
    assert not action.get('crew_cost')


def test_destroy_is_replaced_repeatedly_even_when_already_tapped():
    engine,source,creatures=board()
    for _ in range(2):
        source.damage_marked=3;engine.rules.destroy(source)
        assert source.zone==Zone.BATTLEFIELD and source.tapped and source.damage_marked==0
        assert len(source.replacement_effects)==1


def test_lethal_damage_regenerates_and_removes_combat_relationships():
    engine,source,creatures=board();attacker=card(engine,'Colossal Dreadmaw',player='p2')
    attacker.attacking=True;attacker.blocked_by=[source.instance_id];attacker.is_blocked=True
    source.blocking=attacker.instance_id
    engine.rules.deal_damage(source,6,source=attacker,combat=True);engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD and source.tapped and source.damage_marked==0
    assert source.blocking is None and attacker.blocked_by==[] and attacker.is_blocked


def test_regeneration_fires_only_genuine_tap_transition():
    engine,source,creatures=board();engine.rules.destroy(source);engine.rules.destroy(source)
    events=[e for e in engine.state.events_this_turn() if e.type=='TAPPED' and e.get('instance_id')==source.instance_id]
    assert len(events)==1


@pytest.mark.parametrize('mode',['cannot_regenerate','prohibition','sacrifice','zero_toughness','exile'])
def test_nonregenerable_destruction_or_other_zone_change_is_not_prevented(mode):
    engine,source,creatures=board()
    if mode=='cannot_regenerate':engine.rules.destroy(source,can_be_regenerated=False)
    elif mode=='prohibition':source.temp_cant_be_regenerated=True;engine.rules.destroy(source)
    elif mode=='sacrifice':engine.rules.sacrifice(engine.state.players[0])
    elif mode=='zero_toughness':source.add_counters('-1/-1',5);engine.recompute_continuous_effects();engine.resolve_until_stable()
    else:engine.rules.exile(source)
    assert source.zone==(Zone.EXILE if mode=='exile' else Zone.GRAVEYARD)


def test_countered_pump_does_not_untap_paid_creatures():
    engine,source,creatures=board(6,4);activate(engine,source,creatures)
    engine.rules.counter_ability(engine.state.stack[-1]);engine.resolve_until_stable()
    assert source.power==5 and all(obj.tapped for obj in creatures)


def test_repeated_activations_stack_until_cleanup():
    engine,source,creatures=board(6,4);activate(engine,source,creatures);engine.resolve_until_stable()
    for obj in creatures:obj.tapped=False
    activate(engine,source,creatures);engine.resolve_until_stable()
    assert source.power==source.toughness==45


def test_old_pump_does_not_affect_returned_troll():
    engine,source,creatures=board(6,4);activate(engine,source,creatures)
    engine.rules.put_into_graveyard(source);engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable();assert source.power==5


def test_cloned_replacement_regenerates_only_the_restored_object():
    engine,source,creatures=board();restored=GameEngine(engine.state.clone())
    clone=restored.state.find_object(source.instance_id);restored.rules.destroy(clone)
    assert clone.tapped and clone.zone==Zone.BATTLEFIELD and not source.tapped


def test_pending_pump_survives_clone_without_paying_again():
    engine,source,creatures=board(6,4);activate(engine,source,creatures)
    restored=GameEngine(engine.state.clone());restored.resolve_until_stable()
    assert restored.state.find_object(source.instance_id).power==25 and source.power==5


def test_crew_and_saddle_power_bonuses_do_not_pay_this_cost():
    engine,source,creatures=board(9)
    creatures[0].temp_combat_restrictions.extend([
        {'kind':'crew_power_bonus','count':10},{'kind':'saddle_power_bonus','count':10}])
    assert engine._crew_power_of(creatures[0])==19
    assert engine._crew_power_of(creatures[0],False)==19
    with pytest.raises(ValueError):activate(engine,source,creatures)
    assert not creatures[0].tapped


def test_regeneration_removes_attacker_and_blockers_relationship():
    engine,source,creatures=board();blocker=card(engine,'Grizzly Bears',player='p2')
    source.attacking=True;source.is_blocked=True;source.blocked_by=[blocker.instance_id]
    blocker.blocking=source.instance_id
    engine.rules.destroy(source)
    assert not source.attacking and source.blocked_by==[] and blocker.blocking is None
