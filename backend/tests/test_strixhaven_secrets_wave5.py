"""Secrets of Strixhaven — playability batch, wave 5.

Wave 5 / MEC-77: RULE 508.1g **attack tax** — "Creatures can't attack you
unless their controller pays {N} for each creature they control that's
attacking you." (Propaganda / Ghostly Prison / Windborn Muse). New
`EffectRegistry` "attack_tax" marker static + `continuous.attack_tax_per_
creature_for`, enforced (auto-paid) in `combat_mixin.declare_attackers`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


@pytest.mark.parametrize("name", ["Ghostly Prison", "Propaganda", "Windborn Muse"])
def test_attack_tax_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, (name, r.unclaimed)
    static = [s for s in r.specs if s.ability_kind == "static"][0]
    assert static.effects[0].type == "attack_tax"
    assert static.effects[0].params["amount"] == 2


@pytest.mark.parametrize(
    ("name", "selector", "scope"),
    [
        ("Collective Restraint", "basic_land_types_among_lands_you_control", "player"),
        ("Sphere of Safety", "enchantments_you_control", "player_or_planeswalker"),
    ],
)
def test_x_scaled_attack_tax_variants_are_modeled(name, selector, scope):
    c = _db().get_card(name)
    if c is None:
        pytest.skip(f"{name} not cached")
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, (name, r.unclaimed)
    static = [s for s in r.specs if s.ability_kind == "static"][0]
    assert static.effects[0].params == {
        "amount_count_selector": selector, "defender_scope": scope,
    }


def _combat_engine():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    gp = GameObject(_db().get_card("Ghostly Prison"), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    gp.controller_id = p1.id
    eng.state.add_to_battlefield(gp)
    bind_from_catalogue(gp)
    eng.recompute_continuous_effects()
    eng.state.active_player_index = 1
    eng.state.current_step = "declare_attackers"
    return eng, p1, p2


def _bear(eng, pid, name="Bear"):
    o = GameObject(Card(id=name, name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    o.summoning_sick = False
    eng.state.add_to_battlefield(o)
    return o


def _permanent(eng, pid, name, type_line, **card_flags):
    o = GameObject(Card(id=name, name=name, type_line=type_line, **card_flags),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


def test_attack_tax_helper_scoped_to_static_controller():
    eng, p1, p2 = _combat_engine()
    assert continuous.attack_tax_per_creature_for(eng.state, p1.id) == 2
    assert continuous.attack_tax_per_creature_for(eng.state, p2.id) == 0


def test_cannot_declare_attacker_without_paying_the_tax():
    eng, p1, p2 = _combat_engine()
    atk = _bear(eng, p2.id)
    with pytest.raises(ValueError, match="attack tax"):
        eng.declare_attackers(p2, [{"attacker": atk, "defender": {"kind": "player", "id": p1.id}}])
    assert not atk.attacking


def test_declares_after_paying_the_tax_from_pool():
    eng, p1, p2 = _combat_engine()
    atk = _bear(eng, p2.id)
    p2.mana_pool.add_many({"C": 2})
    eng.declare_attackers(p2, [{"attacker": atk, "defender": {"kind": "player", "id": p1.id}}])
    assert atk.attacking
    assert p2.mana_pool.total() == 0


def test_tax_scales_with_number_of_attackers():
    eng, p1, p2 = _combat_engine()
    a1, a2 = _bear(eng, p2.id, "Bear1"), _bear(eng, p2.id, "Bear2")
    p2.mana_pool.add_many({"C": 3})  # need {4}, only have {3}
    with pytest.raises(ValueError, match="attack tax"):
        eng.declare_attackers(p2, [
            {"attacker": a1, "defender": {"kind": "player", "id": p1.id}},
            {"attacker": a2, "defender": {"kind": "player", "id": p1.id}},
        ])
    p2.mana_pool.add_many({"C": 1})  # now {4}
    eng.declare_attackers(p2, [
        {"attacker": a1, "defender": {"kind": "player", "id": p1.id}},
        {"attacker": a2, "defender": {"kind": "player", "id": p1.id}},
    ])
    assert a1.attacking and a2.attacking


def test_player_can_decline_attack_tax_without_spending_mana():
    eng, p1, p2 = _combat_engine()
    atk = _bear(eng, p2.id)
    p2.mana_pool.add_many({"C": 2})
    with pytest.raises(ValueError, match="attack tax declined"):
        eng.declare_attackers(p2, [{
            "attacker": atk,
            "defender": {"kind": "player", "id": p1.id},
            "pay_attack_tax": False,
        }])
    assert not atk.attacking
    assert p2.mana_pool.total() == 2


def test_collective_restraint_counts_distinct_basic_land_types():
    eng, p1, _p2 = _combat_engine()
    gp = next(o for o in eng.state.battlefield if o.name == "Ghostly Prison")
    eng.state.battlefield.remove(gp)
    restraint = GameObject(_db().get_card("Collective Restraint"), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    restraint.controller_id = p1.id
    eng.state.add_to_battlefield(restraint)
    bind_from_catalogue(restraint)
    _permanent(eng, p1.id, "Tundra", "Land — Plains Island", is_land=True)
    _permanent(eng, p1.id, "Forest", "Land — Forest", is_land=True)
    eng.recompute_continuous_effects()
    assert continuous.attack_tax_per_creature_for(eng.state, p1.id) == 3


def test_sphere_of_safety_taxes_attacks_on_its_controllers_planeswalker():
    eng, p1, p2 = _combat_engine()
    gp = next(o for o in eng.state.battlefield if o.name == "Ghostly Prison")
    eng.state.battlefield.remove(gp)
    sphere = GameObject(_db().get_card("Sphere of Safety"), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    sphere.controller_id = p1.id
    eng.state.add_to_battlefield(sphere)
    bind_from_catalogue(sphere)
    walker = _permanent(eng, p1.id, "Test Walker", "Planeswalker — Test")
    eng.recompute_continuous_effects()
    atk = _bear(eng, p2.id)
    attack_action = next(
        action for action in eng.legal_actions(p2)
        if action["type"] == "attack" and action["instance_id"] == atk.instance_id
    )
    walker_index = next(
        index for index, defender in enumerate(attack_action["legal_defenders"])
        if defender["kind"] == "planeswalker" and defender["instance_id"] == walker.instance_id
    )
    assert attack_action["attack_tax_amounts"][walker_index] == 1
    with pytest.raises(ValueError, match="attack tax"):
        eng.declare_attackers(p2, [{
            "attacker": atk,
            "defender": {"kind": "planeswalker", "instance_id": walker.instance_id},
        }])
