"""Uhura casts at most one opposing instant/sorcery and bottoms the exact rest."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, activate
from tests.support.star_trek import advance_to


def board(names=('Lightning Bolt','Sol Ring','Forest'),lands=('Forest','Island','Mountain'),opponent='p2'):
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,'Lieutenant Nyota Uhura')
    for name in lands:
        land=card(engine,name); land.tapped=True
    top=[card(engine,name,player=opponent,zone=Zone.LIBRARY) for name in reversed(names)]
    top.reverse()
    return engine,source,top


def offer(engine,source,opponent='p2'):
    engine.state.players[0].mana_pool.add('C',4)
    activate(engine,source,targets=[engine.state.player_by_id(opponent)])


def test_fresh_specs_binding_and_printed_activation_cost():
    engine,source,top=board(); a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.activated_abilities)==1 and source.activated_abilities[0].cost.taps_self
    player=engine.state.players[0]; player.mana_pool.add('C',3)
    assert not engine.can_activate(player,source,source.activated_abilities[0])
    player.mana_pool.add('C',1); activate(engine,source,targets=[engine.state.players[1]])
    assert source.tapped and player.mana_pool.total()==0


@pytest.mark.parametrize('opponent',['p2','p3'])
def test_target_opponent_exiles_x_top_cards_and_only_instants_and_sorceries_are_castable(opponent):
    engine,source,top=board(opponent=opponent); offer(engine,source,opponent)
    assert all(obj.zone==Zone.EXILE and not obj.face_down_in_exile for obj in top)
    assert engine.state.pending_choice['kind']=='play_during_resolution'
    player=engine.state.players[0]
    assert engine.can_cast(player,top[0],targets=[engine.state.players[1]])
    assert not engine.can_cast(player,top[1]) and not engine.can_play_land(player,top[2])


def test_decline_returns_every_card_to_opponents_bottom_not_casters_library():
    engine,source,top=board(); own=list(engine.state.players[0].library)
    other=list(engine.state.players[1].library[:-3]); offer(engine,source)
    engine.resolve_pending_choice('decline')
    assert set(engine.state.players[1].library[:3])==set(top)
    assert engine.state.players[1].library[3:]==other
    assert engine.state.players[0].library==own and not engine.state.players[1].exile
    assert not engine.state.free_cast_instance_ids and not engine.state.resolution_play_choice


def test_cast_is_free_and_rest_returns_before_the_chosen_spell_resolves():
    engine,source,top=board(); offer(engine,source)
    player=engine.state.players[0]; player.mana_pool.empty(); opponent=engine.state.players[1]
    engine.play_resolution_card(player,top[0],targets=[engine.state.players[2]])
    assert top[0].zone==Zone.STACK and engine.state.players[2].life==20
    assert set(opponent.library[:2])==set(top[1:]) and not opponent.exile
    assert not engine.state.resolution_play_choice and not engine.state.free_cast_instance_ids
    engine.resolve_until_stable()
    assert engine.state.players[2].life==17 and player.mana_pool.total()==0
    assert top[0] in opponent.graveyard


def test_only_one_of_multiple_instants_or_sorceries_can_be_cast():
    engine,source,top=board(names=('Lightning Bolt','Shock','Sol Ring')); offer(engine,source)
    engine.play_resolution_card(engine.state.players[0],top[0],targets=[engine.state.players[2]])
    assert top[1].zone==Zone.LIBRARY and top[2].zone==Zone.LIBRARY
    assert not engine.can_cast(engine.state.players[0],top[1],targets=[engine.state.players[2]])


@pytest.mark.parametrize('names',[('Sol Ring','Forest','Mountain'),('Forest',)])
def test_no_legally_castable_spell_returns_cards_without_an_empty_choice(names):
    engine,source,top=board(names=names); offer(engine,source)
    assert engine.state.pending_choice is None and not engine.state.resolution_play_choice
    assert all(obj.zone==Zone.LIBRARY for obj in top)


@pytest.mark.parametrize('lands,expected',[((),0),(('Forest','Forest'),1),(('Forest','Island','Forest'),2)])
def test_x_counts_distinct_land_names(lands,expected):
    engine,source,top=board(lands=lands); offer(engine,source)
    if expected:
        assert sum(obj.zone==Zone.EXILE for obj in top)==expected
        engine.resolve_pending_choice('decline')
    else:
        assert engine.state.pending_choice is None and all(obj.zone==Zone.LIBRARY for obj in top)


def test_land_count_is_measured_when_ability_resolves():
    engine,source,top=board(lands=('Forest','Island')); player=engine.state.players[0]
    player.mana_pool.add('C',4); engine.activate_ability(player,source,0,targets=[engine.state.players[1]])
    card(engine,'Mountain'); engine.resolve_until_stable()
    assert all(obj.zone==Zone.EXILE for obj in top)


def test_short_library_exiles_only_available_cards():
    engine,source,top=board(names=('Lightning Bolt',)); engine.state.players[1].library[:]=top
    offer(engine,source); engine.resolve_pending_choice('decline')
    assert engine.state.players[1].library==top and not engine.state.players[1].has_lost


def test_remaining_cards_are_randomized_as_one_group_without_shuffling_library(monkeypatch):
    engine,source,top=board(); seen=[]
    def shuffle(items):
        seen.append(list(items)); items.reverse()
    offer(engine,source); monkeypatch.setattr('random.shuffle',shuffle)
    engine.resolve_pending_choice('decline')
    assert len(seen)==1 and set(seen[0])==set(top)
    assert engine.state.players[1].library[:3]==top


def test_unrelated_exiled_cards_and_new_exile_visits_are_left_alone():
    engine,source,top=board(); unrelated=card(engine,'Short Sword',player='p2',zone=Zone.EXILE)
    offer(engine,source); changed=top[1]
    engine.rules.return_to_hand(changed); engine.rules.exile(changed)
    engine.resolve_pending_choice('decline')
    assert changed.zone==unrelated.zone==Zone.EXILE
    assert top[0].zone==top[2].zone==Zone.LIBRARY


@pytest.mark.parametrize('departure',['exile','control'])
def test_source_departure_or_control_change_does_not_change_count_or_casting_player(departure):
    engine,source,top=board(); player=engine.state.players[0]
    player.mana_pool.add('C',4); engine.activate_ability(player,source,0,targets=[engine.state.players[1]])
    if departure=='exile': engine.rules.exile(source)
    else: source.controller_id='p2'; engine.recompute_continuous_effects()
    engine.resolve_until_stable()
    assert all(obj.zone==Zone.EXILE for obj in top)
    assert engine.state.pending_choice['player_id']=='p1'
    engine.resolve_pending_choice('decline')
    assert set(engine.state.players[1].library[:3])==set(top)


def test_sorcery_can_be_cast_during_an_opponents_turn_from_this_resolution():
    engine,source,top=board(names=('Divination','Sol Ring','Forest'))
    engine.state.active_player_index=1; engine.state.current_step='upkeep'; engine.state.current_phase='beginning'
    player=engine.state.players[0]; player.mana_pool.add('C',4)
    engine.activate_ability(player,source,0,targets=[engine.state.players[1]]); engine.resolve_until_stable()
    before=len(player.hand); engine.play_resolution_card(player,top[0]); engine.resolve_until_stable()
    assert len(player.hand)==before+2 and top[0] in engine.state.players[1].graveyard


def test_clone_keeps_pending_cast_and_correct_bottom_owner():
    engine,source,top=board(); offer(engine,source)
    clone=GameEngine(engine.state.clone()); clone.resolve_pending_choice('decline')
    assert {obj.instance_id for obj in clone.state.players[1].library[:3]}=={obj.instance_id for obj in top}
    assert all(obj.zone==Zone.EXILE for obj in top)
    assert not clone.state.free_cast_instance_ids


def test_clone_can_cast_one_spell_and_bottom_the_rest_before_resolution():
    engine,source,top=board(); offer(engine,source)
    clone=GameEngine(engine.state.clone()); selected=clone.state.find_object(top[0].instance_id)
    clone.play_resolution_card(clone.state.players[0],selected,targets=[clone.state.players[2]])
    assert selected.zone==Zone.STACK
    assert {obj.instance_id for obj in clone.state.players[1].library[:2]}=={obj.instance_id for obj in top[1:]}
    clone.resolve_until_stable(); assert clone.state.players[2].life==17
    assert all(obj.zone==Zone.EXILE for obj in top)


def test_land_play_attempt_is_rejected_without_losing_the_cast_choice():
    engine,source,top=board(); offer(engine,source)
    with pytest.raises(ValueError): engine.play_resolution_card(engine.state.players[0],top[2])
    assert engine.state.pending_choice['kind']=='play_during_resolution'
    assert top[2].zone==Zone.EXILE


def test_countered_activation_spends_costs_but_never_exiles_cards():
    engine,source,top=board(); player=engine.state.players[0]
    player.mana_pool.add('C',4); engine.activate_ability(player,source,0,targets=[engine.state.players[1]])
    engine.rules.counter_ability(engine.state.stack[-1]); engine.resolve_until_stable()
    assert source.tapped and player.mana_pool.total()==0
    assert all(obj.zone==Zone.LIBRARY for obj in top) and engine.state.pending_choice is None


def test_free_cast_still_pays_additional_sacrifice_cost():
    engine,source,top=board(names=('Fling','Sol Ring','Forest')); offer(engine,source)
    engine.play_resolution_card(engine.state.players[0],top[0],targets=[engine.state.players[2]])
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD and engine.state.players[2].life==18
    assert set(engine.state.players[1].library[:2])==set(top[1:])
