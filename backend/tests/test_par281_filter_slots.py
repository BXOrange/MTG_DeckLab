"""PAR-281: the filter-slot peeler offers "with <quality>" to a library search whose row never wrote it.

Parse shape, fail-closed refusals, and execution in the real engine (the search offers exactly the cards the
carried quality admits)."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.cards import card_query
from mtg_analyzer.parser.oracle.catalogue.filter_slots import peel_filter_slots, quality_criteria
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, make_engine

_TAIL = ", reveal it, put it into your hand, then shuffle"


def _criteria(noun: str) -> dict:
    specs = match_clause(f"search your library for {noun}{_TAIL}")
    assert specs is not None and [s.type for s in specs] == ["search"], noun
    return specs[0].params["criteria"]


def test_exact_mana_value_is_both_bounds():
    assert _criteria("an artifact card with mana value 2") == {"type": "artifact", "min_mana_value": 2, "max_mana_value": 2}


def test_mana_value_alternatives_are_an_or_of_exact_values():
    crit = _criteria("an artifact card with mana value 4 or 5")
    assert crit["or"] == [{"min_mana_value": 4, "max_mana_value": 4}, {"min_mana_value": 5, "max_mana_value": 5}]


def test_keyword_and_keyword_alternatives():
    assert _criteria("a creature card with defender") == {"type": "creature", "has_keyword": "defender"}
    assert _criteria("a creature card with eternalize or embalm")["or"] == [
        {"has_keyword": "eternalize"}, {"has_keyword": "embalm"}]


def test_power_or_toughness_is_an_either_stat_bound():
    assert _criteria("a creature card with power or toughness 6 or greater")["or"] == [{"min_power": 6}, {"min_toughness": 6}]


@pytest.mark.parametrize("quality", [
    "the same name as that card",                 # dynamic: no card_query key
    "mana value equal to the number of age counters on ~",
    "a mana ability",                              # prose is not a keyword
    "flying and haste",
])
def test_unreadable_quality_is_refused_never_dropped(quality):
    assert quality_criteria(quality) is None
    assert match_clause(f"search your library for a card with {quality}{_TAIL}") is None


def test_second_qualifier_in_the_noun_phrase_is_refused():
    assert match_clause(f"search your library for a creature card with defender with power 2 or less{_TAIL}") is None


def test_quality_colliding_with_a_row_written_key_is_refused():
    shorter = lambda _s: match_clause(f"search your library for a creature card with mana value 3 or less{_TAIL}")
    assert peel_filter_slots(f"search your library for a creature card with mana value 3 or less with mana value 2{_TAIL}", shorter) is None


def test_only_a_carrier_spec_may_take_the_quality():
    # "destroy target creature with defender" is read by its own row; the peeler never rewrites a non-search spec
    assert peel_filter_slots("destroy target creature with wibble", lambda s: match_clause(s)) is None


def test_real_cards_become_modeled():
    db = CardDatabase(DB_PATH)
    for name in ("Micromancer", "Transit Mage", "Shield-Wall Sentinel", "Rootless Yew"):
        card = db.get_card(name)
        assert card is not None and parse_oracle(card).modeled, name


def test_carried_quality_filters_the_real_search():
    crit = _criteria("an artifact card with mana value 4 or 5")
    def artifact(name, cmc):
        return creature(name, cost="{%d}" % cmc, type_line="Artifact")
    pool = [artifact("Three", 3), artifact("Four", 4), artifact("Five", 5), artifact("Six", 6)]
    assert [c.name for c in pool if card_query.matches(c, crit)] == ["Four", "Five"]
    eng = make_engine(pool)
    p1 = eng.state.player_by_id("p1")
    eng.rules._request_search(p1, crit, "hand", count=1)
    choice = eng.state.pending_choice
    assert choice is not None and choice.get("kind") == "search"
    assert sorted(o["name"] for o in choice["eligible"]) == ["Five", "Four"]
