"""Hand-authored cards of the saved "Hydranten" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from tests.support.catalogue import battlefield_object, two_player_game


def _vigor_game():
    engine, player = two_player_game()
    vigor = battlefield_object(engine, "p1", "Primal Vigor", "Enchantment")
    bind_from_catalogue(vigor)
    return engine


def test_primal_vigor_doubles_every_players_tokens_and_plus_one_counters_on_any_creature():
    engine = _vigor_game()
    token = Card(id="Soldier", name="Soldier", type_line="Token Creature — Soldier", is_creature=True, power=1, toughness=1)
    assert len(engine.rules.create_token("p1", token, count=2)) == 4  # mine
    assert len(engine.rules.create_token("p2", token, count=1)) == 2  # an opponent's too

    mine = battlefield_object(engine, "p1", "My Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    engine.rules.add_counters(mine, 1, "+1/+1")
    engine.rules.add_counters(theirs, 2, "+1/+1")
    assert mine.counters["+1/+1"] == 2 and theirs.counters["+1/+1"] == 4

    engine.rules.add_counters(mine, 1, "-1/-1")  # other counter kinds are not doubled
    assert mine.counters["-1/-1"] == 1
