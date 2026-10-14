"""MEC-119: Warp payment, delayed exile, and incarnation-scoped permission."""
import pytest
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSession, GameActionError


def setup():
    engine = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = 'main1'
    player = engine.state.active_player
    card = Card(id='warper', name='Warper', type_line='Creature — Warrior', is_creature=True,
                mana_cost_string='{5}{R}', converted_mana_cost=6, power=3, toughness=3,
                keywords=['Warp'], oracle_text='Warp {1}{R}')
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    bind_from_catalogue(obj)
    player.mana_pool.add_many({'R': 8})
    return engine, player, obj


def end(engine):
    engine._fire_delayed_triggers('end')
    engine.resolve_until_stable()


def test_session_warp_cost_event_and_owner_recast():
    engine, player, obj = setup()
    offer = next(a for a in engine.legal_actions(player) if a.get('warp'))
    assert offer['cost_label'] == '{1}{R}'
    assert offer['mana_value'] == 6
    GameSession(engine).apply_action(offer)
    assert player.mana_pool.total() == 6
    assert engine.state.stack[-1].obj is obj
    engine.resolve_until_stable()
    assert obj in engine.state.battlefield
    end(engine)
    assert obj in player.exile and obj.warped_card
    assert not engine.can_cast(player, obj)
    engine.state.internal_turn.number += 1
    engine.state.current_step = 'main1'
    assert engine.can_cast(player, obj)
    assert any(a['instance_id'] == obj.instance_id for a in engine.legal_actions(player) if a['type'] == 'cast_spell')
    assert not engine.can_cast(player, obj, warp=True)
    engine.cast_spell(player, obj)
    assert not obj.warped_card
    engine.resolve_until_stable()
    end(engine)
    assert obj in engine.state.battlefield


def test_normal_cast_and_conflicting_alt_costs():
    engine, player, obj = setup()
    for flag in ('free', 'evoke', 'surge', 'alt_cost', 'mutate'):
        assert not engine.can_cast(player, obj, warp=True, **{flag: True})
    engine.cast_spell(player, obj)
    engine.resolve_until_stable()
    end(engine)
    assert obj in engine.state.battlefield and not obj.warped_card


def test_delayed_exile_tracks_incarnation():
    engine, player, obj = setup()
    engine.cast_spell(player, obj, warp=True)
    engine.resolve_until_stable()
    engine.rules.exile(obj)
    player.exile.remove(obj)
    obj.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(obj)
    end(engine)
    assert obj in engine.state.battlefield and not obj.warped_card


def test_control_change_exiles_for_owner_only_and_permission_clears():
    engine, player, obj = setup()
    engine.cast_spell(player, obj, warp=True)
    engine.resolve_until_stable()
    other = next(p for p in engine.state.players if p is not player)
    obj.controller_id = other.id
    end(engine)
    assert obj.warped_card
    engine.state.internal_turn.number += 1
    engine.state.current_step = 'main1'
    assert engine._has_warp_permission(player, obj)
    assert not engine._has_warp_permission(other, obj)
    player.exile.remove(obj)
    obj.zone = Zone.HAND
    player.hand.append(obj)
    player.hand.remove(obj)
    obj.zone = Zone.EXILE
    player.exile.append(obj)
    assert not engine._has_warp_permission(player, obj)


def test_warp_cast_sets_void_even_when_countered():
    from mtg_analyzer.game.static_conditions import condition_holds
    from mtg_analyzer.models.game.events import EventType
    engine, player, obj = setup()
    assert not condition_holds({'kind': 'void_this_turn'}, engine.state, obj, player.id)
    engine.cast_spell(player, obj, warp=True)
    event = next(e for e in engine.state.events_this_turn() if e.type == EventType.SPELL_CAST)
    assert event.get('warped') is True
    assert condition_holds({'kind': 'void_this_turn'}, engine.state, obj, player.id)
    engine.rules.counter_spell(obj)
    end(engine)
    assert obj in player.graveyard and not engine.state.delayed_triggers


def test_warp_additional_cost_and_commander_tax():
    from mtg_analyzer.game.costs import parse_activation_cost
    engine, player, obj = setup()
    obj.additional_cast_cost = parse_activation_cost('{2}')
    obj.is_commander = True
    player.commander_casts[obj.instance_id] = 1
    assert engine.effective_cast_cost(player, obj, warp=True).resolved_value == 4
    engine.cast_spell(player, obj, warp=True)
    assert player.mana_pool.total() == 4


def test_warp_missing_additional_discard_cost_refuses():
    from mtg_analyzer.game.costs import parse_activation_cost
    engine, player, obj = setup()
    obj.additional_cast_cost = parse_activation_cost('Discard a card')
    assert not engine.can_cast(player, obj, warp=True)
    assert not any(a.get('warp') for a in engine.legal_actions(player))


def test_warp_can_pay_kicker_and_presents_additional_cost_choices():
    from mtg_analyzer.game.costs import parse_activation_cost
    engine, player, obj = setup()
    obj.parametric_keywords['kicker'] = {'cost': '{2}'}
    obj.additional_cast_cost = parse_activation_cost('Pay 2 life')
    offer = next(a for a in engine.legal_actions(player) if a.get('warp'))
    assert offer['has_kicker'] and offer['additional_cost_label']
    engine.cast_spell(player, obj, warp=True, kicked=1)
    assert player.mana_pool.total() == 4


def test_warp_permission_keeps_normal_timing_after_turn_ends():
    engine, player, obj = setup()
    engine.cast_spell(player, obj, warp=True)
    engine.resolve_until_stable()
    end(engine)
    engine.state.internal_turn.number += 1
    engine.state.current_step = 'end'
    assert engine._has_warp_permission(player, obj)
    assert not engine.can_cast(player, obj)
    engine.state.current_step = 'main1'
    assert engine.can_cast(player, obj)


def test_session_warp_undo_restores_permission_and_delayed_trigger():
    engine, player, obj = setup()
    session = GameSession(engine)
    offer = next(a for a in engine.legal_actions(player) if a.get('warp'))
    session.apply_action(offer)
    session.rewind()
    restored = session.engine.state.find_object(obj.instance_id)
    assert restored.zone == Zone.HAND and not restored.cast_via_warp


def test_warp_spell_copy_resolves_with_delayed_exile():
    engine, player, obj = setup()
    original = engine.cast_spell(player, obj, warp=True)
    copied = engine.rules.copy_spell(original, player.id)[0]
    assert copied.obj.cast_via_warp
    engine.resolve_until_stable()
    assert obj.cast_via_warp
    assert len(engine.state.delayed_triggers) == 2
    end(engine)
    assert obj.warped_card and copied.obj not in engine.state.battlefield


def test_warp_exile_event_observers_see_designation():
    from mtg_analyzer.models.game.events import EventType
    engine, player, obj = setup()
    observed = []
    engine.state.subscribe(lambda event: observed.append(obj.warped_card) if event.type == EventType.EXILE else None)
    engine.cast_spell(player, obj, warp=True)
    engine.resolve_until_stable()
    end(engine)
    assert observed == [True]


def test_warp_does_not_allow_announced_x_absent_from_alternative_cost():
    engine, player, obj = setup()
    obj.card.mana_cost_string = '{X}{R}'
    assert not engine.can_cast(player, obj, x=2, warp=True)
    assert engine.can_cast(player, obj, x=0, warp=True)


def test_warp_priority_session_rejects_non_holder():
    engine, player, obj = setup()
    other = next(p for p in engine.state.players if p is not player)
    engine.state.priority_player_index = engine.state.players.index(other)
    session = GameSession(engine, mode='multiplayer')
    with pytest.raises(GameActionError, match="priority"):
        session.apply_action({'type': 'cast_spell', 'instance_id': obj.instance_id, 'warp': True}, actor_id=player.id)
