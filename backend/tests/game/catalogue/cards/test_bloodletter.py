"""Bloodletter's global name-initial state trigger and conditional self sacrifice."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,cast,filler,game


def board():
    engine=game(players=3,library=30)
    source=card(engine,'Bloodletter')
    return engine,source


def permanent(engine,name,player='p1',kind='Artifact'):
    return filler(engine,name,player=player,type_line=kind,
                  **({'power':5,'toughness':5} if 'Creature' in kind else {}))


def queue(engine):
    engine.rules.check_state_based_actions()
    engine.rules.put_triggers_on_stack()


def test_fresh_specs_bind_state_trigger():
    engine,source=board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==1


def test_three_nonland_initials_across_players_trigger_sacrifice_and_global_damage():
    engine,source=board()
    for i,player in enumerate(('p1','p2','p3')):permanent(engine,f'Alpha {i}',player,kind='Creature')
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD
    assert [p.life for p in engine.state.players]==[18,18,18]
    assert all(obj.damage_marked==2 for obj in engine.state.battlefield if obj.is_creature)


def test_source_name_can_contribute_to_three():
    engine,source=board()
    permanent(engine,'Book');permanent(engine,'Basin')
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD


def test_two_matching_nonland_names_are_not_enough():
    engine,source=board()
    permanent(engine,'Alpha');permanent(engine,'Atom')
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD and not engine.state.stack


def test_lands_are_excluded_even_if_they_share_initials():
    engine,source=board()
    for name in ('Book','Basin','Bog'):permanent(engine,name,kind='Land')
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD


def test_matching_is_case_insensitive():
    engine,source=board()
    for name in ('apple','Apple','APPLE'):permanent(engine,name)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD


def test_tokens_count_as_permanents():
    engine,source=board()
    for name in ('Book','Basin'):
        obj=permanent(engine,name);obj.is_token=True
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD


def test_numeric_name_prefix_is_not_a_letter():
    engine,source=board()
    for name in ('1 Alpha','1 Beta','1 Gamma'):permanent(engine,name)
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD


def test_nameless_and_face_down_objects_do_not_contribute():
    engine,source=board()
    permanent(engine,'Alpha');permanent(engine,'Atom')
    hidden=permanent(engine,'Azure',kind='Creature');hidden.face_down=True
    blank=filler(engine,'Arcade // Atrium',type_line='Enchantment — Room',layout='split',
                 back_name='Atrium',back_type_line='Enchantment — Room')
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD
    assert hidden.names==blank.names==()


def test_pending_state_trigger_is_not_queued_repeatedly():
    engine,source=board()
    permanent(engine,'Book');permanent(engine,'Basin')
    for _ in range(3):engine.rules.check_state_based_actions()
    assert len(engine.rules.pending_triggers)==1
    engine.rules.put_triggers_on_stack()
    for _ in range(3):engine.rules.check_state_based_actions()
    assert len(engine.state.stack)==1 and not engine.rules.pending_triggers


def test_countered_state_trigger_can_trigger_again_while_state_is_true():
    engine,source=board()
    permanent(engine,'Book');permanent(engine,'Basin')
    queue(engine)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD and [p.life for p in engine.state.players]==[18,18,18]


def test_condition_need_not_remain_true_on_resolution():
    engine,source=board()
    a=permanent(engine,'Book');permanent(engine,'Basin')
    queue(engine)
    engine.rules.exile(a)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD and engine.state.players[0].life==18


def test_missing_source_cannot_be_sacrificed_and_deals_no_damage():
    engine,source=board()
    permanent(engine,'Book');permanent(engine,'Basin')
    queue(engine)
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert [p.life for p in engine.state.players]==[20,20,20]


def test_prohibited_sacrifice_does_not_deal_damage():
    engine,source=board()
    a=permanent(engine,'Book');permanent(engine,'Basin')
    queue(engine)
    source.cant_be_sacrificed_this_turn=True
    engine.rules.exile(a)
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD and [p.life for p in engine.state.players]==[20,20,20]


def test_pending_state_trigger_survives_clone():
    engine,source=board()
    permanent(engine,'Book');permanent(engine,'Basin')
    queue(engine)
    restored=GameEngine(engine.state.clone())
    restored.resolve_until_stable()
    assert restored.state.find_object(source.instance_id).zone==Zone.GRAVEYARD
    assert [p.life for p in restored.state.players]==[18,18,18]
    assert source.zone==Zone.BATTLEFIELD


def test_room_with_two_same_initial_names_counts_as_one_permanent():
    engine,source=board()
    room=filler(engine,'Amber // Atrium',type_line='Enchantment — Room',layout='split',
                back_name='Atrium',back_type_line='Enchantment — Room')
    room.unlocked_doors={'left','right'}
    permanent(engine,'Apple')
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD
    permanent(engine,'Anchor')
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD


def test_actual_cast_into_matching_board():
    engine=game(library=30)
    permanent(engine,'Book');permanent(engine,'Basin')
    source=card(engine,'Bloodletter',zone=Zone.HAND)
    cast(engine,source)
    assert source.zone==Zone.GRAVEYARD and [p.life for p in engine.state.players]==[18,18]


def test_returned_source_cannot_be_sacrificed_by_its_old_trigger():
    engine,source=board()
    a=permanent(engine,'Book');permanent(engine,'Basin')
    queue(engine)
    engine.rules.exile(a)
    engine.rules.put_into_graveyard(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert source.zone==Zone.BATTLEFIELD and [p.life for p in engine.state.players]==[20,20,20]


def test_sacrifice_payoff_damage_keeps_bloodletter_as_source():
    from mtg_analyzer.models.game.events import EventType
    engine,source=board()
    permanent(engine,'Book');permanent(engine,'Basin')
    engine.resolve_until_stable()
    damage=[event for event in engine.state.events_this_turn() if event.type==EventType.DAMAGE]
    assert len(damage)==3 and all(event.get('source_id')==source.instance_id for event in damage)
