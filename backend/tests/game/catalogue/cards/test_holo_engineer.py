"""Holo-Engineer: every token you would create becomes the same number of 3/3 colorless Illusion artifact creatures."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.token_database import synthesize_token_card
from tests.support.star_trek import cast, game

NAME = "Holo-Engineer"
ORACLE = (
    "When this creature enters, create a 3/3 colorless Illusion artifact creature token.\n"
    "If one or more tokens would be created under your control, that many 3/3 colorless Illusion artifact creature "
    "tokens are created instead."
)
ILLUSION_SIZE = 3


def _holo():
    return Card(id="holo", name=NAME, type_line="Creature — Human Artificer", is_creature=True, power=3,
                toughness=3, mana_cost_string="{2}{G}{G}", converted_mana_cost=4, oracle_text=ORACLE)


def _put(engine, card, zone, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def _board(holos=1):
    engine, p1, p2 = game()
    for _ in range(holos):
        _put(engine, _holo(), Zone.BATTLEFIELD)
    return engine, p1, p2


def _tokens(engine):
    return [o for o in engine.state.battlefield if o.is_token]


def _make(engine, owner, card, count=1):
    made = engine.rules.create_token(owner, card, count)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    return made


def test_specs_are_fresh_valid_and_bind():
    first, second = specs_for(_holo()), specs_for(_holo())
    assert first[0] is not second[0] and sorted(s.ability_kind for s in first) == ["replacement", "triggered"]
    for spec in first:
        spec.validate()


@pytest.mark.parametrize("card", [
    synthesize_token_card("Treasure", subtypes=["Treasure"], is_artifact=True),
    synthesize_token_card("Goblin", power=1, toughness=1, colors=["R"], subtypes=["Goblin"]),
])
def test_any_token_becomes_an_illusion_artifact_creature(card):
    engine, p1, p2 = _board()
    made = _make(engine, "p1", card)
    assert len(made) == 1 and made[0].name == "Illusion"
    assert (made[0].power, made[0].toughness) == (ILLUSION_SIZE, ILLUSION_SIZE)
    assert made[0].is_creature and "artifact" in made[0].type_words and not made[0].card.color_identity


def test_the_number_of_tokens_is_preserved():
    engine, p1, p2 = _board()
    made = _make(engine, "p1", synthesize_token_card("Soldier", power=1, toughness=1, colors=["W"],
                                                     subtypes=["Soldier"]), count=3)
    assert len(made) == 3 and all(t.name == "Illusion" for t in made)


def test_opponents_tokens_are_unaffected():
    engine, p1, p2 = _board()
    (token,) = _make(engine, "p2", synthesize_token_card("Soldier", power=1, toughness=1, colors=["W"],
                                                         subtypes=["Soldier"]))
    assert token.name == "Soldier" and token.power == 1


def test_two_holo_engineers_do_not_replace_the_substitute_again():
    engine, p1, p2 = _board(holos=2)
    made = engine.rules.create_token("p1", synthesize_token_card("Clue", subtypes=["Clue"], is_artifact=True), 2)
    assert engine.state.pending_choice["kind"] == "replacement_order"  # RULE 616.1: the affected player orders them
    engine.resolve_pending_choice("0")
    engine.resolve_until_stable()
    illusions = [t for t in _tokens(engine) if t.name == "Illusion"]
    assert len(illusions) == 2 and not [t for t in _tokens(engine) if t.name != "Illusion"]


def test_without_holo_engineer_tokens_are_unchanged():
    engine, p1, p2 = _board(holos=0)
    (token,) = _make(engine, "p1", synthesize_token_card("Goblin", power=1, toughness=1, colors=["R"],
                                                         subtypes=["Goblin"]))
    assert token.name == "Goblin"


def test_its_own_enter_trigger_makes_exactly_one_illusion():
    engine, p1, p2 = game()
    obj = _put(engine, _holo(), Zone.HAND)
    cast(engine, p1, obj)
    illusions = [t for t in _tokens(engine) if t.name == "Illusion"]
    assert len(illusions) == 1 and (illusions[0].power, illusions[0].toughness) == (ILLUSION_SIZE, ILLUSION_SIZE)


def test_leaving_the_battlefield_stops_the_replacement():
    engine, p1, p2 = _board()
    holo = next(o for o in engine.state.battlefield if o.name == NAME)
    engine.rules.destroy(holo)
    engine.resolve_until_stable()
    (token,) = _make(engine, "p1", synthesize_token_card("Goblin", power=1, toughness=1, colors=["R"],
                                                         subtypes=["Goblin"]))
    assert token.name == "Goblin"
