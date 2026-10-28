"""PAR-215: "return target creature card with mana value X or less from your graveyard" (RULE 107.3, RULE 701.3).

X is the spell's announced X (Stir the Grave, Profane Command) or a "where X is ..." amount (Celestine, the Living
Saint). The ceiling is applied when the target is offered.
"""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import answer, card, cast, filler, game, step
from tests.test_par215_damage_recipients import _parse


@pytest.mark.parametrize("name", [
    "Stir the Grave", "Celestine, the Living Saint", "Unforgiving One", "Profane Command", "Guardian Scalelord",
])
def test_x_bound_graveyard_returns_are_modeled(name):
    from mtg_analyzer.parser.oracle import parse_oracle
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
    assert parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card(name)).modeled


def test_stir_the_grave_respects_announced_x():
    eng = game(library=0)
    cheap = filler(eng, "Cheap", mv=2, power=2, toughness=2, zone=Zone.GRAVEYARD)
    dear = filler(eng, "Dear", mv=4, power=4, toughness=4, zone=Zone.GRAVEYARD)
    spell = card(eng, "Stir the Grave", zone=Zone.HAND)
    from mtg_analyzer.game.targeting import legal_targets
    cast(eng, spell, targets=[cheap], x=2)
    assert cheap in eng.state.permanents() and dear not in eng.state.permanents()


def test_celestine_returns_by_life_gained_this_turn():
    eng = game(library=0)
    card(eng, "Celestine, the Living Saint")
    cheap = filler(eng, "Cheap", mv=3, power=2, toughness=2, zone=Zone.GRAVEYARD)
    dear = filler(eng, "Dear", mv=5, power=4, toughness=4, zone=Zone.GRAVEYARD)
    eng.rules.gain_life(eng.state.player_by_id("p1"), 3)
    step(eng, "end")
    answer(eng)
    assert cheap in eng.state.permanents() and dear not in eng.state.permanents()


def test_raise_the_past_returns_only_cheap_creatures():
    eng = game(library=0)
    cheap = filler(eng, "Cheap", mv=2, power=2, toughness=2, zone=Zone.GRAVEYARD)
    dear = filler(eng, "Dear", mv=3, power=3, toughness=3, zone=Zone.GRAVEYARD)
    spell = card(eng, "Raise the Past", zone=Zone.HAND)
    cast(eng, spell)
    assert cheap in eng.state.permanents() and dear not in eng.state.permanents()


def test_ascend_from_avernus_uses_announced_x_for_creatures_and_planeswalkers():
    eng = game(library=0)
    cheap = filler(eng, "Cheap", mv=2, power=2, toughness=2, zone=Zone.GRAVEYARD)
    walker = filler(eng, "Walker", type_line="Planeswalker", mv=3, zone=Zone.GRAVEYARD)
    dear = filler(eng, "Dear", mv=5, power=3, toughness=3, zone=Zone.GRAVEYARD)
    spell = card(eng, "Ascend from Avernus", zone=Zone.HAND)
    cast(eng, spell, x=3)
    assert cheap in eng.state.permanents() and walker in eng.state.permanents() and dear not in eng.state.permanents()


def test_proclamation_of_rebirth_takes_up_to_three_cheap_targets():
    eng = game(library=0)
    a = filler(eng, "A", mv=1, power=1, toughness=1, zone=Zone.GRAVEYARD)
    b = filler(eng, "B", mv=1, power=1, toughness=1, zone=Zone.GRAVEYARD)
    spell = card(eng, "Proclamation of Rebirth", zone=Zone.HAND)
    cast(eng, spell, targets=[a, b])
    assert a in eng.state.permanents() and b in eng.state.permanents()


def test_unmeasurable_where_x_ceiling_is_declined_not_left_as_a_placeholder():
    """"... mana value X or less, where X is the amount of mana spent" cannot be measured while the target is offered."""
    result = _parse(
        "Return target creature card with mana value X or less from your graveyard to the battlefield, where X is "
        "the amount of mana spent to cast this spell."
    )
    assert not result.modeled


def test_source_power_ceiling_uses_the_existing_sentinel():
    result = _parse(
        "Whenever ~ attacks, return target nonland permanent card with mana value X or less from your graveyard to "
        "the battlefield, where X is ~'s power.", "Creature",
    )
    assert result.modeled
    params = result.specs[0].to_dict()["effects"][0]["params"]
    assert params["max_mana_value"] == "source_power"
