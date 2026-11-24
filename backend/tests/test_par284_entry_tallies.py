"""PAR-284 milestone 14: entry replacements counted off a tally only the entry can read (RULE 614.1c).

"enters with a +1/+1 counter on it for each creature that died this turn", "... for each mana spent to cast it",
"... for each time you've cast your commander", "... for each other creature you control with a +1/+1 counter on it",
"... for each +1/+1 counter among other creatures you control" and Thief of Blood's remove-then-count pair."""
from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par284_counter_amounts import _board_creature, _enter
from tests.test_par284_this_way_windows import _card, _engine

DIED = "This creature enters with a +1/+1 counter on it for each creature that died this turn."
OWN_DIED = "This creature enters with a +1/+1 counter on it for each creature that died under your control this turn."
MANA = "This creature enters with a +1/+1 counter on it for each mana spent to cast it."
COMMANDER = ("This creature enters with 2 +1/+1 counters on it for each time you've cast your commander from the "
             "command zone this game.")
AVATAR = "This creature enters with a +1/+1 counter on it for each other creature you control with a +1/+1 counter on it."
ACOLYTE = "This creature enters with a +1/+1 counter on it for each +1/+1 counter among other creatures you control."
THIEF = ("As this creature enters, remove all counters from all permanents. This creature enters with a +1/+1 "
         "counter on it for each counter removed this way.")


@pytest.mark.parametrize("oracle", [DIED, OWN_DIED, MANA, COMMANDER, AVATAR, ACOLYTE, THIEF])
def test_entry_tallies_are_modeled(oracle):
    result = parse_oracle(_card("Probe", "Creature — Bear", oracle, is_creature=True, power=1, toughness=1))
    assert result.modeled, result.unclaimed


@pytest.mark.parametrize("oracle", [
    "This creature enters with a +1/+1 counter on it for each card revealed this way.",
    "This creature enters with a +1/+1 counter on it for each counter removed this way.",
    "As this creature enters, remove all counters from all permanents. This creature enters with a +1/+1 counter on "
    "it for each card revealed this way.",
])
def test_unfounded_this_way_tallies_stay_unclaimed(oracle):
    result = parse_oracle(_card("Probe", "Creature — Bear", oracle, is_creature=True, power=1, toughness=1))
    assert not result.modeled


def _probe(oracle):
    return _card("Probe", "Creature — Bear", oracle, is_creature=True, power=1, toughness=1)


def test_died_this_turn_counts_every_players_creatures():
    eng = _engine()
    for owner in ("p1", "p2"):
        victim = _board_creature(eng, _card(f"V{owner}", "Creature — Bear", is_creature=True, power=1, toughness=1), owner)
        eng.rules.destroy(victim)
    assert _enter(eng, _probe(DIED)).counters.get("+1/+1", 0) == 2


def test_died_under_your_control_counts_only_your_creatures():
    eng = _engine()
    for owner in ("p1", "p2", "p2"):
        victim = _board_creature(eng, _card("V", "Creature — Bear", is_creature=True, power=1, toughness=1), owner)
        eng.rules.destroy(victim)
    assert _enter(eng, _probe(OWN_DIED)).counters.get("+1/+1", 0) == 1


def test_mana_spent_to_cast_it_counts_the_payment():
    eng = _engine()
    card = Card(id="m", name="Mana Probe", type_line="Creature — Bear", mana_cost_string="{2}{G}", converted_mana_cost=3,
                oracle_text=MANA, is_creature=True, power=1, toughness=1)
    from mtg_analyzer.game.binding.core import attach_to_object
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, parse_oracle(card).specs)
    player = eng.state.players[0]
    player.hand.append(obj)
    player.mana_pool.add_many({"G": 1, "C": 2})
    eng.cast_spell(player, obj)
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD
    assert obj.counters.get("+1/+1", 0) == 3


def test_commander_casts_double_per_cast():
    eng = _engine()
    eng.state.players[0].commander_casts = {0: 2}
    assert _enter(eng, _probe(COMMANDER)).counters.get("+1/+1", 0) == 4


def test_avatar_counts_other_creatures_with_a_counter():
    eng = _engine()
    for name, counters in (("A", 1), ("B", 3), ("C", 0)):
        obj = _board_creature(eng, _card(name, "Creature — Bear", is_creature=True, power=1, toughness=1))
        if counters:
            obj.counters["+1/+1"] = counters
    assert _enter(eng, _probe(AVATAR)).counters.get("+1/+1", 0) == 2


def test_acolyte_sums_counters_among_other_creatures():
    eng = _engine()
    for name, counters in (("A", 1), ("B", 3), ("C", 0)):
        obj = _board_creature(eng, _card(name, "Creature — Bear", is_creature=True, power=1, toughness=1))
        if counters:
            obj.counters["+1/+1"] = counters
    assert _enter(eng, _probe(ACOLYTE)).counters.get("+1/+1", 0) == 4


def test_thief_of_blood_strips_every_counter_and_takes_them():
    eng = _engine()
    a = _board_creature(eng, _card("A", "Creature — Bear", is_creature=True, power=1, toughness=1))
    a.counters["+1/+1"] = 2
    land = _board_creature(eng, _card("L", "Land", is_land=True))
    land.counters["charge"] = 3
    thief = _enter(eng, _probe(THIEF))
    assert thief.counters.get("+1/+1", 0) == 5
    assert not a.counters.get("+1/+1") and not land.counters.get("charge")
