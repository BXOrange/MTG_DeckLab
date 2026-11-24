"""ENG-68 -- granted Equip abilities (RULE 702.6, 113.6, 613.6).

"Clues you control are Equipment in addition to their other types and have "Equipped creature gets +2/+0" and equip {2}."
(Armed with Proof, Arterial Alchemy, Dan Lewis, Gemcutter Buccaneer, Bram, Baguette Brawler, Bludgeon Brawl): the group
becomes Equipment, gains the quoted static and a real Equip activated ability per object, and stops being any of it the
moment the source leaves or the object becomes a creature.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.game.catalogue.cards.test_miracle_worker_deck import _card, _filler, _game
from tests.support.card_cache import get_cached_card

SIX = ["Armed with Proof", "Arterial Alchemy", "Dan Lewis", "Gemcutter Buccaneer", "Bram, Baguette Brawler", "Bludgeon Brawl"]


@pytest.mark.parametrize("name", SIX)
def test_the_six_cards_are_modeled(name):
    assert parse_oracle(get_cached_card(name)).modeled


def _equip_abilities(obj):
    return [a for a in obj.granted_activated_abilities if getattr(a, "attach_kind", None) == "equip"]


def _bear(engine, player="p1", subtype="Bear"):
    return _filler(engine, f"{subtype} {player}", f"Creature — {subtype}", player=player, power=2, toughness=2)


def _power(engine, obj):
    engine.recompute_continuous_effects()
    return obj.power


def _equip(engine, player, equipment, host, index=0):
    engine.state.current_step = "main1"
    engine.activate_ability(engine.state.player_by_id(player), equipment, ability_index=index, targets=[host])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def test_armed_with_proof_makes_only_your_clues_equipment_with_equip_two():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Armed with Proof")
    clue = _filler(engine, "Clue", "Artifact — Clue")
    theirs = _filler(engine, "Clue", "Artifact — Clue", player="p2")
    rock = _filler(engine, "Rock", "Artifact")
    bear = _bear(engine)
    engine.recompute_continuous_effects()

    assert clue.has_subtype("equipment") and not theirs.has_subtype("equipment") and not rock.has_subtype("equipment")
    [equip] = _equip_abilities(clue)
    assert equip.cost.attach_kind == "equip" and equip.cost.sorcery_speed_only
    assert "{2}" in equip.description
    assert _equip_abilities(theirs) == [] and _equip_abilities(rock) == []

    p1.mana_pool.add_many({"R": 2})
    base = _power(engine, bear)
    _equip(engine, "p1", clue, bear, index=0)
    assert clue.attached_to == bear.instance_id
    assert p1.mana_pool.total() == 0  # the granted cost was really paid
    assert _power(engine, bear) == base + 2  # the granted "Equipped creature gets +2/+0"


def test_grant_ends_with_its_source_and_the_clue_falls_off():
    engine = _game()
    p1 = engine.state.players[0]
    proof = _card(engine, "Armed with Proof")
    clue = _filler(engine, "Clue", "Artifact — Clue")
    bear = _bear(engine)
    engine.recompute_continuous_effects()
    p1.mana_pool.add_many({"R": 2})
    _equip(engine, "p1", clue, bear)
    assert clue.attached_to == bear.instance_id

    engine.rules.destroy(proof)
    engine.rules.check_state_based_actions()
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    # RULE 704.5n: no longer an Equipment, so it unattaches and stays on the battlefield.
    assert not clue.has_subtype("equipment") and clue.attached_to is None and clue in engine.state.battlefield
    assert _equip_abilities(clue) == []


def test_dan_lewis_skips_equipment_and_creatures_and_keeps_the_grant_after_the_type_is_added():
    engine = _game()
    _card(engine, "Dan Lewis")
    rock = _filler(engine, "Rock", "Artifact")
    sword = _filler(engine, "Sword", "Artifact — Equipment")
    golem = _filler(engine, "Golem", "Artifact Creature — Golem", power=2, toughness=2)
    for _ in range(3):  # the layer-6 grants must not vanish once the layer-4 part made the rock an Equipment
        engine.recompute_continuous_effects()
        assert rock.has_subtype("equipment") and len(_equip_abilities(rock)) == 1
    assert _equip_abilities(sword) == [] and _equip_abilities(golem) == []
    assert not golem.has_subtype("equipment")


def test_gemcutter_buccaneer_grants_two_equip_abilities_and_the_pirate_one_only_targets_pirates():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Gemcutter Buccaneer")
    treasure = _filler(engine, "Treasure", "Artifact — Treasure")
    bear = _bear(engine)
    pirate = _bear(engine, subtype="Pirate")
    engine.recompute_continuous_effects()
    abilities = _equip_abilities(treasure)
    assert sorted(a.description for a in abilities) == ["Equip Pirate {1}", "Equip {3}"]

    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 4})
    equips = [a for a in engine.legal_actions(p1)
              if a.get("type") == "activate_ability" and a["instance_id"] == treasure.instance_id]
    assert len(equips) == 2
    by_label = {a["description"]: {o["name"] for o in a["targets"][0]["options"]} for a in equips}
    assert by_label["Equip Pirate {1}"] == {"Gemcutter Buccaneer", pirate.name}  # RULE 702.6a: Pirates only
    assert bear.name in by_label["Equip {3}"]
    pirate_ability = next(i for i, a in enumerate(treasure.activated_abilities + treasure.granted_activated_abilities)
                          if a.description == "Equip Pirate {1}")
    _equip(engine, "p1", treasure, pirate, index=pirate_ability)
    assert treasure.attached_to == pirate.instance_id
    assert bear.power == 2 and _power(engine, pirate) == 4  # +2/+0


def test_bram_makes_noncreature_food_equipment_with_equip_one_and_plus_one_plus_one():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Bram, Baguette Brawler")
    food = _filler(engine, "Food", "Artifact — Food")
    bear = _bear(engine)
    engine.recompute_continuous_effects()
    assert food.has_subtype("equipment") and food.has_subtype("food")
    p1.mana_pool.add_many({"G": 1})
    _equip(engine, "p1", food, bear)
    engine.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (3, 3)


def test_bludgeon_brawl_equip_cost_and_bonus_are_the_artifacts_mana_value():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Bludgeon Brawl")
    rock = _filler(engine, "Rock", "Artifact", mv=3)
    bear = _bear(engine)
    engine.recompute_continuous_effects()
    [equip] = _equip_abilities(rock)
    assert "{3}" in equip.description
    p1.mana_pool.add_many({"R": 3})
    _equip(engine, "p1", rock, bear)
    assert rock.attached_to == bear.instance_id and p1.mana_pool.total() == 0
    assert _power(engine, bear) == 5  # 2 + X where X is the artifact's mana value


def test_an_equipment_that_is_also_a_creature_cannot_be_attached():
    """RULE 301.5c: the grant's own group excludes creatures, and the attach check refuses one that became a creature."""
    engine = _game()
    _card(engine, "Armed with Proof")
    clue = _filler(engine, "Clue", "Artifact — Clue")
    bear = _bear(engine)
    engine.recompute_continuous_effects()
    clue.card.is_creature = True
    engine.recompute_continuous_effects()
    assert not engine.rules.attach_to_target(clue, bear)


# -- plain group grants: "Equipment you control have equip {N}" / "Vehicles you control have crew N" ---------------------


@pytest.mark.parametrize("name", ["Astor, Bearer of Blades", "Syr Gwyn, Hero of Ashvale"])
def test_plain_group_grants_are_modeled(name):
    assert parse_oracle(get_cached_card(name)).modeled


def test_astor_grants_equip_one_next_to_the_printed_equip():
    engine = _game()
    p1 = engine.state.players[0]
    astor = _card(engine, "Astor, Bearer of Blades")
    sword = _card(engine, "Sword of Fire and Ice")  # printed Equip {2}
    bear = _bear(engine)
    engine.recompute_continuous_effects()
    assert [a.cost.raw for a in sword.activated_abilities if a.attach_kind == "equip"] == ["{2}"]
    [granted] = _equip_abilities(sword)
    assert "{1}" in granted.description

    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 2})
    offered = {a["cost_label"] for a in engine.legal_actions(p1)
               if a.get("type") == "activate_ability" and a["instance_id"] == sword.instance_id}
    assert offered == {"{1}", "{2}"}  # both the printed and the granted Equip (RULE 113.2c)
    index = len(sword.activated_abilities)
    _equip(engine, "p1", sword, bear, index=index)
    assert sword.attached_to == bear.instance_id and p1.mana_pool.total() == 1  # paid {1}, not {2}

    engine.rules.destroy(astor)
    engine.rules.check_state_based_actions()
    engine.recompute_continuous_effects()
    assert _equip_abilities(sword) == []  # the grant left with its source


def test_syr_gwyn_grants_equip_knight_zero_only_attaching_to_knights():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Syr Gwyn, Hero of Ashvale")  # a Knight itself
    sword = _filler(engine, "Sword", "Artifact — Equipment")
    bear = _bear(engine)
    knight = _bear(engine, subtype="Knight")
    engine.recompute_continuous_effects()
    [granted] = _equip_abilities(sword)
    assert granted.description == "Equip Knight {0}"
    engine.state.current_step = "main1"
    [action] = [a for a in engine.legal_actions(p1)
                if a.get("type") == "activate_ability" and a["instance_id"] == sword.instance_id]
    names = {o["name"] for o in action["targets"][0]["options"]}
    assert knight.name in names and bear.name not in names
    _equip(engine, "p1", sword, knight, index=len(sword.activated_abilities))
    assert sword.attached_to == knight.instance_id


def test_astor_grants_crew_one_to_vehicles_beside_a_printed_crew():
    engine = _game()
    astor = _card(engine, "Astor, Bearer of Blades")
    vehicle = _card(engine, "Heart of Kiran")  # printed Crew 3
    pilot = _filler(engine, "Pilot", "Creature — Human", power=1, toughness=1)
    engine.recompute_continuous_effects()
    crews = [a for a in vehicle.activated_abilities + vehicle.granted_activated_abilities
             if getattr(a.cost, "crew_power", None)]
    assert sorted(a.cost.crew_power for a in crews) == [1, 3]
    index = next(i for i, a in enumerate(vehicle.activated_abilities + vehicle.granted_activated_abilities)
                 if getattr(a.cost, "crew_power", None) == 1)
    engine.state.current_step = "main1"
    engine.activate_ability(engine.state.players[0], vehicle, index)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert vehicle.is_creature and (pilot.tapped or astor.tapped)  # one power crewed it through the granted Crew 1
