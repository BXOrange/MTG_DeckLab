"""Brazen Bluff gives the targeted spell's controller the first decision."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, RICH
from tests.support.star_trek import advance_to


def board(target_name='Sol Ring',owner='p2',free_name='Divination'):
    engine=game(players=3,library=30); advance_to(engine,'main1')
    engine.state.active_player_index=1
    target=card(engine,target_name,player=owner,zone=Zone.HAND)
    caster=engine.state.players[1]
    if owner!='p2':
        engine.state.player_by_id(owner).remove_from_zone(target,Zone.HAND)
        caster.add_to_zone(target,Zone.HAND); target.controller_id='p2'
    caster.mana_pool.add_many(RICH); engine.cast_spell(caster,target)
    bluff=card(engine,'Brazen Bluff',zone=Zone.HAND)
    free=card(engine,free_name,zone=Zone.HAND)
    engine.state.players[0].mana_pool.add('R',2)
    return engine,bluff,target,free


def offer(engine,bluff,target):
    engine.cast_spell(engine.state.players[0],bluff,targets=[target]); engine.resolve_until_stable()
    assert engine.state.pending_choice['kind']=='composite_optional'


def test_fresh_specs_and_noncreature_opposing_spell_target():
    engine,bluff,target,free=board(); a,b=specs_for(bluff.card),specs_for(bluff.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    spec=bluff.spell_effects[0].target_specs[0]
    assert spec.kind=='spell_you_dont_control' and spec.spell_filter=={'noncreature':True}
    assert target.instance_id in {o.get('instance_id') for o in legal_targets(engine.state,'p1',spec,bluff)}


def test_accepting_exiles_spell_without_offering_caster_a_free_cast():
    engine,bluff,target,free=board(); offer(engine,bluff,target)
    assert engine.state.pending_choice['player_id']=='p2'
    engine.resolve_pending_choice('yes')
    assert target.zone==Zone.EXILE and target in engine.state.players[1].exile
    assert bluff.zone==Zone.GRAVEYARD and free.zone==Zone.HAND
    assert not engine.state.pending_choice and not engine.state.free_cast_instance_ids


def test_declining_allows_caster_to_cast_sorcery_off_turn_before_original_spell_resolves():
    engine,bluff,target,free=board(); offer(engine,bluff,target)
    engine.resolve_pending_choice('decline')
    assert engine.state.pending_choice['kind']=='play_during_resolution'
    assert engine.state.pending_choice['player_id']=='p1' and target.zone==Zone.STACK
    player=engine.state.players[0]; player.mana_pool.empty(); before=len(player.hand)
    engine.play_resolution_card(player,free)
    assert free.zone==Zone.STACK and target.zone==Zone.STACK
    assert engine.state.stack[-1].obj is free
    engine.resolve_until_stable()
    assert len(player.hand)==before+1 and free.zone==Zone.GRAVEYARD
    assert target.zone==Zone.BATTLEFIELD and player.mana_pool.total()==0


def test_caster_can_also_decline_the_free_cast():
    engine,bluff,target,free=board(); offer(engine,bluff,target)
    engine.resolve_pending_choice('decline'); engine.resolve_pending_choice('decline')
    engine.resolve_until_stable()
    assert target.zone==Zone.BATTLEFIELD and free.zone==Zone.HAND
    assert not engine.state.free_cast_instance_ids and not engine.state.pending_choice


def test_creature_in_hand_is_not_offered_for_the_free_cast():
    engine,bluff,target,free=board(free_name='Grizzly Bears'); offer(engine,bluff,target)
    engine.resolve_pending_choice('decline')
    assert engine.state.pending_choice is None and free.zone==Zone.HAND
    assert target.zone==Zone.BATTLEFIELD


def test_target_creature_spell_is_not_legal():
    engine,bluff,target,free=board(target_name='Grizzly Bears')
    spec=bluff.spell_effects[0].target_specs[0]
    assert target.instance_id not in {o.get('instance_id') for o in legal_targets(engine.state,'p1',spec,bluff)}


def test_own_noncreature_spell_is_not_a_legal_target():
    engine,bluff,target,free=board(); target.controller_id='p1'
    engine.state.stack[0].controller_id='p1'
    spec=bluff.spell_effects[0].target_specs[0]
    assert not legal_targets(engine.state,'p1',spec,bluff)


def test_a_spell_that_cannot_be_countered_can_still_be_exiled():
    engine,bluff,target,free=board(target_name='Supreme Verdict'); offer(engine,bluff,target)
    engine.resolve_pending_choice('yes')
    assert target.zone==Zone.EXILE and free.zone==Zone.HAND


def test_spell_controller_decides_but_card_is_exiled_to_its_owner():
    engine,bluff,target,free=board(owner='p3'); offer(engine,bluff,target)
    assert engine.state.pending_choice['player_id']=='p2'
    engine.resolve_pending_choice('yes')
    assert target in engine.state.players[2].exile and target not in engine.state.players[1].exile


def test_missing_target_fizzles_without_either_choice():
    engine,bluff,target,free=board()
    engine.cast_spell(engine.state.players[0],bluff,targets=[target])
    engine.rules.move_spell_off_stack(target,'exile'); engine.resolve_until_stable()
    assert engine.state.pending_choice is None and free.zone==Zone.HAND


def test_target_now_controlled_by_caster_is_illegal_at_resolution():
    engine,bluff,target,free=board()
    engine.cast_spell(engine.state.players[0],bluff,targets=[target])
    target.controller_id='p1'; engine.state.stack[0].controller_id='p1'
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and free.zone==Zone.HAND
    assert target.zone==Zone.BATTLEFIELD


def test_only_one_noncreature_spell_is_cast_for_free():
    engine,bluff,target,free=board(); second=card(engine,'Sol Ring',zone=Zone.HAND)
    offer(engine,bluff,target); engine.resolve_pending_choice('decline')
    engine.play_resolution_card(engine.state.players[0],free); engine.resolve_until_stable()
    assert second.zone==Zone.HAND and second.instance_id not in engine.state.free_cast_instance_ids


def test_clone_preserves_opponents_decision_and_free_cast_fallback():
    engine,bluff,target,free=board(); offer(engine,bluff,target)
    clone=GameEngine(engine.state.clone()); clone.resolve_pending_choice('decline')
    assert clone.state.pending_choice['player_id']=='p1'
    selected=clone.state.find_object(free.instance_id)
    clone.play_resolution_card(clone.state.players[0],selected); clone.resolve_until_stable()
    assert selected.zone==Zone.GRAVEYARD
    assert free.zone==Zone.HAND and engine.state.pending_choice['player_id']=='p2'


def test_free_cast_checks_modal_spell_face_instead_of_creature_front():
    engine,bluff,target,free=board(free_name='Valki, God of Lies // Tibalt, Cosmic Impostor')
    offer(engine,bluff,target); engine.resolve_pending_choice('decline')
    player=engine.state.players[0]
    assert free.instance_id in engine.state.resolution_play_choice['instance_ids']
    assert not engine.can_cast(player,free) and engine.can_cast(player,free,face='back')
    with pytest.raises(ValueError): engine.play_resolution_card(player,free)
    engine.play_resolution_card(player,free,face='back'); engine.resolve_until_stable()
    assert free.zone==Zone.BATTLEFIELD and free.is_planeswalker


def test_stack_item_target_survives_the_opponents_pending_decision():
    engine,bluff,target,free=board(); stack_item=engine.state.stack[0]
    offer(engine,bluff,stack_item); engine.resolve_pending_choice('yes')
    assert target.zone==Zone.EXILE


def test_adventure_spell_is_allowed_but_its_creature_is_not():
    engine,bluff,target,free=board(free_name='Bonecrusher Giant // Stomp')
    offer(engine,bluff,target); engine.resolve_pending_choice('decline')
    player=engine.state.players[0]
    assert not engine.can_cast(player,free)
    engine.play_resolution_card(player,free,face='back',targets=[engine.state.players[2]])
    engine.resolve_until_stable()
    assert engine.state.players[2].life==18 and free.zone==Zone.EXILE


def test_clone_preserves_stack_id_target_when_opponent_accepts_exile():
    engine,bluff,target,free=board(); offer(engine,bluff,engine.state.stack[0])
    clone=GameEngine(engine.state.clone()); clone.resolve_pending_choice('yes')
    assert clone.state.find_object(target.instance_id).zone==Zone.EXILE
    assert target.zone==Zone.STACK and engine.state.pending_choice['player_id']=='p2'


def test_current_opponent_controller_gets_decision_after_control_changes():
    engine,bluff,target,free=board()
    engine.cast_spell(engine.state.players[0],bluff,targets=[target])
    target.controller_id='p3'; engine.state.stack[0].controller_id='p3'
    engine.resolve_until_stable()
    assert engine.state.pending_choice['player_id']=='p3'
    engine.resolve_pending_choice('decline')
    assert engine.state.pending_choice['kind']=='play_during_resolution'
    assert engine.state.pending_choice['player_id']=='p1'
