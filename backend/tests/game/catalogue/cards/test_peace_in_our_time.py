"""Peace in Our Time ties the active player's draw to a turn-long attack prohibition."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.events import EventType,GameEvent
from tests.support.deck_batch import card, filler, game, step
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    peace=card(engine,'Peace in Our Time')
    creatures={actor:filler(engine,'Creature '+actor,player=actor,power=2,toughness=2)
               for actor in ['p1','p2','p3']}
    return engine,peace,creatures


def offer(engine,actor='p2'):
    engine.state.active_player_index=int(actor[-1])-1
    engine.state.current_phase='combat'
    step(engine,'begin_combat',player=actor)
    assert engine.state.pending_choice['player_id']==actor


def test_fresh_specs_and_binding():
    engine,peace,creatures=board()
    a,b=specs_for(peace.card),specs_for(peace.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(peace.triggered_abilities)==2


@pytest.mark.parametrize('actor',['p1','p2','p3'])
def test_active_player_accepts_draw_and_cannot_attack_any_opponent(actor):
    engine,peace,creatures=board()
    player=engine.state.player_by_id(actor); before=len(player.hand)
    offer(engine,actor); engine.resolve_pending_choice('yes')
    assert len(player.hand)==before+1 and peace.counters.get('peace')==1
    engine.state.current_step='declare_attackers'
    for target in engine.state.players:
        if target.id!=actor:
            assert not engine._can_attack(player,creatures[actor],target)
            with pytest.raises(ValueError):
                engine.declare_attackers(player,[{'attacker':creatures[actor],'defender':target}])
    assert not creatures[actor].tapped


def test_declining_draw_does_not_add_counter_or_prevent_attack():
    engine,peace,creatures=board(); player=engine.state.player_by_id('p2'); before=len(player.hand)
    offer(engine); engine.resolve_pending_choice('decline')
    assert len(player.hand)==before and not peace.counters
    engine.state.current_step='declare_attackers'
    engine.declare_attackers(player,[{'attacker':creatures['p2'],'defender':engine.state.player_by_id('p1')}])
    assert creatures['p2'].tapped


def test_later_creatures_also_cannot_attack():
    engine,peace,creatures=board(); offer(engine); engine.resolve_pending_choice('yes')
    late=filler(engine,'Later',player='p2',power=3,toughness=3)
    assert not engine._can_attack(engine.state.player_by_id('p2'),late,engine.state.player_by_id('p3'))


def test_source_departure_does_not_remove_player_attack_prohibition():
    engine,peace,creatures=board(); offer(engine)
    engine.rules.exile(peace); engine.resolve_pending_choice('yes')
    assert 'p2' in engine.state.players_cant_attack_this_turn and peace.zone==Zone.EXILE
    assert not peace.counters


def test_cleanup_expires_player_attack_prohibition():
    engine,peace,creatures=board(); offer(engine,'p1'); engine.resolve_pending_choice('yes')
    advance_to(engine,'cleanup')
    assert not engine.state.players_cant_attack_this_turn


def test_clone_preserves_pending_draw_choice_and_prohibition():
    engine,peace,creatures=board(); offer(engine)
    clone=GameEngine(engine.state.clone()); clone.resolve_pending_choice('yes')
    assert 'p2' in clone.state.players_cant_attack_this_turn
    assert clone.state.find_object(peace.instance_id).counters.get('peace')==1
    assert not engine.state.players_cant_attack_this_turn


@pytest.mark.parametrize('count,actor,wins',[(11,'p1',False),(12,'p1',True),(12,'p2',False)])
def test_win_requires_twelve_counters_on_your_upkeep(count,actor,wins):
    engine,peace,creatures=board(); engine.rules.add_counters(peace,count,'peace')
    engine.state.active_player_index=int(actor[-1])-1
    step(engine,'upkeep',player=actor)
    assert (engine.state.winner_id=='p1')==wins


def test_win_condition_is_rechecked_at_resolution():
    engine,peace,creatures=board(); engine.rules.add_counters(peace,12,'peace')
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep',player_id='p1',controller_id='p1'))
    engine.rules.put_triggers_on_stack(); engine.rules.add_counters(peace,-1,'peace')
    engine.resolve_until_stable()
    assert engine.state.winner_id is None


def test_replaced_draw_still_applies_rider_after_dredge_choice():
    engine,peace,creatures=board()
    dredger=card(engine,'Golgari Brownscale',player='p2',zone=Zone.GRAVEYARD)
    offer(engine); engine.resolve_pending_choice('yes')
    assert engine.state.pending_choice['kind']=='dredge'
    assert not peace.counters and not engine.state.players_cant_attack_this_turn
    choice=engine.state.pending_choice
    option=next(o for o in choice['options'] if o['id']!='decline')
    engine.resolve_pending_choice(str(option['id']))
    assert dredger.zone==Zone.HAND and peace.counters.get('peace')==1
    assert 'p2' in engine.state.players_cant_attack_this_turn


def test_prevented_draw_does_not_add_counter_or_attack_prohibition():
    engine,peace,creatures=board()
    card(engine,'Narset, Parter of Veils')
    engine.rules.draw(engine.state.player_by_id('p2'),1)
    offer(engine); engine.resolve_pending_choice('yes')
    assert not peace.counters and not engine.state.players_cant_attack_this_turn


def test_source_control_change_does_not_change_winner_of_existing_trigger():
    engine,peace,creatures=board(); engine.rules.add_counters(peace,12,'peace')
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep',player_id='p1',controller_id='p1'))
    engine.rules.put_triggers_on_stack()
    peace.controller_id='p2'; engine.recompute_continuous_effects()
    engine.resolve_until_stable()
    assert engine.state.winner_id=='p1'


def test_win_trigger_uses_last_known_counters_after_source_leaves():
    engine,peace,creatures=board(); engine.rules.add_counters(peace,12,'peace')
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep',player_id='p1',controller_id='p1'))
    engine.rules.put_triggers_on_stack(); engine.rules.exile(peace)
    engine.resolve_until_stable()
    assert engine.state.winner_id=='p1'
