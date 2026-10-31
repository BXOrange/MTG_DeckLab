"""PAR-215 axis B: several creatures each deal damage equal to their power to one recipient.

"Up to two target creatures you control each deal damage equal to their power to target creature an opponent
controls." (Band Together family) announces the dealers as one requirement and the recipient as the last pick;
"they each deal damage ..." reuses the preceding clause's targets (Coordinated Clobbering, Terrific Team-Up).
RULE 115.1a (N targets), RULE 120.1 (simultaneous damage), RULE 608.2b (illegal recipient).
"""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game
from tests.test_par215_damage_recipients import _parse, _power_damage


@pytest.mark.parametrize("name", [
    "Allies at Last", "Band Together", "Common Goal", "Coordinated Clobbering", "Terrific Team-Up",
])
def test_multi_dealer_cards_are_modeled(name):
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
    from mtg_analyzer.parser.oracle import parse_oracle
    assert parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card(name)).modeled


def test_multi_dealer_spec_shape():
    spec = _power_damage(_parse(
        "Up to two target creatures you control each deal damage equal to their power to another target creature."
    ))[0]["params"]
    assert spec["dealer_kind"] == "creature_you_control" and spec["dealer_count"] == 2
    assert spec["dealer_optional"] and spec["distinct"]


def test_declinable_recipient_is_not_claimed():
    assert not _power_damage(_parse(
        "Two target creatures you control each deal damage equal to their power to up to one target creature."
    ))


def test_band_together_both_dealers_hit_the_recipient():
    eng = game(library=0)
    a = filler(eng, "Bear", power=2, toughness=2)
    b = filler(eng, "Ogre", power=3, toughness=3)
    victim = filler(eng, "Wall", player="p2", power=0, toughness=9)
    spell = card(eng, "Band Together", zone=Zone.HAND)
    cast(eng, spell, targets=[a, b, victim])
    assert victim.damage_marked == 5 and a.damage_marked == 0


def test_band_together_with_one_dealer_picked():
    eng = game(library=0)
    a = filler(eng, "Bear", power=2, toughness=2)
    victim = filler(eng, "Wall", player="p2", power=0, toughness=9)
    spell = card(eng, "Band Together", zone=Zone.HAND)
    cast(eng, spell, targets=[a, None, victim])
    assert victim.damage_marked == 2


def test_coordinated_clobbering_taps_then_both_deal_damage():
    eng = game(library=0)
    a = filler(eng, "Bear", power=2, toughness=2)
    b = filler(eng, "Ogre", power=3, toughness=3)
    victim = filler(eng, "Wall", player="p2", power=0, toughness=9)
    spell = card(eng, "Coordinated Clobbering", zone=Zone.HAND)
    cast(eng, spell, targets=[a, b, victim], groups=[[a, b], [victim]])
    assert a.tapped and b.tapped and victim.damage_marked == 5


def test_terrific_team_up_pumps_before_damage():
    eng = game(library=0)
    a = filler(eng, "Bear", power=2, toughness=2)
    victim = filler(eng, "Wall", player="p2", power=0, toughness=9)
    spell = card(eng, "Terrific Team-Up", zone=Zone.HAND)
    cast(eng, spell, targets=[a, victim])
    assert victim.damage_marked == 3
