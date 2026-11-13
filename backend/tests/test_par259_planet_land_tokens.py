"""PAR-259: Planet land tokens ("create a tapped Planet land token named New Planet with ...") and the
"basic land card or Planet card" search, parsed and executed on a real engine."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import match_clause
from mtg_analyzer.game.mana_abilities import mana_abilities_for
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import cast, game, on_battlefield, stock_library, vanilla

#: Real cached cards this ticket makes MODELED through the parser alone.
PARSER_MODELED = (
    "Artificial Anomaly", "Gaseous Anomaly", "Spatial Anomaly", "Subspace Anomaly",
    "David and Carol Marcus, Creators", "Genesis Effect", "Saurian Explorer", "Stable Wormhole",
)

TOKEN_CLAUSE = 'create a tapped planet land token named new planet with "{t}: add 1 mana of any color."'
SEARCH_CLAUSE = "search your library for a basic land card or planet card, put it onto the battlefield tapped, then shuffle"


@pytest.mark.parametrize("name", PARSER_MODELED)
def test_card_is_modeled(name):
    card = get_cached_card(name)
    assert card is not None and parse_oracle(card).modeled, name


def test_token_clause_emits_land_token_spec():
    [spec] = match_clause(TOKEN_CLAUSE)
    assert spec.type == "create_token"
    assert spec.params["is_land"] and spec.params["tapped"] and spec.params["token_name"] == "New Planet"
    assert spec.params["subtypes"] == ["Planet"]


@pytest.mark.parametrize("clause", [
    'create a tapped planet land token named new planet with "{t}: draw a card."',  # not a mana ability
    'create a tapped planet land token named new planet',  # no ability
    'create a tapped moon land token named new planet with "{t}: add 1 mana of any color."',  # unknown subtype
])
def test_adversarial_land_token_clauses_stay_unclaimed(clause):
    assert match_clause(clause) is None


def _new_planet(engine):
    tokens = [o for o in engine.state.battlefield if o.is_token and o.name == "New Planet"]
    assert len(tokens) == 1
    return tokens[0]


def _assert_untapped_planet_taps_for_any_color(engine, p1, token):
    assert token.is_land and not token.is_creature  # RULE 111.10: a land token, never a creature
    assert "Planet" in token.card.type_line and token.controller_id == "p1"
    assert token.tapped  # RULE 110.5a: it entered tapped
    token.tapped = False
    abilities = mana_abilities_for(token, state=engine.state)
    assert len(abilities) == 1 and {next(iter(o)) for o in abilities[0].options} == set("WUBRG")  # RULE 605.1a
    produced = engine.tap_for_mana(p1, token, option_index=3)
    assert token.tapped and produced == {"R": 1}


def test_david_and_carol_marcus_makes_a_tapped_planet_that_taps_for_any_color():
    engine, p1, _ = game("David and Carol Marcus, Creators")
    cast(engine, p1, p1.hand[0])
    _assert_untapped_planet_taps_for_any_color(engine, p1, _new_planet(engine))


def test_anomaly_sacrifices_itself_applies_its_effect_then_makes_the_planet():
    engine, p1, p2 = game()
    anomaly = on_battlefield(engine, "p1", "Artificial Anomaly")
    p1.mana_pool.add_many({"B": 1, "C": 3})
    engine.activate_ability(p1, anomaly, 0)
    engine.resolve_until_stable()
    assert anomaly not in engine.state.battlefield  # sacrificed as a cost
    assert (p2.life, p1.life) == (18, 22)
    _assert_untapped_planet_taps_for_any_color(engine, p1, _new_planet(engine))


def _library_card(name, type_line, **flags):
    return Card(id=name, name=name, type_line=type_line, **flags)


def test_search_finds_basic_and_planet_but_not_other_nonbasic_lands():
    library = [
        _library_card("Forest", "Basic Land — Forest", is_land=True),
        _library_card("New Planet", "Land — Planet", is_land=True),
        _library_card("Command Tower", "Land", is_land=True),
        _library_card("Llanowar Elves", "Creature — Elf Druid", is_creature=True, power=1, toughness=1),
    ]
    engine = GameEngine.new_game([("p1", "Alice", library)], starting_hand=0)
    [spec] = match_clause(SEARCH_CLAUSE)
    assert spec.type == "search" and spec.params["destination"] == "battlefield_tapped"
    EffectRegistry.create(spec.type, spec.params).apply(engine.rules.context)
    choice = engine.state.pending_choice
    assert {e["name"] for e in choice["eligible"]} == {"Forest", "New Planet"}
    picked = next(e for e in choice["eligible"] if e["name"] == "New Planet")["instance_id"]
    engine.rules.resolve_choice(picked)
    found = engine.state.find_object(picked)
    assert found in engine.state.battlefield and found.tapped


def test_gaseous_anomaly_draws_two_then_makes_the_planet():
    engine, p1, _ = game()
    anomaly = on_battlefield(engine, "p1", "Gaseous Anomaly")
    stock_library(engine, "p1", 3)
    p1.mana_pool.add_many({"U": 1, "C": 5})
    engine.activate_ability(p1, anomaly, 0)
    engine.resolve_until_stable()
    assert len(p1.hand) == 2 and anomaly not in engine.state.battlefield
    _assert_untapped_planet_taps_for_any_color(engine, p1, _new_planet(engine))


def test_spatial_anomaly_damages_a_creature_then_makes_the_planet():
    engine, p1, p2 = game()
    anomaly = on_battlefield(engine, "p1", "Spatial Anomaly")
    victim = vanilla(engine, "p2", toughness=2)
    p1.mana_pool.add_many({"R": 1, "C": 4})
    engine.activate_ability(p1, anomaly, 0, targets=[victim])
    engine.resolve_until_stable()
    assert victim not in engine.state.battlefield
    _assert_untapped_planet_taps_for_any_color(engine, p1, _new_planet(engine))


def test_subspace_anomaly_makes_two_officers_and_the_planet():
    engine, p1, _ = game()
    anomaly = on_battlefield(engine, "p1", "Subspace Anomaly")
    p1.mana_pool.add_many({"W": 1, "C": 4})
    engine.activate_ability(p1, anomaly, 0)
    engine.resolve_until_stable()
    officers = [o for o in engine.state.battlefield if o.is_token and o.is_creature]
    assert len(officers) == 2
    _assert_untapped_planet_taps_for_any_color(engine, p1, _new_planet(engine))


def test_saurian_explorer_pays_six_for_a_planet_at_sorcery_speed():
    engine, p1, _ = game()
    explorer = on_battlefield(engine, "p1", "Saurian Explorer")
    p1.mana_pool.add_many({"C": 6})
    engine.activate_ability(p1, explorer, 0)
    engine.resolve_until_stable()
    _assert_untapped_planet_taps_for_any_color(engine, p1, _new_planet(engine))


def test_stable_wormhole_makes_a_planet_whenever_you_attack():
    engine, p1, _ = game(via_steps=True)
    on_battlefield(engine, "p1", "Stable Wormhole")
    bear = vanilla(engine, "p1")
    while engine.state.current_step != "declare_attackers":
        engine.advance_step()
    engine.declare_attackers(p1, [{"attacker": bear, "defender": engine.legal_defenders_for(p1)[0]}])
    engine._fire_player_attacked_events()  # what the turn loop does once attackers are declared (RULE 506.4)
    engine.resolve_until_stable()
    _assert_untapped_planet_taps_for_any_color(engine, p1, _new_planet(engine))


def test_genesis_effect_burns_a_creature_destroys_a_land_and_makes_the_planet():
    engine, p1, _ = game("Genesis Effect")
    victim = vanilla(engine, "p2", toughness=2)
    land = GameObject(Card(id="Plains", name="Plains", type_line="Basic Land — Plains", is_land=True),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    land.controller_id = "p1"
    engine.state.add_to_battlefield(land)
    engine.recompute_continuous_effects()
    cast(engine, p1, p1.hand[0], targets=[victim, land])
    assert victim not in engine.state.battlefield and land not in engine.state.battlefield
    _assert_untapped_planet_taps_for_any_color(engine, p1, _new_planet(engine))
