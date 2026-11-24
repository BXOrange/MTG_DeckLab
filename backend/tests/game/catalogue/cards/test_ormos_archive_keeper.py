"""Ormos replaces empty draws and pays three pairwise different names."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game


def board(*names):
    engine = game(players=3, library=40)
    source = card(engine, 'Ormos, Archive Keeper')
    cards = [filler(engine, name, type_line='Instant', zone=Zone.HAND) for name in names]
    engine.state.players[0].mana_pool.add_many({'U': 2, 'C': 1})
    return engine, source, cards


def activate(engine, source, cards=None):
    engine.activate_ability(engine.state.players[0], source, 0,
                            discard_choices=None if cards is None else [obj.instance_id for obj in cards])


def empty_library(engine, player='p1', keep=0):
    library = engine.state.player_by_id(player).library
    for obj in list(library)[:-keep] if keep else list(library):
        engine.rules.exile(obj)


def test_fresh_specs_bind_flying_replacement_and_activation():
    engine, source, _ = board()
    a,b = specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert combat.has(source, 'flying') and len(source.replacement_effects) == 1
    assert len(source.activated_abilities) == 1


def test_actual_cast_discard_cost_then_draw_five():
    engine = game(library=40)
    source = card(engine, 'Ormos, Archive Keeper', zone=Zone.HAND)
    cast(engine, source)
    cards = [filler(engine, name, zone=Zone.HAND) for name in ('A','B','C')]
    activate(engine, source, cards)
    assert all(obj.zone == Zone.GRAVEYARD for obj in cards)
    assert not engine.state.players[0].hand
    engine.resolve_until_stable()
    assert len(engine.state.players[0].hand) == 5


@pytest.mark.parametrize('names', [('A','A','B'), ('A','A','A'), ('A','B')])
def test_names_and_card_count_must_be_valid_before_payment(names):
    engine, source, cards = board(*names)
    with pytest.raises(ValueError): activate(engine, source, cards)
    assert all(obj.zone == Zone.HAND for obj in cards)
    assert engine.state.players[0].mana_pool.total() == 3


def test_automatic_discard_finds_a_complete_different_name_set():
    engine, source, cards = board('A','A','B','C')
    activate(engine, source)
    assert cards[0].zone == cards[2].zone == cards[3].zone == Zone.GRAVEYARD
    assert cards[1].zone == Zone.HAND


def test_interchangeable_names_are_not_different():
    engine, source, cards = board('Cecily, Haunted Mage','Eleven, the Mage','Third')
    with pytest.raises(ValueError): activate(engine, source, cards)


def test_nameless_cards_cannot_pay():
    engine, source, cards = board('A','B','C')
    cards[0]._derived_name = ''
    with pytest.raises(ValueError): activate(engine, source, cards)


def test_split_name_overlap_rejects_otherwise_different_cards():
    engine, source, cards = board('A','B')
    split = filler(engine, 'A // C', layout='split', back_name='C', type_line='Instant', zone=Zone.HAND)
    with pytest.raises(ValueError): activate(engine, source, [*cards,split])


def test_automatic_selection_backtracks_around_split_card():
    engine, source, cards = board('B','C','D')
    split = filler(engine, 'B // C', layout='split', back_name='C', type_line='Instant', zone=Zone.HAND)
    player = engine.state.players[0]
    player.hand.remove(split)
    player.hand.insert(0,split)
    activate(engine, source)
    assert split.zone == Zone.HAND and all(obj.zone == Zone.GRAVEYARD for obj in cards)


def test_empty_library_draw_adds_five_counters_without_loss_or_draw_event():
    engine, source, _ = board()
    empty_library(engine)
    player = engine.state.players[0]
    engine.rules.draw(player,1)
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1') == 5 and not player.has_lost
    assert engine.state.cards_drawn_this_turn.get(player.id,0) == 0
    assert not player.attempted_draw_from_empty


def test_five_empty_draws_are_five_replacements():
    engine, source, cards = board('A','B','C')
    empty_library(engine)
    activate(engine,source,cards)
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1') == 25
    assert not engine.state.players[0].has_lost


def test_running_out_mid_draw_draws_remaining_then_replaces_the_rest():
    engine, source, cards = board('A','B','C')
    empty_library(engine,keep=2)
    activate(engine,source,cards)
    engine.resolve_until_stable()
    assert len(engine.state.players[0].hand) == 2
    assert source.counters.get('+1/+1') == 15


def test_replacement_tracks_changed_controller():
    engine, source, _ = board()
    source.controller_id = 'p2'
    empty_library(engine,'p2')
    engine.rules.draw(engine.state.players[1],1)
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1') == 5


def test_clone_replacement_mutates_only_restored_source():
    engine, source, _ = board()
    empty_library(engine)
    restored = GameEngine(engine.state.clone())
    restored.rules.draw(restored.state.players[0],1)
    restored.resolve_until_stable()
    assert restored.state.find_object(source.instance_id).counters.get('+1/+1') == 5
    assert not source.counters.get('+1/+1')


def test_countering_does_not_refund_discard_or_draw():
    engine, source, cards = board('A','B','C')
    activate(engine,source,cards)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert not engine.state.players[0].hand
    assert all(obj.zone == Zone.GRAVEYARD for obj in cards)


def test_source_departure_keeps_draw_ability_but_removes_replacement():
    engine, source, cards = board('A','B','C')
    activate(engine,source,cards)
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert len(engine.state.players[0].hand) == 5


def test_opponents_empty_draw_is_not_protected():
    engine, source, _ = board()
    empty_library(engine,'p2')
    opponent = engine.state.players[1]
    engine.rules.draw(opponent,1)
    engine.resolve_until_stable()
    assert opponent.has_lost and not source.counters.get('+1/+1')


def test_leaving_battlefield_ends_empty_draw_protection():
    engine, source, _ = board()
    empty_library(engine)
    engine.rules.exile(source)
    engine.rules.draw(engine.state.players[0],1)
    engine.resolve_until_stable()
    assert engine.state.players[0].has_lost and not source.counters.get('+1/+1')


def test_repeated_card_id_does_not_pay_three_discards():
    engine, source, cards = board('A','B','C')
    with pytest.raises(ValueError): activate(engine,source,[cards[0],cards[0],cards[2]])
    assert all(obj.zone == Zone.HAND for obj in cards)


def test_tapped_summoning_sick_ormos_can_use_non_tap_ability():
    engine, source, cards = board('A','B','C')
    source.tapped = source.summoning_sick = True
    activate(engine,source,cards)
    engine.resolve_until_stable()
    assert len(engine.state.players[0].hand) == 5


def test_pending_draw_survives_clone_without_repaying_discard():
    engine, source, cards = board('A','B','C')
    activate(engine,source,cards)
    restored = GameEngine(engine.state.clone())
    restored.resolve_until_stable()
    assert len(restored.state.players[0].hand) == 5
    assert len(restored.state.players[0].graveyard) == 3
    assert not engine.state.players[0].hand
