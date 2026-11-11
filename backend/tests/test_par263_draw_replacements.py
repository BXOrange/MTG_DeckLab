"""PAR-263: "If you would draw a card, draw N cards instead" (Mr. Spock, Thought Reflection) and the
"except the first one you draw in each of your draw steps" form (Alhammarret's Archive, Teferi's Ageless Insight)."""

from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import game, on_battlefield, stock_library

SPOCK = "Mr. Spock, Science Officer"
ARCHIVE = "Alhammarret's Archive"
LIBRARY = 30


def _hand_after(engine, player, action) -> int:
    before = len(player.hand)
    action()
    return len(player.hand) - before


@pytest.mark.parametrize("name", [SPOCK, "Thought Reflection", ARCHIVE, "Teferi's Ageless Insight", "Vnwxt, Verbose Host"])
def test_cards_parse_modeled(name):
    card = get_cached_card(name)
    assert card is not None
    assert parse_oracle(card).coverage == "MODELED"


def test_spock_doubles_an_effect_draw():
    engine, p1, _p2 = game()
    stock_library(engine, "p1", LIBRARY)
    on_battlefield(engine, "p1", SPOCK)
    assert _hand_after(engine, p1, lambda: engine.rules.draw(p1, 1)) == 2


def test_spock_does_not_touch_the_opponents_draw():
    engine, _p1, p2 = game()
    stock_library(engine, "p2", LIBRARY)
    on_battlefield(engine, "p1", SPOCK)
    assert _hand_after(engine, p2, lambda: engine.rules.draw(p2, 1)) == 1


def test_spock_doubles_each_card_of_a_multi_draw():
    engine, p1, _p2 = game()
    stock_library(engine, "p1", LIBRARY)
    on_battlefield(engine, "p1", SPOCK)
    assert _hand_after(engine, p1, lambda: engine.rules.draw(p1, 2)) == 4


def test_two_spocks_each_apply_once_to_one_draw():
    # RULE 614.5: each replacement applies once; the second acts on the cards the first produced (1 -> 2 -> 4).
    engine, p1, _p2 = game()
    stock_library(engine, "p1", LIBRARY)
    on_battlefield(engine, "p1", SPOCK)
    on_battlefield(engine, "p1", SPOCK)

    def draw_one():
        engine.rules.draw(p1, 1)
        # RULE 616.1e: two applicable replacements, the affected player picks the order.
        assert engine.state.pending_choice["kind"] == "replacement_order"
        engine.rules.resolve_choice("0")
        assert engine.state.pending_choice is None

    assert _hand_after(engine, p1, draw_one) == 4


def test_archive_spares_only_the_first_draw_of_the_draw_step():
    engine, p1, _p2 = game()
    stock_library(engine, "p1", LIBRARY)
    on_battlefield(engine, "p1", ARCHIVE)
    engine.state.current_step = "draw"  # p1's own draw step (RULE 504.1)
    assert _hand_after(engine, p1, lambda: engine.rules.draw(p1, 1)) == 1
    assert _hand_after(engine, p1, lambda: engine.rules.draw(p1, 1)) == 2


def test_archive_doubles_a_draw_outside_the_draw_step():
    engine, p1, _p2 = game()
    stock_library(engine, "p1", LIBRARY)
    on_battlefield(engine, "p1", ARCHIVE)
    assert engine.state.current_step == "main1"
    assert _hand_after(engine, p1, lambda: engine.rules.draw(p1, 1)) == 2


def test_archive_doubles_all_non_step_draws_and_still_doubles_life():
    engine, p1, _p2 = game()
    stock_library(engine, "p1", LIBRARY)
    on_battlefield(engine, "p1", ARCHIVE)
    assert _hand_after(engine, p1, lambda: engine.rules.draw(p1, 3)) == 6
    life = p1.life
    engine.rules.gain_life(p1, 3)
    assert p1.life - life == 6


def test_vnwxt_doubles_draws_only_at_max_speed():
    # "Max speed — If you would draw a card, draw two cards instead." keeps its gate (RULE 702.179e).
    engine, p1, _p2 = game()
    stock_library(engine, "p1", LIBRARY)
    on_battlefield(engine, "p1", "Vnwxt, Verbose Host")
    assert _hand_after(engine, p1, lambda: engine.rules.draw(p1, 1)) == 1
    p1.speed = 4
    assert _hand_after(engine, p1, lambda: engine.rules.draw(p1, 1)) == 2
