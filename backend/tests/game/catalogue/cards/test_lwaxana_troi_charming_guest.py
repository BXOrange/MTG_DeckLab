"""Lwaxana doubles the chosen object's triggers only while continuously tapped."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    lwaxana=card(engine,'Lwaxana Troi, Charming Guest')
    chosen=filler(engine,'Chosen',power=2,toughness=2,oracle_text='Whenever this creature becomes tapped, draw a card.')
    other=filler(engine,'Other',power=2,toughness=2,oracle_text='Whenever this creature becomes tapped, draw a card.')
    player=engine.state.player_by_id('p1'); player.mana_pool.add_many(RICH)
    return engine,lwaxana,chosen,other,player


def activate(engine,lwaxana,chosen,player,resolve=True):
    engine.activate_ability(player,lwaxana,0,targets=[chosen])
    if resolve:
        engine.resolve_until_stable()


def tap_and_count(engine,obj,player):
    before=len(player.hand)
    engine.rules.set_tapped(obj,True); engine.resolve_until_stable()
    return len(player.hand)-before


def test_fresh_specs_and_binding():
    engine,lwaxana,chosen,other,player=board()
    a,b=specs_for(lwaxana.card),specs_for(lwaxana.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(lwaxana.activated_abilities)==1 and lwaxana.static_effects


def test_only_chosen_creatures_trigger_gets_an_additional_time():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player)
    assert lwaxana.tapped
    assert tap_and_count(engine,chosen,player)==2
    assert tap_and_count(engine,other,player)==1


def test_self_and_opponent_targets_are_rejected_before_costs():
    engine,lwaxana,chosen,other,player=board()
    enemy=filler(engine,'Enemy',player='p2',power=2,toughness=2)
    before=player.mana_pool.to_dict()
    for target in [lwaxana,enemy]:
        with pytest.raises(ValueError):
            activate(engine,lwaxana,target,player)
        assert not lwaxana.tapped and player.mana_pool.to_dict()==before


def test_untap_then_retap_does_not_revive_old_effect():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player)
    engine.rules.set_tapped(lwaxana,False); engine.rules.set_tapped(lwaxana,True)
    assert tap_and_count(engine,chosen,player)==1


def test_source_untapped_before_resolution_creates_no_doubler():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player,False)
    engine.rules.set_tapped(lwaxana,False); engine.resolve_until_stable()
    assert tap_and_count(engine,chosen,player)==1


def test_source_departure_ends_doubler():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player)
    engine.rules.exile(lwaxana); engine.recompute_continuous_effects()
    assert tap_and_count(engine,chosen,player)==1


def test_target_zone_visit_is_fixed():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player)
    engine.rules.exile(chosen); engine.rules.return_from_graveyard(chosen,'battlefield')
    engine.recompute_continuous_effects()
    assert tap_and_count(engine,chosen,player)==1


def test_control_change_of_chosen_creature_does_not_end_effect():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player)
    chosen.controller_id='p2'; engine.recompute_continuous_effects()
    assert tap_and_count(engine,chosen,engine.state.player_by_id('p2'))==2


def test_lwaxana_losing_abilities_does_not_end_resolved_effect():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player)
    aura=card(engine,'Darksteel Mutation'); aura.attached_to=lwaxana.instance_id
    engine.recompute_continuous_effects()
    assert tap_and_count(engine,chosen,player)==2


def test_clone_preserves_bound_doubler():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player)
    clone=GameEngine(engine.state.clone())
    assert tap_and_count(clone,clone.state.find_object(chosen.instance_id),clone.state.player_by_id('p1'))==2
    assert not chosen.tapped


def test_countered_activation_grants_no_doubler():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player,False)
    engine.rules.counter_ability(engine.state.stack[-1]); engine.resolve_until_stable()
    assert lwaxana.tapped and tap_and_count(engine,chosen,player)==1


def test_may_remain_tapped_through_own_untap_step():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player)
    engine.set_skip_untap(player,lwaxana,True)
    for _ in range(100):
        engine.advance_step(); engine.resolve_until_stable()
        if engine.state.active_player.id=='p1' and engine.state.current_step=='untap':
            break
    else:
        raise AssertionError('own untap step not reached')
    assert lwaxana.tapped and tap_and_count(engine,chosen,player)==2


def test_stun_counter_replacing_untap_keeps_doubler_active():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player)
    engine.rules.add_counters(lwaxana,1,'stun')
    engine.rules.set_tapped(lwaxana,False)
    assert lwaxana.tapped and not lwaxana.counters.get('stun',0)
    assert tap_and_count(engine,chosen,player)==2


def test_source_blink_then_retap_does_not_restore_old_doubler():
    engine,lwaxana,chosen,other,player=board(); activate(engine,lwaxana,chosen,player)
    engine.rules.exile(lwaxana); engine.rules.return_from_graveyard(lwaxana,'battlefield')
    engine.rules.set_tapped(lwaxana,True); engine.recompute_continuous_effects()
    assert tap_and_count(engine,chosen,player)==1
