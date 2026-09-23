"""Secrets of Strixhaven — playability batch, wave 16.

Wave 16 (PARSER_VERSION 291 -> 292): "**this spell costs {N} less to cast
for each <type> card in your graveyard**" — new
`static_handlers._SELF_COST_REDUCTION_GY_RE` emits ``affects="self"`` + a
`per` graveyard-count selector `continuous.count_selector` already resolves,
plus a new `instant_or_sorcery_cards_in_your_graveyard` selector for the one
compound real cards print. Single-type / "instant and sorcery" only.
Narrows Furygale Flocking (Prismari deck) to a single remaining clause.

PAR-120 (PARSER_VERSION 467) retired the rest of `_GY_COST_COUNT_SELECTORS`
in favour of the shared `count_phrase` grammar (`_gy_cost_selector`) —
"instant and sorcery" is the one entry left, since "and" meaning a union of
two mutually-exclusive card types is a real but narrow oracle-text idiom the
grammar's own "or"/same-object-conjunction shapes don't cover. Every single
type word, plus any subtype the grammar already recognizes generically
(a "cave card" — RULE 400.1 — now parses too), reaches a structured
selector instead of a named string.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


@pytest.mark.parametrize("word,selector", [
    ("creature", {"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"}}),
    ("land", {"zone": "graveyard", "of": "you", "filter": {"card_type": "land"}}),
    ("instant", {"zone": "graveyard", "of": "you", "filter": {"card_type": "instant"}}),
    ("instant and sorcery", "instant_or_sorcery_cards_in_your_graveyard"),
])
def test_gy_cost_reduction_claimed(word, selector):
    specs = static_effect_specs(
        f"this spell costs {{1}} less to cast for each {word} card in your graveyard")
    assert specs is not None
    assert specs[0].type == "cost_reduction"
    assert specs[0].params == {"affects": "self", "generic": 1, "per": selector}


def test_a_subtype_now_parses_via_the_shared_grammar():
    # PAR-120: "cave card" used to be a different, unwired selector — the
    # shared noun-phrase grammar reaches any subtype it knows generically.
    specs = static_effect_specs(
        "this spell costs {1} less to cast for each cave card in your graveyard")
    assert specs is not None
    assert specs[0].params["per"] == {
        "zone": "graveyard", "of": "you", "filter": {"subtype": "cave"},
    }


def test_unmodeled_filters_stay_fail_closed():
    # A *compound* filter ("artifact and/or creature") the shared grammar
    # doesn't express — a genuinely different, unwired selector.
    assert static_effect_specs(
        "this spell costs {1} less to cast for each artifact and/or creature card "
        "in your graveyard"
    ) is None


@pytest.mark.parametrize("name", [
    "Ghoultree", "Molderhulk", "Cryptic Serpent", "Tolarian Terror", "Ore-Scale Guardian",
])
def test_real_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed


def test_instant_or_sorcery_gy_selector_counts():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    for i in range(3):
        o = GameObject(card=Card(id=f"g{i}", name=f"Bolt{i}", type_line="Instant",
                                 is_instant=True),
                       owner_id=p1.id, zone=Zone.GRAVEYARD)
        o.zone = Zone.GRAVEYARD
        p1.graveyard.append(o)
    z = GameObject(card=Card(id="z", name="Z", type_line="Creature — Zombie", is_creature=True),
                   owner_id=p1.id, zone=Zone.GRAVEYARD)
    z.zone = Zone.GRAVEYARD
    p1.graveyard.append(z)
    assert continuous.count_selector(
        eng.state, p1.id, "instant_or_sorcery_cards_in_your_graveyard", None) == 3
