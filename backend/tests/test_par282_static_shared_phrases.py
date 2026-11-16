"""PAR-282: the static rows' blocker/count operands read through the shared `characteristic_phrase` grammar."""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_rows.object_scope import object_filter
from mtg_analyzer.parser.oracle.catalogue.static_rows.static_conditions import parse_combat_condition
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, type_line, text="", keywords=None, **kw):
    return Card(id=name[:6], name=name, type_line=type_line, oracle_text=text, keywords=keywords or [],
                is_creature="Creature" in type_line, **kw)


def _bf(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    eng.state.add_to_battlefield(obj)
    return obj


@pytest.mark.parametrize("phrase,expected", [
    ("creatures with power 2 or less", {"card_type": "creature", "max_power": 2}),
    ("creatures with flying or reach", {"card_type": "creature", "keyword_any": ["flying", "reach"]}),
    ("creatures with first strike", {"card_type": "creature", "keyword": "first_strike"}),
    ("creatures with flanking", {"card_type": "creature", "keyword": "flanking"}),
    ("creatures with mana value 3 or less", {"card_type": "creature", "max_mana_value": 3}),
    ("black and/or red creatures", {"color_any": ["B", "R"], "card_type": "creature"}),
    ("knight or a soldier", {"any_of": [{"subtype": "knight"}, {"subtype": "soldier"}]}),
    ("creature tokens", {"token": True, "card_type": "creature"}),
])
def test_object_filter_reads_through_the_shared_grammar(phrase, expected):
    assert object_filter(phrase) == expected


@pytest.mark.parametrize("phrase", ["black", "creatures you control", "creatures with fnord"])
def test_object_filter_refuses_a_bare_adjective_a_controller_tail_and_unknown_words(phrase):
    assert object_filter(phrase) is None


def test_reference_power_filters_stay_dynamic():
    assert object_filter("creatures with greater power") == {"power_vs_reference": "greater"}


def test_spelled_numbers_up_to_ten_fold_in_a_combat_condition():
    cond = parse_combat_condition("you control eight or more creatures")
    assert cond == {"kind": "you_control", "min": 8, "filter": {"card_type": "creature"}}


@pytest.mark.parametrize("name", [
    "Sacred Knight", "Rubblebelt Runner", "Duskwatch Hunter", "Orcish Veteran", "War Falcon", "Hero of the Dunes", "Oko, the Ringleader", "Knight of Valor", "Telim'Tor",
])
def test_real_cards_gained_by_the_shared_grammar_are_modeled(name):
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    assert parse_oracle(card).modeled is True


def test_sacred_knight_restriction_executes_against_black_and_red_but_not_white_blockers():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    knight = _bf(eng, _card("Sacred Knight", "Creature — Human Knight", power=3, toughness=2))
    spec = EffectSpec("combat_restriction", {
        "kind": "cant_be_blocked_by", "filter": object_filter("black and/or red creatures"), "affects": "self",
    })
    filt = spec.params["filter"]
    blockers = {}
    for name, color in (("Black", "B"), ("Red", "R"), ("White", "W")):
        blockers[name] = _bf(eng, _card(name, "Creature — Bear", power=2, toughness=2), "p2")
        blockers[name]._derived_colors = {color}
    assert combat.matches_object_filter(blockers["Black"], filt)
    assert combat.matches_object_filter(blockers["Red"], filt)
    assert not combat.matches_object_filter(blockers["White"], filt)
