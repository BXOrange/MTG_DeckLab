"""PAR-284 milestone 21: "counters removed this way" after an activation's own "remove all <kind> counters" cost.

RULE 602.2b: the cost is paid as the ability is activated, so its count is stamped on the source
(`GameObject.counters_removed_as_cost`) and read back by the `counters_removed_as_cost` amount. The gate only admits that
amount in an activated ability whose cost text removes counters (`gate._counters_removed_amounts_ok`).
"""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par284_counter_amounts import _board_creature
from tests.test_par284_this_way_windows import _card, _engine

BOTTLE = "{T}, Remove all elixir counters from Essence Bottle: You gain 2 life for each elixir counter removed this way."
CATTI = ("{1}, Remove all +1/+1 counters from Catti-brie: It deals X damage to target attacking or blocking creature an opponent "
         "controls, where X is the number of counters removed this way.")
VISH = "Remove all +1/+1 counters from Vish Kal: Target creature gets -1/-1 until end of turn for each +1/+1 counter removed this way."
NEXUS = ("Whenever a player casts an instant or sorcery spell, put a number of charge counters on Geometric Nexus equal to that spell's "
         "mana value.\n{6}, {T}, Remove all charge counters from Geometric Nexus: Create a 0/0 green and blue Fractal creature token. "
         "Put X +1/+1 counters on it, where X is the number of charge counters removed this way.")


@pytest.mark.parametrize("name, type_line, oracle", [
    ("Essence Bottle", "Artifact", BOTTLE), ("Catti-brie", "Creature — Bear", CATTI),
    ("Vish Kal", "Creature — Bear", VISH), ("Geometric Nexus", "Artifact", NEXUS),
])
def test_cost_removed_cards_are_modeled(name, type_line, oracle):
    creature = "Creature" in type_line
    assert parse_oracle(_card(name, type_line, oracle, is_creature=creature,
                              power=1 if creature else None, toughness=1 if creature else None)).modeled


@pytest.mark.parametrize("oracle", [
    # no cost removes anything: the phrase has no tally to read
    "{T}: You gain 2 life for each elixir counter removed this way.",
    # a trigger has no activation payment
    "Whenever ~ attacks, you gain 2 life for each elixir counter removed this way.",
    # the cost removes another kind
    "{T}, Remove all charge counters from ~: You gain 2 life for each elixir counter removed this way.",
])
def test_removed_amount_without_a_matching_cost_stays_unclaimed(oracle):
    assert not parse_oracle(_card("Probe", "Artifact", oracle)).modeled


def _board(eng, name, type_line, oracle, counters, owner="p1", power=2, toughness=2):
    card = _card(name, type_line, oracle, is_creature="Creature" in type_line,
                 power=power if "Creature" in type_line else None, toughness=toughness if "Creature" in type_line else None)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.counters.update(counters)
    attach_to_object(obj, result.specs)
    eng.state.add_to_battlefield(obj)
    return obj


def test_essence_bottle_gains_two_life_per_counter_removed():
    eng = _engine()
    p1 = eng.state.players[0]
    bottle = _board(eng, "Essence Bottle", "Artifact", BOTTLE, {"elixir": 3})
    eng.activate_ability(p1, bottle, 0)
    eng.resolve_until_stable()
    assert bottle.counters.get("elixir", 0) == 0
    assert p1.life == 20 + 6


def test_catti_brie_deals_damage_equal_to_the_counters_removed():
    eng = _engine()
    p1 = eng.state.players[0]
    src = _board(eng, "Catti-brie", "Creature — Bear", CATTI, {"+1/+1": 3})
    victim = _board_creature(eng, _card("Big", "Creature — Bear", is_creature=True, power=2, toughness=9), "p2")
    victim.attacking = True  # RULE 506.4: attacking creature
    p1.mana_pool.add_many({"C": 1})
    eng.activate_ability(p1, src, 0, targets=[victim])
    eng.resolve_until_stable()
    assert src.counters.get("+1/+1", 0) == 0
    assert victim.damage_marked == 3


def test_vish_kal_shrinks_by_the_counters_removed():
    eng = _engine()
    p1 = eng.state.players[0]
    src = _board(eng, "Vish Kal", "Creature — Vampire", VISH, {"+1/+1": 4})
    victim = _board_creature(eng, _card("Big", "Creature — Bear", is_creature=True, power=9, toughness=9), "p2")
    eng.activate_ability(p1, src, 0, targets=[victim])
    eng.resolve_until_stable()
    assert (victim.power, victim.toughness) == (5, 5)


def test_geometric_nexus_charges_by_spell_mana_value_then_spends_them_on_a_fractal():
    eng = _engine()
    p1 = eng.state.players[0]
    nexus = _board(eng, "Geometric Nexus", "Artifact", NEXUS, {"charge": 2})
    p1.mana_pool.add_many({"C": 6})
    eng.activate_ability(p1, nexus, 0)
    eng.resolve_until_stable()
    assert nexus.counters.get("charge", 0) == 0
    token = next(o for o in eng.state.battlefield if o.card.name.startswith("Fractal"))
    eng.recompute_continuous_effects()
    assert token.counters.get("+1/+1") == 2
    # the first ability charges by the cast spell's mana value (RULE 601.2i)
    spell = _card("Cantrip", "Instant", "You gain 1 life.", mv=3, is_instant=True)
    spell.mana_cost_string = "{2}{U}"
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, parse_oracle(spell).specs)
    p1.hand.append(obj)
    p1.mana_pool.add_many({"U": 1, "C": 2})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert nexus.counters.get("charge", 0) == 3
