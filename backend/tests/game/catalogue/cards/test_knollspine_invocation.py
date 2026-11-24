"""Knollspine Invocation announces X, discards exactly that value, then deals X."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game


def board(*values):
    engine = game(players=3, library=40)
    source = card(engine, 'Knollspine Invocation')
    cards = [filler(engine, f'Value {value}', mv=value, type_line='Instant', zone=Zone.HAND) for value in values]
    engine.state.players[0].mana_pool.add('C', 10)
    return engine, source, cards


def activate(engine, source, x, cards=None, target=None):
    engine.activate_ability(engine.state.players[0], source, 0, x=x,
                            discard_choices=None if cards is None else [obj.instance_id for obj in cards],
                            targets=[target or engine.state.players[1]])


def offer(engine, source):
    return next((a for a in engine.legal_actions(engine.state.players[0])
                 if a['type'] == 'activate_ability' and a['instance_id'] == source.instance_id), None)


def test_fresh_specs_and_binding():
    engine, source, _ = board(2)
    a, b = specs_for(source.card), specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.activated_abilities) == 1
    assert source.activated_abilities[0].cost.discard_mana_value_x


def test_actual_cast_then_discard_and_mana_precede_damage():
    engine = game(library=40)
    source = card(engine, 'Knollspine Invocation', zone=Zone.HAND)
    cast(engine, source)
    discarded = filler(engine, mv=3, zone=Zone.HAND)
    player, opponent = engine.state.players
    player.mana_pool.empty()
    player.mana_pool.add('C', 3)
    activate(engine, source, 3, [discarded])
    assert discarded.zone == Zone.GRAVEYARD and player.mana_pool.total() == 0
    assert opponent.life == 20
    engine.resolve_until_stable()
    assert opponent.life == 17 and not source.tapped


@pytest.mark.parametrize('value,x', [(2,1), (2,3), (0,1), (1,0)])
def test_wrong_mana_value_is_rejected_before_costs(value,x):
    engine, source, cards = board(value)
    with pytest.raises(ValueError):
        activate(engine, source, x, cards)
    assert cards[0].zone == Zone.HAND and engine.state.players[0].mana_pool.total() == 10
    assert not engine.state.stack


def test_zero_value_card_can_pay_x_zero():
    engine, source, cards = board(0)
    engine.state.players[0].mana_pool.empty()
    activate(engine, source, 0, cards)
    engine.resolve_until_stable()
    assert cards[0].zone == Zone.GRAVEYARD and engine.state.players[1].life == 20


def test_automatic_discard_skips_wrong_value_cards():
    engine, source, cards = board(1,3,2)
    activate(engine, source, 3)
    assert cards[1].zone == Zone.GRAVEYARD and cards[0].zone == cards[2].zone == Zone.HAND


def test_offer_lists_only_affordable_values_and_preserves_gaps():
    engine, source, cards = board(1,3,7)
    player = engine.state.players[0]
    player.mana_pool.empty()
    player.mana_pool.add('C', 4)
    action = offer(engine, source)
    assert action['allowed_x'] == [1,3] and action['min_x'] == 1 and action['max_x'] == 3
    assert action['discard_cost']['mana_value_equals_x']


def test_no_hand_card_means_no_offer():
    engine, source, _ = board()
    assert offer(engine, source) is None


def test_only_unaffordable_hand_cards_means_no_offer():
    engine, source, cards = board(3)
    engine.state.players[0].mana_pool.empty()
    assert offer(engine, source) is None


def test_insufficient_mana_does_not_discard():
    engine, source, cards = board(3)
    engine.state.players[0].mana_pool.empty()
    with pytest.raises(ValueError):
        activate(engine, source, 3, cards)
    assert cards[0].zone == Zone.HAND


def test_countering_does_not_refund_discard_or_deal_damage():
    engine, source, cards = board(3)
    activate(engine, source, 3, cards)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert cards[0].zone == Zone.GRAVEYARD and engine.state.players[1].life == 20


def test_source_departure_does_not_change_announced_x():
    engine, source, cards = board(3)
    activate(engine, source, 3, cards)
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert engine.state.players[1].life == 17


def test_pending_damage_survives_clone():
    engine, source, cards = board(3)
    activate(engine, source, 3, cards)
    restored = GameEngine(engine.state.clone())
    restored.resolve_until_stable()
    assert restored.state.players[1].life == 17 and engine.state.players[1].life == 20


def test_creature_is_a_legal_damage_target():
    engine, source, cards = board(3)
    victim = filler(engine, 'Victim', player='p2', power=5, toughness=5)
    activate(engine, source, 3, cards, victim)
    engine.resolve_until_stable()
    assert victim.damage_marked == 3


def test_invalid_noncreature_target_pays_nothing():
    engine, source, cards = board(3)
    victim = filler(engine, 'Artifact', type_line='Artifact', player='p2')
    with pytest.raises(ValueError):
        activate(engine, source, 3, cards, victim)
    assert cards[0].zone == Zone.HAND


def test_land_can_be_discarded_for_zero():
    engine, source, _ = board()
    land = card(engine, 'Forest', zone=Zone.HAND)
    activate(engine, source, 0, [land])
    engine.resolve_until_stable()
    assert land.zone == Zone.GRAVEYARD


def test_x_in_hand_card_cost_counts_as_zero():
    engine, source, _ = board()
    obj = filler(engine, 'X spell', type_line='Sorcery', mv=1,
                 mana_cost_string='{X}{R}', zone=Zone.HAND)
    activate(engine, source, 1, [obj])
    engine.resolve_until_stable()
    assert engine.state.players[1].life == 19


def test_split_card_uses_combined_mana_value_in_hand():
    engine, source, _ = board()
    obj = filler(engine, 'First // Second', type_line='Instant', mv=4,
                 layout='split', back_name='Second', zone=Zone.HAND)
    activate(engine, source, 4, [obj])
    engine.resolve_until_stable()
    assert engine.state.players[1].life == 16


def test_separate_pending_activations_keep_their_own_x():
    engine, source, cards = board(3,1)
    activate(engine, source, 3, cards[:1])
    activate(engine, source, 1, cards[1:])
    engine.resolve_until_stable()
    assert engine.state.players[1].life == 16


def test_planeswalker_is_a_legal_damage_target():
    engine, source, cards = board(3)
    victim = filler(engine, 'Walker', type_line='Planeswalker', player='p2', loyalty=5)
    activate(engine, source, 3, cards, victim)
    engine.resolve_until_stable()
    assert victim.counters.get('loyalty') == 2


def test_battle_is_a_legal_damage_target():
    engine, source, cards = board(3)
    victim = filler(engine, 'Battle', type_line='Battle — Siege', player='p2', defense=5)
    activate(engine, source, 3, cards, victim)
    engine.resolve_until_stable()
    assert victim.counters.get('defense') == 2
