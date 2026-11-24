"""PAR-284 milestone 13: counters on "that creature" and "enters with ... for each / where X is" counts (RULE 122.1, 608.2h, 614.1c).

Pinned: "the number of counters on that creature" reads the earlier clause's pick (last-known counters once it died), and
a self entry replacement counted off a selector the shared grammar reads is `enters_with_counters_count`; a quantity
outside that grammar (mana spent, a prior clause's tally) stays unclaimed.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par284_this_way_windows import _card, _engine

PARTING = ("Destroy target creature. You draw X cards and you lose X life, where X is the number of counters on that "
           "creature.")
KINSBAILE = "This creature enters with a +1/+1 counter on it for each other Kithkin you control."


@pytest.mark.parametrize("oracle", [
    PARTING,
    "Destroy target creature. You gain life equal to the number of counters on that creature.",
    "Exile target creature. Draw a card for each counter on that creature.",
])
def test_counters_on_that_creature_are_modeled(oracle):
    result = parse_oracle(_card("Probe", "Instant", oracle, is_instant=True))
    assert result.modeled, result.unclaimed


def test_that_creature_without_an_antecedent_is_unclaimed():
    result = parse_oracle(_card("Probe", "Instant", "Draw a card for each counter on that creature.", is_instant=True))
    assert not result.modeled


@pytest.mark.parametrize("oracle", [
    KINSBAILE,
    "This creature enters with X +1/+1 counters on it, where X is the number of other creatures on the battlefield.",
    "This creature enters with a number of +1/+1 counters on it equal to the number of creature cards in your graveyard.",
    "This creature enters with 2 +1/+1 counters on it for each other nontoken Human you control.",
])
def test_entry_counter_counts_are_modeled(oracle):
    result = parse_oracle(_card("Probe", "Creature — Kithkin", oracle, is_creature=True, power=1, toughness=1))
    assert result.modeled, result.unclaimed


@pytest.mark.parametrize("oracle", [
    "This creature enters with a +1/+1 counter on it for each card revealed this way.",
])
def test_entry_counter_counts_outside_the_selector_grammar_stay_unclaimed(oracle):
    result = parse_oracle(_card("Probe", "Creature — Kithkin", oracle, is_creature=True, power=1, toughness=1))
    assert not result.modeled


def _board_creature(eng, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    eng.state.battlefield.append(obj)
    return obj


def test_parting_thoughts_draws_and_loses_the_destroyed_creatures_counters():
    eng = _engine()
    p1 = eng.state.players[0]
    for i in range(5):
        p1.library.append(GameObject(_card(f"L{i}", "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    victim = _board_creature(eng, _card("Victim", "Creature — Bear", is_creature=True, power=2, toughness=2), "p2")
    victim.counters["+1/+1"] = 3
    card = _card("Parting Probe", "Instant", PARTING, is_instant=True)
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(spell, parse_oracle(card).specs)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, spell, targets=[victim])
    eng.resolve_until_stable()
    assert victim not in eng.state.battlefield
    assert p1.life == 20 - 3
    assert len(p1.hand) == 3


def _enter(eng, card, owner="p1"):
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    player = eng.state.players[0]
    player.hand.append(obj)
    player.mana_pool.add_many({"C": 1})
    eng.cast_spell(player, obj)
    eng.resolve_until_stable()
    return obj


def test_kinsbaile_enters_with_a_counter_per_other_kithkin():
    eng = _engine()
    for name in ("K1", "K2"):
        _board_creature(eng, _card(name, "Creature — Kithkin", is_creature=True, power=1, toughness=1))
    _board_creature(eng, _card("Bear", "Creature — Bear", is_creature=True, power=1, toughness=1))
    guard = _enter(eng, _card("Guard Probe", "Creature — Kithkin", KINSBAILE, is_creature=True, power=1, toughness=1))
    assert guard.zone == Zone.BATTLEFIELD
    assert guard.counters.get("+1/+1", 0) == 2  # itself is not an "other" Kithkin, the Bear is not a Kithkin


def test_a_multiplied_entry_count_scales_the_per_unit_amount():
    eng = _engine()
    _board_creature(eng, _card("H1", "Creature — Human", is_creature=True, power=1, toughness=1))
    obj = _enter(eng, _card("Hamlet Probe", "Creature — Human",
                            "This creature enters with 2 +1/+1 counters on it for each other nontoken Human you control.",
                            is_creature=True, power=1, toughness=1))
    assert obj.counters.get("+1/+1", 0) == 2


def test_a_planeswalker_enters_with_loyalty_counters_per_land():
    # Dakkon, Shadow Slayer prints its loyalty as "*"; the replacement supplies it, counting lands as it enters.
    eng = _engine()
    for i in range(3):
        _board_creature(eng, _card(f"Land{i}", "Basic Land — Plains", is_land=True))
    walker = _enter(eng, _card(
        "Walker Probe", "Legendary Planeswalker — Dakkon",
        "This planeswalker enters with a number of loyalty counters on it equal to the number of lands you control.",
        ))
    assert walker.zone == Zone.BATTLEFIELD
    assert walker.counters.get("loyalty", 0) == 3
