"""PAR-285 (v984): "<adjective> permanents <scope>" and "attacking <quality> creatures you control" as a group subject
of keyword grants / losses (RULE 109.5, 611.2c, 702.12 indestructible, 613.1f).

`effect_rows.shared._GROUP` knew "permanents you control" and bare-subtype groups but not "legendary permanents you
control" (Dora Milaje Elite), "nonland permanents your opponents control" (Exterminatus) or "attacking modified
creatures you control" (War Machine, Avenging Arsenal). The shared `parse_count_phrase` reads the quality. Tests run
parser -> binder -> engine on real cards with matching AND non-matching candidates; they fail without the alternation."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_par285_other_group_pumps import _combat_engine
from tests.test_par285_sequential_another_target import _hand, _put, _session

NEW_CARDS = ["Exterminatus", "War Machine, Avenging Arsenal"]


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _body(name: str, type_line: str = "Creature — Bear", oracle: str = "") -> Card:
    return Card(id=name, name=name, type_line=type_line, mana_cost_string="{1}", converted_mana_cost=1,
                is_creature="Creature" in type_line,
                power=2 if "Creature" in type_line else None, toughness=2 if "Creature" in type_line else None,
                oracle_text=oracle)


@pytest.mark.parametrize("name", NEW_CARDS)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True, name


@pytest.mark.parametrize("clause, scope, flt, key, value", [
    ("legendary permanents you control gain indestructible until end of turn",
     "you", {"legendary": True}, "keywords", ["indestructible"]),
    ("nonland permanents your opponents control lose indestructible until end of turn",
     "opponents", {"without_card_type": "land"}, "removed_keywords", ["indestructible"]),
    ("attacking modified creatures you control gain double strike until end of turn",
     "you", {"attacking": True, "card_type": "creature", "modified": True}, "keywords", ["double_strike"]),
])
def test_group_selector_shape(clause, scope, flt, key, value):
    (effect,) = match_clause(clause)
    assert effect.type == "pump" and effect.params[key] == value
    assert effect.params["selector"] == {"zone": "battlefield", "of": scope, "filter": flt}


def test_unknown_quality_word_fails_closed():
    assert match_clause("frobnicated permanents you control gain indestructible until end of turn") is None


def test_exterminatus_strips_indestructible_from_opposing_nonlands_before_the_wrath():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand(state, _real("Exterminatus"))
    mine = _put(state, _body("Mine", oracle="Indestructible"))
    theirs = _put(state, _body("Theirs", oracle="Indestructible"), "p2")
    their_land = _put(state, _body("Their Land", "Land"), "p2")
    p1.mana_pool.add_many({"W": 3, "B": 3, "C": 3})
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()
    # Only the opponent's nonland permanent lost indestructible (RULE 702.12), so only it dies to "destroy all".
    assert mine in state.battlefield
    assert theirs not in state.battlefield
    assert their_land in state.battlefield  # "nonland": the land is neither stripped nor destroyed


def test_war_machine_grants_double_strike_only_to_attacking_modified_creatures_you_control():
    engine, state = _combat_engine()
    p1 = state.player_by_id("p1")
    war_machine = _put(state, _real("War Machine, Avenging Arsenal"))
    modified = _put(state, _body("Modified"))
    modified.counters["+1/+1"] = 1  # RULE 700.9: a counter makes a creature modified
    plain = _put(state, _body("Plain"))
    foreign = _put(state, _body("Foreign"), "p2")
    foreign.counters["+1/+1"] = 1
    engine.declare_attackers(p1, [war_machine, modified, plain])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    has = lambda o: "double_strike" in o.granted_keywords
    assert [has(o) for o in (war_machine, modified, plain, foreign)] == [False, True, False, False]

