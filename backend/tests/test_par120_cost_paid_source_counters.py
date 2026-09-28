"""PAR-120 (d): an activated ability whose cost exiles or sacrifices its own
source still counts the counters it had (RULE 608.2h last-known information)
— "draw a card for each verse counter on ~. If it had seven or more …"
(Lost Isle Calling), "draw a card for each charge counter on ~" (Culling Dais)."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle


def _board(card, counter, n, library=10):
    assert parse_oracle(card).modeled
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    engine.begin_turn()
    state = engine.state
    state.current_step = "main1"
    player = state.player_by_id("p1")
    for i in range(library):
        player.library.append(GameObject(Card(id=f"l{i}", name="Land", type_line="Land"),
                                         owner_id="p1", zone=Zone.LIBRARY))
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.controller_id = "p1"
    source.counters[counter] = n
    state.add_to_battlefield(source)
    bind_from_catalogue(source)
    return engine, state, player, source


def _activate_last(engine, player, source):
    engine.activate_ability(player, source, len(source.activated_abilities) - 1)
    engine.rules.resolve_top_of_stack()


LOST_ISLE = Card(
    id="lost-isle", name="Lost Isle Calling", type_line="Enchantment",
    oracle_text=("Whenever you scry, put a verse counter on Lost Isle Calling.\n{4}{U}{U}, Exile "
                 "Lost Isle Calling: Draw a card for each verse counter on Lost Isle Calling. If it "
                 "had seven or more verse counters on it, take an extra turn after this one. "
                 "Activate only as a sorcery."))


@pytest.mark.parametrize("verses, extra_turn", [(7, True), (3, False)])
def test_lost_isle_calling_counts_the_verses_it_had_when_exiled(verses, extra_turn):
    engine, state, player, isle = _board(LOST_ISLE, "verse", verses)
    player.mana_pool.add("U", 2)
    player.mana_pool.add("C", 4)
    _activate_last(engine, player, isle)
    assert isle.zone == Zone.EXILE
    assert len(player.hand) == verses
    assert (state.extra_turns == ["p1"]) is extra_turn


def test_culling_dais_draws_for_the_charge_counters_it_was_sacrificed_with():
    card = Card(id="dais", name="Culling Dais", type_line="Artifact",
                oracle_text=("{T}, Sacrifice a creature: Put a charge counter on Culling Dais.\n"
                             "{1}, Sacrifice Culling Dais: Draw a card for each charge counter on "
                             "Culling Dais."))
    engine, state, player, dais = _board(card, "charge", 3)
    player.mana_pool.add("C", 1)
    _activate_last(engine, player, dais)
    assert dais.zone == Zone.GRAVEYARD
    assert len(player.hand) == 3
