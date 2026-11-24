"""Võx grants two independently consumed next-spell slots per resolution."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.events import EventType,GameEvent
from tests.support.deck_batch import card, filler, game, enter
from tests.support.star_trek import advance_to


def board(players=3):
    engine=game(players=players,library=30); advance_to(engine,'main1')
    source=card(engine,'Võx, Child of the Collective'); enter(engine,source)
    return engine,source


def spell(engine,name='Artifact creature',kind='Artifact Creature — Construct',cost='{5}',player='p1'):
    creature='Creature' in kind
    return filler(engine,name,type_line=kind,player=player,mv=5,mana_cost_string=cost,
                  power=2 if creature else None,toughness=2 if creature else None,zone=Zone.HAND)


def effective(engine,obj,player='p1'):
    return engine.effective_cast_cost(engine.state.player_by_id(player),obj).render()


def cast_exact(engine,obj,pool,player='p1'):
    actor=engine.state.player_by_id(player); actor.mana_pool.empty(); actor.mana_pool.add_many(pool)
    engine.cast_spell(actor,obj); engine.resolve_until_stable()


def test_fresh_specs_and_entry_grants_both_slots():
    engine,source=board(); a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==2
    assert engine.state.next_undaunted_grants==[{'player_id':'p1','turn':1,'artifact_creature':True,'spacecraft':True}]


@pytest.mark.parametrize('players,cost',[(2,'{4}'),(3,'{3}'),(4,'{2}')])
def test_undaunted_discount_counts_current_opponents(players,cost):
    engine,source=board(players); obj=spell(engine)
    assert effective(engine,obj)==cost


def test_artifact_creature_and_spacecraft_slots_are_consumed_independently():
    engine,source=board(); creature=spell(engine)
    ship=spell(engine,'Ship','Artifact — Spacecraft'); second=spell(engine,'Second artifact creature')
    cast_exact(engine,creature,{'C':3})
    assert effective(engine,second)=='{5}' and effective(engine,ship)=='{3}'
    cast_exact(engine,ship,{'C':3})
    assert not engine.state.next_undaunted_grants


def test_both_type_spell_uses_both_slots_but_receives_one_instance_per_effect():
    engine,source=board(); both=spell(engine,'Both','Artifact Creature — Spacecraft')
    assert effective(engine,both)=='{3}'
    cast_exact(engine,both,{'C':3}); assert not engine.state.next_undaunted_grants


def test_multiple_resolutions_stack_undaunted_instances_on_next_matching_spell():
    engine,source=board(); engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield'); engine.resolve_until_stable()
    obj=spell(engine); assert effective(engine,obj)=='{1}'
    cast_exact(engine,obj,{'C':1})
    assert all(not g['artifact_creature'] and g['spacecraft'] for g in engine.state.next_undaunted_grants)


def test_colored_pips_are_not_reduced():
    engine,source=board(players=4); obj=spell(engine,cost='{1}{U}{U}')
    assert effective(engine,obj)=='{U}{U}'
    player=engine.state.players[0]; player.mana_pool.add('U',1)
    assert not engine.can_cast(player,obj)
    cast_exact(engine,obj,{'U':2})


def test_cost_queries_and_failed_cast_do_not_consume_next_spell():
    engine,source=board(); obj=spell(engine)
    for _ in range(3): assert effective(engine,obj)=='{3}'
    engine.state.players[0].mana_pool.add('C',2)
    with pytest.raises(ValueError): engine.cast_spell(engine.state.players[0],obj)
    assert engine.state.next_undaunted_grants[0]['artifact_creature']
    cast_exact(engine,obj,{'C':3})
    assert not engine.state.next_undaunted_grants[0]['artifact_creature']


@pytest.mark.parametrize('kind',['Creature — Human','Artifact','Enchantment'])
def test_nonmatching_spells_neither_receive_nor_consume_grants(kind):
    engine,source=board(); obj=spell(engine,kind=kind)
    assert effective(engine,obj)=='{5}'
    cast_exact(engine,obj,{'C':5})
    assert engine.state.next_undaunted_grants[0]['artifact_creature']
    assert engine.state.next_undaunted_grants[0]['spacecraft']


def test_countered_spell_still_consumes_matching_slot():
    engine,source=board(); obj=spell(engine); player=engine.state.players[0]
    player.mana_pool.add('C',3); engine.cast_spell(player,obj)
    engine.rules.counter_spell(obj); engine.resolve_until_stable()
    assert obj.zone==Zone.GRAVEYARD
    assert not engine.state.next_undaunted_grants[0]['artifact_creature']


def test_source_departure_does_not_end_grants():
    engine,source=board(); engine.rules.exile(source); obj=spell(engine)
    assert effective(engine,obj)=='{3}'


def test_cleanup_expires_unused_slots():
    engine,source=board(); advance_to(engine,'cleanup')
    assert not engine.state.next_undaunted_grants


def test_current_first_main_triggers_but_later_main_does_not():
    engine=game(players=3,library=30); source=card(engine,'Võx, Child of the Collective')
    advance_to(engine,'main1'); assert len(engine.state.next_undaunted_grants)==1
    advance_to(engine,'main2'); assert len(engine.state.next_undaunted_grants)==1


def test_first_actual_main_after_skipped_precombat_main_still_triggers():
    engine=game(players=3,library=30); source=card(engine,'Võx, Child of the Collective')
    for phase,step in engine._turn_steps:
        if phase.name=='precombat_main': phase.skipped=True
    advance_to(engine,'main2')
    assert engine.state.main_phases_this_turn==1 and len(engine.state.next_undaunted_grants)==1


def test_other_players_first_main_does_not_trigger_your_vox():
    engine,source=board(); advance_to(engine,'cleanup'); engine.advance_step(); advance_to(engine,'main1')
    assert engine.state.active_player.id=='p2' and not engine.state.next_undaunted_grants


def test_granted_controller_is_frozen_after_trigger_and_source_control_change():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,'Võx, Child of the Collective')
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,instance_id=source.instance_id,
                                    controller_id='p1',object_types=sorted(source.type_words)))
    engine.rules.put_triggers_on_stack(); source.controller_id='p2'; engine.recompute_continuous_effects()
    engine.resolve_until_stable()
    assert effective(engine,spell(engine))=='{3}'
    assert effective(engine,spell(engine,player='p2'),player='p2')=='{5}'


def test_clone_preserves_both_remaining_slots_and_independent_consumption():
    engine,source=board(); obj=spell(engine); clone=GameEngine(engine.state.clone())
    copied=clone.state.find_object(obj.instance_id); cast_exact(clone,copied,{'C':3})
    assert not clone.state.next_undaunted_grants[0]['artifact_creature']
    assert engine.state.next_undaunted_grants[0]['artifact_creature']


def test_commander_tax_is_part_of_total_cost_before_undaunted_reduction():
    engine,source=board(); obj=spell(engine,cost='{1}')
    player=engine.state.players[0]; player.remove_from_zone(obj,Zone.HAND); player.add_to_zone(obj,Zone.COMMAND)
    obj.is_commander=True; player.commander_casts[obj.instance_id]=1
    assert effective(engine,obj)=='{1}'
    cast_exact(engine,obj,{'C':1})


def test_departed_opponents_are_not_counted():
    engine,source=board(players=4); obj=spell(engine)
    assert effective(engine,obj)=='{2}'
    engine.state.players[3].has_lost=True
    assert effective(engine,obj)=='{3}'


def test_additional_kicker_mana_is_reduced_even_when_base_cost_has_no_generic():
    engine,source=board()
    obj=filler(engine,'Kicked construct',type_line='Artifact Creature — Construct',power=2,toughness=2,
               zone=Zone.HAND,oracle_text='Kicker {3}',keywords=['Kicker'],mana_cost_string='{0}')
    player=engine.state.players[0]
    assert engine.effective_cast_cost(player,obj,kicked=1).render()=='{1}'
    player.mana_pool.add('C',1); engine.cast_spell(player,obj,kicked=1); engine.resolve_until_stable()
    assert obj.zone==Zone.BATTLEFIELD


def test_undaunted_does_not_reduce_below_a_total_cost_floor():
    engine,source=board(); card(engine,'Trinisphere'); obj=spell(engine,cost='{3}')
    assert effective(engine,obj)=='{3}'
    cast_exact(engine,obj,{'C':3})
    assert not engine.state.next_undaunted_grants[0]['artifact_creature']
