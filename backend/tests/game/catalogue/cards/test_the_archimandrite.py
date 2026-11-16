"""The Archimandrite measures upkeep hand size and buffs the current subtype union per life event."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType,GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,cast,filler,game


def board():
    engine=game(players=3,library=40);source=card(engine,'The Archimandrite')
    return engine,source


def upkeep(engine,player='p1',resolve=True):
    engine.state.active_player_index=next(i for i,p in enumerate(engine.state.players) if p.id==player)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep',player_id=player))
    engine.rules.put_triggers_on_stack()
    if resolve:engine.resolve_until_stable()


def helpers(engine):
    return [card(engine,name) for name in ('Persistent Petitioners','Etherium Sculptor','Monastery Swiftspear')]


def activate(engine,source,chosen=None):
    engine.activate_ability(engine.state.player_by_id(source.controller_id),source,0,
                           tap_choices=None if chosen is None else [obj.instance_id for obj in chosen])


def test_fresh_specs_bind_all_three_abilities():
    engine,source=board();a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.triggered_abilities)==2 and len(source.activated_abilities)==1


def test_actual_cast_then_mixed_type_cost_draws_on_resolution():
    engine=game(library=40);source=card(engine,'The Archimandrite',zone=Zone.HAND);cast(engine,source)
    chosen=helpers(engine);before=len(engine.state.players[0].hand)
    activate(engine,source,chosen)
    assert all(obj.tapped for obj in chosen) and len(engine.state.players[0].hand)==before
    engine.resolve_until_stable();assert len(engine.state.players[0].hand)==before+1


@pytest.mark.parametrize('size,gain',[(0,0),(3,0),(4,0),(5,1),(8,4)])
def test_upkeep_gains_hand_size_minus_four_without_losing_life(size,gain):
    engine,source=board();base=source.power
    for i in range(size):filler(engine,f'Hand {i}',type_line='Instant',zone=Zone.HAND)
    upkeep(engine)
    assert engine.state.players[0].life==20+gain and source.power==base+gain
    assert combat.has(source,'vigilance')==bool(gain)


def test_upkeep_uses_hand_size_at_resolution():
    engine,source=board();upkeep(engine,resolve=False)
    for i in range(7):filler(engine,f'Hand {i}',type_line='Instant',zone=Zone.HAND)
    engine.resolve_until_stable();assert engine.state.players[0].life==23


def test_opponents_upkeep_does_not_trigger():
    engine,source=board()
    for i in range(8):filler(engine,f'Hand {i}',type_line='Instant',zone=Zone.HAND)
    upkeep(engine,'p2');assert engine.state.players[0].life==20


def test_life_gain_buffs_each_matching_permanent_once_and_excludes_others():
    engine,source=board();chosen=helpers(engine)
    multi=filler(engine,'Multi',type_line='Creature — Advisor Artificer Monk',power=1,toughness=4)
    unrelated=card(engine,'Grizzly Bears');opposing=card(engine,'Monastery Swiftspear',player='p2')
    originals={obj.instance_id:(obj.power,obj.toughness) for obj in [source,*chosen,multi,unrelated,opposing]}
    engine.rules.gain_life(engine.state.players[0],3);engine.resolve_until_stable()
    for obj in [source,*chosen,multi]:
        power,toughness=originals[obj.instance_id]
        assert obj.power==power+3 and obj.toughness==toughness and combat.has(obj,'vigilance')
    assert unrelated.power==2 and not combat.has(unrelated,'vigilance')
    assert opposing.power==1 and not combat.has(opposing,'vigilance')


def test_separate_life_events_stack_with_their_own_amounts_until_cleanup():
    engine,source=board();base=source.power
    engine.rules.gain_life(engine.state.players[0],2);engine.rules.gain_life(engine.state.players[0],5)
    engine.resolve_until_stable();assert source.power==base+7
    engine._step_cleanup();engine.recompute_continuous_effects()
    assert source.power==base and not combat.has(source,'vigilance')


def test_opponents_life_gain_does_not_buff_your_group():
    engine,source=board();base=source.power
    engine.rules.gain_life(engine.state.players[1],4);engine.resolve_until_stable()
    assert source.power==base and not combat.has(source,'vigilance')


def test_recipients_are_chosen_at_resolution_and_newcomers_afterward_are_not_buffed():
    engine,source=board();engine.rules.gain_life(engine.state.players[0],3)
    before=card(engine,'Monastery Swiftspear');engine.resolve_until_stable()
    after=card(engine,'Monastery Swiftspear')
    assert before.power==4 and combat.has(before,'vigilance')
    assert after.power==1 and not combat.has(after,'vigilance')


def test_source_control_change_does_not_redirect_queued_life_trigger():
    engine,source=board();own=card(engine,'Monastery Swiftspear')
    other=card(engine,'Monastery Swiftspear',player='p2')
    engine.rules.gain_life(engine.state.players[0],3);source.controller_id='p2'
    engine.recompute_continuous_effects();engine.resolve_until_stable()
    assert own.power==4 and other.power==1 and source.power==0


def test_departed_source_does_not_stop_queued_group_buff():
    engine,source=board();own=card(engine,'Monastery Swiftspear')
    engine.rules.gain_life(engine.state.players[0],3);engine.rules.exile(source);engine.resolve_until_stable()
    assert own.power==4 and combat.has(own,'vigilance')


def test_source_can_be_one_of_three_cost_permanents_even_with_summoning_sickness():
    engine,source=board();chosen=helpers(engine)[:2]
    for obj in [source,*chosen]:obj.summoning_sick=True
    activate(engine,source,[source,*chosen]);engine.resolve_until_stable()
    assert source.tapped and len(engine.state.players[0].hand)==1


def test_multiple_matching_types_do_not_let_one_permanent_pay_twice():
    engine,source=board();multi=filler(engine,'Multi',type_line='Creature — Advisor Artificer Monk',power=1,toughness=4)
    with pytest.raises(ValueError):activate(engine,source,[source,multi,multi])
    assert not source.tapped and not multi.tapped


def test_nonmatching_tapped_or_opposing_permanent_cannot_pay():
    engine,source=board();chosen=helpers(engine);bear=card(engine,'Grizzly Bears')
    with pytest.raises(ValueError):activate(engine,source,[chosen[0],chosen[1],bear])
    chosen[2].tapped=True
    with pytest.raises(ValueError):activate(engine,source,chosen)
    chosen[2].tapped=False;chosen[2].controller_id='p2'
    with pytest.raises(ValueError):activate(engine,source,chosen)
    assert not chosen[0].tapped and not chosen[1].tapped


def test_legal_cost_pool_is_union_not_three_separate_type_requirements():
    engine,source=board();chosen=helpers(engine);card(engine,'Grizzly Bears')
    action=next(a for a in engine.legal_actions(engine.state.players[0]) if a['type']=='activate_ability' and a['instance_id']==source.instance_id)
    assert action['tap_cost']['count']==3
    assert {o['instance_id'] for o in action['tap_cost']['options']}=={source.instance_id,*(obj.instance_id for obj in chosen)}


def test_countered_draw_leaves_cost_permanents_tapped():
    engine,source=board();chosen=helpers(engine);activate(engine,source,chosen)
    engine.rules.counter_ability(engine.state.stack[-1]);engine.resolve_until_stable()
    assert all(obj.tapped for obj in chosen) and not engine.state.players[0].hand


def test_queued_life_trigger_survives_clone():
    engine,source=board();engine.rules.gain_life(engine.state.players[0],3)
    restored=GameEngine(engine.state.clone());restored.resolve_until_stable()
    assert restored.state.find_object(source.instance_id).power==3 and source.power==0


def test_three_of_the_same_allowed_type_are_sufficient():
    engine,source=board()
    chosen=[card(engine,'Persistent Petitioners') for _ in range(3)]
    activate(engine,source,chosen);engine.resolve_until_stable()
    assert all(obj.tapped for obj in chosen) and len(engine.state.players[0].hand)==1


def test_cost_does_not_add_an_unprinted_creature_requirement():
    engine,source=board()
    a=filler(engine,'Kindred A',type_line='Kindred Enchantment — Advisor')
    b=filler(engine,'Kindred B',type_line='Kindred Artifact — Artificer')
    activate(engine,source,[source,a,b]);engine.resolve_until_stable()
    assert source.tapped and a.tapped and b.tapped and len(engine.state.players[0].hand)==1
