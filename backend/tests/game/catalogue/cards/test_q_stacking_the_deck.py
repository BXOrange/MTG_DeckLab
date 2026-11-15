"""Q grants one exact exile visit a repeatable, paid card-copy activation."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.events import EventType,GameEvent
from tests.support.deck_batch import card, filler, game, enter
from tests.support.star_trek import advance_to


@pytest.fixture(autouse=True)
def fixed_shuffle(monkeypatch):
    monkeypatch.setattr('random.shuffle',lambda cards: None)


def board(hit='Ornithopter'):
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,'Q, Stacking the Deck')
    target=card(engine,hit,zone=Zone.LIBRARY)
    lands=[card(engine,name,zone=Zone.LIBRARY) for name in ['Island','Mountain']]
    enter(engine,source)
    return engine,source,target,lands


def activate_copy(engine,target):
    fodder=filler(engine,'Exile payment',type_line='Sorcery',zone=Zone.HAND)
    engine.activate_ability(engine.state.players[0],target,len(target.activated_abilities)-1,
                            hand_card_choices=[fodder.instance_id])
    engine.resolve_until_stable()
    return fodder


def offered_copy(engine):
    assert engine.state.pending_choice['kind']=='play_during_resolution'
    return engine.state.find_object(engine.state.resolution_play_choice['instance_ids'][0])


def test_fresh_specs_binding_and_only_first_nonland_gets_ability():
    engine,source,target,lands=board(); a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert source.triggered_abilities and target.zone==Zone.EXILE
    assert all(obj.zone==Zone.EXILE and not obj.activated_abilities for obj in lands)
    assert len(target.activated_abilities)==1
    assert target.activated_abilities[0].cost.activation_zones==('exile',)


def test_shuffle_happens_before_exile_and_can_change_which_nonland_is_hit(monkeypatch):
    engine=game(players=3,library=30); advance_to(engine,'main1'); source=card(engine,'Q, Stacking the Deck')
    first=card(engine,'Sol Ring',zone=Zone.LIBRARY); second=card(engine,'Ornithopter',zone=Zone.LIBRARY)
    seen=[]
    def shuffle(cards):
        seen.append(list(cards)); cards.remove(first); cards.append(first)
    monkeypatch.setattr('random.shuffle',shuffle); enter(engine,source)
    assert len(seen)==1 and first.zone==Zone.EXILE and second.zone==Zone.LIBRARY


def test_granted_activation_is_offered_from_exile_in_legal_actions():
    engine,source,target,lands=board()
    assert any(a['type']=='activate_ability' and a.get('instance_id')==target.instance_id
               for a in engine.legal_actions(engine.state.players[0]))


def test_activation_exiles_chosen_hand_card_and_creates_optional_copy_without_casting_original():
    engine,source,target,lands=board(); fodder=activate_copy(engine,target); copy=offered_copy(engine)
    assert fodder.zone==Zone.EXILE and target.zone==Zone.EXILE
    assert copy is not target and copy.is_copy and copy.name==target.name
    assert not copy.activated_abilities  # the granted ability is not a copiable value
    engine.play_resolution_card(engine.state.players[0],copy); engine.resolve_until_stable()
    assert copy.zone==Zone.BATTLEFIELD and copy.is_token and target.zone==Zone.EXILE


def test_copy_uses_normal_mana_cost_and_can_be_declined():
    engine,source,target,lands=board(hit='Sol Ring'); activate_copy(engine,target); copy=offered_copy(engine)
    player=engine.state.players[0]; player.mana_pool.empty()
    assert not engine.can_cast(player,copy)
    with pytest.raises(ValueError): engine.play_resolution_card(player,copy)
    engine.resolve_pending_choice('decline')
    assert copy not in player.exile and target.zone==Zone.EXILE
    assert not engine.state.free_cast_instance_ids


def test_paying_copy_cost_casts_copy_and_keeps_exiled_original_repeatable():
    engine,source,target,lands=board(hit='Sol Ring'); first=activate_copy(engine,target); copy=offered_copy(engine)
    engine.state.players[0].mana_pool.add('C',1)
    engine.play_resolution_card(engine.state.players[0],copy); engine.resolve_until_stable()
    assert copy.zone==Zone.BATTLEFIELD and first.zone==Zone.EXILE
    second=activate_copy(engine,target)
    assert second.zone==Zone.EXILE and offered_copy(engine).instance_id!=copy.instance_id


def test_only_owner_can_activate_and_only_during_owners_turn():
    engine,source,target,lands=board(); ability=target.activated_abilities[-1]
    assert not engine.can_activate(engine.state.players[1],target,ability)
    engine.state.active_player_index=1
    assert not engine.can_activate(engine.state.players[0],target,ability)


def test_empty_hand_cannot_pay_activation_cost():
    engine,source,target,lands=board(); engine.state.players[0].hand.clear()
    assert not engine.can_activate(engine.state.players[0],target,target.activated_abilities[-1])


def test_activation_is_not_restricted_to_sorcery_timing_on_your_turn():
    engine,source,target,lands=board(); engine.state.current_phase='combat'; engine.state.current_step='begin_combat'
    activate_copy(engine,target)
    assert offered_copy(engine).name=='Ornithopter'


def test_source_q_leaving_does_not_remove_exiled_cards_ability():
    engine,source,target,lands=board(); engine.rules.exile(source)
    activate_copy(engine,target); assert offered_copy(engine).name=='Ornithopter'


def test_new_exile_visit_cannot_use_stale_granted_ability():
    engine,source,target,lands=board(); ability=target.activated_abilities[-1]
    engine.rules.return_to_hand(target); engine.rules.exile(target)
    assert not engine.can_activate(engine.state.players[0],target,ability)
    assert not any(a['type']=='activate_ability' and a.get('instance_id')==target.instance_id
                   for a in engine.legal_actions(engine.state.players[0]))


def test_card_leaving_after_activation_does_not_counter_its_ability():
    engine,source,target,lands=board(); fodder=engine.state.players[0].hand[0]
    engine.activate_ability(engine.state.players[0],target,len(target.activated_abilities)-1,
                            hand_card_choices=[fodder.instance_id])
    engine.rules.return_to_hand(target); engine.resolve_until_stable()
    assert offered_copy(engine).name=='Ornithopter' and target.zone==Zone.HAND


def test_countering_activation_keeps_hand_exile_cost_paid_but_creates_no_copy():
    engine,source,target,lands=board(); fodder=engine.state.players[0].hand[0]
    engine.activate_ability(engine.state.players[0],target,len(target.activated_abilities)-1,
                            hand_card_choices=[fodder.instance_id])
    engine.rules.counter_ability(engine.state.stack[-1]); engine.resolve_until_stable()
    assert fodder.zone==Zone.EXILE and engine.state.pending_choice is None
    assert not any(getattr(o,'is_copy',False) for o in engine.state.players[0].exile)


@pytest.mark.parametrize('size',[0,1,3])
def test_all_land_or_empty_library_exiles_available_cards_without_losing(size):
    engine=game(players=3,library=30); advance_to(engine,'main1')
    player=engine.state.players[0]; player.library[:]=player.library[:size]
    source=card(engine,'Q, Stacking the Deck'); enter(engine,source)
    assert not player.library and len(player.exile)==size and not player.has_lost
    assert all(not obj.activated_abilities for obj in player.exile)


def test_trigger_controller_is_retained_after_q_control_changes():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,'Q, Stacking the Deck'); target=card(engine,'Ornithopter',zone=Zone.LIBRARY)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,instance_id=source.instance_id,
                                    controller_id='p1',object_types=sorted(source.type_words)))
    engine.rules.put_triggers_on_stack(); source.controller_id='p2'
    engine.resolve_until_stable()
    assert target.zone==Zone.EXILE and target.activated_abilities


def test_clone_preserves_granted_exile_activation_and_pending_copy_choice():
    engine,source,target,lands=board(); clone=GameEngine(engine.state.clone())
    selected=clone.state.find_object(target.instance_id); activate_copy(clone,selected)
    copy=offered_copy(clone); clone=GameEngine(clone.state.clone())
    clone.play_resolution_card(clone.state.players[0],clone.state.find_object(copy.instance_id))
    clone.resolve_until_stable()
    assert clone.state.find_object(copy.instance_id).zone==Zone.BATTLEFIELD
    assert engine.state.pending_choice is None and target.zone==Zone.EXILE


def test_paid_instant_copy_uses_normal_targets_and_ceases_after_resolution():
    engine,source,target,lands=board(hit='Lightning Bolt'); activate_copy(engine,target)
    copy=offered_copy(engine); player=engine.state.players[0]; player.mana_pool.add('R',1)
    engine.play_resolution_card(player,copy,targets=[engine.state.players[1]])
    engine.resolve_until_stable()
    assert engine.state.players[1].life==17 and target.zone==Zone.EXILE
    assert copy not in player.exile and copy not in player.graveyard
    assert not engine.state.resolution_play_choice


def test_real_q_cast_resolves_entry_and_grants_exile_ability():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,'Q, Stacking the Deck',zone=Zone.HAND)
    target=card(engine,'Ornithopter',zone=Zone.LIBRARY); player=engine.state.players[0]
    player.mana_pool.add_many({'R':2,'C':2}); engine.cast_spell(player,source); engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD and target.zone==Zone.EXILE
    assert target.activated_abilities[-1].cost.exile_hand_cards==1
