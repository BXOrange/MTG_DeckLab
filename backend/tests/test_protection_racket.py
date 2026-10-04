"""Protection Racket: one reveal and optional life payment per opponent."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.game.card_registry import specs_for
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _game, _card
from tests.test_weathered_sentinels import _to


def _position(seats=4, cards=("Solemn Simulacrum", "Llanowar Elves", "Forest")):
    engine = _game(seats=seats)
    racket = _card(engine, "Protection Racket")
    p1 = engine.state.player_by_id("p1")
    p1.library.clear()
    objects = [_card(engine, name, zone=Zone.LIBRARY) for name in reversed(cards)]
    objects.reverse()
    _to(engine, "p1", "upkeep")
    return engine, racket, objects


def test_opponents_decide_in_turn_order_and_each_moves_a_new_top_card():
    engine, _, cards = _position()
    p1, p2, p3, p4 = engine.state.players
    assert engine.state.pending_choice["player_id"] == p2.id
    assert cards[0].name in engine.state.pending_choice["prompt"]
    assert "4" in engine.state.pending_choice["options"][0]["label"]
    engine.resolve_pending_choice("pay")
    assert p2.life == 16 and cards[0].zone == Zone.EXILE
    assert engine.state.pending_choice["player_id"] == p3.id
    assert cards[1].name in engine.state.pending_choice["prompt"]
    engine.resolve_pending_choice("decline")
    assert p3.life == 20 and cards[1].zone == Zone.HAND
    assert engine.state.pending_choice["player_id"] == p4.id
    engine.resolve_pending_choice("pay")
    assert p4.life == 20 and cards[2].zone == Zone.EXILE
    assert engine.state.pending_choice is None
    assert not p1.library


@pytest.mark.parametrize("life", [1, 3])
def test_unaffordable_life_payment_puts_card_into_hand(life):
    engine = _game()
    _card(engine, "Protection Racket")
    p1, p2 = engine.state.players
    p1.library.clear()
    card = _card(engine, "Solemn Simulacrum", zone=Zone.LIBRARY)
    p2.life = life
    _to(engine, "p1", "upkeep")
    assert card.zone == Zone.HAND
    assert engine.state.pending_choice is None
    assert p2.life == life


def test_empty_library_does_not_reuse_the_previous_reveal():
    engine, _, cards = _position(cards=("Llanowar Elves",))
    engine.resolve_pending_choice("decline")
    assert cards[0].zone == Zone.HAND
    assert engine.state.pending_choice is None
    assert len(engine.state.player_by_id("p1").hand) == 1


def test_other_upkeeps_do_not_trigger_racket():
    engine, _, cards = _position(seats=2, cards=("Llanowar Elves", "Forest"))
    engine.resolve_pending_choice("decline")
    _to(engine, "p2", "upkeep")
    assert engine.state.pending_choice is None
    assert cards[1].zone == Zone.LIBRARY


def test_specs_are_fresh_and_trigger_is_not_targeted():
    engine = _game()
    racket = _card(engine, "Protection Racket")
    first, second = specs_for(racket.card), specs_for(racket.card)
    first[0].effects[0].params["effects"].clear()
    assert len(second[0].effects[0].params["effects"]) == 2
    assert len(racket.triggered_abilities) == 1


def test_eliminated_opponent_is_skipped():
    engine = _game(seats=3)
    _card(engine, "Protection Racket")
    p1, p2, p3 = engine.state.players
    p2.has_lost = True
    p1.library.clear()
    card = _card(engine, "Llanowar Elves", zone=Zone.LIBRARY)
    _to(engine, "p1", "upkeep")
    assert engine.state.pending_choice["player_id"] == p3.id
    engine.resolve_pending_choice("decline")
    assert card.zone == Zone.HAND
    assert engine.state.pending_choice is None


def test_can_pay_exact_life_and_finish_the_single_ability():
    engine, _, cards = _position(seats=3, cards=("Solemn Simulacrum", "Llanowar Elves"))
    p1, p2, p3 = engine.state.players
    p2.life = 4
    engine.resolve_pending_choice("pay")
    assert p2.life == 0 and not p2.has_lost
    assert engine.state.pending_choice["player_id"] == p3.id
    engine.resolve_pending_choice("decline")
    assert cards[0].zone == Zone.EXILE and cards[1].zone == Zone.HAND
    assert p2.has_lost


def test_revealed_card_is_kept_across_a_cloned_pending_payment():
    engine, _, cards = _position(seats=2, cards=("Llanowar Elves",))
    restored = GameEngine(engine.state.clone())
    restored.resolve_pending_choice("pay")
    obj = restored.state.find_object(cards[0].instance_id)
    assert obj.zone == Zone.EXILE
    assert restored.state.player_by_id("p2").life == 19
    assert cards[0].zone == Zone.LIBRARY  # the original game is unchanged


def test_reveals_are_public_and_putting_into_hand_is_not_a_draw():
    engine, _, cards = _position(seats=2, cards=("Llanowar Elves",))
    reveals = [e for e in engine.state.event_log if e.type == EventType.REVEAL]
    assert reveals[-1].get("instance_id") == cards[0].instance_id
    assert reveals[-1].get("object") == cards[0].name
    draws_before = sum(e.type == EventType.DRAW for e in engine.state.event_log)
    engine.resolve_pending_choice("decline")
    assert sum(e.type == EventType.DRAW for e in engine.state.event_log) == draws_before


def test_remaining_iteration_uses_original_controller_after_source_leaves():
    engine = _game(seats=3)
    p1, p2, p3 = engine.state.players
    racket = _card(engine, "Protection Racket", player="p2")
    racket.controller_id = "p1"
    p1.library.clear()
    last = _card(engine, "Forest", zone=Zone.LIBRARY)
    first = _card(engine, "Llanowar Elves", zone=Zone.LIBRARY)
    _to(engine, "p1", "upkeep")
    engine.rules.destroy(racket)
    engine.resolve_pending_choice("decline")
    assert first.zone == Zone.HAND
    assert engine.state.pending_choice["player_id"] == p3.id
    assert last.name in engine.state.pending_choice["prompt"]
    engine.resolve_pending_choice("decline")
    assert last in p1.hand and last not in p2.hand
