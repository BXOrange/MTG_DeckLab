"""Secrets of Strixhaven — playability batch, wave 17.

Wave 17 (PARSER_VERSION 292 -> 293): 'create a … creature token with
"when ~ dies, you gain N life."' — the STX Pest token's own printed death
trigger. The inline-create-token regex gained a quoted-ability tail
alternative; `CreateTokenEffect.token_dies_gain_life` binds a
``dies`` -> ``gain_life`` `TriggeredAbility` onto each created token (the
triggered-ability sibling of ``grant_self_anthem``).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


@pytest.mark.parametrize("clause", [
    'create a 1/1 black and green pest creature token with "when ~ dies, you gain 1 life."',
    'create a 1/1 black and green pest creature token with "when it dies, you gain 1 life"',
])
def test_pest_token_death_trigger_claimed(clause):
    specs = match_clause(clause)
    assert [s.type for s in specs] == ["create_token"]
    p = specs[0].params
    assert p["token_dies_gain_life"] == 1
    assert p["subtypes"] == ["Pest"]
    assert p["power"] == 1 and p["toughness"] == 1


def test_plain_keyword_token_unchanged():
    specs = match_clause("create a 2/2 black zombie creature token with menace")
    assert specs[0].params["keywords"] == ["menace"]
    assert "token_dies_gain_life" not in specs[0].params


@pytest.mark.parametrize("name", ["Hunt for Specimens", "Professor of Zoomancy"])
def test_real_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed


def test_pest_token_gets_bound_death_trigger():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(card=Card(id="s", name="Hunt", type_line="Sorcery", is_sorcery=True),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    eff = EffectRegistry.create("create_token", {
        "power": 1, "toughness": 1, "colors": ["B", "G"], "subtypes": ["Pest"],
        "token_name": "Pest", "token_dies_gain_life": 1})
    eff.source = src
    eff.apply(eng.rules.context)
    tok = next(o for o in eng.state.battlefield if o.is_token)
    assert len(tok.triggered_abilities) == 1
    assert tok.triggered_abilities[0].trigger_event == "DIES"


def test_pest_token_death_trigger_fires_at_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(card=Card(id="s", name="Hunt", type_line="Sorcery", is_sorcery=True),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    eff = EffectRegistry.create("create_token", {
        "power": 1, "toughness": 1, "colors": ["B", "G"], "subtypes": ["Pest"],
        "token_name": "Pest", "token_dies_gain_life": 1})
    eff.source = src
    eff.apply(eng.rules.context)
    tok = next(o for o in eng.state.battlefield if o.is_token)
    before = p1.life
    eng.rules.destroy(tok)
    eng.resolve_until_stable()
    assert p1.life - before == 1
