"""PAR-285: supertype / negated-type qualifiers in a library search's noun phrase (RULE 701.19a, 205.4).

"search your library for a legendary creature card" / "a nonland card" / "a nonlegendary green creature card with mana
value 3 or less" used to leave the clause unclaimed (the criteria grammar knew only colour, basic, subtype and type
words). The qualifier now maps onto `card_query`'s `all_types` / `nonlegendary` / `without_type` keys. Tests run
parser -> binder -> engine: the real cards' specs open a real search choice over a stocked library."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_par285_sequential_another_target import _card, _put, _session


def _real_card(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _search_effects(name: str):
    result = parse_oracle(_real_card(name))
    assert result.modeled is True, name
    return [e for ab in result.specs if ab.effects for e in ab.effects if e.type == "search"]


def _library_card(name, type_line, mv=1, color=None):
    card = _card(name, type_line)
    card.converted_mana_cost = mv
    if color:
        card.mana_cost_string = "{%s}" % color  # RULE 202.2: a card's colour is read from its mana cost
    return card


def _stock(state, cards):
    player = state.player_by_id("p1")
    player.library.clear()
    for card in cards:
        player.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))


def _eligible(name, library, source_name, source_type="Creature — Bear"):
    _, engine, state = _session()
    source = _put(state, _card(source_name, source_type))
    _stock(state, library)
    specs = _search_effects(name)
    assert specs
    engine.rules._apply_effect_specs([e.to_dict() for e in specs], source, [])
    return {e["name"] for e in state.pending_choice["eligible"]}


def test_qualifier_words_map_onto_card_query_keys():
    (legend,) = match_clause("search your library for a legendary creature card, reveal it, put it into your hand, then shuffle")
    assert legend.params["criteria"] == {"type": "creature", "all_types": ["legendary"]}
    (nonland,) = match_clause("search your library for a nonland card, reveal it, put it into your hand, then shuffle")
    assert nonland.params["criteria"] == {"without_type": ["land"]}
    (combo,) = match_clause(
        "search your library for a nonlegendary green creature card with mana value 3 or less, put it onto the battlefield, then shuffle")
    assert combo.params["criteria"]["nonlegendary"] is True and combo.params["criteria"]["max_mana_value"] == 3


def test_unlisted_qualifier_stays_unclaimed():
    assert match_clause("search your library for a nonbasic land card, put it into your hand, then shuffle") is None


@pytest.mark.parametrize("name", ["Lifespinner", "Thalia's Lancers", "The Seriema", "Time of Need",
                                  "War of the Last Alliance", "Woodland Bellower"])
def test_real_cards_are_modeled(name):
    assert _search_effects(name)


def test_time_of_need_offers_only_legendary_creatures():
    eligible = _eligible("Time of Need", [
        _library_card("Plain Bear", "Creature — Bear"),
        _library_card("Legend Bear", "Legendary Creature — Bear"),
        _library_card("Legend Relic", "Legendary Artifact"),
    ], "Source")
    assert eligible == {"Legend Bear"}


def test_lifespinner_legendary_spirit_permanent_requires_both_words():
    eligible = _eligible("Lifespinner", [
        _library_card("Mere Spirit", "Creature — Spirit"),
        _library_card("Legend Spirit", "Legendary Creature — Spirit"),
        _library_card("Legend Bear", "Legendary Creature — Bear"),
    ], "Lifespinner", "Creature — Spirit")
    assert eligible == {"Legend Spirit"}


def test_woodland_bellower_nonlegendary_green_creature_with_mv_bound():
    eligible = _eligible("Woodland Bellower", [
        _library_card("Ok Elf", "Creature — Elf", mv=3, color="G"),
        _library_card("Legend Elf", "Legendary Creature — Elf", mv=3, color="G"),
        _library_card("Big Elf", "Creature — Elf", mv=4, color="G"),
        _library_card("Red Elf", "Creature — Elf", mv=2, color="R"),
    ], "Woodland Bellower", "Creature — Elf")
    assert eligible == {"Ok Elf"}


def test_nonland_qualifier_excludes_lands():
    # No real card in the cache is solo-blocked on bare "nonland", so drive the same parsed spec through the engine.
    _, engine, state = _session()
    source = _put(state, _card("Source", "Creature — Bear"))
    _stock(state, [_library_card("Forest", "Basic Land — Forest"), _library_card("Rock", "Artifact")])
    (spec,) = match_clause("search your library for a nonland card, reveal it, put it into your hand, then shuffle")
    engine.rules._apply_effect_specs([spec.to_dict()], source, [])
    assert {e["name"] for e in state.pending_choice["eligible"]} == {"Rock"}
