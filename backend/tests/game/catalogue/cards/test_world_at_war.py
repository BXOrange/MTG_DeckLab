"""World at War adds phases after the second actual main and has exact Rebound timing."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def board():
    engine=game(players=2,library=40); advance_to(engine,'main1')
    attacker=filler(engine,'Attacker',power=2,toughness=2)
    idle=filler(engine,'Idle creature',power=2,toughness=2)
    spell=card(engine,'World at War',zone=Zone.HAND)
    return engine,spell,attacker,idle


def cast_war(engine,spell):
    player=engine.state.players[0]; player.mana_pool.add_many(RICH)
    engine.cast_spell(player,spell); engine.resolve_until_stable()


def attack(engine,attacker):
    advance_to(engine,'declare_attackers')
    engine.declare_attackers(engine.state.players[0],[{'attacker':attacker,'defender':engine.state.players[1]}])


def test_fresh_specs_bind_effect_and_native_rebound():
    engine,spell,attacker,idle=board(); a,b=specs_for(spell.card),specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(spell.spell_effects)==1 and spell.has_rebound


@pytest.mark.parametrize('cast_step',['main1','main2'])
def test_additional_combat_and_main_follow_second_main_before_end_step(cast_step):
    engine,spell,attacker,idle=board(); advance_to(engine,cast_step); cast_war(engine,spell)
    assert spell.zone==Zone.EXILE
    if cast_step=='main1':
        advance_to(engine,'begin_combat'); assert engine.state.main_phases_this_turn==1
        advance_to(engine,'main2')
    assert engine.state.main_phases_this_turn==2
    assert engine.advance_step()==('combat','begin_combat')
    advance_to(engine,'main2'); assert engine.state.main_phases_this_turn==3
    assert engine.advance_step()==('ending','end')


def test_untap_waits_for_beginning_of_added_combat_and_only_affects_attackers():
    engine,spell,attacker,idle=board(); cast_war(engine,spell)
    engine.rules.set_tapped(idle,True); attack(engine,attacker)
    advance_to(engine,'main2'); assert attacker.tapped and idle.tapped
    engine.advance_step()
    assert not attacker.tapped and idle.tapped


def test_untap_trigger_is_counterable_and_phase_still_occurs():
    engine,spell,attacker,idle=board(); attack(engine,attacker)
    advance_to(engine,'main2'); cast_war(engine,spell); engine.interactive_priority=True
    engine.advance_step()
    assert engine.state.current_step=='begin_combat' and attacker.tapped
    trigger=engine.state.stack[-1]
    engine.rules.counter_ability(trigger); engine.resolve_until_stable()
    assert attacker.tapped
    engine.interactive_priority=False; engine.advance_step()
    assert engine.state.current_step=='declare_attackers'


def test_control_change_does_not_exclude_a_creature_that_attacked():
    engine,spell,attacker,idle=board(); attack(engine,attacker)
    advance_to(engine,'main2'); attacker.controller_id='p2'; engine.recompute_continuous_effects()
    cast_war(engine,spell); engine.advance_step()
    assert not attacker.tapped and attacker.controller_id=='p2'


def test_blinked_creature_is_not_a_creature_that_attacked_this_turn():
    engine,spell,attacker,idle=board(); attack(engine,attacker)
    advance_to(engine,'main2'); engine.rules.exile(attacker)
    engine.rules.return_from_graveyard(attacker,'battlefield'); engine.rules.set_tapped(attacker,True)
    cast_war(engine,spell); engine.advance_step()
    assert attacker.tapped and not attacker.attacked_this_turn


def test_cast_during_third_main_does_not_add_more_phases():
    engine,spell,attacker,idle=board(); cast_war(engine,spell)
    advance_to(engine,'main2'); engine.advance_step(); advance_to(engine,'main2')
    assert engine.state.main_phases_this_turn==3
    second=card(engine,'World at War',zone=Zone.HAND); cast_war(engine,second)
    assert engine.advance_step()==('ending','end')


def test_multiple_resolutions_add_multiple_combats_each_with_its_own_untap():
    engine,spell,attacker,idle=board(); cast_war(engine,spell)
    second=card(engine,'World at War',zone=Zone.HAND); cast_war(engine,second)
    attack(engine,attacker); advance_to(engine,'main2'); engine.advance_step()
    assert not attacker.tapped
    engine.rules.set_tapped(attacker,True); advance_to(engine,'main2'); engine.advance_step()
    assert engine.state.current_step=='begin_combat' and not attacker.tapped
    advance_to(engine,'main2'); assert engine.state.main_phases_this_turn==4
    assert engine.advance_step()==('ending','end')


def test_inserted_main_phase_counts_as_second_before_normal_postcombat_main():
    engine,spell,attacker,idle=board(); cast_war(engine,spell)
    engine.insert_additional_combat_phase(main_phase_too=True,after_current_phase=True)
    engine.advance_step(); advance_to(engine,'main2')
    assert engine.state.main_phases_this_turn==2
    assert engine.advance_step()==('combat','begin_combat')
    advance_to(engine,'main2'); assert engine.state.main_phases_this_turn==3
    assert engine.advance_step()==('combat','begin_combat')  # the original combat remains later


def test_pending_phase_request_and_inserted_delayed_trigger_survive_cloning():
    engine,spell,attacker,idle=board(); cast_war(engine,spell); attack(engine,attacker)
    clone=GameEngine(engine.state.clone()); clone.resume_at(engine.step_cursor); advance_to(clone,'main2')
    clone.interactive_priority=True; clone.advance_step()
    assert clone.state.main_phases_this_turn==2
    assert clone.state.find_object(attacker.instance_id).tapped
    clone=GameEngine(clone.state.clone()); clone.resolve_until_stable()
    assert not clone.state.find_object(attacker.instance_id).tapped and attacker.tapped


def next_own_upkeep(engine):
    # Finish this turn and the opponent's turn; rebound only fires for p1.
    advance_to(engine,'cleanup'); engine.advance_step(); advance_to(engine,'upkeep')
    assert engine.state.active_player.id=='p2' and engine.state.pending_choice is None
    advance_to(engine,'cleanup'); engine.advance_step(); advance_to(engine,'upkeep')
    assert engine.state.active_player.id=='p1'


def test_rebound_offers_free_cast_during_next_own_upkeep_then_goes_to_graveyard():
    engine,spell,attacker,idle=board(); cast_war(engine,spell); next_own_upkeep(engine)
    assert engine.state.pending_choice['kind']=='play_during_resolution'
    player=engine.state.players[0]; player.mana_pool.empty()
    engine.play_resolution_card(player,spell); engine.resolve_until_stable()
    assert spell.zone==Zone.GRAVEYARD and player.mana_pool.total()==0
    advance_to(engine,'main2'); assert engine.advance_step()==('combat','begin_combat')


def test_declining_rebound_does_not_leave_a_free_cast_permission_for_later():
    engine,spell,attacker,idle=board(); cast_war(engine,spell); next_own_upkeep(engine)
    engine.resolve_pending_choice('decline'); advance_to(engine,'main1')
    assert spell.zone==Zone.EXILE and not engine.state.free_cast_instance_ids
    assert not engine.can_cast(engine.state.players[0],spell)


def test_rebound_does_not_follow_a_new_exile_visit():
    engine,spell,attacker,idle=board(); cast_war(engine,spell)
    engine.rules.return_to_hand(spell); engine.rules.exile(spell)
    next_own_upkeep(engine)
    assert engine.state.pending_choice is None and not engine.state.free_cast_instance_ids


def test_spell_cast_outside_hand_does_not_rebound():
    engine,spell,attacker,idle=board(); engine.rules.exile(spell)
    engine.rules._request_resolution_play(engine.state.players[0],[spell],free=True,only_spells=True)
    engine.play_resolution_card(engine.state.players[0],spell); engine.resolve_until_stable()
    assert spell.zone==Zone.GRAVEYARD
    assert not any('World at War' in trigger.description for trigger in engine.state.delayed_triggers)


def test_countered_spell_adds_no_phases_and_does_not_rebound():
    engine,spell,attacker,idle=board(); player=engine.state.players[0]; player.mana_pool.add_many(RICH)
    engine.cast_spell(player,spell); engine.rules.counter_spell(spell); engine.resolve_until_stable()
    assert spell.zone==Zone.GRAVEYARD and not engine.state.pending_extra_combats
    advance_to(engine,'main2'); assert engine.advance_step()==('ending','end')


def test_request_expires_if_the_turn_never_has_a_second_main_phase():
    engine,spell,attacker,idle=board(); cast_war(engine,spell)
    for phase,step in engine._turn_steps:
        if phase.name=='postcombat_main': phase.skipped=True
    advance_to(engine,'end')
    assert engine.state.main_phases_this_turn==1
    assert len(engine.state.pending_extra_combats)==1
    advance_to(engine,'cleanup'); engine.advance_step()
    assert engine.state.main_phases_this_turn==0 and not engine.state.pending_extra_combats
    advance_to(engine,'main2'); assert engine.advance_step()==('ending','end')


def test_cloned_rebound_choice_casts_only_in_cloned_game():
    engine,spell,attacker,idle=board(); cast_war(engine,spell); next_own_upkeep(engine)
    clone=GameEngine(engine.state.clone()); copied=clone.state.find_object(spell.instance_id)
    clone.play_resolution_card(clone.state.players[0],copied); clone.resolve_until_stable()
    assert copied.zone==Zone.GRAVEYARD and clone.state.pending_extra_combats
    assert spell.zone==Zone.EXILE and engine.state.pending_choice is not None
