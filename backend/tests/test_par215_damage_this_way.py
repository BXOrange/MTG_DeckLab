"""PAR-215 axis F: "the damage dealt this way" / "excess damage was dealt this way" (RULE 120.3, 120.4a, 608.2)."""
import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from tests.support.deck_batch import answer, card, cast, filler, game


def _parse(text):
    c = Card(id="x", name="Probe Card", type_line="Instant", oracle_text=text, is_instant=True)
    return parse_oracle(c)


def _flat(result):
    return [e for s in result.specs for e in s.to_dict()["effects"]]


@pytest.mark.parametrize("text,tally", [
    ("Probe Card deals 2 damage to each other player. You gain life equal to the damage dealt this way.",
     "damage_dealt_this_way"),
    ("Probe Card deals 4 damage to target creature. You gain life equal to the excess damage dealt this way.",
     "excess_damage_this_way"),
])
def test_life_gain_reads_the_damage_tally(text, tally):
    result = _parse(text)
    assert result.modeled, result.unclaimed
    bind = next(e for e in _flat(result) if e["type"] == "bind")
    assert bind["params"]["amount"] == {"kind": "this_way", "tally": tally}


def test_excess_damage_gate_is_a_tally_comparison():
    result = _parse("Probe Card deals 6 damage to target creature. If excess damage was dealt this way, draw a card.")
    assert result.modeled, result.unclaimed
    gated = [s for s in result.specs[0].effects if s.condition]
    assert gated and gated[0].condition["left"] == {"kind": "this_way", "tally": "excess_damage_this_way"}


def test_unknown_damage_phrases_stay_unclaimed():
    # "that much" with no prevention shield before it has no tally behind it (a shield's tally is the
    # `reflexive_damage` rider, test_par215_prevent_reflexive.py)
    assert not _parse("If damage is prevented this way, Probe Card deals that much damage to any target.").modeled


def test_syphon_soul_gains_what_every_opponent_lost_in_total():
    eng = game(players=3, library=3)
    cast(eng, card(eng, "Syphon Soul", zone=Zone.HAND))
    assert [p.life for p in eng.state.players] == [24, 18, 18]


def test_razor_rings_gains_only_the_excess_damage():
    eng = game(library=3)
    victim = filler(eng, "Ogre", player="p2", power=1, toughness=2)
    victim.attacking = True
    cast(eng, card(eng, "Razor Rings", zone=Zone.HAND), targets=[victim])
    assert eng.state.player_by_id("p1").life == 22


def test_orbital_plunge_makes_a_lander_only_on_excess_damage():
    for toughness, expect in ((2, ["Lander"]), (9, [])):
        eng = game(library=3)
        victim = filler(eng, "Ogre", player="p2", power=1, toughness=toughness)
        cast(eng, card(eng, "Orbital Plunge", zone=Zone.HAND), targets=[victim])
        answer(eng)
        assert [o.name for o in eng.state.battlefield if o.name == "Lander"] == expect


def test_corrupt_gains_life_equal_to_damage_actually_dealt():
    eng = game(library=3)
    for i in range(3):
        filler(eng, f"Swamp{i}", type_line="Basic Land — Swamp", mv=0)
    target = eng.state.player_by_id("p2")
    cast(eng, card(eng, "Corrupt", zone=Zone.HAND), targets=[target])
    assert target.life == 17 and eng.state.player_by_id("p1").life == 23
