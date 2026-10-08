"""Miracle reveal and its response window bound the only discounted cast."""
import json
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.game_session import GameSession, MULTIPLAYER
from tests.game.catalogue.cards.test_miracle_worker_deck import _game, _card, _lib


def _setup():
    engine = _game(library=8)
    player = engine.state.players[0]
    aminatou = _card(engine, 'Aminatou, Veil Piercer')
    spell = _lib(engine, 'Private Enchantment', 'Enchantment', mv=5)
    spell.card.mana_cost = {'generic': 4, 'G': 1}
    spell.card.mana_cost_string = '{4}{G}'
    player.mana_pool.add('G', 1)
    return engine, player, aminatou, spell


def _reveal_to_stack(engine, player, spell):
    engine.rules.draw(player)
    engine.rules.resolve_choice('reveal')
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 1
    return engine.state.stack[-1]


def test_miracle_reveal_decision_is_private_and_does_not_arm_a_turn_window():
    engine, player, aminatou, spell = _setup()
    engine.rules.draw(player)
    session = GameSession(engine)
    assert spell.name in json.dumps(session.view(perspective='p1'))
    assert spell.name not in json.dumps(session.view(perspective='p2'))
    assert not spell.miracle_armed
    engine.resolve_pending_choice('decline')
    engine.state.current_step = 'main1'
    assert not engine.can_cast(player, spell, alt_cost=True)
    assert not engine.state.pending_choice and not engine.state.stack


def test_miracle_is_public_until_countered_then_discount_and_reveal_end():
    engine, player, aminatou, spell = _setup()
    trigger = _reveal_to_stack(engine, player, spell)
    session = GameSession(engine)
    assert spell.name in json.dumps(session.view(perspective='p2'))
    assert not engine.can_cast(player, spell, alt_cost=True)
    engine.rules.counter_ability(trigger)
    assert spell.name not in json.dumps(session.view(perspective='p2'))
    assert not spell.miracle_armed and spell.zone == Zone.HAND


def test_declining_resolved_miracle_offer_closes_it_before_later_main_phase():
    engine, player, aminatou, spell = _setup()
    _reveal_to_stack(engine, player, spell)
    engine.rules.resolve_top_of_stack()
    assert engine.state.resolution_play_choice['miracle']
    assert engine.can_cast(player, spell, alt_cost=True)
    engine.resolve_pending_choice('decline')
    engine.state.current_step = 'main1'
    assert not engine.can_cast(player, spell, alt_cost=True)
    assert not spell.miracle_armed and not engine.state.miracle_armed_ids


def test_miracle_casts_during_opponents_turn_and_preserves_colored_cost():
    engine, player, aminatou, spell = _setup()
    engine.state.active_player_index = 1
    engine.state.current_step = 'combat_damage'
    _reveal_to_stack(engine, player, spell)
    engine.rules.resolve_top_of_stack()
    assert engine.can_cast(player, spell, alt_cost=True)
    with pytest.raises(ValueError, match='miracle cost'):
        engine.play_resolution_card(player, spell)
    engine.play_resolution_card(player, spell, alt_cost=True)
    assert player.mana_pool.total() == 0 and spell.zone == Zone.STACK
    assert not spell.miracle_armed and engine.state.resolution_play_choice is None
    engine.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD


def test_miracle_trigger_retains_granted_cost_after_aminatou_leaves():
    engine, player, aminatou, spell = _setup()
    _reveal_to_stack(engine, player, spell)
    engine.rules.exile(aminatou)
    engine.rules.resolve_top_of_stack()
    engine.play_resolution_card(player, spell, alt_cost=True)
    assert player.mana_pool.total() == 0


def test_miracle_does_not_follow_card_out_of_hand_and_back():
    engine, player, aminatou, spell = _setup()
    _reveal_to_stack(engine, player, spell)
    engine.rules.exile(spell)
    engine.rules.return_to_hand(spell)
    engine.rules.resolve_top_of_stack()
    assert not engine.state.pending_choice and not engine.state.resolution_play_choice
    assert not engine.can_cast(player, spell, alt_cost=True)


@pytest.mark.parametrize('reveal', [True, False])
def test_multiple_draws_pause_before_second_card_until_reveal_decision(reveal):
    engine, player, aminatou, spell = _setup()
    engine.rules.draw(player, 3)
    assert player.hand == [spell] and engine.state.cards_drawn_this_turn[player.id] == 1
    engine.rules.resolve_choice('reveal' if reveal else 'decline')
    assert len(player.hand) == 3 and engine.state.cards_drawn_this_turn[player.id] == 3
    assert len(engine.rules.pending_triggers) == int(reveal)


def test_replaced_multi_draw_resumes_without_reapplying_draw_multiplier():
    engine, player, aminatou, spell = _setup()
    from mtg_analyzer.game.effects.core import ReplacementEffect
    from mtg_analyzer.models.game.events import EventType

    player.player_effects.append(ReplacementEffect(EventType.DRAW,
        lambda event, context: event.copy_with(count=event.get('count', 1) * 2)))
    engine.rules.draw(player, 2)
    assert player.hand == [spell]
    engine.rules.resolve_choice('decline')
    assert len(player.hand) == 4 and engine.state.cards_drawn_this_turn[player.id] == 4


def test_multiplayer_reveal_leaves_miracle_trigger_for_responses_and_rewind():
    engine, player, aminatou, spell = _setup()
    engine.rules.draw(player)
    session = GameSession(engine, mode=MULTIPLAYER, require_setup=False)
    session.apply_action({'type': 'choose', 'option_id': 'reveal', 'name': spell.name}, actor_id='p1')
    assert len(session.engine.state.stack) == 1 and not session.engine.state.resolution_play_choice
    assert session.move_log == ['choose']
    session.rewind()
    assert session.engine.state.pending_choice['kind'] == 'miracle_reveal'
    assert not session.engine.state.find_object(spell.instance_id).miracle_armed


def test_each_player_draw_preserves_separate_miracle_reveal_choices():
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.game.effects.damage_draw import DrawCardEffect

    engine, player, aminatou, spell = _setup()
    _card(engine, 'Aminatou, Veil Piercer', player='p2')
    other = _lib(engine, 'Other Private Enchantment', 'Enchantment', player='p2', mv=1)
    DrawCardEffect(selector='each_player').apply(GameContext(engine.state, engine.rules))
    assert engine.state.pending_choice['player_id'] == 'p1' and other.zone == Zone.LIBRARY
    engine.resolve_pending_choice('decline')
    assert engine.state.pending_choice['player_id'] == 'p2' and other.zone == Zone.HAND
    engine.resolve_pending_choice('decline')
    assert not engine.state.pending_choice and not engine.state.stack
