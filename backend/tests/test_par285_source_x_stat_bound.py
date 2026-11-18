"""PAR-285: "target creature with power/toughness X or less" -- X is the source's announced {X} (RULE 107.3).

Parse shape (both grammars: the shared target quality tail and the creature-quality suffix), the adversarial
"X or greater" refusal, the targeting predicate in a real engine, and real-card end-to-end verdicts."""

from __future__ import annotations

import pytest

from mtg_analyzer.game import targeting
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.config import DB_PATH
from tests.support.game import creature, make_engine, obj_on_battlefield


@pytest.mark.parametrize("clause,verb,key", [
    ("destroy target creature with power x or less", "destroy", "max_power_from_source_x"),
    ("tap target creature with power x or less", "tap", "max_power_from_source_x"),
    ("destroy target creature with toughness x or less", "destroy", "max_toughness_from_source_x"),
    ("exile target creature with toughness x or less", "exile", "max_toughness_from_source_x"),
])
def test_x_stat_bound_parses_as_source_x_filter(clause, verb, key):
    specs = match_clause(clause)
    assert specs is not None and [s.type for s in specs] == [verb]
    assert specs[0].params["creature_filter"][key] is True


@pytest.mark.parametrize("clause", [
    "destroy target creature with power x or greater",
    "tap target creature with toughness x or greater",
])
def test_x_or_greater_is_not_claimed(clause):
    assert match_clause(clause) is None


def test_targeting_reads_stat_against_announced_x():
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, creature("Source"), "p1")
    source.x_paid = 3
    big_toughness = obj_on_battlefield(state, engine, creature("Wall", power=1, toughness=5), "p2")
    big_power = obj_on_battlefield(state, engine, creature("Ogre", power=4, toughness=1), "p2")
    small = obj_on_battlefield(state, engine, creature("Elf", power=1, toughness=3), "p2")

    def ok(obj, filt):
        return targeting._creature_matches_filter(obj, filt, reference=source, state=state, controller_id="p1")

    power_filt = {"max_power_from_source_x": True}
    assert ok(small, power_filt) and ok(big_toughness, power_filt) and not ok(big_power, power_filt)
    tough_filt = {"max_toughness_from_source_x": True}
    assert ok(small, tough_filt) and ok(big_power, tough_filt) and not ok(big_toughness, tough_filt)
    assert not targeting._creature_matches_filter(small, power_filt, reference=None, state=state)


@pytest.mark.parametrize("name", ["Gang Up", "Killing Glare", "Entrancing Lyre"])
def test_real_cards_are_modeled(name):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    assert parse_oracle(card).modeled is True
