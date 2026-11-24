"""Kal-if-fee tracks the exact two creatures that actually fought."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, enter
from tests.support.star_trek import advance_to


def board(power=2, toughness=5, opponent='p2'):
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,"T'Pring, Never Parted")
    own=filler(engine,'Own fighter',power=power,toughness=toughness)
    other=filler(engine,'Other fighter',player=opponent,power=power,toughness=toughness)
    return engine,source,own,other


def choose(engine,source,own,other):
    enter(engine,source)
    choice=engine.state.pending_choice
    assert source.instance_id not in [o.get('instance_id') for o in choice['options']]
    engine.resolve_pending_choice(str(own.instance_id))
    engine.resolve_pending_choice(str(other.instance_id))
    assert engine.state.pending_choice['kind']=='composite_optional'


def fight(engine,source,own,other):
    choose(engine,source,own,other); engine.resolve_pending_choice('yes')


def hand(engine,player='p1'):
    return len(engine.state.player_by_id(player).hand)


def test_fresh_specs_and_binding():
    engine,source,own,other=board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==1


@pytest.mark.parametrize('opponent',['p2','p3'])
def test_both_fighters_deal_noncombat_damage_and_each_later_death_draws(opponent):
    engine,source,own,other=board(opponent=opponent); before=hand(engine)
    fight(engine,source,own,other)
    assert own.damage_marked==2 and other.damage_marked==2
    engine.rules.destroy(own); engine.resolve_until_stable()
    assert hand(engine)==before+1
    engine.rules.destroy(other); engine.resolve_until_stable()
    assert hand(engine)==before+2


def test_lethal_fight_draws_for_both_creatures():
    engine,source,own,other=board(power=3,toughness=3); before=hand(engine)
    fight(engine,source,own,other)
    assert own.zone==other.zone==Zone.GRAVEYARD
    assert hand(engine)==before+2


def test_declining_fight_creates_no_damage_or_death_triggers():
    engine,source,own,other=board(); before=hand(engine)
    choose(engine,source,own,other); engine.resolve_pending_choice('decline')
    assert own.damage_marked==other.damage_marked==0
    assert not engine.state.turn_scoped_triggers
    engine.rules.destroy(own); engine.rules.destroy(other); engine.resolve_until_stable()
    assert hand(engine)==before


@pytest.mark.parametrize('which',[0,1])
def test_one_missing_fighter_prevents_fight_and_tracking(which):
    engine,source,own,other=board(); before=hand(engine)
    choose(engine,source,own,other)
    engine.rules.exile([own,other][which]); engine.resolve_pending_choice('yes')
    survivor=[other,own][which]
    assert survivor.damage_marked==0 and not engine.state.turn_scoped_triggers
    engine.rules.destroy(survivor); engine.resolve_until_stable()
    assert hand(engine)==before


def test_departed_source_does_not_remove_delayed_triggers():
    engine,source,own,other=board(); before=hand(engine)
    fight(engine,source,own,other); engine.rules.exile(source)
    engine.rules.destroy(other); engine.resolve_until_stable()
    assert hand(engine)==before+1


def test_control_changes_do_not_redirect_draw():
    engine,source,own,other=board(); before=hand(engine); p2_before=hand(engine,'p2')
    fight(engine,source,own,other)
    source.controller_id='p2'; own.controller_id='p3'
    engine.recompute_continuous_effects()
    engine.rules.destroy(own); engine.resolve_until_stable()
    assert hand(engine)==before+1 and hand(engine,'p2')==p2_before


def test_trigger_controller_survives_source_control_change_before_resolution():
    engine,source,own,other=board(); before=hand(engine); p2_before=hand(engine,'p2')
    enter(engine,source); engine.resolve_pending_choice(str(own.instance_id))
    engine.rules.resolve_choice(str(other.instance_id))
    source.controller_id='p2'; engine.recompute_continuous_effects()
    engine.resolve_until_stable()
    assert engine.state.pending_choice['player_id']=='p1'
    engine.resolve_pending_choice('yes')
    engine.rules.destroy(other); engine.resolve_until_stable()
    assert own.damage_marked==2
    assert hand(engine)==before+1 and hand(engine,'p2')==p2_before


def test_blinked_fighter_is_a_new_object():
    engine,source,own,other=board(); before=hand(engine)
    fight(engine,source,own,other); engine.rules.exile(own)
    engine.rules.return_from_graveyard(own,'battlefield')
    engine.rules.destroy(own); engine.resolve_until_stable()
    assert hand(engine)==before


def test_unrelated_creatures_do_not_draw():
    engine,source,own,other=board(); before=hand(engine)
    fight(engine,source,own,other)
    unrelated=filler(engine,'Unrelated',player='p2',power=1,toughness=1)
    engine.rules.destroy(unrelated); engine.resolve_until_stable()
    assert hand(engine)==before


def test_next_turn_expires_tracking():
    engine,source,own,other=board(); fight(engine,source,own,other)
    advance_to(engine,'cleanup'); engine.advance_step(); before=hand(engine)
    assert not engine.state.turn_scoped_triggers
    engine.rules.destroy(own); engine.resolve_until_stable()
    assert hand(engine)==before


@pytest.mark.parametrize('which',[0,1])
def test_illegal_target_before_resolution_prevents_both_from_fighting(which):
    engine,source,own,other=board(); before=hand(engine)
    enter(engine,source); engine.resolve_pending_choice(str(own.instance_id))
    engine.rules.resolve_choice(str(other.instance_id))
    engine.rules.exile([own,other][which]); engine.resolve_until_stable()
    if engine.state.pending_choice:
        engine.resolve_pending_choice('yes')
    assert own.damage_marked==other.damage_marked==0
    assert not engine.state.turn_scoped_triggers and hand(engine)==before


def test_zero_power_creatures_still_fight_and_are_tracked():
    engine,source,own,other=board(power=0); before=hand(engine)
    fight(engine,source,own,other)
    assert own.damage_marked==other.damage_marked==0
    engine.rules.destroy(own); engine.rules.destroy(other); engine.resolve_until_stable()
    assert hand(engine)==before+2


def test_exile_is_not_death():
    engine,source,own,other=board(); before=hand(engine)
    fight(engine,source,own,other); engine.rules.exile(other); engine.resolve_until_stable()
    assert hand(engine)==before


def test_clone_preserves_pending_fight_and_delayed_triggers():
    engine,source,own,other=board(); choose(engine,source,own,other)
    clone=GameEngine(engine.state.clone()); before=hand(clone)
    clone.resolve_pending_choice('yes')
    cloned_other=clone.state.find_object(other.instance_id)
    assert cloned_other.damage_marked==2 and other.damage_marked==0
    clone=GameEngine(clone.state.clone())
    clone.rules.destroy(clone.state.find_object(other.instance_id)); clone.resolve_until_stable()
    assert hand(clone)==before+1 and hand(engine)==before
