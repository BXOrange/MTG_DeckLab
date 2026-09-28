"""PAR-120 (e): "Reveal the first card you draw each turn. Whenever you
reveal a `<type>` card this way, …" — the first-draw trigger gated on the
`first_drawn_this_turn` referent's type (Primitive Etchings, Rowen)."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle

ETCHINGS = ("Reveal the first card you draw each turn. Whenever you reveal a creature card "
            "this way, draw a card.")
ROWEN = ("Reveal the first card you draw each turn. Whenever you reveal a basic land card "
         "this way, draw a card.")

BEAR = Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True,
            power=2, toughness=2)
FOREST = Card(id="forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
DUNES = Card(id="dunes", name="Dunes", type_line="Land — Desert", is_land=True)


def _game(oracle, top_cards):
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    player = state.player_by_id("p1")
    filler = [Card(id=f"f{n}", name=f"Filler {n}", type_line="Sorcery", is_sorcery=True)
              for n in range(3)]
    # `library[-1]` is the top card.
    for card in [*filler, *reversed(top_cards)]:
        player.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))
    card = Card(id="src", name="Source", type_line="Enchantment",
                oracle_text=oracle)
    assert parse_oracle(card).modeled
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.controller_id = "p1"
    state.add_to_battlefield(source)
    bind_from_catalogue(source)
    return engine, player


def _draw(engine, player):
    engine.rules.draw(player, 1)
    while engine.rules.put_triggers_on_stack() or engine.state.stack:
        engine.rules.resolve_top_of_stack()


@pytest.mark.parametrize("oracle, first, extra", [
    (ETCHINGS, BEAR, True),
    (ETCHINGS, FOREST, False),
    (ROWEN, FOREST, True),
    (ROWEN, DUNES, False),  # a land, but not basic
])
def test_first_draw_reveal_draws_only_for_the_named_type(oracle, first, extra):
    engine, player = _game(oracle, [first, BEAR])
    _draw(engine, player)
    assert len(player.hand) == (2 if extra else 1)


def test_a_later_draw_of_the_type_does_not_trigger():
    engine, player = _game(ETCHINGS, [FOREST, BEAR, BEAR])
    _draw(engine, player)
    _draw(engine, player)
    assert len(player.hand) == 2
