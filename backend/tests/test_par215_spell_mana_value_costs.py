"""PAR-215: "spells you cast with mana value N or greater cost {1} less to cast" (RULE 202.3, RULE 601.2f).

Also pins the colorless-spell discount (Herald of Kozilek), which used to match no spell at all because the parser's
colour symbol ``C`` was compared against a colour set.
"""
import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game
from tests.test_par215_damage_recipients import _parse


def _reduction(eng, spell):
    return continuous.cost_reduction_for(eng.state, eng.state.player_by_id("p1"), spell)[0]


@pytest.mark.parametrize("text,key,value", [
    ("Spells you cast with mana value 5 or greater cost {1} less to cast.", "spell_min_mana_value", 5),
    ("Creature spells you cast with mana value 6 or greater cost {2} less to cast.", "spell_min_mana_value", 6),
])
def test_mana_value_bound_parses(text, key, value):
    result = _parse(text, "Creature")
    assert result.modeled
    params = result.specs[0].to_dict()["effects"][0]["params"]
    assert params[key] == value


def test_spectacle_mage_discounts_only_big_multicolored_spells():
    eng = game(library=0)
    card(eng, "Spectacle Mage", zone=Zone.BATTLEFIELD)
    big = card(eng, "Wurmcoil Engine", zone=Zone.HAND)
    small = card(eng, "Sol Ring", zone=Zone.HAND)
    assert _reduction(eng, big) == 0  # Wurmcoil is neither an instant nor a sorcery
    assert _reduction(eng, small) == 0


def test_krosan_drover_discounts_creature_spells_of_mana_value_six():
    eng = game(library=0)
    card(eng, "Krosan Drover", zone=Zone.BATTLEFIELD)
    big = card(eng, "Wurmcoil Engine", zone=Zone.HAND)  # mana value 6
    small = card(eng, "Grizzly Bears", zone=Zone.HAND)
    assert _reduction(eng, big) == 2 and _reduction(eng, small) == 0


def test_colorless_discount_applies_to_colorless_spells():
    eng = game(library=0)
    card(eng, "Herald of Kozilek", zone=Zone.BATTLEFIELD)
    colorless = card(eng, "Sol Ring", zone=Zone.HAND)
    colored = card(eng, "Grizzly Bears", zone=Zone.HAND)
    assert _reduction(eng, colorless) == 1 and _reduction(eng, colored) == 0
