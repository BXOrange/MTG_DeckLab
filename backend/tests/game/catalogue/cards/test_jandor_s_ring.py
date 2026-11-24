"""Jandor's Ring: exact last-drawn hand visit is paid before the draw resolves."""
import pytest

from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game


def board(draws=1):
    engine = game(players=3, library=40)
    source = card(engine, "Jandor's Ring")
    player = engine.state.players[0]
    engine.rules.draw(player, draws)
    player.mana_pool.add('C', 2)
    return engine, source, player


def activate(engine, source, choices=None):
    engine.activate_ability(engine.state.players[0], source, 0, discard_choices=choices)


def offer(engine, source):
    return next((a for a in engine.legal_actions(engine.state.players[0])
                 if a['type'] == 'activate_ability' and a['instance_id'] == source.instance_id), None)


def test_fresh_specs_and_cost_binding():
    engine, source, player = board()
    a, b = specs_for(source.card), specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    cost = source.activated_abilities[0].cost
    assert cost.taps_self and cost.discard == 1
    assert 'Discard the last card you drew this turn' in cost.label()


def test_actual_cast_and_pay_cost_before_drawing_on_resolution():
    engine = game(library=40)
    source = card(engine, "Jandor's Ring", zone=Zone.HAND)
    cast(engine, source)
    player = engine.state.players[0]
    engine.rules.draw(player, 1)
    drawn = player.hand[-1]
    player.mana_pool.empty()
    player.mana_pool.add('C', 2)
    activate(engine, source, [drawn.instance_id])
    assert source.tapped and drawn.zone == Zone.GRAVEYARD and not player.hand
    assert player.mana_pool.total() == 0
    engine.resolve_until_stable()
    assert len(player.hand) == 1


def test_only_latest_of_multiple_individual_draws_is_offered():
    engine, source, player = board(3)
    action = offer(engine, source)
    assert [o['instance_id'] for o in action['discard_cost']['options']] == [player.hand[-1].instance_id]
    earlier = player.hand[0]
    with pytest.raises(ValueError):
        activate(engine, source, [earlier.instance_id])
    assert not source.tapped and earlier.zone == Zone.HAND


def test_automatic_payment_uses_last_draw():
    engine, source, player = board(3)
    earlier, latest = player.hand[0], player.hand[-1]
    activate(engine, source)
    assert earlier.zone == Zone.HAND and latest.zone == Zone.GRAVEYARD


def test_no_draw_this_turn_cannot_pay_with_an_existing_hand_card():
    engine, source, player = board(0)
    obj = filler(engine, zone=Zone.HAND)
    assert offer(engine, source) is None
    with pytest.raises(ValueError):
        activate(engine, source, [obj.instance_id])
    assert not source.tapped


def test_missing_latest_draw_does_not_fall_back_to_earlier_draw():
    engine, source, player = board(2)
    earlier, latest = player.hand
    engine.rules.exile(latest)
    assert offer(engine, source) is None
    with pytest.raises(ValueError):
        activate(engine, source, [earlier.instance_id])


def test_returning_last_draw_to_hand_is_a_new_ineligible_object():
    engine, source, player = board()
    obj = player.hand[-1]
    engine.rules.discard(player, 1)
    engine.rules.return_from_graveyard(obj, 'hand')
    assert obj.zone == Zone.HAND and offer(engine, source) is None
    with pytest.raises(ValueError):
        activate(engine, source, [obj.instance_id])


def test_putting_another_card_into_hand_does_not_replace_last_draw():
    engine, source, player = board()
    drawn = player.hand[-1]
    other = filler(engine, 'Not drawn', zone=Zone.HAND)
    activate(engine, source)
    assert drawn.zone == Zone.GRAVEYARD and other.zone == Zone.HAND


def test_opponents_draw_does_not_replace_your_last_draw():
    engine, source, player = board()
    drawn = player.hand[-1]
    engine.rules.draw(engine.state.players[1], 2)
    activate(engine, source)
    assert drawn.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('choices', [[], [0, 0], [-1]])
def test_invalid_choices_do_not_pay_mana_tap_or_discard(choices):
    engine, source, player = board()
    drawn = player.hand[-1]
    ids = [drawn.instance_id if value == 0 else value for value in choices]
    with pytest.raises(ValueError):
        activate(engine, source, ids)
    assert not source.tapped and drawn.zone == Zone.HAND
    assert player.mana_pool.total() == 2


def test_countering_keeps_costs_paid_and_does_not_draw():
    engine, source, player = board()
    activate(engine, source)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert source.tapped and not player.hand and len(player.graveyard) == 1


def test_source_departure_does_not_prevent_draw():
    engine, source, player = board()
    activate(engine, source)
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert len(player.hand) == 1


def test_clone_retains_draw_visit_for_unpaid_activation():
    engine, source, player = board()
    restored = GameEngine(engine.state.clone())
    restored_source = restored.state.find_object(source.instance_id)
    activate(restored, restored_source)
    restored.resolve_until_stable()
    assert len(restored.state.players[0].hand) == 1
    assert not source.tapped and len(player.graveyard) == 0


def test_new_turn_forgets_previous_turn_draw():
    engine, source, player = board()
    engine.begin_turn()
    assert offer(engine, source) is None


def test_tapped_ring_cannot_activate():
    engine, source, player = board()
    source.tapped = True
    with pytest.raises(ValueError):
        activate(engine, source)
    assert len(player.hand) == 1


def test_resolved_draw_can_pay_again_after_untapping():
    engine, source, player = board()
    activate(engine, source)
    engine.resolve_until_stable()
    next_draw = player.hand[-1]
    source.tapped = False
    player.mana_pool.add('C', 2)
    activate(engine, source)
    assert next_draw.zone == Zone.GRAVEYARD
    engine.resolve_until_stable()
    assert len(player.hand) == 1 and len(player.graveyard) == 2


def test_prevented_later_draw_does_not_invalidate_last_successful_draw():
    engine, source, player = board()
    drawn = player.hand[-1]
    card(engine, 'Spirit of the Labyrinth')
    engine.recompute_continuous_effects()
    engine.rules.draw(player, 1)
    assert len(player.hand) == 1
    activate(engine, source)
    assert drawn.zone == Zone.GRAVEYARD


def test_drawing_during_an_opponents_turn_can_pay():
    engine, source, player = board(0)
    engine.begin_turn()
    assert engine.state.active_player.id != player.id
    engine.rules.draw(player, 1)
    player.mana_pool.add('C', 2)
    activate(engine, source)
    engine.resolve_until_stable()
    assert len(player.hand) == 1


def test_insufficient_mana_does_not_discard_or_tap():
    engine, source, player = board()
    player.mana_pool.empty()
    player.mana_pool.add('C', 1)
    with pytest.raises(ValueError):
        activate(engine, source)
    assert not source.tapped and len(player.hand) == 1
