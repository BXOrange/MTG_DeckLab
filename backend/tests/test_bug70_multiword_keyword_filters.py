"""BUG-70: "… with first strike" / "double strike" filters must match.

The shared phrase grammar (`characteristic_phrase.KEYWORD_WORDS`) and several effect rows emit the printed spaced
name; `combat.has` compares the slug `combat._normalize` produces. Every reader of a keyword name now folds either
spelling to the slug, so grammar emitters and hand-authored entries agree.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import parse_object_phrase


def _creature(keywords):
    obj = GameObject(
        Card(id="c", name="Duelist", type_line="Creature — Human", is_creature=True, power=2, toughness=2,
             keywords=list(keywords)),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = "p1"
    return obj


@pytest.mark.parametrize("word", ["first strike", "double strike", "first_strike", "First strike"])
def test_spaced_keyword_filter_matches(word):
    slug = word.lower().replace(" ", "_")
    obj = _creature([slug.replace("_", " ").capitalize()])
    assert combat.matches_object_filter(obj, {"keyword": word})
    assert combat.matches_object_filter(obj, {"keyword_any": ["flying", word]})
    assert not combat.matches_object_filter(obj, {"without_keyword": word})
    assert not combat.matches_object_filter(obj, {"without_keyword": [word, "flying"]})
    assert combat.has(obj, word)


def test_spaced_keyword_filter_rejects_creature_without_it():
    obj = _creature(["Flying"])
    assert not combat.matches_object_filter(obj, {"keyword": "first strike"})
    assert not combat.matches_object_filter(obj, {"keyword_any": ["first strike", "double strike"]})
    assert combat.matches_object_filter(obj, {"without_keyword": "first strike"})


def test_shared_grammar_phrase_matches_a_first_striker():
    parsed = parse_object_phrase("creatures with first strike", plural=True)
    assert parsed is not None
    assert combat.matches_object_filter(_creature(["First strike"]), parsed[0])
    assert not combat.matches_object_filter(_creature(["Flying"]), parsed[0])


def test_spaced_grants_reach_the_combat_readers():
    """Hand-authored grants (Chocobo Knights, Halvar, Kamiz, Valor...) store "double strike"/"first strike" spaced."""
    ds, fs = _creature([]), _creature([])
    ds._granted_keywords.add("double strike")
    fs._granted_keywords.add("first strike")
    assert combat.has_double_strike(ds) and not combat.has_first_strike(ds)
    assert combat.has_first_strike(fs) and not combat.has_double_strike(fs)
    ds.removed_keywords.add("double strike")
    assert combat.has_double_strike(ds)  # a later grant outlives an earlier removal (RULE 613.7a)
    ds._granted_keywords.clear()
    assert not combat.has(ds, "double strike")


def test_spaced_double_strike_grant_deals_damage_in_both_steps():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.game.game_engine import GameEngine

    start_life, power = 20, 2
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=start_life, starting_hand=0)
    eng.start()
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()
    obj = GameObject(Card(id="d", name="Duelist", type_line="Creature — Human", is_creature=True, power=power,
                          toughness=power), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    obj.intrinsic_keywords.add("double strike")  # the spaced spelling a pump grant stores
    eng.declare_attackers(eng.state.player_by_id("p1"), [obj])
    eng.advance_step()
    eng.declare_blockers(eng.state.player_by_id("p2"), [])
    eng.advance_step()
    assert eng.state.player_by_id("p2").life == start_life - power, "first-strike step hit"
    eng.advance_step()
    assert eng.state.player_by_id("p2").life == start_life - 2 * power, "regular step hit"
