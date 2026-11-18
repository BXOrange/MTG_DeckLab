"""PAR-285 (v982): a library search whose mana-value bound is a *measured* amount (RULE 701.19a, 202.3).

"search your library for a black card with mana value less than or equal to the number of creature cards in your
graveyard" (Mausoleum Secrets), "... to your devotion to black" (Grim Servant), "... equal to the number of verse
counters on ~" (Yisan, the Wanderer Bard) map onto `search`'s ``mana_value_from`` (``count_selector`` source), evaluated
live when the search opens. Cost-recorded referents (the sacrificed / discarded card, MEC-145) stay unclaimed.
Tests run parser -> binder -> engine over a stocked library, with matching AND non-matching candidates. Each behaviour
test fails when `SearchLibraryEffect._resolved_criteria` stops reading the bound (the whole library is then eligible)."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_par285_sequential_another_target import _card, _put, _session

NEW_CARDS = ["Mausoleum Secrets", "Grim Servant", "Yisan, the Wanderer Bard"]


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _search_specs(name: str):
    result = parse_oracle(_real(name))
    assert result.modeled is True, name
    return [e.to_dict() for ab in result.specs if ab.effects for e in ab.effects if e.type == "search"]


def _lib(name, type_line, mv, cost):
    card = _card(name, type_line)
    card.converted_mana_cost = mv
    card.mana_cost_string = cost  # RULE 202.2: colour is read off the mana cost
    return card


def _stock(state, cards):
    player = state.player_by_id("p1")
    player.library.clear()
    for card in cards:
        player.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))


def _eligible(state, engine, source, name):
    specs = _search_specs(name)
    assert len(specs) == 1
    engine.rules._apply_effect_specs(specs, source, [])
    return {e["name"] for e in state.pending_choice["eligible"]}


@pytest.mark.parametrize("name", NEW_CARDS)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


def test_parse_shape_and_adversaries():
    (spec,) = match_clause(
        "search your library for a creature card with mana value equal to the number of verse counters on ~, "
        "put it onto the battlefield, then shuffle")
    assert spec.params["mana_value_from"] == {
        "source": "count_selector", "count_selector": {"counters_on": "source", "kind": "verse"}, "cmp": "eq"}
    # cost-recorded referents belong to MEC-145; an unmeasurable amount is not guessed
    for text in (
        "search your library for a creature card with mana value equal to the discarded card's mana value, put it into your hand, then shuffle",
        "search your library for a creature card with mana value less than or equal to the number of frobs on ~, put it into your hand, then shuffle",
    ):
        assert match_clause(text) is None
    # a plain literal bound keeps its own (unchanged) reading
    (literal,) = match_clause("search your library for a creature card with mana value 3 or less, put it into your hand, then shuffle")
    assert "mana_value_from" not in literal.params and literal.params["criteria"]["max_mana_value"] == 3


def test_mausoleum_secrets_bound_is_the_graveyards_creature_count():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    for i in range(2):  # two creature cards, one non-creature: the count is 2
        p1.graveyard.append(GameObject(_card(f"Dead{i}", "Creature — Bear"), owner_id="p1", zone=Zone.GRAVEYARD))
    p1.graveyard.append(GameObject(_card("Spent", "Instant"), owner_id="p1", zone=Zone.GRAVEYARD))
    _stock(state, [
        _lib("Black Two", "Creature — Bear", 2, "{1}{B}"),
        _lib("Black One", "Creature — Bear", 1, "{B}"),
        _lib("Black Three", "Creature — Bear", 3, "{2}{B}"),
        _lib("Red Two", "Creature — Bear", 2, "{1}{R}"),
    ])
    source = _put(state, _card("Source", "Creature — Bear"))
    assert _eligible(state, engine, source, "Mausoleum Secrets") == {"Black Two", "Black One"}


def test_mausoleum_secrets_bound_follows_the_graveyard_live():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    p1.graveyard.clear()  # no creature cards: only mana value 0 qualifies
    _stock(state, [_lib("Black One", "Creature — Bear", 1, "{B}"), _lib("Black Zero", "Creature — Bear", 0, "{B}")])
    source = _put(state, _card("Source", "Creature — Bear"))
    assert _eligible(state, engine, source, "Mausoleum Secrets") == {"Black Zero"}


def test_grim_servant_bound_is_the_black_devotion():
    _, engine, state = _session()
    servant = _put(state, _real("Grim Servant"), "p1")  # {3}{B}: one black symbol
    pip = _card("Pip", "Creature — Bear")
    pip.mana_cost_string = "{B}{B}"
    _put(state, pip, "p1")  # devotion to black = 1 + 2
    _put(state, _card("Foe", "Creature — Bear"), "p2").card.mana_cost_string = "{B}{B}{B}"  # not yours: not counted
    _stock(state, [
        _lib("Three", "Creature — Bear", 3, "{2}{G}"),
        _lib("Two", "Creature — Bear", 2, "{1}{G}"),
        _lib("Four", "Creature — Bear", 4, "{3}{G}"),
    ])
    assert _eligible(state, engine, servant, "Grim Servant") == {"Three", "Two"}


def test_yisan_finds_exactly_the_verse_counter_mana_value():
    _, engine, state = _session()
    yisan = _put(state, _real("Yisan, the Wanderer Bard"), "p1")
    yisan.counters["verse"] = 2
    _stock(state, [
        _lib("Two", "Creature — Bear", 2, "{1}{G}"),
        _lib("One", "Creature — Bear", 1, "{G}"),
        _lib("Three", "Creature — Bear", 3, "{2}{G}"),
        _lib("Two Spell", "Sorcery", 2, "{1}{G}"),
    ])
    assert _eligible(state, engine, yisan, "Yisan, the Wanderer Bard") == {"Two"}
