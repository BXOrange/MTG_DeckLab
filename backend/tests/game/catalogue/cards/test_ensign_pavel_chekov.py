"""Chekov exiles every opposing pool before choosing one land from each."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.events import EventType,GameEvent
from tests.support.deck_batch import card, game, cast, enter
from tests.support.star_trek import advance_to


def board(lands=('Forest','Island','Mountain'),p2=('Plains','Swamp','Lightning Bolt'),
          p3=('Island','Mountain','Sol Ring')):
    engine=game(players=3,library=30); advance_to(engine,'main1')
    for name in lands: card(engine,name)
    pools={}
    for player,names in [('p2',p2),('p3',p3)]:
        pools[player]=[card(engine,name,player=player,zone=Zone.LIBRARY) for name in reversed(names)]
        pools[player].reverse()
    source=card(engine,'Ensign Pavel Chekov')
    return engine,source,pools


def offered(engine):
    return {o.get('instance_id') for o in engine.state.pending_choice['options'] if 'instance_id' in o}


def choose_both(engine,pools):
    engine.resolve_pending_choice(str(pools['p2'][0].instance_id))
    engine.resolve_pending_choice(str(pools['p3'][0].instance_id))


def test_fresh_specs_binding_and_untargeted_trigger():
    engine,source,pools=board(); a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==1 and not source.triggered_abilities[0].effects[0].target_specs


def test_all_opponents_exile_before_first_choice_and_each_pool_offers_only_its_lands():
    engine,source,pools=board(); own_library=list(engine.state.players[0].library)
    enter(engine,source)
    assert all(obj.zone==Zone.EXILE for pool in pools.values() for obj in pool)
    assert engine.state.players[0].library==own_library
    assert offered(engine)=={o.instance_id for o in pools['p2'][:2]}
    assert engine.state.pending_choice['player_id']=='p1'
    engine.resolve_pending_choice(str(pools['p2'][0].instance_id))
    assert offered(engine)=={o.instance_id for o in pools['p3'][:2]}
    engine.resolve_pending_choice(str(pools['p3'][0].instance_id))
    assert engine.state.pending_choice is None


def test_only_chosen_lands_get_standing_play_permissions():
    engine,source,pools=board(); enter(engine,source); choose_both(engine,pools)
    selected={pools['p2'][0].instance_id,pools['p3'][0].instance_id}
    assert set(engine.state.temp_play_permissions)==selected
    assert engine.state.temp_play_permission_standing==selected
    assert all(holder=='p1' for holder in engine.state.temp_play_permission_player.values())
    assert all(obj.zone==Zone.EXILE for pool in pools.values() for obj in pool)


def test_land_choice_is_mandatory_and_cannot_choose_another_opponents_card():
    engine,source,pools=board(); enter(engine,source)
    for answer in ['decline',str(pools['p3'][0].instance_id),str(pools['p2'][2].instance_id)]:
        with pytest.raises(ValueError): engine.resolve_pending_choice(answer)
        assert offered(engine)=={o.instance_id for o in pools['p2'][:2]}
    choose_both(engine,pools)


def test_single_land_per_pool_is_chosen_automatically():
    engine,source,pools=board(p2=('Plains','Sol Ring','Lightning Bolt'),p3=('Island','Opt','Sol Ring'))
    enter(engine,source)
    assert engine.state.pending_choice is None
    assert set(engine.state.temp_play_permissions)=={pools['p2'][0].instance_id,pools['p3'][0].instance_id}


def test_no_land_in_one_pool_does_not_prevent_choice_from_other_pool():
    engine,source,pools=board(p2=('Sol Ring','Opt','Lightning Bolt'))
    enter(engine,source)
    assert offered(engine)=={o.instance_id for o in pools['p3'][:2]}
    engine.resolve_pending_choice(str(pools['p3'][0].instance_id))
    assert set(engine.state.temp_play_permissions)=={pools['p3'][0].instance_id}


def test_empty_libraries_do_not_lose_and_need_no_choice():
    engine,source,pools=board()
    for player in engine.state.players[1:]: player.library.clear()
    enter(engine,source)
    assert engine.state.pending_choice is None and not engine.state.temp_play_permissions
    assert not any(player.has_lost for player in engine.state.players)


@pytest.mark.parametrize('lands,expected',[((),0),(('Forest','Forest'),1),(('Forest','Island','Forest'),2)])
def test_x_counts_differently_named_lands_once_for_all_opponents(lands,expected):
    engine,source,pools=board(lands=lands); enter(engine,source)
    for pool in pools.values():
        assert sum(obj.zone==Zone.EXILE for obj in pool)==expected
    if expected==0:
        assert engine.state.pending_choice is None


def test_land_count_is_measured_at_resolution_and_retains_original_controller():
    engine,source,pools=board(lands=('Forest','Island'))
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,instance_id=source.instance_id,
        controller_id='p1',object_types=sorted(source.type_words)))
    engine.rules.put_triggers_on_stack(); card(engine,'Mountain'); source.controller_id='p2'
    engine.recompute_continuous_effects(); engine.resolve_until_stable()
    assert all(obj.zone==Zone.EXILE for pool in pools.values() for obj in pool)
    assert engine.state.pending_choice['player_id']=='p1'; choose_both(engine,pools)
    assert all(holder=='p1' for holder in engine.state.temp_play_permission_player.values())


def test_normal_land_play_limits_apply_and_owners_do_not_get_permissions():
    engine,source,pools=board(); enter(engine,source); choose_both(engine,pools)
    player=engine.state.players[0]; first=pools['p2'][0]; second=pools['p3'][0]
    assert engine.can_play_land(player,first)
    engine.play_land(player,first)
    assert first.zone==Zone.BATTLEFIELD and first.controller_id=='p1' and first.owner_id=='p2'
    assert not engine.can_play_land(player,second)
    engine.state.active_player_index=2
    assert not engine.can_play_land(engine.state.players[2],second)


def test_permissions_survive_source_departure_and_cleanup():
    engine,source,pools=board(); enter(engine,source); choose_both(engine,pools)
    engine.rules.exile(source)
    for _ in range(3):
        advance_to(engine,'cleanup'); engine.advance_step(); advance_to(engine,'main1')
    player=engine.state.players[0]
    assert engine.can_play_land(player,pools['p2'][0])
    assert engine.can_play_land(player,pools['p3'][0])


def test_leaving_and_reentering_exile_does_not_restore_permission():
    engine,source,pools=board(); enter(engine,source); choose_both(engine,pools)
    chosen=pools['p2'][0]
    engine.rules.return_to_hand(chosen); engine.rules.exile(chosen)
    assert not engine._has_temp_play_permission(chosen,engine.state.players[0])
    assert not engine.can_play_land(engine.state.players[0],chosen)


def test_source_departure_before_trigger_resolution_still_exiles_and_chooses():
    engine,source,pools=board()
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,instance_id=source.instance_id,
        controller_id='p1',object_types=sorted(source.type_words)))
    engine.rules.put_triggers_on_stack(); engine.rules.exile(source); engine.resolve_until_stable()
    choose_both(engine,pools)
    assert engine._has_temp_play_permission(pools['p2'][0],engine.state.players[0])


def test_clone_preserves_current_choice_and_remaining_opponents_pool():
    engine,source,pools=board(); enter(engine,source)
    clone=GameEngine(engine.state.clone())
    clone.resolve_pending_choice(str(pools['p2'][1].instance_id))
    assert offered(clone)=={o.instance_id for o in pools['p3'][:2]}
    clone=GameEngine(clone.state.clone()); clone.resolve_pending_choice(str(pools['p3'][0].instance_id))
    assert set(clone.state.temp_play_permissions)=={pools['p2'][1].instance_id,pools['p3'][0].instance_id}
    assert not engine.state.temp_play_permissions and engine.state.pending_choice is not None


def test_unrelated_exiled_lands_are_not_offered():
    engine,source,pools=board(); unrelated=card(engine,'Wastes',player='p2',zone=Zone.EXILE)
    enter(engine,source)
    assert unrelated.instance_id not in offered(engine)
    choose_both(engine,pools)
    assert unrelated.instance_id not in engine.state.temp_play_permissions


def test_current_choice_rejects_a_new_exile_visit_of_the_same_card():
    engine,source,pools=board(); enter(engine,source); changed=pools['p2'][0]
    engine.rules.return_to_hand(changed); engine.rules.exile(changed)
    with pytest.raises(ValueError): engine.resolve_pending_choice(str(changed.instance_id))
    assert changed.instance_id not in engine.state.temp_play_permissions
    engine.resolve_pending_choice(str(pools['p2'][1].instance_id))
    engine.resolve_pending_choice(str(pools['p3'][0].instance_id))
    assert set(engine.state.temp_play_permissions)=={pools['p2'][1].instance_id,pools['p3'][0].instance_id}


def test_later_opponents_pool_also_excludes_changed_exile_visits():
    engine,source,pools=board(); enter(engine,source); changed=pools['p3'][0]
    engine.rules.return_to_hand(changed); engine.rules.exile(changed)
    engine.resolve_pending_choice(str(pools['p2'][0].instance_id))
    assert engine.state.pending_choice is None  # the other original land is the sole remaining choice
    assert set(engine.state.temp_play_permissions)=={pools['p2'][0].instance_id,pools['p3'][1].instance_id}


def test_real_cast_fires_the_entry_ability():
    engine,source,pools=board()
    engine.rules.return_to_hand(source); cast(engine,source)
    assert source.zone==Zone.BATTLEFIELD
    assert offered(engine)=={o.instance_id for o in pools['p2'][:2]}
