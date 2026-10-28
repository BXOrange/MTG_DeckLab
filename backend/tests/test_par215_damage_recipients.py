"""PAR-215 axis B: "<creature> deals damage equal to its power/toughness to <role recipient>".

Parse tests pin the spec; execution tests resolve real cards against the real engine (RULE 120.3 damage, RULE
608.2h last known power, RULE 109.5 "each other creature").
"""
import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from tests.support.deck_batch import answer, card, cast, filler, game


def _parse(text, type_line="Instant"):
    c = Card(id="x", name="Probe Card", type_line=type_line, oracle_text=text, is_instant="Instant" in type_line,
             is_creature="Creature" in type_line)
    return parse_oracle(c)


def _power_damage(result):
    return [e for s in result.specs for e in s.to_dict()["effects"] if e["type"] == "damage_equal_to_power"]


@pytest.mark.parametrize("text,params", [
    ("Tap target untapped creature. That creature deals damage equal to its power to its controller.",
     {"dealer_kind": "previous_target", "recipient": "dealer_controller"}),
    ("Put X +1/+1 counters on target creature you control. It deals damage equal to its power to each other creature.",
     {"dealer_kind": "previous_target", "selector": "each_other_creature"}),
    ("Target creature you control deals damage equal to its power to each other creature.",
     {"dealer_kind": "creature_you_control", "selector": "each_other_creature"}),
    ("Target creature an opponent controls deals damage equal to its power to that player.",
     {"dealer_kind": "creature_you_dont_control", "recipient": "dealer_controller"}),
])
def test_role_recipients_parse(text, params):
    result = _parse(text)
    assert result.modeled, result.unclaimed
    effect = _power_damage(result)[-1]["params"]
    assert {k: effect.get(k) for k in params} == params


@pytest.mark.parametrize("text", [
    # "that player" is only the dealer's controller for an opposing dealer
    "Target creature you control deals damage equal to its power to that player.",
    # a spell's power is not a creature on the battlefield
    "Counter target creature spell. Probe Card deals damage equal to that spell's power to its controller.",
])
def test_role_recipient_is_not_over_claimed(text):
    assert not _power_damage(_parse(text))


def test_backlash_damages_the_tapped_creatures_controller():
    eng = game(library=0)
    victim = filler(eng, "Ogre", player="p2", power=4, toughness=4)
    spell = card(eng, "Backlash", zone=Zone.HAND)
    life = eng.state.player_by_id("p2").life
    cast(eng, spell, targets=[victim])
    assert victim.tapped
    assert eng.state.player_by_id("p2").life == life - 4


def test_nova_flame_hits_every_other_creature_but_not_the_dealer():
    eng = game(library=0)
    mine = filler(eng, "Bear", power=2, toughness=9)
    other = filler(eng, "Wall", player="p2", power=0, toughness=9)
    spell = card(eng, "Nova Flame", zone=Zone.HAND)
    cast(eng, spell, targets=[mine], x=2)
    assert other.damage_marked == 4 and mine.damage_marked == 0


def test_dong_zhou_damages_the_opposing_creatures_controller():
    eng = game(library=0)
    victim = filler(eng, "Ogre", player="p2", power=3, toughness=3)
    life = eng.state.player_by_id("p2").life
    dong = card(eng, "Dong Zhou, the Tyrant", zone=Zone.HAND)
    cast(eng, dong)
    answer(eng)
    assert eng.state.player_by_id("p2").life == life - 3


def test_reanimated_creature_damages_every_other_creature_by_its_power():
    eng = game(library=0)
    bystander = filler(eng, "Wall", player="p2", power=0, toughness=20)
    dead = filler(eng, "Dead Giant", player="p2", power=5, toughness=9, zone=Zone.GRAVEYARD)
    spell = card(eng, "Too Greedily, Too Deep", zone=Zone.HAND)
    cast(eng, spell, targets=[dead])
    answer(eng)
    assert dead.zone == Zone.BATTLEFIELD and dead.damage_marked == 0
    assert bystander.damage_marked == 5


def test_traitors_roar_taps_and_damages_the_creatures_controller():
    eng = game(library=0)
    victim = filler(eng, "Ogre", player="p2", power=3, toughness=3)
    spell = card(eng, "Traitor's Roar", zone=Zone.HAND)
    life = eng.state.player_by_id("p2").life
    cast(eng, spell, targets=[victim])
    assert victim.tapped and eng.state.player_by_id("p2").life == life - 3
